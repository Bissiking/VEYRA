# tests/test_storage.py
"""Tests de persistance : configuration, événements, profils chiffrés."""

from __future__ import annotations

import numpy as np
import pytest

from veyra.core.policy import SecurityPolicy
from veyra.storage.biometrics import (BiometricVault, KeyStorageError,
                                      SealedEmbedding, UnavailableKeyStorage)
from veyra.storage.config import ConfigStore
from veyra.storage.database import Database


class MemoryKeyStorage:
    """Coffre clés factice pour les tests (pas de Keychain réel)."""

    def __init__(self) -> None:
        self.key: bytes | None = None
        self.deleted = False

    def get_or_create_kek(self) -> bytes:
        if self.key is None:
            self.key = b"\x11" * 32
        return self.key

    def delete_kek(self) -> None:
        self.key = None
        self.deleted = True


@pytest.fixture
def db():
    database = Database(":memory:")
    yield database
    database.close()


# ------------------------------------------------------------------ settings

def test_settings_roundtrip(db):
    store = ConfigStore(db)
    store.set_camera_index(2)
    assert store.get_camera_index() == 2
    store.set_camera_index(0)
    assert store.get_camera_index() == 0


def test_policy_roundtrip(db):
    store = ConfigStore(db)
    policy = SecurityPolicy(idle_threshold_s=25.0, confirm_window_s=4.0,
                            lock_on_unknown_face_with_activity=False)
    store.save_policy(policy)
    loaded = store.load_policy()
    assert loaded.idle_threshold_s == 25.0
    assert loaded.confirm_window_s == 4.0
    assert loaded.lock_on_unknown_face_with_activity is False


def test_policy_invalide_ne_crash_pas(db):
    store = ConfigStore(db)
    db.set_setting("config.policy", "pas-du-json")
    policy = store.load_policy()
    assert isinstance(policy, SecurityPolicy)  # retombe sur les défauts


def test_policy_from_dict_ignore_clues_inconnues():
    policy = SecurityPolicy.from_dict({"idle_threshold_s": 7, "cle_unknown": 42})
    assert policy.idle_threshold_s == 7


# -------------------------------------------------------------------- events

def test_events_persists(db):
    db.add_event(1712345678.0, "decision", "engine", "LOCK_SESSION : raison",
                 severity="warning", details_json='{"decision":"LOCK_SESSION"}')
    rows = db.recent_events(limit=10)
    assert len(rows) == 1
    assert rows[0]["message"] == "LOCK_SESSION : raison"
    assert rows[0]["severity"] == "warning"
    assert db.clear_events() == 1
    assert db.recent_events() == []


# ------------------------------------------------------------------ profils

def test_profile_save_get_delete(db):
    db.save_profile("owner", "Propriétaire", b"blob", "{}")
    row = db.get_profile("owner")
    assert row is not None and row["display_name"] == "Propriétaire"
    # upsert
    db.save_profile("owner", "Renommé", b"blob2", "{}")
    assert db.get_profile("owner")["display_name"] == "Renommé"
    assert db.delete_profile("owner") is True
    assert db.get_profile("owner") is None
    assert db.delete_profile("owner") is False


# ---------------------------------------------------------------- biométrie

def test_vault_chiffre_et_dechiffre():
    vault = BiometricVault(MemoryKeyStorage())
    assert vault.available is True
    plaintext = np.random.rand(128).astype(np.float32).tobytes()
    sealed = vault.seal(plaintext)
    assert isinstance(sealed, SealedEmbedding)
    # Rien de lisible dans le JSON sérialisé
    assert plaintext[:8].hex() not in sealed.to_json()
    reopened = SealedEmbedding.from_json(sealed.to_json())
    assert vault.open(reopened) == plaintext


def test_vault_echec_si_cle_changee():
    storage = MemoryKeyStorage()
    vault = BiometricVault(storage)
    sealed = vault.seal(b"data")
    storage.key = b"\x22" * 32  # remplacement de la clé (ex. Keychain vidé)
    # Nouveau vault = nouvelle session : recharge la KEK actuelle du coffre.
    vault2 = BiometricVault(storage)
    with pytest.raises(KeyStorageError):
        vault2.open(sealed)


def test_vault_destroy_efface_la_cle():
    storage = MemoryKeyStorage()
    vault = BiometricVault(storage)
    vault.seal(b"data")
    vault.destroy()
    assert storage.deleted is True
    assert storage.key is None


def test_keystorage_indisponible_refuse_tout():
    vault = BiometricVault(UnavailableKeyStorage("TestOS"))
    assert vault.available is False
    with pytest.raises(KeyStorageError):
        vault.seal(b"data")
