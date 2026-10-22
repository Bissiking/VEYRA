# tests/test_bootstrap.py
"""Tests d'intégration du contexte applicatif (démarrage/arrêt, mode forcé)."""

from __future__ import annotations

import time

import pytest

from veyra.bootstrap import AppContext
from veyra.core.policy import ProtectionMode, SecurityPolicy


@pytest.fixture
def ctx(tmp_path):
    context = AppContext(tmp_path / "test.db")
    yield context
    context.stop()


def test_mode_simulation_forge_au_demarrage(ctx):
    assert ctx.circuit.mode is ProtectionMode.SIMULATION


def test_demarrage_arret_cycle_complet(ctx):
    ctx.start()
    time.sleep(0.6)
    infos = ctx.modules.infos()
    # face_guard peut être en ERROR si modèles absents : c'est un état explicite.
    states = {i.module_id: i.state.value for i in infos}
    assert states["session_guard"] == "RUNNING"
    assert states["activity_guard"] in ("RUNNING", "DEGRADED", "UNAVAILABLE")
    ctx.stop()


def test_protection_exige_confirmation(ctx):
    assert ctx.enable_protection(confirmed=False) is False
    assert ctx.circuit.mode is ProtectionMode.SIMULATION
    assert ctx.enable_protection(confirmed=True) is True
    assert ctx.circuit.mode is ProtectionMode.PROTECTION
    ctx.revert_to_simulation()
    assert ctx.circuit.mode is ProtectionMode.SIMULATION


def test_apply_policy_persiste(ctx):
    policy = SecurityPolicy(idle_threshold_s=42.0, confirm_window_s=3.0)
    ctx.apply_policy(policy)
    assert ctx.config.load_policy().idle_threshold_s == 42.0
    assert ctx.engine._policy.confirm_window_s == 3.0
    assert ctx.face_guard._policy.idle_threshold_s == 42.0


def test_evenements_persistes_sur_le_bus(ctx):
    from veyra.core.events import Event, EventType
    ctx.start()
    ctx.bus.publish(Event(EventType.FACE_OBSERVATION, source="test",
                          data={"state": "TRUSTED"}))
    time.sleep(0.2)
    rows = ctx.db.recent_events(limit=10)
    assert any(r["type"] == "face_observation" for r in rows)
    # Aucune donnée biométrique ne transite par SQLite.
    for row in rows:
        assert "embedding" not in str(row["details"]).lower()
    ctx.stop()


def test_suppression_profil_biometrique(ctx, monkeypatch):
    # Simule un profil sans dépendre du Keychain réel.
    ctx.profile_repo.has_profile = lambda: True
    deleted_profiles = []
    monkeypatch.setattr(ctx.profile_repo, "delete_profile", lambda: deleted_profiles.append(1) or True)
    assert ctx.delete_biometric_profile() is True
    assert deleted_profiles
