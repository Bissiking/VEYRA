# veyra/platforms/windows.py
"""Adaptateur Windows — INTERFACE FOURNIE, NON OPÉRATIONNELLE EN V0.1.

Les fonctions marquées indisponibles apparaissent comme telles dans la GUI.
Aucune simulation silencieuse n'est effectuée.
"""

from __future__ import annotations


from veyra.platforms.base import PlatformAdapter, PlatformCapabilities


class WindowsAdapter(PlatformAdapter):
    platform_id = "windows"
    display_name = "Windows (prévisionnel)"

    def capabilities(self) -> PlatformCapabilities:
        return PlatformCapabilities(
            session_lock=False,  # V0.1 : non implémenté (LockWorkStation non branché)
            activity_monitoring=False,  # V0.1 : non testé sur Windows
            secure_key_storage=False,  # V0.1 : DPAPI non branché
            tray_icon=True,
            notes={
                "status": "Adaptateur prévisionnel. Aucune fonction opérationnelle en V0.1.",
                "session_lock": "Verrouillage non implémenté (V0.1).",
                "activity_monitoring": "Flux d'activité non implémenté (V0.1).",
                "secure_key_storage": "Coffre de clés non implémenté : enrôlement biométrique désactivé.",
            },
        )

    def lock_session(self) -> bool:
        # Volontairement non implémenté : voir capabilities().
        raise NotImplementedError(
            "Verrouillage Windows non implémenté en V0.1. "
            "Le coupe-circuit bloque toute tentative en mode PROTECTION."
        )

    def create_activity_stream(self):
        return None
