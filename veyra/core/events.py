# veyra/core/events.py
"""Bus d'événements interne et types d'événements.

Tous les modules communiquent avec le noyau exclusivement via ce bus.
Les événements ne contiennent jamais de données biométriques brutes
(images, empreintes) ni de contenu de frappe/souris.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

logger = logging.getLogger(__name__)


class EventType(str, Enum):
    """Types d'événements circulant dans le bus."""

    # Activité utilisateur (jamais le détail des touches)
    ACTIVITY_DETECTED = "activity_detected"
    ACTIVITY_STREAM_STATUS = "activity_stream_status"

    # Caméra / visage
    CAMERA_STATUS = "camera_status"
    FACE_OBSERVATION = "face_observation"
    ANALYSIS_REQUEST = "analysis_request"
    ENROLLMENT_PROGRESS = "enrollment_progress"

    # Décisions et actions
    DECISION = "decision"
    LOCK_REQUEST = "lock_request"
    LOCK_OUTCOME = "lock_outcome"

    # Modules / système
    MODULE_STATUS = "module_status"
    PROTECTION_MODE_CHANGED = "protection_mode_changed"
    ENGINE_STATE = "engine_state"


@dataclass(frozen=True)
class Event:
    """Événement générique publié sur le bus."""

    type: EventType
    source: str
    timestamp: float = field(default_factory=time.time)
    data: dict[str, Any] = field(default_factory=dict)

    def __repr__(self) -> str:  # évite d'imprimer des payloads sensibles
        return f"Event({self.type.value}, source={self.source}, data_keys={sorted(self.data)})"


Subscriber = Callable[[Event], None]


class EventBus:
    """Bus d'événements thread-safe, pub/sub.

    Les abonnements se font par type d'événement ou pour tous les types
    (``EventType`` n'acceptant pas de wildcard : passer ``None``).
    Une exception dans un abonné est journalisée sans interrompre les autres.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._subscribers: dict[EventType | None, list[Subscriber]] = defaultdict(list)

    def subscribe(self, event_type: EventType | None, callback: Subscriber) -> Callable[[], None]:
        """Abonne ``callback``. Retourne une fonction de désabonnement."""
        with self._lock:
            self._subscribers[event_type].append(callback)

        def unsubscribe() -> None:
            with self._lock:
                try:
                    self._subscribers[event_type].remove(callback)
                except ValueError:
                    pass

        return unsubscribe

    def publish(self, event: Event) -> None:
        """Publie un événement vers tous les abonnés concernés."""
        with self._lock:
            targets = list(self._subscribers.get(event.type, [])) + list(self._subscribers.get(None, []))
        for callback in targets:
            try:
                callback(event)
            except Exception:
                logger.exception("Erreur dans un abonné EventBus (%s)", event.type.value)
