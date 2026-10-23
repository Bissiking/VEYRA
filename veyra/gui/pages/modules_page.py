# veyra/gui/pages/modules_page.py
"""Page Modules : liste, état, activation/désactivation des modules."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from veyra.gui.widgets import PageHeader, StateBadge

_STATE_KIND = {
    "RUNNING": "success",
    "STARTING": "warning",
    "DEGRADED": "warning",
    "ERROR": "danger",
    "STOPPED": "muted",
    "UNAVAILABLE": "muted",
}


class ModuleRow(QFrame):
    """Ligne d'un module : nom, détail, badge d'état, bouton start/stop."""

    def __init__(self, ctx, module_id: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._ctx = ctx
        self._module_id = module_id
        self.setObjectName("card")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(12)

        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        self.name_label = QLabel(module_id)
        self.name_label.setObjectName("cardValue")
        self.detail_label = QLabel("")
        self.detail_label.setObjectName("mutedLabel")
        self.detail_label.setWordWrap(True)
        text_col.addWidget(self.name_label)
        text_col.addWidget(self.detail_label)
        layout.addLayout(text_col, stretch=1)

        self.badge = StateBadge("—", "muted")
        layout.addWidget(self.badge, alignment=Qt.AlignmentFlag.AlignRight)

        self.toggle = QPushButton("Arrêter")
        self.toggle.clicked.connect(self._on_toggle)
        layout.addWidget(self.toggle)

    def refresh(self) -> None:
        info = None
        for candidate in self._ctx.modules.infos():
            if candidate.module_id == self._module_id:
                info = candidate
                break
        if info is None:
            return
        self.name_label.setText(info.name)
        metrics = info.metrics
        detail = info.detail
        if metrics:
            extra = ", ".join(f"{k}={v}" for k, v in metrics.items())
            detail = f"{detail} ({extra})" if detail else extra
        self.detail_label.setText(detail)
        state = info.state.value
        self.badge.set_state(state, _STATE_KIND.get(state, "muted"))
        if state == "UNAVAILABLE":
            self.toggle.setEnabled(False)
            self.toggle.setText("Indisponible")
        elif state in ("RUNNING", "STARTING", "DEGRADED"):
            self.toggle.setEnabled(True)
            self.toggle.setText("Arrêter")
        else:
            self.toggle.setEnabled(True)
            self.toggle.setText("Démarrer")

    def _on_toggle(self) -> None:
        info = next((i for i in self._ctx.modules.infos()
                     if i.module_id == self._module_id), None)
        if info is None:
            return
        if info.state.value in ("RUNNING", "STARTING", "DEGRADED"):
            self._ctx.modules.stop_module(self._module_id)
        else:
            self._ctx.modules.start_module(self._module_id)
        self.refresh()


class ModulesPage(QWidget):
    def __init__(self, ctx, bridge, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._ctx = ctx

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 20)
        outer.setSpacing(12)
        outer.addWidget(PageHeader(
            "Modules",
            "Chaque module communique avec le noyau via le bus d'événements ; "
            "aucun module ne verrouille directement la session.",
        ))

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        self._layout = QVBoxLayout(body)
        self._layout.setSpacing(10)

        self._rows: list[ModuleRow] = []
        for info in ctx.modules.infos():
            row = ModuleRow(ctx, info.module_id)
            row.refresh()
            self._layout.addWidget(row)
            self._rows.append(row)

        # Note plateforme (capacités réelles)
        caps = ctx.platform.capabilities()
        note = QLabel(
            f"Plateforme : {ctx.platform.display_name} — "
            f"verrouillage : {'oui' if caps.session_lock else 'NON'}, "
            f"activité : {'oui' if caps.activity_monitoring else 'NON'}, "
            f"coffre clés : {'oui' if caps.secure_key_storage else 'NON'}."
        )
        note.setObjectName("mutedLabel")
        note.setWordWrap(True)
        self._layout.addWidget(note)
        for text in caps.notes.values():
            label = QLabel(f"• {text}")
            label.setObjectName("mutedLabel")
            label.setWordWrap(True)
            self._layout.addWidget(label)

        self._layout.addStretch(1)
        scroll.setWidget(body)
        outer.addWidget(scroll)

        timer = QTimer(self)
        timer.setInterval(2000)
        timer.timeout.connect(self.refresh)
        timer.start()

    def refresh(self) -> None:
        for row in self._rows:
            row.refresh()
