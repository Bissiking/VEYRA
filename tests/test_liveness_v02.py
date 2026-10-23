# tests/test_liveness_v02.py
"""Tests V0.2 : anti-spoofing (LivenessTracker, eye_openness, texture)."""

from __future__ import annotations

import numpy as np

from veyra.modules.face_guard.liveness import (
    LivenessSnapshot,
    LivenessTracker,
    eye_openness,
    texture_score,
)

# ------------------------------------------------------------- tracker blink


def test_tracker_vide_nest_pas_suspect():
    tracker = LivenessTracker(window_s=2.0, min_blinks=1)
    snap = tracker.snapshot()
    assert snap.observations == 0
    assert snap.suspect is False
    assert snap.enough_data is False


def test_tracker_clignement_compte():
    tracker = LivenessTracker(window_s=2.0, min_blinks=1,
                              min_openness=0.12, min_texture=40.0)
    # ouvert -> ferme -> ouvre = 1 clignement, texture bonne.
    tracker.observe(0.0, 0.30, 100.0)
    tracker.observe(0.1, 0.05, 100.0)
    tracker.observe(0.2, 0.30, 100.0)
    snap = tracker.snapshot()
    assert snap.blinks == 1
    assert snap.suspect is False


def test_tracker_sans_clignement_et_texture_basse_suspect():
    tracker = LivenessTracker(window_s=1.0, min_blinks=1,
                              min_openness=0.12, min_texture=40.0)
    # Horodatages binaires-exacts (0.5) pour éviter les bornes flottantes.
    for i in range(8):  # 0.0 .. 3.5
        tracker.observe(i * 0.5, 0.30, 10.0)
    snap = tracker.snapshot()
    assert snap.enough_data is True
    assert snap.blinks == 0
    assert snap.suspect is True


def test_tracker_texture_basse_seule_insuffisante():
    """Un seul signal au maximum n'élève pas de suspicion (faux positifs)."""
    tracker = LivenessTracker(window_s=2.0, min_blinks=1,
                              min_openness=0.12, min_texture=40.0)
    # Texture basse MAIS clignement dans la fenêtre -> pas suspect.
    for i in range(6):  # 0.0 .. 2.5 (texture basse, ouvert)
        tracker.observe(i * 0.5, 0.30, 10.0)
    tracker.observe(3.0, 0.05, 10.0)   # ferme
    tracker.observe(3.5, 0.30, 10.0)   # ouvre -> blink (toujours dans la fenêtre)
    snap = tracker.snapshot()
    assert snap.blinks >= 1
    assert snap.suspect is False


def test_tracker_clignement_seul_insuffisant():
    """Texture bonne mais aucun clignement -> pas suspect (visage figé)."""
    tracker = LivenessTracker(window_s=1.0, min_blinks=1,
                              min_openness=0.12, min_texture=40.0)
    for i in range(8):
        tracker.observe(i * 0.5, 0.30, 100.0)
    snap = tracker.snapshot()
    assert snap.blinks == 0
    assert snap.suspect is False  # texture haute -> pas de suspicion


def test_tracker_prune_anciennes_observations():
    tracker = LivenessTracker(window_s=1.0, min_blinks=1)
    tracker.observe(0.0, 0.30, 100.0)
    tracker.observe(10.0, 0.30, 100.0)  # 10 s plus tard -> l'ancienne est purgée
    assert tracker.snapshot().observations == 1


def test_tracker_reset():
    tracker = LivenessTracker(window_s=1.0)
    tracker.observe(0.0, 0.05, 10.0)
    tracker.reset()
    assert tracker.snapshot().observations == 0


def test_tracker_reconfigure_conserve_historique():
    tracker = LivenessTracker(window_s=1.0, min_blinks=1)
    tracker.observe(0.0, 0.30, 100.0)
    tracker.reconfigure(window_s=5.0, min_blinks=2,
                        min_openness=0.1, min_texture=30.0)
    assert tracker.snapshot().observations == 1


def test_snapshot_est_immuable():
    tracker = LivenessTracker(window_s=1.0)
    tracker.observe(0.0, 0.30, 100.0)
    snap = tracker.snapshot()
    assert isinstance(snap, LivenessSnapshot)


# ---------------------------------------------------------- mesures images


def test_eye_openness_image_uniforme_faible():
    """Un ROI uniforme (œil fermé) a un contraste ~0."""
    frame = np.full((200, 200, 3), 120, dtype=np.uint8)
    assert eye_openness(frame, 100, 100, 100) < 0.05


def test_eye_openness_image_contrastee():
    """Un ROI avec pupille sombre + sclère claire a un contraste élevé."""
    frame = np.full((200, 200, 3), 200, dtype=np.uint8)
    # pupille sombre au centre
    frame[95:105, 95:105] = 20
    assert eye_openness(frame, 100, 100, 100) > 0.2


def test_eye_openness_hors_image():
    frame = np.zeros((50, 50, 3), dtype=np.uint8)
    assert eye_openness(frame, -10, -10, 100) == 0.0


def test_texture_score_image_lisse():
    """Dégradé lisse (photo imprimée) -> variance faible."""
    ramp = np.tile(np.linspace(0, 255, 100, dtype=np.uint8), (100, 1))
    frame = np.stack([ramp] * 3, axis=-1)
    assert texture_score(frame, 0, 0, 100, 100) < 50.0


def test_texture_score_image_texturee():
    """Bruit fin (peau réelle) -> variance élevée."""
    rng = np.random.default_rng(42)
    frame = rng.integers(0, 255, size=(100, 100, 3), dtype=np.uint8)
    assert texture_score(frame, 0, 0, 100, 100) > 1000.0


def test_texture_score_hors_image():
    frame = np.zeros((50, 50, 3), dtype=np.uint8)
    assert texture_score(frame, -10, -10, 10, 10) == 0.0
