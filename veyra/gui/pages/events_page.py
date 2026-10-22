# veyra/gui/pages/events_page.py
"""Page Events : historique des événements, décisions et verrouillages simulés."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QHeaderView, QLabel,
                               QMessageBox, QPushButton, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from veyra.gui.widgets import PageHeader

_TYPE_LABELS = {
    "decision": "Décision",
    "lock_outcome": "Verrouillage",
    "protection_mode_changed": "Mode protection",
    "engine_state": "Moteur",
    "module_status": "Module",
    "camera_status": "Caméra",
    "face_observation": "Visage",
    "activity_stream_status": "Activité",
    "enrollment_progress": "Enrôlement",
}


class EventsPage(QWidget):
    def __init__(self, ctx, bridge, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._ctx = ctx

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 20)
        outer.setSpacing(12)
        outer.addWidget(PageHeader(
            "Events",
            "Historique local des décisions et actions (jamais de données biométriques).",
        ))

        controls = QHBoxLayout()
        controls.addWidget(QLabel("Filtrer :"))
        self.filter_box = QComboBox()
        self.filter_box.addItem("Tous", None)
        for value, label in _TYPE_LABELS.items():
            self.filter_box.addItem(label, value)
        self.filter_box.currentIndexChanged.connect(self.refresh)
        controls.addWidget(self.filter_box)
        controls.addStretch(1)

        self.count_label = QLabel("")
        self.count_label.setObjectName("mutedLabel")
        controls.addWidget(self.count_label)

        self.btn_refresh = QPushButton("Actualiser")
        self.btn_refresh.clicked.connect(self.refresh)
        controls.addWidget(self.btn_refresh)

        self.btn_clear = QPushButton("Effacer l'historique")
        self.btn_clear.setObjectName("dangerButton")
        self.btn_clear.clicked.connect(self._clear)
        controls.addWidget(self.btn_clear)
        outer.addLayout(controls)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["Horodatage", "Type", "Source", "Sévérité", "Message"])
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        outer.addWidget(self.table)

        bridge.event.connect(self._on_event)
        timer = QTimer(self)
        timer.setInterval(3000)
        timer.timeout.connect(self.refresh)
        timer.start()
        self.refresh()

    def refresh(self) -> None:
        rows = self._ctx.db.recent_events(limit=500)
        type_filter = self.filter_box.currentData()
        if type_filter:
            rows = [r for r in rows if r["type"] == type_filter]
        self.table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            when = datetime.fromtimestamp(float(row["ts"])).strftime("%Y-%m-%d %H:%M:%S")
            type_label = _TYPE_LABELS.get(str(row["type"]), str(row["type"]))
            values = (when, type_label, str(row["source"]),
                      str(row["severity"]), str(row["message"]))
            for c, text in enumerate(values):
                item = QTableWidgetItem(text)
                if row["severity"] == "warning":
                    item.setForeground(Qt.GlobalColor.yellow)
                self.table.setItem(r, c, item)
        self.count_label.setText(f"{len(rows)} événement(s)")

    def _on_event(self, etype: str, source: str, data: dict) -> None:
        # Actualisation légère : la table se recharge par timer ; ici on suit
        # seulement les événements marquants pour réagir vite.
        if etype in ("decision", "lock_outcome", "protection_mode_changed"):
            self.refresh()

    def _clear(self) -> None:
        answer = QMessageBox.question(
            self, "Effacer l'historique",
            "Supprimer tous les événements journalisés ?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._ctx.db.clear_events()
            self.refresh()
