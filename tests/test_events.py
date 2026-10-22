# tests/test_events.py
"""Tests du bus d'événements (pub/sub, isolation des exceptions, filtres)."""

from __future__ import annotations

from veyra.core.events import Event, EventType


def test_publie_vers_abonne_type(bus):
    received = []
    bus.subscribe(EventType.DECISION, received.append)
    bus.publish(Event(EventType.DECISION, source="engine", data={"a": 1}))
    bus.publish(Event(EventType.ACTIVITY_DETECTED, source="act"))
    assert len(received) == 1
    assert received[0].data == {"a": 1}


def test_abonnement_general(bus):
    received = []
    bus.subscribe(None, received.append)
    bus.publish(Event(EventType.DECISION, source="e"))
    bus.publish(Event(EventType.CAMERA_STATUS, source="f"))
    assert len(received) == 2


def test_desabonnement(bus):
    received = []
    unsub = bus.subscribe(EventType.DECISION, received.append)
    bus.publish(Event(EventType.DECISION, source="e"))
    unsub()
    bus.publish(Event(EventType.DECISION, source="e"))
    assert len(received) == 1


def test_exception_abonne_ne_bloque_pas_les_autres(bus):
    good = []

    def bad(event):
        raise RuntimeError("abonné défaillant")

    bus.subscribe(EventType.DECISION, bad)
    bus.subscribe(EventType.DECISION, good.append)
    bus.publish(Event(EventType.DECISION, source="e"))
    assert len(good) == 1


def test_event_repr_ne_montre_pas_le_payload(bus):
    event = Event(EventType.FACE_OBSERVATION, source="f",
                  data={"embedding": [0.1] * 8, "state": "TRUSTED"})
    assert "embedding" not in repr(event) or "data_keys" in repr(event)
    assert "[0.1" not in repr(event)


def test_evenement_horsodates_defaut():
    e = Event(EventType.DECISION, source="x")
    assert e.timestamp > 0 and e.data == {}
