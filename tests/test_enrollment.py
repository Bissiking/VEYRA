# tests/test_enrollment.py
"""Tests de la session d'enrôlement (sans caméra, vault mémoire)."""

from __future__ import annotations

import numpy as np
import pytest

from veyra.core.policy import SecurityPolicy
from veyra.modules.face_guard.enrollment import (EnrollmentSession, EnrollmentStage,
                                                 PROFILE_USER_KEY, ProfileRepository)
from veyra.modules.face_guard.models import ModelPaths, default_models_dir
from veyra.storage.biometrics import BiometricVault, UnavailableKeyStorage
from veyra.storage.database import Database
from tests.test_storage import MemoryKeyStorage

paths = ModelPaths(default_models_dir())
requires_models = pytest.mark.skipif(
    bool(paths.missing()),
    reason="modèles ONNX absents -> python scripts/download_models.py",
)


@pytest.fixture
def db():
    database = Database(":memory:")
    yield database
    database.close()


def make_session(db, bus, vault: BiometricVault, policy: SecurityPolicy | None = None):
    from veyra.modules.face_guard.pipeline import FacePipeline
    return EnrollmentSession(
        policy=policy or SecurityPolicy(enrollment_samples=3),
        pipeline=FacePipeline(paths),  # non chargé => start() refuse proprement
        vault=vault,
        db=db,
        bus=bus,
    )


# --------------------------------------------------------------- démarrage

def test_start_refuse_sans_vault_disponible(db, bus):
    vault = BiometricVault(UnavailableKeyStorage("TestOS"))
    session = make_session(db, bus, vault)
    assert session.start(lambda: None) is False
    assert session.progress.stage is EnrollmentStage.FAILED
    assert "Coffre de clés" in session.progress.message


def test_start_refuse_si_pipeline_non_charge(db, bus):
    vault = BiometricVault(MemoryKeyStorage())
    session = make_session(db, bus, vault)
    assert session.start(lambda: None) is False
    assert session.progress.stage is EnrollmentStage.FAILED


def test_progress_publie_sur_le_bus(db, bus):
    vault = BiometricVault(UnavailableKeyStorage("TestOS"))
    session = make_session(db, bus, vault)
    events = []
    from veyra.core.events import EventType
    bus.subscribe(EventType.ENROLLMENT_PROGRESS, lambda e: events.append(e.data))
    session.start(lambda: None)
    assert events and events[-1]["stage"] == "FAILED"


def test_annulation_sans_thread_est_saine(db, bus):
    vault = BiometricVault(MemoryKeyStorage())
    session = make_session(db, bus, vault)
    session.cancel()  # aucun thread : ne doit pas lever
    assert session.busy is False


# ----------------------------------------------------- utilitaires purs

def test_moyenne_est_normalisee():
    a = np.ones(128, dtype=np.float32)
    b = np.zeros(128, dtype=np.float32)
    b[0] = 2.0
    mean = EnrollmentSession._average([a, b])
    assert mean.dtype == np.float32
    assert abs(float(np.linalg.norm(mean)) - 1.0) < 1e-5


def test_diversite_angles():
    assert EnrollmentSession._is_diverse((0.0, 0.0), []) is True
    assert EnrollmentSession._is_diverse((0.0, 0.0), [(0.0, 0.0)]) is False
    assert EnrollmentSession._is_diverse((0.1, 0.0), [(0.0, 0.0)]) is True


def test_indice_orientation():
    assert EnrollmentSession._hint((-0.1, 0.0)) == "Tournez vers la gauche."
    assert EnrollmentSession._hint((0.1, 0.0)) == "Tournez vers la droite."
    assert EnrollmentSession._hint((0.0, 0.0)).startswith("Inclinez")


# ------------------------------------------------------------ repository

def test_repository_sans_profil(db):
    vault = BiometricVault(MemoryKeyStorage())
    repo = ProfileRepository(db, vault)
    assert repo.has_profile() is False
    assert repo.reference() is None


def test_repository_roundtrip_profil(db):
    vault = BiometricVault(MemoryKeyStorage())
    repo = ProfileRepository(db, vault)
    embedding = np.random.rand(128).astype(np.float32)
    sealed = vault.seal(embedding.tobytes())
    db.save_profile(PROFILE_USER_KEY, "Propriétaire",
                    sealed.to_json().encode(), "{}")

    assert repo.has_profile() is True
    loaded = repo.reference()
    assert loaded is not None
    assert np.allclose(loaded, embedding, atol=1e-6)


def test_repository_suppression_complete(db):
    vault_storage = MemoryKeyStorage()
    vault = BiometricVault(vault_storage)
    repo = ProfileRepository(db, vault)
    sealed = vault.seal(np.ones(128, dtype=np.float32).tobytes())
    db.save_profile(PROFILE_USER_KEY, "P", sealed.to_json().encode(), "{}")

    assert repo.delete_profile() is True
    repo.destroy_vault()
    assert repo.has_profile() is False
    assert vault_storage.deleted is True
