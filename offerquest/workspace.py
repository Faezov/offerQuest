from __future__ import annotations

import json
import re
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


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
    def from_root(cls, root: str | Path) -> "ProjectState":
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
    suffix = slugify(label or workflow)
    return f"{timestamp}-{suffix}"


def relative_to_root(path: Path, root: Path) -> Path:
    try:
        return path.resolve().relative_to(root.resolve())
    except ValueError:
        return path.resolve()


def slugify(value: str) -> str:
    lowered = value.lower()
    lowered = re.sub(r"[^a-z0-9]+", "-", lowered)
    return lowered.strip("-") or "run"


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
