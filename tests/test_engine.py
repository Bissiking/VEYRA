# tests/test_engine.py
"""Tests unitaires du moteur de décision adaptatif (sans caméra, horloge fake)."""

from __future__ import annotations

import pytest

from veyra.core.engine import SurveillanceEngine
from veyra.core.events import Event, EventType
from veyra.core.policy import Decision, IdentityState, SecurityPolicy, SurveillanceMode


def publish_activity(bus) -> None:
    bus.publish(Event(EventType.ACTIVITY_DETECTED, source="activity_guard"))


def publish_face(bus, state: IdentityState) -> None:
    bus.publish(Event(EventType.FACE_OBSERVATION, source="face_guard",
                      data={"state": state.value}))


def publish_camera(bus, ok: bool) -> None:
    bus.publish(Event(EventType.CAMERA_STATUS, source="face_guard", data={"ok": ok}))


@pytest.fixture
def engine(bus, clock, policy) -> SurveillanceEngine:
    eng = SurveillanceEngine(bus, policy, clock=clock)
    yield eng
    eng.stop()


# ----------------------------------------------------------------- rythme

def test_passe_en_mode_leger_apres_seuil(engine, clock, bus):
    publish_activity(bus)
    clock.advance(5)
    assert engine.tick() is None
    assert engine.mode is SurveillanceMode.ACTIVE

    clock.advance(6)  # > idle_threshold_s (10)
    engine.tick()
    assert engine.mode is SurveillanceMode.LIGHT


def test_reprise_active_retablit_mode_actif(engine, clock, bus):
    publish_activity(bus)
    clock.advance(11)
    engine.tick()
    assert engine.mode is SurveillanceMode.LIGHT

    publish_activity(bus)
    assert engine.mode is SurveillanceMode.PRIORITY

    # La priorité est consommée après une durée d'analyse active.
    clock.advance(engine._policy.active_analysis_interval_s)
    engine.tick()
    assert engine.mode is SurveillanceMode.ACTIVE


def test_analyse_prioritaire_publiee_sur_reprise(engine, clock, bus):
    requests = []
    bus.subscribe(EventType.ANALYSIS_REQUEST, lambda e: requests.append(e.data))
    publish_activity(bus)
    clock.advance(11)
    engine.tick()
    requests.clear()

    publish_activity(bus)
    assert requests and requests[-1]["priority"] is True


# ------------------------------------------------------- règle 3 : inconnu

def test_verrouillage_apres_confirmation_inconnu_active(engine, clock, bus):
    decisions = []
    bus.subscribe(EventType.DECISION, lambda e: decisions.append(e.data))

    publish_activity(bus)
    publish_camera(bus, True)
    publish_face(bus, IdentityState.UNKNOWN)

    # Avant la fenêtre de confirmation : rien.
    clock.advance(1.5)
    assert engine.tick() is None

    # Après la fenêtre (2 s) : LOCK_SESSION.
    clock.advance(1.0)
    record = engine.tick()
    assert record is not None
    assert record.decision is Decision.LOCK_SESSION
    assert record.reason == "unknown_face_confirmed_with_activity"
    assert decisions[-1]["decision"] == "LOCK_SESSION"

    # Un seul verrouillage par épisode d'inconnu.
    clock.advance(5)
    assert engine.tick() is None


def test_pas_de_verrouillage_si_activite_arrete_inconnu(engine, clock, bus):
    publish_face(bus, IdentityState.UNKNOWN)  # jamais d'activité utilisateur
    publish_camera(bus, True)
    clock.advance(30)
    record = engine.tick()
    # Règle 4 : absence inconnue sans activité -> maintien, pas de verrouillage.
    assert record is not None
    assert record.decision is Decision.MAINTAIN_SESSION


def test_visage_confiant_reinitialise_suspicion(engine, clock, bus):
    publish_activity(bus)
    publish_camera(bus, True)
    publish_face(bus, IdentityState.UNKNOWN)
    clock.advance(1.5)
    assert engine.tick() is None

    publish_face(bus, IdentityState.TRUSTED)  # le propriétaire réapparaît
    clock.advance(2)
    assert engine.tick() is None
    assert engine.identity is IdentityState.TRUSTED


# ------------------------------------------------- règle 4 : webcam perdue

def test_verrouillage_webcam_apres_absence_puis_activite(engine, clock, bus):
    publish_activity(bus)
    publish_camera(bus, True)
    publish_face(bus, IdentityState.TRUSTED)
    engine.tick()

    # Le propriétaire s'absente.
    publish_face(bus, IdentityState.NO_FACE)
    clock.advance(11)  # inactivité -> mode léger
    engine.tick()

    # La webcam tombe pendant l'absence.
    publish_camera(bus, False)

    # Quelqu'un devient actif -> analyse prioritaire + verrouillage policy.
    publish_activity(bus)
    record = engine.tick()
    assert record is not None
    assert record.decision is Decision.LOCK_SESSION
    assert record.reason == "camera_unavailable_after_absence_with_activity"


def test_politique_camera_desactivee_bloque_la_regle(engine, clock, bus):
    engine.update_policy(SecurityPolicy(lock_on_camera_loss_after_absence=False))
    publish_activity(bus)
    publish_camera(bus, True)
    publish_face(bus, IdentityState.TRUSTED)
    engine.tick()
    publish_face(bus, IdentityState.NO_FACE)
    clock.advance(11)
    engine.tick()
    publish_camera(bus, False)
    publish_activity(bus)
    assert engine.tick() is None


# ------------------------------------------------ règle 5 : maintien session

def test_absence_sans_activite_maintient_session(engine, clock, bus):
    publish_activity(bus)
    publish_camera(bus, True)
    publish_face(bus, IdentityState.TRUSTED)
    engine.tick()

    publish_face(bus, IdentityState.NO_FACE)
    clock.advance(11)
    record = engine.tick()
    assert record is not None
    assert record.decision is Decision.MAINTAIN_SESSION
    assert record.reason == "owner_absent_without_activity"

    # Un seul MAINTAIN par épisode d'absence.
    clock.advance(5)
    assert engine.tick() is None


def test_trust_obsolete_si_camera_perdue(engine, clock, bus):
    # TRUSTED puis perte caméra : le statut de confiance devient obsolète.
    publish_camera(bus, True)
    publish_face(bus, IdentityState.TRUSTED)
    publish_camera(bus, False)
    assert engine.identity is IdentityState.UNDETERMINED
