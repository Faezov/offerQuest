from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..profile import build_profile_from_files
from ..workspace import ProjectState, relative_to_root
from ._util import (
    attach_form_feedback,
    list_profile_source_files,
    resolve_workspace_input_path,
    resolve_workspace_output_path,
    select_default_document,
    suggest_profile_output_path,
)


@dataclass(frozen=True)
class BuildProfileResult:
    profile: dict[str, Any]
    output_path: Path
    output_path_relative: str
    run_manifest: dict[str, Any]


def build_profile_form_view(
    project_state: ProjectState,
    *,
    cv_path: str | None = None,
    cover_letter_path: str | None = None,
    output_path: str | None = None,
    error: str | None = None,
    field_errors: dict[str, str] | None = None,
    result: BuildProfileResult | None = None,
) -> dict[str, Any]:
    documents = list_profile_source_files(project_state)
    default_cv = cv_path or select_default_document(documents, preferred_terms=["cv", "resume"])
    default_cover_letter = cover_letter_path or select_default_document(
        documents,
        preferred_terms=["cover", "letter", "cl"],
    )
    default_output = output_path or suggest_profile_output_path(default_cv)

    return attach_form_feedback(
        {
            "documents": documents,
            "selected_cv": default_cv,
            "selected_cover_letter": default_cover_letter,
            "selected_output": default_output,
            "result": result,
            "has_documents": bool(documents),
        },
        error=error,
        field_errors=field_errors,
    )


def run_profile_build(
    project_state: ProjectState,
    *,
    cv_path: str,
    cover_letter_path: str,
    output_path: str,
) -> BuildProfileResult:
    cv_full_path = resolve_workspace_input_path(project_state, cv_path)
    cover_letter_full_path = resolve_workspace_input_path(project_state, cover_letter_path)
    output_full_path = resolve_workspace_output_path(project_state, output_path)

    if not cv_full_path.exists():
        raise ValueError(f"CV file not found: {cv_path}")
    if not cover_letter_full_path.exists():
        raise ValueError(f"Cover letter file not found: {cover_letter_path}")

    profile = build_profile_from_files(cv_full_path, cover_letter_full_path)
    output_full_path.parent.mkdir(parents=True, exist_ok=True)
    output_full_path.write_text(json.dumps(profile, indent=2), encoding="utf-8")

    run_manifest = project_state.record_run(
        "build-profile",
        artifacts=[{"kind": "profile", "path": output_full_path}],
        metadata={"source_files": profile.get("source_files", {})},
        label=output_full_path.stem,
    )

    return BuildProfileResult(
        profile=profile,
        output_path=output_full_path,
        output_path_relative=str(relative_to_root(output_full_path, project_state.root)),
        run_manifest=run_manifest,
    )
