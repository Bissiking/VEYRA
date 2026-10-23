# veyra/modules/face_guard/liveness.py
"""Anti-spoofing basique (V0.2) : clignement + texture locale.

Deux signaux indépendants, tous deux HEURISTIQUES (voir docs/SECURITY.md) :

1. **Clignement** — ouverture des yeux mesurée par le contraste local autour
   des centres d'yeux (landmarks YuNet). Un œil ouvert mêle pupille sombre et
   sclère claire (contraste élevé) ; un œil fermé est uniforme. Un clignement
   = transition ouvert -> fermé -> ouvert.
2. **Texture** — variance du Laplacien sur le ROI visage. Une photo imprimée
   est plus lisse qu'une peau réelle sous une lumière courante.

Un visage est considéré suspect si, sur la fenêtre de suivi, AUCUN clignement
n'a été observé ET la texture moyenne est sous le seuil. Un seul signal au
maximum n'élève pas de suspicion (faux positifs possibles : visage figé,
éclairage plat).

Aucune image n'est conservée : seuls des scores scalaires sont suivis, en
mémoire uniquement. Les seuils sont réglables dans les paramètres.
"""

from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class LivenessSnapshot:
    """État agrégé du suivi anti-spoofing sur la fenêtre courante."""

    observations: int
    blinks: int
    mean_texture: float
    enough_data: bool
    suspect: bool


class LivenessTracker:
    """Suit ouverture des yeux et texture ; détecte clignements et suspects.

    Thread-safe : alimenté par la boucle d'analyse et par l'échantillonnage
    rapide du module face_guard.
    """

    def __init__(self, window_s: float = 8.0, min_blinks: int = 1,
                 min_openness: float = 0.12, min_texture: float = 40.0) -> None:
        self._lock = threading.Lock()
        self._window_s = max(window_s, 1.0)
        self._min_blinks = max(min_blinks, 0)
        self._min_openness = min_openness
        self._min_texture = min_texture
        self._obs: deque[tuple[float, float, float]] = deque()  # (ts, openness, texture)
        self._blink_ts: deque[float] = deque()
        self._eyes_closed = False

    def reconfigure(self, window_s: float, min_blinks: int,
                    min_openness: float, min_texture: float) -> None:
        """Applique de nouveaux seuils sans effacer l'historique."""
        with self._lock:
            self._window_s = max(window_s, 1.0)
            self._min_blinks = max(min_blinks, 0)
            self._min_openness = min_openness
            self._min_texture = min_texture

    def reset(self) -> None:
        with self._lock:
            self._obs.clear()
            self._blink_ts.clear()
            self._eyes_closed = False

    def observe(self, ts: float, openness: float, texture: float) -> None:
        """Enregistre une observation (ouverture 0..1, texture variance >= 0)."""
        with self._lock:
            self._prune(ts)
            # Machine à états du clignement.
            if not self._eyes_closed and openness < self._min_openness:
                self._eyes_closed = True
            elif self._eyes_closed and openness >= self._min_openness:
                self._eyes_closed = False
                self._blink_ts.append(ts)
            self._obs.append((ts, openness, texture))

    def snapshot(self) -> LivenessSnapshot:
        """État courant : suspect uniquement si la fenêtre est couverte."""
        with self._lock:
            if not self._obs:
                return LivenessSnapshot(0, 0, 0.0, False, False)
            oldest, newest = self._obs[0][0], self._obs[-1][0]
            enough = (newest - oldest) >= self._window_s
            blinks = sum(1 for t in self._blink_ts if t >= newest - self._window_s)
            mean_texture = float(np.mean([o[2] for o in self._obs]))
            suspect = enough and blinks < self._min_blinks \
                and mean_texture < self._min_texture
            return LivenessSnapshot(
                observations=len(self._obs),
                blinks=blinks,
                mean_texture=round(mean_texture, 1),
                enough_data=enough,
                suspect=suspect,
            )

    def _prune(self, now: float) -> None:
        cutoff = now - self._window_s
        while self._obs and self._obs[0][0] < cutoff:
            self._obs.popleft()
        while self._blink_ts and self._blink_ts[0] < cutoff:
            self._blink_ts.popleft()


# ------------------------------------------------------------- mesures locales


def eye_openness(frame_bgr: np.ndarray, cx: int, cy: int, face_w: int) -> float:
    """Contraste local d'un œil (0..~0.5). Faible si l'œil est fermé.

    ``cx, cy`` : centre de l'œil en pixels ; ``face_w`` : largeur du visage
    en pixels (sert à dimensionner la fenêtre de mesure).
    """
    import cv2

    half_w = max(int(face_w * 0.10), 4)
    half_h = max(int(face_w * 0.06), 3)
    h_img, w_img = frame_bgr.shape[:2]
    x0, x1 = max(cx - half_w, 0), min(cx + half_w, w_img)
    y0, y1 = max(cy - half_h, 0), min(cy + half_h, h_img)
    if x1 <= x0 or y1 <= y0:
        return 0.0
    gray = cv2.cvtColor(frame_bgr[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY)
    return float(gray.std()) / 255.0


def texture_score(frame_bgr: np.ndarray, x: int, y: int, w: int, h: int) -> float:
    """Variance du Laplacien du ROI visage — indicator de texture (peau vs photo)."""
    import cv2

    h_img, w_img = frame_bgr.shape[:2]
    x0, y0 = max(x, 0), max(y, 0)
    x1, y1 = min(x + w, w_img), min(y + h, h_img)
    if x1 <= x0 or y1 <= y0:
        return 0.0
    gray = cv2.cvtColor(frame_bgr[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())
