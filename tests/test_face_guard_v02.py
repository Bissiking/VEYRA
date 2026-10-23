# tests/test_face_guard_v02.py
"""Tests V0.2 du module FaceGuard : dégradation anti-spoofing + calibration.

Le pipeline et la caméra sont mockés — aucune webcam, aucun modèle ONNX.
"""

from __future__ import annotations

import numpy as np

from veyra.core.events import Event, EventType
from veyra.core.policy import IdentityState, SecurityPolicy
from veyra.modules.face_guard.liveness import LivenessTracker
from veyra.modules.face_guard.module import FaceGuardModule
from veyra.modules.face_guard.pipeline import DetectedFace, PipelineResult


class _FakeCamera:
    """Caméra factice : une frame noire 100x100 toujours disponible."""

    def __init__(self):
        self.available = True

    def latest(self):
        return 0.0, np.zeros((100, 100, 3), dtype=np.uint8)

    def latest_frame(self):
        return np.zeros((100, 100, 3), dtype=np.uint8)

    def start(self):
        pass

    def stop(self):
        pass

    def set_index(self, index):
        pass


class _FakePipeline:
    """Pipeline factice : renvoie un résultat préprogrammé."""

    def __init__(self, result: PipelineResult | None = None) -> None:
        self.result = result or PipelineResult(IdentityState.NO_FACE)
        self.loaded_ok = True

    def load(self) -> bool:
        return self.loaded_ok

    @property
    def error(self) -> str:
        return ""

    def process(self, frame, policy, reference) -> PipelineResult:
        return self.result


def _make_module(bus, policy, pipeline_result=None) -> FaceGuardModule:
    module = FaceGuardModule(bus, policy, camera_index=0)
    module._camera = _FakeCamera()  # remplace la vraie caméra
    module._pipeline = _FakePipeline(pipeline_result)
    return module


def _face(state=IdentityState.TRUSTED, distance=0.3, texture=100.0,
          landmarks=None) -> DetectedFace:
    face = DetectedFace(x=0.25, y=0.25, w=0.5, h=0.5, score=0.9,
                        w_px=50, h_px=50)
    face.state = state
    face.distance = distance
    face.texture = texture
    face.landmarks = landmarks if landmarks is not None else np.array(
        [[40, 40], [60, 40], [50, 55], [42, 70], [58, 70]], dtype=np.float32)
    return face


def test_analyse_sans_anti_spoofing_publie_etat_trusted(bus):
    policy = SecurityPolicy(anti_spoofing_enabled=False)
    result = PipelineResult(IdentityState.TRUSTED, faces=[_face()])
    module = _make_module(bus, policy, result)
    events: list[Event] = []
    bus.subscribe(EventType.FACE_OBSERVATION, events.append)
    module._analyze_once()
    assert events
    assert events[-1].data["state"] == "TRUSTED"
    assert "spoof_suspect" not in events[-1].data


def test_anti_spoofing_publie_metrique_spoof(bus):
    policy = SecurityPolicy(anti_spoofing_enabled=True)
    result = PipelineResult(IdentityState.TRUSTED, faces=[_face()])
    module = _make_module(bus, policy, result)
    events: list[Event] = []
    bus.subscribe(EventType.FACE_OBSERVATION, events.append)
    module._analyze_once()
    assert events
    assert "spoof_suspect" in events[-1].data
    assert "blinks" in events[-1].data


def test_trusted_degrade_en_unknown_si_suspect(bus, monkeypatch):
    policy = SecurityPolicy(anti_spoofing_enabled=True,
                            liveness_window_s=1.0, liveness_min_blinks=1)
    result = PipelineResult(IdentityState.TRUSTED, faces=[_face(texture=5.0)])
    module = _make_module(bus, policy, result)
    # Remplit le tracker manuellement : assez d'obs, aucun blink, texture basse.
    module._liveness = LivenessTracker(window_s=1.0, min_blinks=1,
                                       min_openness=0.12, min_texture=40.0)
    for i in range(8):
        module._liveness.observe(i * 0.5, 0.30, 5.0)
    # Aligne time.monotonic sur la dernière observation synthétique (3.5) pour
    # que la fenêtre glissante ne purge pas l'historique.
    monkeypatch.setattr("time.monotonic", lambda: 4.0)
    assert module._liveness.snapshot().suspect is True
    events: list[Event] = []
    bus.subscribe(EventType.FACE_OBSERVATION, events.append)
    module._analyze_once()
    assert events[-1].data["state"] == "UNKNOWN"
    assert events[-1].data["spoof_suspect"] is True


def test_trusted_non_degrade_si_passe_suspect(bus):
    """Tracker non suspect -> TRUSTED inchangé."""
    policy = SecurityPolicy(anti_spoofing_enabled=True)
    result = PipelineResult(IdentityState.TRUSTED, faces=[_face(texture=100.0)])
    module = _make_module(bus, policy, result)
    module._liveness = LivenessTracker(window_s=1.0, min_blinks=1,
                                       min_openness=0.12, min_texture=40.0)
    # Tracker vide -> pas suspect (pas assez de données).
    events: list[Event] = []
    bus.subscribe(EventType.FACE_OBSERVATION, events.append)
    module._analyze_once()
    assert events[-1].data["state"] == "TRUSTED"


def test_calibration_collecte_trusted_et_unknown(bus):
    policy = SecurityPolicy(anti_spoofing_enabled=False)
    result = PipelineResult(IdentityState.TRUSTED, faces=[
        _face(state=IdentityState.TRUSTED, distance=0.3)])
    module = _make_module(bus, policy, result)
    module.start_calibration()
    module._analyze_once()
    # Un visage UNKNOWN avec distance.
    result2 = PipelineResult(IdentityState.UNKNOWN, faces=[
        _face(state=IdentityState.UNKNOWN, distance=0.9)])
    module._pipeline.result = result2
    module._analyze_once()
    samples = module.stop_calibration()
    assert samples["genuine"] == [0.3]
    assert samples["impostor"] == [0.9]
    assert module.calibrating is False


def test_calibration_inactive_ne_collecte_rien(bus):
    policy = SecurityPolicy(anti_spoofing_enabled=False)
    result = PipelineResult(IdentityState.TRUSTED, faces=[
        _face(state=IdentityState.TRUSTED, distance=0.3)])
    module = _make_module(bus, policy, result)
    module._analyze_once()
    samples = module.stop_calibration()
    assert samples == {"genuine": [], "impostor": []}


def test_reconfigure_tracker_via_set_policy(bus):
    policy = SecurityPolicy(anti_spoofing_enabled=True,
                            liveness_window_s=8.0, liveness_min_blinks=1)
    module = _make_module(bus, policy)
    new_policy = SecurityPolicy(anti_spoofing_enabled=True,
                                liveness_window_s=15.0, liveness_min_blinks=3)
    module.set_policy(new_policy)
    # Le tracker du module doit avoir repris les nouvelles valeurs.
    snap = module._liveness.snapshot()  # vide, mais pas d'erreur
    assert snap.observations == 0
