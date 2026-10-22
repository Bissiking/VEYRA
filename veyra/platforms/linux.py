# veyra/platforms/linux.py
"""Adaptateur Linux — INTERFACE FOURNIE, NON OPÉRATIONNELLE EN V0.1.

Fonctions marquées indisponibles dans la GUI ; aucun fallback silencieux.
"""

from __future__ import annotations

from veyra.platforms.base import PlatformAdapter, PlatformCapabilities


class LinuxAdapter(PlatformAdapter):
    platform_id = "linux"
    display_name = "Linux (prévisionnel)"

    def capabilities(self) -> PlatformCapabilities:
        return PlatformCapabilities(
            session_lock=False,  # V0.1 : non implémenté (loginctl/xdg non branchés)
            activity_monitoring=False,  # V0.1 : pynput X11 non testé
            secure_key_storage=False,  # V0.1 : Secret Service non branché
            tray_icon=True,
            notes={
                "status": "Adaptateur prévisionnel. Aucune fonction opérationnelle en V0.1.",
                "session_lock": "Verrouillage non implémenté (V0.1).",
                "activity_monitoring": "Flux d'activité non implémenté (V0.1).",
                "secure_key_storage": "Coffre de clés non implémenté : enrôlement biométrique désactivé.",
            },
        )

    def lock_session(self) -> bool:
        raise NotImplementedError(
            "Verrouillage Linux non implémenté en V0.1. "
            "Le coupe-circuit bloque toute tentative en mode PROTECTION."
        )

    def create_activity_stream(self):
        return None
