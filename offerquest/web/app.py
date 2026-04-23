import argparse
import os
from pathlib import Path
from typing import Any

from .. import config as _config
from ..errors import ProfileValidationError
from ..ollama import OllamaError
from ..workspace import ProjectState
from ..workbench import (
    build_artifact_preview,
    build_cover_letter_compare_view,
    build_cover_letter_form_view,
    build_dashboard_view,
    build_job_sources_view,
    build_latest_rankings_view,
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
    run_profile_build,
    run_refresh_jobs_build,
    run_rerank_jobs_build,
    run_resume_tailored_draft_build,
    run_resume_tailoring_plan_build,
)


def create_app(
    *,
    workspace_root: str | Path | None = None,
    config_path: str | Path | None = None,
) -> Any:
    try:
        from fastapi import FastAPI, HTTPException, Request
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

        if not cv_path or not cover_letter_path or not output_path:
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
                        error="CV file, cover letter file, and output path are all required.",
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
        except ValueError as exc:
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
            if not config_path or not output_dir:
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
                            refresh_error="Config path and output directory are both required.",
                        ),
                    },
                )

            try:
                result = run_refresh_jobs_build(
                    project_state,
                    config_path=config_path,
                    output_dir=output_dir,
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

    @app.post("/rerank-jobs/new", response_class=HTMLResponse)
    async def build_rerank_jobs_submit(request: Request) -> HTMLResponse:
        form = await request.form()
        ranking_file = str(form.get("ranking_file") or "").strip() or None
        cv_path = str(form.get("cv_path") or "").strip()
        base_cover_letter_path = str(form.get("base_cover_letter_path") or "").strip() or None
        jobs_file = str(form.get("jobs_file") or "").strip()
        top_n_raw = str(form.get("top_n") or "").strip()
        output_path = str(form.get("output_path") or "").strip()

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

        if not cv_path or not jobs_file or not output_path:
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
                        error="CV file, jobs file, rerank count, and output path are all required.",
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
        except ValueError as exc:
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

        if not job_id or not cv_path or not jobs_file or not output_path:
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
                        error="Selected job, CV file, jobs file, and output path are all required.",
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
        except (ValueError, ProfileValidationError) as exc:
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

        if not job_id or not cv_path or not jobs_file or not output_path:
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
                        error="Selected job, CV file, jobs file, and output path are all required.",
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
        except (ValueError, ProfileValidationError) as exc:
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

        if not job_id or not cv_path or not jobs_file or not output_path:
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
                        error="Selected job, CV file, jobs file, and output path are all required.",
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
        except (ValueError, ProfileValidationError, OllamaError) as exc:
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

        if not job_id or not cv_path or not jobs_file or not rule_based_output_path or not llm_output_path:
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
                        error="Selected job, CV file, jobs file, and both output paths are required.",
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
        except (ValueError, ProfileValidationError, OllamaError) as exc:
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
    parser.add_argument("--host", default="127.0.0.1", help="Bind host, default: 127.0.0.1")
    parser.add_argument("--port", type=int, default=8787, help="Bind port, default: 8787")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload for local development")
    args = parser.parse_args(argv)

    try:
        import uvicorn
    except ImportError as exc:
        raise SystemExit(
            "The local web workbench requires Uvicorn. Install it with `pip install -e .[web]`."
        ) from exc

    os.environ["OFFERQUEST_WORKSPACE_ROOT"] = str(args.root.resolve())
    if args.config:
        os.environ[_config.CONFIG_PATH_ENVVAR] = str(args.config.resolve())

    if args.reload:
        uvicorn.run(
            "offerquest.web.app:create_app",
            host=args.host,
            port=args.port,
            reload=True,
            factory=True,
        )
        return 0

    app = create_app(workspace_root=args.root, config_path=args.config)
    uvicorn.run(app, host=args.host, port=args.port, reload=False)
    return 0
