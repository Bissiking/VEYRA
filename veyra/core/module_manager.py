# veyra/core/module_manager.py
"""Gestionnaire des modules VEYRA : enregistrement, démarrage, arrêt, statuts."""

from __future__ import annotations

import logging
import threading

from veyra.core.events import Event, EventBus, EventType
from veyra.core.module_api import IVeyraModule, ModuleInfo, ModuleState

logger = logging.getLogger(__name__)


class ModuleManager:
    """Détient le registre des modules et orchestre leur cycle de vie."""

    def __init__(self, bus: EventBus) -> None:
        self._bus = bus
        self._lock = threading.RLock()
        self._modules: dict[str, IVeyraModule] = {}

    def register(self, module: IVeyraModule) -> None:
        with self._lock:
            if module.module_id in self._modules:
                raise ValueError(f"Module déjà enregistré : {module.module_id}")
            self._modules[module.module_id] = module
        logger.info("Module enregistré : %s (%s)", module.module_id, module.name)

    def start_all(self) -> None:
        for module in self._snapshot():
            try:
                module.start()
            except Exception:
                logger.exception("Échec de démarrage du module %s", module.module_id)
                self._publish_status(module, fallback_state=ModuleState.ERROR,
                                     detail="échec au démarrage")
            else:
                self._publish_status(module)

    def start_module(self, module_id: str) -> bool:
        """Démarre un module individuel (depuis la GUI). Retourne le succès."""
        module = self.get(module_id)
        if module is None:
            return False
        try:
            module.start()
        except Exception:
            logger.exception("Échec de démarrage du module %s", module_id)
            self._publish_status(module, fallback_state=ModuleState.ERROR,
                                 detail="échec au démarrage")
            return False
        self._publish_status(module)
        return True

    def stop_module(self, module_id: str) -> bool:
        """Arrête un module individuel (depuis la GUI)."""
        module = self.get(module_id)
        if module is None:
            return False
        try:
            module.stop()
        except Exception:
            logger.exception("Échec d'arrêt du module %s", module_id)
            return False
        self._publish_status(module)
        return True

    def stop_all(self) -> None:
        for module in reversed(self._snapshot()):
            try:
                module.stop()
            except Exception:
                logger.exception("Échec d'arrêt du module %s", module.module_id)
            else:
                self._publish_status(module)

    def get(self, module_id: str) -> IVeyraModule | None:
        with self._lock:
            return self._modules.get(module_id)

    def infos(self) -> list[ModuleInfo]:
        result: list[ModuleInfo] = []
        for module in self._snapshot():
            try:
                result.append(module.info())
            except Exception:
                logger.exception("Échec de lecture du statut du module %s", module.module_id)
                result.append(ModuleInfo(module.module_id, module.name, ModuleState.ERROR,
                                         detail="statut indisponible"))
        return result

    def _snapshot(self) -> list[IVeyraModule]:
        with self._lock:
            return list(self._modules.values())

    def _publish_status(self, module: IVeyraModule,
                        fallback_state: ModuleState | None = None,
                        detail: str = "") -> None:
        try:
            info = module.info()
            if fallback_state is not None:
                info = ModuleInfo(info.module_id, info.name, fallback_state,
                                  detail=detail or info.detail, metrics=info.metrics)
        except Exception:
            info = ModuleInfo(module.module_id, module.name,
                              fallback_state or ModuleState.ERROR, detail=detail)
        self._bus.publish(Event(EventType.MODULE_STATUS, source=module.module_id, data={
            "state": info.state.value,
            "detail": info.detail,
            "metrics": info.metrics,
        }))
