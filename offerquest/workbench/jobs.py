from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..extractors import read_document_text
from ..jobs import read_job_records
from ..profile import build_candidate_profile
from ..reranking import rerank_job_records
from ..workspace import ProjectState, relative_to_root
from ._util import (
    build_ranking_preview_items,
    choose_ranking_source,
    list_job_record_files,
    list_profile_source_files,
    list_ranking_sources,
    resolve_workspace_input_path,
    resolve_workspace_output_path,
    select_default_document,
    select_default_jobs_file,
    suggest_rerank_output_path,
    suggest_rerank_top_n,
)


@dataclass(frozen=True)
class BuildRerankJobsResult:
    payload: dict[str, Any]
    output_path: Path
    output_path_relative: str
    run_manifest: dict[str, Any]


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
