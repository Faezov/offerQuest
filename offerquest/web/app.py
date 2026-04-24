from __future__ import annotations

import argparse
import logging
import os
import socket
from pathlib import Path
from typing import Any

from .. import config as _config
from ..errors import OfferQuestError
from ..workspace import ProjectState
from ._routes_overview import register_overview_routes
from ._routes_setup import register_setup_routes
from ._routes_workflows import register_workflow_routes
from ._support import (
    FieldErrors,
    OllamaJobStore,
    build_job_source_field_errors,
    build_page_chrome,
    collect_required_field_errors,
    make_page_renderer,
    map_common_form_error,
    map_job_source_exception_to_field_errors,
    maybe_render_required_field_errors,
    normalize_progress,
    parse_optional_positive_int_or_render,
    safe_request_url_for,
    summarize_field_errors,
)

LOG_LEVEL_NAMES = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
logger = logging.getLogger(__name__)
AUTO_PORT = "auto"


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

    register_overview_routes(
        app=app,
        render=render,
        project_state=project_state,
        favicon_svg=favicon_svg,
        HTMLResponse=HTMLResponse,
        HTTPException=HTTPException,
        Response=Response,
    )
    register_setup_routes(
        app=app,
        render=render,
        project_state=project_state,
        HTMLResponse=HTMLResponse,
        JSONResponse=JSONResponse,
    )
    register_workflow_routes(
        app=app,
        render=render,
        project_state=project_state,
        HTMLResponse=HTMLResponse,
    )
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


__all__ = [
    "AUTO_PORT",
    "FieldErrors",
    "OllamaJobStore",
    "build_job_source_field_errors",
    "collect_required_field_errors",
    "create_app",
    "find_available_port",
    "format_workbench_url",
    "main",
    "make_page_renderer",
    "map_common_form_error",
    "map_job_source_exception_to_field_errors",
    "maybe_render_required_field_errors",
    "normalize_progress",
    "parse_optional_positive_int_or_render",
    "parse_port_argument",
    "resolve_port",
    "summarize_field_errors",
]
