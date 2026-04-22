from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .cover_letter import (
    DEFAULT_OLLAMA_BASE_URL,
    generate_cover_letter_for_job_record,
    generate_cover_letter_for_job_record_llm,
    slugify,
    write_cover_letter,
)
from .jobs import find_job_record, read_job_records
from .profile import build_profile_from_files
from .workspace import ProjectState
from .workspace import relative_to_root

TEXT_PREVIEW_SUFFIXES = {".txt", ".md", ".json", ".jsonl", ".log"}
PROFILE_SOURCE_SUFFIXES = {".txt", ".md", ".doc", ".docx", ".odt"}
JOB_RECORD_SUFFIXES = {".json", ".jsonl"}


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


@dataclass(frozen=True)
class BuildCoverLetterResult:
    draft_mode: str
    payload: dict[str, Any]
    output_path: Path
    output_path_relative: str
    run_manifest: dict[str, Any]


@dataclass(frozen=True)
class CoverLetterDraftArtifact:
    draft_mode: str
    payload: dict[str, Any]
    output_path: Path
    output_path_relative: str


@dataclass(frozen=True)
class CompareCoverLettersResult:
    rule_based: CoverLetterDraftArtifact
    llm: CoverLetterDraftArtifact
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


def build_latest_rankings_view(
    project_state: ProjectState,
    *,
    limit: int = 15,
) -> dict[str, Any]:
    ranking_sources = list_ranking_sources(project_state)
    latest = ranking_sources[0] if ranking_sources else None

    if latest is None:
        return {
            "has_ranking": False,
            "ranking_sources": [],
        }

    payload = latest["payload"]
    rankings = payload.get("rankings", [])
    top_rankings = []
    for index, item in enumerate(rankings[:limit], start=1):
        top_rankings.append(
            {
                "rank": index,
                "job_title": item.get("job_title") or "Unknown title",
                "company": item.get("company") or "Unknown company",
                "location": item.get("location") or "Unknown location",
                "score": item.get("score"),
                "employment_type": item.get("employment_type"),
                "job_url": item.get("url"),
                "job_id": item.get("job_id"),
                "strengths": item.get("strengths", []),
                "gaps": item.get("gaps", []),
                "source": item.get("source"),
                "posted_at": item.get("posted_at"),
            }
        )

    return {
        "has_ranking": True,
        "ranking_file": latest["relative_path"],
        "ranking_filename": latest["path"].name,
        "modified_at": latest["modified_at"],
        "job_count": payload.get("job_count") or len(rankings),
        "top_rankings": top_rankings,
        "run_reference": latest["run_reference"],
        "ranking_sources": ranking_sources,
    }


def build_cover_letter_form_view(
    project_state: ProjectState,
    *,
    ranking_file: str | None = None,
    job_id: str | None = None,
    draft_mode: str | None = None,
    cv_path: str | None = None,
    base_cover_letter_path: str | None = None,
    jobs_file: str | None = None,
    output_path: str | None = None,
    llm_model: str | None = None,
    llm_base_url: str | None = None,
    llm_timeout_seconds: str | None = None,
    error: str | None = None,
    result: BuildCoverLetterResult | None = None,
) -> dict[str, Any]:
    ranking_sources = list_ranking_sources(project_state)
    selected_source = choose_ranking_source(ranking_sources, ranking_file=ranking_file)
    selected_job = choose_ranking_job(selected_source, job_id=job_id)
    selected_draft_mode = normalize_draft_mode(draft_mode)

    documents = list_profile_source_files(project_state)
    jobs_files = list_job_record_files(project_state)

    selected_cv = cv_path or select_default_document(documents, preferred_terms=["cv", "resume"])
    selected_base_cover_letter = base_cover_letter_path or select_default_document(
        documents,
        preferred_terms=["cover", "letter", "cl"],
    )
    selected_jobs_file = jobs_file or select_default_jobs_file(jobs_files)
    selected_output = output_path or suggest_cover_letter_output_path(selected_job, draft_mode=selected_draft_mode)

    return {
        "ranking_sources": ranking_sources,
        "selected_ranking_file": selected_source["relative_path"] if selected_source else ranking_file,
        "selected_job": selected_job,
        "selected_draft_mode": selected_draft_mode,
        "documents": documents,
        "jobs_files": jobs_files,
        "selected_cv": selected_cv,
        "selected_base_cover_letter": selected_base_cover_letter,
        "selected_jobs_file": selected_jobs_file,
        "selected_output": selected_output,
        "selected_llm_model": llm_model or "qwen3:8b",
        "selected_llm_base_url": llm_base_url or DEFAULT_OLLAMA_BASE_URL,
        "selected_llm_timeout_seconds": llm_timeout_seconds or "180",
        "error": error,
        "result": result,
        "has_rankings": bool(ranking_sources),
        "has_jobs_files": bool(jobs_files),
        "has_documents": bool(documents),
    }


def build_cover_letter_compare_view(
    project_state: ProjectState,
    *,
    ranking_file: str | None = None,
    job_id: str | None = None,
    cv_path: str | None = None,
    base_cover_letter_path: str | None = None,
    jobs_file: str | None = None,
    rule_based_output_path: str | None = None,
    llm_output_path: str | None = None,
    llm_model: str | None = None,
    llm_base_url: str | None = None,
    llm_timeout_seconds: str | None = None,
    error: str | None = None,
    result: CompareCoverLettersResult | None = None,
) -> dict[str, Any]:
    selection = build_cover_letter_selection_context(
        project_state,
        ranking_file=ranking_file,
        job_id=job_id,
        cv_path=cv_path,
        base_cover_letter_path=base_cover_letter_path,
        jobs_file=jobs_file,
    )
    selected_job = selection["selected_job"]

    return {
        **selection,
        "selected_rule_based_output": rule_based_output_path
        or suggest_cover_letter_output_path(selected_job, draft_mode="rule_based"),
        "selected_llm_output": llm_output_path
        or suggest_cover_letter_output_path(selected_job, draft_mode="llm"),
        "selected_llm_model": llm_model or "qwen3:8b",
        "selected_llm_base_url": llm_base_url or DEFAULT_OLLAMA_BASE_URL,
        "selected_llm_timeout_seconds": llm_timeout_seconds or "180",
        "error": error,
        "result": result,
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


def run_cover_letter_build(
    project_state: ProjectState,
    *,
    draft_mode: str,
    cv_path: str,
    base_cover_letter_path: str | None,
    jobs_file: str,
    job_id: str,
    output_path: str,
    llm_model: str | None = None,
    llm_base_url: str | None = None,
    llm_timeout_seconds: int | None = None,
) -> BuildCoverLetterResult:
    prepared = prepare_cover_letter_inputs(
        project_state,
        cv_path=cv_path,
        base_cover_letter_path=base_cover_letter_path,
        jobs_file=jobs_file,
        job_id=job_id,
    )
    draft = build_cover_letter_draft_artifact(
        project_state,
        prepared=prepared,
        draft_mode=draft_mode,
        output_path=output_path,
        llm_model=llm_model,
        llm_base_url=llm_base_url,
        llm_timeout_seconds=llm_timeout_seconds,
    )

    run_manifest = project_state.record_run(
        "generate-cover-letter-llm" if draft.draft_mode == "llm" else "generate-cover-letter",
        artifacts=[{"kind": "llm_cover_letter" if draft.draft_mode == "llm" else "cover_letter", "path": draft.output_path}],
        metadata={
            "draft_mode": draft.draft_mode,
            "job_id": draft.payload.get("job_id"),
            "job_title": draft.payload.get("job_title"),
            "company": draft.payload.get("company"),
            "job_url": draft.payload.get("job_url"),
            "llm_model": draft.payload.get("llm_model"),
        },
        label=draft.output_path.stem,
    )

    return BuildCoverLetterResult(
        draft_mode=draft.draft_mode,
        payload=draft.payload,
        output_path=draft.output_path,
        output_path_relative=draft.output_path_relative,
        run_manifest=run_manifest,
    )


def run_cover_letter_compare(
    project_state: ProjectState,
    *,
    cv_path: str,
    base_cover_letter_path: str | None,
    jobs_file: str,
    job_id: str,
    rule_based_output_path: str,
    llm_output_path: str,
    llm_model: str | None = None,
    llm_base_url: str | None = None,
    llm_timeout_seconds: int | None = None,
) -> CompareCoverLettersResult:
    prepared = prepare_cover_letter_inputs(
        project_state,
        cv_path=cv_path,
        base_cover_letter_path=base_cover_letter_path,
        jobs_file=jobs_file,
        job_id=job_id,
    )
    rule_based_output_full_path = resolve_workspace_output_path(project_state, rule_based_output_path)
    llm_output_full_path = resolve_workspace_output_path(project_state, llm_output_path)

    if rule_based_output_full_path == llm_output_full_path:
        raise ValueError("Rule-based and LLM output paths must be different.")

    rule_based_payload = generate_cover_letter_payload(
        prepared=prepared,
        draft_mode="rule_based",
    )
    llm_payload = generate_cover_letter_payload(
        prepared=prepared,
        draft_mode="llm",
        llm_model=llm_model,
        llm_base_url=llm_base_url,
        llm_timeout_seconds=llm_timeout_seconds,
    )

    rule_based = write_cover_letter_draft_artifact(
        project_state,
        draft_mode="rule_based",
        payload=rule_based_payload,
        output_full_path=rule_based_output_full_path,
    )
    llm = write_cover_letter_draft_artifact(
        project_state,
        draft_mode="llm",
        payload=llm_payload,
        output_full_path=llm_output_full_path,
    )

    run_manifest = project_state.record_run(
        "compare-cover-letter-drafts",
        artifacts=[
            {"kind": "cover_letter", "path": rule_based.output_path},
            {"kind": "llm_cover_letter", "path": llm.output_path},
        ],
        metadata={
            "job_id": rule_based.payload.get("job_id"),
            "job_title": rule_based.payload.get("job_title"),
            "company": rule_based.payload.get("company"),
            "job_url": rule_based.payload.get("job_url"),
            "llm_model": llm.payload.get("llm_model"),
        },
        label=f"{rule_based.output_path.stem}-comparison",
    )

    return CompareCoverLettersResult(
        rule_based=rule_based,
        llm=llm,
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


def list_ranking_sources(project_state: ProjectState) -> list[dict[str, Any]]:
    if not project_state.outputs_dir.exists():
        return []

    sources: list[dict[str, Any]] = []
    for path in project_state.outputs_dir.rglob("*.json"):
        if project_state.state_dir in path.parents:
            continue

        payload = load_json_payload(path)
        if not is_ranking_payload(payload):
            continue

        relative_path = str(relative_to_root(path, project_state.root))
        sources.append(
            {
                "path": path,
                "relative_path": relative_path,
                "payload": payload,
                "modified_at": datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds"),
                "run_reference": find_run_reference_for_artifact(project_state, relative_path),
            }
        )

    return sorted(
        sources,
        key=lambda item: item["path"].stat().st_mtime,
        reverse=True,
    )


def list_job_record_files(project_state: ProjectState) -> list[dict[str, Any]]:
    if not project_state.outputs_dir.exists():
        return []

    files: list[dict[str, Any]] = []
    for path in project_state.outputs_dir.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in JOB_RECORD_SUFFIXES:
            continue
        if project_state.state_dir in path.parents:
            continue

        try:
            records = read_job_records(path)
        except Exception:
            continue

        if not records:
            continue

        files.append(
            {
                "relative_path": str(relative_to_root(path, project_state.root)),
                "record_count": len(records),
            }
        )

    return sorted(files, key=lambda item: item["relative_path"])


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


def load_json_payload(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def is_ranking_payload(payload: Any) -> bool:
    return isinstance(payload, dict) and isinstance(payload.get("rankings"), list)


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


def build_cover_letter_selection_context(
    project_state: ProjectState,
    *,
    ranking_file: str | None = None,
    job_id: str | None = None,
    cv_path: str | None = None,
    base_cover_letter_path: str | None = None,
    jobs_file: str | None = None,
) -> dict[str, Any]:
    ranking_sources = list_ranking_sources(project_state)
    selected_source = choose_ranking_source(ranking_sources, ranking_file=ranking_file)
    selected_job = choose_ranking_job(selected_source, job_id=job_id)

    documents = list_profile_source_files(project_state)
    jobs_files = list_job_record_files(project_state)

    return {
        "ranking_sources": ranking_sources,
        "selected_ranking_file": selected_source["relative_path"] if selected_source else ranking_file,
        "selected_job": selected_job,
        "documents": documents,
        "jobs_files": jobs_files,
        "selected_cv": cv_path or select_default_document(documents, preferred_terms=["cv", "resume"]),
        "selected_base_cover_letter": base_cover_letter_path
        or select_default_document(documents, preferred_terms=["cover", "letter", "cl"]),
        "selected_jobs_file": jobs_file or select_default_jobs_file(jobs_files),
        "has_rankings": bool(ranking_sources),
        "has_jobs_files": bool(jobs_files),
        "has_documents": bool(documents),
    }


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


def select_default_jobs_file(jobs_files: list[dict[str, Any]]) -> str | None:
    for item in jobs_files:
        filename = Path(item["relative_path"]).name.lower()
        if filename == "all.jsonl":
            return item["relative_path"]
    return jobs_files[0]["relative_path"] if jobs_files else None


def suggest_cover_letter_output_path(selected_job: dict[str, Any] | None, *, draft_mode: str) -> str:
    if not selected_job:
        suffix = "-llm" if draft_mode == "llm" else ""
        return f"outputs/workbench/cover-letter{suffix}.txt"
    company = slugify(selected_job.get("company") or "company")
    title = slugify(selected_job.get("job_title") or "job")
    suffix = "-llm" if draft_mode == "llm" else ""
    return f"outputs/workbench/{company}-{title}{suffix}.txt"


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


def prepare_cover_letter_inputs(
    project_state: ProjectState,
    *,
    cv_path: str,
    base_cover_letter_path: str | None,
    jobs_file: str,
    job_id: str,
) -> dict[str, Any]:
    cv_full_path = resolve_workspace_input_path(project_state, cv_path)
    base_cover_letter_full_path = (
        resolve_workspace_input_path(project_state, base_cover_letter_path)
        if base_cover_letter_path
        else None
    )
    jobs_file_full_path = resolve_workspace_input_path(project_state, jobs_file)

    if not cv_full_path.exists():
        raise ValueError(f"CV file not found: {cv_path}")
    if base_cover_letter_full_path and not base_cover_letter_full_path.exists():
        raise ValueError(f"Base cover letter file not found: {base_cover_letter_path}")
    if not jobs_file_full_path.exists():
        raise ValueError(f"Jobs file not found: {jobs_file}")

    job_records = read_job_records(jobs_file_full_path)
    job_record = find_job_record(job_records, job_id)
    if job_record is None:
        raise ValueError(f"Job id not found in {jobs_file}: {job_id}")

    return {
        "cv_full_path": cv_full_path,
        "base_cover_letter_full_path": base_cover_letter_full_path,
        "jobs_file_full_path": jobs_file_full_path,
        "job_record": job_record,
    }


def build_cover_letter_draft_artifact(
    project_state: ProjectState,
    *,
    prepared: dict[str, Any],
    draft_mode: str,
    output_path: str,
    llm_model: str | None = None,
    llm_base_url: str | None = None,
    llm_timeout_seconds: int | None = None,
) -> CoverLetterDraftArtifact:
    output_full_path = resolve_workspace_output_path(project_state, output_path)
    payload = generate_cover_letter_payload(
        prepared=prepared,
        draft_mode=draft_mode,
        llm_model=llm_model,
        llm_base_url=llm_base_url,
        llm_timeout_seconds=llm_timeout_seconds,
    )
    return write_cover_letter_draft_artifact(
        project_state,
        draft_mode=normalize_draft_mode(draft_mode),
        payload=payload,
        output_full_path=output_full_path,
    )


def generate_cover_letter_payload(
    *,
    prepared: dict[str, Any],
    draft_mode: str,
    llm_model: str | None = None,
    llm_base_url: str | None = None,
    llm_timeout_seconds: int | None = None,
) -> dict[str, Any]:
    normalized_draft_mode = normalize_draft_mode(draft_mode)

    if normalized_draft_mode == "llm":
        return generate_cover_letter_for_job_record_llm(
            prepared["cv_full_path"],
            prepared["job_record"],
            base_cover_letter_path=prepared["base_cover_letter_full_path"],
            model=llm_model or "qwen3:8b",
            base_url=llm_base_url or DEFAULT_OLLAMA_BASE_URL,
            timeout_seconds=llm_timeout_seconds or 180,
        )

    return generate_cover_letter_for_job_record(
        prepared["cv_full_path"],
        prepared["job_record"],
        base_cover_letter_path=prepared["base_cover_letter_full_path"],
    )


def write_cover_letter_draft_artifact(
    project_state: ProjectState,
    *,
    draft_mode: str,
    payload: dict[str, Any],
    output_full_path: Path,
) -> CoverLetterDraftArtifact:
    output_full_path.parent.mkdir(parents=True, exist_ok=True)
    write_cover_letter(output_full_path, payload)
    return CoverLetterDraftArtifact(
        draft_mode=normalize_draft_mode(draft_mode),
        payload=payload,
        output_path=output_full_path,
        output_path_relative=str(relative_to_root(output_full_path, project_state.root)),
    )


def find_run_reference_for_artifact(project_state: ProjectState, relative_path: str) -> dict[str, Any] | None:
    for run in project_state.list_runs():
        artifacts = run.get("artifacts", [])
        for index, artifact in enumerate(artifacts):
            if artifact.get("path") == relative_path:
                return {
                    "run_id": run.get("id"),
                    "run_label": run.get("label"),
                    "artifact_index": index,
                }
    return None


def choose_ranking_source(
    ranking_sources: list[dict[str, Any]],
    *,
    ranking_file: str | None,
) -> dict[str, Any] | None:
    if ranking_file:
        for source in ranking_sources:
            if source["relative_path"] == ranking_file:
                return source
    return ranking_sources[0] if ranking_sources else None


def choose_ranking_job(
    ranking_source: dict[str, Any] | None,
    *,
    job_id: str | None,
) -> dict[str, Any] | None:
    if ranking_source is None:
        return None

    rankings = ranking_source["payload"].get("rankings", [])
    if job_id:
        for item in rankings:
            if item.get("job_id") == job_id:
                return item
    return rankings[0] if rankings else None


def normalize_draft_mode(draft_mode: str | None) -> str:
    if draft_mode == "llm":
        return "llm"
    return "rule_based"
