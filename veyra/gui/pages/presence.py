# veyra/gui/pages/presence.py
"""Page Présence : aperçu caméra, enrôlement du visage, statut de reconnaissance.

L'aperçu est rendu depuis la dernière frame du ``CameraWorker`` (thread dédié) ;
la conversion BGR->QImage est faite dans le thread GUI sur une image unique,
sans jamais bloquer la capture.
"""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QProgressBar, QPushButton,
                               QScrollArea, QVBoxLayout, QWidget)

from veyra.gui.widgets import PageHeader, StateBadge


class PresencePage(QWidget):
    def __init__(self, ctx, bridge, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._ctx = ctx
        self._last_qimage: QImage | None = None  # évite les allocations inutiles

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 20)
        outer.setSpacing(12)
        outer.addWidget(PageHeader(
            "Présence",
            "Enrôlement local du propriétaire unique (V0.1) et aperçu de la reconnaissance.",
        ))

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setSpacing(12)

        # ---- aperçu caméra
        preview_row = QHBoxLayout()
        self.preview = QLabel("Caméra arrêtée")
        self.preview.setMinimumSize(480, 320)
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setStyleSheet(
            "QLabel { background: #0a0c10; border: 1px solid #2a2f3d; "
            "border-radius: 10px; color: #98a0b3; }"
        )
        preview_row.addWidget(self.preview, stretch=3)

        side = QVBoxLayout()
        side.setSpacing(10)

        status_row = QHBoxLayout()
        status_row.addWidget(QLabel("Statut :"))
        self.status_badge = StateBadge("—", "muted")
        status_row.addWidget(self.status_badge)
        status_row.addStretch(1)
        side.addLayout(status_row)

        self.face_detail = QLabel("Aucune analyse pour l'instant.")
        self.face_detail.setObjectName("mutedLabel")
        self.face_detail.setWordWrap(True)
        side.addWidget(self.face_detail)

        self.profile_label = QLabel("")
        self.profile_label.setObjectName("mutedLabel")
        self.profile_label.setWordWrap(True)
        side.addWidget(self.profile_label)

        self.btn_enroll = QPushButton("Enrôler mon visage")
        self.btn_enroll.setObjectName("primaryButton")
        self.btn_enroll.clicked.connect(self._start_enrollment)

        self.btn_delete = QPushButton("Supprimer le profil biométrique")
        self.btn_delete.setObjectName("dangerButton")
        self.btn_delete.clicked.connect(self._delete_profile)

        side.addWidget(self.btn_enroll)
        side.addWidget(self.btn_delete)
        side.addStretch(1)
        preview_row.addLayout(side, stretch=2)
        layout.addLayout(preview_row)

        # ---- progression enrôlement
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        layout.addWidget(self.progress)
        self.progress_label = QLabel("")
        self.progress_label.setObjectName("mutedLabel")
        self.progress_label.setWordWrap(True)
        self.progress_label.setVisible(False)
        layout.addWidget(self.progress_label)

        self.hint_label = QLabel("")
        self.hint_label.setStyleSheet("color: #5b8cff; font-weight: 600;")
        self.hint_label.setVisible(False)
        layout.addWidget(self.hint_label)

        layout.addStretch(1)
        scroll.setWidget(body)
        outer.addWidget(scroll)

        # ---- timers
        self._preview_timer = QTimer(self)
        self._preview_timer.setInterval(120)   # ~8 fps d'aperçu suffisent
        self._preview_timer.timeout.connect(self._update_preview)
        self._preview_timer.start()

        self._status_timer = QTimer(self)
        self._status_timer.setInterval(1500)
        self._status_timer.timeout.connect(self._update_status)
        self._status_timer.start()

        bridge.face_observation.connect(self._on_face_observation)
        bridge.enrollment_progress.connect(self._on_enrollment)

        self._update_status()

    # ------------------------------------------------------------- aperçu

    def _update_preview(self) -> None:
        frame = self._ctx.face_guard.camera.latest_frame()
        if frame is None:
            if self._last_qimage is not None:
                self.preview.clear()
                self.preview.setText("Caméra indisponible")
                self._last_qimage = None
            return
        rgb = np.ascontiguousarray(frame[:, :, ::-1])  # BGR -> RGB
        h, w, _ = rgb.shape
        if (self._last_qimage is None or self._last_qimage.width() != w
                or self._last_qimage.height() != h):
            image = QImage(rgb.data, w, h, 3 * w, QImage.Format.Format_RGB888)
            self._last_qimage = image.copy()  # copie indépendante du buffer numpy
        else:
            self._last_qimage = QImage(rgb.data, w, h, 3 * w,
                                       QImage.Format.Format_RGB888).copy()
        pixmap = QPixmap.fromImage(self._last_qimage)
        pixmap = pixmap.scaled(
            self.preview.size(), Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.preview.setPixmap(pixmap)

    # ------------------------------------------------------------- statut

    def _update_status(self) -> None:
        face = self._ctx.face_guard
        if not face.camera.available:
            self.status_badge.set_state("CAMÉRA INDISPONIBLE", "danger")
        elif not face.pipeline.loaded:
            self.status_badge.set_state("MODÈLES ABSENTS", "warning")
        else:
            state = face.info().metrics.get("last_state", "NO_FACE")
            mapping = {
                "TRUSTED": ("TRUSTED", "success"),
                "UNKNOWN": ("UNKNOWN", "danger"),
                "UNDETERMINED": ("UNDETERMINED", "warning"),
                "NO_FACE": ("NO_FACE", "muted"),
            }
            text, kind = mapping.get(str(state), (str(state), "muted"))
            self.status_badge.set_state(text, kind)

        has_profile = self._ctx.profile_repo.has_profile()
        vault_ok = self._ctx.profile_repo.available
        if has_profile and vault_ok:
            self.profile_label.setText(
                "Profil : enrôlé (empreinte chiffrée au Keychain macOS).")
        elif has_profile and not vault_ok:
            self.profile_label.setText(
                "Profil : présent mais indéchiffrable (clé Keychain manquante).")
        else:
            self.profile_label.setText(
                "Profil : aucun — la reconnaissance ne peut pas établir la confiance.")
        self.btn_delete.setEnabled(has_profile)

    def _on_face_observation(self, data: dict) -> None:
        state = data.get("state", "?")
        count = data.get("face_count", 0)
        parts = [f"État : {state}", f"Visages : {count}"]
        if "best_distance" in data:
            parts.append(f"Distance : {data['best_distance']}")
        if "min_brightness" in data:
            parts.append(f"Luminosité : {data['min_brightness']}")
        if data.get("detail"):
            parts.append(str(data["detail"]))
        self.face_detail.setText(" · ".join(parts))

    # ---------------------------------------------------------- enrôlement

    def _start_enrollment(self) -> None:
        session = self._ctx.face_guard.enrollment_session()
        if session is None:
            self.progress_label.setVisible(True)
            self.progress_label.setText("Module d'enrôlement indisponible.")
            return
        ok = session.start(lambda: self._ctx.face_guard.camera.latest_frame())
        if not ok:
            self.progress.setVisible(True)
            self.progress_label.setVisible(True)
            self.progress_label.setText(session.progress.message or
                                        "Impossible de démarrer l'enrôlement.")
        else:
            self.btn_enroll.setEnabled(False)

    def _delete_profile(self) -> None:
        from PySide6.QtWidgets import QMessageBox
        answer = QMessageBox.question(
            self, "Supprimer le profil biométrique",
            "Supprimer définitivement l'empreinte faciale et sa clé de "
            "chiffrement ? La reconnaissance sera impossible jusqu'au prochain "
            "enrôlement.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._ctx.delete_biometric_profile()
            self._update_status()

    def _on_enrollment(self, data: dict) -> None:
        stage = str(data.get("stage", ""))
        if stage == "IDLE":
            self.progress.setVisible(False)
            self.progress_label.setVisible(False)
            self.hint_label.setVisible(False)
            self.btn_enroll.setEnabled(True)
            return
        self.progress.setVisible(True)
        self.progress_label.setVisible(True)
        captured = int(data.get("captured", 0))
        target = max(int(data.get("target", 1)), 1)
        self.progress.setMaximum(target)
        self.progress.setValue(captured)
        self.progress_label.setText(str(data.get("message", "")))
        hint = str(data.get("orientation_hint", ""))
        self.hint_label.setText(hint)
        self.hint_label.setVisible(bool(hint))
        if stage in ("DONE", "FAILED"):
            self.btn_enroll.setEnabled(True)
            if stage == "DONE":
                self.hint_label.setStyleSheet("color: #34d399; font-weight: 600;")
                self.hint_label.setText("Profil enregistré.")
                self.hint_label.setVisible(True)
                self._update_status()
            else:
                self.hint_label.setStyleSheet("color: #f87171; font-weight: 600;")
