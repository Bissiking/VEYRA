# veyra/modules/face_guard/models.py
"""Emplacement et disponibilité des modèles ONNX locaux.

Deux modèles sont requis (téléchargés par ``scripts/download_models.py``) :
- ``face_detection_yunet_2023mar.onnx`` : détection de visages (OpenCV Zoo) ;
- ``face_recognition_sface_2021dec.onnx`` : empreinte faciale 128-D (SFace).

Aucun modèle n'est versionné dans le dépôt. Si un fichier manque, le module
face_guard passe en état ``ERROR`` avec un message explicite — il n'est JAMAIS
remplacé par une reconnaissance simulée.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

YUNET_FILE = "face_detection_yunet_2023mar.onnx"
SFACE_FILE = "face_recognition_sface_2021dec.onnx"


def default_models_dir() -> Path:
    """Dossier des modèles : ``$VEYRA_MODELS_DIR`` ou ``<racine dépôt>/models``."""
    env = os.environ.get("VEYRA_MODELS_DIR")
    if env:
        return Path(env)
    # veyra/modules/face_guard/models.py -> racine du dépôt
    return Path(__file__).resolve().parents[3] / "models"


@dataclass(frozen=True)
class ModelPaths:
    models_dir: Path

    @property
    def yunet(self) -> Path:
        return self.models_dir / YUNET_FILE

    @property
    def sface(self) -> Path:
        return self.models_dir / SFACE_FILE

    def missing(self) -> list[str]:
        missing = []
        if not self.yunet.is_file():
            missing.append(self.yunet.name)
        if not self.sface.is_file():
            missing.append(self.sface.name)
        return missing

    def hint(self) -> str:
        missing = self.missing()
        if not missing:
            return ""
        return (
            f"Modèle(s) manquant(s) : {', '.join(missing)}. "
            "Exécuter : python scripts/download_models.py"
        )
