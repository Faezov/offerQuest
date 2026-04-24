from __future__ import annotations

import copy
import threading
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

PAGE_CHROME: dict[str, dict[str, str]] = {
    "dashboard": {
        "section": "Workspace Overview",
        "summary": "Check setup readiness, review recent activity, and jump into the next useful step.",
    },
    "job_sources": {
        "section": "Setup",
        "summary": "Manage provider connections, refresh job feeds, and keep one merged jobs dataset current.",
    },
    "ollama_setup": {
        "section": "Local Models",
        "summary": "Install and manage the local Ollama runtime, server, and drafting models for workspace workflows.",
    },
    "build_profile_page": {
        "section": "Setup",
        "summary": "Turn your CV and base cover letter into one reusable candidate profile for ranking and drafting.",
    },
    "rankings": {
        "section": "Shortlist",
        "summary": "Review the strongest current matches and move into the next workflow from one ranked job.",
    },
    "build_rerank_jobs_page": {
        "section": "Refine Ranking",
        "summary": "Apply a second ATS-aware pass to the jobs most worth a closer look.",
    },
    "build_resume_tailoring_page": {
        "section": "Tailor CV",
        "summary": "Plan the highest-impact resume changes for one ranked role before drafting a full revision.",
    },
    "build_resume_tailored_draft_page": {
        "section": "Tailor CV",
        "summary": "Generate a concrete tailored CV draft and compare the ATS movement against the current version.",
    },
    "build_cover_letter_page": {
        "section": "Cover Letters",
        "summary": "Create a role-specific draft using either the rule-based workflow or the local Ollama-backed LLM flow.",
    },
    "compare_cover_letters_page": {
        "section": "Cover Letters",
        "summary": "Review rule-based and LLM cover-letter drafts side by side before choosing a direction.",
    },
    "runs": {
        "section": "History",
        "summary": "Browse recorded workflow history, metadata, and generated outputs for this workspace.",
    },
    "run_detail": {
        "section": "History",
        "summary": "Inspect one recorded workflow run, its metadata, and the artifacts it produced.",
    },
    "artifact_preview": {
        "section": "History",
        "summary": "Preview a generated artifact without leaving the workbench flow.",
    },
}

NAV_GROUP_SPECS: tuple[dict[str, Any], ...] = (
    {
        "label": "Setup",
        "items": (
            {"label": "Overview", "route_name": "dashboard", "active_routes": {"dashboard"}},
            {"label": "Job Sources", "route_name": "job_sources", "active_routes": {"job_sources"}},
            {"label": "Ollama Setup", "route_name": "ollama_setup", "active_routes": {"ollama_setup"}},
            {
                "label": "Build Profile",
                "route_name": "build_profile_page",
                "active_routes": {"build_profile_page"},
            },
        ),
    },
    {
        "label": "Workflows",
        "items": (
            {"label": "Latest Rankings", "route_name": "rankings", "active_routes": {"rankings"}},
            {
                "label": "Tailor CV",
                "route_name": "build_resume_tailoring_page",
                "active_routes": {
                    "build_resume_tailoring_page",
                    "build_resume_tailored_draft_page",
                },
            },
            {
                "label": "Cover Letters",
                "route_name": "build_cover_letter_page",
                "active_routes": {"build_cover_letter_page"},
            },
            {
                "label": "Compare Drafts",
                "route_name": "compare_cover_letters_page",
                "active_routes": {"compare_cover_letters_page"},
            },
            {
                "label": "Rerank Jobs",
                "route_name": "build_rerank_jobs_page",
                "active_routes": {"build_rerank_jobs_page"},
            },
        ),
    },
    {
        "label": "History",
        "items": (
            {
                "label": "Runs",
                "route_name": "runs",
                "active_routes": {"runs", "run_detail", "artifact_preview"},
            },
        ),
    },
)

FieldErrors = dict[str, str]


def collect_required_field_errors(
    values: dict[str, str | None],
    *,
    required: list[tuple[str, str]],
) -> FieldErrors:
    errors: FieldErrors = {}
    for field_name, label in required:
        if not str(values.get(field_name) or "").strip():
            errors[field_name] = f"{label} is required."
    return errors


def summarize_field_errors(
    field_errors: FieldErrors,
    *,
    fallback: str = "Please fix the highlighted fields and try again.",
) -> str | None:
    if not field_errors:
        return None
    if len(field_errors) == 1:
        return next(iter(field_errors.values()))
    return fallback


def parse_optional_positive_int(
    raw_value: str | None,
    *,
    invalid_message: str,
    minimum_message: str,
) -> tuple[int | None, str | None]:
    text = str(raw_value or "").strip()
    if not text:
        return None, None

    try:
        value = int(text)
    except ValueError:
        return None, invalid_message
    if value < 1:
        return None, minimum_message
    return value, None


def make_page_renderer(
    request: Any,
    render_page: Callable[[Any, str, dict[str, Any]], Any],
    *,
    template_name: str,
    page_title: str,
    build_view: Callable[..., dict[str, Any]],
    **base_view_kwargs: Any,
) -> Callable[..., Any]:
    def render_view(**view_kwargs: Any) -> Any:
        return render_page(
            request,
            template_name,
            {
                "page_title": page_title,
                "view": build_view(**{**base_view_kwargs, **view_kwargs}),
            },
        )

    return render_view


def maybe_render_required_field_errors(
    render_view: Callable[..., Any],
    values: dict[str, str | None],
    *,
    required: list[tuple[str, str]],
    fallback: str = "Please fix the highlighted fields and try again.",
) -> Any | None:
    field_errors = collect_required_field_errors(values, required=required)
    if not field_errors:
        return None
    return render_view(
        error=summarize_field_errors(field_errors, fallback=fallback),
        field_errors=field_errors,
    )


def parse_optional_positive_int_or_render(
    render_view: Callable[..., Any],
    *,
    field_name: str,
    raw_value: str | None,
    invalid_message: str,
    minimum_message: str,
) -> tuple[int | None, Any | None]:
    value, error = parse_optional_positive_int(
        raw_value,
        invalid_message=invalid_message,
        minimum_message=minimum_message,
    )
    if error is None:
        return value, None
    field_errors = {field_name: error}
    return None, render_view(
        error=summarize_field_errors(field_errors),
        field_errors=field_errors,
    )


def map_common_form_error(message: str) -> FieldErrors:
    if message.startswith("CV file not found:"):
        return {"cv_path": message}
    if message.startswith("Cover letter file not found:"):
        return {"cover_letter_path": message}
    if message.startswith("Base cover letter file not found:"):
        return {"base_cover_letter_path": message}
    if message.startswith("Jobs file not found:"):
        return {"jobs_file": message}
    if message.startswith("Job id not found"):
        return {"job_id": message}
    if message == "Output path must stay inside the current workspace.":
        return {"output_path": message}
    return {}


def build_job_source_field_errors(source_form_data: dict[str, str]) -> FieldErrors:
    field_errors: FieldErrors = {}
    source_type = str(source_form_data.get("type") or "").strip().lower()
    if not str(source_form_data.get("name") or "").strip():
        field_errors["source_name"] = "Source name is required."
    if source_type not in {"adzuna", "greenhouse", "manual"}:
        field_errors["source_type"] = "Choose a supported source type."
        return field_errors

    if source_type == "adzuna":
        if not str(source_form_data.get("what") or "").strip() and not str(
            source_form_data.get("where") or ""
        ).strip():
            message = "Enter search keywords or a location."
            field_errors["adzuna_what"] = message
            field_errors["adzuna_where"] = message
        for field_name, label in (
            ("pages", "Adzuna pages"),
            ("results_per_page", "Adzuna results per page"),
        ):
            raw_value = str(source_form_data.get(field_name) or "").strip()
            input_name = f"adzuna_{field_name}"
            if not raw_value:
                field_errors[input_name] = f"{label} is required."
                continue
            try:
                value = int(raw_value)
            except ValueError:
                field_errors[input_name] = f"{label} must be a whole number."
                continue
            if value < 1:
                field_errors[input_name] = f"{label} must be at least 1."
    elif source_type == "greenhouse":
        if not str(source_form_data.get("board_token") or "").strip():
            field_errors["greenhouse_board_token"] = "Board token is required for Greenhouse sources."
    elif source_type == "manual" and not str(source_form_data.get("input_path") or "").strip():
        field_errors["manual_input_path"] = "Input path is required for manual sources."

    return field_errors


def map_job_source_exception_to_field_errors(message: str) -> FieldErrors:
    if message in {"Source name is required.", "Source names must be unique."}:
        return {"source_name": message}
    if message in {
        "Output filename is required.",
        "Output filenames must be unique.",
    }:
        return {"source_output": message}
    if message == "Source type must be one of: adzuna, greenhouse, manual.":
        return {"source_type": "Choose a supported source type."}
    if message == "Greenhouse sources require a board token.":
        return {"greenhouse_board_token": message}
    if message == "Manual sources require an input path.":
        return {"manual_input_path": message}
    if message == "Adzuna sources need at least search keywords or a location.":
        return {
            "adzuna_what": message,
            "adzuna_where": message,
        }
    if message.startswith("Adzuna pages"):
        return {"adzuna_pages": message}
    if message.startswith("Adzuna results per page"):
        return {"adzuna_results_per_page": message}
    return {}


def safe_request_url_for(
    request: Any,
    route_name: str,
    *,
    fallback: str,
) -> str:
    try:
        return str(request.url_for(route_name))
    except Exception:
        return fallback


def build_navigation_groups(request: Any) -> list[dict[str, Any]]:
    route = request.scope.get("route")
    current_route_name = getattr(route, "name", None)
    groups: list[dict[str, Any]] = []

    for group_spec in NAV_GROUP_SPECS:
        items: list[dict[str, Any]] = []
        for item_spec in group_spec["items"]:
            route_name = str(item_spec["route_name"])
            fallback = "/" if route_name == "dashboard" else f"/{route_name.replace('_', '-')}"
            items.append(
                {
                    "label": item_spec["label"],
                    "href": safe_request_url_for(request, route_name, fallback=fallback),
                    "active": current_route_name in item_spec["active_routes"],
                }
            )
        groups.append({"label": group_spec["label"], "items": items})

    return groups


def build_page_chrome(request: Any) -> dict[str, Any]:
    route = request.scope.get("route")
    route_name = getattr(route, "name", None)
    chrome = PAGE_CHROME.get(
        route_name or "",
        {
            "section": "OfferQuest",
            "summary": "Work through setup, ranking, tailoring, and review from one local workspace.",
        },
    )
    return {
        "page_section": chrome["section"],
        "page_summary": chrome["summary"],
        "nav_groups": build_navigation_groups(request),
    }


class OllamaJobStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: dict[str, dict[str, Any]] = {}

    def create(self, *, intent: str, base_url: str, custom_model: str | None) -> str:
        job_id = uuid.uuid4().hex
        now = datetime.now(UTC).isoformat()
        with self._lock:
            self._jobs[job_id] = {
                "id": job_id,
                "intent": intent,
                "base_url": base_url,
                "custom_model": custom_model,
                "status": "queued",
                "progress": 0,
                "message": "Queued",
                "detail": "Waiting to start.",
                "error": None,
                "action_result": None,
                "created_at": now,
                "updated_at": now,
            }
            self._prune_locked()
        return job_id

    def update(self, job_id: str, **updates: Any) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            if "progress" in updates:
                updates["progress"] = normalize_progress(updates["progress"])
            job.update(updates)
            job["updated_at"] = datetime.now(UTC).isoformat()

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return copy.deepcopy(job) if job is not None else None

    def _prune_locked(self, *, keep_latest: int = 30) -> None:
        if len(self._jobs) <= keep_latest:
            return
        sorted_jobs = sorted(
            self._jobs.values(),
            key=lambda job: str(job.get("created_at") or ""),
            reverse=True,
        )
        keep_ids = {str(job["id"]) for job in sorted_jobs[:keep_latest]}
        for job_id in list(self._jobs):
            if job_id not in keep_ids:
                del self._jobs[job_id]


def normalize_progress(value: Any) -> int:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return 0
    return max(0, min(100, int(round(parsed))))
