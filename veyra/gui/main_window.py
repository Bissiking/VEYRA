# veyra/gui/main_window.py
"""Fenêtre principale VEYRA : navigation latérale + pages + tray.

Comportement de fermeture :
- fermer la fenêtre MASQUE l'application (la surveillance continue) ;
- la sortie complète demande une action explicite (menu Fichier > Quitter,
  ou « Quitter » du menu de la zone de notification).
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QCloseEvent
from PySide6.QtWidgets import (QButtonGroup, QHBoxLayout, QLabel, QMainWindow,
                               QMessageBox, QPushButton, QStackedWidget,
                               QSystemTrayIcon, QVBoxLayout, QWidget)

from veyra.gui import theme
from veyra.gui.bridge import GuiBridge
from veyra.gui.pages.dashboard import DashboardPage
from veyra.gui.pages.events_page import EventsPage
from veyra.gui.pages.modules_page import ModulesPage
from veyra.gui.pages.presence import PresencePage
from veyra.gui.pages.settings_page import SettingsPage

logger = logging.getLogger(__name__)

import veyra


class MainWindow(QMainWindow):
    """Fenêtre unique à navigation par pages (Dashboard / Présence / …)."""

    def __init__(self, ctx, bridge: GuiBridge) -> None:
        super().__init__()
        self._ctx = ctx
        self._bridge = bridge
        self._really_quit = False

        self.setWindowTitle(f"VEYRA {veyra.__version__} — sécurité locale")
        self.setMinimumSize(1024, 680)
        self.setWindowIcon(theme.make_app_icon())

        # ------------------------------------------------------------- layout
        central = QWidget()
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Barre latérale
        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(210)
        side_layout = QVBoxLayout(sidebar)
        side_layout.setContentsMargins(0, 0, 0, 12)
        side_layout.setSpacing(0)

        brand = QLabel("VEYRA")
        brand.setObjectName("brand")
        side_layout.addWidget(brand)
        version = QLabel(f"v{veyra.__version__} · local only")
        version.setObjectName("brandVersion")
        side_layout.addWidget(version)

        self._nav_group = QButtonGroup(self)
        self._nav_group.setExclusive(True)
        self._pages = QStackedWidget()
        pages_spec = [
            ("dashboard", "Tableau de bord", DashboardPage),
            ("presence", "Présence", PresencePage),
            ("modules", "Modules", ModulesPage),
            ("events", "Événements", EventsPage),
            ("settings", "Réglages", SettingsPage),
        ]
        self._nav_buttons: dict[str, QPushButton] = {}
        for index, (key, label, _cls) in enumerate(pages_spec):
            button = QPushButton(label)
            button.setObjectName("navButton")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            self._nav_group.addButton(button, index)
            self._nav_buttons[key] = button
            side_layout.addWidget(button)
        side_layout.addStretch(1)

        # statut discret en bas de la barre
        self._mode_label = QLabel("SIMULATION")
        self._mode_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._mode_label.setStyleSheet(theme.badge_stylesheet("warning"))
        side_layout.addWidget(self._mode_label, alignment=Qt.AlignmentFlag.AlignHCenter)

        self._pages.addWidget(DashboardPage(ctx, bridge))
        self._pages.addWidget(PresencePage(ctx, bridge))
        self._pages.addWidget(ModulesPage(ctx, bridge))
        self._pages.addWidget(EventsPage(ctx, bridge))
        settings_page = SettingsPage(ctx, bridge)
        self._pages.addWidget(settings_page)
        self._settings_page = settings_page

        self._nav_group.idClicked.connect(self._pages.setCurrentIndex)
        self._nav_group.button(0).setChecked(True)

        root.addWidget(sidebar)
        root.addWidget(self._pages, stretch=1)
        self.setCentralWidget(central)

        self._build_menus()
        self._build_tray()

        bridge.protection_mode.connect(self._on_mode_changed)
        bridge.lock_outcome.connect(self._on_lock_outcome)

    # --------------------------------------------------------------- menus

    def _build_menus(self) -> None:
        file_menu = self.menuBar().addMenu("&Fichier")

        act_show = QAction("Afficher la fenêtre", self)
        act_show.triggered.connect(self._show_window)
        file_menu.addAction(act_show)

        file_menu.addSeparator()
        act_quit = QAction("Quitter (arrêter la surveillance)", self)
        act_quit.setShortcut("Ctrl+Shift+Q")
        act_quit.triggered.connect(self.quit_app)
        file_menu.addAction(act_quit)

        help_menu = self.menuBar().addMenu("&Aide")
        act_about = QAction("À propos", self)
        act_about.triggered.connect(self._about)
        help_menu.addAction(act_about)

    # ---------------------------------------------------------------- tray

    def _build_tray(self) -> None:
        self._tray: QSystemTrayIcon | None = None
        if not QSystemTrayIcon.isSystemTrayAvailable():
            logger.warning("Icône de zone de notification indisponible.")
            return
        tray = QSystemTrayIcon(theme.make_app_icon(), self)
        tray.setToolTip(f"VEYRA {veyra.__version__} — surveillance locale active")

        from PySide6.QtWidgets import QMenu
        menu = QMenu()
        act_open = menu.addAction("Ouvrir VEYRA")
        act_open.triggered.connect(self._show_window)
        menu.addSeparator()
        act_quit = menu.addAction("Quitter complètement")
        act_quit.triggered.connect(self.quit_app)
        tray.setContextMenu(menu)
        tray.activated.connect(
            lambda reason: self._show_window()
            if reason == QSystemTrayIcon.ActivationReason.Trigger else None)
        tray.show()
        self._tray = tray

    def _on_lock_outcome(self, data: dict) -> None:
        if self._tray is None:
            return
        if data.get("simulated"):
            message = f"Verrouillage simulé : {data.get('reason', '')}"
        elif data.get("executed"):
            message = "Session verrouillée (mode PROTECTION)."
        else:
            message = f"Verrouillage échoué : {data.get('reason', '')}"
        self._tray.showMessage("VEYRA", message)

    def _on_mode_changed(self, mode: str) -> None:
        if mode == "PROTECTION":
            self._mode_label.setText("PROTECTION")
            self._mode_label.setStyleSheet(theme.badge_stylesheet("danger"))
        else:
            self._mode_label.setText("SIMULATION")
            self._mode_label.setStyleSheet(theme.badge_stylesheet("warning"))
        self._settings_page.refresh_mode()

    # ------------------------------------------------------------- actions

    def _show_window(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _about(self) -> None:
        QMessageBox.about(
            self, "À propos de VEYRA",
            f"<b>VEYRA {veyra.__version__}</b><br>"
            "Plateforme de sécurité locale, modulaire et adaptative.<br>"
            "Reconnaissance faciale et décision 100 % hors ligne.<br><br>"
            "Documentation : dossier <code>docs/</code> du dépôt.",
        )

    def quit_app(self) -> None:
        """Seule voie de sortie complète de l'application."""
        answer = QMessageBox.question(
            self, "Quitter VEYRA",
            "Arrêter complètement la surveillance et quitter ?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._really_quit = True
        if self._tray is not None:
            self._tray.hide()
        self.close()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 (API Qt)
        if self._really_quit:
            event.accept()
            return
        # Fermeture -> masquage : la surveillance continue en arrière-plan.
        event.ignore()
        self.hide()
        if self._tray is not None:
            self._tray.showMessage(
                "VEYRA",
                "La fenêtre est masquée, la surveillance continue. "
                "Utilisez le menu de la zone de notification pour quitter.",
            )
