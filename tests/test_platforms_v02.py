# tests/test_platforms_v02.py
"""Tests V0.2 : verrouillage Windows/Linux, coffres clés, autostart.

Aucune commande native n'est exécutée : ``sys.platform`` et ``subprocess.run``
sont monkeypatchés. Aucune caméra, aucun keychain réel.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from veyra.platforms.autostart import (
    _launch_command,
    _macos_plist_content,
    autostart_supported,
    is_autostart_enabled,
    set_autostart,
)
from veyra.platforms.base import PlatformCapabilities
from veyra.platforms.linux import LinuxAdapter
from veyra.platforms.windows import WindowsAdapter
from veyra.storage.biometrics import (
    KeyStorageError,
    LinuxSecretServiceStorage,
    UnavailableKeyStorage,
    WindowsDpapiStorage,
    create_key_storage,
)

# ------------------------------------------------------------- verrouillage


def test_windows_lock_refuse_hors_windows(monkeypatch):
    monkeypatch.setattr("sys.platform", "darwin")
    adapter = WindowsAdapter()
    assert adapter.lock_session() is False


def test_linux_lock_refuse_hors_linux(monkeypatch):
    monkeypatch.setattr("sys.platform", "darwin")
    adapter = LinuxAdapter()
    assert adapter.lock_session() is False


def test_windows_lock_succes(monkeypatch):
    monkeypatch.setattr("sys.platform", "win32")
    fake_user32 = MagicMock()
    fake_user32.LockWorkStation.return_value = 1
    fake_windll = MagicMock()
    fake_windll.user32 = fake_user32
    monkeypatch.setattr("ctypes.windll", fake_windll, raising=False)
    assert WindowsAdapter().lock_session() is True
    fake_user32.LockWorkStation.assert_called_once()


def test_windows_lock_echec_applicatif(monkeypatch):
    monkeypatch.setattr("sys.platform", "win32")
    fake_user32 = MagicMock()
    fake_user32.LockWorkStation.return_value = 0
    fake_windll = MagicMock()
    fake_windll.user32 = fake_user32
    monkeypatch.setattr("ctypes.windll", fake_windll, raising=False)
    assert WindowsAdapter().lock_session() is False


def test_linux_lock_succes(monkeypatch):
    monkeypatch.setattr("sys.platform", "linux")
    fake_result = MagicMock()
    fake_result.returncode = 0
    fake_result.stderr = ""
    fake_result.stdout = ""
    monkeypatch.setattr("subprocess.run", lambda *a, **k: fake_result)
    assert LinuxAdapter().lock_session() is True


def test_linux_lock_echec_applicatif(monkeypatch):
    monkeypatch.setattr("sys.platform", "linux")
    fake_result = MagicMock()
    fake_result.returncode = 1
    fake_result.stderr = "Failed to issue method call: Not authorized"
    fake_result.stdout = ""
    monkeypatch.setattr("subprocess.run", lambda *a, **k: fake_result)
    assert LinuxAdapter().lock_session() is False


def test_linux_lock_commande_loginctl(monkeypatch):
    monkeypatch.setattr("sys.platform", "linux")
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        result = MagicMock()
        result.returncode = 0
        result.stderr = ""
        result.stdout = ""
        return result

    monkeypatch.setattr("subprocess.run", fake_run)
    LinuxAdapter().lock_session()
    assert calls and calls[0][0] == "loginctl"
    assert "lock-session" in calls[0]


# --------------------------------------------------------------- capacités


def test_windows_capabilities_hors_windows():
    caps = WindowsAdapter().capabilities()
    assert caps.session_lock is False
    assert caps.secure_key_storage is False
    assert "status" in caps.notes


def test_linux_capabilities_sonde_outils(monkeypatch):
    monkeypatch.setattr("sys.platform", "linux")
    monkeypatch.setattr("shutil.which", lambda name: None)
    caps = LinuxAdapter().capabilities()
    assert caps.session_lock is False
    assert caps.secure_key_storage is False
    assert "loginctl" in caps.notes["session_lock"]
    assert "secret-tool" in caps.notes["secure_key_storage"]


def test_linux_capabilities_outils_presents(monkeypatch):
    monkeypatch.setattr("sys.platform", "linux")
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/" + name)
    caps = LinuxAdapter().capabilities()
    assert caps.session_lock is True
    assert caps.secure_key_storage is True


def test_capabilities_est_un_dataclass_figee():
    import dataclasses

    caps = PlatformCapabilities(session_lock=True)
    with pytest.raises(dataclasses.FrozenInstanceError):
        caps.session_lock = False  # type: ignore[misc]


# ------------------------------------------------------------- coffre clés


def test_fabrique_refuse_sans_plateforme_connue(monkeypatch):
    monkeypatch.setattr("sys.platform", "aix")
    storage = create_key_storage()
    assert isinstance(storage, UnavailableKeyStorage)
    with pytest.raises(KeyStorageError):
        storage.get_or_create_kek()


def test_windows_dpapi_refuse_hors_windows(monkeypatch, tmp_path):
    monkeypatch.setattr("sys.platform", "darwin")
    storage = WindowsDpapiStorage(appdata=tmp_path)
    with pytest.raises(KeyStorageError):
        storage.get_or_create_kek()
    # delete_kek ne doit jamais lever (idempotent, silencieux).
    storage.delete_kek()


def test_linux_secret_service_refuse_hors_linux(monkeypatch):
    monkeypatch.setattr("sys.platform", "darwin")
    storage = LinuxSecretServiceStorage()
    with pytest.raises(KeyStorageError):
        storage.get_or_create_kek()
    storage.delete_kek()  # silencieux


def test_linux_secret_service_lookup_puis_store(monkeypatch):
    monkeypatch.setattr("sys.platform", "linux")
    storage = LinuxSecretServiceStorage()
    calls: list[list[str]] = []

    def fake_run(args, stdin=None, **kwargs):
        calls.append(list(args))
        result = MagicMock()
        if args[0] == "lookup":
            result.returncode = 1  # rien trouvé
            result.stdout = b""
        else:
            result.returncode = 0
            result.stdout = b""
        return result

    monkeypatch.setattr(storage, "_run", fake_run)
    kek = storage.get_or_create_kek()
    assert len(kek) == 32
    assert calls[0][0] == "lookup"
    assert calls[1][0] == "store"
    # Un second appel doit retourner le même kek (via lookup).
    calls.clear()

    def fake_run2(args, stdin=None, **kwargs):
        calls.append(list(args))
        result = MagicMock()
        result.returncode = 0
        result.stdout = kek
        return result

    monkeypatch.setattr(storage, "_run", fake_run2)
    assert storage.get_or_create_kek() == kek


# ---------------------------------------------------------------- autostart


def test_autostart_supported_macos():
    assert autostart_supported() is True


def test_autostart_lancement_commande():
    cmd = _launch_command()
    assert cmd[1:] == ["-m", "veyra.app"]


def test_macos_plist_contenu_valide():
    xml = _macos_plist_content()
    assert "com.veyra.app" in xml
    assert "<key>RunAtLoad</key>" in xml
    assert "veyra.app" in xml


def test_macos_autostart_enable_disable(monkeypatch, tmp_path):
    monkeypatch.setattr("sys.platform", "darwin")
    # Path.home() utilise HOME sur POSIX.
    monkeypatch.setenv("HOME", str(tmp_path))
    # Aucun appel réel à launchctl : on simule un échec bénin.
    fake = MagicMock()
    fake.returncode = 1
    fake.stdout = ""
    fake.stderr = "bootstrap simulé (test)"
    monkeypatch.setattr("subprocess.run", lambda *a, **k: fake)
    plist = tmp_path / "Library" / "LaunchAgents" / "com.veyra.app.plist"
    # bootstrap launchctl échouera (mock) mais le plist doit être écrit
    # et l'état détecté — chargement au prochain login réel.
    assert set_autostart(True) is True
    assert plist.is_file()
    assert is_autostart_enabled() is True
    assert set_autostart(False) is True
    assert not plist.exists()
    assert is_autostart_enabled() is False


def test_autostart_desactive_par_defaut(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    assert is_autostart_enabled() is False
