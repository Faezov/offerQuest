from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from offerquest.workbench import (
    build_artifact_preview,
    build_dashboard_view,
    build_profile_form_view,
    build_run_detail_view,
    build_runs_view,
    run_profile_build,
)
from offerquest.workspace import ProjectState


class WorkbenchTests(unittest.TestCase):
    def test_build_dashboard_view_summarizes_runs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            state = ProjectState.from_root(root)

            profile_path = root / "outputs" / "profile.json"
            profile_path.parent.mkdir(parents=True, exist_ok=True)
            profile_path.write_text("{}", encoding="utf-8")

            state.record_run(
                "build-profile",
                artifacts=[{"kind": "profile", "path": profile_path}],
                metadata={"source": "cv"},
                label="profile",
            )

            dashboard = build_dashboard_view(state)

        self.assertTrue(dashboard["has_runs"])
        self.assertEqual(dashboard["stats"]["run_count"], 1)
        self.assertEqual(dashboard["workflow_counts"][0]["workflow"], "build-profile")

    def test_build_run_detail_view_enriches_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            state = ProjectState.from_root(root)

            report_path = root / "outputs" / "ats.json"
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text('{"ok": true}', encoding="utf-8")

            manifest = state.record_run(
                "ats-check",
                artifacts=[{"kind": "ats_report", "path": report_path}],
                metadata={"job_title": "Data Analyst"},
                label="ats",
            )

            detail = build_run_detail_view(state, manifest["id"])

        self.assertIsNotNone(detail)
        self.assertEqual(detail["artifact_count"], 1)
        self.assertTrue(detail["artifacts"][0]["exists"])
        self.assertEqual(detail["artifacts"][0]["filename"], "ats.json")

    def test_build_artifact_preview_reads_text_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            state = ProjectState.from_root(root)

            text_path = root / "outputs" / "letter.txt"
            text_path.parent.mkdir(parents=True, exist_ok=True)
            text_path.write_text("Dear Hiring Team,\n\nExample.\n", encoding="utf-8")

            manifest = state.record_run(
                "generate-cover-letter",
                artifacts=[{"kind": "cover_letter", "path": text_path}],
                label="letter",
            )

            preview = build_artifact_preview(state, manifest["id"], 0)

        self.assertIsNotNone(preview)
        self.assertEqual(preview.preview_kind, "text")
        self.assertIn("Dear Hiring Team", preview.content or "")

    def test_build_runs_view_handles_empty_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state = ProjectState.from_root(tmpdir)

            runs_view = build_runs_view(state)

        self.assertFalse(runs_view["has_runs"])
        self.assertEqual(runs_view["run_count"], 0)

    def test_build_profile_form_view_lists_workspace_documents(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            data_dir = root / "data"
            data_dir.mkdir(parents=True, exist_ok=True)
            (data_dir / "CV_sample.docx").write_text("cv", encoding="utf-8")
            (data_dir / "CL_sample.doc").write_text("cl", encoding="utf-8")

            state = ProjectState.from_root(root)
            view = build_profile_form_view(state)

        self.assertTrue(view["has_documents"])
        self.assertIn("data/CV_sample.docx", view["documents"])
        self.assertEqual(view["selected_cv"], "data/CV_sample.docx")

    def test_run_profile_build_writes_output_and_records_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            data_dir = root / "data"
            data_dir.mkdir(parents=True, exist_ok=True)
            cv_path = data_dir / "CV_sample.txt"
            cl_path = data_dir / "CL_sample.txt"
            cv_path.write_text(
                "Jane Doe\nMelbourne, VIC, Australia\njane@example.com\nProfessional Summary\nSenior analyst with SQL and reporting experience.\n",
                encoding="utf-8",
            )
            cl_path.write_text(
                "Dear Hiring Team,\nI am writing to apply for the position of Senior Data Analyst.\nJane Doe\n",
                encoding="utf-8",
            )

            state = ProjectState.from_root(root)
            result = run_profile_build(
                state,
                cv_path="data/CV_sample.txt",
                cover_letter_path="data/CL_sample.txt",
                output_path="outputs/profiles/jane-profile.json",
            )

            self.assertTrue(result.output_path.exists())
            self.assertEqual(result.profile["name"], "Jane Doe")
            self.assertEqual(result.run_manifest["workflow"], "build-profile")


if __name__ == "__main__":
    unittest.main()
