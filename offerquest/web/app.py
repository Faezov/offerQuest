import argparse
import logging
import os
import socket
from pathlib import Path
from typing import Any

from .. import config as _config
from ..errors import OfferQuestError
from ..ollama import DEFAULT_OLLAMA_BASE_URL
from ..workspace import ProjectState
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
    run_cover_letter_compare,
    run_cover_letter_build,
    run_job_source_delete,
    run_job_source_save,
    run_job_source_toggle,
    run_ollama_models_pull,
    run_profile_build,
    run_refresh_jobs_build,
    run_rerank_jobs_build,
    run_resume_tailored_draft_build,
    run_resume_tailoring_plan_build,
)

LOG_LEVEL_NAMES = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
logger = logging.getLogger(__name__)
AUTO_PORT = "auto"


def validate_required_form_fields(
    values: dict[str, str | None],
    *,
    required: list[tuple[str, str]],
) -> str | None:
    missing_labels = [
        label
        for field_name, label in required
        if not str(values.get(field_name) or "").strip()
    ]
    if not missing_labels:
        return None
    if len(missing_labels) == 1:
        return f"{missing_labels[0]} is required."
    if len(missing_labels) == 2:
        return f"{missing_labels[0]} and {missing_labels[1]} are required."
    return f"{', '.join(missing_labels[:-1])}, and {missing_labels[-1]} are required."


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


def create_app(
    *,
    workspace_root: str | Path | None = None,
    config_path: str | Path | None = None,
) -> Any:
    try:
        from fastapi import FastAPI, HTTPException, Request
        from fastapi.responses import FileResponse
        from fastapi.responses import HTMLResponse
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

    app = FastAPI(title="OfferQuest Workbench")
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
    templates = Jinja2Templates(directory=str(templates_dir))
    app.state.project_state = project_state

    def render(request: Request, template_name: str, context: dict[str, Any]) -> HTMLResponse:
        base_context = {
            "request": request,
            "workspace_root": str(project_state.root),
            "ollama_setup_href": safe_request_url_for(
                request,
                "ollama_setup",
                fallback="/ollama",
            ),
        }
        return templates.TemplateResponse(
            request,
            template_name,
            {**base_context, **context},
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
    async def favicon() -> FileResponse:
        return FileResponse(
            static_dir / "favicon.svg",
            media_type="image/svg+xml",
        )

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

        error = validate_required_form_fields(
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
        if error:
            return render(
                request,
                "build_profile.html",
                {
                    "page_title": "Build Profile",
                    "view": build_profile_form_view(
                        project_state,
                        cv_path=cv_path or None,
                        cover_letter_path=cover_letter_path or None,
                        output_path=output_path or None,
                        error=error,
                    ),
                },
            )

        try:
            result = run_profile_build(
                project_state,
                cv_path=cv_path,
                cover_letter_path=cover_letter_path,
                output_path=output_path,
            )
        except (ValueError, OfferQuestError) as exc:
            return render(
                request,
                "build_profile.html",
                {
                    "page_title": "Build Profile",
                    "view": build_profile_form_view(
                        project_state,
                        cv_path=cv_path,
                        cover_letter_path=cover_letter_path,
                        output_path=output_path,
                        error=str(exc),
                    ),
                },
            )

        return render(
            request,
            "build_profile.html",
            {
                "page_title": "Build Profile",
                "view": build_profile_form_view(
                    project_state,
                    cv_path=cv_path,
                    cover_letter_path=cover_letter_path,
                    output_path=output_path,
                    result=result,
                ),
            },
        )

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

        if intent == "save_source":
            try:
                result = run_job_source_save(
                    project_state,
                    source_form_data=source_form_data,
                )
            except (OSError, ValueError) as exc:
                return render(
                    request,
                    "job_sources.html",
                    {
                        "page_title": "Job Sources",
                        "view": build_job_sources_view(
                            project_state,
                            app_id=app_id or None,
                            refresh_config_path=config_path or None,
                            refresh_output_dir=output_dir or None,
                            source_form_data=source_form_data,
                            source_form_error=str(exc),
                        ),
                    },
                )

            return render(
                request,
                "job_sources.html",
                {
                    "page_title": "Job Sources",
                    "view": build_job_sources_view(
                        project_state,
                        refresh_config_path=config_path or None,
                        refresh_output_dir=output_dir or None,
                        source_form_result=result,
                    ),
                },
            )

        if intent in {"delete_source", "toggle_source"}:
            try:
                source_index = int(source_index_raw)
            except ValueError:
                return render(
                    request,
                    "job_sources.html",
                    {
                        "page_title": "Job Sources",
                        "view": build_job_sources_view(
                            project_state,
                            app_id=app_id or None,
                            refresh_config_path=config_path or None,
                            refresh_output_dir=output_dir or None,
                            source_form_error="Selected source index must be a whole number.",
                        ),
                    },
                )

            try:
                result = (
                    run_job_source_delete(project_state, source_index=source_index)
                    if intent == "delete_source"
                    else run_job_source_toggle(project_state, source_index=source_index)
                )
            except (OSError, ValueError) as exc:
                return render(
                    request,
                    "job_sources.html",
                    {
                        "page_title": "Job Sources",
                        "view": build_job_sources_view(
                            project_state,
                            app_id=app_id or None,
                            refresh_config_path=config_path or None,
                            refresh_output_dir=output_dir or None,
                            source_form_error=str(exc),
                        ),
                    },
                )

            return render(
                request,
                "job_sources.html",
                {
                    "page_title": "Job Sources",
                    "view": build_job_sources_view(
                        project_state,
                        refresh_config_path=config_path or None,
                        refresh_output_dir=output_dir or None,
                        source_form_result=result,
                    ),
                },
            )

        if intent == "refresh_jobs":
            error = validate_required_form_fields(
                {
                    "config_path": config_path,
                    "output_dir": output_dir,
                },
                required=[
                    ("config_path", "Config path"),
                    ("output_dir", "Output directory"),
                ],
            )
            if error:
                return render(
                    request,
                    "job_sources.html",
                    {
                        "page_title": "Job Sources",
                        "view": build_job_sources_view(
                            project_state,
                            app_id=app_id or None,
                            refresh_config_path=config_path or None,
                            refresh_output_dir=output_dir or None,
                            refresh_error=error,
                        ),
                    },
                )

            try:
                result = run_refresh_jobs_build(
                    project_state,
                    config_path=config_path,
                    output_dir=output_dir,
                )
            except (OSError, ValueError, OfferQuestError) as exc:
                return render(
                    request,
                    "job_sources.html",
                    {
                        "page_title": "Job Sources",
                        "view": build_job_sources_view(
                            project_state,
                            app_id=app_id or None,
                            refresh_config_path=config_path,
                            refresh_output_dir=output_dir,
                            refresh_error=str(exc),
                        ),
                    },
                )

            return render(
                request,
                "job_sources.html",
                {
                    "page_title": "Job Sources",
                    "view": build_job_sources_view(
                        project_state,
                        refresh_config_path=config_path,
                        refresh_output_dir=output_dir,
                        refresh_result=result,
                    ),
                },
            )

        try:
            result = run_adzuna_credentials_save(
                app_id=app_id or None,
                app_key=app_key or None,
            )
        except (OSError, ValueError) as exc:
            return render(
                request,
                "job_sources.html",
                {
                    "page_title": "Job Sources",
                    "view": build_job_sources_view(
                        project_state,
                        app_id=app_id or None,
                        refresh_config_path=config_path or None,
                        refresh_output_dir=output_dir or None,
                        credentials_error=str(exc),
                    ),
                },
            )

        return render(
            request,
            "job_sources.html",
                {
                    "page_title": "Job Sources",
                    "view": build_job_sources_view(
                        project_state,
                        app_id=app_id or None,
                        refresh_config_path=config_path or None,
                        refresh_output_dir=output_dir or None,
                        credentials_result=result,
                    ),
                },
        )

    @app.post("/ollama", response_class=HTMLResponse)
    async def ollama_setup_submit(request: Request) -> HTMLResponse:
        form = await request.form()
        intent = str(form.get("intent") or "refresh_status").strip()
        base_url = str(form.get("base_url") or "").strip() or None
        custom_model = str(form.get("custom_model") or "").strip() or None

        if intent == "refresh_status":
            return render(
                request,
                "ollama_setup.html",
                {
                    "page_title": "Ollama Setup",
                    "view": build_ollama_setup_view(
                        project_state,
                        base_url=base_url,
                        custom_model=custom_model,
                    ),
                },
            )

        try:
            if intent == "pull_recommended":
                models = list(build_ollama_setup_view(project_state, base_url=base_url)["recommended_models"])
            elif intent == "pull_missing_recommended":
                current_view = build_ollama_setup_view(
                    project_state,
                    base_url=base_url,
                    custom_model=custom_model,
                )
                models = list(current_view["missing_recommended_models"])
                if not models:
                    raise ValueError("All recommended models are already installed.")
            elif intent == "pull_custom":
                if not custom_model:
                    raise ValueError("Custom model name is required.")
                models = [custom_model]
            else:
                raise ValueError("Unknown Ollama setup action.")

            result = run_ollama_models_pull(
                base_url=base_url or DEFAULT_OLLAMA_BASE_URL,
                models=models,
            )
        except (ValueError, OfferQuestError) as exc:
            return render(
                request,
                "ollama_setup.html",
                {
                    "page_title": "Ollama Setup",
                    "view": build_ollama_setup_view(
                        project_state,
                        base_url=base_url,
                        custom_model=custom_model,
                        error=str(exc),
                    ),
                },
            )

        return render(
            request,
            "ollama_setup.html",
            {
                "page_title": "Ollama Setup",
                "view": build_ollama_setup_view(
                    project_state,
                    base_url=base_url,
                    custom_model=custom_model,
                    result=result,
                ),
            },
        )

    @app.post("/rerank-jobs/new", response_class=HTMLResponse)
    async def build_rerank_jobs_submit(request: Request) -> HTMLResponse:
        form = await request.form()
        ranking_file = str(form.get("ranking_file") or "").strip() or None
        cv_path = str(form.get("cv_path") or "").strip()
        base_cover_letter_path = str(form.get("base_cover_letter_path") or "").strip() or None
        jobs_file = str(form.get("jobs_file") or "").strip()
        top_n_raw = str(form.get("top_n") or "").strip()
        output_path = str(form.get("output_path") or "").strip()

        error = validate_required_form_fields(
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
        if error:
            return render(
                request,
                "rerank_jobs.html",
                {
                    "page_title": "Rerank Jobs",
                    "view": build_rerank_jobs_form_view(
                        project_state,
                        ranking_file=ranking_file,
                        cv_path=cv_path or None,
                        base_cover_letter_path=base_cover_letter_path,
                        jobs_file=jobs_file or None,
                        top_n=top_n_raw or None,
                        output_path=output_path or None,
                        error=error,
                    ),
                },
            )

        try:
            top_n = int(top_n_raw)
        except ValueError:
            return render(
                request,
                "rerank_jobs.html",
                {
                    "page_title": "Rerank Jobs",
                    "view": build_rerank_jobs_form_view(
                        project_state,
                        ranking_file=ranking_file,
                        cv_path=cv_path or None,
                        base_cover_letter_path=base_cover_letter_path,
                        jobs_file=jobs_file or None,
                        top_n=top_n_raw or None,
                        output_path=output_path or None,
                        error="Top count must be a whole number.",
                    ),
                },
            )

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
            return render(
                request,
                "rerank_jobs.html",
                {
                    "page_title": "Rerank Jobs",
                    "view": build_rerank_jobs_form_view(
                        project_state,
                        ranking_file=ranking_file,
                        cv_path=cv_path,
                        base_cover_letter_path=base_cover_letter_path,
                        jobs_file=jobs_file,
                        top_n=top_n_raw,
                        output_path=output_path,
                        error=str(exc),
                    ),
                },
            )

        return render(
            request,
            "rerank_jobs.html",
            {
                "page_title": "Rerank Jobs",
                "view": build_rerank_jobs_form_view(
                    project_state,
                    ranking_file=ranking_file,
                    cv_path=cv_path,
                    base_cover_letter_path=base_cover_letter_path,
                    jobs_file=jobs_file,
                    top_n=top_n_raw,
                    output_path=output_path,
                    result=result,
                ),
            },
        )

    @app.post("/cv-tailoring/new", response_class=HTMLResponse)
    async def build_resume_tailoring_submit(request: Request) -> HTMLResponse:
        form = await request.form()
        ranking_file = str(form.get("ranking_file") or "").strip() or None
        job_id = str(form.get("job_id") or "").strip() or None
        cv_path = str(form.get("cv_path") or "").strip()
        base_cover_letter_path = str(form.get("base_cover_letter_path") or "").strip() or None
        jobs_file = str(form.get("jobs_file") or "").strip()
        output_path = str(form.get("output_path") or "").strip()

        error = validate_required_form_fields(
            {
                "job_id": job_id,
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
        if error:
            return render(
                request,
                "tailor_cv.html",
                {
                    "page_title": "Tailor CV",
                    "view": build_resume_tailoring_form_view(
                        project_state,
                        ranking_file=ranking_file,
                        job_id=job_id,
                        cv_path=cv_path or None,
                        base_cover_letter_path=base_cover_letter_path,
                        jobs_file=jobs_file or None,
                        output_path=output_path or None,
                        error=error,
                    ),
                },
            )

        try:
            result = run_resume_tailoring_plan_build(
                project_state,
                cv_path=cv_path,
                base_cover_letter_path=base_cover_letter_path,
                jobs_file=jobs_file,
                job_id=job_id,
                output_path=output_path,
            )
        except (ValueError, OfferQuestError) as exc:
            return render(
                request,
                "tailor_cv.html",
                {
                    "page_title": "Tailor CV",
                    "view": build_resume_tailoring_form_view(
                        project_state,
                        ranking_file=ranking_file,
                        job_id=job_id,
                        cv_path=cv_path,
                        base_cover_letter_path=base_cover_letter_path,
                        jobs_file=jobs_file,
                        output_path=output_path,
                        error=str(exc),
                    ),
                },
            )

        return render(
            request,
            "tailor_cv.html",
            {
                "page_title": "Tailor CV",
                "view": build_resume_tailoring_form_view(
                    project_state,
                    ranking_file=ranking_file,
                    job_id=job_id,
                    cv_path=cv_path,
                    base_cover_letter_path=base_cover_letter_path,
                    jobs_file=jobs_file,
                    output_path=output_path,
                    result=result,
                ),
            },
        )

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

        error = validate_required_form_fields(
            {
                "job_id": job_id,
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
        if error:
            return render(
                request,
                "tailor_cv_draft.html",
                {
                    "page_title": "Tailored CV Draft",
                    "view": build_resume_tailored_draft_form_view(
                        project_state,
                        ranking_file=ranking_file,
                        job_id=job_id,
                        cv_path=cv_path or None,
                        base_cover_letter_path=base_cover_letter_path,
                        jobs_file=jobs_file or None,
                        output_path=output_path or None,
                        export_docx=export_docx,
                        docx_output_path=docx_output_path,
                        error=error,
                    ),
                },
            )

        try:
            result = run_resume_tailored_draft_build(
                project_state,
                cv_path=cv_path,
                base_cover_letter_path=base_cover_letter_path,
                jobs_file=jobs_file,
                job_id=job_id,
                output_path=output_path,
                export_docx=export_docx,
                docx_output_path=docx_output_path,
            )
        except (ValueError, OfferQuestError) as exc:
            return render(
                request,
                "tailor_cv_draft.html",
                {
                    "page_title": "Tailored CV Draft",
                    "view": build_resume_tailored_draft_form_view(
                        project_state,
                        ranking_file=ranking_file,
                        job_id=job_id,
                        cv_path=cv_path,
                        base_cover_letter_path=base_cover_letter_path,
                        jobs_file=jobs_file,
                        output_path=output_path,
                        export_docx=export_docx,
                        docx_output_path=docx_output_path,
                        error=str(exc),
                    ),
                },
            )

        return render(
            request,
            "tailor_cv_draft.html",
            {
                "page_title": "Tailored CV Draft",
                "view": build_resume_tailored_draft_form_view(
                    project_state,
                    ranking_file=ranking_file,
                    job_id=job_id,
                    cv_path=cv_path,
                    base_cover_letter_path=base_cover_letter_path,
                    jobs_file=jobs_file,
                    output_path=output_path,
                    export_docx=export_docx,
                    docx_output_path=docx_output_path,
                    result=result,
                ),
            },
        )

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

        error = validate_required_form_fields(
            {
                "job_id": job_id,
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
        if error:
            return render(
                request,
                "build_cover_letter.html",
                {
                    "page_title": "Generate Cover Letter",
                    "view": build_cover_letter_form_view(
                        project_state,
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
                        error=error,
                    ),
                },
            )

        try:
            llm_timeout_seconds = int(llm_timeout_seconds_raw) if llm_timeout_seconds_raw else None
        except ValueError:
            llm_timeout_seconds = None
            return render(
                request,
                "build_cover_letter.html",
                {
                    "page_title": "Generate Cover Letter",
                    "view": build_cover_letter_form_view(
                        project_state,
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
                        error="LLM timeout must be a whole number of seconds.",
                    ),
                },
            )

        try:
            result = run_cover_letter_build(
                project_state,
                draft_mode=draft_mode or "rule_based",
                cv_path=cv_path,
                base_cover_letter_path=base_cover_letter_path,
                jobs_file=jobs_file,
                job_id=job_id,
                output_path=output_path,
                llm_model=llm_model,
                llm_base_url=llm_base_url,
                llm_timeout_seconds=llm_timeout_seconds,
            )
        except (ValueError, OfferQuestError) as exc:
            return render(
                request,
                "build_cover_letter.html",
                {
                    "page_title": "Generate Cover Letter",
                    "view": build_cover_letter_form_view(
                        project_state,
                        ranking_file=ranking_file,
                        job_id=job_id,
                        draft_mode=draft_mode,
                        cv_path=cv_path,
                        base_cover_letter_path=base_cover_letter_path,
                        jobs_file=jobs_file,
                        output_path=output_path,
                        llm_model=llm_model,
                        llm_base_url=llm_base_url,
                        llm_timeout_seconds=llm_timeout_seconds_raw,
                        error=str(exc),
                    ),
                },
            )

        return render(
            request,
            "build_cover_letter.html",
            {
                "page_title": "Generate Cover Letter",
                "view": build_cover_letter_form_view(
                    project_state,
                    ranking_file=ranking_file,
                    job_id=job_id,
                    draft_mode=draft_mode,
                    cv_path=cv_path,
                    base_cover_letter_path=base_cover_letter_path,
                    jobs_file=jobs_file,
                    output_path=output_path,
                    llm_model=llm_model,
                    llm_base_url=llm_base_url,
                    llm_timeout_seconds=llm_timeout_seconds_raw,
                    result=result,
                ),
            },
        )

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

        error = validate_required_form_fields(
            {
                "job_id": job_id,
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
        if error:
            return render(
                request,
                "compare_cover_letters.html",
                {
                    "page_title": "Compare Drafts",
                    "view": build_cover_letter_compare_view(
                        project_state,
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
                        error=error,
                    ),
                },
            )

        try:
            llm_timeout_seconds = int(llm_timeout_seconds_raw) if llm_timeout_seconds_raw else None
        except ValueError:
            return render(
                request,
                "compare_cover_letters.html",
                {
                    "page_title": "Compare Drafts",
                    "view": build_cover_letter_compare_view(
                        project_state,
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
                        error="LLM timeout must be a whole number of seconds.",
                    ),
                },
            )

        try:
            result = run_cover_letter_compare(
                project_state,
                cv_path=cv_path,
                base_cover_letter_path=base_cover_letter_path,
                jobs_file=jobs_file,
                job_id=job_id,
                rule_based_output_path=rule_based_output_path,
                llm_output_path=llm_output_path,
                llm_model=llm_model,
                llm_base_url=llm_base_url,
                llm_timeout_seconds=llm_timeout_seconds,
            )
        except (ValueError, OfferQuestError) as exc:
            return render(
                request,
                "compare_cover_letters.html",
                {
                    "page_title": "Compare Drafts",
                    "view": build_cover_letter_compare_view(
                        project_state,
                        ranking_file=ranking_file,
                        job_id=job_id,
                        cv_path=cv_path,
                        base_cover_letter_path=base_cover_letter_path,
                        jobs_file=jobs_file,
                        rule_based_output_path=rule_based_output_path,
                        llm_output_path=llm_output_path,
                        llm_model=llm_model,
                        llm_base_url=llm_base_url,
                        llm_timeout_seconds=llm_timeout_seconds_raw,
                        error=str(exc),
                    ),
                },
            )

        return render(
            request,
            "compare_cover_letters.html",
            {
                "page_title": "Compare Drafts",
                "view": build_cover_letter_compare_view(
                    project_state,
                    ranking_file=ranking_file,
                    job_id=job_id,
                    cv_path=cv_path,
                    base_cover_letter_path=base_cover_letter_path,
                    jobs_file=jobs_file,
                    rule_based_output_path=rule_based_output_path,
                    llm_output_path=llm_output_path,
                    llm_model=llm_model,
                    llm_base_url=llm_base_url,
                    llm_timeout_seconds=llm_timeout_seconds_raw,
                    result=result,
                ),
            },
        )

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
