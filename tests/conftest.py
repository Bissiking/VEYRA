# tests/conftest.py
"""Fixtures communes des tests VEYRA (aucune caméra, aucun keychain réel)."""

from __future__ import annotations


import pytest

from veyra.core.events import EventBus
from veyra.core.policy import SecurityPolicy


class FakeClock:
    """Horloge monotonic pilotée manuellement pour les tests du moteur."""

    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> float:
        self.now += seconds
        return self.now


@pytest.fixture
def bus() -> EventBus:
    return EventBus()


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def policy() -> SecurityPolicy:
    return SecurityPolicy()


class FakeLocker:
    """Plateforme de verrouillage instrumentée pour vérifier le coupe-circuit."""

    def __init__(self, fail: bool = False, boom: bool = False) -> None:
        self.calls = 0
        self.fail = fail
        self.boom = boom

    def lock_session(self) -> bool:
        self.calls += 1
        if self.boom:
            raise RuntimeError("lock_service crashe")
        return not self.fail


@pytest.fixture
def fake_locker() -> FakeLocker:
    return FakeLocker()
