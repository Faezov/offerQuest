from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..cover_letter import slugify
from ..jobs import (
    load_adzuna_credentials_status,
    refresh_job_sources,
    write_adzuna_credentials_file,
)
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
    install_local_ollama_runtime,
    pull_ollama_model,
    restart_managed_ollama_server,
)
from ..workspace import ProjectState, relative_to_root, write_json_atomic
from ._util import (
    format_user_path,
    normalize_boolean_toggle,
    resolve_workspace_input_path,
    resolve_workspace_output_path,
)

JOB_SOURCE_TYPES = ("adzuna", "greenhouse", "manual")


@dataclass(frozen=True)
class SaveAdzunaCredentialsResult:
    credentials_path: Path
    credentials_path_display: str
    saved_app_id_masked: str | None
    saved_app_key_masked: str | None


@dataclass(frozen=True)
class BuildRefreshJobsResult:
    summary: dict[str, Any]
    summary_path: Path
    summary_path_relative: str
    merged_output_path: Path | None
    merged_output_path_relative: str | None
    run_manifest: dict[str, Any]


@dataclass(frozen=True)
class SaveJobSourceConfigResult:
    config_path: Path
    config_path_relative: str
    action: str
    source_name: str
    source_count: int


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


def build_job_sources_view(
    project_state: ProjectState,
    *,
    app_id: str | None = None,
    credentials_error: str | None = None,
    credentials_result: SaveAdzunaCredentialsResult | None = None,
    refresh_config_path: str | None = None,
    refresh_output_dir: str | None = None,
    refresh_error: str | None = None,
    refresh_result: BuildRefreshJobsResult | None = None,
    source_form_data: dict[str, Any] | None = None,
    source_form_error: str | None = None,
    source_form_result: SaveJobSourceConfigResult | None = None,
    edit_source_index: int | None = None,
    duplicate_source_index: int | None = None,
) -> dict[str, Any]:
    credentials = load_adzuna_credentials_status()
    source_summary = load_job_sources_summary(project_state)
    credentials_panel_open = bool(
        credentials_error
        or credentials_result
        or credentials["is_env_override"]
        or (
            source_summary.get("adzuna_count", 0) > 0
            and not credentials["has_effective_credentials"]
        )
    )
    selected_config_path = refresh_config_path or "jobs/sources.json"
    selected_output_dir = refresh_output_dir or "outputs/jobs"
    default_summary_output = str(Path(selected_output_dir) / "refresh-summary.json")
    source_form, source_form_mode, source_form_notice = build_job_source_form_state(
        source_summary,
        source_form_data=source_form_data,
        edit_source_index=edit_source_index,
        duplicate_source_index=duplicate_source_index,
    )

    return {
        "entered_app_id": app_id or "",
        "credentials": credentials,
        "credentials_panel_open": credentials_panel_open,
        "credentials_path_display": format_user_path(credentials["path"]),
        "source_summary": source_summary,
        "credentials_error": credentials_error,
        "credentials_result": credentials_result,
        "selected_refresh_config_path": selected_config_path,
        "selected_refresh_output_dir": selected_output_dir,
        "selected_refresh_summary_output": default_summary_output,
        "refresh_error": refresh_error,
        "refresh_result": refresh_result,
        "source_form": source_form,
        "source_form_mode": source_form_mode,
        "source_form_notice": source_form_notice,
        "source_form_error": source_form_error,
        "source_form_result": source_form_result,
        "source_type_options": list(JOB_SOURCE_TYPES),
    }


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


def run_adzuna_credentials_save(
    *,
    app_id: str | None,
    app_key: str | None,
) -> SaveAdzunaCredentialsResult:
    existing = load_adzuna_credentials_status()
    normalized_app_id = (app_id or "").strip() or existing.get("saved_app_id")
    normalized_app_key = (app_key or "").strip() or existing.get("saved_app_key")
    if not normalized_app_id or not normalized_app_key:
        raise ValueError(
            "Adzuna app id and app key are required. After the first save, you can leave a field blank to keep the current saved value."
        )

    credentials_path = write_adzuna_credentials_file(
        normalized_app_id,
        normalized_app_key,
    )
    saved_status = load_adzuna_credentials_status(credentials_path)
    return SaveAdzunaCredentialsResult(
        credentials_path=credentials_path,
        credentials_path_display=format_user_path(credentials_path),
        saved_app_id_masked=saved_status.get("saved_app_id_masked"),
        saved_app_key_masked=saved_status.get("saved_app_key_masked"),
    )


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


def run_local_ollama_runtime_install(
    *,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    return install_local_ollama_runtime(progress_callback=progress_callback)


def run_ollama_server_restart(*, base_url: str) -> dict[str, Any]:
    return restart_managed_ollama_server(base_url=base_url)


def run_job_source_save(
    project_state: ProjectState,
    *,
    source_form_data: dict[str, Any],
) -> SaveJobSourceConfigResult:
    config_state = load_job_sources_config_state(project_state)
    if config_state["error"]:
        raise ValueError(str(config_state["error"]))

    payload = dict(config_state["payload"])
    sources = list(payload.get("sources", []))
    source_index = parse_optional_source_index(source_form_data.get("source_index"))
    source_record = build_job_source_record(
        source_form_data,
        existing_sources=sources,
        current_index=source_index,
    )

    if source_index is None:
        sources.append(source_record)
        action = "created"
    else:
        if source_index < 0 or source_index >= len(sources):
            raise ValueError("Selected source was not found in the current config.")
        sources[source_index] = source_record
        action = "updated"

    updated_payload = build_updated_job_sources_payload(payload, sources)
    write_json_atomic(config_state["path"], updated_payload)
    return SaveJobSourceConfigResult(
        config_path=config_state["path"],
        config_path_relative=config_state["path_relative"],
        action=action,
        source_name=str(source_record.get("name") or "source"),
        source_count=len(sources),
    )


def run_job_source_delete(
    project_state: ProjectState,
    *,
    source_index: int,
) -> SaveJobSourceConfigResult:
    config_state = load_job_sources_config_state(project_state)
    if config_state["error"]:
        raise ValueError(str(config_state["error"]))

    payload = dict(config_state["payload"])
    sources = list(payload.get("sources", []))
    if source_index < 0 or source_index >= len(sources):
        raise ValueError("Selected source was not found in the current config.")

    removed_source = sources.pop(source_index)
    updated_payload = build_updated_job_sources_payload(payload, sources)
    write_json_atomic(config_state["path"], updated_payload)
    return SaveJobSourceConfigResult(
        config_path=config_state["path"],
        config_path_relative=config_state["path_relative"],
        action="deleted",
        source_name=str(removed_source.get("name") or "source"),
        source_count=len(sources),
    )


def run_job_source_toggle(
    project_state: ProjectState,
    *,
    source_index: int,
) -> SaveJobSourceConfigResult:
    config_state = load_job_sources_config_state(project_state)
    if config_state["error"]:
        raise ValueError(str(config_state["error"]))

    payload = dict(config_state["payload"])
    sources = list(payload.get("sources", []))
    if source_index < 0 or source_index >= len(sources):
        raise ValueError("Selected source was not found in the current config.")

    source = dict(sources[source_index])
    enabled = source.get("enabled", True) is not False
    if enabled:
        source["enabled"] = False
        action = "disabled"
    else:
        source.pop("enabled", None)
        action = "enabled"
    sources[source_index] = source

    updated_payload = build_updated_job_sources_payload(payload, sources)
    write_json_atomic(config_state["path"], updated_payload)
    return SaveJobSourceConfigResult(
        config_path=config_state["path"],
        config_path_relative=config_state["path_relative"],
        action=action,
        source_name=str(source.get("name") or "source"),
        source_count=len(sources),
    )


def run_refresh_jobs_build(
    project_state: ProjectState,
    *,
    config_path: str,
    output_dir: str,
) -> BuildRefreshJobsResult:
    config_full_path = resolve_workspace_input_path(project_state, config_path)
    output_dir_full_path = resolve_workspace_output_path(project_state, output_dir)

    if not config_full_path.exists():
        raise ValueError(f"Jobs config file not found: {config_path}")

    summary = refresh_job_sources(
        config_full_path,
        workspace_root=project_state.root,
        output_dir=output_dir_full_path,
    )
    summary_path = project_state.resolve_artifact_path(summary["summary_output"])
    merged_output_value = summary.get("merged_output")
    merged_output_path = (
        project_state.resolve_artifact_path(merged_output_value)
        if merged_output_value
        else None
    )

    artifacts: list[dict[str, Any]] = [{"kind": "jobs_refresh_summary", "path": summary_path}]
    artifacts.extend(
        {"kind": "jobs_file", "path": project_state.resolve_artifact_path(source["output"])}
        for source in summary.get("sources", [])
        if source.get("output")
    )
    if merged_output_path is not None:
        artifacts.append({"kind": "jobs_file", "path": merged_output_path})

    run_manifest = project_state.record_run(
        "refresh-jobs",
        artifacts=artifacts,
        metadata={
            "source_count": summary.get("source_count"),
            "merged_job_count": summary.get("merged_job_count"),
            "config_path": summary.get("config_path"),
            "output_dir": summary.get("output_dir"),
        },
        label=output_dir_full_path.name,
    )

    return BuildRefreshJobsResult(
        summary=summary,
        summary_path=summary_path,
        summary_path_relative=str(relative_to_root(summary_path, project_state.root)),
        merged_output_path=merged_output_path,
        merged_output_path_relative=(
            str(relative_to_root(merged_output_path, project_state.root))
            if merged_output_path is not None
            else None
        ),
        run_manifest=run_manifest,
    )


def load_job_sources_summary(project_state: ProjectState) -> dict[str, Any]:
    config_state = load_job_sources_config_state(project_state)
    config_path = config_state["path"]
    summary: dict[str, Any] = {
        "exists": config_path.exists(),
        "path": config_path,
        "path_relative": config_state["path_relative"],
        "sources": [],
        "source_count": 0,
        "adzuna_count": 0,
        "greenhouse_count": 0,
        "manual_count": 0,
        "other_count": 0,
        "error": config_state["error"],
        "merge_enabled": True,
        "merge_output": "all.jsonl",
        "merge_inputs": [],
        "summary_output": "refresh-summary.json",
        "payload": config_state["payload"],
    }
    if not config_path.exists() or config_state["error"]:
        return summary

    payload = config_state["payload"]
    raw_sources = payload.get("sources", [])
    sources: list[dict[str, Any]] = []
    counts = {
        "adzuna_count": 0,
        "greenhouse_count": 0,
        "manual_count": 0,
        "other_count": 0,
    }
    merge_payload = payload.get("merge") if isinstance(payload.get("merge"), dict) else {}

    for index, raw_source in enumerate(raw_sources):
        if not isinstance(raw_source, dict):
            continue
        source_type = str(raw_source.get("type") or "unknown").strip().lower()
        if source_type == "adzuna":
            counts["adzuna_count"] += 1
            details = " / ".join(
                part
                for part in [
                    str(raw_source.get("what") or "").strip(),
                    str(raw_source.get("where") or "").strip(),
                    str(raw_source.get("country") or "").strip(),
                ]
                if part
            )
        elif source_type == "greenhouse":
            counts["greenhouse_count"] += 1
            details = str(raw_source.get("board_token") or "").strip()
        elif source_type == "manual":
            counts["manual_count"] += 1
            details = str(raw_source.get("input_path") or "").strip()
        else:
            counts["other_count"] += 1
            details = ""

        sources.append(
            {
                "index": index,
                "position": index + 1,
                "name": str(
                    raw_source.get("name") or raw_source.get("output") or f"source-{index + 1}"
                ).strip(),
                "type": source_type,
                "enabled": raw_source.get("enabled", True) is not False,
                "details": details,
                "output": str(raw_source.get("output") or "").strip() or None,
                "what": str(raw_source.get("what") or "").strip(),
                "where": str(raw_source.get("where") or "").strip(),
                "country": str(raw_source.get("country") or "").strip(),
                "pages": raw_source.get("pages"),
                "results_per_page": raw_source.get("results_per_page"),
                "board_token": str(raw_source.get("board_token") or "").strip(),
                "input_path": str(raw_source.get("input_path") or "").strip(),
            }
        )

    return {
        **summary,
        **counts,
        "sources": sources,
        "source_count": len(sources),
        "merge_enabled": bool(merge_payload.get("enabled", True)),
        "merge_output": str(merge_payload.get("output") or "all.jsonl").strip() or "all.jsonl",
        "merge_inputs": [
            str(item).strip()
            for item in merge_payload.get("inputs", [])
            if str(item).strip()
        ]
        if isinstance(merge_payload.get("inputs"), list)
        else [],
        "summary_output": str(payload.get("summary_output") or "refresh-summary.json").strip()
        or "refresh-summary.json",
    }


def load_job_sources_config_state(project_state: ProjectState) -> dict[str, Any]:
    config_path = project_state.root / "jobs" / "sources.json"
    default_payload = default_job_sources_payload()
    state: dict[str, Any] = {
        "path": config_path,
        "path_relative": str(relative_to_root(config_path, project_state.root)),
        "exists": config_path.exists(),
        "payload": default_payload,
        "error": None,
    }
    if not config_path.exists():
        return state

    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {**state, "error": f"Could not parse jobs/sources.json: {exc.msg}"}

    if not isinstance(payload, dict):
        return {**state, "error": "jobs/sources.json must contain a top-level object."}
    if not isinstance(payload.get("sources", []), list):
        return {**state, "error": "jobs/sources.json must contain a `sources` list."}
    if "merge" in payload and not isinstance(payload.get("merge"), dict):
        return {**state, "error": "jobs/sources.json `merge` must be an object when present."}

    return {**state, "payload": payload}


def default_job_sources_payload() -> dict[str, Any]:
    return {
        "sources": [],
        "merge": {
            "enabled": True,
            "inputs": [],
            "output": "all.jsonl",
        },
        "summary_output": "refresh-summary.json",
    }


def default_job_source_form_data(*, source_type: str = "adzuna") -> dict[str, Any]:
    normalized_type = source_type if source_type in JOB_SOURCE_TYPES else "adzuna"
    return {
        "source_index": "",
        "name": "",
        "type": normalized_type,
        "enabled": "true",
        "output": "",
        "what": "",
        "where": "",
        "country": "au",
        "pages": "1",
        "results_per_page": "20",
        "board_token": "",
        "input_path": "jobs",
    }


def build_job_source_form_state(
    source_summary: dict[str, Any],
    *,
    source_form_data: dict[str, Any] | None,
    edit_source_index: int | None,
    duplicate_source_index: int | None,
) -> tuple[dict[str, Any], str, str | None]:
    if source_form_data is not None:
        normalized = default_job_source_form_data(
            source_type=str(source_form_data.get("type") or "adzuna").strip().lower()
        )
        normalized.update({key: source_form_data.get(key, value) for key, value in normalized.items()})
        mode = "edit" if str(normalized.get("source_index") or "").strip() else "create"
        return normalized, mode, None

    sources = source_summary.get("sources", [])
    if duplicate_source_index is not None:
        if duplicate_source_index < 0 or duplicate_source_index >= len(sources):
            return (
                default_job_source_form_data(),
                "create",
                "Selected source for duplication was not found.",
            )
        source = sources[duplicate_source_index]
        existing_names = [str(item.get("name") or "") for item in sources]
        duplicate_name = suggest_duplicate_source_name(str(source.get("name") or "source"), existing_names)
        duplicate_output = suggest_duplicate_source_output(
            duplicate_name,
            str(source.get("output") or ""),
        )
        return (
            {
                **source_to_form_data(source),
                "source_index": "",
                "name": duplicate_name,
                "output": duplicate_output,
            },
            "create",
            f"Duplicating `{source.get('name') or 'source'}` as a new source.",
        )

    if edit_source_index is not None:
        if edit_source_index < 0 or edit_source_index >= len(sources):
            return (
                default_job_source_form_data(),
                "create",
                "Selected source for editing was not found.",
            )
        source = sources[edit_source_index]
        return (
            source_to_form_data(source),
            "edit",
            f"Editing `{source.get('name') or 'source'}`.",
        )

    return default_job_source_form_data(), "create", None


def source_to_form_data(source: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_index": str(source.get("index", "")),
        "name": str(source.get("name") or ""),
        "type": str(source.get("type") or "adzuna"),
        "enabled": "true" if source.get("enabled", True) else "false",
        "output": str(source.get("output") or ""),
        "what": str(source.get("what") or ""),
        "where": str(source.get("where") or ""),
        "country": str(source.get("country") or "au"),
        "pages": str(source.get("pages") or "1"),
        "results_per_page": str(source.get("results_per_page") or "20"),
        "board_token": str(source.get("board_token") or ""),
        "input_path": str(source.get("input_path") or "jobs"),
    }


def parse_optional_source_index(value: Any) -> int | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        index = int(text)
    except ValueError as exc:
        raise ValueError("Selected source index must be a whole number.") from exc
    if index < 0:
        raise ValueError("Selected source index must not be negative.")
    return index


def build_job_source_record(
    source_form_data: dict[str, Any],
    *,
    existing_sources: list[dict[str, Any]],
    current_index: int | None,
) -> dict[str, Any]:
    source_type = str(source_form_data.get("type") or "").strip().lower()
    if source_type not in JOB_SOURCE_TYPES:
        raise ValueError("Source type must be one of: adzuna, greenhouse, manual.")

    name = str(source_form_data.get("name") or "").strip()
    if not name:
        raise ValueError("Source name is required.")

    output = str(source_form_data.get("output") or "").strip() or suggest_source_output_filename(name)
    if not output:
        raise ValueError("Output filename is required.")

    enabled = normalize_boolean_toggle(source_form_data.get("enabled"), default=True)
    record: dict[str, Any] = {
        "name": name,
        "type": source_type,
        "output": output,
    }
    if not enabled:
        record["enabled"] = False

    if source_type == "adzuna":
        what = str(source_form_data.get("what") or "").strip()
        where = str(source_form_data.get("where") or "").strip()
        if not what and not where:
            raise ValueError("Adzuna sources need at least search keywords or a location.")
        country = str(source_form_data.get("country") or "").strip() or "au"
        pages = parse_positive_int(source_form_data.get("pages"), field_name="Adzuna pages")
        results_per_page = parse_positive_int(
            source_form_data.get("results_per_page"),
            field_name="Adzuna results per page",
        )
        record.update(
            {
                "country": country,
                "pages": pages,
                "results_per_page": results_per_page,
            }
        )
        if what:
            record["what"] = what
        if where:
            record["where"] = where
    elif source_type == "greenhouse":
        board_token = str(source_form_data.get("board_token") or "").strip()
        if not board_token:
            raise ValueError("Greenhouse sources require a board token.")
        record["board_token"] = board_token
    elif source_type == "manual":
        input_path = str(source_form_data.get("input_path") or "").strip()
        if not input_path:
            raise ValueError("Manual sources require an input path.")
        record["input_path"] = input_path

    validate_job_source_uniqueness(
        record,
        existing_sources=existing_sources,
        current_index=current_index,
    )
    return record


def validate_job_source_uniqueness(
    record: dict[str, Any],
    *,
    existing_sources: list[dict[str, Any]],
    current_index: int | None,
) -> None:
    for index, existing in enumerate(existing_sources):
        if current_index is not None and index == current_index:
            continue
        if not isinstance(existing, dict):
            continue
        existing_name = str(existing.get("name") or "").strip().lower()
        existing_output = str(existing.get("output") or "").strip().lower()
        if existing_name and existing_name == str(record.get("name") or "").strip().lower():
            raise ValueError("Source names must be unique.")
        if existing_output and existing_output == str(record.get("output") or "").strip().lower():
            raise ValueError("Output filenames must be unique.")


def build_updated_job_sources_payload(
    payload: dict[str, Any],
    sources: list[dict[str, Any]],
) -> dict[str, Any]:
    updated = dict(payload)
    updated["sources"] = sources

    merge_payload = dict(updated.get("merge") or {})
    merge_payload["enabled"] = merge_payload.get("enabled", True) is not False
    merge_payload["output"] = str(merge_payload.get("output") or "all.jsonl").strip() or "all.jsonl"
    merge_payload["inputs"] = [
        str(source.get("output")).strip()
        for source in sources
        if isinstance(source, dict)
        and source.get("enabled", True) is not False
        and str(source.get("output") or "").strip()
    ]
    updated["merge"] = merge_payload
    updated["summary_output"] = (
        str(updated.get("summary_output") or "refresh-summary.json").strip()
        or "refresh-summary.json"
    )
    return updated


def parse_positive_int(value: Any, *, field_name: str) -> int:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field_name} is required.")
    try:
        number = int(text)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be a whole number.") from exc
    if number < 1:
        raise ValueError(f"{field_name} must be at least 1.")
    return number


def suggest_source_output_filename(name: str) -> str:
    return f"{slugify(name)}.jsonl"


def suggest_duplicate_source_name(name: str, existing_names: list[str]) -> str:
    base_name = f"{name}-copy"
    candidate = base_name
    suffix = 2
    normalized_existing = {item.strip().lower() for item in existing_names if item.strip()}
    while candidate.strip().lower() in normalized_existing:
        candidate = f"{base_name}-{suffix}"
        suffix += 1
    return candidate


def suggest_duplicate_source_output(name: str, output: str) -> str:
    path = Path(output) if output else Path(suggest_source_output_filename(name))
    stem = path.stem or slugify(name)
    suffix = path.suffix or ".jsonl"
    duplicate_stem = f"{stem}-copy"
    if duplicate_stem == stem:
        duplicate_stem = f"{slugify(name)}-copy"
    return f"{duplicate_stem}{suffix}"
