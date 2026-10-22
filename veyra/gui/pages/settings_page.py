# veyra/gui/pages/settings_page.py
"""Page Settings : caméra, performances, délais, modes de protection, confidentialité.

La bascule en mode PROTECTION exige une confirmation explicite (dialogue + saisi
de la chaîne « PROTECTION »). Le retour en SIMULATION est toujours libre.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QDoubleSpinBox, QFormLayout,
                               QGroupBox, QHBoxLayout, QLabel, QLineEdit,
                               QMessageBox, QPushButton, QScrollArea, QSpinBox,
                               QVBoxLayout, QWidget)

from veyra.core.policy import ProtectionMode, SecurityPolicy
from veyra.gui.widgets import PageHeader, StateBadge


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
        cam_group = QGroupBox("Caméra")
        cam_form = QFormLayout(cam_group)
        self.camera_box = QSpinBox()
        self.camera_box.setRange(0, 9)
        self.camera_box.setValue(self._ctx.config.get_camera_index())
        cam_form.addRow("Index de caméra", self.camera_box)
        cam_note = QLabel("L'index 0 correspond à la caméra par défaut du système.")
        cam_note.setObjectName("mutedLabel")
        cam_form.addRow("", cam_note)
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
            "• Aucune image brute n'est conservée par défaut (V0.1 : jamais, "
            "l'enregistrement d'images n'est pas implémenté).",
            "• Seules les empreintes biométriques chiffrées (AES-256-GCM, clé au "
            "Keychain macOS) sont stockées dans SQLite.",
            "• Aucune touche tapée ni trajectoire de souris n'est enregistrée : "
            "seuls des horodatages d'activité sont produits.",
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
