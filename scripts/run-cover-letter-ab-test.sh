#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$ROOT_DIR/scripts/cover-letter-models.sh"

usage() {
  cat <<'EOF'
Run the same local-LLM cover-letter generation across multiple models.

Usage:
  Single job:
    ./scripts/run-cover-letter-ab-test.sh \
      --cv PATH \
      --jobs-file PATH \
      --job-id JOB_ID \
      --output-dir PATH \
      [--base-cover-letter PATH] \
      [--employer-context PATH] \
      [--model NAME ... | --all]

  Ranked top jobs:
    ./scripts/run-cover-letter-ab-test.sh \
      --cv PATH \
      --jobs-file PATH \
      --ranking-file PATH \
      --output-dir PATH \
      [--base-cover-letter PATH] \
      [--employer-context-dir PATH] \
      [--top N] \
      [--docx] \
      [--model NAME ... | --all]

Options:
  --cv PATH                   CV file.
  --jobs-file PATH            JSON or JSONL job-record file.
  --job-id JOB_ID             Single job id to test.
  --ranking-file PATH         Ranking file for top-job batch testing.
  --output-dir PATH           Destination directory for generated drafts.
  --base-cover-letter PATH    Base cover letter for tone and reusable context.
  --employer-context PATH     Employer-specific notes file for single-job mode.
  --employer-context-dir PATH Employer-context directory for ranking mode.
  --top N                     Top unique jobs to generate in ranking mode, default: 3.
  --docx                      Also export .docx files in ranking mode.
  --timeout-seconds N         Ollama request timeout, default: 600.
  --base-url URL              Ollama base URL, default: http://localhost:11434.
  --all                       Include stretch models such as mistral-small.
  --model NAME                Use only the named model. Repeat for multiple models.
  --list                      Print the curated model set and exit.
  -h, --help                  Show this help text.
EOF
}

require_ollama_server() {
  if ! "$ROOT_DIR/scripts/ollama-local.sh" list >/dev/null 2>&1; then
    echo "Local Ollama server is not reachable." >&2
    echo "Start it first with ./scripts/start-ollama-local.sh" >&2
    exit 1
  fi
}

cv_path=""
jobs_file=""
job_id=""
ranking_file=""
output_dir=""
base_cover_letter=""
employer_context=""
employer_context_dir=""
top_n=3
timeout_seconds=600
base_url="http://localhost:11434"
use_all=false
export_docx=false
declare -a custom_models=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --cv)
      cv_path="$2"
      shift 2
      ;;
    --jobs-file)
      jobs_file="$2"
      shift 2
      ;;
    --job-id)
      job_id="$2"
      shift 2
      ;;
    --ranking-file)
      ranking_file="$2"
      shift 2
      ;;
    --output-dir)
      output_dir="$2"
      shift 2
      ;;
    --base-cover-letter)
      base_cover_letter="$2"
      shift 2
      ;;
    --employer-context)
      employer_context="$2"
      shift 2
      ;;
    --employer-context-dir)
      employer_context_dir="$2"
      shift 2
      ;;
    --top)
      top_n="$2"
      shift 2
      ;;
    --timeout-seconds)
      timeout_seconds="$2"
      shift 2
      ;;
    --base-url)
      base_url="$2"
      shift 2
      ;;
    --all)
      use_all=true
      shift
      ;;
    --model)
      custom_models+=("$2")
      shift 2
      ;;
    --docx)
      export_docx=true
      shift
      ;;
    --list)
      printf 'Recommended models:\n'
      print_cover_letter_model_list | sed 's/^/  - /'
      printf 'Stretch models:\n'
      printf '%s\n' "${COVER_LETTER_MODELS_STRETCH[@]}" | sed 's/^/  - /'
      exit 0
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

if [[ -z "$cv_path" || -z "$jobs_file" || -z "$output_dir" ]]; then
  echo "--cv, --jobs-file, and --output-dir are required." >&2
  exit 1
fi

if [[ -n "$job_id" && -n "$ranking_file" ]]; then
  echo "Use either --job-id or --ranking-file, not both." >&2
  exit 1
fi

if [[ -z "$job_id" && -z "$ranking_file" ]]; then
  echo "One of --job-id or --ranking-file is required." >&2
  exit 1
fi

if [[ -n "$job_id" && -n "$employer_context_dir" ]]; then
  echo "--employer-context-dir is only valid with --ranking-file." >&2
  exit 1
fi

if [[ -n "$ranking_file" && -n "$employer_context" ]]; then
  echo "--employer-context is only valid with --job-id." >&2
  exit 1
fi

declare -a models=()
if [[ ${#custom_models[@]} -gt 0 ]]; then
  models=("${custom_models[@]}")
elif [[ "$use_all" == true ]]; then
  mapfile -t models < <(print_cover_letter_model_list_with_stretch)
else
  mapfile -t models < <(print_cover_letter_model_list)
fi

mkdir -p "$output_dir"
printf '%s\n' "${models[@]}" > "$output_dir/models.txt"

printf 'Running A/B test with models:\n'
printf '  - %s\n' "${models[@]}"

require_ollama_server

if [[ -n "$job_id" ]]; then
  for model in "${models[@]}"; do
    model_slug="$(cover_letter_model_slug "$model")"
    output_path="$output_dir/$model_slug.txt"

    cmd=(
      python3 -m offerquest generate-cover-letter-llm
      --cv "$cv_path"
      --jobs-file "$jobs_file"
      --job-id "$job_id"
      --model "$model"
      --base-url "$base_url"
      --timeout-seconds "$timeout_seconds"
      --output "$output_path"
    )

    if [[ -n "$base_cover_letter" ]]; then
      cmd+=(--base-cover-letter "$base_cover_letter")
    fi

    if [[ -n "$employer_context" ]]; then
      cmd+=(--employer-context "$employer_context")
    fi

    printf '\nGenerating with %s\n' "$model"
    "${cmd[@]}"
  done

  printf '\nFinished single-job A/B test in %s\n' "$output_dir"
  exit 0
fi

for model in "${models[@]}"; do
  model_slug="$(cover_letter_model_slug "$model")"
  model_output_dir="$output_dir/$model_slug"

  cmd=(
    python3 -m offerquest generate-cover-letters-llm
    --cv "$cv_path"
    --jobs-file "$jobs_file"
    --ranking-file "$ranking_file"
    --output-dir "$model_output_dir"
    --top "$top_n"
    --model "$model"
    --base-url "$base_url"
    --timeout-seconds "$timeout_seconds"
  )

  if [[ -n "$base_cover_letter" ]]; then
    cmd+=(--base-cover-letter "$base_cover_letter")
  fi

  if [[ -n "$employer_context_dir" ]]; then
    cmd+=(--employer-context-dir "$employer_context_dir")
  fi

  if [[ "$export_docx" == true ]]; then
    cmd+=(--docx)
  fi

  printf '\nGenerating top %s letters with %s\n' "$top_n" "$model"
  "${cmd[@]}"
done

printf '\nFinished ranking-based A/B test in %s\n' "$output_dir"
