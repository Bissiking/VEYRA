# veyra/core/safety.py
"""Coupe-circuit de sécurité : modes SIMULATION / PROTECTION et exécuteur unique.

Toute action sensible (verrouillage de session) DOIT passer par
``ActionExecutor``. L'exécuteur vérifie le mode avant chaque exécution :

- SIMULATION (défaut à chaque démarrage) : la demande est calculée,
  journalisée, mais **aucune action réelle n'est exécutée**.
- PROTECTION : nécessite une confirmation explicite ; les décisions
  autorisées sont déléguées à la plateforme.

Aucun module applicatif ne doit appeler directement un adaptateur
plateforme pour verrouiller la session.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Protocol

from veyra.core.events import Event, EventBus, EventType
from veyra.core.policy import ProtectionMode

logger = logging.getLogger(__name__)


class PlatformLocker(Protocol):
    """Interface minimale attendue d'un adaptateur plateforme pour le verrouillage."""

    def lock_session(self) -> bool: ...


@dataclass(frozen=True)
class LockRequest:
    """Demande de verrouillage émise par le moteur de décision."""

    reason: str
    source: str
    metadata: dict[str, object]


@dataclass(frozen=True)
class LockOutcome:
    """Résultat d'une demande passée au coupe-circuit."""

    executed: bool
    simulated: bool
    mode: ProtectionMode
    reason: str


class SafetyCircuit:
    """Détient le mode de protection et valide les transitions de mode."""

    def __init__(self, bus: EventBus) -> None:
        self._lock = threading.RLock()
        self._mode = ProtectionMode.SIMULATION  # toujours SIMULATION au démarrage
        self._bus = bus

    @property
    def mode(self) -> ProtectionMode:
        with self._lock:
            return self._mode

    def enable_protection(self, confirmation: bool) -> bool:
        """Passe en mode PROTECTION. ``confirmation`` doit être True (explicite).

        Retourne True si le mode a été activé.
        """
        if not confirmation:
            logger.warning("Activation PROTECTION refusée : confirmation explicite absente.")
            return False
        with self._lock:
            if self._mode is ProtectionMode.PROTECTION:
                return True
            self._mode = ProtectionMode.PROTECTION
        logger.warning("Mode PROTECTION activé : les verrouillages sont désormais réels.")
        self._bus.publish(Event(EventType.PROTECTION_MODE_CHANGED, source="safety",
                                data={"mode": ProtectionMode.PROTECTION.value}))
        return True

    def revert_to_simulation(self) -> None:
        """Revenir (ou rester) en SIMULATION. Action toujours autorisée."""
        with self._lock:
            if self._mode is ProtectionMode.SIMULATION:
                return
            self._mode = ProtectionMode.SIMULATION
        logger.info("Mode SIMULATION rétabli : aucun verrouillage réel ne sera exécuté.")
        self._bus.publish(Event(EventType.PROTECTION_MODE_CHANGED, source="safety",
                                data={"mode": ProtectionMode.SIMULATION.value}))


class ActionExecutor:
    """Exécuteur unique des actions sensibles.

    C'est le SEUL point du système autorisé à déclencher un verrouillage
    réel de session. Toute demande est journalisée dans les deux modes.
    """

    def __init__(self, circuit: SafetyCircuit, locker: PlatformLocker, bus: EventBus) -> None:
        self._circuit = circuit
        self._locker = locker
        self._bus = bus
        self._lock = threading.RLock()

    def request_lock(self, request: LockRequest) -> LockOutcome:
        """Traite une demande de verrouillage selon le mode courant."""
        mode = self._circuit.mode
        with self._lock:
            if mode is ProtectionMode.SIMULATION:
                logger.info("[SIMULATION] Verrouillage simulé : %s (source=%s)",
                            request.reason, request.source)
                outcome = LockOutcome(executed=False, simulated=True, mode=mode,
                                      reason=request.reason)
            else:
                try:
                    ok = bool(self._locker.lock_session())
                except Exception:
                    logger.exception("Échec du verrouillage réel de la session.")
                    ok = False
                logger.warning("Verrouillage %s : %s (source=%s)",
                               "réalisé" if ok else "échoué", request.reason, request.source)
                outcome = LockOutcome(executed=ok, simulated=False, mode=mode,
                                      reason=request.reason)

        self._bus.publish(Event(EventType.LOCK_OUTCOME, source="executor", data={
            "executed": outcome.executed,
            "simulated": outcome.simulated,
            "mode": outcome.mode.value,
            "reason": outcome.reason,
            "request_source": request.source,
        }))
        return outcome
