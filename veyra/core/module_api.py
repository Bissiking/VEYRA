# veyra/core/module_api.py
"""Interfaces communes des modules VEYRA.

Un module :
- ne verrouille JAMAIS la session directement ;
- communique avec le noyau via l'EventBus ;
- expose son statut pour la GUI.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ModuleState(str, Enum):
    STOPPED = "STOPPED"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    DEGRADED = "DEGRADED"   # fonctionne partiellement (ex. permission manquante)
    ERROR = "ERROR"
    UNAVAILABLE = "UNAVAILABLE"  # non supporté sur cette plateforme


@dataclass(frozen=True)
class ModuleInfo:
    """Instantané du statut d'un module pour la GUI / les journaux."""

    module_id: str
    name: str
    state: ModuleState
    detail: str = ""
    metrics: dict[str, Any] = field(default_factory=dict)


class IVeyraModule(ABC):
    """Interface que tout module doit implémenter."""

    module_id: str = "abstract"
    name: str = "Module abstrait"

    @abstractmethod
    def start(self) -> None:
        """Démarre le module (thread-safe, non bloquant)."""

    @abstractmethod
    def stop(self) -> None:
        """Arrête le module et libère ses ressources."""

    @abstractmethod
    def info(self) -> ModuleInfo:
        """Retourne l'état courant du module."""
