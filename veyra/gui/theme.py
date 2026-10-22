# veyra/gui/theme.py
"""Thème visuel sombre et sobre de VEYRA + fabrique d'icônes."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPalette, QPixmap
from PySide6.QtWidgets import QApplication

# Palette (valeurs nommées réutilisées par le QSS et les badges)
BG = "#0f1116"
PANEL = "#171a22"
PANEL_ALT = "#1d212c"
BORDER = "#2a2f3d"
TEXT = "#e8eaf0"
MUTED = "#98a0b3"
ACCENT = "#5b8cff"
SUCCESS = "#34d399"
WARNING = "#fbbf24"
DANGER = "#f87171"

_BADGE_COLORS = {
    "success": (SUCCESS, "#0c2b21"),
    "warning": (WARNING, "#33290a"),
    "danger": (DANGER, "#38161a"),
    "accent": (ACCENT, "#14203f"),
    "muted": (MUTED, "#232735"),
}

_QSS = f"""
* {{
    font-size: 13px;
}}
QMainWindow, QDialog {{
    background: {BG};
    color: {TEXT};
}}
QWidget {{
    color: {TEXT};
    background: transparent;
}}
QLabel#pageTitle {{
    font-size: 20px;
    font-weight: 600;
}}
QLabel#pageSubtitle {{
    color: {MUTED};
    font-size: 12px;
}}
QLabel#mutedLabel {{
    color: {MUTED};
}}
QFrame#sidebar {{
    background: {PANEL};
    border-right: 1px solid {BORDER};
}}
QLabel#brand {{
    font-size: 18px;
    font-weight: 700;
    letter-spacing: 3px;
    color: {ACCENT};
    padding: 18px 14px 6px 14px;
}}
QLabel#brandVersion {{
    color: {MUTED};
    font-size: 11px;
    padding: 0 14px 14px 14px;
}}
QPushButton#navButton {{
    text-align: left;
    padding: 10px 18px;
    border: none;
    border-radius: 8px;
    margin: 2px 8px;
    color: {MUTED};
    font-size: 13px;
    background: transparent;
}}
QPushButton#navButton:hover {{
    background: {PANEL_ALT};
    color: {TEXT};
}}
QPushButton#navButton:checked {{
    background: #14203f;
    color: {ACCENT};
    font-weight: 600;
}}
QFrame#card {{
    background: {PANEL};
    border: 1px solid {BORDER};
    border-radius: 10px;
}}
QLabel#cardTitle {{
    color: {MUTED};
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 1px;
}}
QLabel#cardValue {{
    font-size: 16px;
    font-weight: 600;
}}
QPushButton {{
    background: {PANEL_ALT};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 7px 14px;
}}
QPushButton:hover {{
    border-color: {ACCENT};
}}
QPushButton:disabled {{
    color: {MUTED};
    border-color: {BORDER};
    background: {PANEL};
}}
QPushButton#primaryButton {{
    background: {ACCENT};
    color: #0b1020;
    border: none;
    font-weight: 600;
}}
QPushButton#primaryButton:hover {{
    background: #7aa0ff;
}}
QPushButton#dangerButton {{
    background: #38161a;
    color: {DANGER};
    border: 1px solid {DANGER};
}}
QPushButton#dangerButton:hover {{
    background: #4a1b21;
}}
QTableWidget, QListWidget {{
    background: {PANEL};
    border: 1px solid {BORDER};
    border-radius: 8px;
    gridline-color: {BORDER};
    selection-background-color: #14203f;
}}
QHeaderView::section {{
    background: {PANEL_ALT};
    color: {MUTED};
    border: none;
    border-bottom: 1px solid {BORDER};
    padding: 6px 8px;
    font-weight: 600;
}}
QComboBox, QSpinBox, QDoubleSpinBox, QLineEdit {{
    background: {PANEL_ALT};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 5px 8px;
    min-height: 20px;
}}
QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QLineEdit:focus {{
    border-color: {ACCENT};
}}
QCheckBox {{
    spacing: 8px;
}}
QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border-radius: 4px;
    border: 1px solid {BORDER};
    background: {PANEL_ALT};
}}
QCheckBox::indicator:checked {{
    background: {ACCENT};
    border-color: {ACCENT};
}}
QProgressBar {{
    background: {PANEL_ALT};
    border: 1px solid {BORDER};
    border-radius: 6px;
    text-align: center;
    height: 16px;
}}
QProgressBar::chunk {{
    background: {ACCENT};
    border-radius: 5px;
}}
QScrollArea {{
    border: none;
}}
QGroupBox {{
    border: 1px solid {BORDER};
    border-radius: 8px;
    margin-top: 14px;
    padding-top: 8px;
    background: {PANEL};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
    color: {MUTED};
    font-weight: 600;
}}
QStatusBar {{
    background: {PANEL};
    border-top: 1px solid {BORDER};
    color: {MUTED};
}}
QToolBar {{
    background: {PANEL};
    border-bottom: 1px solid {BORDER};
    spacing: 8px;
    padding: 4px;
}}
QToolTip {{
    background: {PANEL_ALT};
    color: {TEXT};
    border: 1px solid {BORDER};
    padding: 4px;
}}
QMessageBox {{
    background: {PANEL};
}}
"""


def apply_theme(app: QApplication) -> None:
    """Applique la palette et le stylesheet sombres à l'application."""
    app.setStyle("Fusion")
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(BG))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.Base, QColor(PANEL))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(PANEL_ALT))
    palette.setColor(QPalette.ColorRole.Text, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.Button, QColor(PANEL_ALT))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(ACCENT))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#0b1020"))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(PANEL_ALT))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(TEXT))
    app.setPalette(palette)
    font = QFont()
    font.setPointSize(11)
    app.setFont(font)
    app.setStyleSheet(_QSS)


def badge_stylesheet(kind: str) -> str:
    """QSS d'un petit badge coloré (success/warning/danger/accent/muted)."""
    fg, bg = _BADGE_COLORS.get(kind, _BADGE_COLORS["muted"])
    return (
        f"QLabel {{ color: {fg}; background: {bg}; border: 1px solid {fg}; "
        "border-radius: 9px; padding: 2px 10px; font-size: 11px; font-weight: 600; }"
    )


def make_app_icon(size: int = 256) -> QIcon:
    """Icône de l'application : bouclier stylisé « V » (dessiné, sans asset disque)."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    margin = size * 0.08
    rect = QRectF(margin, margin, size - 2 * margin, size - 2 * margin)

    # Bouclier
    from PySide6.QtGui import QBrush, QPainterPath, QPen
    path = QPainterPath()
    w = rect.width()
    h = rect.height()
    path.moveTo(rect.left() + w * 0.08, rect.top() + h * 0.16)
    path.lineTo(rect.left() + w * 0.5, rect.top() + h * 0.04)
    path.lineTo(rect.left() + w * 0.92, rect.top() + h * 0.16)
    path.lineTo(rect.left() + w * 0.92, rect.top() + h * 0.52)
    path.lineTo(rect.left() + w * 0.5, rect.top() + h * 0.96)
    path.lineTo(rect.left() + w * 0.08, rect.top() + h * 0.52)
    path.closeSubpath()

    painter.setPen(QPen(QColor(ACCENT), size * 0.035))
    painter.setBrush(QBrush(QColor("#14203f")))
    painter.drawPath(path)

    # Lettre V
    painter.setPen(QPen(QColor(TEXT), size * 0.09, Qt.PenStyle.SolidLine,
                        Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawPolyline([
        QPoint(int(rect.left() + w * 0.30), int(rect.top() + h * 0.30)),
        QPoint(int(rect.left() + w * 0.50), int(rect.top() + h * 0.68)),
        QPoint(int(rect.left() + w * 0.70), int(rect.top() + h * 0.30)),
    ])
    painter.end()
    return QIcon(pixmap)
