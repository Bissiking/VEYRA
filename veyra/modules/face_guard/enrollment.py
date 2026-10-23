# veyra/modules/face_guard/enrollment.py
"""Enrôlement du profil biométrique unique autorisé (V0.1).

Flux :
1. l'utilisateur lance l'enrôlement depuis la GUI Presence ;
2. ``EnrollmentSession`` récolte des empreintes sur plusieurs frames
   (orientation du visage suivie par l'écart des yeux dans l'image) ;
3. les empreintes sont moyennées puis L2-normalisées -> empreinte de référence ;
4. l'empreinte est chiffrée (``BiometricVault``) et stockée dans SQLite ;
5. les images sont détruites à chaque itération (jamais persistées).

Si le coffre de clés plateforme est indisponible, l'enrôlement échoue
EXPLICITEMENT (pas de stockage en clair, pas de fallback silencieux).
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum

import numpy as np

from veyra.core.events import Event, EventBus, EventType
from veyra.core.policy import SecurityPolicy
from veyra.modules.face_guard.pipeline import FacePipeline
from veyra.storage.biometrics import BiometricVault, KeyStorageError
from veyra.storage.database import Database

logger = logging.getLogger(__name__)

PROFILE_USER_KEY = "owner"  # V0.1 : un seul profil autorisé


class EnrollmentStage(str, Enum):
    IDLE = "IDLE"
    NEED_FACE = "NEED_FACE"
    CAPTURING = "CAPTURING"
    MOVING = "MOVING"          # demande de changer d'angle
    SAVING = "SAVING"
    DONE = "DONE"
    FAILED = "FAILED"


@dataclass
class EnrollmentProgress:
    stage: EnrollmentStage
    captured: int
    target: int
    message: str = ""
    orientation_hint: str = ""

    @property
    def fraction(self) -> float:
        return self.captured / self.target if self.target else 0.0


@dataclass
class EnrollmentSession:
    """Récolte multi-angles pilotée par la GUI (un thread à la fois)."""

    policy: SecurityPolicy
    pipeline: FacePipeline | None  # renseigné après chargement du FaceGuard
    vault: BiometricVault
    db: Database
    bus: EventBus

    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _thread: threading.Thread | None = field(default=None, repr=False)
    _stop: bool = field(default=False, repr=False)
    progress: EnrollmentProgress = field(default_factory=lambda: EnrollmentProgress(
        EnrollmentStage.IDLE, 0, 0))

    # ------------------------------------------------------------- API

    @property
    def busy(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, frame_provider: Callable[[], np.ndarray | None]) -> bool:
        """Lance la session. ``frame_provider`` retourne la dernière image BGR."""
        with self._lock:
            if self.busy:
                return False
            target = self.policy.enrollment_samples
            if not self.vault.available:
                self._set_progress(
                    EnrollmentStage.FAILED, 0, target,
                    message="Coffre de clés plateforme indisponible : enrôlement impossible "
                            "sans protection au repos (limite V0.1 documentée).",
                )
                return False
            if self.pipeline is None or not self.pipeline.loaded:
                self._set_progress(EnrollmentStage.FAILED, 0, target,
                                   message=self.pipeline.error if self.pipeline
                                   else "Pipeline non chargé.")
                return False
            self._stop = False
            self._set_progress(EnrollmentStage.NEED_FACE, 0, target,
                               message="Placez votre visage face à la caméra.")
            self._thread = threading.Thread(
                target=self._run, args=(frame_provider,),
                name="veyra-enrollment", daemon=True,
            )
            self._thread.start()
        return True

    def cancel(self) -> None:
        with self._lock:
            self._stop = True
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3.0)
        self._set_progress(EnrollmentStage.IDLE, 0, self.progress.target,
                           message="Enrôlement annulé.")

    # --------------------------------------------------------- exécution

    def _run(self, frame_provider: Callable[[], np.ndarray | None]) -> None:
        assert self.pipeline is not None  # vérifié dans start()
        target = self.policy.enrollment_samples
        samples: list[np.ndarray] = []
        orientations: list[tuple[float, float]] = []  # (dx, dy) relatifs des yeux
        fails = 0
        deadline = time.monotonic() + 180  # timeout global de 3 min

        while not self._stop and time.monotonic() < deadline:
            frame = frame_provider()
            if frame is None:
                self._set_progress(EnrollmentStage.NEED_FACE, len(samples), target,
                                   message="Caméra indisponible…")
                time.sleep(0.3)
                fails += 1
                if fails > 100:
                    break
                continue

            result = self.pipeline.process(frame, self.policy, reference=None)
            valid = [f for f in result.faces
                     if f.state.value in ("UNDETERMINED", "TRUSTED", "UNKNOWN")
                     and f.embedding is not None
                     and f.brightness >= self.policy.min_face_brightness]
            if len(result.faces) != 1 or len(valid) != 1:
                self._set_progress(
                    EnrollmentStage.NEED_FACE, len(samples), target,
                    message=("Un seul visage doit être visible."
                             if len(result.faces) > 1 else "Aucun visage détecté."),
                )
                time.sleep(0.3)
                continue

            face = valid[0]
            emb = face.embedding
            orientation = (face.x - 0.5, face.y - 0.5)

            # Diversité des angles : exiger un écart minimal par rapport aux
            # échantillons déjà retenus, sinon inviter à tourner la tête.
            if samples and not self._is_diverse(orientation, orientations):
                self._set_progress(
                    EnrollmentStage.MOVING, len(samples), target,
                    message="Tournez légèrement la tête pour varier les angles.",
                    orientation_hint=self._hint(orientation),
                )
                time.sleep(0.3)
                continue

            samples.append(emb)
            orientations.append(orientation)
            self._set_progress(
                EnrollmentStage.CAPTURING, len(samples), target,
                message=f"Échantillon {len(samples)}/{target} capturé.",
            )
            del frame, emb  # l'image n'est jamais conservée
            time.sleep(0.25)

        if len(samples) < target:
            if not self._stop:
                self._set_progress(EnrollmentStage.FAILED, len(samples), target,
                                   message="Enrôlement interrompu (temps écoulé ou caméra "
                                           "indisponible). Aucun profil enregistré.")
            return

        reference = self._average(samples)
        self._set_progress(EnrollmentStage.SAVING, target, target,
                           message="Chiffrement et enregistrement de l'empreinte…")
        try:
            sealed = self.vault.seal(reference.tobytes())
            self.db.save_profile(
                user_key=PROFILE_USER_KEY,
                display_name="Propriétaire",
                embedding_blob=sealed.to_json().encode("utf-8"),
                kdf_params_json='{"algo":"AESGCM-256","context":"veyra.embedding.v1"}',
            )
        except (KeyStorageError, Exception) as exc:
            logger.exception("Échec d'enregistrement du profil.")
            self._set_progress(EnrollmentStage.FAILED, len(samples), target,
                               message=f"Échec d'enregistrement : {exc}")
            return
        finally:
            samples.clear()

        self._set_progress(EnrollmentStage.DONE, target, target,
                           message="Profil biométrique enregistré et chiffré.")
        logger.info("Enrôlement terminé : empreinte moyenne sur %d échantillons.", target)

    # -------------------------------------------------------------- util

    @staticmethod
    def _average(samples: list[np.ndarray]) -> np.ndarray:
        mean = np.mean(np.stack(samples), axis=0).astype(np.float32)
        norm = float(np.linalg.norm(mean))
        if norm > 1e-6:
            mean = mean / norm
        return mean

    @staticmethod
    def _is_diverse(orientation: tuple[float, float],
                    existing: list[tuple[float, float]],
                    min_delta: float = 0.06) -> bool:
        if not existing:
            return True
        return any(
            abs(orientation[0] - ex) + abs(orientation[1] - ey) >= min_delta
            for ex, ey in existing
        )

    @staticmethod
    def _hint(orientation: tuple[float, float]) -> str:
        dx, _ = orientation
        if dx < -0.05:
            return "Tournez vers la gauche."
        if dx > 0.05:
            return "Tournez vers la droite."
        return "Inclinez légèrement la tête."

    def _set_progress(self, stage: EnrollmentStage, captured: int, target: int,
                      message: str = "", orientation_hint: str = "") -> None:
        self.progress = EnrollmentProgress(stage, captured, target, message,
                                           orientation_hint)
        self.bus.publish(Event(EventType.ENROLLMENT_PROGRESS, source="face_guard", data={
            "stage": stage.value,
            "progress": f"{captured}/{target}",
            "captured": captured,
            "target": target,
            "message": message,
            "orientation_hint": orientation_hint,
        }))


class ProfileRepository:
    """Charge/supprime l'empreinte de référence du profil autorisé."""

    def __init__(self, db: Database, vault: BiometricVault) -> None:
        self._db = db
        self._vault = vault
        self._cached: np.ndarray | None = None
        self._cache_valid = False

    @property
    def available(self) -> bool:
        return self._vault.available

    def has_profile(self) -> bool:
        return self._db.get_profile(PROFILE_USER_KEY) is not None

    def reference(self) -> np.ndarray | None:
        """Empreinte de référence en mémoire (None si absente/indéchiffrable)."""
        if self._cache_valid:
            return self._cached
        row = self._db.get_profile(PROFILE_USER_KEY)
        if row is None:
            self._cached, self._cache_valid = None, True
            return None
        try:
            from veyra.storage.biometrics import SealedEmbedding
            sealed = SealedEmbedding.from_json(row["embedding_blob"])
            raw = self._vault.open(sealed)
            self._cached = np.frombuffer(raw, dtype=np.float32).copy()
        except Exception:
            logger.exception("Impossible de déchiffrer l'empreinte du profil.")
            self._cached, self._cache_valid = None, True
            return None
        self._cache_valid = True
        return self._cached

    def invalidate(self) -> None:
        self._cached = None
        self._cache_valid = False

    def delete_profile(self) -> bool:
        """Suppression complète : ligne SQLite + clé Keychain si plus utilisé."""
        self.invalidate()
        return self._db.delete_profile(PROFILE_USER_KEY)

    def destroy_vault(self) -> None:
        """Efface la KEK du coffre plateforme (suppression complète)."""
        self._vault.destroy()
        self.invalidate()
