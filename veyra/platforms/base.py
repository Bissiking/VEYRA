# veyra/platforms/base.py
"""Interface commune des adaptateurs plateforme VEYRA.

Chaque plateforme implémente :
- ``lock_session()`` : verrouillage réel de la session (appelé UNIQUEMENT
  par ``core.safety.ActionExecutor`` en mode PROTECTION) ;
- ``platform_id`` / ``display_name`` / ``capabilities`` : description pour la GUI ;
- ``activity_stream`` : capture d'activité clavier/souris sans contenu (fabrique).

Toute fonctionnalité non disponible doit être exposée comme indisponible
(``capabilities[...] = False``) — jamais simulée silencieusement.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from veyra.modules.activity_guard.stream import ActivityStream


@dataclass(frozen=True)
class PlatformCapabilities:
    """État réel des fonctions supportées sur la plateforme courante."""

    session_lock: bool = False
    activity_monitoring: bool = False
    secure_key_storage: bool = False
    tray_icon: bool = True
    notes: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_lock": self.session_lock,
            "activity_monitoring": self.activity_monitoring,
            "secure_key_storage": self.secure_key_storage,
            "tray_icon": self.tray_icon,
            "notes": dict(self.notes),
        }


class PlatformAdapter(ABC):
    """Contrat minimal d'un adaptateur plateforme."""

    platform_id: str = "unknown"
    display_name: str = "Plateforme inconnue"

    @abstractmethod
    def capabilities(self) -> PlatformCapabilities:
        """Retourne les capacités RÉELLES (aucune fonction fantôme)."""

    @abstractmethod
    def lock_session(self) -> bool:
        """Verrouille la session utilisateur. True si l'action a réussi.

        Appelé uniquement par l'exécuteur de sécurité en mode PROTECTION.
        """

    @abstractmethod
    def create_activity_stream(self) -> "ActivityStream | None":
        """Fabrique le flux d'activité (sans contenu de frappe).

        Retourne None si la plateforme ne le supporte pas (V0.1).
        """

    def is_available(self) -> bool:
        """Indique si l'adaptateur est opérationnel sur ce système."""
        return True
