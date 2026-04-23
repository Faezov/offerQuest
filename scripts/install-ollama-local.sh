#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ARCHIVE_PATH="$ROOT_DIR/.tools/ollama-linux-amd64.tar.zst"
DOWNLOAD_PATH="$ARCHIVE_PATH.download"
INSTALL_DIR="$ROOT_DIR/.tools/ollama"
DOWNLOAD_URL="https://ollama.com/download/ollama-linux-amd64.tar.zst"

mkdir -p "$ROOT_DIR/.tools"
mkdir -p "$INSTALL_DIR"

validate_archive() {
  if [[ ! -f "$ARCHIVE_PATH" ]]; then
    return 1
  fi

  zstd -t "$ARCHIVE_PATH" >/dev/null
}

download_archive() {
  rm -f "$DOWNLOAD_PATH"

  if command -v wget >/dev/null 2>&1; then
    wget --progress=dot:giga -O "$DOWNLOAD_PATH" "$DOWNLOAD_URL"
  elif command -v curl >/dev/null 2>&1; then
    curl --http1.1 -fL --progress-bar -o "$DOWNLOAD_PATH" "$DOWNLOAD_URL"
  else
    echo "Neither wget nor curl is available to download Ollama." >&2
    exit 1
  fi

  if ! zstd -t "$DOWNLOAD_PATH" >/dev/null; then
    echo "Downloaded archive failed integrity validation. Removing it so the next run starts clean." >&2
    rm -f "$DOWNLOAD_PATH"
    exit 1
  fi

  mv "$DOWNLOAD_PATH" "$ARCHIVE_PATH"
}

if ! command -v zstd >/dev/null 2>&1; then
  echo "zstd is required to verify and extract the Ollama archive." >&2
  exit 1
fi

if [[ -f "$ARCHIVE_PATH" ]]; then
  if validate_archive; then
    echo "Using cached Ollama archive at $ARCHIVE_PATH"
  else
    echo "Existing archive is corrupted. Removing it and downloading a clean copy..." >&2
    rm -f "$ARCHIVE_PATH"
    download_archive
  fi
else
  download_archive
fi

rm -f "$DOWNLOAD_PATH"

rm -rf "$INSTALL_DIR/bin" "$INSTALL_DIR/lib"
tar --use-compress-program=unzstd -xf "$ARCHIVE_PATH" -C "$INSTALL_DIR"

echo "Installed local Ollama runtime to $INSTALL_DIR"
echo "Preferred binary: $INSTALL_DIR/bin/ollama"
