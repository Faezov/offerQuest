from __future__ import annotations

import json
import re
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

WORKSPACE_README = """# OfferQuest Workspace

This folder is a local OfferQuest workspace.

## What Goes Here

- Put your CV and base cover letter in `data/`
- Keep manual job descriptions in `jobs/`
- OfferQuest writes generated outputs to `outputs/`

## First Steps

1. Add your own CV and base cover letter under `data/`
2. Review `jobs/sources.json` and update the starter job sources
3. Run `offerquest doctor --path .` to check the workspace
4. Start the web workbench with `offerquest-workbench --root .`

No personal sample documents are included. This workspace is meant to stay user-owned.
"""

DATA_README = """Put your own CV, resume, and base cover letter files here.

Use filenames that include `cv` or `resume` for the resume, and `cover` or `letter` for the cover letter, so OfferQuest can pick sensible defaults in the CLI and web workbench.
"""

JOBS_README = """Put manual job descriptions here as `.txt`, `.md`, `.doc`, `.docx`, or `.odt` files.

The starter `sources.json` file already includes a manual source that reads from this folder and writes normalized job records to `outputs/jobs/manual.jsonl`.
"""

STARTER_JOB_SOURCES = {
    "sources": [
        {
            "name": "manual-jobs",
            "type": "manual",
            "input_path": "jobs",
            "output": "manual.jsonl",
        }
    ],
    "merge": {
        "enabled": True,
        "inputs": ["manual.jsonl"],
        "output": "all.jsonl",
    },
    "summary_output": "refresh-summary.json",
}


@dataclass(frozen=True)
class ProjectState:
    root: Path
    data_dir: Path
    jobs_dir: Path
    outputs_dir: Path
    state_dir: Path
    runs_dir: Path
    index_path: Path

    @classmethod
    def from_root(cls, root: str | Path) -> ProjectState:
        root_path = Path(root).resolve()
        outputs_dir = root_path / "outputs"
        state_dir = outputs_dir / "state"
        return cls(
            root=root_path,
            data_dir=root_path / "data",
            jobs_dir=root_path / "jobs",
            outputs_dir=outputs_dir,
            state_dir=state_dir,
            runs_dir=state_dir / "runs",
            index_path=state_dir / "index.json",
        )

    def ensure_directories(self) -> None:
        self.outputs_dir.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.runs_dir.mkdir(parents=True, exist_ok=True)

    def record_run(
        self,
        workflow: str,
        *,
        artifacts: list[dict[str, Any]],
        metadata: dict[str, Any] | None = None,
        label: str | None = None,
    ) -> dict[str, Any]:
        self.ensure_directories()
        created_at = now_iso()
        run_id = self._next_run_id(workflow, created_at=created_at, label=label)

        manifest = {
            "id": run_id,
            "workflow": workflow,
            "label": label,
            "created_at": created_at,
            "workspace_root": str(self.root),
            "artifacts": [self._normalize_artifact(artifact) for artifact in artifacts],
            "metadata": metadata or {},
        }
        manifest_path = self.runs_dir / f"{run_id}.json"
        write_json_atomic(manifest_path, manifest)
        self._update_index(manifest)
        return manifest

    def list_runs(self) -> list[dict[str, Any]]:
        if not self.index_path.exists():
            return []
        payload = json.loads(self.index_path.read_text(encoding="utf-8"))
        runs = payload.get("runs", [])
        if not isinstance(runs, list):
            return []
        return runs

    def get_run_manifest(self, run_id: str) -> dict[str, Any] | None:
        manifest_path = self.runs_dir / f"{run_id}.json"
        if not manifest_path.exists():
            return None
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return None
        return payload

    def resolve_artifact_path(self, path: str | Path) -> Path:
        artifact_path = Path(path)
        if artifact_path.is_absolute():
            return artifact_path
        return (self.root / artifact_path).resolve()

    def _normalize_artifact(self, artifact: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(artifact)
        raw_path = normalized.get("path")
        if raw_path:
            artifact_path = Path(raw_path)
            if not artifact_path.is_absolute():
                artifact_path = (self.root / artifact_path).resolve()
            normalized["path"] = str(relative_to_root(artifact_path, self.root))
        return normalized

    def _update_index(self, manifest: dict[str, Any]) -> None:
        existing_runs = [run for run in self.list_runs() if run.get("id") != manifest["id"]]
        index_payload = {
            "workspace_root": str(self.root),
            "runs": [
                summarize_run(manifest),
                *existing_runs,
            ],
        }
        write_json_atomic(self.index_path, index_payload)

    def _next_run_id(self, workflow: str, *, created_at: str, label: str | None = None) -> str:
        base_run_id = build_run_id(workflow, created_at=created_at, label=label)
        run_id = base_run_id
        sequence = 2

        while (self.runs_dir / f"{run_id}.json").exists():
            run_id = f"{base_run_id}-{sequence}"
            sequence += 1

        return run_id


@dataclass(frozen=True)
class WorkspaceInitResult:
    root: Path
    created_paths: tuple[str, ...]
    overwritten_paths: tuple[str, ...]
    readme_path: Path
    sources_path: Path


def init_workspace(root: str | Path, *, force: bool = False) -> WorkspaceInitResult:
    project_state = ProjectState.from_root(root)
    root_path = project_state.root
    created_paths: list[str] = []
    overwritten_paths: list[str] = []

    if root_path.exists():
        try:
            has_existing_content = any(root_path.iterdir())
        except OSError:
            has_existing_content = False
        if has_existing_content and not force:
            raise ValueError(
                f"Workspace path is not empty: {root_path}. Use --force to bootstrap into an existing directory."
            )
    else:
        root_path.mkdir(parents=True, exist_ok=True)
        created_paths.append(".")

    for directory in (
        project_state.data_dir,
        project_state.jobs_dir,
        project_state.outputs_dir,
        project_state.state_dir,
        project_state.runs_dir,
    ):
        if not directory.exists():
            directory.mkdir(parents=True, exist_ok=True)
            created_paths.append(str(relative_to_root(directory, root_path)))

    readme_path = root_path / "README.md"
    data_readme_path = project_state.data_dir / "README.md"
    jobs_readme_path = project_state.jobs_dir / "README.md"
    sources_path = project_state.jobs_dir / "sources.json"

    _write_workspace_text(
        readme_path,
        WORKSPACE_README,
        root=root_path,
        created_paths=created_paths,
        overwritten_paths=overwritten_paths,
    )
    _write_workspace_text(
        data_readme_path,
        DATA_README,
        root=root_path,
        created_paths=created_paths,
        overwritten_paths=overwritten_paths,
    )
    _write_workspace_text(
        jobs_readme_path,
        JOBS_README,
        root=root_path,
        created_paths=created_paths,
        overwritten_paths=overwritten_paths,
    )
    _write_workspace_json(
        sources_path,
        STARTER_JOB_SOURCES,
        root=root_path,
        created_paths=created_paths,
        overwritten_paths=overwritten_paths,
    )

    return WorkspaceInitResult(
        root=root_path,
        created_paths=tuple(created_paths),
        overwritten_paths=tuple(overwritten_paths),
        readme_path=readme_path,
        sources_path=sources_path,
    )


def summarize_run(manifest: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": manifest.get("id"),
        "workflow": manifest.get("workflow"),
        "label": manifest.get("label"),
        "created_at": manifest.get("created_at"),
        "artifacts": manifest.get("artifacts", []),
        "metadata": manifest.get("metadata", {}),
    }


def build_run_id(workflow: str, *, created_at: str, label: str | None = None) -> str:
    timestamp = created_at.replace("-", "").replace(":", "").replace("T", "-").replace("Z", "")
    suffix = slugify(label or workflow, fallback="run")
    return f"{timestamp}-{suffix}"


def relative_to_root(path: Path, root: Path) -> Path:
    try:
        return path.resolve().relative_to(root.resolve())
    except ValueError:
        return path.resolve()


def slugify(value: str, *, fallback: str = "item") -> str:
    lowered = value.lower()
    lowered = re.sub(r"[^a-z0-9]+", "-", lowered)
    return lowered.strip("-") or fallback


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None

    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            handle.write(json.dumps(payload, indent=2))
            handle.flush()
            temp_path = Path(handle.name)

        temp_path.replace(path)
    finally:
        if temp_path and temp_path.exists():
            temp_path.unlink()


def _write_workspace_text(
    path: Path,
    content: str,
    *,
    root: Path,
    created_paths: list[str],
    overwritten_paths: list[str],
) -> None:
    _record_workspace_path(path, root=root, created_paths=created_paths, overwritten_paths=overwritten_paths)
    path.write_text(content, encoding="utf-8")


def _write_workspace_json(
    path: Path,
    payload: dict[str, Any],
    *,
    root: Path,
    created_paths: list[str],
    overwritten_paths: list[str],
) -> None:
    _record_workspace_path(path, root=root, created_paths=created_paths, overwritten_paths=overwritten_paths)
    write_json_atomic(path, payload)


def _record_workspace_path(
    path: Path,
    *,
    root: Path,
    created_paths: list[str],
    overwritten_paths: list[str],
) -> None:
    relative = str(relative_to_root(path, root))
    if path.exists():
        if relative not in overwritten_paths:
            overwritten_paths.append(relative)
    elif relative not in created_paths:
        created_paths.append(relative)
