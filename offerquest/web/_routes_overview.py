from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class OverviewRouteDeps:
    build_artifact_preview: Any
    build_dashboard_view: Any
    build_run_detail_view: Any
    build_runs_view: Any


def register_overview_routes(
    *,
    app: Any,
    render: Any,
    project_state: Any,
    favicon_svg: bytes,
    HTMLResponse: Any,
    HTTPException: Any,
    Response: Any,
    get_deps: Any,
) -> None:
    @app.get("/", response_class=HTMLResponse)
    async def dashboard(request: Any) -> Any:
        deps = get_deps()
        return render(
            request,
            "dashboard.html",
            {
                "page_title": "Workbench",
                "view": deps.build_dashboard_view(project_state),
            },
        )

    @app.get("/favicon.ico", include_in_schema=False)
    async def favicon() -> Any:
        return Response(content=favicon_svg, media_type="image/svg+xml")

    @app.get("/runs", response_class=HTMLResponse)
    async def runs(request: Any) -> Any:
        deps = get_deps()
        return render(
            request,
            "runs.html",
            {
                "page_title": "Runs",
                "view": deps.build_runs_view(project_state),
            },
        )

    @app.get("/runs/{run_id}", response_class=HTMLResponse)
    async def run_detail(request: Any, run_id: str) -> Any:
        deps = get_deps()
        detail = deps.build_run_detail_view(project_state, run_id)
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
    async def artifact_preview(request: Any, run_id: str, artifact_index: int) -> Any:
        deps = get_deps()
        preview = deps.build_artifact_preview(project_state, run_id, artifact_index)
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
