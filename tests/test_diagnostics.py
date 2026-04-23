from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from offerquest.diagnostics import build_doctor_report, render_doctor_report
from offerquest.workspace import ProjectState, init_workspace


class DiagnosticsTests(unittest.TestCase):
    def test_doctor_report_flags_missing_cv_and_cover_letter(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            init_workspace(root)

            with patch(
                "offerquest.diagnostics.get_ollama_status",
                return_value={
                    "reachable": False,
                    "command_available": True,
                    "error": "offline",
                },
            ):
                report = build_doctor_report(ProjectState.from_root(root))

        profile_check = next(
            check for check in report["checks"] if check["key"] == "profile_sources"
        )
        self.assertEqual(profile_check["status"], "warn")
        self.assertIn("CV or resume", profile_check["summary"])
        self.assertFalse(report["ready_for_first_run"])

    def test_doctor_report_flags_missing_web_dependencies(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            init_workspace(root)
            (root / "data" / "candidate-cv.txt").write_text("cv", encoding="utf-8")
            (root / "data" / "base-cover-letter.txt").write_text("cl", encoding="utf-8")

            with patch("offerquest.diagnostics.is_module_available", return_value=False):
                with patch(
                    "offerquest.diagnostics.get_ollama_status",
                    return_value={
                        "reachable": False,
                        "command_available": True,
                        "error": "offline",
                    },
                ):
                    report = build_doctor_report(ProjectState.from_root(root))

        web_check = next(check for check in report["checks"] if check["key"] == "web_dependencies")
        self.assertEqual(web_check["status"], "warn")
        self.assertIn("pip install -e .[web]", web_check["next_step"])

    def test_doctor_report_flags_missing_adzuna_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            init_workspace(root)
            (root / "data" / "candidate-cv.txt").write_text("cv", encoding="utf-8")
            (root / "data" / "base-cover-letter.txt").write_text("cl", encoding="utf-8")

            with patch(
                "offerquest.diagnostics.load_adzuna_credentials_status",
                return_value={
                    "has_effective_credentials": False,
                    "path": str(root / "missing.env"),
                },
            ):
                with patch(
                    "offerquest.diagnostics.get_ollama_status",
                    return_value={
                        "reachable": False,
                        "command_available": True,
                        "error": "offline",
                    },
                ):
                    report = build_doctor_report(ProjectState.from_root(root))

        adzuna_check = next(check for check in report["checks"] if check["key"] == "adzuna_credentials")
        self.assertEqual(adzuna_check["status"], "warn")
        self.assertIn("No Adzuna credentials", adzuna_check["summary"])

    def test_doctor_report_flags_unreachable_ollama(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            init_workspace(root)
            (root / "data" / "candidate-cv.txt").write_text("cv", encoding="utf-8")
            (root / "data" / "base-cover-letter.txt").write_text("cl", encoding="utf-8")

            with patch(
                "offerquest.diagnostics.get_ollama_status",
                return_value={
                    "reachable": False,
                    "command_available": True,
                    "error": "connection refused",
                },
            ):
                report = build_doctor_report(ProjectState.from_root(root))

        ollama_check = next(check for check in report["checks"] if check["key"] == "ollama")
        self.assertEqual(ollama_check["status"], "warn")
        self.assertIn("installed", ollama_check["summary"])
        self.assertIn("connection refused", ollama_check["detail"])

    def test_doctor_report_flags_missing_ollama_cli(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            init_workspace(root)

            with patch(
                "offerquest.diagnostics.get_ollama_status",
                return_value={
                    "reachable": False,
                    "command_available": False,
                    "error": "offline",
                },
            ):
                report = build_doctor_report(ProjectState.from_root(root))

        ollama_check = next(check for check in report["checks"] if check["key"] == "ollama")
        self.assertEqual(ollama_check["status"], "warn")
        self.assertIn("CLI was not found", ollama_check["summary"])

    def test_doctor_report_flags_running_ollama_without_models(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            init_workspace(root)

            with patch(
                "offerquest.diagnostics.get_ollama_status",
                return_value={
                    "reachable": True,
                    "command_available": True,
                    "models": [],
                    "missing_recommended_models": ["qwen3:8b"],
                },
            ):
                report = build_doctor_report(ProjectState.from_root(root))

        ollama_check = next(check for check in report["checks"] if check["key"] == "ollama")
        self.assertEqual(ollama_check["status"], "warn")
        self.assertIn("no models are installed", ollama_check["summary"])

    def test_render_doctor_report_is_human_readable(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            init_workspace(root)

            with patch(
                "offerquest.diagnostics.get_ollama_status",
                return_value={
                    "reachable": False,
                    "command_available": True,
                    "error": "offline",
                },
            ):
                report = build_doctor_report(ProjectState.from_root(root))

        rendered = render_doctor_report(report)
        self.assertIn("OfferQuest doctor", rendered)
        self.assertIn("Recommended next steps:", rendered)
        self.assertIn("Overall status: needs setup", rendered)


if __name__ == "__main__":
    unittest.main()
