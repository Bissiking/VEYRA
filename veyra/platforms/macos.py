# veyra/platforms/macos.py
"""Adaptateur macOS — plateforme prioritaire de la V0.1.

Verrouillage : `osascript` + System Events (keystroke Ctrl+Cmd+Q),
aucun droit administrateur requis. Si l'autorisation est refusée,
l'échec est signalé tel quel (aucun contournement des protections système).

Activity : pynput (nécessite l'autorisation « Accessibilité » ou
« Surveillance clavier » selon la version de macOS ; sinon l'état du
flux est DÉGRADÉ, visible dans la GUI).
"""

from __future__ import annotations

import logging
import subprocess
import sys

from veyra.platforms.base import PlatformAdapter, PlatformCapabilities

logger = logging.getLogger(__name__)

_LOCK_APPLESCRIPT = (
    'tell application "System Events" to keystroke "q" '
    "using {control down, command down}"
)


class MacosAdapter(PlatformAdapter):
    platform_id = "macos"
    display_name = "macOS"

    def capabilities(self) -> PlatformCapabilities:
        notes: dict[str, str] = {}
        if sys.platform != "darwin":
            notes["session_lock"] = (
                "Adaptateur macOS chargé hors de macOS : verrouillage indisponible."
            )
            return PlatformCapabilities(
                session_lock=False,
                activity_monitoring=False,
                secure_key_storage=False,
                notes=notes,
            )
        return PlatformCapabilities(
            session_lock=True,
            activity_monitoring=True,
            secure_key_storage=True,  # Keychain via `security` (storage/biometrics.py)
            tray_icon=True,
            notes=notes,
        )

    def lock_session(self) -> bool:
        if sys.platform != "darwin":
            logger.error("lock_session appelé hors macOS.")
            return False
        try:
            result = subprocess.run(
                ["osascript", "-e", _LOCK_APPLESCRIPT],
                check=False, capture_output=True, text=True, timeout=10,
            )
        except (OSError, subprocess.TimeoutExpired):
            logger.exception("Échec de l'exécution d'osascript.")
            return False
        if result.returncode != 0:
            # Refus probable : permission Accessibilité non accordée à l'app.
            logger.error("Verrouillage refusé par macOS : %s",
                         (result.stderr or result.stdout).strip())
            return False
        return True

    def create_activity_stream(self):
        from veyra.modules.activity_guard.stream import PynputActivityStream
        return PynputActivityStream()
