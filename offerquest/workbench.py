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
from .diagnostics import build_doctor_report
from .docx import export_document_as_docx
from .extractors import read_document_text
from .jobs import (
    find_job_record,
    load_adzuna_credentials_status,
    read_job_records,
    refresh_job_sources,
    write_adzuna_credentials_file,
)
from .profile import build_candidate_profile, build_profile_from_files
from .reranking import rerank_job_records
from .resume_tailoring import (
    build_resume_tailored_draft_for_job_record,
    build_resume_tailoring_plan_for_job_record,
)
from .workspace import ProjectState
from .workspace import relative_to_root
from .workspace import write_json_atomic

TEXT_PREVIEW_SUFFIXES = {".txt", ".md", ".json", ".jsonl", ".log"}
PROFILE_SOURCE_SUFFIXES = {".txt", ".md", ".doc", ".docx", ".odt"}
JOB_RECORD_SUFFIXES = {".json", ".jsonl"}
JOB_SOURCE_TYPES = ("adzuna", "greenhouse", "manual")


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


@dataclass(frozen=True)
class BuildResumeTailoringPlanResult:
    plan: dict[str, Any]
    output_path: Path
    output_path_relative: str
    run_manifest: dict[str, Any]


@dataclass(frozen=True)
class BuildResumeTailoredDraftResult:
    comparison: dict[str, Any]
    output_path: Path
    output_path_relative: str
    analysis_output_path: Path
    analysis_output_path_relative: str
    docx_output_path: Path | None
    docx_output_path_relative: str | None
    run_manifest: dict[str, Any]


@dataclass(frozen=True)
class BuildRerankJobsResult:
    payload: dict[str, Any]
    output_path: Path
    output_path_relative: str
    run_manifest: dict[str, Any]


@dataclass(frozen=True)
class SaveAdzunaCredentialsResult:
    credentials_path: Path
    credentials_path_display: str
    saved_app_id_masked: str | None
    saved_app_key_masked: str | None


@dataclass(frozen=True)
class BuildRefreshJobsResult:
    summary: dict[str, Any]
    summary_path: Path
    summary_path_relative: str
    merged_output_path: Path | None
    merged_output_path_relative: str | None
    run_manifest: dict[str, Any]


@dataclass(frozen=True)
class SaveJobSourceConfigResult:
    config_path: Path
    config_path_relative: str
    action: str
    source_name: str
    source_count: int


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


def build_rerank_jobs_form_view(
    project_state: ProjectState,
    *,
    ranking_file: str | None = None,
    cv_path: str | None = None,
    base_cover_letter_path: str | None = None,
    jobs_file: str | None = None,
    top_n: str | None = None,
    output_path: str | None = None,
    error: str | None = None,
    result: BuildRerankJobsResult | None = None,
) -> dict[str, Any]:
    ranking_sources = list_ranking_sources(project_state)
    selected_source = choose_ranking_source(ranking_sources, ranking_file=ranking_file)
    documents = list_profile_source_files(project_state)
    jobs_files = list_job_record_files(project_state)

    return {
        "ranking_sources": ranking_sources,
        "selected_ranking_file": selected_source["relative_path"] if selected_source else ranking_file,
        "selected_ranking_filename": selected_source["path"].name if selected_source else None,
        "selected_ranking_modified_at": selected_source["modified_at"] if selected_source else None,
        "selected_ranking_job_count": (
            selected_source["payload"].get("job_count")
            or len(selected_source["payload"].get("rankings", []))
            if selected_source
            else 0
        ),
        "selected_ranking_run_reference": selected_source["run_reference"] if selected_source else None,
        "selected_ranking_strategy": (
            selected_source["payload"].get("rerank_strategy")
            if selected_source and isinstance(selected_source.get("payload"), dict)
            else None
        ),
        "selected_ranking_preview": build_ranking_preview_items(selected_source),
        "documents": documents,
        "jobs_files": jobs_files,
        "selected_cv": cv_path or select_default_document(documents, preferred_terms=["cv", "resume"]),
        "selected_base_cover_letter": base_cover_letter_path
        or select_default_document(documents, preferred_terms=["cover", "letter", "cl"]),
        "selected_jobs_file": jobs_file or select_default_jobs_file(jobs_files),
        "selected_top_n": top_n or suggest_rerank_top_n(selected_source),
        "selected_output": output_path or suggest_rerank_output_path(selected_source),
        "error": error,
        "result": result,
        "has_rankings": bool(ranking_sources),
        "has_jobs_files": bool(jobs_files),
        "has_documents": bool(documents),
    }


def build_job_sources_view(
    project_state: ProjectState,
    *,
    app_id: str | None = None,
    credentials_error: str | None = None,
    credentials_result: SaveAdzunaCredentialsResult | None = None,
    refresh_config_path: str | None = None,
    refresh_output_dir: str | None = None,
    refresh_error: str | None = None,
    refresh_result: BuildRefreshJobsResult | None = None,
    source_form_data: dict[str, Any] | None = None,
    source_form_error: str | None = None,
    source_form_result: SaveJobSourceConfigResult | None = None,
    edit_source_index: int | None = None,
    duplicate_source_index: int | None = None,
) -> dict[str, Any]:
    credentials = load_adzuna_credentials_status()
    source_summary = load_job_sources_summary(project_state)
    credentials_panel_open = bool(
        credentials_error
        or credentials_result
        or credentials["is_env_override"]
        or (
            source_summary.get("adzuna_count", 0) > 0
            and not credentials["has_effective_credentials"]
        )
    )
    selected_config_path = refresh_config_path or "jobs/sources.json"
    selected_output_dir = refresh_output_dir or "outputs/jobs"
    default_summary_output = str(Path(selected_output_dir) / "refresh-summary.json")
    source_form, source_form_mode, source_form_notice = build_job_source_form_state(
        source_summary,
        source_form_data=source_form_data,
        edit_source_index=edit_source_index,
        duplicate_source_index=duplicate_source_index,
    )

    return {
        "entered_app_id": app_id or "",
        "credentials": credentials,
        "credentials_panel_open": credentials_panel_open,
        "credentials_path_display": format_user_path(credentials["path"]),
        "source_summary": source_summary,
        "credentials_error": credentials_error,
        "credentials_result": credentials_result,
        "selected_refresh_config_path": selected_config_path,
        "selected_refresh_output_dir": selected_output_dir,
        "selected_refresh_summary_output": default_summary_output,
        "refresh_error": refresh_error,
        "refresh_result": refresh_result,
        "source_form": source_form,
        "source_form_mode": source_form_mode,
        "source_form_notice": source_form_notice,
        "source_form_error": source_form_error,
        "source_form_result": source_form_result,
        "source_type_options": list(JOB_SOURCE_TYPES),
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


def build_resume_tailoring_form_view(
    project_state: ProjectState,
    *,
    ranking_file: str | None = None,
    job_id: str | None = None,
    cv_path: str | None = None,
    base_cover_letter_path: str | None = None,
    jobs_file: str | None = None,
    output_path: str | None = None,
    error: str | None = None,
    result: BuildResumeTailoringPlanResult | None = None,
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
        "selected_output": output_path or suggest_resume_tailoring_output_path(selected_job),
        "error": error,
        "result": result,
    }


def build_resume_tailored_draft_form_view(
    project_state: ProjectState,
    *,
    ranking_file: str | None = None,
    job_id: str | None = None,
    cv_path: str | None = None,
    base_cover_letter_path: str | None = None,
    jobs_file: str | None = None,
    output_path: str | None = None,
    export_docx: str | bool | None = None,
    docx_output_path: str | None = None,
    error: str | None = None,
    result: BuildResumeTailoredDraftResult | None = None,
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
    selected_output = output_path or suggest_resume_tailored_draft_output_path(selected_job)
    selected_export_docx = normalize_boolean_toggle(export_docx, default=True)

    return {
        **selection,
        "selected_output": selected_output,
        "selected_export_docx": selected_export_docx,
        "selected_docx_output": docx_output_path or suggest_docx_output_path(selected_output),
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


def run_adzuna_credentials_save(
    *,
    app_id: str | None,
    app_key: str | None,
) -> SaveAdzunaCredentialsResult:
    existing = load_adzuna_credentials_status()
    normalized_app_id = (app_id or "").strip() or existing.get("saved_app_id")
    normalized_app_key = (app_key or "").strip() or existing.get("saved_app_key")
    if not normalized_app_id or not normalized_app_key:
        raise ValueError(
            "Adzuna app id and app key are required. After the first save, you can leave a field blank to keep the current saved value."
        )

    credentials_path = write_adzuna_credentials_file(
        normalized_app_id,
        normalized_app_key,
    )
    saved_status = load_adzuna_credentials_status(credentials_path)
    return SaveAdzunaCredentialsResult(
        credentials_path=credentials_path,
        credentials_path_display=format_user_path(credentials_path),
        saved_app_id_masked=saved_status.get("saved_app_id_masked"),
        saved_app_key_masked=saved_status.get("saved_app_key_masked"),
    )


def run_job_source_save(
    project_state: ProjectState,
    *,
    source_form_data: dict[str, Any],
) -> SaveJobSourceConfigResult:
    config_state = load_job_sources_config_state(project_state)
    if config_state["error"]:
        raise ValueError(str(config_state["error"]))

    payload = dict(config_state["payload"])
    sources = list(payload.get("sources", []))
    source_index = parse_optional_source_index(source_form_data.get("source_index"))
    source_record = build_job_source_record(
        source_form_data,
        existing_sources=sources,
        current_index=source_index,
    )

    if source_index is None:
        sources.append(source_record)
        action = "created"
    else:
        if source_index < 0 or source_index >= len(sources):
            raise ValueError("Selected source was not found in the current config.")
        sources[source_index] = source_record
        action = "updated"

    updated_payload = build_updated_job_sources_payload(payload, sources)
    write_json_atomic(config_state["path"], updated_payload)
    return SaveJobSourceConfigResult(
        config_path=config_state["path"],
        config_path_relative=config_state["path_relative"],
        action=action,
        source_name=str(source_record.get("name") or "source"),
        source_count=len(sources),
    )


def run_job_source_delete(
    project_state: ProjectState,
    *,
    source_index: int,
) -> SaveJobSourceConfigResult:
    config_state = load_job_sources_config_state(project_state)
    if config_state["error"]:
        raise ValueError(str(config_state["error"]))

    payload = dict(config_state["payload"])
    sources = list(payload.get("sources", []))
    if source_index < 0 or source_index >= len(sources):
        raise ValueError("Selected source was not found in the current config.")

    removed_source = sources.pop(source_index)
    updated_payload = build_updated_job_sources_payload(payload, sources)
    write_json_atomic(config_state["path"], updated_payload)
    return SaveJobSourceConfigResult(
        config_path=config_state["path"],
        config_path_relative=config_state["path_relative"],
        action="deleted",
        source_name=str(removed_source.get("name") or "source"),
        source_count=len(sources),
    )


def run_job_source_toggle(
    project_state: ProjectState,
    *,
    source_index: int,
) -> SaveJobSourceConfigResult:
    config_state = load_job_sources_config_state(project_state)
    if config_state["error"]:
        raise ValueError(str(config_state["error"]))

    payload = dict(config_state["payload"])
    sources = list(payload.get("sources", []))
    if source_index < 0 or source_index >= len(sources):
        raise ValueError("Selected source was not found in the current config.")

    source = dict(sources[source_index])
    enabled = source.get("enabled", True) is not False
    if enabled:
        source["enabled"] = False
        action = "disabled"
    else:
        source.pop("enabled", None)
        action = "enabled"
    sources[source_index] = source

    updated_payload = build_updated_job_sources_payload(payload, sources)
    write_json_atomic(config_state["path"], updated_payload)
    return SaveJobSourceConfigResult(
        config_path=config_state["path"],
        config_path_relative=config_state["path_relative"],
        action=action,
        source_name=str(source.get("name") or "source"),
        source_count=len(sources),
    )


def run_refresh_jobs_build(
    project_state: ProjectState,
    *,
    config_path: str,
    output_dir: str,
) -> BuildRefreshJobsResult:
    config_full_path = resolve_workspace_input_path(project_state, config_path)
    output_dir_full_path = resolve_workspace_output_path(project_state, output_dir)

    if not config_full_path.exists():
        raise ValueError(f"Jobs config file not found: {config_path}")

    summary = refresh_job_sources(
        config_full_path,
        workspace_root=project_state.root,
        output_dir=output_dir_full_path,
    )
    summary_path = project_state.resolve_artifact_path(summary["summary_output"])
    merged_output_value = summary.get("merged_output")
    merged_output_path = (
        project_state.resolve_artifact_path(merged_output_value)
        if merged_output_value
        else None
    )

    artifacts = [{"kind": "jobs_refresh_summary", "path": summary_path}]
    artifacts.extend(
        {"kind": "jobs_file", "path": project_state.resolve_artifact_path(source["output"])}
        for source in summary.get("sources", [])
        if source.get("output")
    )
    if merged_output_path is not None:
        artifacts.append({"kind": "jobs_file", "path": merged_output_path})

    run_manifest = project_state.record_run(
        "refresh-jobs",
        artifacts=artifacts,
        metadata={
            "source_count": summary.get("source_count"),
            "merged_job_count": summary.get("merged_job_count"),
            "config_path": summary.get("config_path"),
            "output_dir": summary.get("output_dir"),
        },
        label=output_dir_full_path.name,
    )

    return BuildRefreshJobsResult(
        summary=summary,
        summary_path=summary_path,
        summary_path_relative=str(relative_to_root(summary_path, project_state.root)),
        merged_output_path=merged_output_path,
        merged_output_path_relative=(
            str(relative_to_root(merged_output_path, project_state.root))
            if merged_output_path is not None
            else None
        ),
        run_manifest=run_manifest,
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


def run_resume_tailoring_plan_build(
    project_state: ProjectState,
    *,
    cv_path: str,
    base_cover_letter_path: str | None,
    jobs_file: str,
    job_id: str,
    output_path: str,
) -> BuildResumeTailoringPlanResult:
    prepared = prepare_cover_letter_inputs(
        project_state,
        cv_path=cv_path,
        base_cover_letter_path=base_cover_letter_path,
        jobs_file=jobs_file,
        job_id=job_id,
    )
    output_full_path = resolve_workspace_output_path(project_state, output_path)

    plan = build_resume_tailoring_plan_for_job_record(
        prepared["cv_full_path"],
        prepared["job_record"],
        cover_letter_path=prepared["base_cover_letter_full_path"],
    )

    output_full_path.parent.mkdir(parents=True, exist_ok=True)
    output_full_path.write_text(json.dumps(plan, indent=2), encoding="utf-8")

    run_manifest = project_state.record_run(
        "tailor-cv-plan",
        artifacts=[{"kind": "resume_tailoring_plan", "path": output_full_path}],
        metadata={
            "job_id": plan.get("job_id"),
            "job_title": plan.get("job_title"),
            "company": plan.get("company"),
            "job_url": plan.get("job_url"),
            "ats_score_before": plan.get("ats_snapshot", {}).get("score_before"),
        },
        label=output_full_path.stem,
    )

    return BuildResumeTailoringPlanResult(
        plan=plan,
        output_path=output_full_path,
        output_path_relative=str(relative_to_root(output_full_path, project_state.root)),
        run_manifest=run_manifest,
    )


def run_resume_tailored_draft_build(
    project_state: ProjectState,
    *,
    cv_path: str,
    base_cover_letter_path: str | None,
    jobs_file: str,
    job_id: str,
    output_path: str,
    export_docx: bool = False,
    docx_output_path: str | None = None,
) -> BuildResumeTailoredDraftResult:
    prepared = prepare_cover_letter_inputs(
        project_state,
        cv_path=cv_path,
        base_cover_letter_path=base_cover_letter_path,
        jobs_file=jobs_file,
        job_id=job_id,
    )
    output_full_path = resolve_workspace_output_path(project_state, output_path)
    analysis_output_path = output_full_path.parent / f"{output_full_path.stem}-analysis.json"
    docx_output_full_path = (
        resolve_workspace_output_path(project_state, docx_output_path)
        if export_docx and docx_output_path
        else output_full_path.with_suffix(".docx")
        if export_docx
        else None
    )

    if docx_output_full_path and docx_output_full_path == output_full_path:
        raise ValueError("DOCX output path must be different from the text output path.")
    if docx_output_full_path and docx_output_full_path == analysis_output_path:
        raise ValueError("DOCX output path must be different from the analysis JSON path.")

    comparison = build_resume_tailored_draft_for_job_record(
        prepared["cv_full_path"],
        prepared["job_record"],
        cover_letter_path=prepared["base_cover_letter_full_path"],
    )

    output_full_path.parent.mkdir(parents=True, exist_ok=True)
    output_full_path.write_text(comparison["tailored_cv_text"], encoding="utf-8")
    analysis_output_path.write_text(json.dumps(comparison, indent=2), encoding="utf-8")
    if docx_output_full_path:
        export_document_as_docx(output_full_path, docx_output_full_path)

    artifacts = [
        {"kind": "tailored_resume", "path": output_full_path},
        {"kind": "resume_tailoring_analysis", "path": analysis_output_path},
    ]
    if docx_output_full_path:
        artifacts.append({"kind": "tailored_resume_docx", "path": docx_output_full_path})

    run_manifest = project_state.record_run(
        "tailor-cv-draft",
        artifacts=artifacts,
        metadata={
            "job_id": comparison.get("job_id"),
            "job_title": comparison.get("job_title"),
            "company": comparison.get("company"),
            "job_url": comparison.get("job_url"),
            "ats_score_before": comparison.get("ats_before", {}).get("ats_score"),
            "ats_score_after": comparison.get("ats_after", {}).get("ats_score"),
            "ats_score_change": comparison.get("ats_delta", {}).get("score_change"),
            "docx_output_path": str(relative_to_root(docx_output_full_path, project_state.root)) if docx_output_full_path else None,
        },
        label=output_full_path.stem,
    )

    return BuildResumeTailoredDraftResult(
        comparison=comparison,
        output_path=output_full_path,
        output_path_relative=str(relative_to_root(output_full_path, project_state.root)),
        analysis_output_path=analysis_output_path,
        analysis_output_path_relative=str(relative_to_root(analysis_output_path, project_state.root)),
        docx_output_path=docx_output_full_path,
        docx_output_path_relative=(
            str(relative_to_root(docx_output_full_path, project_state.root))
            if docx_output_full_path
            else None
        ),
        run_manifest=run_manifest,
    )


def run_rerank_jobs_build(
    project_state: ProjectState,
    *,
    ranking_file: str | None,
    cv_path: str,
    base_cover_letter_path: str | None,
    jobs_file: str,
    top_n: int,
    output_path: str,
) -> BuildRerankJobsResult:
    if top_n < 1:
        raise ValueError("Top count must be at least 1.")

    cv_full_path = resolve_workspace_input_path(project_state, cv_path)
    base_cover_letter_full_path = (
        resolve_workspace_input_path(project_state, base_cover_letter_path)
        if base_cover_letter_path
        else None
    )
    jobs_file_full_path = resolve_workspace_input_path(project_state, jobs_file)
    output_full_path = resolve_workspace_output_path(project_state, output_path)

    if not cv_full_path.exists():
        raise ValueError(f"CV file not found: {cv_path}")
    if base_cover_letter_full_path and not base_cover_letter_full_path.exists():
        raise ValueError(f"Base cover letter file not found: {base_cover_letter_path}")
    if not jobs_file_full_path.exists():
        raise ValueError(f"Jobs file not found: {jobs_file}")

    selected_source = choose_ranking_source(
        list_ranking_sources(project_state),
        ranking_file=ranking_file,
    )

    cv_text = read_document_text(cv_full_path)
    cover_letter_text = (
        read_document_text(base_cover_letter_full_path)
        if base_cover_letter_full_path
        else ""
    )
    profile = build_candidate_profile(
        cv_text,
        cover_letter_text,
        cv_path=str(relative_to_root(cv_full_path, project_state.root)),
        cover_letter_path=(
            str(relative_to_root(base_cover_letter_full_path, project_state.root))
            if base_cover_letter_full_path
            else None
        ),
    )
    rankings = rerank_job_records(
        read_job_records(jobs_file_full_path),
        profile,
        cv_text=cv_text,
        cv_path=cv_full_path,
        cover_letter_text=cover_letter_text,
        top_n=top_n,
    )
    payload = {
        "job_count": len(rankings),
        "reranked_count": min(top_n, len(rankings)),
        "rerank_strategy": "ats-hybrid-v1",
        "ranking_context_file": selected_source["relative_path"] if selected_source else ranking_file,
        "jobs_file": str(relative_to_root(jobs_file_full_path, project_state.root)),
        "rankings": rankings,
    }

    output_full_path.parent.mkdir(parents=True, exist_ok=True)
    output_full_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    run_manifest = project_state.record_run(
        "rerank-jobs",
        artifacts=[{"kind": "ranking", "path": output_full_path}],
        metadata={
            "job_count": payload["job_count"],
            "reranked_count": payload["reranked_count"],
            "rerank_strategy": payload["rerank_strategy"],
            "ranking_context_file": payload["ranking_context_file"],
            "jobs_file": payload["jobs_file"],
        },
        label=output_full_path.stem,
    )

    return BuildRerankJobsResult(
        payload=payload,
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


def suggest_resume_tailoring_output_path(selected_job: dict[str, Any] | None) -> str:
    if not selected_job:
        return "outputs/workbench/resume-tailoring-plan.json"
    company = slugify(selected_job.get("company") or "company")
    title = slugify(selected_job.get("job_title") or "job")
    return f"outputs/workbench/{company}-{title}-resume-plan.json"


def suggest_resume_tailored_draft_output_path(selected_job: dict[str, Any] | None) -> str:
    if not selected_job:
        return "outputs/workbench/tailored-resume.txt"
    company = slugify(selected_job.get("company") or "company")
    title = slugify(selected_job.get("job_title") or "job")
    return f"outputs/workbench/{company}-{title}-tailored-resume.txt"


def suggest_rerank_output_path(selected_source: dict[str, Any] | None) -> str:
    if not selected_source:
        return "outputs/workbench/job-ranking-reranked.json"

    path = Path(selected_source["relative_path"])
    stem = path.stem
    if stem.endswith("-reranked"):
        filename = f"{stem}-2{path.suffix}"
    else:
        filename = f"{stem}-reranked{path.suffix}"
    return str(path.with_name(filename))


def suggest_rerank_top_n(selected_source: dict[str, Any] | None) -> str:
    if not selected_source:
        return "20"
    job_count = selected_source["payload"].get("job_count") or len(
        selected_source["payload"].get("rankings", [])
    )
    if not job_count:
        return "20"
    return str(min(20, int(job_count)))


def suggest_docx_output_path(output_path: str | None) -> str:
    if not output_path:
        return "outputs/workbench/tailored-resume.docx"
    return str(Path(output_path).with_suffix(".docx"))


def resolve_workspace_input_path(project_state: ProjectState, raw_path: str) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        resolved = path.resolve()
    else:
        resolved = (project_state.root / path).resolve()

    try:
        resolved.relative_to(project_state.root)
    except ValueError as exc:
        raise ValueError("Input path must stay inside the current workspace.") from exc

    return resolved


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


def build_ranking_preview_items(
    ranking_source: dict[str, Any] | None,
    *,
    limit: int = 5,
) -> list[dict[str, Any]]:
    if ranking_source is None:
        return []

    rankings = ranking_source["payload"].get("rankings", [])
    preview: list[dict[str, Any]] = []
    for index, item in enumerate(rankings[:limit], start=1):
        preview.append(
            {
                "rank": index,
                "job_title": item.get("job_title") or "Unknown title",
                "company": item.get("company") or "Unknown company",
                "location": item.get("location") or "Unknown location",
                "score": item.get("score"),
                "job_id": item.get("job_id"),
            }
        )
    return preview


def normalize_draft_mode(draft_mode: str | None) -> str:
    if draft_mode == "llm":
        return "llm"
    return "rule_based"


def normalize_boolean_toggle(value: str | bool | None, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return value.lower() not in {"", "0", "false", "off", "no"}


def load_job_sources_summary(project_state: ProjectState) -> dict[str, Any]:
    config_state = load_job_sources_config_state(project_state)
    config_path = config_state["path"]
    summary = {
        "exists": config_path.exists(),
        "path": config_path,
        "path_relative": config_state["path_relative"],
        "sources": [],
        "source_count": 0,
        "adzuna_count": 0,
        "greenhouse_count": 0,
        "manual_count": 0,
        "other_count": 0,
        "error": config_state["error"],
        "merge_enabled": True,
        "merge_output": "all.jsonl",
        "merge_inputs": [],
        "summary_output": "refresh-summary.json",
        "payload": config_state["payload"],
    }
    if not config_path.exists() or config_state["error"]:
        return summary

    payload = config_state["payload"]
    raw_sources = payload.get("sources", [])
    sources: list[dict[str, Any]] = []
    counts = {
        "adzuna_count": 0,
        "greenhouse_count": 0,
        "manual_count": 0,
        "other_count": 0,
    }
    merge_payload = payload.get("merge") if isinstance(payload.get("merge"), dict) else {}

    for index, raw_source in enumerate(raw_sources):
        if not isinstance(raw_source, dict):
            continue
        source_type = str(raw_source.get("type") or "unknown").strip().lower()
        if source_type == "adzuna":
            counts["adzuna_count"] += 1
            details = " / ".join(
                part
                for part in [
                    str(raw_source.get("what") or "").strip(),
                    str(raw_source.get("where") or "").strip(),
                    str(raw_source.get("country") or "").strip(),
                ]
                if part
            )
        elif source_type == "greenhouse":
            counts["greenhouse_count"] += 1
            details = str(raw_source.get("board_token") or "").strip()
        elif source_type == "manual":
            counts["manual_count"] += 1
            details = str(raw_source.get("input_path") or "").strip()
        else:
            counts["other_count"] += 1
            details = ""

        sources.append(
            {
                "index": index,
                "position": index + 1,
                "name": str(
                    raw_source.get("name") or raw_source.get("output") or f"source-{index + 1}"
                ).strip(),
                "type": source_type,
                "enabled": raw_source.get("enabled", True) is not False,
                "details": details,
                "output": str(raw_source.get("output") or "").strip() or None,
                "what": str(raw_source.get("what") or "").strip(),
                "where": str(raw_source.get("where") or "").strip(),
                "country": str(raw_source.get("country") or "").strip(),
                "pages": raw_source.get("pages"),
                "results_per_page": raw_source.get("results_per_page"),
                "board_token": str(raw_source.get("board_token") or "").strip(),
                "input_path": str(raw_source.get("input_path") or "").strip(),
            }
        )

    return {
        **summary,
        **counts,
        "sources": sources,
        "source_count": len(sources),
        "merge_enabled": bool(merge_payload.get("enabled", True)),
        "merge_output": str(merge_payload.get("output") or "all.jsonl").strip() or "all.jsonl",
        "merge_inputs": [
            str(item).strip()
            for item in merge_payload.get("inputs", [])
            if str(item).strip()
        ]
        if isinstance(merge_payload.get("inputs"), list)
        else [],
        "summary_output": str(payload.get("summary_output") or "refresh-summary.json").strip()
        or "refresh-summary.json",
    }


def load_job_sources_config_state(project_state: ProjectState) -> dict[str, Any]:
    config_path = project_state.root / "jobs" / "sources.json"
    default_payload = default_job_sources_payload()
    state = {
        "path": config_path,
        "path_relative": str(relative_to_root(config_path, project_state.root)),
        "exists": config_path.exists(),
        "payload": default_payload,
        "error": None,
    }
    if not config_path.exists():
        return state

    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {**state, "error": f"Could not parse jobs/sources.json: {exc.msg}"}

    if not isinstance(payload, dict):
        return {**state, "error": "jobs/sources.json must contain a top-level object."}
    if not isinstance(payload.get("sources", []), list):
        return {**state, "error": "jobs/sources.json must contain a `sources` list."}
    if "merge" in payload and not isinstance(payload.get("merge"), dict):
        return {**state, "error": "jobs/sources.json `merge` must be an object when present."}

    return {**state, "payload": payload}


def default_job_sources_payload() -> dict[str, Any]:
    return {
        "sources": [],
        "merge": {
            "enabled": True,
            "inputs": [],
            "output": "all.jsonl",
        },
        "summary_output": "refresh-summary.json",
    }


def default_job_source_form_data(*, source_type: str = "adzuna") -> dict[str, Any]:
    normalized_type = source_type if source_type in JOB_SOURCE_TYPES else "adzuna"
    return {
        "source_index": "",
        "name": "",
        "type": normalized_type,
        "enabled": "true",
        "output": "",
        "what": "",
        "where": "",
        "country": "au",
        "pages": "1",
        "results_per_page": "20",
        "board_token": "",
        "input_path": "jobs",
    }


def build_job_source_form_state(
    source_summary: dict[str, Any],
    *,
    source_form_data: dict[str, Any] | None,
    edit_source_index: int | None,
    duplicate_source_index: int | None,
) -> tuple[dict[str, Any], str, str | None]:
    if source_form_data is not None:
        normalized = default_job_source_form_data(
            source_type=str(source_form_data.get("type") or "adzuna").strip().lower()
        )
        normalized.update({key: source_form_data.get(key, value) for key, value in normalized.items()})
        mode = "edit" if str(normalized.get("source_index") or "").strip() else "create"
        return normalized, mode, None

    sources = source_summary.get("sources", [])
    if duplicate_source_index is not None:
        if duplicate_source_index < 0 or duplicate_source_index >= len(sources):
            return (
                default_job_source_form_data(),
                "create",
                "Selected source for duplication was not found.",
            )
        source = sources[duplicate_source_index]
        existing_names = [str(item.get("name") or "") for item in sources]
        duplicate_name = suggest_duplicate_source_name(str(source.get("name") or "source"), existing_names)
        duplicate_output = suggest_duplicate_source_output(
            duplicate_name,
            str(source.get("output") or ""),
        )
        return (
            {
                **source_to_form_data(source),
                "source_index": "",
                "name": duplicate_name,
                "output": duplicate_output,
            },
            "create",
            f"Duplicating `{source.get('name') or 'source'}` as a new source.",
        )

    if edit_source_index is not None:
        if edit_source_index < 0 or edit_source_index >= len(sources):
            return (
                default_job_source_form_data(),
                "create",
                "Selected source for editing was not found.",
            )
        source = sources[edit_source_index]
        return (
            source_to_form_data(source),
            "edit",
            f"Editing `{source.get('name') or 'source'}`.",
        )

    return default_job_source_form_data(), "create", None


def source_to_form_data(source: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_index": str(source.get("index", "")),
        "name": str(source.get("name") or ""),
        "type": str(source.get("type") or "adzuna"),
        "enabled": "true" if source.get("enabled", True) else "false",
        "output": str(source.get("output") or ""),
        "what": str(source.get("what") or ""),
        "where": str(source.get("where") or ""),
        "country": str(source.get("country") or "au"),
        "pages": str(source.get("pages") or "1"),
        "results_per_page": str(source.get("results_per_page") or "20"),
        "board_token": str(source.get("board_token") or ""),
        "input_path": str(source.get("input_path") or "jobs"),
    }


def parse_optional_source_index(value: Any) -> int | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        index = int(text)
    except ValueError as exc:
        raise ValueError("Selected source index must be a whole number.") from exc
    if index < 0:
        raise ValueError("Selected source index must not be negative.")
    return index


def build_job_source_record(
    source_form_data: dict[str, Any],
    *,
    existing_sources: list[dict[str, Any]],
    current_index: int | None,
) -> dict[str, Any]:
    source_type = str(source_form_data.get("type") or "").strip().lower()
    if source_type not in JOB_SOURCE_TYPES:
        raise ValueError("Source type must be one of: adzuna, greenhouse, manual.")

    name = str(source_form_data.get("name") or "").strip()
    if not name:
        raise ValueError("Source name is required.")

    output = str(source_form_data.get("output") or "").strip() or suggest_source_output_filename(name)
    if not output:
        raise ValueError("Output filename is required.")

    enabled = normalize_boolean_toggle(source_form_data.get("enabled"), default=True)
    record: dict[str, Any] = {
        "name": name,
        "type": source_type,
        "output": output,
    }
    if not enabled:
        record["enabled"] = False

    if source_type == "adzuna":
        what = str(source_form_data.get("what") or "").strip()
        where = str(source_form_data.get("where") or "").strip()
        if not what and not where:
            raise ValueError("Adzuna sources need at least search keywords or a location.")
        country = str(source_form_data.get("country") or "").strip() or "au"
        pages = parse_positive_int(source_form_data.get("pages"), field_name="Adzuna pages")
        results_per_page = parse_positive_int(
            source_form_data.get("results_per_page"),
            field_name="Adzuna results per page",
        )
        record.update(
            {
                "country": country,
                "pages": pages,
                "results_per_page": results_per_page,
            }
        )
        if what:
            record["what"] = what
        if where:
            record["where"] = where
    elif source_type == "greenhouse":
        board_token = str(source_form_data.get("board_token") or "").strip()
        if not board_token:
            raise ValueError("Greenhouse sources require a board token.")
        record["board_token"] = board_token
    elif source_type == "manual":
        input_path = str(source_form_data.get("input_path") or "").strip()
        if not input_path:
            raise ValueError("Manual sources require an input path.")
        record["input_path"] = input_path

    validate_job_source_uniqueness(
        record,
        existing_sources=existing_sources,
        current_index=current_index,
    )
    return record


def validate_job_source_uniqueness(
    record: dict[str, Any],
    *,
    existing_sources: list[dict[str, Any]],
    current_index: int | None,
) -> None:
    for index, existing in enumerate(existing_sources):
        if current_index is not None and index == current_index:
            continue
        if not isinstance(existing, dict):
            continue
        existing_name = str(existing.get("name") or "").strip().lower()
        existing_output = str(existing.get("output") or "").strip().lower()
        if existing_name and existing_name == str(record.get("name") or "").strip().lower():
            raise ValueError("Source names must be unique.")
        if existing_output and existing_output == str(record.get("output") or "").strip().lower():
            raise ValueError("Output filenames must be unique.")


def build_updated_job_sources_payload(
    payload: dict[str, Any],
    sources: list[dict[str, Any]],
) -> dict[str, Any]:
    updated = dict(payload)
    updated["sources"] = sources

    merge_payload = dict(updated.get("merge") or {})
    merge_payload["enabled"] = merge_payload.get("enabled", True) is not False
    merge_payload["output"] = str(merge_payload.get("output") or "all.jsonl").strip() or "all.jsonl"
    merge_payload["inputs"] = [
        str(source.get("output")).strip()
        for source in sources
        if isinstance(source, dict)
        and source.get("enabled", True) is not False
        and str(source.get("output") or "").strip()
    ]
    updated["merge"] = merge_payload
    updated["summary_output"] = (
        str(updated.get("summary_output") or "refresh-summary.json").strip()
        or "refresh-summary.json"
    )
    return updated


def parse_positive_int(value: Any, *, field_name: str) -> int:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field_name} is required.")
    try:
        number = int(text)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be a whole number.") from exc
    if number < 1:
        raise ValueError(f"{field_name} must be at least 1.")
    return number


def suggest_source_output_filename(name: str) -> str:
    return f"{slugify(name)}.jsonl"


def suggest_duplicate_source_name(name: str, existing_names: list[str]) -> str:
    base_name = f"{name}-copy"
    candidate = base_name
    suffix = 2
    normalized_existing = {item.strip().lower() for item in existing_names if item.strip()}
    while candidate.strip().lower() in normalized_existing:
        candidate = f"{base_name}-{suffix}"
        suffix += 1
    return candidate


def suggest_duplicate_source_output(name: str, output: str) -> str:
    path = Path(output) if output else Path(suggest_source_output_filename(name))
    stem = path.stem or slugify(name)
    suffix = path.suffix or ".jsonl"
    duplicate_stem = f"{stem}-copy"
    if duplicate_stem == stem:
        duplicate_stem = f"{slugify(name)}-copy"
    return f"{duplicate_stem}{suffix}"


def format_user_path(path: Path) -> str:
    resolved = path.expanduser().resolve()
    home = Path.home().resolve()
    try:
        relative_home = resolved.relative_to(home)
    except ValueError:
        return str(resolved)
    return str(Path("~") / relative_home)
