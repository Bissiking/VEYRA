# tests/test_scenarios.py
"""Scénarios d'intrusion de bout en bout, SANS caméra (flux synthétiques).

Ces tests valident la chaîne complète :
décision -> session_guard -> coupe-circuit -> plateforme (jamais appelée en SIMULATION).
"""

from __future__ import annotations


import pytest

from veyra.core.engine import SurveillanceEngine
from veyra.core.events import Event, EventType
from veyra.core.module_manager import ModuleManager
from veyra.core.policy import IdentityState, ProtectionMode
from veyra.core.safety import ActionExecutor, SafetyCircuit
from veyra.modules.session_guard.module import SessionGuardModule
from tests.conftest import FakeLocker


@pytest.fixture
def rig(bus, clock, policy):
    """Chaîne décision -> verrouillage avec plateforme instrumentée."""
    locker = FakeLocker()
    circuit = SafetyCircuit(bus)
    executor = ActionExecutor(circuit, locker, bus)
    session = SessionGuardModule(bus, executor)
    engine = SurveillanceEngine(bus, policy, clock=clock)

    manager = ModuleManager(bus)
    manager.register(session)
    session.start()

    outcomes = []
    bus.subscribe(EventType.LOCK_OUTCOME, lambda e: outcomes.append(e.data))

    yield {
        "bus": bus, "clock": clock, "policy": policy, "locker": locker,
        "circuit": circuit, "executor": executor, "session": session,
        "engine": engine, "outcomes": outcomes,
    }
    engine.stop()
    session.stop()


def activity(rig) -> None:
    rig["bus"].publish(Event(EventType.ACTIVITY_DETECTED, source="activity_guard"))


def face(rig, state: IdentityState) -> None:
    rig["bus"].publish(Event(EventType.FACE_OBSERVATION, source="face_guard",
                             data={"state": state.value}))


def camera(rig, ok: bool) -> None:
    rig["bus"].publish(Event(EventType.CAMERA_STATUS, source="face_guard", data={"ok": ok}))


# ---------------------------------------------------------------- scénarios

def test_intrusion_confirmee_simulee_sans_verrouiller(rig):
    """Intrus actif + visage inconnu confirmé -> décision calculée, verrou SIMULÉ."""
    assert rig["circuit"].mode is ProtectionMode.SIMULATION  # défaut

    activity(rig)
    camera(rig, True)
    face(rig, IdentityState.UNKNOWN)

    rig["clock"].advance(1.5)
    assert rig["engine"].tick() is None
    rig["clock"].advance(1.0)
    record = rig["engine"].tick()

    assert record is not None and record.decision.value == "LOCK_SESSION"
    assert rig["locker"].calls == 0  # JAMAIS d'appel plateforme
    assert rig["outcomes"] and rig["outcomes"][-1]["simulated"] is True
    assert rig["session"].info().metrics["lock_requests"] == 1


def test_meme_scenario_en_protection_verrouille_reellement(rig):
    """Même moteur, mode PROTECTION explicite -> verrouillage réel exécuté."""
    rig["circuit"].enable_protection(True)

    activity(rig)
    camera(rig, True)
    face(rig, IdentityState.UNKNOWN)
    rig["clock"].advance(3.0)
    record = rig["engine"].tick()

    assert record is not None and record.decision.value == "LOCK_SESSION"
    assert rig["locker"].calls == 1
    assert rig["outcomes"][-1]["executed"] is True


def test_proprietaire_reconnu_ne_verrouille_rien(rig):
    activity(rig)
    camera(rig, True)
    face(rig, IdentityState.TRUSTED)
    rig["clock"].advance(10)
    assert rig["engine"].tick() is None
    assert rig["locker"].calls == 0
    assert rig["outcomes"] == []


def test_scenario_sans_webcam_proprietaire_absent_avec_activite(rig):
    """Caméra indisponible au démarrage, propriétaire jamais vu, activité humaine :
    la politique bascule sur la règle caméra après la première absence constatée.

    Ici l'absence est initiée par une observation NO_FACE préalable (possible
    même sans caméra via un épisode d'analyse précédent) ; la suite du scénario
    (camera KO + reprise d'activité) est couverte par test_engine.
    """
    camera(rig, False)        # webcam indisponible
    face(rig, IdentityState.NO_FACE)  # aucune présence vérifiée
    activity(rig)

    rig["clock"].advance(3.0)
    record = rig["engine"].tick()
    # Webcam KO + absence constatée + activité -> LOCK simulé (politique active).
    assert record is not None and record.decision.value == "LOCK_SESSION"
    assert rig["locker"].calls == 0
    assert rig["outcomes"][-1]["simulated"] is True


def test_inactivite_prolongee_ne_verrouille_jamais(rig):
    """Pas d'activité, pas de visage : la session reste maintenue, aucun lock."""
    face(rig, IdentityState.NO_FACE)
    camera(rig, True)
    rig["clock"].advance(120)
    records = [rig["engine"].tick() for _ in range(4)]
    locks = [r for r in records if r and r.decision.value == "LOCK_SESSION"]
    assert locks == []
    assert rig["locker"].calls == 0


def test_session_guard_ignore_les_decisions_non_lock(rig):
    rig["bus"].publish(Event(EventType.DECISION, source="engine", data={
        "decision": "MAINTAIN_SESSION", "reason": "x",
    }))
    assert rig["session"].info().metrics["lock_requests"] == 0
    assert rig["locker"].calls == 0
