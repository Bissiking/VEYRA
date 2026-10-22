# veyra/modules/face_guard/camera.py
"""Capture webcam dans un thread dédié (jamais sur le thread GUI).

- conserve seulement la dernière image (aucun historique, aucun disque) ;
- publie ``CAMERA_STATUS`` à chaque transition disponibilité/indisponibilité ;
- réessaie d'ouvrir la caméra avec backoff si elle disparaît (débranchement,
  autre application, permission refusée).
"""

from __future__ import annotations

import logging
import threading
import time

from veyra.core.events import Event, EventBus, EventType

logger = logging.getLogger(__name__)

_RETRY_MIN_S = 2.0
_RETRY_MAX_S = 15.0
_READ_FAILURE_LIMIT = 15


class CameraWorker:
    """Boucle de capture autonome ; thread-safe pour la lecture de la dernière frame."""

    def __init__(self, bus: EventBus, camera_index: int = 0) -> None:
        self._bus = bus
        self._index = camera_index
        self._lock = threading.Lock()
        self._frame = None            # np.ndarray (BGR), dernière image
        self._frame_ts = 0.0
        self._running = False
        self._thread: threading.Thread | None = None
        self._available = False
        self._last_status: bool | None = None
        self._error_detail = ""

    # ------------------------------------------------------------ cycle de vie

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, name="veyra-camera", daemon=True)
        self._thread.start()
        logger.info("Caméra #%d : thread de capture démarré.", self._index)

    def stop(self) -> None:
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5.0)
        self._frame = None
        self._set_available(False, detail="arrêté")

    @property
    def available(self) -> bool:
        return self._available

    @property
    def error_detail(self) -> str:
        return self._error_detail

    def latest_frame(self):
        """Dernière image BGR (ou None) — copie de référence, non bloquante."""
        with self._lock:
            return self._frame

    def latest(self):
        """Retourne ``(timestamp, frame)`` ou ``(0.0, None)``."""
        with self._lock:
            return self._frame_ts, self._frame

    def set_index(self, index: int) -> None:
        """Change de caméra : redémarre le flux au prochain tour."""
        with self._lock:
            changed = index != self._index
            self._index = index
        if changed and self._running:
            logger.info("Bascule vers la caméra #%d.", index)
            # La boucle détecte l'index courant à chaque réouverture ; on force
            # une fermeture en marquant l'indisponibilité.
            self._set_available(False, detail="changement de caméra")

    # -------------------------------------------------------------- boucle

    def _loop(self) -> None:
        import cv2

        retry_delay = _RETRY_MIN_S
        cap = None
        while self._running:
            with self._lock:
                index = self._index
            if cap is None:
                cap = cv2.VideoCapture(index)
                if not cap.isOpened():
                    cap.release()
                    cap = None
                    self._set_available(False, detail=f"caméra #{index} introuvable")
                    time.sleep(retry_delay)
                    retry_delay = min(retry_delay * 2, _RETRY_MAX_S)
                    continue
                retry_delay = _RETRY_MIN_S
                self._set_available(True)
                logger.info("Caméra #%d ouverte.", index)

            ok, frame = cap.read()
            if not ok or frame is None:
                self._set_available(False, detail="lecture d'image échouée")
                failures = 0
                while self._running and failures < _READ_FAILURE_LIMIT:
                    ok, frame = cap.read()
                    failures += 1
                    if ok and frame is not None:
                        break
                    time.sleep(0.2)
                if not (ok and frame is not None):
                    cap.release()
                    cap = None
                    time.sleep(retry_delay)
                    retry_delay = min(retry_delay * 2, _RETRY_MAX_S)
                    continue
                self._set_available(True)
                retry_delay = _RETRY_MIN_S

            with self._lock:
                self._frame = frame
                self._frame_ts = time.time()

            # Cadence de lecture : ~10 fps suffisent pour la détection.
            time.sleep(0.1)

        if cap is not None:
            cap.release()

    def _set_available(self, ok: bool, detail: str = "") -> None:
        if ok == self._last_status and (ok or detail == self._error_detail):
            return
        self._available = ok
        self._error_detail = "" if ok else detail
        self._last_status = ok
        self._bus.publish(Event(EventType.CAMERA_STATUS, source="face_guard", data={
            "ok": ok,
            "detail": self._error_detail,
            "camera_index": self._index,
        }))
        logger.info("Statut caméra : %s %s", "disponible" if ok else "indisponible",
                    f"({detail})" if detail else "")
