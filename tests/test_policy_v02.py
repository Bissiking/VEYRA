# tests/test_policy_v02.py
"""Tests V0.2 : persistance des nouveaux champs de SecurityPolicy."""

from __future__ import annotations

from veyra.core.policy import SecurityPolicy


def test_nouveaux_champs_presents_dans_to_dict():
    policy = SecurityPolicy()
    data = policy.to_dict()
    for key in ("anti_spoofing_enabled", "liveness_window_s",
                "liveness_min_blinks", "liveness_min_openness",
                "liveness_min_texture"):
        assert key in data


def test_roundtrip_nouveaux_champs():
    policy = SecurityPolicy(
        anti_spoofing_enabled=False,
        liveness_window_s=12.5,
        liveness_min_blinks=2,
        liveness_min_openness=0.2,
        liveness_min_texture=80.0,
    )
    restored = SecurityPolicy.from_dict(policy.to_dict())
    assert restored.anti_spoofing_enabled is False
    assert restored.liveness_window_s == 12.5
    assert restored.liveness_min_blinks == 2
    assert restored.liveness_min_openness == 0.2
    assert restored.liveness_min_texture == 80.0


def test_ancien_dict_sans_nouveaux_champs_utilise_defauts():
    """Un dict V0.1 persisté (sans les clés V0.2) doit charger proprement."""
    old = SecurityPolicy().to_dict()
    for key in ("anti_spoofing_enabled", "liveness_window_s",
                "liveness_min_blinks", "liveness_min_openness",
                "liveness_min_texture"):
        old.pop(key, None)
    restored = SecurityPolicy.from_dict(old)
    defaults = SecurityPolicy()
    assert restored.anti_spoofing_enabled == defaults.anti_spoofing_enabled
    assert restored.liveness_window_s == defaults.liveness_window_s


def test_defauts_veut_anti_spoofing_actif():
    assert SecurityPolicy().anti_spoofing_enabled is True
