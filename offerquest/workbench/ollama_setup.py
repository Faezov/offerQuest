from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ..ollama import (
    DEFAULT_OLLAMA_BASE_URL,
    LIGHTWEIGHT_OLLAMA_MODELS,
    RECOMMENDED_OLLAMA_MODELS,
    STRETCH_OLLAMA_MODELS,
    build_ollama_model_cards,
    detect_gpu_environment,
    get_managed_ollama_server_state,
    get_ollama_status,
    has_local_ollama_installer,
    has_local_ollama_runtime,
    install_local_ollama_runtime as run_local_ollama_runtime_install,
    pull_ollama_model,
    restart_managed_ollama_server as run_ollama_server_restart,
)
from ..workspace import ProjectState


@dataclass(frozen=True)
class PullOllamaModelsResult:
    pulled_models: tuple[str, ...]
    base_url: str
    ollama_status: dict[str, Any]


def summarize_ollama_status(status: dict[str, Any]) -> tuple[str, str, str]:
    if not status.get("command_available") and not status.get("reachable"):
        return (
            "CLI Missing",
            "status-chip--muted",
            "Install Ollama first to enable local LLM workflows.",
        )
    if not status.get("reachable"):
        return (
            "Server Offline",
            "status-chip--muted",
            "The Ollama CLI is available, but the server is not reachable yet.",
        )
    if not status.get("has_models"):
        return (
            "Ready for First Pull",
            "status-chip--warning",
            "The server is reachable, but no models are installed yet.",
        )
    return (
        "Ready",
        "status-chip--live",
        f"{len(status.get('models', []))} installed model(s) ready for use.",
    )


def build_ollama_setup_view(
    project_state: ProjectState,
    *,
    base_url: str | None = None,
    custom_model: str | None = None,
    error: str | None = None,
    result: PullOllamaModelsResult | None = None,
    action_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    del project_state
    selected_base_url = base_url or DEFAULT_OLLAMA_BASE_URL
    ollama_status = get_ollama_status(selected_base_url, timeout_seconds=2)
    hardware_status = detect_gpu_environment()
    managed_server = get_managed_ollama_server_state()
    installed_models = [
        str(model.get("name"))
        for model in ollama_status.get("models", [])
        if model.get("name")
    ]
    missing_recommended_models = list(
        ollama_status.get("missing_recommended_models", list(RECOMMENDED_OLLAMA_MODELS))
    )
    status_label, status_css_class, status_summary = summarize_ollama_status(ollama_status)

    return {
        "selected_base_url": selected_base_url,
        "custom_model": custom_model or "",
        "ollama_status": ollama_status,
        "installed_models": installed_models,
        "missing_recommended_models": missing_recommended_models,
        "recommended_models": list(RECOMMENDED_OLLAMA_MODELS),
        "stretch_models": list(STRETCH_OLLAMA_MODELS),
        "lightweight_models": list(LIGHTWEIGHT_OLLAMA_MODELS),
        "recommended_model_cards": build_ollama_model_cards(RECOMMENDED_OLLAMA_MODELS),
        "stretch_model_cards": build_ollama_model_cards(STRETCH_OLLAMA_MODELS),
        "lightweight_model_cards": build_ollama_model_cards(LIGHTWEIGHT_OLLAMA_MODELS),
        "status_label": status_label,
        "status_css_class": status_css_class,
        "status_summary": status_summary,
        "can_pull_models": bool(ollama_status.get("reachable")),
        "can_install_runtime": has_local_ollama_installer(),
        "has_local_runtime": has_local_ollama_runtime(),
        "can_restart_server": bool(ollama_status.get("command_available")),
        "managed_server": managed_server,
        "managed_server_button_label": (
            "Restart Managed Server" if managed_server.get("running") else "Start Managed Server"
        ),
        "hardware_status": hardware_status,
        "error": error,
        "result": result,
        "action_result": action_result,
        "serve_command": "offerquest ollama serve",
        "pull_command": "offerquest ollama pull",
        "models_command": "offerquest ollama models",
    }


def run_ollama_models_pull(
    *,
    base_url: str,
    models: list[str],
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> PullOllamaModelsResult:
    normalized_models = []
    for model in models:
        normalized_model = str(model or "").strip()
        if normalized_model and normalized_model not in normalized_models:
            normalized_models.append(normalized_model)

    if not normalized_models:
        raise ValueError("Select at least one Ollama model to pull.")

    status = get_ollama_status(base_url, timeout_seconds=2)
    if not status.get("reachable"):
        raise ValueError(
            "Ollama server is not reachable. Start it with `offerquest ollama serve` first."
        )

    model_count = len(normalized_models)
    for model_index, model in enumerate(normalized_models):
        pull_ollama_model(
            model=model,
            base_url=base_url,
            progress_callback=build_model_pull_progress_callback(
                model=model,
                model_index=model_index,
                model_count=model_count,
                progress_callback=progress_callback,
            ),
        )
        if progress_callback is not None:
            progress_callback(
                {
                    "progress": ((model_index + 1) / model_count) * 100,
                    "message": f"Pulled {model}",
                    "detail": f"{model_index + 1} of {model_count} model(s) ready.",
                }
            )

    refreshed_status = get_ollama_status(base_url, timeout_seconds=2)
    return PullOllamaModelsResult(
        pulled_models=tuple(normalized_models),
        base_url=base_url,
        ollama_status=refreshed_status,
    )


def build_model_pull_progress_callback(
    *,
    model: str,
    model_index: int,
    model_count: int,
    progress_callback: Callable[[dict[str, Any]], None] | None,
) -> Callable[[dict[str, Any]], None] | None:
    if progress_callback is None:
        return None

    layer_totals: dict[str, int] = {}
    layer_completed: dict[str, int] = {}
    last_progress = [model_index / model_count * 100]

    def handle_progress(chunk: dict[str, Any]) -> None:
        status = str(chunk.get("status") or "Pulling model")
        digest = str(chunk.get("digest") or "")
        total = parse_progress_int(chunk.get("total"))
        completed = parse_progress_int(chunk.get("completed"))

        if digest and total is not None:
            layer_totals[digest] = total
        if digest and completed is not None:
            layer_completed[digest] = completed

        known_total = sum(layer_totals.values())
        known_completed = sum(
            min(layer_completed.get(digest, 0), total)
            for digest, total in layer_totals.items()
        )
        if known_total:
            model_fraction = min(known_completed / known_total, 1)
        else:
            model_fraction = 0
        overall_progress = ((model_index + model_fraction) / model_count) * 100
        last_progress[0] = max(last_progress[0], overall_progress)

        detail = status
        if known_total:
            detail = f"{status}: {format_progress_bytes(known_completed)} of {format_progress_bytes(known_total)}"

        progress_callback(
            {
                "progress": last_progress[0],
                "message": f"Pulling {model}",
                "detail": detail,
            }
        )

    return handle_progress


def parse_progress_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def format_progress_bytes(size: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.0f} {unit}"
        size = int(size / 1024)
    return f"{size:.0f} TB"
