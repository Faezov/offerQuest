from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

from .jobs import load_adzuna_credentials_status
from .ollama import DEFAULT_OLLAMA_BASE_URL, get_ollama_status
from .workspace import ProjectState

PROFILE_SOURCE_SUFFIXES = {".txt", ".md", ".doc", ".docx", ".odt"}
WEB_DEPENDENCY_MODULES = (
    ("fastapi", "FastAPI"),
    ("jinja2", "Jinja2"),
    ("multipart", "python-multipart"),
    ("uvicorn", "Uvicorn"),
)


def build_doctor_report(
    project_state: ProjectState,
    *,
    ollama_base_url: str = DEFAULT_OLLAMA_BASE_URL,
    ollama_timeout_seconds: int = 2,
) -> dict[str, Any]:
    layout_check = build_workspace_layout_check(project_state)
    job_sources_check = build_job_sources_check(project_state)
    profile_sources_check = build_profile_sources_check(project_state)
    web_dependencies_check = build_web_dependencies_check()
    adzuna_check = build_adzuna_credentials_check()
    ollama_check = build_ollama_check(
        ollama_base_url=ollama_base_url,
        timeout_seconds=ollama_timeout_seconds,
    )
    checks = [
        layout_check,
        profile_sources_check,
        job_sources_check,
        web_dependencies_check,
        adzuna_check,
        ollama_check,
    ]
    blocking_issue_count = sum(
        1 for check in checks if check["blocking"] and check["status"] != "ok"
    )
    warning_count = sum(1 for check in checks if check["status"] != "ok")

    return {
        "workspace_root": str(project_state.root),
        "checks": checks,
        "blocking_issue_count": blocking_issue_count,
        "warning_count": warning_count,
        "ready_for_first_run": blocking_issue_count == 0,
        "recommended_next_steps": build_recommended_next_steps(
            project_state,
            checks=checks,
        ),
    }


def render_doctor_report(report: dict[str, Any]) -> str:
    lines = [
        "OfferQuest doctor",
        f"Workspace: {report['workspace_root']}",
        "",
    ]

    for check in report["checks"]:
        lines.append(f"[{check['status_label']}] {check['title']}")
        lines.append(check["summary"])
        if check.get("detail"):
            lines.append(check["detail"])
        if check.get("next_step"):
            lines.append(f"Next: {check['next_step']}")
        lines.append("")

    if report["recommended_next_steps"]:
        lines.append("Recommended next steps:")
        for index, step in enumerate(report["recommended_next_steps"], start=1):
            lines.append(f"{index}. {step}")
        lines.append("")

    overall = "ready" if report["ready_for_first_run"] else "needs setup"
    lines.append(f"Overall status: {overall}")
    return "\n".join(lines).rstrip() + "\n"


def build_workspace_layout_check(project_state: ProjectState) -> dict[str, Any]:
    missing_paths = [
        name
        for name, path in (
            ("data/", project_state.data_dir),
            ("jobs/", project_state.jobs_dir),
            ("outputs/", project_state.outputs_dir),
        )
        if not path.exists()
    ]

    if missing_paths:
        return make_check(
            key="workspace_layout",
            title="Workspace layout",
            status="warn",
            blocking=True,
            summary=(
                "This workspace is missing the standard OfferQuest folders: "
                + ", ".join(missing_paths)
            ),
            next_step=(
                f"Run `offerquest init-workspace --path {project_state.root}` to create the standard layout."
            ),
            detail="OfferQuest expects separate `data/`, `jobs/`, and `outputs/` folders for source files and generated artifacts.",
        )

    return make_check(
        key="workspace_layout",
        title="Workspace layout",
        status="ok",
        blocking=True,
        summary="The standard OfferQuest folders are present.",
        detail="`data/`, `jobs/`, and `outputs/` are ready for use.",
    )


def build_profile_sources_check(project_state: ProjectState) -> dict[str, Any]:
    documents = list_workspace_documents(project_state)
    cv_candidate = choose_document(documents, preferred_terms=("cv", "resume"))
    cover_letter_candidate = choose_document(
        documents,
        preferred_terms=("cover", "letter", "cl"),
    )

    if cv_candidate and cover_letter_candidate:
        return make_check(
            key="profile_sources",
            title="Profile source documents",
            status="ok",
            blocking=True,
            summary=(
                f"Found {len(documents)} profile source file(s), including a default CV and cover letter."
            ),
            detail=(
                f"Default CV: `{cv_candidate}`. Default cover letter: `{cover_letter_candidate}`."
            ),
        )

    missing_labels: list[str] = []
    if not cv_candidate:
        missing_labels.append("CV or resume")
    if not cover_letter_candidate:
        missing_labels.append("cover letter")

    return make_check(
        key="profile_sources",
        title="Profile source documents",
        status="warn",
        blocking=True,
        summary=(
            "Missing "
            + " and ".join(missing_labels)
            + " under `data/`."
        ),
        next_step=(
            "Add your own files under `data/` and name them with `cv` or `resume`, "
            "and `cover` or `letter`, so OfferQuest can choose defaults automatically."
        ),
        detail=(
            f"Detected {len(documents)} supported file(s) in `data/`."
            if documents
            else "No supported profile documents were found in `data/`."
        ),
    )


def build_job_sources_check(project_state: ProjectState) -> dict[str, Any]:
    config_path = project_state.jobs_dir / "sources.json"
    if not config_path.exists():
        return make_check(
            key="job_sources",
            title="Job source config",
            status="warn",
            blocking=True,
            summary="`jobs/sources.json` is missing.",
            next_step=(
                f"Run `offerquest init-workspace --path {project_state.root}` or create `jobs/sources.json` manually."
            ),
            detail="The refresh workflow uses this file to define manual, Greenhouse, and Adzuna sources.",
        )

    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except OSError:
        return make_check(
            key="job_sources",
            title="Job source config",
            status="warn",
            blocking=True,
            summary="`jobs/sources.json` could not be read.",
            next_step="Check file permissions and try `offerquest doctor` again.",
        )
    except json.JSONDecodeError:
        return make_check(
            key="job_sources",
            title="Job source config",
            status="warn",
            blocking=True,
            summary="`jobs/sources.json` is not valid JSON.",
            next_step="Fix the JSON syntax or recreate the file with `offerquest init-workspace --path ... --force`.",
        )

    sources = payload.get("sources", [])
    if not isinstance(sources, list):
        return make_check(
            key="job_sources",
            title="Job source config",
            status="warn",
            blocking=True,
            summary="`jobs/sources.json` must contain a `sources` list.",
            next_step="Update the config schema so `sources` is a JSON array of job source objects.",
        )

    enabled_count = sum(
        1 for source in sources if isinstance(source, dict) and source.get("enabled", True) is not False
    )
    if not sources:
        return make_check(
            key="job_sources",
            title="Job source config",
            status="warn",
            blocking=True,
            summary="`jobs/sources.json` exists, but no job sources are configured yet.",
            next_step="Add at least one manual, Greenhouse, or Adzuna source before refreshing jobs.",
        )

    return make_check(
        key="job_sources",
        title="Job source config",
        status="ok",
        blocking=True,
        summary=f"Found {len(sources)} configured job source(s), {enabled_count} enabled.",
        detail="You can edit sources in `jobs/sources.json` or from the workbench Job Sources page.",
    )


def build_web_dependencies_check() -> dict[str, Any]:
    missing_packages = [
        display_name
        for module_name, display_name in WEB_DEPENDENCY_MODULES
        if not is_module_available(module_name)
    ]
    if missing_packages:
        return make_check(
            key="web_dependencies",
            title="Web workbench dependencies",
            status="warn",
            blocking=False,
            summary="The optional web workbench dependencies are not fully installed.",
            next_step="Install them with `pip install -e .[web]` before using `offerquest-workbench`.",
            detail="Missing packages: " + ", ".join(missing_packages) + ".",
        )

    return make_check(
        key="web_dependencies",
        title="Web workbench dependencies",
        status="ok",
        blocking=False,
        summary="FastAPI, Jinja2, python-multipart, and Uvicorn are available.",
    )


def build_adzuna_credentials_check() -> dict[str, Any]:
    credentials = load_adzuna_credentials_status()
    if credentials.get("has_effective_credentials"):
        source = credentials.get("effective_source") or "credentials"
        return make_check(
            key="adzuna_credentials",
            title="Adzuna credentials",
            status="ok",
            blocking=False,
            summary=f"Adzuna credentials are available from `{source}`.",
            detail=(
                f"Credentials file: `{credentials['path']}`."
                if credentials.get("path")
                else None
            ),
        )

    return make_check(
        key="adzuna_credentials",
        title="Adzuna credentials",
        status="warn",
        blocking=False,
        summary="No Adzuna credentials were found in the environment or saved credentials file.",
        next_step=(
            "Save credentials from the Job Sources page or set `ADZUNA_APP_ID` and `ADZUNA_APP_KEY` for Adzuna refreshes."
        ),
        detail="Manual and Greenhouse sources can still run without Adzuna credentials.",
    )


def build_ollama_check(
    *,
    ollama_base_url: str = DEFAULT_OLLAMA_BASE_URL,
    timeout_seconds: int = 2,
) -> dict[str, Any]:
    status = get_ollama_status(
        ollama_base_url,
        timeout_seconds=timeout_seconds,
    )
    if status.get("reachable"):
        models = status.get("models", [])
        model_names = [str(model.get("name")) for model in models if model.get("name")]
        detail = (
            "Available models: " + ", ".join(model_names[:5]) + ("." if len(model_names) <= 5 else ", ...")
            if model_names
            else "The server is reachable, but no models were listed."
        )
        return make_check(
            key="ollama",
            title="Ollama",
            status="ok",
            blocking=False,
            summary=f"Ollama is reachable at `{ollama_base_url}`.",
            detail=detail,
        )

    return make_check(
        key="ollama",
        title="Ollama",
        status="warn",
        blocking=False,
        summary=f"Ollama is not reachable at `{ollama_base_url}`.",
        next_step="Start Ollama locally before using the LLM cover-letter workflows, or skip those workflows for now.",
        detail=str(status.get("error") or "The server did not respond."),
    )


def build_recommended_next_steps(
    project_state: ProjectState,
    *,
    checks: list[dict[str, Any]],
) -> list[str]:
    check_map = {check["key"]: check for check in checks}
    steps: list[str] = []

    if check_map["workspace_layout"]["status"] != "ok":
        steps.append(
            f"Run `offerquest init-workspace --path {project_state.root}` to create the standard workspace layout."
        )
    if check_map["profile_sources"]["status"] != "ok":
        steps.append(
            "Add your CV and base cover letter under `data/`, then rerun `offerquest doctor --path .`."
        )
    if check_map["job_sources"]["status"] != "ok":
        steps.append(
            "Edit `jobs/sources.json` or open the Job Sources page in the workbench to configure at least one source."
        )
    steps.append(
        f"Start the web workbench with `offerquest-workbench --root {project_state.root}` for the guided workflow."
    )
    if check_map["adzuna_credentials"]["status"] != "ok":
        steps.append(
            "If you plan to use Adzuna, save credentials from the Job Sources page or set them in your shell environment."
        )
    if check_map["ollama"]["status"] != "ok":
        steps.append(
            "If you want LLM cover-letter drafts, start Ollama locally and pull at least one model first."
        )
    return steps


def list_workspace_documents(project_state: ProjectState) -> list[str]:
    if not project_state.data_dir.exists():
        return []

    return sorted(
        str(path.relative_to(project_state.root))
        for path in project_state.data_dir.rglob("*")
        if path.is_file()
        and path.suffix.lower() in PROFILE_SOURCE_SUFFIXES
        and not path.name.lower().startswith("readme")
    )


def choose_document(documents: list[str], *, preferred_terms: tuple[str, ...]) -> str | None:
    for document in documents:
        lowered = Path(document).name.lower()
        if any(term in lowered for term in preferred_terms):
            return document
    return None


def is_module_available(module_name: str) -> bool:
    return importlib.util.find_spec(module_name) is not None


def make_check(
    *,
    key: str,
    title: str,
    status: str,
    blocking: bool,
    summary: str,
    next_step: str | None = None,
    detail: str | None = None,
) -> dict[str, Any]:
    return {
        "key": key,
        "title": title,
        "status": status,
        "status_label": "OK" if status == "ok" else "WARN",
        "status_css_class": "status-chip--live" if status == "ok" else "status-chip--warning",
        "blocking": blocking,
        "summary": summary,
        "detail": detail,
        "next_step": next_step,
    }
