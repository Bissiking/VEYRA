# veyra/modules/session_guard/module.py
"""Module Session Guard : seul relais entre décisions et coupe-circuit.

Rôle :
- écouter les ``DECISION`` du moteur ;
- pour ``LOCK_SESSION`` : formuler une ``LockRequest`` et la confier à
  ``ActionExecutor`` (le SEUL point autorisé à verrouiller réellement) ;
- journaliser l'état verrouillé/déverrouillé pour la GUI.

Le module ne détient AUCUN accès direct à la plateforme : même en mode
PROTECTION, il ne peut passer qu'par l'exécuteur.
"""

from __future__ import annotations

import logging

from veyra.core.events import Event, EventBus, EventType
from veyra.core.module_api import IVeyraModule, ModuleInfo, ModuleState
from veyra.core.policy import Decision
from veyra.core.safety import ActionExecutor, LockRequest

logger = logging.getLogger(__name__)


class SessionGuardModule(IVeyraModule):
    module_id = "session_guard"
    name = "Verrouillage de session"

    def __init__(self, bus: EventBus, executor: ActionExecutor) -> None:
        self._bus = bus
        self._executor = executor
        self._state = ModuleState.STOPPED
        self._detail = "En écoute des décisions."
        self._lock_requests = 0
        self._last_outcome: str = ""
        self._unsub = None

    def start(self) -> None:
        if self._state is ModuleState.RUNNING:
            return
        self._unsub = self._bus.subscribe(EventType.DECISION, self._on_decision)
        self._state = ModuleState.RUNNING
        self._detail = "Relais actif vers l'exécuteur de sécurité."
        self._publish_status()

    def stop(self) -> None:
        if self._unsub is not None:
            self._unsub()
            self._unsub = None
        self._state = ModuleState.STOPPED
        self._detail = ""
        self._publish_status()

    def info(self) -> ModuleInfo:
        return ModuleInfo(
            self.module_id, self.name, self._state, self._detail,
            metrics={
                "lock_requests": self._lock_requests,
                "last_outcome": self._last_outcome,
            },
        )

    # ------------------------------------------------------------ interne

    def _on_decision(self, event: Event) -> None:
        try:
            decision = Decision(event.data.get("decision", Decision.NONE.value))
        except ValueError:
            return
        if decision is not Decision.LOCK_SESSION:
            return
        reason = str(event.data.get("reason", "unknown"))
        self._lock_requests += 1
        outcome = self._executor.request_lock(LockRequest(
            reason=reason,
            source="session_guard",
            metadata={"identity": event.data.get("identity", ""),
                      "mode": event.data.get("mode", "")},
        ))
        self._last_outcome = "simulé" if outcome.simulated else (
            "exécuté" if outcome.executed else "échoué")
        logger.info("LockRequest -> %s", self._last_outcome)
        self._publish_status()

    def _publish_status(self) -> None:
        info = self.info()
        self._bus.publish(Event(EventType.MODULE_STATUS, source=self.module_id, data={
            "state": info.state.value,
            "detail": info.detail,
            "metrics": info.metrics,
        }))
