#!/usr/bin/env bash

# Shared model groups for local cover-letter generation experiments.
# The recommended set is chosen to fit comfortably on a ~12 GB GPU while
# still offering a real quality step up over tiny smoke-test models.

COVER_LETTER_MODELS_RECOMMENDED=(
  "qwen3:8b"
  "gemma3:12b"
  "qwen3:14b"
)

# Stretch models may work, but are more likely to spill into system RAM and
# become noticeably slower on a laptop-class 12 GB GPU.
COVER_LETTER_MODELS_STRETCH=(
  "gpt-oss:20b"
  "mistral-small"
)

cover_letter_model_slug() {
  printf '%s' "$1" | tr '/:' '--'
}

print_cover_letter_model_list() {
  printf '%s\n' "${COVER_LETTER_MODELS_RECOMMENDED[@]}"
}

print_cover_letter_model_list_with_stretch() {
  print_cover_letter_model_list
  printf '%s\n' "${COVER_LETTER_MODELS_STRETCH[@]}"
}
