# veyra/storage/event_store.py
"""Journalisation persistante des événements (sans données biométriques sensibles)."""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from veyra.core.events import Event, EventBus, EventType
from veyra.storage.database import Database

logger = logging.getLogger(__name__)

# Les types suivants sont persistés (les autres restent dans les journaux texte).
_PERSISTED = {
    EventType.DECISION,
    EventType.LOCK_OUTCOME,
    EventType.PROTECTION_MODE_CHANGED,
    EventType.ENGINE_STATE,
    EventType.MODULE_STATUS,
    EventType.CAMERA_STATUS,
    EventType.FACE_OBSERVATION,
    EventType.ACTIVITY_STREAM_STATUS,
    EventType.ENROLLMENT_PROGRESS,
}


class EventStore:
    """S'abonne au bus et écrit les événements notables dans SQLite."""

    def __init__(self, bus: EventBus, db: Database) -> None:
        self._db = db
        self._unsub = bus.subscribe(None, self._on_event)

    def _on_event(self, event: Event) -> None:
        if event.type not in _PERSISTED:
            return
        severity = "warning" if event.type in (EventType.LOCK_OUTCOME,) else "info"
        try:
            self._db.add_event(
                ts=event.timestamp,
                type_=event.type.value,
                source=event.source,
                message=self._message_for(event),
                severity=severity,
                details_json=json.dumps(_sanitize(event.data), default=str),
            )
        except Exception:
            logger.exception("Échec de persistance de l'événement %s", event.type.value)

    @staticmethod
    def _message_for(event: Event) -> str:
        data = event.data
        if event.type is EventType.DECISION:
            return f"{data.get('decision')} : {data.get('reason')}"
        if event.type is EventType.LOCK_OUTCOME:
            if data.get("simulated"):
                return f"Verrouillage simulé : {data.get('reason')}"
            if data.get("executed"):
                return f"Verrouillage exécuté : {data.get('reason')}"
            return f"Verrouillage échoué : {data.get('reason')}"
        if event.type is EventType.PROTECTION_MODE_CHANGED:
            return f"Mode de protection : {data.get('mode')}"
        if event.type is EventType.ENGINE_STATE:
            return f"Moteur : mode {data.get('mode')}, identité {data.get('identity')}"
        if event.type is EventType.CAMERA_STATUS:
            return ("Caméra disponible" if data.get("ok") else "Caméra indisponible")
        if event.type is EventType.FACE_OBSERVATION:
            # L'état seul n'est pas sensible ; aucune empreinte ni coordonnée.
            return f"Observation faciale : {data.get('state')}"
        if event.type is EventType.MODULE_STATUS:
            return f"Module {event.source} : {data.get('state')}"
        if event.type is EventType.ACTIVITY_STREAM_STATUS:
            return f"Flux d'activité : {data.get('state')}"
        if event.type is EventType.ENROLLMENT_PROGRESS:
            return f"Enrôlement : {data.get('stage', '')} {data.get('progress', '')}"
        return event.type.value

    def close(self) -> None:
        self._unsub()


def _sanitize(data: dict[str, Any]) -> dict[str, Any]:
    """Supprime toute clé qui pourrait contenir une donnée sensible."""
    forbidden = {"embedding", "embeddings", "image", "frame", "keys", "raw"}
    return {k: v for k, v in data.items() if k.lower() not in forbidden}


def now() -> float:
    return time.time()
