#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIST_DIR="${1:-$ROOT_DIR/dist}"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

if ! compgen -G "$DIST_DIR/offerquest-*.whl" > /dev/null || ! compgen -G "$DIST_DIR/offerquest-*.tar.gz" > /dev/null; then
  "$ROOT_DIR/scripts/build-release.sh" "$DIST_DIR"
fi

BASE_VENV="$TMP_DIR/base"
WEB_VENV="$TMP_DIR/web"
WHEEL_PATH="$(ls "$DIST_DIR"/offerquest-*.whl | sort | tail -n 1)"

python3 -m venv "$BASE_VENV"
"$BASE_VENV/bin/pip" install --upgrade pip
"$BASE_VENV/bin/pip" install "$WHEEL_PATH"
"$BASE_VENV/bin/offerquest" --help > /dev/null

python3 -m venv "$WEB_VENV"
"$WEB_VENV/bin/pip" install --upgrade pip
"$WEB_VENV/bin/pip" install "$ROOT_DIR[web]"
"$WEB_VENV/bin/offerquest-workbench" --help > /dev/null

echo "Smoke test install completed successfully."
