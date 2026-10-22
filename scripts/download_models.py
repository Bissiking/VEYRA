# scripts/download_models.py
"""Télécharge les modèles ONNX locaux de VEYRA (aucune API externe au runtime).

Sources épinglées à un commit précis d'opencv_zoo (reproductible) :
- YuNet  : face_detection_yunet_2023mar.onnx  (détection)
- SFace  : face_recognition_sface_2021dec.onnx (empreinte 128-D)

Vérifie le SHA-256 de chaque fichier. Les modèles restent locaux et ne sont
jamais versionnés (.gitignore).
"""

from __future__ import annotations

import hashlib
import sys
import urllib.request
from pathlib import Path

COMMIT = "eb9f4f2d4b79b58e5513b5d25d5f0243a8357bf4"
BASE = f"https://github.com/opencv/opencv_zoo/raw/{COMMIT}/models"

MODELS = {
    "face_detection_yunet_2023mar.onnx": {
        "url": f"{BASE}/face_detection_yunet/face_detection_yunet_2023mar.onnx",
        "sha256": "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4",
    },
    "face_recognition_sface_2021dec.onnx": {
        "url": f"{BASE}/face_recognition_sface/face_recognition_sface_2021dec.onnx",
        "sha256": "0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79",
    },
}


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    import os
    target_dir = Path(os.environ.get(
        "VEYRA_MODELS_DIR",
        Path(__file__).resolve().parents[1] / "models",
    ))
    target_dir.mkdir(parents=True, exist_ok=True)

    failures = 0
    for name, spec in MODELS.items():
        dest = target_dir / name
        if dest.is_file() and sha256_of(dest) == spec["sha256"]:
            print(f"[ok] {name} déjà présent et vérifié.")
            continue
        print(f"[dl] {name} …")
        try:
            with urllib.request.urlopen(spec["url"], timeout=120) as response:
                data = response.read()
        except Exception as exc:
            print(f"[erreur] {name} : {exc}", file=sys.stderr)
            failures += 1
            continue
        digest = hashlib.sha256(data).hexdigest()
        if digest != spec["sha256"]:
            print(f"[erreur] SHA-256 invalide pour {name} : {digest}", file=sys.stderr)
            failures += 1
            continue
        dest.write_bytes(data)
        print(f"[ok] {name} ({len(data) // 1024} Ko) -> {dest}")

    if failures:
        print(f"{failures} modèle(s) en échec.", file=sys.stderr)
        return 1
    print("Tous les modèles sont prêts.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
