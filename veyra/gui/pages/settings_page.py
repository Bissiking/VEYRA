# veyra/gui/pages/settings_page.py
"""Page Settings : caméra, performances, délais, modes de protection, confidentialité.

La bascule en mode PROTECTION exige une confirmation explicite (dialogue + saisi
de la chaîne « PROTECTION »). Le retour en SIMULATION est toujours libre.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from veyra.core.policy import ProtectionMode, SecurityPolicy
from veyra.gui.widgets import PageHeader, StateBadge
from veyra.modules.face_guard.calibration import CalibrationSummary, calibrate
from veyra.platforms import autostart


class FarFrrCurveWidget(QWidget):
    """Courbe FAR/FRR minimaliste peinte sans dépendance externe."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._summary: CalibrationSummary | None = None
        self.setMinimumHeight(140)

    def set_summary(self, summary: CalibrationSummary | None) -> None:
        self._summary = summary
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(30, 10, -10, -25)
        painter.fillRect(self.rect(), QColor("#14161a"))
        if self._summary is None or not self._summary.curve:
            painter.setPen(QColor("#666"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                             "Aucune donnée de calibration")
            return
        # Axes
        painter.setPen(QPen(QColor("#444"), 1))
        painter.drawRect(rect)
        curve = self._summary.curve
        xs = [p.threshold for p in curve]
        x_min, x_max = min(xs), max(xs)

        def to_rect(t: float, v: float) -> tuple[float, float]:
            x = rect.left() + (t - x_min) / max(x_max - x_min, 1e-9) * rect.width()
            y = rect.bottom() - v * rect.height()
            return x, y

        # FAR (rouge) et FRR (bleu)
        for attr, color in (("far", "#e74c3c"), ("frr", "#3498db")):
            painter.setPen(QPen(QColor(color), 2))
            prev = None
            for p in curve:
                pt = to_rect(p.threshold, getattr(p, attr))
                if prev is not None:
                    painter.drawLine(QPointF(*prev), QPointF(*pt))
                prev = pt
        # Point EER
        if self._summary.eer_threshold is not None and self._summary.eer is not None:
            ex, ey = to_rect(self._summary.eer_threshold, self._summary.eer)
            painter.setPen(QPen(QColor("#f1c40f"), 2))
            painter.drawEllipse(QRectF(ex - 4, ey - 4, 8, 8))
            painter.setPen(QColor("#f1c40f"))
            painter.drawText(int(ex) + 6, int(ey) - 6,
                             f"EER {self._summary.eer_threshold:.2f}")
        # Légende
        painter.setPen(QColor("#e74c3c"))
        painter.drawText(35, 12, "FAR")
        painter.setPen(QColor("#3498db"))
        painter.drawText(65, 12, "FRR")
        painter.setPen(QColor("#888"))
        painter.drawText(rect.left(), self.height() - 8,
                         f"seuils {x_min:.2f}–{x_max:.2f} (distance L2)")


class _AppliedSignal(QObject):
    """Porte de signal pour rafraîchir les cartes après application."""

    policy_applied = Signal()


class SettingsPage(QWidget):
    def __init__(self, ctx, bridge, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._ctx = ctx
        self.events = _AppliedSignal()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 20)
        outer.setSpacing(12)
        outer.addWidget(PageHeader(
            "Settings",
            "Paramètres persistants (SQLite) appliqués immédiatement au moteur.",
        ))

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setSpacing(12)

        # ---------------------------------------------------------- caméra
        cam_group = QGroupBox("Caméra et démarrage")
        cam_form = QFormLayout(cam_group)
        self.camera_box = QSpinBox()
        self.camera_box.setRange(0, 9)
        self.camera_box.setValue(self._ctx.config.get_camera_index())
        cam_form.addRow("Index de caméra", self.camera_box)
        cam_note = QLabel("L'index 0 correspond à la caméra par défaut du système.")
        cam_note.setObjectName("mutedLabel")
        cam_form.addRow("", cam_note)

        self.autostart_box = QCheckBox(
            "Démarrer VEYRA automatiquement à la connexion")
        if autostart.autostart_supported():
            self.autostart_box.setChecked(autostart.is_autostart_enabled())
            self.autostart_box.stateChanged.connect(self._toggle_autostart)
        else:
            self.autostart_box.setEnabled(False)
            self.autostart_box.setToolTip(
                "Démarrage au login non géré sur cette plateforme.")
        cam_form.addRow(self.autostart_box)
        layout.addWidget(cam_group)

        # ------------------------------------------------------ performances
        perf_group = QGroupBox("Performances")
        perf_form = QFormLayout(perf_group)
        self.low_power = QCheckBox(
            "Mode économe (cadence d'analyse divisée par 2)")
        self.low_power.setChecked(self._ctx.config.get_low_power())
        perf_form.addRow(self.low_power)
        layout.addWidget(perf_group)

        # ------------------------------------------------------------ délais
        policy = self._ctx.policy
        delay_group = QGroupBox("Délais de surveillance")
        delay_form = QFormLayout(delay_group)

        self.idle_spin = self._double_spin(policy.idle_threshold_s, 1.0, 300.0)
        self.idle_spin.setSuffix(" s")
        delay_form.addRow("Passage en surveillance légère après", self.idle_spin)

        self.light_spin = self._double_spin(policy.light_analysis_interval_s, 1.0, 60.0)
        self.light_spin.setSuffix(" s")
        delay_form.addRow("Analyse légère toutes les", self.light_spin)

        self.active_spin = self._double_spin(policy.active_analysis_interval_s, 0.5, 60.0)
        self.active_spin.setSuffix(" s")
        delay_form.addRow("Analyse active toutes les", self.active_spin)

        self.confirm_spin = self._double_spin(policy.confirm_window_s, 0.5, 30.0)
        self.confirm_spin.setSuffix(" s")
        delay_form.addRow("Fenêtre de confirmation d'identité suspecte", self.confirm_spin)

        self.threshold_spin = self._double_spin(policy.recognition_threshold, 0.1, 1.5)
        delay_form.addRow("Seuil de reconnaissance (distance L2)", self.threshold_spin)

        self.lock_unknown = QCheckBox(
            "Verrouiller si visage inconnu confirmé + activité")
        self.lock_unknown.setChecked(policy.lock_on_unknown_face_with_activity)
        delay_form.addRow(self.lock_unknown)

        self.lock_camera = QCheckBox(
            "Verrouiller si webcam indisponible après absence + nouvelle activité")
        self.lock_camera.setChecked(policy.lock_on_camera_loss_after_absence)
        delay_form.addRow(self.lock_camera)

        self.absent_keep = QCheckBox(
            "Maintenir la session si propriétaire absent sans activité")
        self.absent_keep.setChecked(policy.absent_idle_keep_session)
        delay_form.addRow(self.absent_keep)

        layout.addWidget(delay_group)

        # ------------------------------------------------------ anti-spoofing
        spoof_group = QGroupBox("Anti-spoofing (basique — voir docs/SECURITY.md)")
        spoof_form = QFormLayout(spoof_group)

        self.spoof_enabled = QCheckBox(
            "Activer le contrôle clignement + texture (photo/écran possible)")
        self.spoof_enabled.setChecked(policy.anti_spoofing_enabled)
        spoof_form.addRow(self.spoof_enabled)

        self.spoof_window = self._double_spin(policy.liveness_window_s, 3.0, 30.0)
        self.spoof_window.setSuffix(" s")
        spoof_form.addRow("Fenêtre de suivi du clignement", self.spoof_window)

        self.spoof_blinks = QSpinBox()
        self.spoof_blinks.setRange(0, 5)
        self.spoof_blinks.setValue(policy.liveness_min_blinks)
        spoof_form.addRow("Clignements minimum sur la fenêtre", self.spoof_blinks)

        self.spoof_openness = self._double_spin(policy.liveness_min_openness, 0.02, 0.5)
        spoof_form.addRow("Seuil d'ouverture d'œil (contraste)", self.spoof_openness)

        self.spoof_texture = self._double_spin(policy.liveness_min_texture, 5.0, 500.0)
        spoof_form.addRow("Seuil de texture minimum (Laplacien)", self.spoof_texture)

        spoof_note = QLabel(
            "Heuristique : un visage sans clignement ET lisse sur la fenêtre "
            "est dégradé (TRUSTED -> UNKNOWN), ce qui déclenche la confirmation "
            "du moteur — jamais un verrouillage immédiat.")
        spoof_note.setObjectName("mutedLabel")
        spoof_note.setWordWrap(True)
        spoof_form.addRow("", spoof_note)
        layout.addWidget(spoof_group)

        # --------------------------------------------------------- calibration
        calib_group = QGroupBox("Calibration des seuils (FAR/FRR locale)")
        calib_layout = QVBoxLayout(calib_group)

        calib_help = QLabel(
            "Pendant la collecte, chaque visage reconnu (TRUSTED) ou inconnu "
            "(UNKNOWN) ajoute sa distance à l'histogramme local. Aucune image "
            "ni empreinte n'est conservée — des distances seules. Après "
            "arrêt, la courbe et le point d'égalisation (EER) sont calculés ; "
            "vous pouvez appliquer le seuil suggéré.")
        calib_help.setObjectName("mutedLabel")
        calib_help.setWordWrap(True)
        calib_layout.addWidget(calib_help)

        calib_buttons = QHBoxLayout()
        self.btn_calib_start = QPushButton("Démarrer la collecte")
        self.btn_calib_start.clicked.connect(self._calib_start)
        self.btn_calib_stop = QPushButton("Arrêter et calculer")
        self.btn_calib_stop.setEnabled(False)
        self.btn_calib_stop.clicked.connect(self._calib_stop)
        calib_buttons.addWidget(self.btn_calib_start)
        calib_buttons.addWidget(self.btn_calib_stop)
        calib_buttons.addStretch(1)
        calib_layout.addLayout(calib_buttons)

        self.calib_status = QLabel("Collecte inactive.")
        self.calib_status.setObjectName("mutedLabel")
        calib_layout.addWidget(self.calib_status)

        self.calib_curve = FarFrrCurveWidget()
        calib_layout.addWidget(self.calib_curve)

        self.btn_calib_apply = QPushButton("Appliquer le seuil suggéré (EER)")
        self.btn_calib_apply.setEnabled(False)
        self.btn_calib_apply.clicked.connect(self._calib_apply_threshold)
        calib_layout.addWidget(self.btn_calib_apply, alignment=Qt.AlignmentFlag.AlignLeft)

        self._calib_summary: CalibrationSummary | None = None
        self._calib_timer = QTimer(self)
        self._calib_timer.setInterval(1000)
        self._calib_timer.timeout.connect(self._calib_refresh_status)
        layout.addWidget(calib_group)

        btn_apply = QPushButton("Appliquer les paramètres")
        btn_apply.setObjectName("primaryButton")
        btn_apply.clicked.connect(self._apply)
        layout.addWidget(btn_apply, alignment=Qt.AlignmentFlag.AlignLeft)

        # ------------------------------------------------- mode de protection
        mode_group = QGroupBox("Mode de protection")
        mode_layout = QVBoxLayout(mode_group)

        row = QHBoxLayout()
        row.addWidget(QLabel("Mode courant :"))
        self.mode_badge = StateBadge("—", "warning")
        row.addWidget(self.mode_badge)
        row.addStretch(1)
        mode_layout.addLayout(row)

        mode_help = QLabel(
            "SIMULATION (défaut à chaque démarrage) : toutes les détections et "
            "décisions fonctionnent, les verrouillages sont journalisés mais JAMAIS "
            "exécutés. PROTECTION : les décisions autorisées peuvent verrouiller "
            "réellement la session."
        )
        mode_help.setObjectName("mutedLabel")
        mode_help.setWordWrap(True)
        mode_layout.addWidget(mode_help)

        mode_buttons = QHBoxLayout()
        self.btn_protect = QPushButton("Activer la protection réelle…")
        self.btn_protect.setObjectName("dangerButton")
        self.btn_protect.clicked.connect(self._enable_protection)
        self.btn_simulate = QPushButton("Revenir en simulation")
        self.btn_simulate.clicked.connect(self._revert_simulation)
        mode_buttons.addWidget(self.btn_protect)
        mode_buttons.addWidget(self.btn_simulate)
        mode_buttons.addStretch(1)
        mode_layout.addLayout(mode_buttons)
        layout.addWidget(mode_group)

        # ---------------------------------------------------- confidentialité
        priv_group = QGroupBox("Confidentialité et données")
        priv_layout = QVBoxLayout(priv_group)

        priv_lines = [
            ("• Aucune image brute n'est conservée (l'enregistrement d'images "
             "n'est pas implémenté)."),
            ("• Seules les empreintes biométriques chiffrées (AES-256-GCM, clé "
             "au coffre de la plateforme : Keychain / DPAPI / Secret Service) "
             "sont stockées dans SQLite."),
            ("• Aucune touche tapée ni trajectoire de souris n'est enregistrée : "
             "seuls des horodatages d'activité sont produits."),
            "• Aucun contenu d'application n'est lu, aucun réseau n'est utilisé.",
            "• Les journaux ne contiennent aucune donnée biométrique sensible.",
        ]
        for line in priv_lines:
            label = QLabel(line)
            label.setObjectName("mutedLabel")
            label.setWordWrap(True)
            priv_layout.addWidget(label)

        danger_row = QHBoxLayout()
        self.btn_delete_profile = QPushButton("Supprimer le profil biométrique")
        self.btn_delete_profile.setObjectName("dangerButton")
        self.btn_delete_profile.clicked.connect(self._delete_profile)
        self.btn_clear_events = QPushButton("Effacer tous les événements")
        self.btn_clear_events.clicked.connect(self._clear_events)
        danger_row.addWidget(self.btn_delete_profile)
        danger_row.addWidget(self.btn_clear_events)
        danger_row.addStretch(1)
        priv_layout.addLayout(danger_row)
        layout.addWidget(priv_group)

        layout.addStretch(1)
        scroll.setWidget(body)
        outer.addWidget(scroll)

        bridge.protection_mode.connect(lambda _: self.refresh_mode())
        self.refresh_mode()

    # ------------------------------------------------------------- helpers

    @staticmethod
    def _double_spin(value: float, lo: float, hi: float) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(lo, hi)
        spin.setSingleStep(0.5)
        spin.setDecimals(1)
        spin.setValue(value)
        return spin

    def refresh_mode(self) -> None:
        mode = self._ctx.circuit.mode
        if mode is ProtectionMode.PROTECTION:
            self.mode_badge.set_state("PROTECTION", "danger")
            self.btn_protect.setEnabled(False)
            self.btn_simulate.setEnabled(True)
        else:
            self.mode_badge.set_state("SIMULATION", "warning")
            self.btn_protect.setEnabled(True)
            self.btn_simulate.setEnabled(False)

    # ------------------------------------------------------------- actions

    def _apply(self) -> None:
        policy = SecurityPolicy(
            idle_threshold_s=self.idle_spin.value(),
            light_analysis_interval_s=self.light_spin.value(),
            active_analysis_interval_s=self.active_spin.value(),
            confirm_window_s=self.confirm_spin.value(),
            recognition_threshold=self.threshold_spin.value(),
            absent_idle_keep_session=self.absent_keep.isChecked(),
            lock_on_unknown_face_with_activity=self.lock_unknown.isChecked(),
            lock_on_camera_loss_after_absence=self.lock_camera.isChecked(),
            anti_spoofing_enabled=self.spoof_enabled.isChecked(),
            liveness_window_s=self.spoof_window.value(),
            liveness_min_blinks=self.spoof_blinks.value(),
            liveness_min_openness=self.spoof_openness.value(),
            liveness_min_texture=self.spoof_texture.value(),
            # conservés tels quels
            recognition_margin=self._ctx.policy.recognition_margin,
            min_face_size_px=self._ctx.policy.min_face_size_px,
            min_face_brightness=self._ctx.policy.min_face_brightness,
            enrollment_samples=self._ctx.policy.enrollment_samples,
        )
        self._ctx.apply_policy(policy)
        self._ctx.config.set_camera_index(self.camera_box.value())
        self._ctx.face_guard.set_camera_index(self.camera_box.value())
        self._ctx.config.set_low_power(self.low_power.isChecked())
        self._ctx.face_guard.set_low_power(self.low_power.isChecked())
        self.events.policy_applied.emit()
        QMessageBox.information(self, "Paramètres",
                                "Paramètres appliqués et enregistrés.")

    def _enable_protection(self) -> None:
        from PySide6.QtWidgets import QInputDialog
        text, ok = QInputDialog.getText(
            self,
            "Activer la protection réelle",
            "Mode PROTECTION : les LOCK_SESSION verrouilleront RÉELLEMENT la "
            "session.\n\nTapez « PROTECTION » pour confirmer :",
            QLineEdit.EchoMode.Normal,
            "",
        )
        if not ok or text.strip() != "PROTECTION":
            if ok:
                QMessageBox.warning(self, "Confirmation",
                                    "Texte incorrect — activation annulée.")
            return
        if self._ctx.enable_protection(confirmed=True):
            QMessageBox.information(
                self, "Mode PROTECTION",
                "Mode PROTECTION activé. Les verrouillages sont désormais réels.",
            )
        else:
            QMessageBox.warning(self, "Mode PROTECTION",
                                "Activation refusée par le coupe-circuit.")
        self.refresh_mode()

    def _revert_simulation(self) -> None:
        self._ctx.revert_to_simulation()
        self.refresh_mode()

    def _toggle_autostart(self, state: int) -> None:
        enabled = state == 2  # Qt.CheckState.Checked
        if not autostart.set_autostart(enabled):
            QMessageBox.warning(
                self, "Démarrage au login",
                "Impossible d'activer ou désactiver le démarrage au login "
                "(voir les journaux pour le détail).")
            # Resynchronise la case avec l'état réel.
            self.autostart_box.setChecked(autostart.is_autostart_enabled())

    # ----------------------------------------------------------- calibration

    def _calib_start(self) -> None:
        self._ctx.face_guard.start_calibration()
        self.btn_calib_start.setEnabled(False)
        self.btn_calib_stop.setEnabled(True)
        self.btn_calib_apply.setEnabled(False)
        self.calib_status.setText("Collecte en cours… présentez des visages "
                                  "(propriétaire et, si possible, un autre).")
        self._calib_timer.start()

    def _calib_stop(self) -> None:
        samples = self._ctx.face_guard.stop_calibration()
        self._calib_timer.stop()
        self.btn_calib_start.setEnabled(True)
        self.btn_calib_stop.setEnabled(False)
        genuine = samples.get("genuine", [])
        impostor = samples.get("impostor", [])
        self._calib_summary = calibrate(genuine, impostor)
        self.calib_curve.set_summary(self._calib_summary)
        if not genuine and not impostor:
            self.calib_status.setText(
                "Aucun échantillon collecté — aucun seuil calculé.")
            self.btn_calib_apply.setEnabled(False)
            return
        eer = self._calib_summary.eer_threshold
        if eer is None:
            self.calib_status.setText(
                f"Genuine : {len(genuine)} — Impostor : {len(impostor)} — "
                "EER impossible (il faut au moins un visage de chaque côté).")
            self.btn_calib_apply.setEnabled(False)
            return
        self.calib_status.setText(
            f"Genuine : {len(genuine)} — Impostor : {len(impostor)} — "
            f"EER ≈ {self._calib_summary.eer:.1%} au seuil {eer:.3f}.")
        self.btn_calib_apply.setEnabled(True)

    def _calib_refresh_status(self) -> None:
        if not self._ctx.face_guard.calibrating:
            return
        info = self._ctx.face_guard.info()
        # Compteur indicatif via les métriques du module (analyses).
        self.calib_status.setText(
            f"Collecte en cours… ({info.metrics.get('analyses', 0)} analyses "
            "depuis le démarrage du module).")

    def _calib_apply_threshold(self) -> None:
        if self._calib_summary is None or self._calib_summary.eer_threshold is None:
            return
        eer = self._calib_summary.eer_threshold
        # bornes conformes au spin de Settings (0.1 .. 1.5)
        eer = max(0.1, min(1.5, eer))
        self.threshold_spin.setValue(round(eer, 3))
        # Recopie immédiate dans la politique courante via _apply().
        self._apply()

    def _delete_profile(self) -> None:
        answer = QMessageBox.question(
            self, "Supprimer le profil biométrique",
            "Supprimer définitivement l'empreinte faciale ET sa clé de chiffrement ?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._ctx.delete_biometric_profile()

    def _clear_events(self) -> None:
        answer = QMessageBox.question(
            self, "Effacer les événements",
            "Supprimer tout l'historique d'événements ?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._ctx.db.clear_events()
