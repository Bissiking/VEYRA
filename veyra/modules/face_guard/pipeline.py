# veyra/modules/face_guard/pipeline.py
"""Pipeline de reconnaissance faciale locale.

Étapes : détection YuNet (OpenCV) -> alignement SFace -> empreinte ONNX Runtime
-> comparaison L2 avec l'empreinte de référence (profil autorisé).

États produits : TRUSTED / UNKNOWN / UNDETERMINED / NO_FACE.
Anti-spoofing V0.2 : le pipeline expose les landmarks YuNet (5 points) et un
score de texture ; le suivi temporel (clignement) est assuré par
``liveness.LivenessTracker`` côté module. La protection reste BASIQUE
(voir docs/SECURITY.md) : elle limite les photos imprimées simples, pas
une vidéo projetée ou un masque.

Aucune image n'est conservée au-delà de l'appel ; l'empreinte vit en mémoire
ou chiffrée via ``BiometricVault``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np

from veyra.core.policy import IdentityState, SecurityPolicy
from veyra.modules.face_guard.models import ModelPaths

logger = logging.getLogger(__name__)


@dataclass
class DetectedFace:
    """Visage détecté dans une image (coordonnées normalisées 0..1 + pixels)."""

    x: float
    y: float
    w: float
    h: float
    score: float
    w_px: int = 0
    h_px: int = 0
    embedding: np.ndarray | None = None
    brightness: float = 0.0
    state: IdentityState = IdentityState.UNDETERMINED
    distance: float | None = None
    landmarks: np.ndarray | None = None  # (5, 2) pixels : yeux, nez, bouche
    texture: float = 0.0  # variance du Laplacien du ROI (anti-spoofing V0.2)


@dataclass
class PipelineResult:
    state: IdentityState
    faces: list[DetectedFace] = field(default_factory=list)
    detail: str = ""


class FacePipeline:
    """Détecte et identifie les visages d'une image BGR."""

    def __init__(self, paths: ModelPaths) -> None:
        self._paths = paths
        self._detector = None
        self._aligner = None
        self._session = None
        self._input_name = ""
        self._error = ""

    # ------------------------------------------------------------ chargement

    @property
    def loaded(self) -> bool:
        return (self._detector is not None and self._aligner is not None
                and self._session is not None)

    @property
    def error(self) -> str:
        return self._error

    def load(self) -> bool:
        """Charge les modèles. Retourne False avec un message explicite si absents."""
        missing = self._paths.missing()
        if missing:
            self._error = self._paths.hint()
            logger.error(self._error)
            return False
        try:
            import cv2
            import onnxruntime as ort

            self._detector = cv2.FaceDetectorYN.create(
                str(self._paths.yunet), "",
                (640, 480),
                score_threshold=0.6,
                nms_threshold=0.3,
                top_k=5000,
            )
            # alignCrop est une méthode d'instance depuis OpenCV 4.10+.
            self._aligner = cv2.FaceRecognizerSF.create(str(self._paths.sface), "")
            so = ort.SessionOptions()
            so.log_severity_level = 3  # réduit le bruit des warnings ONNX
            self._session = ort.InferenceSession(
                str(self._paths.sface), sess_options=so,
                providers=["CPUExecutionProvider"],
            )
            self._input_name = self._session.get_inputs()[0].name
            self._error = ""
            logger.info("Pipeline biométrique chargé (YuNet + SFace/ONNX Runtime).")
            return True
        except Exception as exc:
            self._error = f"Échec de chargement des modèles : {exc}"
            logger.exception(self._error)
            self._detector = None
            self._aligner = None
            self._session = None
            return False

    # ------------------------------------------------------------ inférence

    def process(self, frame: np.ndarray, policy: SecurityPolicy,
                reference: np.ndarray | None) -> PipelineResult:
        """Analyse une image BGR.

        ``reference`` : empreinte de référence du profil autorisé (ou None si
        aucun profil n'existe -> état UNDETERMINED quand un visage est vu).
        """
        if not self.loaded:
            return PipelineResult(IdentityState.UNDETERMINED, detail=self._error)


        h, w = frame.shape[:2]
        self._detector.setInputSize((w, h))
        try:
            _res, detections = self._detector.detect(frame)
        except Exception as exc:
            logger.exception("Échec de la détection faciale.")
            return PipelineResult(IdentityState.UNDETERMINED, detail=f"détection échouée : {exc}")

        if detections is None or len(detections) == 0:
            return PipelineResult(IdentityState.NO_FACE, detail="aucun visage détecté")

        faces: list[DetectedFace] = []
        for det in detections:
            x, y, bw, bh = det[:4]
            score = float(det[-1])
            face = DetectedFace(
                x=float(x) / w, y=float(y) / h,
                w=float(bw) / w, h=float(bh) / h,
                score=score,
                w_px=int(bw), h_px=int(bh),
            )
            face.landmarks = np.asarray(det[4:14], dtype=np.float32).reshape(5, 2)
            face.brightness = self._face_brightness(frame, int(x), int(y), int(bw), int(bh))
            face.texture = self._face_texture(frame, int(x), int(y), int(bw), int(bh))
            face.embedding = self._embed(frame, det)
            face.state = self._classify(face, reference, policy)
            faces.append(face)

        return PipelineResult(self._aggregate(faces), faces=faces)

    # -------------------------------------------------------------- privés

    def _embed(self, frame: np.ndarray, det: np.ndarray) -> np.ndarray | None:
        """Empreinte SFace 128-D, normalisée L2 (sortie ONNX Runtime)."""
        try:
            aligned = self._aligner.alignCrop(frame, det)
            blob = aligned.astype(np.float32)
            blob = (blob - 127.5) / 127.5          # normalisation standard SFace
            blob = blob.transpose(2, 0, 1)[None]    # NCHW
            out = self._session.run(None, {self._input_name: blob})[0]
            vec = np.asarray(out, dtype=np.float32).reshape(-1)
            norm = float(np.linalg.norm(vec))
            if norm > 1e-6:
                vec = vec / norm
            return vec
        except Exception:
            logger.exception("Échec de calcul d'empreinte faciale.")
            return None

    @staticmethod
    def _face_brightness(frame: np.ndarray, x: int, y: int, w: int, h: int) -> float:
        import cv2

        h_img, w_img = frame.shape[:2]
        x0, y0 = max(x, 0), max(y, 0)
        x1, y1 = min(x + w, w_img), min(y + h, h_img)
        if x1 <= x0 or y1 <= y0:
            return 0.0
        roi = frame[y0:y1, x0:x1]
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        return float(gray.mean())

    @staticmethod
    def _face_texture(frame: np.ndarray, x: int, y: int, w: int, h: int) -> float:
        """Variance du Laplacien du ROI — lisse = photo imprimée possible."""
        import cv2

        h_img, w_img = frame.shape[:2]
        x0, y0 = max(x, 0), max(y, 0)
        x1, y1 = min(x + w, w_img), min(y + h, h_img)
        if x1 <= x0 or y1 <= y0:
            return 0.0
        gray = cv2.cvtColor(frame[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY)
        return float(cv2.Laplacian(gray, cv2.CV_64F).var())

    def _classify(self, face: DetectedFace, reference: np.ndarray | None,
                  policy: SecurityPolicy) -> IdentityState:
        # Conditions de qualité -> indéterminé (pas une preuve d'intrusion).
        if min(face.w_px, face.h_px) < policy.min_face_size_px:
            return IdentityState.UNDETERMINED
        if face.brightness < policy.min_face_brightness:
            return IdentityState.UNDETERMINED
        if face.embedding is None:
            return IdentityState.UNDETERMINED
        if reference is None:
            # Aucun profil autorisé -> on ne peut pas établir la confiance.
            return IdentityState.UNDETERMINED
        distance = float(np.linalg.norm(face.embedding - reference))
        face.distance = distance
        if distance <= policy.recognition_threshold:
            return IdentityState.TRUSTED
        if distance <= policy.recognition_threshold + policy.recognition_margin:
            # Zone grise : trop proche pour trancher -> indéterminé.
            return IdentityState.UNDETERMINED
        return IdentityState.UNKNOWN

    @staticmethod
    def _aggregate(faces: list[DetectedFace]) -> IdentityState:
        """États multiples : TRUSTED prime, puis UNKNOWN, puis UNDETERMINED."""
        states = {f.state for f in faces}
        if IdentityState.TRUSTED in states:
            return IdentityState.TRUSTED
        if IdentityState.UNKNOWN in states:
            return IdentityState.UNKNOWN
        return IdentityState.UNDETERMINED
