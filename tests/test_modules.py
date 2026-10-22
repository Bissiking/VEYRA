# tests/test_modules.py
"""Tests du gestionnaire de modules et des interfaces de module."""

from __future__ import annotations

import pytest

from veyra.core.module_api import IVeyraModule, ModuleInfo, ModuleState
from veyra.core.module_manager import ModuleManager


class DummyModule(IVeyraModule):
    module_id = "dummy"
    name = "Module factice"

    def __init__(self, fail_start: bool = False, module_id: str | None = None) -> None:
        if module_id is not None:
            self.module_id = module_id
        self.fail_start = fail_start
        self.started = False
        self.stopped = False

    def start(self) -> None:
        if self.fail_start:
            raise RuntimeError("démarrage impossible")
        self.started = True

    def stop(self) -> None:
        self.stopped = True

    def info(self) -> ModuleInfo:
        state = ModuleState.RUNNING if self.started and not self.stopped else ModuleState.STOPPED
        return ModuleInfo(self.module_id, self.name, state)


def test_enregistrement_et_doublon(bus):
    manager = ModuleManager(bus)
    manager.register(DummyModule())
    with pytest.raises(ValueError):
        manager.register(DummyModule())


def test_start_all_stop_all(bus):
    manager = ModuleManager(bus)
    module = DummyModule()
    manager.register(module)
    manager.start_all()
    assert module.started
    manager.stop_all()
    assert module.stopped


def test_demarrage_echoue_ne_monte_pas(bus):
    manager = ModuleManager(bus)
    bad = DummyModule(fail_start=True, module_id="bad")
    good = DummyModule(module_id="good")
    manager.register(bad)
    manager.register(good)
    manager.start_all()  # ne doit pas lever
    assert not bad.started and good.started


def test_start_stop_individuel(bus):
    manager = ModuleManager(bus)
    module = DummyModule()
    manager.register(module)
    assert manager.start_module("dummy") is True
    assert module.started
    assert manager.stop_module("dummy") is True
    assert module.stopped
    assert manager.start_module("inconnu") is False
    assert manager.stop_module("inconnu") is False


def test_infos_reflete_etats(bus):
    manager = ModuleManager(bus)
    module = DummyModule()
    manager.register(module)
    infos = manager.infos()
    assert len(infos) == 1 and infos[0].state is ModuleState.STOPPED
    manager.start_module("dummy")
    assert manager.infos()[0].state is ModuleState.RUNNING


def test_infos_sur_erreur_info(bus):
    class ExplodingInfo(DummyModule):
        def info(self):
            raise RuntimeError("état illisible")

    manager = ModuleManager(bus)
    manager.register(ExplodingInfo())
    infos = manager.infos()
    assert infos[0].state is ModuleState.ERROR
