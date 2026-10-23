# tests/test_calibration_v02.py
"""Tests V0.2 : calibration locale des seuils (courbe FAR/FRR, EER)."""

from __future__ import annotations

import pytest

from veyra.modules.face_guard.calibration import (
    CurvePoint,
    calibrate,
    equal_error_point,
    far_frr_curve,
    merge_samples,
)


def test_curve_separations_parfaites():
    """Genuine serrés à 0.3, impostors à 1.0 -> FAR/FRR nuls entre les deux."""
    genuine = [0.30, 0.32, 0.28, 0.31]
    impostors = [0.95, 1.02, 0.98, 1.10]
    curve = far_frr_curve(genuine, impostors, thresholds=[0.5, 0.7])
    assert all(p.far == 0.0 and p.frr == 0.0 for p in curve)


def test_curve_chevauchement():
    genuine = [0.4, 0.5, 0.6]
    impostors = [0.5, 0.6, 0.7]
    curve = far_frr_curve(genuine, impostors, thresholds=[0.55])
    point = curve[0]
    # impostors <= 0.55 : 0.5 -> FAR = 1/3
    assert abs(point.far - 1 / 3) < 1e-9
    # genuine > 0.55 : 0.6 -> FRR = 1/3
    assert abs(point.frr - 1 / 3) < 1e-9


def test_curve_vide():
    assert far_frr_curve([], [], thresholds=[0.5]) == (
        CurvePoint(threshold=0.5, far=0.0, frr=0.0),)


def test_eer_seuil_parfaitement_separe():
    genuine = [0.2, 0.25, 0.3]
    impostors = [1.0, 1.1, 1.2]
    curve = far_frr_curve(genuine, impostors,
                          thresholds=[0.3, 0.5, 0.7, 0.9, 1.05])
    eep = equal_error_point(curve)
    assert eep is not None
    _threshold, eer = eep
    assert eer == 0.0  # séparation parfaite -> EER nul


def test_eer_curve_vide():
    assert equal_error_point(()) is None


def test_calibrate_compte():
    genuine = [0.3, 0.35]
    impostors = [0.9, 1.0, 1.1]
    summary = calibrate(genuine, impostors)
    assert summary.genuine_count == 2
    assert summary.impostor_count == 3
    assert summary.suggested_threshold is not None
    assert 0.0 <= summary.eer <= 1.0


def test_calibrate_aucun_impostor():
    """Sans impostor, FAR = 0 partout ; EER = point où FRR minimal."""
    summary = calibrate([0.3, 0.31, 0.32], [])
    assert summary.suggested_threshold is not None  # toujours un minimum
    assert all(p.far == 0.0 for p in summary.curve)


def test_merge_samples_borne():
    existing = {"genuine": [1.0] * 490, "impostor": []}
    incoming = {"genuine": [2.0] * 20, "impostor": [3.0]}
    merged = merge_samples(existing, incoming, cap=500)
    assert len(merged["genuine"]) == 500
    assert len(merged["impostor"]) == 1
    assert merged["genuine"][-1] == 2.0


def test_merge_samples_conserve_les_plus_recents():
    merged = merge_samples({"genuine": [1, 2, 3]}, {"genuine": [4, 5]}, cap=4)
    assert merged["genuine"] == [2, 3, 4, 5]


def test_curve_point_est_immuable():
    import dataclasses

    p = CurvePoint(threshold=0.5, far=0.1, frr=0.2)
    with pytest.raises(dataclasses.FrozenInstanceError):
        p.far = 0.9  # type: ignore[misc]
