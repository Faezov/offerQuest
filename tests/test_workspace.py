from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from offerquest.workspace import ProjectState, init_workspace


class WorkspaceTests(unittest.TestCase):
    def test_init_workspace_creates_expected_layout(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace_root = Path(tmpdir) / "workspace"

            result = init_workspace(workspace_root)
            self.assertEqual(result.root, workspace_root.resolve())
            self.assertTrue((workspace_root / "data").is_dir())
            self.assertTrue((workspace_root / "jobs").is_dir())
            self.assertTrue((workspace_root / "outputs").is_dir())
            self.assertTrue((workspace_root / "jobs" / "sources.json").exists())
            self.assertTrue((workspace_root / "README.md").exists())

    def test_init_workspace_rejects_non_empty_directory_without_force(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace_root = Path(tmpdir) / "workspace"
            workspace_root.mkdir()
            (workspace_root / "notes.txt").write_text("existing", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "Workspace path is not empty"):
                init_workspace(workspace_root)

    def test_init_workspace_force_overwrites_starter_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace_root = Path(tmpdir) / "workspace"
            init_workspace(workspace_root)
            starter_sources_path = workspace_root / "jobs" / "sources.json"
            starter_sources_path.write_text('{"sources": []}', encoding="utf-8")

            result = init_workspace(workspace_root, force=True)
            self.assertIn("jobs/sources.json", result.overwritten_paths)
            self.assertIn("manual-jobs", starter_sources_path.read_text(encoding="utf-8"))

    def test_record_run_writes_manifest_and_index(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            output_file = root / "outputs" / "profile.json"
            output_file.parent.mkdir(parents=True, exist_ok=True)
            output_file.write_text("{}", encoding="utf-8")

            state = ProjectState.from_root(root)
            manifest = state.record_run(
                "build-profile",
                artifacts=[{"kind": "profile", "path": output_file}],
                metadata={"job_count": 0},
                label="profile",
            )

            run_files = list(state.runs_dir.glob("*.json"))
            indexed_runs = state.list_runs()

            self.assertEqual(len(run_files), 1)
            self.assertEqual(manifest["artifacts"][0]["path"], "outputs/profile.json")
            self.assertEqual(indexed_runs[0]["workflow"], "build-profile")

    def test_record_run_keeps_distinct_ids_when_timestamps_collide(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            state = ProjectState.from_root(root)

            with patch("offerquest.workspace.now_iso", return_value="2026-04-23T01:02:03Z"):
                first = state.record_run("build-profile", artifacts=[], label="profile")
                second = state.record_run("build-profile", artifacts=[], label="profile")

            run_files = sorted(path.name for path in state.runs_dir.glob("*.json"))
            indexed_runs = state.list_runs()

        self.assertEqual(first["id"], "20260423-010203-profile")
        self.assertEqual(second["id"], "20260423-010203-profile-2")
        self.assertEqual(len(run_files), 2)
        self.assertEqual(len(indexed_runs), 2)


if __name__ == "__main__":
    unittest.main()
