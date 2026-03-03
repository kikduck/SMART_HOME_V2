#!/bin/bash
# Télécharge Qwen3.5-2B-Q6_K.gguf depuis Hugging Face
# Usage: ./download_model.sh   (depuis la racine SMART_HOME_V2)

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
MODEL_DIR="${1:-$SCRIPT_DIR/models}"
MODEL_FILE="Qwen3.5-2B-Q4_K_M.gguf"
HF_URL="https://huggingface.co/unsloth/Qwen3.5-2B-GGUF/resolve/main/${MODEL_FILE}"

mkdir -p "$MODEL_DIR"
cd "$MODEL_DIR"

if [ -f "$MODEL_FILE" ]; then
  echo "Modèle déjà présent: $MODEL_FILE"
  exit 0
fi

echo "Téléchargement de $MODEL_FILE (~1.5 GB)..."
if command -v wget &>/dev/null; then
  wget -c "$HF_URL" -O "$MODEL_FILE"
elif command -v curl &>/dev/null; then
  curl -L -C - -o "$MODEL_FILE" "$HF_URL"
else
  echo "Installez wget ou curl"
  exit 1
fi

echo "OK: $MODEL_DIR/$MODEL_FILE"
