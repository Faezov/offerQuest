#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIST_DIR="${1:-$ROOT_DIR/dist}"

mkdir -p "$DIST_DIR"
python3 -m build --sdist --wheel --outdir "$DIST_DIR" "$ROOT_DIR"

echo "Built release artifacts in $DIST_DIR"
