# tests/test_face_pipeline.py
"""Tests du pipeline faciale sans caméra : chargement, états, agrégation.

Utilise les modèles ONNX locaux s'ils sont présents ; sinon saute proprement
(les modèles ne sont pas versionnés dans le dépôt).
"""

from __future__ import annotations

import numpy as np
import pytest

from veyra.core.policy import IdentityState, SecurityPolicy
from veyra.modules.face_guard.models import ModelPaths, default_models_dir
from veyra.modules.face_guard.pipeline import DetectedFace, FacePipeline

paths = ModelPaths(default_models_dir())
requires_models = pytest.mark.skipif(
    bool(paths.missing()),
    reason="modèles ONNX absents -> python scripts/download_models.py",
)


@pytest.fixture(scope="module")
def pipeline() -> FacePipeline:
    pipe = FacePipeline(paths)
    assert pipe.load(), pipe.error
    return pipe


# --------------------------------------------------------------- chargement

def test_models_dir_resolu():
    assert default_models_dir().name == "models"


def test_missing_signale_telechargement(tmp_path):
    empty = ModelPaths(tmp_path)
    missing = empty.missing()
    assert len(missing) == 2
    assert "download_models.py" in empty.hint()


@requires_models
def test_pipeline_charge(pipeline):
    assert pipeline.loaded and pipeline.error == ""


def test_pipeline_sans_modele_refuse_clairement(tmp_path):
    pipe = FacePipeline(ModelPaths(tmp_path))
    assert pipe.load() is False
    assert "download_models.py" in pipe.error
    result = pipe.process(np.zeros((480, 640, 3), dtype=np.uint8),
                          SecurityPolicy(), None)
    assert result.state is IdentityState.UNDETERMINED
    assert "download_models.py" in result.detail


# ------------------------------------------------------------ inférence

@requires_models
def test_image_noire_retourne_no_face(pipeline):
    # Aucun visage dans une image uniforme.
    result = pipeline.process(np.zeros((480, 640, 3), dtype=np.uint8),
                              SecurityPolicy(), None)
    assert result.state is IdentityState.NO_FACE
    assert result.faces == []


@requires_models
def test_bruit_ne_detecte_pas_de_vrai_voisage(pipeline):
    rng = np.random.default_rng(42)
    noise = rng.integers(0, 255, size=(480, 640, 3), dtype=np.uint8)
    result = pipeline.process(noise, SecurityPolicy(), None)
    # Le bruit peut Produire des faux positifs de détection ; dans tous les cas,
    # sans empreinte de référence il n'y a JAMAIS de TRUSTED.
    assert result.state is not IdentityState.TRUSTED


# ------------------------------------------------------ classification unitaire

def _face(brightness: float = 120.0, w_px: int = 200, h_px: int = 200) -> DetectedFace:
    return DetectedFace(x=0.4, y=0.4, w=0.2, h=0.2, score=0.9,
                        w_px=w_px, h_px=h_px, brightness=brightness)


def test_classify_luminosite_insuffisante(pipeline):
    policy = SecurityPolicy()
    face = _face(brightness=policy.min_face_brightness - 1)
    assert pipeline._classify(face, np.ones(128, dtype=np.float32), policy) \
        is IdentityState.UNDETERMINED


def test_classify_visage_trop_petit(pipeline):
    policy = SecurityPolicy()
    face = _face(w_px=policy.min_face_size_px - 1)
    assert pipeline._classify(face, np.ones(128, dtype=np.float32), policy) \
        is IdentityState.UNDETERMINED


def test_classify_sans_profil_est_indetermine(pipeline):
    face = _face()
    assert pipeline._classify(face, None, SecurityPolicy()) is IdentityState.UNDETERMINED


def test_classify_par_distances(pipeline):
    policy = SecurityPolicy()
    reference = np.zeros(128, dtype=np.float32)
    reference[0] = 1.0

    confiant = _face()
    confiant.embedding = reference.copy()
    assert pipeline._classify(confiant, reference, policy) is IdentityState.TRUSTED

    loin = _face()
    loin.embedding = reference * -1.0
    assert pipeline._classify(loin, reference, policy) is IdentityState.UNKNOWN

    # Zone grise (seuil < d < seuil + marge) : on construit un vecteur
    # unitaire à la distance cible voulue (d = sqrt(2 - 2cos θ)).
    marge = _face()
    angle = np.zeros(128, dtype=np.float32)
    angle[1] = 1.0
    target_d = policy.recognition_threshold + policy.recognition_margin / 2
    cos_theta = 1.0 - (target_d ** 2) / 2.0  # distance euclidienne entre unitaires
    theta = float(np.arccos(np.clip(cos_theta, -1.0, 1.0)))
    marge.embedding = (reference * np.cos(theta) + angle * np.sin(theta)).astype(np.float32)
    d = float(np.linalg.norm(marge.embedding - reference))
    assert policy.recognition_threshold < d < policy.recognition_threshold + policy.recognition_margin
    assert pipeline._classify(marge, reference, policy) is IdentityState.UNDETERMINED


def test_classify_empreinte_absente(pipeline):
    face = _face()
    face.embedding = None
    assert pipeline._classify(face, np.ones(128, dtype=np.float32), SecurityPolicy()) \
        is IdentityState.UNDETERMINED


# --------------------------------------------------------------- agrégation

def test_aggregate_trust_prime():
    faces = [
        _face(),
        _face(),
    ]
    faces[0].state = IdentityState.UNKNOWN
    faces[1].state = IdentityState.TRUSTED
    assert FacePipeline._aggregate(faces) is IdentityState.TRUSTED


def test_aggregate_unknown_apres_trust_absent():
    faces = [_face(), _face()]
    faces[0].state = IdentityState.UNDETERMINED
    faces[1].state = IdentityState.UNKNOWN
    assert FacePipeline._aggregate(faces) is IdentityState.UNKNOWN


def test_aggregate_tous_indetermines():
    faces = [_face(), _face()]
    for f in faces:
        f.state = IdentityState.UNDETERMINED
    assert FacePipeline._aggregate(faces) is IdentityState.UNDETERMINED
