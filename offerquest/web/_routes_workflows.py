from dataclasses import dataclass
from functools import partial
from typing import Any

from ..errors import OfferQuestError
from ._support import (
    make_page_renderer,
    map_common_form_error,
    maybe_render_required_field_errors,
    parse_optional_positive_int_or_render,
)


@dataclass(frozen=True)
class WorkflowRouteDeps:
    build_cover_letter_compare_view: Any
    build_cover_letter_form_view: Any
    build_latest_rankings_view: Any
    build_rerank_jobs_form_view: Any
    build_resume_tailored_draft_form_view: Any
    build_resume_tailoring_form_view: Any
    run_cover_letter_build: Any
    run_cover_letter_compare: Any
    run_rerank_jobs_build: Any
    run_resume_tailored_draft_build: Any
    run_resume_tailoring_plan_build: Any


def register_workflow_routes(
    *,
    app: Any,
    render: Any,
    project_state: Any,
    HTMLResponse: Any,
    get_deps: Any,
) -> None:
    from fastapi import Request

    @app.get("/rankings", response_class=HTMLResponse)
    async def rankings(request: Request) -> Any:
        deps = get_deps()
        return render(
            request,
            "rankings.html",
            {
                "page_title": "Latest Rankings",
                "view": deps.build_latest_rankings_view(project_state),
            },
        )

    @app.get("/rerank-jobs/new", response_class=HTMLResponse)
    async def build_rerank_jobs_page(
        request: Request,
        ranking_file: str | None = None,
    ) -> Any:
        deps = get_deps()
        return render(
            request,
            "rerank_jobs.html",
            {
                "page_title": "Rerank Jobs",
                "view": deps.build_rerank_jobs_form_view(
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
    ) -> Any:
        deps = get_deps()
        return render(
            request,
            "tailor_cv.html",
            {
                "page_title": "Tailor CV",
                "view": deps.build_resume_tailoring_form_view(
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
    ) -> Any:
        deps = get_deps()
        return render(
            request,
            "tailor_cv_draft.html",
            {
                "page_title": "Tailored CV Draft",
                "view": deps.build_resume_tailored_draft_form_view(
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
    ) -> Any:
        deps = get_deps()
        return render(
            request,
            "build_cover_letter.html",
            {
                "page_title": "Generate Cover Letter",
                "view": deps.build_cover_letter_form_view(
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
    ) -> Any:
        deps = get_deps()
        return render(
            request,
            "compare_cover_letters.html",
            {
                "page_title": "Compare Drafts",
                "view": deps.build_cover_letter_compare_view(
                    project_state,
                    ranking_file=ranking_file,
                    job_id=job_id,
                ),
            },
        )

    @app.post("/rerank-jobs/new", response_class=HTMLResponse)
    async def build_rerank_jobs_submit(request: Request) -> Any:
        form = await request.form()
        ranking_file = str(form.get("ranking_file") or "").strip() or None
        cv_path = str(form.get("cv_path") or "").strip()
        base_cover_letter_path = str(form.get("base_cover_letter_path") or "").strip() or None
        jobs_file = str(form.get("jobs_file") or "").strip()
        top_n_raw = str(form.get("top_n") or "").strip()
        output_path = str(form.get("output_path") or "").strip()
        deps = get_deps()

        render_view = make_page_renderer(
            request,
            render,
            template_name="rerank_jobs.html",
            page_title="Rerank Jobs",
            build_view=partial(deps.build_rerank_jobs_form_view, project_state),
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
            result = deps.run_rerank_jobs_build(
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
    async def build_resume_tailoring_submit(request: Request) -> Any:
        form = await request.form()
        ranking_file = str(form.get("ranking_file") or "").strip() or None
        job_id = str(form.get("job_id") or "").strip() or None
        cv_path = str(form.get("cv_path") or "").strip()
        base_cover_letter_path = str(form.get("base_cover_letter_path") or "").strip() or None
        jobs_file = str(form.get("jobs_file") or "").strip()
        output_path = str(form.get("output_path") or "").strip()
        deps = get_deps()

        render_view = make_page_renderer(
            request,
            render,
            template_name="tailor_cv.html",
            page_title="Tailor CV",
            build_view=partial(deps.build_resume_tailoring_form_view, project_state),
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
            result = deps.run_resume_tailoring_plan_build(
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
    async def build_resume_tailored_draft_submit(request: Request) -> Any:
        form = await request.form()
        ranking_file = str(form.get("ranking_file") or "").strip() or None
        job_id = str(form.get("job_id") or "").strip() or None
        cv_path = str(form.get("cv_path") or "").strip()
        base_cover_letter_path = str(form.get("base_cover_letter_path") or "").strip() or None
        jobs_file = str(form.get("jobs_file") or "").strip()
        output_path = str(form.get("output_path") or "").strip()
        export_docx = bool(form.get("export_docx"))
        docx_output_path = str(form.get("docx_output_path") or "").strip() or None
        deps = get_deps()

        render_view = make_page_renderer(
            request,
            render,
            template_name="tailor_cv_draft.html",
            page_title="Tailored CV Draft",
            build_view=partial(deps.build_resume_tailored_draft_form_view, project_state),
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
            result = deps.run_resume_tailored_draft_build(
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
    async def build_cover_letter_submit(request: Request) -> Any:
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
        deps = get_deps()

        render_view = make_page_renderer(
            request,
            render,
            template_name="build_cover_letter.html",
            page_title="Generate Cover Letter",
            build_view=partial(deps.build_cover_letter_form_view, project_state),
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
            result = deps.run_cover_letter_build(
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
    async def compare_cover_letters_submit(request: Request) -> Any:
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
        deps = get_deps()

        render_view = make_page_renderer(
            request,
            render,
            template_name="compare_cover_letters.html",
            page_title="Compare Drafts",
            build_view=partial(deps.build_cover_letter_compare_view, project_state),
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
            result = deps.run_cover_letter_compare(
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
