# veyra/platforms/windows.py
"""Adaptateur Windows — verrouillage et coffre clés réels (V0.2).

Verrouillage : ``LockWorkStation`` (user32.dll, aucun droit admin requis).
Activity : pynput non testé sur Windows -> capacité exposée ``False``
(honnête, pas de fallback simulé).
Coffre clés : DPAPI utilisateur via ``storage.biometrics`` (voir ce module).
"""

from __future__ import annotations

import ctypes
import logging
import sys

from veyra.platforms.base import PlatformAdapter, PlatformCapabilities

logger = logging.getLogger(__name__)


class WindowsAdapter(PlatformAdapter):
    platform_id = "windows"
    display_name = "Windows"

    def capabilities(self) -> PlatformCapabilities:
        notes: dict[str, str] = {}
        if not sys.platform.startswith("win"):
            notes["status"] = (
                "Adaptateur Windows chargé hors Windows : "
                "verrouillage et coffre clés indisponibles."
            )
            return PlatformCapabilities(
                session_lock=False,
                activity_monitoring=False,
                secure_key_storage=False,
                notes=notes,
            )
        notes["activity_monitoring"] = (
            "Flux d'activité non testé sur Windows (V0.2)."
        )
        return PlatformCapabilities(
            session_lock=True,
            activity_monitoring=False,
            secure_key_storage=True,
            tray_icon=True,
            notes=notes,
        )

    def lock_session(self) -> bool:
        if not sys.platform.startswith("win"):
            logger.error("lock_session appelé hors Windows.")
            return False
        try:
            # LockWorkStation ne renvoie pas d'erreur détaillée : un retour
            # non nul indique seulement que la demande a été acceptée.
            ok = bool(ctypes.windll.user32.LockWorkStation())
        except (OSError, AttributeError):
            logger.exception("Échec de l'appel à LockWorkStation.")
            return False
        if not ok:
            logger.error("Verrouillage Windows refusé (LockWorkStation = 0).")
            return False
        return True

    def create_activity_stream(self):
        return None
