import argparse
import copy
import logging
import os
import socket
import threading
import uuid
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from typing import Any

from .. import config as _config
from ..errors import OfferQuestError
from ..ollama import DEFAULT_OLLAMA_BASE_URL, RECOMMENDED_OLLAMA_MODELS
from ..workbench import (
    build_artifact_preview,
    build_cover_letter_compare_view,
    build_cover_letter_form_view,
    build_dashboard_view,
    build_job_sources_view,
    build_latest_rankings_view,
    build_ollama_setup_view,
    build_profile_form_view,
    build_rerank_jobs_form_view,
    build_resume_tailored_draft_form_view,
    build_resume_tailoring_form_view,
    build_run_detail_view,
    build_runs_view,
    run_adzuna_credentials_save,
    run_cover_letter_build,
    run_cover_letter_compare,
    run_job_source_delete,
    run_job_source_save,
    run_job_source_toggle,
    run_local_ollama_runtime_install,
    run_ollama_models_pull,
    run_ollama_server_restart,
    run_profile_build,
    run_refresh_jobs_build,
    run_rerank_jobs_build,
    run_resume_tailored_draft_build,
    run_resume_tailoring_plan_build,
)
from ..workspace import ProjectState

LOG_LEVEL_NAMES = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
logger = logging.getLogger(__name__)
AUTO_PORT = "auto"

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


def parse_port_argument(value: str) -> int | str:
    normalized = value.strip().lower()
    if normalized == AUTO_PORT:
        return AUTO_PORT

    try:
        port = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Port must be a whole number or `auto`.") from exc

    if port < 1 or port > 65535:
        raise argparse.ArgumentTypeError("Port must be between 1 and 65535, or `auto`.")
    return port


def resolve_port(host: str, requested_port: int | str) -> int:
    if requested_port == AUTO_PORT:
        return find_available_port(host)
    return int(requested_port)


def find_available_port(host: str) -> int:
    last_error: OSError | None = None
    for family, socktype, proto, _, sockaddr in socket.getaddrinfo(
        host,
        0,
        type=socket.SOCK_STREAM,
    ):
        try:
            with socket.socket(family, socktype, proto) as candidate:
                candidate.bind(sockaddr)
                return int(candidate.getsockname()[1])
        except OSError as exc:
            last_error = exc

    if last_error is not None:
        raise OSError(f"Could not find a free port for host {host}: {last_error}") from last_error
    raise OSError(f"Could not find a free port for host {host}.")


def format_workbench_url(host: str, port: int) -> str:
    display_host = normalize_display_host(host)
    if ":" in display_host and not display_host.startswith("["):
        return f"http://[{display_host}]:{port}"
    return f"http://{display_host}:{port}"


def normalize_display_host(host: str) -> str:
    if host in {"127.0.0.1", "0.0.0.0", "::1", "::", "localhost"}:
        return "localhost"
    return host


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


def create_app(
    *,
    workspace_root: str | Path | None = None,
    config_path: str | Path | None = None,
) -> Any:
    try:
        from fastapi import FastAPI, HTTPException, Request
        from fastapi.responses import HTMLResponse, JSONResponse, Response
        from fastapi.staticfiles import StaticFiles
        from fastapi.templating import Jinja2Templates
    except ImportError as exc:
        raise RuntimeError(
            "The local web workbench requires FastAPI, Jinja2, and Uvicorn. "
            "Install them with `pip install -e .[web]`."
        ) from exc

    if config_path is not None:
        _config.set_active(_config.load_config(config_path))

    root_value = workspace_root or os.getenv("OFFERQUEST_WORKSPACE_ROOT") or Path.cwd()
    root = Path(root_value).resolve()
    project_state = ProjectState.from_root(root)
    logger.info("Creating OfferQuest workbench app for %s", root)

    templates_dir = Path(__file__).with_name("templates")
    static_dir = Path(__file__).with_name("static")
    favicon_svg = (static_dir / "favicon.svg").read_bytes()

    app = FastAPI(title="OfferQuest Workbench")
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
    templates = Jinja2Templates(directory=str(templates_dir))
    app.state.project_state = project_state
    app.state.ollama_jobs = OllamaJobStore()

    def render(request: Request, template_name: str, context: dict[str, Any]) -> HTMLResponse:
        base_context = {
            "request": request,
            "page_title": str(context.get("page_title") or "OfferQuest"),
            "workspace_root": str(project_state.root),
            "ollama_setup_href": safe_request_url_for(
                request,
                "ollama_setup",
                fallback="/ollama",
            ),
            **build_page_chrome(request),
        }
        return templates.TemplateResponse(
            request,
            template_name,
            {**base_context, **context},
        )

    def resolve_ollama_action_models(
        *,
        intent: str,
        base_url: str | None,
        custom_model: str | None,
    ) -> list[str]:
        if intent == "pull_recommended":
            return list(RECOMMENDED_OLLAMA_MODELS)
        if intent == "pull_missing_recommended":
            current_view = build_ollama_setup_view(
                project_state,
                base_url=base_url,
                custom_model=custom_model,
            )
            models = list(current_view["missing_recommended_models"])
            if not models:
                raise ValueError("All recommended models are already installed.")
            return models
        if intent == "pull_custom":
            if not custom_model:
                raise ValueError("Custom model name is required.")
            return [custom_model]
        raise ValueError("Unknown Ollama setup action.")

    def update_ollama_job_from_progress(job_id: str, payload: dict[str, Any]) -> None:
        updates: dict[str, Any] = {}
        if payload.get("progress") is not None:
            updates["progress"] = payload.get("progress")
        if payload.get("message") or payload.get("status"):
            updates["message"] = payload.get("message") or payload.get("status")
        if payload.get("detail"):
            updates["detail"] = payload.get("detail")
        elif payload.get("status"):
            updates["detail"] = payload.get("status")
        if payload.get("completed_bytes") is not None:
            updates["completed_bytes"] = payload.get("completed_bytes")
        if payload.get("total_bytes") is not None:
            updates["total_bytes"] = payload.get("total_bytes")
        if updates:
            app.state.ollama_jobs.update(job_id, **updates)

    def run_ollama_setup_progress_job(
        *,
        job_id: str,
        intent: str,
        base_url: str,
        custom_model: str | None,
    ) -> None:
        app.state.ollama_jobs.update(
            job_id,
            status="running",
            progress=1,
            message="Starting Ollama action",
            detail="Preparing the requested action.",
        )
        try:
            if intent in {"pull_recommended", "pull_missing_recommended", "pull_custom"}:
                models = resolve_ollama_action_models(
                    intent=intent,
                    base_url=base_url,
                    custom_model=custom_model,
                )
                result = run_ollama_models_pull(
                    base_url=base_url,
                    models=models,
                    progress_callback=lambda payload: update_ollama_job_from_progress(job_id, payload),
                )
                title = {
                    "pull_recommended": "Models pulled",
                    "pull_missing_recommended": "Missing recommended models pulled",
                    "pull_custom": "Custom model pulled",
                }[intent]
                action_result = {
                    "title": title,
                    "details": [
                        f"Pulled models: {', '.join(result.pulled_models)}",
                        f"Installed models now: {len(result.ollama_status.get('models', []))}",
                    ],
                }
            elif intent == "download_runtime":
                install_result = run_local_ollama_runtime_install(
                    progress_callback=lambda payload: update_ollama_job_from_progress(job_id, payload),
                )
                action_result = {
                    "title": "Local Ollama runtime downloaded",
                    "details": [
                        f"Command source: {install_result.get('command_source') or 'unknown'}",
                        f"Runtime path: {install_result.get('local_runtime_path') or 'not detected'}",
                    ],
                }
            elif intent == "restart_server":
                app.state.ollama_jobs.update(
                    job_id,
                    progress=20,
                    message="Starting managed Ollama server",
                    detail="Waiting for the server to become reachable.",
                )
                restart_result = run_ollama_server_restart(base_url=base_url)
                action_result = {
                    "title": (
                        "Managed Ollama server restarted"
                        if restart_result.get("restarted_existing")
                        else "Managed Ollama server started"
                    ),
                    "details": [
                        f"Base URL: {restart_result.get('base_url')}",
                        f"Managed PID: {restart_result.get('pid')}",
                    ],
                }
            else:
                raise ValueError("Unknown Ollama setup action.")
        except (ValueError, OfferQuestError) as exc:
            app.state.ollama_jobs.update(
                job_id,
                status="failed",
                progress=100,
                message="Ollama action failed",
                detail=str(exc),
                error=str(exc),
            )
        except Exception as exc:  # pragma: no cover - defensive guard for background thread
            logger.exception("Unexpected Ollama setup job failure")
            app.state.ollama_jobs.update(
                job_id,
                status="failed",
                progress=100,
                message="Ollama action failed",
                detail=str(exc),
                error=str(exc),
            )
        else:
            app.state.ollama_jobs.update(
                job_id,
                status="succeeded",
                progress=100,
                message=action_result["title"],
                detail=" ".join(action_result["details"]),
                action_result=action_result,
            )

    @app.get("/", response_class=HTMLResponse)
    async def dashboard(request: Request) -> HTMLResponse:
        return render(
            request,
            "dashboard.html",
            {
                "page_title": "Workbench",
                "view": build_dashboard_view(project_state),
            },
        )

    @app.get("/favicon.ico", include_in_schema=False)
    async def favicon() -> Response:
        return Response(content=favicon_svg, media_type="image/svg+xml")

    @app.get("/runs", response_class=HTMLResponse)
    async def runs(request: Request) -> HTMLResponse:
        return render(
            request,
            "runs.html",
            {
                "page_title": "Runs",
                "view": build_runs_view(project_state),
            },
        )

    @app.get("/rankings", response_class=HTMLResponse)
    async def rankings(request: Request) -> HTMLResponse:
        return render(
            request,
            "rankings.html",
            {
                "page_title": "Latest Rankings",
                "view": build_latest_rankings_view(project_state),
            },
        )

    @app.get("/job-sources", response_class=HTMLResponse)
    async def job_sources(
        request: Request,
        edit_source: int | None = None,
        duplicate_source: int | None = None,
    ) -> HTMLResponse:
        return render(
            request,
            "job_sources.html",
            {
                "page_title": "Job Sources",
                "view": build_job_sources_view(
                    project_state,
                    edit_source_index=edit_source,
                    duplicate_source_index=duplicate_source,
                ),
            },
        )

    @app.get("/ollama", response_class=HTMLResponse)
    async def ollama_setup(
        request: Request,
        base_url: str | None = None,
    ) -> HTMLResponse:
        return render(
            request,
            "ollama_setup.html",
            {
                "page_title": "Ollama Setup",
                "view": build_ollama_setup_view(
                    project_state,
                    base_url=base_url,
                ),
            },
        )

    @app.post("/ollama/jobs")
    async def ollama_setup_job_submit(request: Request) -> JSONResponse:
        form = await request.form()
        intent = str(form.get("intent") or "refresh_status").strip()
        base_url = str(form.get("base_url") or "").strip() or DEFAULT_OLLAMA_BASE_URL
        custom_model = str(form.get("custom_model") or "").strip() or None

        if intent == "refresh_status":
            return JSONResponse(
                {"error": "Refresh status does not run as a background job."},
                status_code=400,
            )
        if intent not in {
            "download_runtime",
            "restart_server",
            "pull_recommended",
            "pull_missing_recommended",
            "pull_custom",
        }:
            return JSONResponse({"error": "Unknown Ollama setup action."}, status_code=400)

        job_id = app.state.ollama_jobs.create(
            intent=intent,
            base_url=base_url,
            custom_model=custom_model,
        )
        thread = threading.Thread(
            target=run_ollama_setup_progress_job,
            kwargs={
                "job_id": job_id,
                "intent": intent,
                "base_url": base_url,
                "custom_model": custom_model,
            },
            daemon=True,
        )
        thread.start()
        return JSONResponse(
            {
                "job_id": job_id,
                "status_url": str(request.url_for("ollama_setup_job_status", job_id=job_id)),
            }
        )

    @app.get("/ollama/jobs/{job_id}")
    async def ollama_setup_job_status(job_id: str) -> JSONResponse:
        job = app.state.ollama_jobs.get(job_id)
        if job is None:
            return JSONResponse({"error": "Ollama setup job was not found."}, status_code=404)
        return JSONResponse(job)

    @app.get("/build-profile", response_class=HTMLResponse)
    async def build_profile_page(request: Request) -> HTMLResponse:
        return render(
            request,
            "build_profile.html",
            {
                "page_title": "Build Profile",
                "view": build_profile_form_view(project_state),
            },
        )

    @app.get("/rerank-jobs/new", response_class=HTMLResponse)
    async def build_rerank_jobs_page(
        request: Request,
        ranking_file: str | None = None,
    ) -> HTMLResponse:
        return render(
            request,
            "rerank_jobs.html",
            {
                "page_title": "Rerank Jobs",
                "view": build_rerank_jobs_form_view(
                    project_state,
                    ranking_file=ranking_file,
                ),
            },
        )

    @app.get("/cv-tailoring/new", response_class=HTMLResponse)
    async def build_resume_tailoring_page(
        request: Request,
        ranking_file: str | None = None,
        job_id: str | None = None,
    ) -> HTMLResponse:
        return render(
            request,
            "tailor_cv.html",
            {
                "page_title": "Tailor CV",
                "view": build_resume_tailoring_form_view(
                    project_state,
                    ranking_file=ranking_file,
                    job_id=job_id,
                ),
            },
        )

    @app.get("/cv-tailoring/draft/new", response_class=HTMLResponse)
    async def build_resume_tailored_draft_page(
        request: Request,
        ranking_file: str | None = None,
        job_id: str | None = None,
    ) -> HTMLResponse:
        return render(
            request,
            "tailor_cv_draft.html",
            {
                "page_title": "Tailored CV Draft",
                "view": build_resume_tailored_draft_form_view(
                    project_state,
                    ranking_file=ranking_file,
                    job_id=job_id,
                ),
            },
        )

    @app.get("/cover-letters/new", response_class=HTMLResponse)
    async def build_cover_letter_page(
        request: Request,
        ranking_file: str | None = None,
        job_id: str | None = None,
        mode: str | None = None,
    ) -> HTMLResponse:
        return render(
            request,
            "build_cover_letter.html",
            {
                "page_title": "Generate Cover Letter",
                "view": build_cover_letter_form_view(
                    project_state,
                    ranking_file=ranking_file,
                    job_id=job_id,
                    draft_mode=mode,
                ),
            },
        )

    @app.get("/cover-letters/compare", response_class=HTMLResponse)
    async def compare_cover_letters_page(
        request: Request,
        ranking_file: str | None = None,
        job_id: str | None = None,
    ) -> HTMLResponse:
        return render(
            request,
            "compare_cover_letters.html",
            {
                "page_title": "Compare Drafts",
                "view": build_cover_letter_compare_view(
                    project_state,
                    ranking_file=ranking_file,
                    job_id=job_id,
                ),
            },
        )

    @app.post("/build-profile", response_class=HTMLResponse)
    async def build_profile_submit(request: Request) -> HTMLResponse:
        form = await request.form()
        cv_path = str(form.get("cv_path") or "").strip()
        cover_letter_path = str(form.get("cover_letter_path") or "").strip()
        output_path = str(form.get("output_path") or "").strip()

        render_view = make_page_renderer(
            request,
            render,
            template_name="build_profile.html",
            page_title="Build Profile",
            build_view=partial(build_profile_form_view, project_state),
            cv_path=cv_path or None,
            cover_letter_path=cover_letter_path or None,
            output_path=output_path or None,
        )

        validation_response = maybe_render_required_field_errors(
            render_view,
            {
                "cv_path": cv_path,
                "cover_letter_path": cover_letter_path,
                "output_path": output_path,
            },
            required=[
                ("cv_path", "CV file"),
                ("cover_letter_path", "Cover letter file"),
                ("output_path", "Output path"),
            ],
        )
        if validation_response is not None:
            return validation_response

        try:
            result = run_profile_build(
                project_state,
                cv_path=cv_path,
                cover_letter_path=cover_letter_path,
                output_path=output_path,
            )
        except (ValueError, OfferQuestError) as exc:
            return render_view(
                error=str(exc),
                field_errors=map_common_form_error(str(exc)),
            )

        return render_view(result=result)

    @app.post("/job-sources", response_class=HTMLResponse)
    async def job_sources_submit(request: Request) -> HTMLResponse:
        form = await request.form()
        intent = str(form.get("intent") or "save_credentials").strip()
        app_id = str(form.get("app_id") or "").strip()
        app_key = str(form.get("app_key") or "").strip()
        config_path = str(form.get("config_path") or "").strip()
        output_dir = str(form.get("output_dir") or "").strip()
        source_form_data = {
            "source_index": str(form.get("source_index") or "").strip(),
            "name": str(form.get("source_name") or "").strip(),
            "type": str(form.get("source_type") or "").strip(),
            "enabled": str(form.get("source_enabled") or "").strip(),
            "output": str(form.get("source_output") or "").strip(),
            "what": str(form.get("adzuna_what") or "").strip(),
            "where": str(form.get("adzuna_where") or "").strip(),
            "country": str(form.get("adzuna_country") or "").strip(),
            "pages": str(form.get("adzuna_pages") or "").strip(),
            "results_per_page": str(form.get("adzuna_results_per_page") or "").strip(),
            "board_token": str(form.get("greenhouse_board_token") or "").strip(),
            "input_path": str(form.get("manual_input_path") or "").strip(),
        }
        source_index_raw = str(form.get("source_index") or "").strip()
        page_title = "Job Sources"

        def render_view(
            *,
            app_id_value: str | None = app_id or None,
            config_path_value: str | None = config_path or None,
            output_dir_value: str | None = output_dir or None,
            **view_kwargs: Any,
        ) -> HTMLResponse:
            return render(
                request,
                "job_sources.html",
                {
                    "page_title": page_title,
                    "view": build_job_sources_view(
                        project_state,
                        app_id=app_id_value,
                        refresh_config_path=config_path_value,
                        refresh_output_dir=output_dir_value,
                        **view_kwargs,
                    ),
                },
            )

        if intent in {"save_source", "restore_source"}:
            source_field_errors = build_job_source_field_errors(source_form_data)
            if source_field_errors:
                return render_view(
                    source_form_data=source_form_data,
                    source_form_error=summarize_field_errors(
                        source_field_errors,
                        fallback="Please fix the highlighted source fields and try again.",
                    ),
                    source_field_errors=source_field_errors,
                )
            try:
                source_result = run_job_source_save(
                    project_state,
                    source_form_data=source_form_data,
                )
            except (OSError, ValueError) as exc:
                source_field_errors = map_job_source_exception_to_field_errors(str(exc))
                return render_view(
                    source_form_data=source_form_data,
                    source_form_error=str(exc),
                    source_field_errors=source_field_errors,
                )

            if intent == "restore_source":
                source_result = replace(source_result, action="restored")

            return render_view(app_id_value=None, source_form_result=source_result)

        if intent in {"delete_source", "toggle_source"}:
            try:
                source_index = int(source_index_raw)
            except ValueError:
                return render_view(
                    source_form_error="Selected source index must be a whole number.",
                )

            try:
                source_result = (
                    run_job_source_delete(project_state, source_index=source_index)
                    if intent == "delete_source"
                    else run_job_source_toggle(project_state, source_index=source_index)
                )
            except (OSError, ValueError) as exc:
                return render_view(
                    source_form_error=str(exc),
                )

            return render_view(app_id_value=None, source_form_result=source_result)

        if intent == "refresh_jobs":
            refresh_field_errors = collect_required_field_errors(
                {
                    "config_path": config_path,
                    "output_dir": output_dir,
                },
                required=[
                    ("config_path", "Config path"),
                    ("output_dir", "Output directory"),
                ],
            )
            if refresh_field_errors:
                return render_view(
                    refresh_error=summarize_field_errors(
                        refresh_field_errors,
                        fallback="Please fill in the required refresh settings.",
                    ),
                    refresh_field_errors=refresh_field_errors,
                )

            try:
                refresh_result = run_refresh_jobs_build(
                    project_state,
                    config_path=config_path,
                    output_dir=output_dir,
                )
            except (OSError, ValueError, OfferQuestError) as exc:
                return render_view(
                    config_path_value=config_path,
                    output_dir_value=output_dir,
                    refresh_error=str(exc),
                    refresh_field_errors=map_common_form_error(str(exc)),
                )

            return render_view(
                app_id_value=None,
                config_path_value=config_path,
                output_dir_value=output_dir,
                refresh_result=refresh_result,
            )

        try:
            credentials_result = run_adzuna_credentials_save(
                app_id=app_id or None,
                app_key=app_key or None,
            )
        except (OSError, ValueError) as exc:
            credentials_field_errors: FieldErrors = {}
            if str(exc).startswith("Adzuna app id and app key are required."):
                credentials_field_errors = {
                    "app_id": "Adzuna app id is required.",
                    "app_key": "Adzuna app key is required.",
                }
            return render_view(
                credentials_error=str(exc),
                credentials_field_errors=credentials_field_errors,
            )

        return render_view(credentials_result=credentials_result)

    @app.post("/ollama", response_class=HTMLResponse)
    async def ollama_setup_submit(request: Request) -> HTMLResponse:
        form = await request.form()
        intent = str(form.get("intent") or "refresh_status").strip()
        base_url = str(form.get("base_url") or "").strip() or None
        custom_model = str(form.get("custom_model") or "").strip() or None
        render_view = make_page_renderer(
            request,
            render,
            template_name="ollama_setup.html",
            page_title="Ollama Setup",
            build_view=partial(build_ollama_setup_view, project_state),
            base_url=base_url,
            custom_model=custom_model,
        )

        if intent == "refresh_status":
            return render_view()

        try:
            result = None
            action_result: dict[str, Any] | None = None
            if intent == "pull_recommended":
                models = resolve_ollama_action_models(
                    intent=intent,
                    base_url=base_url,
                    custom_model=custom_model,
                )
                result = run_ollama_models_pull(
                    base_url=base_url or DEFAULT_OLLAMA_BASE_URL,
                    models=models,
                )
                action_result = {
                    "title": "Models pulled",
                    "details": [
                        f"Pulled models: {', '.join(result.pulled_models)}",
                        f"Installed models now: {len(result.ollama_status.get('models', []))}",
                    ],
                }
            elif intent == "pull_missing_recommended":
                models = resolve_ollama_action_models(
                    intent=intent,
                    base_url=base_url,
                    custom_model=custom_model,
                )
                if not models:
                    raise ValueError("All recommended models are already installed.")
                result = run_ollama_models_pull(
                    base_url=base_url or DEFAULT_OLLAMA_BASE_URL,
                    models=models,
                )
                action_result = {
                    "title": "Missing recommended models pulled",
                    "details": [
                        f"Pulled models: {', '.join(result.pulled_models)}",
                        f"Installed models now: {len(result.ollama_status.get('models', []))}",
                    ],
                }
            elif intent == "pull_custom":
                models = resolve_ollama_action_models(
                    intent=intent,
                    base_url=base_url,
                    custom_model=custom_model,
                )
                result = run_ollama_models_pull(
                    base_url=base_url or DEFAULT_OLLAMA_BASE_URL,
                    models=models,
                )
                action_result = {
                    "title": "Custom model pulled",
                    "details": [
                        f"Pulled model: {custom_model}",
                        f"Installed models now: {len(result.ollama_status.get('models', []))}",
                    ],
                }
            elif intent == "download_runtime":
                install_result = run_local_ollama_runtime_install()
                result = None
                action_result = {
                    "title": "Local Ollama runtime downloaded",
                    "details": [
                        f"Command source: {install_result.get('command_source') or 'unknown'}",
                        f"Runtime path: {install_result.get('local_runtime_path') or 'not detected'}",
                    ],
                }
            elif intent == "restart_server":
                restart_result = run_ollama_server_restart(
                    base_url=base_url or DEFAULT_OLLAMA_BASE_URL,
                )
                result = None
                action_result = {
                    "title": (
                        "Managed Ollama server restarted"
                        if restart_result.get("restarted_existing")
                        else "Managed Ollama server started"
                    ),
                    "details": [
                        f"Base URL: {restart_result.get('base_url')}",
                        f"Managed PID: {restart_result.get('pid')}",
                    ],
                }
            else:
                raise ValueError("Unknown Ollama setup action.")
        except (ValueError, OfferQuestError) as exc:
            return render_view(
                error=str(exc),
            )

        return render_view(result=result, action_result=action_result)

    @app.post("/rerank-jobs/new", response_class=HTMLResponse)
    async def build_rerank_jobs_submit(request: Request) -> HTMLResponse:
        form = await request.form()
        ranking_file = str(form.get("ranking_file") or "").strip() or None
        cv_path = str(form.get("cv_path") or "").strip()
        base_cover_letter_path = str(form.get("base_cover_letter_path") or "").strip() or None
        jobs_file = str(form.get("jobs_file") or "").strip()
        top_n_raw = str(form.get("top_n") or "").strip()
        output_path = str(form.get("output_path") or "").strip()

        render_view = make_page_renderer(
            request,
            render,
            template_name="rerank_jobs.html",
            page_title="Rerank Jobs",
            build_view=partial(build_rerank_jobs_form_view, project_state),
            ranking_file=ranking_file,
            cv_path=cv_path or None,
            base_cover_letter_path=base_cover_letter_path,
            jobs_file=jobs_file or None,
            top_n=top_n_raw or None,
            output_path=output_path or None,
        )

        validation_response = maybe_render_required_field_errors(
            render_view,
            {
                "cv_path": cv_path,
                "jobs_file": jobs_file,
                "top_n": top_n_raw,
                "output_path": output_path,
            },
            required=[
                ("cv_path", "CV file"),
                ("jobs_file", "Jobs file"),
                ("top_n", "Rerank count"),
                ("output_path", "Output path"),
            ],
        )
        if validation_response is not None:
            return validation_response

        top_n, numeric_response = parse_optional_positive_int_or_render(
            render_view,
            field_name="top_n",
            raw_value=top_n_raw,
            invalid_message="Top count must be a whole number.",
            minimum_message="Top count must be at least 1.",
        )
        if numeric_response is not None:
            return numeric_response
        assert top_n is not None

        try:
            result = run_rerank_jobs_build(
                project_state,
                ranking_file=ranking_file,
                cv_path=cv_path,
                base_cover_letter_path=base_cover_letter_path,
                jobs_file=jobs_file,
                top_n=top_n,
                output_path=output_path,
            )
        except (ValueError, OfferQuestError) as exc:
            return render_view(
                error=str(exc),
                field_errors=map_common_form_error(str(exc)),
            )

        return render_view(result=result)

    @app.post("/cv-tailoring/new", response_class=HTMLResponse)
    async def build_resume_tailoring_submit(request: Request) -> HTMLResponse:
        form = await request.form()
        ranking_file = str(form.get("ranking_file") or "").strip() or None
        job_id = str(form.get("job_id") or "").strip() or None
        cv_path = str(form.get("cv_path") or "").strip()
        base_cover_letter_path = str(form.get("base_cover_letter_path") or "").strip() or None
        jobs_file = str(form.get("jobs_file") or "").strip()
        output_path = str(form.get("output_path") or "").strip()

        render_view = make_page_renderer(
            request,
            render,
            template_name="tailor_cv.html",
            page_title="Tailor CV",
            build_view=partial(build_resume_tailoring_form_view, project_state),
            ranking_file=ranking_file,
            job_id=job_id,
            cv_path=cv_path or None,
            base_cover_letter_path=base_cover_letter_path,
            jobs_file=jobs_file or None,
            output_path=output_path or None,
        )

        validation_response = maybe_render_required_field_errors(
            render_view,
            {
                "job_id": job_id or "",
                "cv_path": cv_path,
                "jobs_file": jobs_file,
                "output_path": output_path,
            },
            required=[
                ("job_id", "Selected job"),
                ("cv_path", "CV file"),
                ("jobs_file", "Jobs file"),
                ("output_path", "Output path"),
            ],
        )
        if validation_response is not None:
            return validation_response

        try:
            result = run_resume_tailoring_plan_build(
                project_state,
                cv_path=cv_path,
                base_cover_letter_path=base_cover_letter_path,
                jobs_file=jobs_file,
                job_id=job_id or "",
                output_path=output_path,
            )
        except (ValueError, OfferQuestError) as exc:
            return render_view(
                error=str(exc),
                field_errors=map_common_form_error(str(exc)),
            )

        return render_view(result=result)

    @app.post("/cv-tailoring/draft/new", response_class=HTMLResponse)
    async def build_resume_tailored_draft_submit(request: Request) -> HTMLResponse:
        form = await request.form()
        ranking_file = str(form.get("ranking_file") or "").strip() or None
        job_id = str(form.get("job_id") or "").strip() or None
        cv_path = str(form.get("cv_path") or "").strip()
        base_cover_letter_path = str(form.get("base_cover_letter_path") or "").strip() or None
        jobs_file = str(form.get("jobs_file") or "").strip()
        output_path = str(form.get("output_path") or "").strip()
        export_docx = bool(form.get("export_docx"))
        docx_output_path = str(form.get("docx_output_path") or "").strip() or None

        render_view = make_page_renderer(
            request,
            render,
            template_name="tailor_cv_draft.html",
            page_title="Tailored CV Draft",
            build_view=partial(build_resume_tailored_draft_form_view, project_state),
            ranking_file=ranking_file,
            job_id=job_id,
            cv_path=cv_path or None,
            base_cover_letter_path=base_cover_letter_path,
            jobs_file=jobs_file or None,
            output_path=output_path or None,
            export_docx=export_docx,
            docx_output_path=docx_output_path,
        )

        validation_response = maybe_render_required_field_errors(
            render_view,
            {
                "job_id": job_id or "",
                "cv_path": cv_path,
                "jobs_file": jobs_file,
                "output_path": output_path,
            },
            required=[
                ("job_id", "Selected job"),
                ("cv_path", "CV file"),
                ("jobs_file", "Jobs file"),
                ("output_path", "Output path"),
            ],
        )
        if validation_response is not None:
            return validation_response

        try:
            result = run_resume_tailored_draft_build(
                project_state,
                cv_path=cv_path,
                base_cover_letter_path=base_cover_letter_path,
                jobs_file=jobs_file,
                job_id=job_id or "",
                output_path=output_path,
                export_docx=export_docx,
                docx_output_path=docx_output_path,
            )
        except (ValueError, OfferQuestError) as exc:
            message = str(exc)
            if message.startswith("DOCX output path"):
                field_errors = {"docx_output_path": message}
            else:
                field_errors = map_common_form_error(message)
            return render_view(error=message, field_errors=field_errors)

        return render_view(result=result)

    @app.post("/cover-letters/new", response_class=HTMLResponse)
    async def build_cover_letter_submit(request: Request) -> HTMLResponse:
        form = await request.form()
        ranking_file = str(form.get("ranking_file") or "").strip() or None
        job_id = str(form.get("job_id") or "").strip() or None
        draft_mode = str(form.get("draft_mode") or "").strip() or None
        cv_path = str(form.get("cv_path") or "").strip()
        base_cover_letter_path = str(form.get("base_cover_letter_path") or "").strip() or None
        jobs_file = str(form.get("jobs_file") or "").strip()
        output_path = str(form.get("output_path") or "").strip()
        llm_model = str(form.get("llm_model") or "").strip() or None
        llm_base_url = str(form.get("llm_base_url") or "").strip() or None
        llm_timeout_seconds_raw = str(form.get("llm_timeout_seconds") or "").strip() or None

        render_view = make_page_renderer(
            request,
            render,
            template_name="build_cover_letter.html",
            page_title="Generate Cover Letter",
            build_view=partial(build_cover_letter_form_view, project_state),
            ranking_file=ranking_file,
            job_id=job_id,
            draft_mode=draft_mode,
            cv_path=cv_path or None,
            base_cover_letter_path=base_cover_letter_path,
            jobs_file=jobs_file or None,
            output_path=output_path or None,
            llm_model=llm_model,
            llm_base_url=llm_base_url,
            llm_timeout_seconds=llm_timeout_seconds_raw,
        )

        validation_response = maybe_render_required_field_errors(
            render_view,
            {
                "job_id": job_id or "",
                "cv_path": cv_path,
                "jobs_file": jobs_file,
                "output_path": output_path,
            },
            required=[
                ("job_id", "Selected job"),
                ("cv_path", "CV file"),
                ("jobs_file", "Jobs file"),
                ("output_path", "Output path"),
            ],
        )
        if validation_response is not None:
            return validation_response

        llm_timeout_seconds, numeric_response = parse_optional_positive_int_or_render(
            render_view,
            field_name="llm_timeout_seconds",
            raw_value=llm_timeout_seconds_raw or "",
            invalid_message="LLM timeout must be a whole number of seconds.",
            minimum_message="LLM timeout must be at least 1 second.",
        )
        if numeric_response is not None:
            return numeric_response

        try:
            result = run_cover_letter_build(
                project_state,
                draft_mode=draft_mode or "rule_based",
                cv_path=cv_path,
                base_cover_letter_path=base_cover_letter_path,
                jobs_file=jobs_file,
                job_id=job_id or "",
                output_path=output_path,
                llm_model=llm_model,
                llm_base_url=llm_base_url,
                llm_timeout_seconds=llm_timeout_seconds,
            )
        except (ValueError, OfferQuestError) as exc:
            message = str(exc)
            if "timeout" in message.lower():
                field_errors = {"llm_timeout_seconds": message}
            else:
                field_errors = map_common_form_error(message)
            return render_view(error=message, field_errors=field_errors)

        return render_view(result=result)

    @app.post("/cover-letters/compare", response_class=HTMLResponse)
    async def compare_cover_letters_submit(request: Request) -> HTMLResponse:
        form = await request.form()
        ranking_file = str(form.get("ranking_file") or "").strip() or None
        job_id = str(form.get("job_id") or "").strip() or None
        cv_path = str(form.get("cv_path") or "").strip()
        base_cover_letter_path = str(form.get("base_cover_letter_path") or "").strip() or None
        jobs_file = str(form.get("jobs_file") or "").strip()
        rule_based_output_path = str(form.get("rule_based_output_path") or "").strip()
        llm_output_path = str(form.get("llm_output_path") or "").strip()
        llm_model = str(form.get("llm_model") or "").strip() or None
        llm_base_url = str(form.get("llm_base_url") or "").strip() or None
        llm_timeout_seconds_raw = str(form.get("llm_timeout_seconds") or "").strip() or None

        render_view = make_page_renderer(
            request,
            render,
            template_name="compare_cover_letters.html",
            page_title="Compare Drafts",
            build_view=partial(build_cover_letter_compare_view, project_state),
            ranking_file=ranking_file,
            job_id=job_id,
            cv_path=cv_path or None,
            base_cover_letter_path=base_cover_letter_path,
            jobs_file=jobs_file or None,
            rule_based_output_path=rule_based_output_path or None,
            llm_output_path=llm_output_path or None,
            llm_model=llm_model,
            llm_base_url=llm_base_url,
            llm_timeout_seconds=llm_timeout_seconds_raw,
        )

        validation_response = maybe_render_required_field_errors(
            render_view,
            {
                "job_id": job_id or "",
                "cv_path": cv_path,
                "jobs_file": jobs_file,
                "rule_based_output_path": rule_based_output_path,
                "llm_output_path": llm_output_path,
            },
            required=[
                ("job_id", "Selected job"),
                ("cv_path", "CV file"),
                ("jobs_file", "Jobs file"),
                ("rule_based_output_path", "Rule-based output path"),
                ("llm_output_path", "LLM output path"),
            ],
        )
        if validation_response is not None:
            return validation_response

        llm_timeout_seconds, numeric_response = parse_optional_positive_int_or_render(
            render_view,
            field_name="llm_timeout_seconds",
            raw_value=llm_timeout_seconds_raw or "",
            invalid_message="LLM timeout must be a whole number of seconds.",
            minimum_message="LLM timeout must be at least 1 second.",
        )
        if numeric_response is not None:
            return numeric_response

        try:
            result = run_cover_letter_compare(
                project_state,
                cv_path=cv_path,
                base_cover_letter_path=base_cover_letter_path,
                jobs_file=jobs_file,
                job_id=job_id or "",
                rule_based_output_path=rule_based_output_path,
                llm_output_path=llm_output_path,
                llm_model=llm_model,
                llm_base_url=llm_base_url,
                llm_timeout_seconds=llm_timeout_seconds,
            )
        except (ValueError, OfferQuestError) as exc:
            message = str(exc)
            if "timeout" in message.lower():
                field_errors = {"llm_timeout_seconds": message}
            else:
                field_errors = map_common_form_error(message)
            return render_view(error=message, field_errors=field_errors)

        return render_view(result=result)

    @app.get("/runs/{run_id}", response_class=HTMLResponse)
    async def run_detail(request: Request, run_id: str) -> HTMLResponse:
        detail = build_run_detail_view(project_state, run_id)
        if detail is None:
            raise HTTPException(status_code=404, detail="Run not found")
        return render(
            request,
            "run_detail.html",
            {
                "page_title": detail["manifest"].get("label") or detail["manifest"].get("workflow") or run_id,
                "view": detail,
            },
        )

    @app.get("/runs/{run_id}/artifacts/{artifact_index}", response_class=HTMLResponse)
    async def artifact_preview(request: Request, run_id: str, artifact_index: int) -> HTMLResponse:
        preview = build_artifact_preview(project_state, run_id, artifact_index)
        if preview is None:
            raise HTTPException(status_code=404, detail="Artifact not found")
        return render(
            request,
            "artifact_preview.html",
            {
                "page_title": preview.artifact.get("filename") or "Artifact Preview",
                "preview": preview,
                "run_id": run_id,
            },
        )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the OfferQuest local web workbench")
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="Workspace root, default: current directory")
    parser.add_argument("--config", type=Path, help="Optional OfferQuest JSON config override")
    parser.add_argument("--log-level", default="INFO", choices=LOG_LEVEL_NAMES, help="Logging verbosity for workbench diagnostics, default: INFO")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host, default: 127.0.0.1")
    parser.add_argument(
        "--port",
        type=parse_port_argument,
        default=8787,
        help="Bind port, default: 8787. Use `auto` to choose a free port automatically.",
    )
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload for local development")
    args = parser.parse_args(argv)
    configure_logging(args.log_level)

    try:
        import uvicorn
    except ImportError as exc:
        raise SystemExit(
            "The local web workbench requires Uvicorn. Install it with `pip install -e .[web]`."
        ) from exc

    os.environ["OFFERQUEST_WORKSPACE_ROOT"] = str(args.root.resolve())
    if args.config:
        _config.load_config(args.config)
        os.environ[_config.CONFIG_PATH_ENVVAR] = str(args.config.resolve())
    port = resolve_port(args.host, args.port)
    launch_url = format_workbench_url(args.host, port)
    logger.info("Starting OfferQuest workbench on %s:%s (reload=%s)", args.host, port, args.reload)
    print(f"OfferQuest workbench available at {launch_url}")

    if args.reload:
        uvicorn.run(
            "offerquest.web.app:create_app",
            host=args.host,
            port=port,
            reload=True,
            factory=True,
        )
        return 0

    try:
        app = create_app(workspace_root=args.root, config_path=args.config)
    except OfferQuestError as exc:
        raise SystemExit(f"error: {exc}") from exc
    uvicorn.run(app, host=args.host, port=port, reload=False)
    return 0


def configure_logging(level_name: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level_name.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
