from __future__ import annotations

import json
import re
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
        run_id = build_run_id(workflow, created_at=created_at, label=label)

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
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
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
        self.index_path.write_text(json.dumps(index_payload, indent=2), encoding="utf-8")


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
