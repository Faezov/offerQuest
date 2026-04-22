#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOCAL_OLLAMA_FULL="$ROOT_DIR/.tools/ollama/bin/ollama"
LOCAL_OLLAMA_PARTIAL="$ROOT_DIR/.tools/ollama-partial/bin/ollama"

export HOME="$ROOT_DIR/.ollama-home"
export OLLAMA_MODELS="$ROOT_DIR/.ollama-home/models"

mkdir -p "$OLLAMA_MODELS"

if [[ -x "$LOCAL_OLLAMA_FULL" ]]; then
  exec "$LOCAL_OLLAMA_FULL" "$@"
fi

if [[ -x "$LOCAL_OLLAMA_PARTIAL" ]]; then
  exec "$LOCAL_OLLAMA_PARTIAL" "$@"
fi

if command -v ollama >/dev/null 2>&1; then
  exec "$(command -v ollama)" "$@"
fi

echo "Ollama binary not found." >&2
echo "Install Ollama system-wide or place the binary at $LOCAL_OLLAMA_FULL." >&2
exit 1
