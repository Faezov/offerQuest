from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from offerquest.workspace import ProjectState


class WorkspaceTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
