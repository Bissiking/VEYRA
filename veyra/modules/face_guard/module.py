# veyra/modules/face_guard/module.py
"""Module Face Guard : orchestre caméra, pipeline et cadence d'analyse.

Cadence pilotée par les demandes du moteur (``ANALYSIS_REQUEST``) et par
l'état du moteur (``ENGINE_STATE``) pour limiter la CPU :
- mode ACTIVE  : analyse à ``active_analysis_interval_s`` ;
- mode LIGHT   : analyse à ``light_analysis_interval_s`` ;
- prioritaire  : analyse immédiate (reprise d'activité après absence).

Anti-spoofing V0.2 : entre deux analyses complètes, un échantillonnage rapide
(~10 Hz, sans inférence ONNX) alimente le ``LivenessTracker`` avec
l'ouverture des yeux et la texture — un clignement dure 200-400 ms et serait
manqué à la cadence normale. Un visage suspect n'est JAMAIS déduit d'un seul
signal (voir liveness.py).

Le module publie uniquement des ``FACE_OBSERVATION`` (état + métriques de
qualité). Aucune image ni empreinte ne transite par le bus ni par SQLite.
"""

from __future__ import annotations

import logging
import threading
import time

from veyra.core.events import Event, EventBus, EventType
from veyra.core.module_api import IVeyraModule, ModuleInfo, ModuleState
from veyra.core.policy import IdentityState, SecurityPolicy, SurveillanceMode
from veyra.modules.face_guard.camera import CameraWorker
from veyra.modules.face_guard.enrollment import EnrollmentSession, ProfileRepository
from veyra.modules.face_guard.liveness import (
    LivenessTracker,
    eye_openness,
    texture_score,
)
from veyra.modules.face_guard.models import ModelPaths, default_models_dir
from veyra.modules.face_guard.pipeline import FacePipeline

logger = logging.getLogger(__name__)

_LIVENESS_SAMPLE_INTERVAL_S = 0.1  # échantillonnage rapide du clignement (~10 Hz)


class FaceGuardModule(IVeyraModule):
    module_id = "face_guard"
    name = "Présence faciale"

    def __init__(self, bus: EventBus, policy: SecurityPolicy,
                 paths: ModelPaths | None = None,
                 profile_repo: ProfileRepository | None = None,
                 enrollment: EnrollmentSession | None = None,
                 camera_index: int = 0) -> None:
        self._bus = bus
        self._policy = policy
        self._paths = paths or ModelPaths(default_models_dir())
        self._pipeline = FacePipeline(self._paths)
        self._camera = CameraWorker(bus, camera_index)
        self._profiles = profile_repo
        self._enrollment = enrollment

        self._state = ModuleState.STOPPED
        self._detail = ""
        self._running = False
        self._thread: threading.Thread | None = None
        self._force_immediate = threading.Event()
        self._mode = SurveillanceMode.ACTIVE
        self._last_result_state = IdentityState.NO_FACE
        self._last_analysis_ts = 0.0
        self._analysis_count = 0
        self._frames_with_faces = 0
        self._low_power = False
        self._unsubs: list = []

        # Anti-spoofing (V0.2) : suivi léger entre deux analyses complètes.
        self._liveness = LivenessTracker(
            window_s=policy.liveness_window_s,
            min_blinks=policy.liveness_min_blinks,
            min_openness=policy.liveness_min_openness,
            min_texture=policy.liveness_min_texture,
        )
        self._last_face_px: tuple[int, int, int, int] | None = None  # x, y, w, h
        self._last_eye_px: tuple[tuple[int, int], tuple[int, int]] | None = None
        self._last_liveness_ts = 0.0

        # Calibration (V0.2) : collecte optionnelle de distances pour la
        # courbe FAR/FRR locale. Seuls des scalaires sont retenus.
        self._calibrating = False
        self._calib_genuine: list[float] = []
        self._calib_impostor: list[float] = []

    # ------------------------------------------------------------ propriétés

    @property
    def camera(self) -> CameraWorker:
        return self._camera

    @property
    def pipeline(self) -> FacePipeline:
        return self._pipeline

    def set_policy(self, policy: SecurityPolicy) -> None:
        self._policy = policy
        self._liveness.reconfigure(
            window_s=policy.liveness_window_s,
            min_blinks=policy.liveness_min_blinks,
            min_openness=policy.liveness_min_openness,
            min_texture=policy.liveness_min_texture,
        )

    def set_camera_index(self, index: int) -> None:
        self._camera.set_index(index)

    def set_low_power(self, value: bool) -> None:
        self._low_power = value

    def request_priority_analysis(self) -> None:
        """Demande d'analyse immédiate (appelée par l'interface en cas de reprise)."""
        self._force_immediate.set()

    # -------------------------------------------------------------- calibration

    def start_calibration(self) -> None:
        """Démarre la collecte de distances pour la courbe FAR/FRR locale."""
        self._calibrating = True
        self._calib_genuine.clear()
        self._calib_impostor.clear()

    def stop_calibration(self) -> dict[str, list[float]]:
        """Arrête la collecte et retourne les échantillons (scalars seuls)."""
        self._calibrating = False
        return {"genuine": list(self._calib_genuine),
                "impostor": list(self._calib_impostor)}

    @property
    def calibrating(self) -> bool:
        return self._calibrating

    # ---------------------------------------------------------- cycle de vie

    def start(self) -> None:
        if self._running:
            return
        self._state = ModuleState.STARTING
        if not self._pipeline.load():
            self._state = ModuleState.ERROR
            self._detail = self._pipeline.error
            self._publish_status()
            # La caméra reste utile pour l'aperçu Presence même sans modèles.
            self._camera.start()
            logger.error("face_guard en erreur : %s", self._detail)
            return
        if self._enrollment is not None and not self._enrollment.vault.available:
            self._detail = ("Coffre clés indisponible : reconnaissance activera mais "
                            "l'enrôlement est désactivé (voir docs/SECURITY.md).")
        self._camera.start()
        self._running = True
        self._unsubs = [
            self._bus.subscribe(EventType.ENGINE_STATE, self._on_engine_state),
            self._bus.subscribe(EventType.ANALYSIS_REQUEST, self._on_analysis_request),
        ]
        self._thread = threading.Thread(target=self._loop, name="veyra-face", daemon=True)
        self._thread.start()
        self._state = ModuleState.RUNNING
        if not self._detail:
            self._detail = "Détection et reconnaissance locales actives."
        self._publish_status()

    def stop(self) -> None:
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5.0)
        for unsub in self._unsubs:
            unsub()
        self._unsubs = []
        self._camera.stop()
        self._state = ModuleState.STOPPED
        self._detail = ""
        self._publish_status()

    def info(self) -> ModuleInfo:
        metrics: dict[str, object] = {
            "analyses": self._analysis_count,
            "last_state": self._last_result_state.value,
            "camera_ok": self._camera.available,
            "profile_loaded": bool(self._profiles and self._profiles.has_profile()),
        }
        if self._camera.available:
            metrics["faces_seen"] = self._frames_with_faces
        return ModuleInfo(self.module_id, self.name, self._state, self._detail, metrics)

    # ------------------------------------------------------ événements noyau

    def _on_engine_state(self, event: Event) -> None:
        try:
            self._mode = SurveillanceMode(event.data.get("mode", SurveillanceMode.ACTIVE.value))
        except ValueError:
            self._mode = SurveillanceMode.ACTIVE

    def _on_analysis_request(self, event: Event) -> None:
        if event.data.get("priority"):
            self._force_immediate.set()

    # --------------------------------------------------------------- boucle

    def _loop(self) -> None:
        while self._running:
            interval = self._current_interval()
            now = time.monotonic()
            forced = self._force_immediate.is_set()
            if forced:
                self._force_immediate.clear()
            elif now - self._last_analysis_ts < interval:
                # Échantillonnage léger anti-spoofing (~10 Hz, sans ONNX).
                if (self._policy.anti_spoofing_enabled
                        and now - self._last_liveness_ts >= _LIVENESS_SAMPLE_INTERVAL_S):
                    try:
                        self._sample_liveness()
                    except Exception:
                        logger.exception("Erreur d'échantillonnage anti-spoofing.")
                time.sleep(0.05)
                continue
            try:
                self._analyze_once()
            except Exception:
                logger.exception("Erreur pendant l'analyse faciale.")
            self._last_analysis_ts = time.monotonic()
            time.sleep(0.05)

    def _current_interval(self) -> float:
        if self._mode is SurveillanceMode.LIGHT:
            base = self._policy.light_analysis_interval_s
        else:
            base = self._policy.active_analysis_interval_s
        if self._low_power:
            base *= 2.0
        return max(base, 0.5)

    def _sample_liveness(self) -> None:
        """Mesure rapide (yeux + texture) entre deux analyses complètes.

        Utilise la dernière boîte connue du visage — aucun décodage ONNX.
        Alimente le tracker ; la décision n'est prise qu'au moment de
        l'analyse complète (``_analyze_once``).
        """
        if self._last_face_px is None or self._last_eye_px is None:
            return
        _ts, frame = self._camera.latest()
        if frame is None:
            return
        (ex_r, ey_r), (ex_l, ey_l) = self._last_eye_px
        x, y, w, h = self._last_face_px
        openness = min(
            eye_openness(frame, ex_r, ey_r, w),
            eye_openness(frame, ex_l, ey_l, w),
        )
        texture = texture_score(frame, x, y, w, h)
        self._liveness.observe(time.monotonic(), openness, texture)
        self._last_liveness_ts = time.monotonic()

    def _analyze_once(self) -> None:
        _ts, frame = self._camera.latest()
        if frame is None:
            # Caméra indisponible : le statut est déjà publié par CameraWorker.
            return
        reference = self._profiles.reference() if self._profiles else None
        result = self._pipeline.process(frame, self._policy, reference)
        self._analysis_count += 1
        if result.state is not IdentityState.NO_FACE:
            self._frames_with_faces += 1

        # Calibration : collecte des distances déjà calculées (scalars seuls).
        if self._calibrating and result.faces:
            for face in result.faces:
                if face.distance is None:
                    continue
                if face.state is IdentityState.TRUSTED:
                    self._calib_genuine.append(face.distance)
                elif face.state is IdentityState.UNKNOWN:
                    self._calib_impostor.append(face.distance)

        # Anti-spoofing : met à jour les repères du visage pour l'échantillonnage
        # rapide et consulte le tracker pour dégrader TRUSTED si nécessaire.
        spoof_suspect = False
        if self._policy.anti_spoofing_enabled:
            if result.faces:
                best = max(result.faces, key=lambda f: f.score)
                if best.landmarks is not None and best.w_px > 0:
                    fw = frame.shape[1]
                    fh = frame.shape[0]
                    self._last_face_px = (
                        int(best.x * fw), int(best.y * fh), best.w_px, best.h_px)
                    eyes = best.landmarks[:2]  # yeux droit puis gauche (YuNet)
                    self._last_eye_px = (
                        (int(eyes[0][0]), int(eyes[0][1])),
                        (int(eyes[1][0]), int(eyes[1][1])),
                    )
                    # Alimente aussi le tracker avec la frame complète courante.
                    openness = min(
                        eye_openness(frame, *self._last_eye_px[0], best.w_px),
                        eye_openness(frame, *self._last_eye_px[1], best.w_px),
                    )
                    self._liveness.observe(time.monotonic(), openness, best.texture)
            snapshot = self._liveness.snapshot()
            spoof_suspect = snapshot.suspect
            if spoof_suspect and result.state is IdentityState.TRUSTED:
                # La distance biométrique est bonne mais le visage ne cligne
                # pas et semble lisse -> photo/écran possible. On dégrade en
                # UNKNOWN (déclenche la confirmation du moteur, jamais un
                # verrouillage immédiat).
                result.state = IdentityState.UNKNOWN
                result.detail = (result.detail
                                 + " — anti-spoofing : clignement/texture "
                                   "insuffisants (photo possible).").strip(" —")
                logger.warning("Anti-spoofing : TRUSTED dégradé en UNKNOWN "
                               "(blinks=%d, texture=%.1f).",
                               snapshot.blinks, snapshot.mean_texture)
            elif spoof_suspect and result.state is not IdentityState.UNKNOWN:
                result.state = IdentityState.UNDETERMINED
                result.detail = (result.detail
                                 + " — anti-spoofing : visage suspect "
                                   "(photo possible).").strip(" —")
        self._last_result_state = result.state

        data: dict[str, object] = {
            "state": result.state.value,
            "face_count": len(result.faces),
            "detail": result.detail,
        }
        if result.faces:
            # Métriques agrégées uniquement (aucune coordonnée individuelle stockée).
            data["best_score"] = round(max(f.score for f in result.faces), 3)
            distances = [round(f.distance, 3) for f in result.faces if f.distance is not None]
            if distances:
                data["best_distance"] = min(distances)
            data["min_brightness"] = round(min(f.brightness for f in result.faces), 1)
        if self._policy.anti_spoofing_enabled:
            snapshot = self._liveness.snapshot()
            data["spoof_suspect"] = spoof_suspect
            data["blinks"] = snapshot.blinks
        self._bus.publish(Event(EventType.FACE_OBSERVATION, source=self.module_id,
                                data=data))

    # ---------------------------------------------------------------- GUI

    def enrollment_session(self) -> EnrollmentSession | None:
        return self._enrollment

    def _publish_status(self) -> None:
        info = self.info()
        self._bus.publish(Event(EventType.MODULE_STATUS, source=self.module_id, data={
            "state": info.state.value,
            "detail": info.detail,
            "metrics": info.metrics,
        }))
