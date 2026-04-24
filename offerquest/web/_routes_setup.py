import logging
import threading
from dataclasses import replace
from functools import partial
from typing import Any

from .. import ollama as ollama_core
from ..errors import OfferQuestError
from ..workbench import job_sources as job_sources_workbench
from ..workbench import ollama_setup as ollama_setup_workbench
from ..workbench import profile as profile_workbench
from ._support import (
    FieldErrors,
    build_job_source_field_errors,
    collect_required_field_errors,
    make_page_renderer,
    map_common_form_error,
    map_job_source_exception_to_field_errors,
    maybe_render_required_field_errors,
    summarize_field_errors,
)

logger = logging.getLogger(__name__)


def register_setup_routes(
    *,
    app: Any,
    render: Any,
    project_state: Any,
    HTMLResponse: Any,
    JSONResponse: Any,
) -> None:
    from fastapi import Request

    def resolve_ollama_action_models(
        *,
        intent: str,
        base_url: str | None,
        custom_model: str | None,
    ) -> list[str]:
        if intent == "pull_recommended":
            return list(ollama_core.RECOMMENDED_OLLAMA_MODELS)
        if intent == "pull_missing_recommended":
            current_view = ollama_setup_workbench.build_ollama_setup_view(
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
                result = ollama_setup_workbench.run_ollama_models_pull(
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
                install_result = ollama_setup_workbench.run_local_ollama_runtime_install(
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
                restart_result = ollama_setup_workbench.run_ollama_server_restart(base_url=base_url)
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

    @app.get("/job-sources", response_class=HTMLResponse)
    async def job_sources(
        request: Request,
        edit_source: int | None = None,
        duplicate_source: int | None = None,
    ) -> Any:
        return render(
            request,
            "job_sources.html",
            {
                "page_title": "Job Sources",
                "view": job_sources_workbench.build_job_sources_view(
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
    ) -> Any:
        return render(
            request,
            "ollama_setup.html",
            {
                "page_title": "Ollama Setup",
                "view": ollama_setup_workbench.build_ollama_setup_view(
                    project_state,
                    base_url=base_url,
                ),
            },
        )

    @app.post("/ollama/jobs")
    async def ollama_setup_job_submit(request: Request) -> Any:
        form = await request.form()
        intent = str(form.get("intent") or "refresh_status").strip()
        base_url = str(form.get("base_url") or "").strip()
        custom_model = str(form.get("custom_model") or "").strip() or None
        normalized_base_url = base_url or ollama_core.DEFAULT_OLLAMA_BASE_URL

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
            base_url=normalized_base_url,
            custom_model=custom_model,
        )
        thread = threading.Thread(
            target=run_ollama_setup_progress_job,
            kwargs={
                "job_id": job_id,
                "intent": intent,
                "base_url": normalized_base_url,
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
    async def ollama_setup_job_status(job_id: str) -> Any:
        job = app.state.ollama_jobs.get(job_id)
        if job is None:
            return JSONResponse({"error": "Ollama setup job was not found."}, status_code=404)
        return JSONResponse(job)

    @app.get("/build-profile", response_class=HTMLResponse)
    async def build_profile_page(request: Request) -> Any:
        return render(
            request,
            "build_profile.html",
            {
                "page_title": "Build Profile",
                "view": profile_workbench.build_profile_form_view(project_state),
            },
        )

    @app.post("/build-profile", response_class=HTMLResponse)
    async def build_profile_submit(request: Request) -> Any:
        form = await request.form()
        cv_path = str(form.get("cv_path") or "").strip()
        cover_letter_path = str(form.get("cover_letter_path") or "").strip()
        output_path = str(form.get("output_path") or "").strip()

        render_view = make_page_renderer(
            request,
            render,
            template_name="build_profile.html",
            page_title="Build Profile",
            build_view=partial(profile_workbench.build_profile_form_view, project_state),
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
            result = profile_workbench.run_profile_build(
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
    async def job_sources_submit(request: Request) -> Any:
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

        def render_view(
            *,
            app_id_value: str | None = app_id or None,
            config_path_value: str | None = config_path or None,
            output_dir_value: str | None = output_dir or None,
            **view_kwargs: Any,
        ) -> Any:
            return render(
                request,
                "job_sources.html",
                {
                    "page_title": "Job Sources",
                    "view": job_sources_workbench.build_job_sources_view(
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
                source_result = job_sources_workbench.run_job_source_save(
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
                    job_sources_workbench.run_job_source_delete(project_state, source_index=source_index)
                    if intent == "delete_source"
                    else job_sources_workbench.run_job_source_toggle(project_state, source_index=source_index)
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
                refresh_result = job_sources_workbench.run_refresh_jobs_build(
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
            credentials_result = job_sources_workbench.run_adzuna_credentials_save(
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
    async def ollama_setup_submit(request: Request) -> Any:
        form = await request.form()
        intent = str(form.get("intent") or "refresh_status").strip()
        base_url = str(form.get("base_url") or "").strip() or None
        custom_model = str(form.get("custom_model") or "").strip() or None

        render_view = make_page_renderer(
            request,
            render,
            template_name="ollama_setup.html",
            page_title="Ollama Setup",
            build_view=partial(ollama_setup_workbench.build_ollama_setup_view, project_state),
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
                result = ollama_setup_workbench.run_ollama_models_pull(
                    base_url=base_url or ollama_core.DEFAULT_OLLAMA_BASE_URL,
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
                result = ollama_setup_workbench.run_ollama_models_pull(
                    base_url=base_url or ollama_core.DEFAULT_OLLAMA_BASE_URL,
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
                result = ollama_setup_workbench.run_ollama_models_pull(
                    base_url=base_url or ollama_core.DEFAULT_OLLAMA_BASE_URL,
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
                install_result = ollama_setup_workbench.run_local_ollama_runtime_install()
                action_result = {
                    "title": "Local Ollama runtime downloaded",
                    "details": [
                        f"Command source: {install_result.get('command_source') or 'unknown'}",
                        f"Runtime path: {install_result.get('local_runtime_path') or 'not detected'}",
                    ],
                }
            elif intent == "restart_server":
                restart_result = ollama_setup_workbench.run_ollama_server_restart(
                    base_url=base_url or ollama_core.DEFAULT_OLLAMA_BASE_URL,
                )
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
