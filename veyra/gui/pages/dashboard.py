# veyra/gui/pages/dashboard.py
"""Page Dashboard : état de protection, identité, caméra, activité, événements."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QGridLayout, QLabel, QScrollArea,
                               QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from veyra.gui.widgets import Card, PageHeader


class DashboardPage(QWidget):
    """Vue synthétique de l'état de surveillance (données réelles uniquement)."""

    def __init__(self, ctx, bridge, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._ctx = ctx

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 20)
        outer.setSpacing(12)
        outer.addWidget(PageHeader(
            "Dashboard",
            "Vue d'ensemble de la protection locale — aucune donnée ne quitte cette machine.",
        ))

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        grid_host = QVBoxLayout(body)
        grid_host.setSpacing(12)

        grid = QGridLayout()
        grid.setSpacing(12)
        self.card_protection = Card("Protection")
        self.card_identity = Card("Identité")
        self.card_camera = Card("Webcam")
        self.card_activity = Card("Activité")
        self.card_mode = Card("Moteur")
        self.card_modules = Card("Modules")
        for i, card in enumerate((
            self.card_protection, self.card_identity, self.card_camera,
            self.card_activity, self.card_mode, self.card_modules,
        )):
            grid.addWidget(card, i // 3, i % 3)
        grid_host.addLayout(grid)

        events_label = QLabel("DERNIERS ÉVÉNEMENTS")
        events_label.setObjectName("cardTitle")
        grid_host.addWidget(events_label)

        self.events_table = QTableWidget(0, 4)
        self.events_table.setHorizontalHeaderLabels(["Heure", "Type", "Source", "Message"])
        self.events_table.horizontalHeader().setStretchLastSection(True)
        self.events_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.events_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.events_table.verticalHeader().setVisible(False)
        self.events_table.setAlternatingRowColors(True)
        grid_host.addWidget(self.events_table)

        scroll.setWidget(body)
        outer.addWidget(scroll)

        # Rafraîchissement périodique (lecture SQLite locale, rapide)
        self._timer = QTimer(self)
        self._timer.setInterval(2500)
        self._timer.timeout.connect(self.refresh)
        self._timer.start()

        bridge.face_observation.connect(self._on_face)
        bridge.lock_outcome.connect(self._on_lock)
        bridge.protection_mode.connect(lambda mode: self._update_protection())
        self.refresh()

    # -------------------------------------------------------------- updates

    def refresh(self) -> None:
        self._update_protection()
        self._update_identity()
        self._update_camera()
        self._update_activity()
        self._update_mode()
        self._update_modules()
        self._update_events()

    def _update_protection(self) -> None:
        mode = self._ctx.circuit.mode.value
        if mode == "SIMULATION":
            self.card_protection.set(
                "Mode SIMULATION", "warning",
                "Les verrouillages sont calculés et journalisés, jamais exécutés.",
            )
        else:
            self.card_protection.set(
                "Mode PROTECTION", "danger",
                "Les décisions LOCK_SESSION peuvent verrouiller réellement la session.",
            )

    def _update_identity(self) -> None:
        engine = self._ctx.engine
        identity = engine.identity.value
        labels = {
            "TRUSTED": ("Propriétaire reconnu", "success"),
            "UNKNOWN": ("Visage inconnu", "danger"),
            "UNDETERMINED": ("Indéterminé", "warning"),
            "NO_FACE": ("Aucun visage", "muted"),
        }
        value, kind = labels.get(identity, (identity, "muted"))
        detail = ""
        if not self._ctx.profile_repo.has_profile():
            detail = "Aucun profil biométrique enrôlé (page Présence)."
        self.card_identity.set(value, kind, detail)

    def _update_camera(self) -> None:
        face = self._ctx.face_guard
        if face.camera.available and face.pipeline.loaded:
            self.card_camera.set("Disponible", "success", "Prêt pour la détection.")
        elif face.camera.available and not face.pipeline.loaded:
            self.card_camera.set("Aperçu seulement", "warning",
                                 face.pipeline.error or "Modèles non chargés.")
        else:
            self.card_camera.set(
                "Indisponible", "danger",
                face.camera.error_detail or "Caméra introuvable ou permission refusée.",
            )

    def _update_activity(self) -> None:
        info = self._ctx.activity_guard.info()
        kind = {"RUNNING": "success", "DEGRADED": "warning", "ERROR": "danger",
                "UNAVAILABLE": "muted"}.get(info.state.value, "muted")
        age = info.metrics.get("last_activity_age_s")
        detail = info.detail
        if isinstance(age, (int, float)):
            detail = f"Dernière activité il y a {age:.0f} s. " + detail
        self.card_activity.set(info.state.value, kind, detail)

    def _update_mode(self) -> None:
        snap = self._ctx.engine.snapshot()
        mode = str(snap["mode"])
        kind = {"ACTIVE": "success", "LIGHT": "accent", "PRIORITY": "warning"}.get(mode, "muted")
        idle = snap.get("last_activity_age_s")
        detail = "Sans activité depuis longtemps." if idle is None and mode == "LIGHT" else (
            f"Inactivité : {idle} s." if idle is not None else "Surveillance régulière.")
        self.card_mode.set(mode, kind, detail)

    def _update_modules(self) -> None:
        infos = self._ctx.modules.infos()
        running = sum(1 for i in infos if i.state.value == "RUNNING")
        problems = [i for i in infos if i.state.value in ("ERROR", "DEGRADED", "UNAVAILABLE")]
        kind = "success" if not problems and running == len(infos) else (
            "warning" if problems else "muted")
        detail = "; ".join(f"{i.name} : {i.state.value}" for i in problems) if problems else \
            "Tous les modules sont opérationnels."
        self.card_modules.set(f"{running}/{len(infos)} actifs", kind, detail)

    def _update_events(self) -> None:
        rows = self._ctx.db.recent_events(limit=15)
        self.events_table.setRowCount(len(rows))
        from datetime import datetime
        for r, row in enumerate(rows):
            when = datetime.fromtimestamp(float(row["ts"])).strftime("%H:%M:%S")
            for c, text in enumerate((
                when, str(row["type"]), str(row["source"]), str(row["message"]),
            )):
                item = QTableWidgetItem(text)
                if row["severity"] == "warning":
                    item.setForeground(Qt.GlobalColor.yellow)
                self.events_table.setItem(r, c, item)
        self.events_table.resizeColumnsToContents()

    # ------------------------------------------- signaux temps réel (bridge)

    def _on_face(self, data: dict) -> None:
        self._update_identity()

    def _on_lock(self, data: dict) -> None:
        self._update_events()
