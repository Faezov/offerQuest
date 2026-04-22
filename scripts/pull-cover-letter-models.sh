#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$ROOT_DIR/scripts/cover-letter-models.sh"

usage() {
  cat <<'EOF'
Pull a curated set of local Ollama models for cover-letter generation.

Usage:
  ./scripts/pull-cover-letter-models.sh [--all] [--model NAME ...] [--list] [--dry-run]

Options:
  --all           Include stretch models such as mistral-small.
  --model NAME    Pull only the named model. Repeat to provide multiple models.
  --list          Print the curated model set and exit.
  --dry-run       Print the models that would be pulled without pulling them.
  -h, --help      Show this help text.

Examples:
  ./scripts/pull-cover-letter-models.sh
  ./scripts/pull-cover-letter-models.sh --all
  ./scripts/pull-cover-letter-models.sh --model qwen3:14b --model gemma3:12b
EOF
}

require_ollama_server() {
  if ! "$ROOT_DIR/scripts/ollama-local.sh" list >/dev/null 2>&1; then
    echo "Local Ollama server is not reachable." >&2
    echo "Start it first with ./scripts/start-ollama-local.sh" >&2
    exit 1
  fi
}

use_all=false
dry_run=false
declare -a custom_models=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --all)
      use_all=true
      shift
      ;;
    --model)
      if [[ $# -lt 2 ]]; then
        echo "--model requires a value" >&2
        exit 1
      fi
      custom_models+=("$2")
      shift 2
      ;;
    --list)
      printf 'Recommended models:\n'
      print_cover_letter_model_list | sed 's/^/  - /'
      printf 'Stretch models:\n'
      printf '%s\n' "${COVER_LETTER_MODELS_STRETCH[@]}" | sed 's/^/  - /'
      exit 0
      ;;
    --dry-run)
      dry_run=true
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

declare -a models=()
if [[ ${#custom_models[@]} -gt 0 ]]; then
  models=("${custom_models[@]}")
elif [[ "$use_all" == true ]]; then
  mapfile -t models < <(print_cover_letter_model_list_with_stretch)
else
  mapfile -t models < <(print_cover_letter_model_list)
fi

if [[ ${#models[@]} -eq 0 ]]; then
  echo "No models selected." >&2
  exit 1
fi

printf 'Selected models:\n'
printf '  - %s\n' "${models[@]}"

if [[ "$dry_run" == true ]]; then
  exit 0
fi

require_ollama_server

for model in "${models[@]}"; do
  printf '\nPulling %s\n' "$model"
  "$ROOT_DIR/scripts/ollama-local.sh" pull "$model"
done

printf '\nFinished pulling %s model(s).\n' "${#models[@]}"
