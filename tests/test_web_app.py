import asyncio
import io
import sys
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch
from urllib.parse import urlencode

from offerquest.web.app import (
    AUTO_PORT,
    OllamaJobStore,
    build_job_source_field_errors,
    collect_required_field_errors,
    format_workbench_url,
    main,
    make_page_renderer,
    map_job_source_exception_to_field_errors,
    maybe_render_required_field_errors,
    normalize_progress,
    parse_optional_positive_int_or_render,
    parse_port_argument,
    resolve_port,
    summarize_field_errors,
)


@dataclass(frozen=True)
class _ASGIResponse:
    status_code: int
    headers: dict[str, str]
    body: bytes

    @property
    def text(self) -> str:
        return self.body.decode("utf-8", errors="replace")


async def _send_asgi_request(
    app: object,
    method: str,
    path: str,
    *,
    data: dict[str, str] | None = None,
) -> _ASGIResponse:
    body = urlencode(data).encode("utf-8") if data else b""
    raw_path, _, query = path.partition("?")
    messages: list[dict[str, object]] = []
    request_sent = False

    async def receive() -> dict[str, object]:
        nonlocal request_sent
        if not request_sent:
            request_sent = True
            return {
                "type": "http.request",
                "body": body,
                "more_body": False,
            }
        return {"type": "http.disconnect"}

    async def send(message: dict[str, object]) -> None:
        messages.append(message)

    headers = [(b"host", b"testserver")]
    if data is not None:
        headers.extend(
            [
                (b"content-type", b"application/x-www-form-urlencoded"),
                (b"content-length", str(len(body)).encode("ascii")),
            ]
        )

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method.upper(),
        "scheme": "http",
        "path": raw_path,
        "raw_path": raw_path.encode("utf-8"),
        "query_string": query.encode("utf-8"),
        "headers": headers,
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
        "root_path": "",
    }

    await app(scope, receive, send)  # type: ignore[misc]

    status_code = 500
    response_headers: dict[str, str] = {}
    response_body = bytearray()
    for message in messages:
        message_type = message.get("type")
        if message_type == "http.response.start":
            status_code = int(message.get("status", 500))
            response_headers = {
                key.decode("latin-1"): value.decode("latin-1")
                for key, value in message.get("headers", [])
            }
        if message_type == "http.response.body":
            response_body.extend(message.get("body", b""))

    return _ASGIResponse(
        status_code=status_code,
        headers=response_headers,
        body=bytes(response_body),
    )


class _TestClient:
    def __init__(self, app: object) -> None:
        self._app = app

    def get(self, path: str) -> _ASGIResponse:
        return asyncio.run(_send_asgi_request(self._app, "GET", path))

    def post(self, path: str, *, data: dict[str, str] | None = None) -> _ASGIResponse:
        return asyncio.run(_send_asgi_request(self._app, "POST", path, data=data))


testclient_module = ModuleType("fastapi.testclient")
testclient_module.TestClient = _TestClient
sys.modules["fastapi.testclient"] = testclient_module


class WebAppTests(unittest.TestCase):
    def test_make_page_renderer_merges_base_and_override_view_state(self) -> None:
        build_view = Mock(return_value={"view_key": "view-value"})
        render_page = Mock(return_value="rendered-response")

        render_view = make_page_renderer(
            "request-object",
            render_page,
            template_name="example.html",
            page_title="Example Page",
            build_view=build_view,
            cv_path="data/cv.txt",
            output_path=None,
        )

        response = render_view(output_path="outputs/profile.json", result={"status": "ok"})

        self.assertEqual(response, "rendered-response")
        self.assertEqual(
            build_view.call_args.kwargs,
            {
                "cv_path": "data/cv.txt",
                "output_path": "outputs/profile.json",
                "result": {"status": "ok"},
            },
        )
        self.assertEqual(
            render_page.call_args.args,
            (
                "request-object",
                "example.html",
                {
                    "page_title": "Example Page",
                    "view": {"view_key": "view-value"},
                },
            ),
        )

    def test_maybe_render_required_field_errors_uses_renderer_for_missing_fields(self) -> None:
        render_view = Mock(return_value="validation-response")

        response = maybe_render_required_field_errors(
            render_view,
            {
                "cv_path": "data/cv.txt",
                "jobs_file": "",
                "output_path": "",
            },
            required=[
                ("cv_path", "CV file"),
                ("jobs_file", "Jobs file"),
                ("output_path", "Output path"),
            ],
            fallback="Please complete the required fields.",
        )

        self.assertEqual(response, "validation-response")
        self.assertEqual(
            render_view.call_args.kwargs,
            {
                "error": "Please complete the required fields.",
                "field_errors": {
                    "jobs_file": "Jobs file is required.",
                    "output_path": "Output path is required.",
                },
            },
        )

    def test_parse_optional_positive_int_or_render_returns_value_or_rendered_error(self) -> None:
        render_view = Mock(return_value="numeric-error-response")

        value, response = parse_optional_positive_int_or_render(
            render_view,
            field_name="top_n",
            raw_value="10",
            invalid_message="Top count must be a whole number.",
            minimum_message="Top count must be at least 1.",
        )

        self.assertEqual((value, response), (10, None))
        self.assertFalse(render_view.called)

        value, response = parse_optional_positive_int_or_render(
            render_view,
            field_name="top_n",
            raw_value="0",
            invalid_message="Top count must be a whole number.",
            minimum_message="Top count must be at least 1.",
        )

        self.assertEqual((value, response), (None, "numeric-error-response"))
        self.assertEqual(
            render_view.call_args.kwargs,
            {
                "error": "Top count must be at least 1.",
                "field_errors": {"top_n": "Top count must be at least 1."},
            },
        )

    def test_parse_port_argument_accepts_auto(self) -> None:
        self.assertEqual(parse_port_argument("auto"), AUTO_PORT)

    def test_format_workbench_url_prefers_localhost_for_loopback(self) -> None:
        self.assertEqual(
            format_workbench_url("127.0.0.1", 8787),
            "http://localhost:8787",
        )

    def test_resolve_port_uses_auto_lookup(self) -> None:
        with patch("offerquest.web.app.find_available_port", return_value=54321) as lookup:
            port = resolve_port("127.0.0.1", AUTO_PORT)

        self.assertEqual(port, 54321)
        self.assertEqual(lookup.call_args.args, ("127.0.0.1",))

    def test_collect_required_field_errors_returns_field_mapping(self) -> None:
        field_errors = collect_required_field_errors(
            {
                "cv_path": "data/cv.txt",
                "jobs_file": "",
                "output_path": "",
            },
            required=[
                ("cv_path", "CV file"),
                ("jobs_file", "Jobs file"),
                ("output_path", "Output path"),
            ],
        )

        self.assertEqual(
            field_errors,
            {
                "jobs_file": "Jobs file is required.",
                "output_path": "Output path is required.",
            },
        )

    def test_summarize_field_errors_prefers_specific_message_for_single_error(self) -> None:
        self.assertEqual(
            summarize_field_errors({"top_n": "Top count must be at least 1."}),
            "Top count must be at least 1.",
        )
        self.assertEqual(
            summarize_field_errors(
                {
                    "cv_path": "CV file is required.",
                    "jobs_file": "Jobs file is required.",
                }
            ),
            "Please fix the highlighted fields and try again.",
        )

    def test_build_job_source_field_errors_matches_selected_source_type(self) -> None:
        field_errors = build_job_source_field_errors(
            {
                "name": "",
                "type": "adzuna",
                "what": "",
                "where": "",
                "pages": "0",
                "results_per_page": "abc",
            }
        )

        self.assertEqual(field_errors["source_name"], "Source name is required.")
        self.assertEqual(field_errors["adzuna_what"], "Enter search keywords or a location.")
        self.assertEqual(field_errors["adzuna_where"], "Enter search keywords or a location.")
        self.assertEqual(field_errors["adzuna_pages"], "Adzuna pages must be at least 1.")
        self.assertEqual(
            field_errors["adzuna_results_per_page"],
            "Adzuna results per page must be a whole number.",
        )

    def test_map_job_source_exception_to_field_errors_targets_matching_input(self) -> None:
        self.assertEqual(
            map_job_source_exception_to_field_errors("Output filenames must be unique."),
            {"source_output": "Output filenames must be unique."},
        )
        self.assertEqual(
            map_job_source_exception_to_field_errors("Greenhouse sources require a board token."),
            {"greenhouse_board_token": "Greenhouse sources require a board token."},
        )

    def test_normalize_progress_clamps_to_percentage_bounds(self) -> None:
        self.assertEqual(normalize_progress(-10), 0)
        self.assertEqual(normalize_progress(42.4), 42)
        self.assertEqual(normalize_progress(120), 100)

    def test_ollama_job_store_tracks_progress_updates(self) -> None:
        store = OllamaJobStore()
        job_id = store.create(
            intent="download_runtime",
            base_url="http://localhost:11434",
            custom_model=None,
        )

        store.update(job_id, status="running", progress=47, message="Downloading")
        job = store.get(job_id)

        self.assertIsNotNone(job)
        self.assertEqual(job["status"], "running")
        self.assertEqual(job["progress"], 47)
        self.assertEqual(job["message"], "Downloading")

    def test_main_uses_auto_port_and_prints_launch_url(self) -> None:
        output = io.StringIO()
        uvicorn_stub = SimpleNamespace(run=Mock())

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            with patch.dict(sys.modules, {"uvicorn": uvicorn_stub}):
                with patch("offerquest.web.app.create_app", return_value=object()):
                    with patch("offerquest.web.app.find_available_port", return_value=54321):
                        with patch("sys.stdout", output):
                            exit_code = main(["--root", str(root), "--port", "auto"])

        self.assertEqual(exit_code, 0)
        self.assertIn("http://localhost:54321", output.getvalue())
        self.assertEqual(uvicorn_stub.run.call_args.kwargs["port"], 54321)

    def test_dashboard_route_returns_html(self) -> None:
        try:
            from fastapi.testclient import TestClient
        except (ImportError, RuntimeError) as exc:
            self.skipTest(f"fastapi test client unavailable: {exc}")

        from offerquest.web.app import create_app

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            app = create_app(workspace_root=root)
            client = TestClient(app)

            with patch(
                "offerquest.workbench.runs.build_dashboard_view",
                return_value={
                    "stats": {"run_count": 0, "artifact_count": 0, "workflow_count": 0},
                    "workflow_counts": [],
                    "recent_runs": [],
                    "has_runs": False,
                    "show_onboarding": True,
                    "doctor": {"checks": [], "recommended_next_steps": []},
                },
            ):
                response = client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("OfferQuest Local Workbench", response.text)

    def test_favicon_route_serves_icon(self) -> None:
        try:
            from fastapi.testclient import TestClient
        except (ImportError, RuntimeError) as exc:
            self.skipTest(f"fastapi test client unavailable: {exc}")

        from offerquest.web.app import create_app

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            app = create_app(workspace_root=root)
            client = TestClient(app)

            response = client.get("/favicon.ico")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "image/svg+xml")
        self.assertIn("<svg", response.text)

    def test_ollama_setup_page_renders(self) -> None:
        try:
            from fastapi.testclient import TestClient
        except (ImportError, RuntimeError) as exc:
            self.skipTest(f"fastapi test client unavailable: {exc}")

        from offerquest.web.app import create_app

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            app = create_app(workspace_root=root)
            client = TestClient(app)

            with patch(
                "offerquest.workbench.ollama_setup.build_ollama_setup_view",
                return_value={
                    "selected_base_url": "http://localhost:11434",
                    "custom_model": "",
                    "ollama_status": {
                        "reachable": False,
                        "command_available": True,
                        "command_source": "repo_local_wrapper",
                    },
                    "installed_models": [],
                    "missing_recommended_models": ["qwen3:8b"],
                    "recommended_models": ["qwen3:8b"],
                    "stretch_models": ["mistral-small"],
                    "status_label": "Server Offline",
                    "status_css_class": "status-chip--muted",
                    "status_summary": "The Ollama CLI is available, but the server is not reachable yet.",
                    "can_pull_models": False,
                    "can_install_runtime": True,
                    "has_local_runtime": False,
                    "can_restart_server": True,
                    "managed_server": {"running": False, "pid": None, "log_path": "log", "pid_path": "pid"},
                    "managed_server_button_label": "Start Managed Server",
                    "hardware_status": {
                        "summary": "NVIDIA GPU detected.",
                        "detail": "Driver needs attention.",
                        "devices": [],
                    },
                    "error": None,
                    "result": None,
                    "action_result": None,
                    "serve_command": "offerquest ollama serve",
                    "pull_command": "offerquest ollama pull",
                    "models_command": "offerquest ollama models",
                },
            ):
                response = client.get("/ollama")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Ollama Setup", response.text)
        self.assertIn("offerquest ollama serve", response.text)
        self.assertIn("Download Local Ollama", response.text)
        self.assertIn("Start Managed Server", response.text)
        self.assertIn("Downloading local Ollama runtime", response.text)
        self.assertIn("id=\"ollama-progress\"", response.text)
        self.assertIn("role=\"progressbar\"", response.text)

    def test_ollama_setup_page_renders_with_legacy_view_payload(self) -> None:
        try:
            from fastapi.testclient import TestClient
        except (ImportError, RuntimeError) as exc:
            self.skipTest(f"fastapi test client unavailable: {exc}")

        from offerquest.web.app import create_app

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            app = create_app(workspace_root=root)
            client = TestClient(app)

            with patch(
                "offerquest.workbench.ollama_setup.build_ollama_setup_view",
                return_value={
                    "selected_base_url": "http://localhost:11434",
                    "custom_model": "",
                    "ollama_status": {
                        "reachable": False,
                        "command_available": True,
                        "command_source": "repo_local_wrapper",
                    },
                    "installed_models": [],
                    "missing_recommended_models": ["qwen3:8b"],
                    "recommended_models": ["qwen3:8b"],
                    "stretch_models": ["mistral-small"],
                    "status_label": "Server Offline",
                    "status_css_class": "status-chip--muted",
                    "status_summary": "The Ollama CLI is available, but the server is not reachable yet.",
                    "can_pull_models": False,
                    "error": None,
                    "result": None,
                    "serve_command": "offerquest ollama serve",
                    "pull_command": "offerquest ollama pull",
                    "models_command": "offerquest ollama models",
                },
            ):
                response = client.get("/ollama")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Managed server", response.text)
        self.assertIn("Hardware detection will appear after the workbench reloads.", response.text)
        self.assertIn("Buttons are waiting for a workbench restart.", response.text)

    def test_ollama_setup_submit_pulls_recommended_models(self) -> None:
        try:
            from fastapi.testclient import TestClient
        except (ImportError, RuntimeError) as exc:
            self.skipTest(f"fastapi test client unavailable: {exc}")

        from offerquest.web.app import create_app
        from offerquest.workbench import PullOllamaModelsResult

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            app = create_app(workspace_root=root)
            client = TestClient(app)

            pull_result = PullOllamaModelsResult(
                pulled_models=("qwen3:8b",),
                base_url="http://localhost:11434",
                ollama_status={
                    "reachable": True,
                    "command_available": True,
                    "models": [{"name": "qwen3:8b"}],
                    "has_models": True,
                    "missing_recommended_models": [],
                },
            )

            response_view = {
                "selected_base_url": "http://localhost:11434",
                "custom_model": "",
                "ollama_status": pull_result.ollama_status,
                "installed_models": ["qwen3:8b"],
                "missing_recommended_models": [],
                "recommended_models": ["qwen3:8b"],
                "stretch_models": ["mistral-small"],
                "status_label": "Ready",
                "status_css_class": "status-chip--live",
                "status_summary": "1 installed model(s) ready for use.",
                "can_pull_models": True,
                "can_install_runtime": True,
                "has_local_runtime": True,
                "can_restart_server": True,
                "managed_server": {"running": True, "pid": 1234, "log_path": "log", "pid_path": "pid"},
                "managed_server_button_label": "Restart Managed Server",
                "hardware_status": {
                    "summary": "NVIDIA GPU detected.",
                    "detail": "Ready",
                    "devices": [],
                },
                "error": None,
                "result": pull_result,
                "action_result": {
                    "title": "Models pulled",
                    "details": ["Pulled models: qwen3:8b"],
                },
                "serve_command": "offerquest ollama serve",
                "pull_command": "offerquest ollama pull",
                "models_command": "offerquest ollama models",
            }

            with patch(
                "offerquest.workbench.ollama_setup.run_ollama_models_pull",
                return_value=pull_result,
            ) as pull_mock:
                with patch(
                    "offerquest.workbench.ollama_setup.build_ollama_setup_view",
                    return_value=response_view,
                ):
                    response = client.post(
                        "/ollama",
                        data={
                            "intent": "pull_recommended",
                            "base_url": "http://localhost:11434",
                        },
                    )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(pull_mock.call_args.kwargs["models"], ["qwen3:8b", "gemma3:12b", "qwen3:14b"])
        self.assertIn("Models pulled", response.text)

    def test_ollama_setup_submit_downloads_local_runtime(self) -> None:
        try:
            from fastapi.testclient import TestClient
        except (ImportError, RuntimeError) as exc:
            self.skipTest(f"fastapi test client unavailable: {exc}")

        from offerquest.web.app import create_app

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            app = create_app(workspace_root=root)
            client = TestClient(app)

            response_view = {
                "selected_base_url": "http://localhost:11434",
                "custom_model": "",
                "ollama_status": {
                    "reachable": False,
                    "command_available": True,
                    "command_source": "repo_local_wrapper",
                },
                "installed_models": [],
                "missing_recommended_models": ["qwen3:8b"],
                "recommended_models": ["qwen3:8b"],
                "stretch_models": ["gpt-oss:20b", "mistral-small"],
                "status_label": "Server Offline",
                "status_css_class": "status-chip--muted",
                "status_summary": "The Ollama CLI is available, but the server is not reachable yet.",
                "can_pull_models": False,
                "can_install_runtime": True,
                "has_local_runtime": True,
                "can_restart_server": True,
                "managed_server": {"running": False, "pid": None, "log_path": "log", "pid_path": "pid"},
                "managed_server_button_label": "Start Managed Server",
                "hardware_status": {
                    "summary": "NVIDIA GPU detected.",
                    "detail": "Ready",
                    "devices": [],
                },
                "error": None,
                "result": None,
                "action_result": {
                    "title": "Local Ollama runtime downloaded",
                    "details": ["Runtime path: /tmp/ollama"],
                },
                "serve_command": "offerquest ollama serve",
                "pull_command": "offerquest ollama pull",
                "models_command": "offerquest ollama models",
            }

            with patch(
                "offerquest.workbench.ollama_setup.run_local_ollama_runtime_install",
                return_value={
                    "command_source": "repo_local_wrapper",
                    "local_runtime_path": "/tmp/ollama",
                },
            ) as install_mock:
                with patch(
                    "offerquest.workbench.ollama_setup.build_ollama_setup_view",
                    return_value=response_view,
                ):
                    response = client.post(
                        "/ollama",
                        data={
                            "intent": "download_runtime",
                            "base_url": "http://localhost:11434",
                        },
                    )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(install_mock.called)
        self.assertIn("Local Ollama runtime downloaded", response.text)

    def test_ollama_setup_submit_restarts_managed_server(self) -> None:
        try:
            from fastapi.testclient import TestClient
        except (ImportError, RuntimeError) as exc:
            self.skipTest(f"fastapi test client unavailable: {exc}")

        from offerquest.web.app import create_app

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            app = create_app(workspace_root=root)
            client = TestClient(app)

            response_view = {
                "selected_base_url": "http://localhost:11434",
                "custom_model": "",
                "ollama_status": {
                    "reachable": True,
                    "command_available": True,
                    "command_source": "repo_local_wrapper",
                },
                "installed_models": ["qwen3:8b"],
                "missing_recommended_models": [],
                "recommended_models": ["qwen3:8b"],
                "stretch_models": ["gpt-oss:20b", "mistral-small"],
                "status_label": "Ready",
                "status_css_class": "status-chip--live",
                "status_summary": "1 installed model(s) ready for use.",
                "can_pull_models": True,
                "can_install_runtime": True,
                "has_local_runtime": True,
                "can_restart_server": True,
                "managed_server": {"running": True, "pid": 4321, "log_path": "log", "pid_path": "pid"},
                "managed_server_button_label": "Restart Managed Server",
                "hardware_status": {
                    "summary": "NVIDIA GPU detected.",
                    "detail": "Ready",
                    "devices": [],
                },
                "error": None,
                "result": None,
                "action_result": {
                    "title": "Managed Ollama server restarted",
                    "details": ["Managed PID: 4321"],
                },
                "serve_command": "offerquest ollama serve",
                "pull_command": "offerquest ollama pull",
                "models_command": "offerquest ollama models",
            }

            with patch(
                "offerquest.workbench.ollama_setup.run_ollama_server_restart",
                return_value={
                    "base_url": "http://localhost:11434",
                    "pid": 4321,
                    "restarted_existing": True,
                },
            ) as restart_mock:
                with patch(
                    "offerquest.workbench.ollama_setup.build_ollama_setup_view",
                    return_value=response_view,
                ):
                    response = client.post(
                        "/ollama",
                        data={
                            "intent": "restart_server",
                            "base_url": "http://localhost:11434",
                        },
                    )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(restart_mock.call_args.kwargs["base_url"], "http://localhost:11434")
        self.assertIn("Managed Ollama server restarted", response.text)

    def test_dashboard_route_shows_start_here_checklist_for_empty_workspace(self) -> None:
        try:
            from fastapi.testclient import TestClient
        except (ImportError, RuntimeError) as exc:
            self.skipTest(f"fastapi test client unavailable: {exc}")

        from offerquest.web.app import create_app

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            app = create_app(workspace_root=root)
            client = TestClient(app)

            with patch(
                "offerquest.workbench.runs.build_dashboard_view",
                return_value={
                    "stats": {"run_count": 0, "artifact_count": 0, "workflow_count": 0},
                    "workflow_counts": [],
                    "recent_runs": [],
                    "has_runs": False,
                    "show_onboarding": True,
                    "doctor": {
                        "checks": [
                            {
                                "title": "Profile source documents",
                                "status_label": "WARN",
                                "status_css_class": "status-chip--warning",
                                "summary": "Missing CV and cover letter under `data/`.",
                                "detail": "No supported profile documents were found in `data/`.",
                                "next_step": "Add your own files under `data/`.",
                            }
                        ],
                        "recommended_next_steps": [
                            "Add your CV and base cover letter under `data/`.",
                            "Start the workbench with `offerquest-workbench --root .`.",
                        ],
                    },
                },
            ):
                response = client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Start Here", response.text)
        self.assertIn("Workspace Checks", response.text)
        self.assertIn("Add your CV and base cover letter under", response.text)

    def test_build_profile_page_renders(self) -> None:
        try:
            from fastapi.testclient import TestClient
        except (ImportError, RuntimeError) as exc:
            self.skipTest(f"fastapi test client unavailable: {exc}")

        from offerquest.web.app import create_app

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            data_dir = root / "data"
            data_dir.mkdir(parents=True, exist_ok=True)
            (data_dir / "CV_sample.txt").write_text("cv", encoding="utf-8")
            (data_dir / "CL_sample.txt").write_text("cl", encoding="utf-8")
            app = create_app(workspace_root=root)
            client = TestClient(app)

            response = client.get("/build-profile")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Build Candidate Profile", response.text)

    def test_resume_tailoring_page_renders(self) -> None:
        try:
            from fastapi.testclient import TestClient
        except (ImportError, RuntimeError) as exc:
            self.skipTest(f"fastapi test client unavailable: {exc}")

        from offerquest.web.app import create_app

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            data_dir = root / "data"
            outputs_dir = root / "outputs"
            jobs_dir = outputs_dir / "jobs"
            data_dir.mkdir(parents=True, exist_ok=True)
            jobs_dir.mkdir(parents=True, exist_ok=True)
            (data_dir / "CV_sample.txt").write_text("cv", encoding="utf-8")
            (data_dir / "CL_sample.txt").write_text("cl", encoding="utf-8")
            (jobs_dir / "all.jsonl").write_text(
                '{"id": "job-1", "title": "Senior Data Analyst", "company": "Example Org", "location": "Sydney", "description_text": "SQL reporting role"}\n',
                encoding="utf-8",
            )
            (outputs_dir / "job-ranking.json").write_text(
                '{"job_count": 1, "rankings": [{"job_id": "job-1", "job_title": "Senior Data Analyst", "company": "Example Org", "location": "Sydney", "score": 95}]}',
                encoding="utf-8",
            )
            app = create_app(workspace_root=root)
            client = TestClient(app)

            response = client.get("/cv-tailoring/new?job_id=job-1")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Build CV Tailoring Plan", response.text)

    def test_resume_tailored_draft_page_renders(self) -> None:
        try:
            from fastapi.testclient import TestClient
        except (ImportError, RuntimeError) as exc:
            self.skipTest(f"fastapi test client unavailable: {exc}")

        from offerquest.web.app import create_app

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            data_dir = root / "data"
            outputs_dir = root / "outputs"
            jobs_dir = outputs_dir / "jobs"
            data_dir.mkdir(parents=True, exist_ok=True)
            jobs_dir.mkdir(parents=True, exist_ok=True)
            (data_dir / "CV_sample.txt").write_text("cv", encoding="utf-8")
            (data_dir / "CL_sample.txt").write_text("cl", encoding="utf-8")
            (jobs_dir / "all.jsonl").write_text(
                '{"id": "job-1", "title": "Senior Data Analyst", "company": "Example Org", "location": "Sydney", "description_text": "SQL reporting role"}\n',
                encoding="utf-8",
            )
            (outputs_dir / "job-ranking.json").write_text(
                '{"job_count": 1, "rankings": [{"job_id": "job-1", "job_title": "Senior Data Analyst", "company": "Example Org", "location": "Sydney", "score": 95}]}',
                encoding="utf-8",
            )
            app = create_app(workspace_root=root)
            client = TestClient(app)

            response = client.get("/cv-tailoring/draft/new?job_id=job-1")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Build Tailored CV Draft", response.text)
        self.assertIn("Also export ATS-safe DOCX", response.text)

    def test_rankings_page_renders(self) -> None:
        try:
            from fastapi.testclient import TestClient
        except (ImportError, RuntimeError) as exc:
            self.skipTest(f"fastapi test client unavailable: {exc}")

        from offerquest.web.app import create_app

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            outputs_dir = root / "outputs"
            outputs_dir.mkdir(parents=True, exist_ok=True)
            (outputs_dir / "job-ranking.json").write_text(
                '{"job_count": 1, "rankings": [{"job_title": "Senior Data Analyst", "company": "Example Org", "location": "Sydney", "score": 95}]}',
                encoding="utf-8",
            )
            app = create_app(workspace_root=root)
            client = TestClient(app)

            response = client.get("/rankings")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Latest Ranking Output", response.text)
        self.assertIn("Rerank Top Jobs", response.text)

    def test_job_sources_page_renders(self) -> None:
        try:
            from fastapi.testclient import TestClient
        except (ImportError, RuntimeError) as exc:
            self.skipTest(f"fastapi test client unavailable: {exc}")

        from offerquest.web.app import create_app

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            jobs_dir = root / "jobs"
            jobs_dir.mkdir(parents=True, exist_ok=True)
            (jobs_dir / "sources.json").write_text(
                '{"sources": [{"name": "adzuna-reporting", "type": "adzuna", "what": "reporting analyst", "where": "Sydney", "output": "adzuna-reporting.jsonl"}]}',
                encoding="utf-8",
            )
            app = create_app(workspace_root=root)
            client = TestClient(app)

            response = client.get("/job-sources")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Credentials and Provider Guide", response.text)
        self.assertIn("Configured Job Streams", response.text)
        self.assertIn("Board token, not a private API key", response.text)

    def test_job_sources_submit_saves_credentials_file(self) -> None:
        try:
            from fastapi.testclient import TestClient
        except (ImportError, RuntimeError) as exc:
            self.skipTest(f"fastapi test client unavailable: {exc}")

        from offerquest.web.app import create_app

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            env_path = Path(tmpdir) / "adzuna.env"
            app = create_app(workspace_root=root)
            client = TestClient(app)

            with patch.dict(
                "os.environ",
                {"OFFERQUEST_ADZUNA_ENV_FILE": str(env_path)},
                clear=False,
            ):
                response = client.post(
                    "/job-sources",
                    data={
                        "app_id": "saved-app-id",
                        "app_key": "saved-app-key",
                    },
                )

            saved_text = env_path.read_text(encoding="utf-8")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Saved credentials file", response.text)
        self.assertIn("saved-app-id", saved_text)
        self.assertIn("saved-app-key", saved_text)

    def test_job_sources_submit_refreshes_jobs(self) -> None:
        try:
            from fastapi.testclient import TestClient
        except (ImportError, RuntimeError) as exc:
            self.skipTest(f"fastapi test client unavailable: {exc}")

        from offerquest.web.app import create_app
        from offerquest.workbench import BuildRefreshJobsResult

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            jobs_dir = root / "jobs"
            jobs_dir.mkdir(parents=True, exist_ok=True)
            (jobs_dir / "sources.json").write_text(
                '{"sources": [{"name": "adzuna-reporting", "type": "adzuna", "what": "reporting analyst", "where": "Sydney", "output": "adzuna-reporting.jsonl"}]}',
                encoding="utf-8",
            )
            app = create_app(workspace_root=root)
            client = TestClient(app)

            refresh_result = BuildRefreshJobsResult(
                summary={
                    "source_count": 1,
                    "merged_job_count": 12,
                    "sources": [
                        {
                            "name": "adzuna-reporting",
                            "job_count": 12,
                            "output": "outputs/jobs/adzuna-reporting.jsonl",
                        }
                    ],
                },
                summary_path=root / "outputs" / "jobs" / "refresh-summary.json",
                summary_path_relative="outputs/jobs/refresh-summary.json",
                merged_output_path=root / "outputs" / "jobs" / "all.jsonl",
                merged_output_path_relative="outputs/jobs/all.jsonl",
                run_manifest={"id": "refresh-run-1"},
            )

            with patch(
                "offerquest.workbench.job_sources.run_refresh_jobs_build",
                return_value=refresh_result,
            ) as refresh_mock:
                response = client.post(
                    "/job-sources",
                    data={
                        "intent": "refresh_jobs",
                        "config_path": "jobs/sources.json",
                        "output_dir": "outputs/jobs",
                    },
                )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(refresh_mock.call_count, 1)
        self.assertIn("Refresh complete", response.text)
        self.assertIn("Open recorded refresh run", response.text)

    def test_job_sources_submit_saves_source_config(self) -> None:
        try:
            from fastapi.testclient import TestClient
        except (ImportError, RuntimeError) as exc:
            self.skipTest(f"fastapi test client unavailable: {exc}")

        from offerquest.web.app import create_app
        from offerquest.workbench import SaveJobSourceConfigResult

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            app = create_app(workspace_root=root)
            client = TestClient(app)

            save_result = SaveJobSourceConfigResult(
                config_path=root / "jobs" / "sources.json",
                config_path_relative="jobs/sources.json",
                action="created",
                source_name="manual",
                source_count=1,
            )

            with patch(
                "offerquest.workbench.job_sources.run_job_source_save",
                return_value=save_result,
            ) as save_mock:
                response = client.post(
                    "/job-sources",
                    data={
                        "intent": "save_source",
                        "source_name": "manual",
                        "source_type": "manual",
                        "source_enabled": "true",
                        "source_output": "manual.jsonl",
                        "manual_input_path": "jobs",
                    },
                )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(save_mock.call_count, 1)
        self.assertIn("Created", response.text)
        self.assertIn("manual", response.text)

    def test_rerank_jobs_page_renders(self) -> None:
        try:
            from fastapi.testclient import TestClient
        except (ImportError, RuntimeError) as exc:
            self.skipTest(f"fastapi test client unavailable: {exc}")

        from offerquest.web.app import create_app

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            data_dir = root / "data"
            outputs_dir = root / "outputs"
            jobs_dir = outputs_dir / "jobs"
            data_dir.mkdir(parents=True, exist_ok=True)
            jobs_dir.mkdir(parents=True, exist_ok=True)
            (data_dir / "CV_sample.txt").write_text("cv", encoding="utf-8")
            (data_dir / "CL_sample.txt").write_text("cl", encoding="utf-8")
            (jobs_dir / "all.jsonl").write_text(
                '{"id": "job-1", "title": "Senior Data Analyst", "company": "Example Org", "location": "Sydney", "description_text": "SQL reporting role"}\n',
                encoding="utf-8",
            )
            (outputs_dir / "job-ranking.json").write_text(
                '{"job_count": 1, "rankings": [{"job_id": "job-1", "job_title": "Senior Data Analyst", "company": "Example Org", "location": "Sydney", "score": 95}]}',
                encoding="utf-8",
            )
            app = create_app(workspace_root=root)
            client = TestClient(app)

            response = client.get("/rerank-jobs/new?ranking_file=outputs/job-ranking.json")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Rerank Top Jobs", response.text)
        self.assertIn("job-ranking.json", response.text)

    def test_cover_letter_page_renders(self) -> None:
        try:
            from fastapi.testclient import TestClient
        except (ImportError, RuntimeError) as exc:
            self.skipTest(f"fastapi test client unavailable: {exc}")

        from offerquest.web.app import create_app

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            data_dir = root / "data"
            outputs_dir = root / "outputs"
            jobs_dir = outputs_dir / "jobs"
            data_dir.mkdir(parents=True, exist_ok=True)
            jobs_dir.mkdir(parents=True, exist_ok=True)
            (data_dir / "CV_sample.txt").write_text("cv", encoding="utf-8")
            (data_dir / "CL_sample.txt").write_text("cl", encoding="utf-8")
            (jobs_dir / "all.jsonl").write_text(
                '{"id": "job-1", "title": "Senior Data Analyst", "company": "Example Org", "location": "Sydney", "description_text": "SQL reporting role"}\n',
                encoding="utf-8",
            )
            (outputs_dir / "job-ranking.json").write_text(
                '{"job_count": 1, "rankings": [{"job_id": "job-1", "job_title": "Senior Data Analyst", "company": "Example Org", "location": "Sydney", "score": 95}]}',
                encoding="utf-8",
            )
            app = create_app(workspace_root=root)
            client = TestClient(app)

            with patch(
                "offerquest.workbench.documents.get_ollama_status",
                return_value={
                    "reachable": False,
                    "command_available": True,
                    "models": [],
                    "missing_recommended_models": ["qwen3:8b"],
                },
            ):
                response = client.get("/cover-letters/new?job_id=job-1")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Generate Cover Letter", response.text)
        self.assertIn("Open Ollama Setup", response.text)
        self.assertIn("/ollama?base_url=http://localhost:11434", response.text)

    def test_cover_letter_page_renders_llm_mode(self) -> None:
        try:
            from fastapi.testclient import TestClient
        except (ImportError, RuntimeError) as exc:
            self.skipTest(f"fastapi test client unavailable: {exc}")

        from offerquest.web.app import create_app

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            data_dir = root / "data"
            outputs_dir = root / "outputs"
            jobs_dir = outputs_dir / "jobs"
            data_dir.mkdir(parents=True, exist_ok=True)
            jobs_dir.mkdir(parents=True, exist_ok=True)
            (data_dir / "CV_sample.txt").write_text("cv", encoding="utf-8")
            (data_dir / "CL_sample.txt").write_text("cl", encoding="utf-8")
            (jobs_dir / "all.jsonl").write_text(
                '{"id": "job-1", "title": "Senior Data Analyst", "company": "Example Org", "location": "Sydney", "description_text": "SQL reporting role"}\n',
                encoding="utf-8",
            )
            (outputs_dir / "job-ranking.json").write_text(
                '{"job_count": 1, "rankings": [{"job_id": "job-1", "job_title": "Senior Data Analyst", "company": "Example Org", "location": "Sydney", "score": 95}]}',
                encoding="utf-8",
            )
            app = create_app(workspace_root=root)
            client = TestClient(app)

            with patch(
                "offerquest.workbench.documents.get_ollama_status",
                return_value={
                    "reachable": True,
                    "command_available": True,
                    "models": [{"name": "qwen3:8b"}],
                    "missing_recommended_models": [],
                },
            ):
                response = client.get("/cover-letters/new?job_id=job-1&mode=llm")

        self.assertEqual(response.status_code, 200)
        self.assertIn("LLM draft (Ollama)", response.text)
        self.assertIn("qwen3:8b", response.text)

    def test_compare_cover_letters_page_renders(self) -> None:
        try:
            from fastapi.testclient import TestClient
        except (ImportError, RuntimeError) as exc:
            self.skipTest(f"fastapi test client unavailable: {exc}")

        from offerquest.web.app import create_app

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            data_dir = root / "data"
            outputs_dir = root / "outputs"
            jobs_dir = outputs_dir / "jobs"
            data_dir.mkdir(parents=True, exist_ok=True)
            jobs_dir.mkdir(parents=True, exist_ok=True)
            (data_dir / "CV_sample.txt").write_text("cv", encoding="utf-8")
            (data_dir / "CL_sample.txt").write_text("cl", encoding="utf-8")
            (jobs_dir / "all.jsonl").write_text(
                '{"id": "job-1", "title": "Senior Data Analyst", "company": "Example Org", "location": "Sydney", "description_text": "SQL reporting role"}\n',
                encoding="utf-8",
            )
            (outputs_dir / "job-ranking.json").write_text(
                '{"job_count": 1, "rankings": [{"job_id": "job-1", "job_title": "Senior Data Analyst", "company": "Example Org", "location": "Sydney", "score": 95}]}',
                encoding="utf-8",
            )
            app = create_app(workspace_root=root)
            client = TestClient(app)

            with patch(
                "offerquest.workbench.documents.get_ollama_status",
                return_value={
                    "reachable": False,
                    "command_available": True,
                    "models": [],
                    "missing_recommended_models": ["qwen3:8b"],
                },
            ):
                response = client.get("/cover-letters/compare?job_id=job-1")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Compare Draft Styles", response.text)
        self.assertIn("Go to Ollama Setup", response.text)


if __name__ == "__main__":
    unittest.main()
