from __future__ import annotations

import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from offerquest.cli import main


class CliProductizationTests(unittest.TestCase):
    def test_main_init_workspace_creates_workspace_and_prints_next_steps(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace_root = Path(tmpdir) / "workspace"
            output = io.StringIO()

            with redirect_stdout(output):
                exit_code = main(["init-workspace", "--path", str(workspace_root)])
            self.assertTrue((workspace_root / "jobs" / "sources.json").exists())

        rendered = output.getvalue()
        self.assertEqual(exit_code, 0)
        self.assertIn("Initialized OfferQuest workspace", rendered)
        self.assertIn("Next steps:", rendered)

    def test_main_doctor_returns_nonzero_when_workspace_needs_setup(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace_root = Path(tmpdir) / "workspace"
            output = io.StringIO()

            with patch(
                "offerquest.cli.build_doctor_report",
                return_value={
                    "workspace_root": str(workspace_root),
                    "checks": [],
                    "blocking_issue_count": 1,
                    "warning_count": 1,
                    "ready_for_first_run": False,
                    "recommended_next_steps": ["Add your CV and base cover letter under `data/`."],
                },
            ):
                with redirect_stdout(output):
                    exit_code = main(["doctor", "--path", str(workspace_root)])

        rendered = output.getvalue()
        self.assertEqual(exit_code, 1)
        self.assertIn("Overall status: needs setup", rendered)


if __name__ == "__main__":
    unittest.main()
