#!/usr/bin/env bash
# scripts/run_dev.sh — lancement en développement local sur macOS/Linux.
#
# Usage : ./scripts/run_dev.sh [--args de veyra…]
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ ! -d .venv ]]; then
  echo "[veyra] Création de l'environnement virtuel…"
  python3 -m venv .venv
fi

# shellcheck disable=SC1091
source .venv/bin/activate
pip install -q -r requirements-dev.txt

if [[ ! -f models/face_detection_yunet_2023mar.onnx || ! -f models/face_recognition_sface_2021dec.onnx ]]; then
  echo "[veyra] Modèles biométriques absents -> téléchargement…"
  python scripts/download_models.py
fi

echo "[veyra] Démarrage (mode SIMULATION par défaut)…"
exec python -m veyra "$@"
