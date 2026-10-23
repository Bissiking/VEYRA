# veyra/platforms/autostart.py
"""Démarrage au login de l'utilisateur (option V0.2).

Agent utilisateur — JAMAIS de daemon root. Trois mécanismes natifs :

- **macOS** : ``LaunchAgent`` dans ``~/Library/LaunchAgents/``
  (``launchctl bootstrap`` pour activer sans redémarrage) ;
- **Windows** : clé de registre ``HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run``
  via ``winreg`` (standard, nettoyable) ;
- **Linux** : fichier ``.desktop`` dans ``~/.config/autostart/`` (XDG).

L'option est DÉSACTIVÉE par défaut ; elle est pilotée depuis la page
Settings. Toute opération échoue silencieusement côté GUI (retour booléen) et
est journalisée — aucune élévation de privilèges n'est tentée.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

_APP_NAME = "VEYRA"
_MACOS_LABEL = "com.veyra.app"
_WINDOWS_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def _launch_command() -> list[str]:
    """Commande de redémarrage : interpréteur courant + module app."""
    return [sys.executable, "-m", "veyra.app"]


# ------------------------------------------------------------------ macOS


def _macos_plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{_MACOS_LABEL}.plist"


def _macos_plist_content() -> str:
    cmd = _launch_command()
    args_xml = "\n".join(f"        <string>{a}</string>" for a in cmd[1:])
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{_MACOS_LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{cmd[0]}</string>
{args_xml}
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <false/>
</dict>
</plist>
"""


def _macos_enable() -> bool:
    path = _macos_plist_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_macos_plist_content(), encoding="utf-8")
    except OSError:
        logger.exception("Écriture du LaunchAgent échouée.")
        return False
    try:
        subprocess.run(
            ["launchctl", "bootstrap", "gui/" + str(os.getuid()), str(path)],
            check=False, capture_output=True, timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        # Le plist est en place : il sera chargé au prochain login même si
        # le bootstrap live échoue (par ex. session déjà chargée).
        logger.warning("bootstrap launchctl échoué ; chargement au prochain login.")
    return True


def _macos_disable() -> bool:
    path = _macos_plist_path()
    try:
        subprocess.run(
            ["launchctl", "bootout", "gui/" + str(os.getuid()), str(path)],
            check=False, capture_output=True, timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        logger.warning("bootout launchctl échoué.")
    try:
        path.unlink(missing_ok=True)
    except OSError:
        logger.exception("Suppression du LaunchAgent échouée.")
        return False
    return True


# ---------------------------------------------------------------- Windows


def _windows_enable() -> bool:
    try:
        import winreg
    except ImportError:
        logger.error("winreg indisponible : autostart Windows impossible.")
        return False
    cmd = " ".join(f'"{a}"' if " " in a else a for a in _launch_command())
    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, _WINDOWS_RUN_KEY) as key:
            winreg.SetValueEx(key, _APP_NAME, 0, winreg.REG_SZ, cmd)
        return True
    except OSError:
        logger.exception("Écriture du registre HKCU Run échouée.")
        return False


def _windows_disable() -> bool:
    try:
        import winreg
    except ImportError:
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _WINDOWS_RUN_KEY,
                            0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, _APP_NAME)
        return True
    except FileNotFoundError:
        return True  # déjà absent
    except OSError:
        logger.exception("Suppression de la clé HKCU Run échouée.")
        return False


# ------------------------------------------------------------------ Linux


def _linux_desktop_path() -> Path:
    return Path.home() / ".config" / "autostart" / "veyra.desktop"


def _linux_enable() -> bool:
    cmd = _launch_command()
    exec_line = " ".join(f'"{a}"' if " " in a else a for a in cmd)
    content = (
        "[Desktop Entry]\n"
        "Type=Application\n"
        f"Name={_APP_NAME}\n"
        "Comment=Surveillance locale (reconnaissance faciale hors ligne)\n"
        f"Exec={exec_line}\n"
        "X-GNOME-Autostart-enabled=true\n"
        "NoDisplay=true\n"
    )
    path = _linux_desktop_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return True
    except OSError:
        logger.exception("Écriture du .desktop autostart échouée.")
        return False


def _linux_disable() -> bool:
    try:
        _linux_desktop_path().unlink(missing_ok=True)
        return True
    except OSError:
        logger.exception("Suppression du .desktop autostart échouée.")
        return False


# ----------------------------------------------------------------- API


def autostart_supported() -> bool:
    """Indique si le démarrage au login est géré sur cette plateforme."""
    return (sys.platform == "darwin"
            or sys.platform.startswith("win")
            or sys.platform.startswith("linux"))


def is_autostart_enabled() -> bool:
    """Vérifie la présence du marqueur natif (plist / registre / .desktop)."""
    if sys.platform == "darwin":
        return _macos_plist_path().is_file()
    if sys.platform.startswith("win"):
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _WINDOWS_RUN_KEY):
                pass
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _WINDOWS_RUN_KEY,
                                0, winreg.KEY_READ) as key:
                winreg.QueryValueEx(key, _APP_NAME)
            return True
        except (ImportError, OSError, FileNotFoundError):
            return False
    if sys.platform.startswith("linux"):
        return _linux_desktop_path().is_file()
    return False


def set_autostart(enabled: bool) -> bool:
    """Active ou désactive le démarrage au login. Retourne le succès."""
    if not autostart_supported():
        logger.error("Démarrage au login non géré sur %s.", sys.platform)
        return False
    if sys.platform == "darwin":
        return _macos_enable() if enabled else _macos_disable()
    if sys.platform.startswith("win"):
        return _windows_enable() if enabled else _windows_disable()
    return _linux_enable() if enabled else _linux_disable()
