# veyra/gui/bridge.py
"""Pont EventBus (threads) -> signaux Qt (thread principal GUI).

Les événements du bus arrivent depuis des threads arbitraires ; ce pont les
re-émet en ``Qt.QueuedConnection`` pour que la GUI ne soit jamais touchée
depuis un thread secondaire.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from veyra.core.events import Event, EventBus, EventType


class GuiBridge(QObject):
    """Traduit les événements VEYRA en signaux Qt typés."""

    # (type_str, source, data) — data = dict simple JSON-safe
    event = Signal(str, str, dict)
    enrollment_progress = Signal(dict)
    face_observation = Signal(dict)
    lock_outcome = Signal(dict)
    protection_mode = Signal(str)

    def __init__(self, bus: EventBus, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._unsubs = [
            bus.subscribe(EventType.ENROLLMENT_PROGRESS, self._forward_enrollment),
            bus.subscribe(EventType.FACE_OBSERVATION, self._forward_face),
            bus.subscribe(EventType.LOCK_OUTCOME, self._forward_lock),
            bus.subscribe(EventType.PROTECTION_MODE_CHANGED, self._forward_mode),
        ]
        self._bus_all = bus.subscribe(None, self._forward_all)

    def shutdown(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs = []
        self._bus_all()

    # ------------------------------------------------- abonnés (threads arb.)

    def _forward_all(self, event: Event) -> None:
        # Émis depuis un thread secondaire ; la connexion par défaut est queued
        # car la côte (GUI) vit dans le thread principal.
        self.event.emit(event.type.value, event.source, dict(event.data))

    def _forward_enrollment(self, event: Event) -> None:
        self.enrollment_progress.emit(dict(event.data))

    def _forward_face(self, event: Event) -> None:
        self.face_observation.emit(dict(event.data))

    def _forward_lock(self, event: Event) -> None:
        self.lock_outcome.emit(dict(event.data))

    def _forward_mode(self, event: Event) -> None:
        self.protection_mode.emit(str(event.data.get("mode", "")))
