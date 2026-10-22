# veyra/core/policy.py
"""Politiques de sécurité et modèle de décision VEYRA."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class IdentityState(str, Enum):
    """État de reconnaissance faciale pour une observation."""

    TRUSTED = "TRUSTED"
    UNKNOWN = "UNKNOWN"
    UNDETERMINED = "UNDETERMINED"
    NO_FACE = "NO_FACE"


class Decision(str, Enum):
    """Décision du moteur de surveillance."""

    NONE = "NONE"
    MAINTAIN_SESSION = "MAINTAIN_SESSION"
    LOCK_SESSION = "LOCK_SESSION"


class SurveillanceMode(str, Enum):
    """Mode de surveillance adaptatif."""

    ACTIVE = "ACTIVE"          # activité récente, analyse régulière
    LIGHT = "LIGHT"            # pas d'activité depuis idle_threshold, analyse espacée
    PRIORITY = "PRIORITY"      # reprise d'activité après absence, analyse immédiate


class ProtectionMode(str, Enum):
    """Coupe-circuit de sécurité.

    SIMULATION : décisions calculées et journalisées, aucun verrouillage réel.
    PROTECTION : les décisions autorisées peuvent déclencher un verrouillage réel.
    """

    SIMULATION = "SIMULATION"
    PROTECTION = "PROTECTION"


@dataclass
class SecurityPolicy:
    """Paramètres du moteur de décision (valeurs par défaut = V0.1).

    Toute valeur est persistée via ``storage.config`` et modifiable dans
    la page Settings de la GUI.
    """

    # Surveillance adaptative
    idle_threshold_s: float = 10.0          # sans activité -> surveillance légère
    light_analysis_interval_s: float = 5.0  # cadence d'analyse en mode léger
    active_analysis_interval_s: float = 1.0  # cadence d'analyse en mode actif
    confirm_window_s: float = 2.0           # fenêtre de confirmation d'identité suspecte
    absent_idle_keep_session: bool = True   # absence du propriétaire sans activité -> maintien

    # Politique de verrouillage
    lock_on_unknown_face_with_activity: bool = True
    lock_on_camera_loss_after_absence: bool = True  # webcam indispo. après absence + activité

    # Reconnaissance faciale
    recognition_threshold: float = 0.636    # distance L2 SFace (recommandation OpenCV)
    recognition_margin: float = 0.08        # zone grise -> UNDETERMINED si seuil < d < seuil+margin
    min_face_size_px: int = 80              # visage trop petit -> UNDETERMINED
    min_face_brightness: float = 40.0       # luminosité moyenne du ROI sous ce seuil -> mauvais éclairage

    # Consentement / enrôlement
    enrollment_samples: int = 8             # échantillons multi-angles requis

    def to_dict(self) -> dict[str, float | bool | int]:
        return {
            "idle_threshold_s": self.idle_threshold_s,
            "light_analysis_interval_s": self.light_analysis_interval_s,
            "active_analysis_interval_s": self.active_analysis_interval_s,
            "confirm_window_s": self.confirm_window_s,
            "absent_idle_keep_session": self.absent_idle_keep_session,
            "lock_on_unknown_face_with_activity": self.lock_on_unknown_face_with_activity,
            "lock_on_camera_loss_after_absence": self.lock_on_camera_loss_after_absence,
            "recognition_threshold": self.recognition_threshold,
            "recognition_margin": self.recognition_margin,
            "min_face_size_px": self.min_face_size_px,
            "min_face_brightness": self.min_face_brightness,
            "enrollment_samples": self.enrollment_samples,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "SecurityPolicy":
        """Construit une politique à partir d'un dict persisté (clés inconnues ignorées)."""
        policy = cls()
        for key, default in cls().to_dict().items():
            if key not in data:
                continue
            value = data[key]
            try:
                setattr(policy, key, type(default)(value))  # noqa: SLF001
            except (TypeError, ValueError):
                continue
        return policy


@dataclass
class DecisionRecord:
    """Représentation d'une décision émise par le moteur."""

    decision: Decision
    reason: str
    identity_state: IdentityState
    mode: SurveillanceMode
    metadata: dict[str, object] = field(default_factory=dict)
