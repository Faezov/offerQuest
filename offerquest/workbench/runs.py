from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..diagnostics import build_doctor_report
from ..workspace import ProjectState
from ._util import (
    TEXT_PREVIEW_SUFFIXES,
    enrich_artifact,
    pretty_json_text,
)


@dataclass(frozen=True)
class ArtifactPreview:
    artifact: dict[str, Any]
    path: Path
    exists: bool
    preview_kind: str
    content: str | None
    note: str | None


def build_dashboard_view(project_state: ProjectState) -> dict[str, Any]:
    runs = project_state.list_runs()
    doctor_report = build_doctor_report(project_state) if not runs else None
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
        "show_onboarding": not bool(runs),
        "doctor": doctor_report,
    }


def build_runs_view(project_state: ProjectState) -> dict[str, Any]:
    runs = project_state.list_runs()
    return {
        "workspace_root": str(project_state.root),
        "runs": [build_run_card(project_state, run) for run in runs],
        "run_count": len(runs),
        "has_runs": bool(runs),
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
