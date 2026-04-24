from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..jobs import (
    load_adzuna_credentials_status,
    refresh_job_sources,
    write_adzuna_credentials_file,
)
from ..workspace import ProjectState, relative_to_root, slugify, write_json_atomic
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
    restorable_source_form_data: dict[str, str] | None = None


def build_job_sources_view(
    project_state: ProjectState,
    *,
    app_id: str | None = None,
    credentials_error: str | None = None,
    credentials_result: SaveAdzunaCredentialsResult | None = None,
    refresh_config_path: str | None = None,
    refresh_output_dir: str | None = None,
    refresh_error: str | None = None,
    refresh_field_errors: dict[str, str] | None = None,
    refresh_result: BuildRefreshJobsResult | None = None,
    source_form_data: dict[str, Any] | None = None,
    source_form_error: str | None = None,
    source_field_errors: dict[str, str] | None = None,
    source_form_result: SaveJobSourceConfigResult | None = None,
    credentials_field_errors: dict[str, str] | None = None,
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
        "credentials_field_errors": dict(credentials_field_errors or {}),
        "credentials_first_error_field": next(iter(credentials_field_errors or {}), None),
        "credentials_result": credentials_result,
        "selected_refresh_config_path": selected_config_path,
        "selected_refresh_output_dir": selected_output_dir,
        "selected_refresh_summary_output": default_summary_output,
        "refresh_error": refresh_error,
        "refresh_field_errors": dict(refresh_field_errors or {}),
        "refresh_first_error_field": next(iter(refresh_field_errors or {}), None),
        "refresh_result": refresh_result,
        "source_form": source_form,
        "source_form_mode": source_form_mode,
        "source_form_notice": source_form_notice,
        "source_form_error": source_form_error,
        "source_field_errors": dict(source_field_errors or {}),
        "source_first_error_field": next(iter(source_field_errors or {}), None),
        "source_form_result": source_form_result,
        "source_type_options": list(JOB_SOURCE_TYPES),
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
        restorable_source_form_data=build_job_source_form_data(removed_source),
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


def build_job_source_form_data(
    source: dict[str, Any] | None = None,
    *,
    source_type: str | None = None,
) -> dict[str, Any]:
    source = source or {}
    normalized_type = str(source_type or source.get("type") or "adzuna").strip().lower()
    if normalized_type not in JOB_SOURCE_TYPES:
        normalized_type = "adzuna"

    enabled_value = source.get("enabled", "true")
    enabled = (
        enabled_value
        if isinstance(enabled_value, str)
        else "true" if enabled_value is not False else "false"
    )

    return {
        "source_index": str(source.get("source_index", source.get("index", ""))),
        "name": str(source.get("name") or ""),
        "type": normalized_type,
        "enabled": enabled,
        "output": str(source.get("output") or ""),
        "what": str(source.get("what") or ""),
        "where": str(source.get("where") or ""),
        "country": str(source.get("country") or "au"),
        "pages": str(source.get("pages") or "1"),
        "results_per_page": str(source.get("results_per_page") or "20"),
        "board_token": str(source.get("board_token") or ""),
        "input_path": str(source.get("input_path") or "jobs"),
    }


def build_job_source_form_state(
    source_summary: dict[str, Any],
    *,
    source_form_data: dict[str, Any] | None,
    edit_source_index: int | None,
    duplicate_source_index: int | None,
) -> tuple[dict[str, Any], str, str | None]:
    if source_form_data is not None:
        normalized = build_job_source_form_data(source_form_data)
        mode = "edit" if str(normalized.get("source_index") or "").strip() else "create"
        return normalized, mode, None

    sources = source_summary.get("sources", [])
    if duplicate_source_index is not None:
        if duplicate_source_index < 0 or duplicate_source_index >= len(sources):
            return (
                build_job_source_form_data(),
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
                **build_job_source_form_data(source),
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
                build_job_source_form_data(),
                "create",
                "Selected source for editing was not found.",
            )
        source = sources[edit_source_index]
        return (
            build_job_source_form_data(source),
            "edit",
            f"Editing `{source.get('name') or 'source'}`.",
        )

    return build_job_source_form_data(), "create", None


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
