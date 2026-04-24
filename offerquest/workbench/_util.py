from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from ..jobs import read_job_records
from ..workspace import ProjectState, relative_to_root, slugify

TEXT_PREVIEW_SUFFIXES = {".txt", ".md", ".json", ".jsonl", ".log"}
PROFILE_SOURCE_SUFFIXES = {".txt", ".md", ".doc", ".docx", ".odt"}
JOB_RECORD_SUFFIXES = {".json", ".jsonl"}


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
        except (OSError, ValueError, json.JSONDecodeError):
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


def attach_form_feedback(
    state: dict[str, Any],
    *,
    error: str | None = None,
    field_errors: dict[str, str] | None = None,
) -> dict[str, Any]:
    normalized_field_errors = {
        str(field_name): str(message)
        for field_name, message in (field_errors or {}).items()
        if str(message).strip()
    }
    return {
        **state,
        "error": error,
        "field_errors": normalized_field_errors,
        "first_error_field": next(iter(normalized_field_errors), None),
    }


def load_json_payload(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def is_ranking_payload(payload: Any) -> bool:
    return isinstance(payload, dict) and isinstance(payload.get("rankings"), list)


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


def select_default_document(documents: list[str], *, preferred_terms: list[str]) -> str | None:
    for document in documents:
        lowered = Path(document).name.lower()
        if any(term in lowered for term in preferred_terms):
            return document
    return documents[0] if documents else None


def select_default_jobs_file(jobs_files: list[dict[str, Any]]) -> str | None:
    for item in jobs_files:
        filename = Path(item["relative_path"]).name.lower()
        if filename == "all.jsonl":
            return item["relative_path"]
    return jobs_files[0]["relative_path"] if jobs_files else None


def suggest_profile_output_path(cv_path: str | None) -> str:
    if cv_path:
        stem = Path(cv_path).stem
        return f"outputs/profiles/{stem}-profile.json"
    return "outputs/profiles/candidate-profile.json"


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


def format_user_path(path: Path) -> str:
    resolved = path.expanduser().resolve()
    home = Path.home().resolve()
    try:
        relative_home = resolved.relative_to(home)
    except ValueError:
        return str(resolved)
    return str(Path("~") / relative_home)
