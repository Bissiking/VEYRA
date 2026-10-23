# veyra/platforms/linux.py
"""Adaptateur Linux — verrouillage et coffre clés réels (V0.2).

Verrouillage : ``loginctl lock-session`` (systemd/logind, aucun sudo).
Coffre clés : Secret Service via ``secret-tool`` (GNOME Keyring / KWallet),
voir ``storage.biometrics``.
Activity : pynput X11/Wayland non testé ici -> capacité ``False`` honnête.

La disponibilité réelle est sondée au chargement (``loginctl`` /
``secret-tool`` absents -> capacité à ``False`` + note explicite).
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import sys

from veyra.platforms.base import PlatformAdapter, PlatformCapabilities

logger = logging.getLogger(__name__)


class LinuxAdapter(PlatformAdapter):
    platform_id = "linux"
    display_name = "Linux"

    def capabilities(self) -> PlatformCapabilities:
        notes: dict[str, str] = {}
        on_linux = sys.platform.startswith("linux")
        if not on_linux:
            notes["status"] = (
                "Adaptateur Linux chargé hors Linux : "
                "verrouillage et coffre clés indisponibles."
            )
            return PlatformCapabilities(
                session_lock=False,
                activity_monitoring=False,
                secure_key_storage=False,
                notes=notes,
            )
        lock_ok = shutil.which("loginctl") is not None
        if not lock_ok:
            notes["session_lock"] = (
                "loginctl introuvable : verrouillage indisponible."
            )
        key_ok = shutil.which("secret-tool") is not None
        if not key_ok:
            notes["secure_key_storage"] = (
                "secret-tool introuvable : enrôlement biométrique désactivé."
            )
        return PlatformCapabilities(
            session_lock=lock_ok,
            activity_monitoring=False,  # pynput non testé sur Linux (V0.2)
            secure_key_storage=key_ok,
            tray_icon=True,
            notes=notes,
        )

    def lock_session(self) -> bool:
        if not sys.platform.startswith("linux"):
            logger.error("lock_session appelé hors Linux.")
            return False
        try:
            result = subprocess.run(
                ["loginctl", "lock-session"],
                check=False, capture_output=True, text=True, timeout=10,
            )
        except (OSError, subprocess.TimeoutExpired):
            logger.exception("Échec de l'exécution de loginctl.")
            return False
        if result.returncode != 0:
            # Session logind absente ou refus : échec signalé tel quel.
            logger.error("Verrouillage refusé par Linux : %s",
                         (result.stderr or result.stdout).strip())
            return False
        return True

    def create_activity_stream(self):
        return None
