# tests/test_safety.py
"""Tests du coupe-circuit : SIMULATION n'exécute JAMAIS de verrouillage réel."""

from __future__ import annotations


from veyra.core.events import EventType
from veyra.core.policy import ProtectionMode
from veyra.core.safety import ActionExecutor, LockRequest, SafetyCircuit
from tests.conftest import FakeLocker


def make_executor(bus, locker: FakeLocker):
    circuit = SafetyCircuit(bus)
    executor = ActionExecutor(circuit, locker, bus)
    return circuit, executor


def test_mode_par_defaut_est_simulation(bus, fake_locker):
    circuit, _ = make_executor(bus, fake_locker)
    assert circuit.mode is ProtectionMode.SIMULATION


def test_simulation_ne_verrouille_jamais(bus, fake_locker):
    circuit, executor = make_executor(bus, fake_locker)
    outcomes = [executor.request_lock(LockRequest(reason="test", source="t", metadata={}))
                for _ in range(5)]
    assert all(o.simulated and not o.executed for o in outcomes)
    assert fake_locker.calls == 0  # le verrouillage réel n'a JAMAIS été appelé


def test_activation_protection_exige_confirmation(bus, fake_locker):
    circuit, executor = make_executor(bus, fake_locker)
    assert circuit.enable_protection(False) is False
    assert circuit.mode is ProtectionMode.SIMULATION
    # Même une fois « activée » sans confirmation, rien ne passe.
    executor.request_lock(LockRequest(reason="x", source="t", metadata={}))
    assert fake_locker.calls == 0

    assert circuit.enable_protection(True) is True
    assert circuit.mode is ProtectionMode.PROTECTION


def test_protection_execute_le_verrouillage(bus, fake_locker):
    circuit, executor = make_executor(bus, fake_locker)
    circuit.enable_protection(True)
    outcome = executor.request_lock(LockRequest(reason="intrusion", source="t", metadata={}))
    assert outcome.executed and not outcome.simulated
    assert fake_locker.calls == 1


def test_retour_simulation_libre(bus, fake_locker):
    circuit, executor = make_executor(bus, fake_locker)
    circuit.enable_protection(True)
    circuit.revert_to_simulation()
    executor.request_lock(LockRequest(reason="x", source="t", metadata={}))
    assert fake_locker.calls == 0


def test_echec_plateforme_signale(bus):
    locker = FakeLocker(fail=True)
    circuit, executor = make_executor(bus, locker)
    circuit.enable_protection(True)
    outcome = executor.request_lock(LockRequest(reason="x", source="t", metadata={}))
    assert not outcome.executed and not outcome.simulated


def test_exception_plateforme_ne_crashe_pas(bus):
    locker = FakeLocker(boom=True)
    circuit, executor = make_executor(bus, locker)
    circuit.enable_protection(True)
    outcome = executor.request_lock(LockRequest(reason="x", source="t", metadata={}))
    assert not outcome.executed


def test_lock_outcome_publie_sur_le_bus(bus, fake_locker):
    _, executor = make_executor(bus, fake_locker)
    received = []
    bus.subscribe(EventType.LOCK_OUTCOME, lambda e: received.append(e.data))
    executor.request_lock(LockRequest(reason="r", source="t", metadata={}))
    assert received and received[0]["simulated"] is True
    assert received[0]["mode"] == "SIMULATION"


def test_activations_successives_idempotentes(bus, fake_locker):
    circuit, _ = make_executor(bus, fake_locker)
    assert circuit.enable_protection(True) is True
    assert circuit.enable_protection(True) is True  # déjà actif
    assert circuit.mode is ProtectionMode.PROTECTION
