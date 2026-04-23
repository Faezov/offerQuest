from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..cover_letter import (
    generate_cover_letter_for_job_record,
    generate_cover_letter_for_job_record_llm,
    write_cover_letter,
)
from ..docx import export_document_as_docx
from ..jobs import find_job_record, read_job_records
from ..ollama import (
    DEFAULT_OLLAMA_BASE_URL,
    RECOMMENDED_OLLAMA_MODELS,
    get_ollama_status,
    select_default_ollama_model,
)
from ..resume_tailoring import (
    build_resume_tailored_draft_for_job_record,
    build_resume_tailoring_plan_for_job_record,
)
from ..workspace import ProjectState, relative_to_root
from ._util import (
    attach_form_feedback,
    choose_ranking_job,
    choose_ranking_source,
    list_job_record_files,
    list_profile_source_files,
    list_ranking_sources,
    normalize_boolean_toggle,
    normalize_draft_mode,
    resolve_workspace_input_path,
    resolve_workspace_output_path,
    select_default_document,
    select_default_jobs_file,
    suggest_cover_letter_output_path,
    suggest_docx_output_path,
    suggest_resume_tailored_draft_output_path,
    suggest_resume_tailoring_output_path,
)


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


def build_ollama_form_state(llm_base_url: str | None) -> dict[str, Any]:
    base_url = llm_base_url or DEFAULT_OLLAMA_BASE_URL
    status = get_ollama_status(base_url, timeout_seconds=1)
    available_models = [
        str(model.get("name"))
        for model in status.get("models", [])
        if model.get("name")
    ]
    return {
        "status": status,
        "available_models": available_models,
    }


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
    field_errors: dict[str, str] | None = None,
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
    ollama_state = build_ollama_form_state(llm_base_url)

    return attach_form_feedback(
        {
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
            "selected_llm_model": select_default_ollama_model(
                ollama_state["status"],
                explicit_model=llm_model,
            ),
            "selected_llm_base_url": llm_base_url or DEFAULT_OLLAMA_BASE_URL,
            "selected_llm_timeout_seconds": llm_timeout_seconds or "180",
            "ollama_status": ollama_state["status"],
            "available_llm_models": ollama_state["available_models"],
            "recommended_llm_models": list(RECOMMENDED_OLLAMA_MODELS),
            "ollama_needs_setup": not bool(ollama_state["status"].get("reachable"))
            or not bool(ollama_state["available_models"]),
            "result": result,
            "has_rankings": bool(ranking_sources),
            "has_jobs_files": bool(jobs_files),
            "has_documents": bool(documents),
        },
        error=error,
        field_errors=field_errors,
    )


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
    field_errors: dict[str, str] | None = None,
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
    ollama_state = build_ollama_form_state(llm_base_url)

    return attach_form_feedback(
        {
            **selection,
            "selected_rule_based_output": rule_based_output_path
            or suggest_cover_letter_output_path(selected_job, draft_mode="rule_based"),
            "selected_llm_output": llm_output_path
            or suggest_cover_letter_output_path(selected_job, draft_mode="llm"),
            "selected_llm_model": select_default_ollama_model(
                ollama_state["status"],
                explicit_model=llm_model,
            ),
            "selected_llm_base_url": llm_base_url or DEFAULT_OLLAMA_BASE_URL,
            "selected_llm_timeout_seconds": llm_timeout_seconds or "180",
            "ollama_status": ollama_state["status"],
            "available_llm_models": ollama_state["available_models"],
            "recommended_llm_models": list(RECOMMENDED_OLLAMA_MODELS),
            "ollama_needs_setup": not bool(ollama_state["status"].get("reachable"))
            or not bool(ollama_state["available_models"]),
            "result": result,
        },
        error=error,
        field_errors=field_errors,
    )


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
    field_errors: dict[str, str] | None = None,
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

    return attach_form_feedback(
        {
            **selection,
            "selected_output": output_path or suggest_resume_tailoring_output_path(selected_job),
            "result": result,
        },
        error=error,
        field_errors=field_errors,
    )


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
    field_errors: dict[str, str] | None = None,
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

    return attach_form_feedback(
        {
            **selection,
            "selected_output": selected_output,
            "selected_export_docx": selected_export_docx,
            "selected_docx_output": docx_output_path or suggest_docx_output_path(selected_output),
            "result": result,
        },
        error=error,
        field_errors=field_errors,
    )


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

    artifacts: list[dict[str, Any]] = [
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
