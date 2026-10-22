# veyra/gui/widgets.py
"""Widgets réutilisables de la GUI VEYRA."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout,
                               QWidget)

from veyra.gui import theme


class Card(QFrame):
    """Carte de tableau de bord (titre + valeur + sous-ligne)."""

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(4)

        self.title = QLabel(title.upper())
        self.title.setObjectName("cardTitle")
        self.value = QLabel("—")
        self.value.setObjectName("cardValue")
        self.detail = QLabel("")
        self.detail.setObjectName("mutedLabel")
        self.detail.setWordWrap(True)

        layout.addWidget(self.title)
        layout.addWidget(self.value)
        layout.addWidget(self.detail)

        self._badge: QLabel | None = None

    def set(self, value: str, badge_kind: str | None = None, detail: str = "") -> None:
        """Met à jour la valeur, le badge coloré et la ligne de détail."""
        self.value.setText(value)
        self.detail.setText(detail)
        self.detail.setVisible(bool(detail))
        if badge_kind is None:
            if self._badge is not None:
                self._badge.setParent(None)
                self._badge = None
            return
        if self._badge is None:
            self._badge = QLabel("")
            box = self.layout()
            # Retire le titre isolé pour le réinsérer dans une ligne avec le badge.
            box.removeWidget(self.title)
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(8)
            row.addWidget(self.title, stretch=1)
            row.addWidget(self._badge, alignment=Qt.AlignmentFlag.AlignRight)
            box.insertLayout(0, row)
        self._badge.setText(badge_kind.upper())
        self._badge.setStyleSheet(theme.badge_stylesheet(badge_kind))


class PageHeader(QWidget):
    """En-tête standard des pages : titre + sous-titre."""

    def __init__(self, title: str, subtitle: str = "",
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 8)
        layout.setSpacing(2)
        self._title = QLabel(title)
        self._title.setObjectName("pageTitle")
        layout.addWidget(self._title)
        if subtitle:
            self._sub = QLabel(subtitle)
            self._sub.setObjectName("pageSubtitle")
            self._sub.setWordWrap(True)
            layout.addWidget(self._sub)


class StateBadge(QLabel):
    """Badge d'état autonome (success/warning/danger/accent/muted)."""

    def __init__(self, text: str = "—", kind: str = "muted",
                 parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.set_kind(kind)

    def set_kind(self, kind: str) -> None:
        self.setStyleSheet(theme.badge_stylesheet(kind))

    def set_state(self, text: str, kind: str) -> None:
        self.setText(text)
        self.set_kind(kind)
