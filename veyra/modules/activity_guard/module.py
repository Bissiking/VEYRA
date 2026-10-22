# veyra/modules/activity_guard/module.py
"""Module Activity Guard : publie des événements d'activité sur le bus.

Aucun détail de frappe/souris n'est capturé ni transmis (voir ``stream.py``).
"""

from __future__ import annotations

import logging
import time

from veyra.core.events import Event, EventBus, EventType
from veyra.core.module_api import IVeyraModule, ModuleInfo, ModuleState
from veyra.platforms.base import PlatformAdapter
from veyra.modules.activity_guard.stream import ActivityStream

logger = logging.getLogger(__name__)


class ActivityGuardModule(IVeyraModule):
    module_id = "activity_guard"
    name = "Activité (clavier/souris)"

    def __init__(self, bus: EventBus, platform: PlatformAdapter) -> None:
        self._bus = bus
        self._platform = platform
        self._stream: ActivityStream | None = None
        self._state = ModuleState.STOPPED
        self._detail = ""
        self._events_count = 0
        self._last_activity_ts = 0.0

    def start(self) -> None:
        if self._state in (ModuleState.RUNNING, ModuleState.STARTING):
            return
        self._state = ModuleState.STARTING
        stream = self._platform.create_activity_stream()
        if stream is None:
            self._state = ModuleState.UNAVAILABLE
            self._detail = "Flux d'activité non disponible sur cette plateforme (V0.1)."
            logger.warning("%s : %s", self.name, self._detail)
            self._publish_status()
            return
        ok = stream.start(self._on_activity)
        self._stream = stream
        if ok:
            self._state = ModuleState.RUNNING
            self._detail = "Écoute active — aucun contenu enregistré."
        else:
            self._state = ModuleState.DEGRADED
            self._detail = stream.last_error or "Démarrage du flux d'activité refusé."
        self._publish_status()

    def stop(self) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream = None
        self._state = ModuleState.STOPPED
        self._detail = ""
        self._publish_status()

    def info(self) -> ModuleInfo:
        metrics: dict[str, object] = {"events": self._events_count}
        if self._last_activity_ts:
            metrics["last_activity_age_s"] = round(time.time() - self._last_activity_ts, 1)
        return ModuleInfo(self.module_id, self.name, self._state, self._detail, metrics)

    # ------------------------------------------------------------ interne

    def _on_activity(self) -> None:
        self._events_count += 1
        self._last_activity_ts = time.time()
        self._bus.publish(Event(EventType.ACTIVITY_DETECTED, source=self.module_id))

    def _publish_status(self) -> None:
        info = self.info()
        self._bus.publish(Event(EventType.MODULE_STATUS, source=self.module_id, data={
            "state": info.state.value,
            "detail": info.detail,
            "metrics": info.metrics,
        }))

    def inject_activity_for_tests(self) -> None:
        """Aide de test : simule une activité sans flux réel."""
        self._on_activity()
