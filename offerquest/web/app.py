import argparse
import os
from pathlib import Path
from typing import Any

from ..workspace import ProjectState
from ..workbench import (
    build_artifact_preview,
    build_dashboard_view,
    build_profile_form_view,
    build_run_detail_view,
    build_runs_view,
    run_profile_build,
)


def create_app(*, workspace_root: str | Path | None = None) -> Any:
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

    if args.reload:
        uvicorn.run(
            "offerquest.web.app:create_app",
            host=args.host,
            port=args.port,
            reload=True,
            factory=True,
        )
        return 0

    app = create_app(workspace_root=args.root)
    uvicorn.run(app, host=args.host, port=args.port, reload=False)
    return 0
