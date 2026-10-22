# tests/test_gui_smoke.py
"""Smoke test GUI offscreen : chaque page se construit et se rafraîchit.

S'exécute avec QT_QPA_PLATFORM=offscreen (aucune fenêtre réelle, aucune caméra
nécessaire). Saute si PySide6 n'est pas installé.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6", reason="PySide6 absent")


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


def test_fenetre_principale_construite(qapp, tmp_path):
    from veyra.bootstrap import AppContext
    from veyra.gui import theme
    from veyra.gui.bridge import GuiBridge
    from veyra.gui.main_window import MainWindow

    theme.apply_theme(qapp)
    ctx = AppContext(tmp_path / "gui.db")
    ctx.revert_to_simulation()
    bridge = GuiBridge(ctx.bus)
    window = MainWindow(ctx, bridge)
    window.show()
    qapp.processEvents()

    try:
        assert window._pages.count() == 5  # 5 pages de navigation
        for i in range(5):
            window._pages.setCurrentIndex(i)
            qapp.processEvents()
            page = window._pages.widget(i)
            if hasattr(page, "refresh"):
                page.refresh()
            qapp.processEvents()
        assert ctx.circuit.mode.value == "SIMULATION"
    finally:
        window._really_quit = True
        window.close()
        bridge.shutdown()
        ctx.stop()


def test_fermeture_masque_sans_quitter(qapp, tmp_path):
    """La fermeture de la fenêtre ne doit pas arrêter le contexte."""
    from veyra.bootstrap import AppContext
    from veyra.gui import theme
    from veyra.gui.bridge import GuiBridge
    from veyra.gui.main_window import MainWindow

    theme.apply_theme(qapp)
    ctx = AppContext(tmp_path / "gui2.db")
    bridge = GuiBridge(ctx.bus)
    window = MainWindow(ctx, bridge)
    window.show()
    qapp.processEvents()

    try:
        window.close()  # sans quit -> masquage seulement
        qapp.processEvents()
        assert not window.isVisible()
        # Le contexte n'est PAS arrêté par la fermeture de fenêtre.
        assert window._really_quit is False
    finally:
        window._really_quit = True
        window.close()
        bridge.shutdown()
        ctx.stop()
