from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .profile import build_profile_from_files
from .workspace import ProjectState
from .workspace import relative_to_root

TEXT_PREVIEW_SUFFIXES = {".txt", ".md", ".json", ".jsonl", ".log"}
PROFILE_SOURCE_SUFFIXES = {".txt", ".md", ".doc", ".docx", ".odt"}


@dataclass(frozen=True)
class ArtifactPreview:
    artifact: dict[str, Any]
    path: Path
    exists: bool
    preview_kind: str
    content: str | None
    note: str | None


@dataclass(frozen=True)
class BuildProfileResult:
    profile: dict[str, Any]
    output_path: Path
    output_path_relative: str
    run_manifest: dict[str, Any]


def build_dashboard_view(project_state: ProjectState) -> dict[str, Any]:
    runs = project_state.list_runs()
    workflow_counts: dict[str, int] = {}
    artifact_count = 0

    for run in runs:
        workflow = str(run.get("workflow") or "unknown")
        workflow_counts[workflow] = workflow_counts.get(workflow, 0) + 1
        artifact_count += len(run.get("artifacts", []))

    recent_runs = [build_run_card(project_state, run) for run in runs[:8]]

    return {
        "workspace_root": str(project_state.root),
        "stats": {
            "run_count": len(runs),
            "artifact_count": artifact_count,
            "workflow_count": len(workflow_counts),
        },
        "workflow_counts": sorted(
            (
                {"workflow": workflow, "count": count}
                for workflow, count in workflow_counts.items()
            ),
            key=lambda item: (-item["count"], item["workflow"]),
        ),
        "recent_runs": recent_runs,
        "has_runs": bool(runs),
    }


def build_runs_view(project_state: ProjectState) -> dict[str, Any]:
    runs = project_state.list_runs()
    return {
        "workspace_root": str(project_state.root),
        "runs": [build_run_card(project_state, run) for run in runs],
        "run_count": len(runs),
        "has_runs": bool(runs),
    }


def build_profile_form_view(
    project_state: ProjectState,
    *,
    cv_path: str | None = None,
    cover_letter_path: str | None = None,
    output_path: str | None = None,
    error: str | None = None,
    result: BuildProfileResult | None = None,
) -> dict[str, Any]:
    documents = list_profile_source_files(project_state)
    default_cv = cv_path or select_default_document(documents, preferred_terms=["cv", "resume"])
    default_cover_letter = cover_letter_path or select_default_document(
        documents,
        preferred_terms=["cover", "letter", "cl"],
    )
    default_output = output_path or suggest_profile_output_path(default_cv)

    return {
        "documents": documents,
        "selected_cv": default_cv,
        "selected_cover_letter": default_cover_letter,
        "selected_output": default_output,
        "error": error,
        "result": result,
        "has_documents": bool(documents),
    }


def build_run_detail_view(project_state: ProjectState, run_id: str) -> dict[str, Any] | None:
    manifest = project_state.get_run_manifest(run_id)
    if manifest is None:
        return None

    artifacts = [
        enrich_artifact(project_state, artifact, index=index)
        for index, artifact in enumerate(manifest.get("artifacts", []))
    ]

    return {
        "manifest": manifest,
        "artifacts": artifacts,
        "artifact_count": len(artifacts),
        "has_artifacts": bool(artifacts),
    }


def build_artifact_preview(
    project_state: ProjectState,
    run_id: str,
    artifact_index: int,
    *,
    max_chars: int = 12000,
) -> ArtifactPreview | None:
    manifest = project_state.get_run_manifest(run_id)
    if manifest is None:
        return None

    artifacts = manifest.get("artifacts", [])
    if not isinstance(artifacts, list) or artifact_index < 0 or artifact_index >= len(artifacts):
        return None

    artifact = artifacts[artifact_index]
    enriched = enrich_artifact(project_state, artifact, index=artifact_index)
    path = enriched["absolute_path"]
    if not enriched["exists"]:
        return ArtifactPreview(
            artifact=enriched,
            path=path,
            exists=False,
            preview_kind="missing",
            content=None,
            note="The artifact path recorded in the run manifest does not exist anymore.",
        )

    if path.suffix.lower() not in TEXT_PREVIEW_SUFFIXES:
        return ArtifactPreview(
            artifact=enriched,
            path=path,
            exists=True,
            preview_kind="binary",
            content=None,
            note=f"Preview is only available for text-like artifacts. Open `{path.name}` directly from the workspace.",
        )

    content = path.read_text(encoding="utf-8", errors="ignore")
    preview_kind = "json" if path.suffix.lower() in {".json", ".jsonl"} else "text"

    if preview_kind == "json":
        content = pretty_json_text(content)

    if len(content) > max_chars:
        content = content[:max_chars].rstrip() + "\n\n... [truncated]"

    return ArtifactPreview(
        artifact=enriched,
        path=path,
        exists=True,
        preview_kind=preview_kind,
        content=content,
        note=None,
    )


def build_run_card(project_state: ProjectState, run: dict[str, Any]) -> dict[str, Any]:
    artifacts = [
        enrich_artifact(project_state, artifact, index=index)
        for index, artifact in enumerate(run.get("artifacts", []))
    ]
    return {
        "id": run.get("id"),
        "workflow": run.get("workflow"),
        "label": run.get("label"),
        "created_at": run.get("created_at"),
        "metadata": run.get("metadata", {}),
        "artifact_count": len(artifacts),
        "artifacts": artifacts,
    }


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


def enrich_artifact(project_state: ProjectState, artifact: dict[str, Any], *, index: int) -> dict[str, Any]:
    relative_path = artifact.get("path")
    absolute_path = project_state.resolve_artifact_path(relative_path) if relative_path else project_state.root
    return {
        **artifact,
        "index": index,
        "path": relative_path,
        "absolute_path": absolute_path,
        "exists": absolute_path.exists() if relative_path else False,
        "filename": absolute_path.name if relative_path else None,
        "suffix": absolute_path.suffix.lower() if relative_path else "",
    }


def pretty_json_text(content: str) -> str:
    stripped = content.strip()
    if not stripped:
        return ""

    try:
        if "\n" in stripped and stripped.splitlines()[0].startswith("{") is False and stripped.splitlines()[0].startswith("[") is False:
            payload = [json.loads(line) for line in stripped.splitlines() if line.strip()]
            return json.dumps(payload, indent=2)

        return json.dumps(json.loads(stripped), indent=2)
    except json.JSONDecodeError:
        return stripped


def list_profile_source_files(project_state: ProjectState) -> list[str]:
    if not project_state.data_dir.exists():
        return []

    return sorted(
        str(path.relative_to(project_state.root))
        for path in project_state.data_dir.rglob("*")
        if path.is_file()
        and path.suffix.lower() in PROFILE_SOURCE_SUFFIXES
        and not path.name.lower().startswith("readme")
    )


def select_default_document(documents: list[str], *, preferred_terms: list[str]) -> str | None:
    for document in documents:
        lowered = Path(document).name.lower()
        if any(term in lowered for term in preferred_terms):
            return document
    return documents[0] if documents else None


def suggest_profile_output_path(cv_path: str | None) -> str:
    if cv_path:
        stem = Path(cv_path).stem
        return f"outputs/profiles/{stem}-profile.json"
    return "outputs/profiles/candidate-profile.json"


def resolve_workspace_input_path(project_state: ProjectState, raw_path: str) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        return path
    return (project_state.root / path).resolve()


def resolve_workspace_output_path(project_state: ProjectState, raw_path: str) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        resolved = path.resolve()
    else:
        resolved = (project_state.root / path).resolve()

    try:
        resolved.relative_to(project_state.root)
    except ValueError as exc:
        raise ValueError("Output path must stay inside the current workspace.") from exc

    return resolved
