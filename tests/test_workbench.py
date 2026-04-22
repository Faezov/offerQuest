from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from offerquest.extractors import read_document_text
from offerquest.workbench import (
    build_artifact_preview,
    build_cover_letter_compare_view,
    build_cover_letter_form_view,
    build_dashboard_view,
    build_latest_rankings_view,
    build_profile_form_view,
    build_resume_tailored_draft_form_view,
    build_resume_tailoring_form_view,
    build_run_detail_view,
    build_runs_view,
    run_cover_letter_compare,
    run_cover_letter_build,
    run_profile_build,
    run_resume_tailored_draft_build,
    run_resume_tailoring_plan_build,
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

    def test_build_latest_rankings_view_uses_latest_ranking_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            outputs_dir = root / "outputs"
            outputs_dir.mkdir(parents=True, exist_ok=True)
            older = outputs_dir / "job-ranking-old.json"
            latest = outputs_dir / "job-ranking.json"
            older.write_text(
                '{"job_count": 1, "rankings": [{"job_title": "Old Role", "company": "Old Co", "location": "Sydney", "score": 70}]}',
                encoding="utf-8",
            )
            latest.write_text(
                '{"job_count": 2, "rankings": [{"job_title": "Fresh Role", "company": "Fresh Co", "location": "Melbourne", "score": 92, "url": "https://example.com"}, {"job_title": "Second Role", "company": "Next Co", "location": "Sydney", "score": 84}]}',
                encoding="utf-8",
            )
            os.utime(older, (1_710_000_000, 1_710_000_000))
            os.utime(latest, (1_720_000_000, 1_720_000_000))

            state = ProjectState.from_root(root)
            view = build_latest_rankings_view(state)

        self.assertTrue(view["has_ranking"])
        self.assertEqual(view["ranking_file"], "outputs/job-ranking.json")
        self.assertEqual(view["top_rankings"][0]["job_title"], "Fresh Role")

    def test_build_cover_letter_form_view_prefills_selected_job(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            data_dir = root / "data"
            outputs_dir = root / "outputs"
            jobs_dir = outputs_dir / "jobs"
            data_dir.mkdir(parents=True, exist_ok=True)
            jobs_dir.mkdir(parents=True, exist_ok=True)
            (data_dir / "CV_sample.txt").write_text("cv", encoding="utf-8")
            (data_dir / "CL_sample.txt").write_text("cl", encoding="utf-8")
            (jobs_dir / "all.jsonl").write_text(
                '{"id": "job-1", "title": "Senior Data Analyst", "company": "Example Org", "location": "Sydney", "description_text": "SQL reporting role"}\n',
                encoding="utf-8",
            )
            (outputs_dir / "job-ranking.json").write_text(
                '{"job_count": 1, "rankings": [{"job_id": "job-1", "job_title": "Senior Data Analyst", "company": "Example Org", "location": "Sydney", "score": 95}]}',
                encoding="utf-8",
            )

            state = ProjectState.from_root(root)
            view = build_cover_letter_form_view(state, job_id="job-1")

        self.assertEqual(view["selected_job"]["job_id"], "job-1")
        self.assertEqual(view["selected_jobs_file"], "outputs/jobs/all.jsonl")

    def test_build_cover_letter_form_view_prefills_llm_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            data_dir = root / "data"
            outputs_dir = root / "outputs"
            jobs_dir = outputs_dir / "jobs"
            data_dir.mkdir(parents=True, exist_ok=True)
            jobs_dir.mkdir(parents=True, exist_ok=True)
            (data_dir / "CV_sample.txt").write_text("cv", encoding="utf-8")
            (data_dir / "CL_sample.txt").write_text("cl", encoding="utf-8")
            (jobs_dir / "all.jsonl").write_text(
                '{"id": "job-1", "title": "Senior Data Analyst", "company": "Example Org", "location": "Sydney", "description_text": "SQL reporting role"}\n',
                encoding="utf-8",
            )
            (outputs_dir / "job-ranking.json").write_text(
                '{"job_count": 1, "rankings": [{"job_id": "job-1", "job_title": "Senior Data Analyst", "company": "Example Org", "location": "Sydney", "score": 95}]}',
                encoding="utf-8",
            )

            state = ProjectState.from_root(root)
            view = build_cover_letter_form_view(state, job_id="job-1", draft_mode="llm")

        self.assertEqual(view["selected_draft_mode"], "llm")
        self.assertEqual(view["selected_output"], "outputs/workbench/example-org-senior-data-analyst-llm.txt")
        self.assertEqual(view["selected_llm_model"], "qwen3:8b")

    def test_build_cover_letter_compare_view_prefills_both_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            data_dir = root / "data"
            outputs_dir = root / "outputs"
            jobs_dir = outputs_dir / "jobs"
            data_dir.mkdir(parents=True, exist_ok=True)
            jobs_dir.mkdir(parents=True, exist_ok=True)
            (data_dir / "CV_sample.txt").write_text("cv", encoding="utf-8")
            (data_dir / "CL_sample.txt").write_text("cl", encoding="utf-8")
            (jobs_dir / "all.jsonl").write_text(
                '{"id": "job-1", "title": "Senior Data Analyst", "company": "Example Org", "location": "Sydney", "description_text": "SQL reporting role"}\n',
                encoding="utf-8",
            )
            (outputs_dir / "job-ranking.json").write_text(
                '{"job_count": 1, "rankings": [{"job_id": "job-1", "job_title": "Senior Data Analyst", "company": "Example Org", "location": "Sydney", "score": 95}]}',
                encoding="utf-8",
            )

            state = ProjectState.from_root(root)
            view = build_cover_letter_compare_view(state, job_id="job-1")

        self.assertEqual(view["selected_rule_based_output"], "outputs/workbench/example-org-senior-data-analyst.txt")
        self.assertEqual(view["selected_llm_output"], "outputs/workbench/example-org-senior-data-analyst-llm.txt")
        self.assertEqual(view["selected_llm_model"], "qwen3:8b")

    def test_build_resume_tailoring_form_view_prefills_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            data_dir = root / "data"
            outputs_dir = root / "outputs"
            jobs_dir = outputs_dir / "jobs"
            data_dir.mkdir(parents=True, exist_ok=True)
            jobs_dir.mkdir(parents=True, exist_ok=True)
            (data_dir / "CV_sample.txt").write_text("cv", encoding="utf-8")
            (data_dir / "CL_sample.txt").write_text("cl", encoding="utf-8")
            (jobs_dir / "all.jsonl").write_text(
                '{"id": "job-1", "title": "Senior Data Analyst", "company": "Example Org", "location": "Sydney", "description_text": "SQL reporting role"}\n',
                encoding="utf-8",
            )
            (outputs_dir / "job-ranking.json").write_text(
                '{"job_count": 1, "rankings": [{"job_id": "job-1", "job_title": "Senior Data Analyst", "company": "Example Org", "location": "Sydney", "score": 95}]}',
                encoding="utf-8",
            )

            state = ProjectState.from_root(root)
            view = build_resume_tailoring_form_view(state, job_id="job-1")

        self.assertEqual(view["selected_output"], "outputs/workbench/example-org-senior-data-analyst-resume-plan.json")
        self.assertEqual(view["selected_jobs_file"], "outputs/jobs/all.jsonl")

    def test_build_resume_tailored_draft_form_view_prefills_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            data_dir = root / "data"
            outputs_dir = root / "outputs"
            jobs_dir = outputs_dir / "jobs"
            data_dir.mkdir(parents=True, exist_ok=True)
            jobs_dir.mkdir(parents=True, exist_ok=True)
            (data_dir / "CV_sample.txt").write_text("cv", encoding="utf-8")
            (data_dir / "CL_sample.txt").write_text("cl", encoding="utf-8")
            (jobs_dir / "all.jsonl").write_text(
                '{"id": "job-1", "title": "Senior Data Analyst", "company": "Example Org", "location": "Sydney", "description_text": "SQL reporting role"}\n',
                encoding="utf-8",
            )
            (outputs_dir / "job-ranking.json").write_text(
                '{"job_count": 1, "rankings": [{"job_id": "job-1", "job_title": "Senior Data Analyst", "company": "Example Org", "location": "Sydney", "score": 95}]}',
                encoding="utf-8",
            )

            state = ProjectState.from_root(root)
            view = build_resume_tailored_draft_form_view(state, job_id="job-1")

        self.assertEqual(view["selected_output"], "outputs/workbench/example-org-senior-data-analyst-tailored-resume.txt")
        self.assertEqual(view["selected_jobs_file"], "outputs/jobs/all.jsonl")
        self.assertTrue(view["selected_export_docx"])
        self.assertEqual(view["selected_docx_output"], "outputs/workbench/example-org-senior-data-analyst-tailored-resume.docx")

    def test_run_cover_letter_build_writes_output_and_records_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            data_dir = root / "data"
            jobs_dir = root / "outputs" / "jobs"
            data_dir.mkdir(parents=True, exist_ok=True)
            jobs_dir.mkdir(parents=True, exist_ok=True)

            cv_path = data_dir / "CV_sample.txt"
            cl_path = data_dir / "CL_sample.txt"
            jobs_path = jobs_dir / "all.jsonl"

            cv_path.write_text(
                "Jane Doe\nMelbourne, VIC, Australia\njane@example.com\nProfessional Summary\nSenior analyst with SQL, Python, and reporting experience.\nCore Skills\nSQL\nPython\nReporting\nProfessional Experience\nExample Org\nSenior Reporting Analyst | 2025\n",
                encoding="utf-8",
            )
            cl_path.write_text(
                "Dear Hiring Team,\nI am writing to apply for the position of Senior Data Analyst.\nWith best regards,\nJane Doe\n",
                encoding="utf-8",
            )
            jobs_path.write_text(
                '{"id": "job-1", "title": "Senior Data Analyst", "company": "Example Org", "location": "Sydney", "description_text": "Senior Data Analyst\\nExample Org, Sydney\\nRequired skills: SQL, reporting, dashboards.\\n", "url": "https://example.com/job-1"}\n',
                encoding="utf-8",
            )

            state = ProjectState.from_root(root)
            result = run_cover_letter_build(
                state,
                draft_mode="rule_based",
                cv_path="data/CV_sample.txt",
                base_cover_letter_path="data/CL_sample.txt",
                jobs_file="outputs/jobs/all.jsonl",
                job_id="job-1",
                output_path="outputs/workbench/example-org-senior-data-analyst.txt",
            )

            self.assertTrue(result.output_path.exists())
            self.assertIn("Senior Data Analyst", result.payload["cover_letter_text"])
            self.assertEqual(result.run_manifest["workflow"], "generate-cover-letter")

    def test_run_cover_letter_build_llm_uses_ollama_generator_and_records_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            data_dir = root / "data"
            jobs_dir = root / "outputs" / "jobs"
            data_dir.mkdir(parents=True, exist_ok=True)
            jobs_dir.mkdir(parents=True, exist_ok=True)

            cv_path = data_dir / "CV_sample.txt"
            cl_path = data_dir / "CL_sample.txt"
            jobs_path = jobs_dir / "all.jsonl"

            cv_path.write_text(
                "Jane Doe\nMelbourne, VIC, Australia\njane@example.com\nProfessional Summary\nSenior analyst with SQL, Python, and reporting experience.\n",
                encoding="utf-8",
            )
            cl_path.write_text(
                "Dear Hiring Team,\nI am writing to apply for the position of Senior Data Analyst.\nWith best regards,\nJane Doe\n",
                encoding="utf-8",
            )
            jobs_path.write_text(
                '{"id": "job-1", "title": "Senior Data Analyst", "company": "Example Org", "location": "Sydney", "description_text": "Senior Data Analyst\\nExample Org, Sydney\\nRequired skills: SQL, reporting, dashboards.\\n", "url": "https://example.com/job-1"}\n',
                encoding="utf-8",
            )

            state = ProjectState.from_root(root)
            with patch(
                "offerquest.workbench.generate_cover_letter_for_job_record_llm",
                return_value={
                    "job_id": "job-1",
                    "job_title": "Senior Data Analyst",
                    "company": "Example Org",
                    "location": "Sydney",
                    "job_url": "https://example.com/job-1",
                    "cover_letter_text": "Dear Hiring Team,\n\nLLM draft.\n",
                    "resume_headline": "Senior Data Analyst",
                    "employer_specific_focus": ["Reporting reliability"],
                    "evidence_used": ["SQL and Python automation"],
                    "caution_flags": [],
                    "ats_score": 88,
                    "matched_keywords": ["SQL", "reporting"],
                    "missing_keywords": ["dashboards"],
                    "llm_provider": "ollama",
                    "llm_model": "qwen3:14b",
                },
            ) as llm_generator:
                result = run_cover_letter_build(
                    state,
                    draft_mode="llm",
                    cv_path="data/CV_sample.txt",
                    base_cover_letter_path="data/CL_sample.txt",
                    jobs_file="outputs/jobs/all.jsonl",
                    job_id="job-1",
                    output_path="outputs/workbench/example-org-senior-data-analyst-llm.txt",
                    llm_model="qwen3:14b",
                    llm_base_url="http://localhost:11434",
                    llm_timeout_seconds=240,
                )

                self.assertTrue(result.output_path.exists())
                self.assertEqual(result.draft_mode, "llm")
                self.assertEqual(result.run_manifest["workflow"], "generate-cover-letter-llm")
                self.assertEqual(result.run_manifest["artifacts"][0]["kind"], "llm_cover_letter")
                self.assertEqual(result.run_manifest["metadata"]["llm_model"], "qwen3:14b")
                self.assertIn("LLM draft.", result.output_path.read_text(encoding="utf-8"))
                llm_generator.assert_called_once()
                call_args = llm_generator.call_args
                self.assertEqual(call_args.args[0], root / "data" / "CV_sample.txt")
                self.assertEqual(call_args.args[1]["id"], "job-1")
                self.assertEqual(call_args.kwargs["base_cover_letter_path"], root / "data" / "CL_sample.txt")
                self.assertEqual(call_args.kwargs["model"], "qwen3:14b")
                self.assertEqual(call_args.kwargs["base_url"], "http://localhost:11434")
                self.assertEqual(call_args.kwargs["timeout_seconds"], 240)

    def test_run_cover_letter_compare_writes_both_outputs_and_records_single_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            data_dir = root / "data"
            jobs_dir = root / "outputs" / "jobs"
            data_dir.mkdir(parents=True, exist_ok=True)
            jobs_dir.mkdir(parents=True, exist_ok=True)

            cv_path = data_dir / "CV_sample.txt"
            cl_path = data_dir / "CL_sample.txt"
            jobs_path = jobs_dir / "all.jsonl"

            cv_path.write_text(
                "Jane Doe\nMelbourne, VIC, Australia\njane@example.com\nProfessional Summary\nSenior analyst with SQL, Python, and reporting experience.\n",
                encoding="utf-8",
            )
            cl_path.write_text(
                "Dear Hiring Team,\nI am writing to apply for the position of Senior Data Analyst.\nWith best regards,\nJane Doe\n",
                encoding="utf-8",
            )
            jobs_path.write_text(
                '{"id": "job-1", "title": "Senior Data Analyst", "company": "Example Org", "location": "Sydney", "description_text": "Senior Data Analyst\\nExample Org, Sydney\\nRequired skills: SQL, reporting, dashboards.\\n", "url": "https://example.com/job-1"}\n',
                encoding="utf-8",
            )

            state = ProjectState.from_root(root)
            with patch(
                "offerquest.workbench.generate_cover_letter_for_job_record_llm",
                return_value={
                    "job_id": "job-1",
                    "job_title": "Senior Data Analyst",
                    "company": "Example Org",
                    "location": "Sydney",
                    "job_url": "https://example.com/job-1",
                    "cover_letter_text": "Dear Hiring Team,\n\nLLM comparison draft.\n",
                    "resume_headline": "Senior Data Analyst",
                    "employer_specific_focus": ["Reporting reliability"],
                    "evidence_used": ["SQL and Python automation"],
                    "caution_flags": [],
                    "ats_score": 88,
                    "matched_keywords": ["SQL", "reporting"],
                    "missing_keywords": ["dashboards"],
                    "llm_provider": "ollama",
                    "llm_model": "qwen3:14b",
                },
            ) as llm_generator:
                result = run_cover_letter_compare(
                    state,
                    cv_path="data/CV_sample.txt",
                    base_cover_letter_path="data/CL_sample.txt",
                    jobs_file="outputs/jobs/all.jsonl",
                    job_id="job-1",
                    rule_based_output_path="outputs/workbench/example-org-senior-data-analyst.txt",
                    llm_output_path="outputs/workbench/example-org-senior-data-analyst-llm.txt",
                    llm_model="qwen3:14b",
                    llm_base_url="http://localhost:11434",
                    llm_timeout_seconds=240,
                )

                self.assertTrue(result.rule_based.output_path.exists())
                self.assertTrue(result.llm.output_path.exists())
                self.assertEqual(result.run_manifest["workflow"], "compare-cover-letter-drafts")
                self.assertEqual(len(result.run_manifest["artifacts"]), 2)
                self.assertEqual(result.run_manifest["metadata"]["llm_model"], "qwen3:14b")
                self.assertIn("Senior Data Analyst", result.rule_based.payload["cover_letter_text"])
                self.assertIn("LLM comparison draft.", result.llm.output_path.read_text(encoding="utf-8"))
                llm_generator.assert_called_once()

    def test_run_cover_letter_compare_requires_distinct_output_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            data_dir = root / "data"
            jobs_dir = root / "outputs" / "jobs"
            data_dir.mkdir(parents=True, exist_ok=True)
            jobs_dir.mkdir(parents=True, exist_ok=True)

            (data_dir / "CV_sample.txt").write_text(
                "Jane Doe\nMelbourne, VIC, Australia\njane@example.com\nProfessional Summary\nSenior analyst.\n",
                encoding="utf-8",
            )
            (data_dir / "CL_sample.txt").write_text(
                "Dear Hiring Team,\nExample.\nJane Doe\n",
                encoding="utf-8",
            )
            (jobs_dir / "all.jsonl").write_text(
                '{"id": "job-1", "title": "Senior Data Analyst", "company": "Example Org", "location": "Sydney", "description_text": "SQL reporting role", "url": "https://example.com/job-1"}\n',
                encoding="utf-8",
            )

            state = ProjectState.from_root(root)

            with self.assertRaisesRegex(ValueError, "must be different"):
                run_cover_letter_compare(
                    state,
                    cv_path="data/CV_sample.txt",
                    base_cover_letter_path="data/CL_sample.txt",
                    jobs_file="outputs/jobs/all.jsonl",
                    job_id="job-1",
                    rule_based_output_path="outputs/workbench/shared.txt",
                    llm_output_path="outputs/workbench/shared.txt",
                )

    def test_run_resume_tailoring_plan_build_writes_output_and_records_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            data_dir = root / "data"
            jobs_dir = root / "outputs" / "jobs"
            data_dir.mkdir(parents=True, exist_ok=True)
            jobs_dir.mkdir(parents=True, exist_ok=True)

            (data_dir / "CV_sample.txt").write_text(
                "Jane Doe\nMelbourne, VIC, Australia\njane@example.com\nProfessional Summary\nSenior data analyst with SQL, Python, reporting, and metadata experience.\nCore Skills\nSQL\nPython\nReporting\nMetadata\nProfessional Experience\nExample Org\nSenior Reporting Analyst | 2025\nBuilt reporting workflows.\n",
                encoding="utf-8",
            )
            (data_dir / "CL_sample.txt").write_text(
                "Dear Hiring Team,\nI am writing to apply for the position of Senior Data Analyst.\nJane Doe\n",
                encoding="utf-8",
            )
            (jobs_dir / "all.jsonl").write_text(
                '{"id": "job-1", "title": "Senior Data Analyst", "company": "Example Org", "location": "Sydney", "description_text": "Senior Data Analyst\\nExample Org, Sydney\\nRequired skills: SQL, Python, Power BI, reporting.\\n", "url": "https://example.com/job-1"}\n',
                encoding="utf-8",
            )

            state = ProjectState.from_root(root)
            result = run_resume_tailoring_plan_build(
                state,
                cv_path="data/CV_sample.txt",
                base_cover_letter_path="data/CL_sample.txt",
                jobs_file="outputs/jobs/all.jsonl",
                job_id="job-1",
                output_path="outputs/workbench/example-org-senior-data-analyst-resume-plan.json",
            )

            self.assertTrue(result.output_path.exists())
            self.assertEqual(result.run_manifest["workflow"], "tailor-cv-plan")
            self.assertEqual(result.plan["job_id"], "job-1")
            self.assertIn("Power BI", result.plan["keyword_plan"]["missing_keywords"])

    def test_run_resume_tailored_draft_build_writes_output_and_records_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            data_dir = root / "data"
            jobs_dir = root / "outputs" / "jobs"
            data_dir.mkdir(parents=True, exist_ok=True)
            jobs_dir.mkdir(parents=True, exist_ok=True)

            (data_dir / "CV_sample.txt").write_text(
                "Jane Doe\nMelbourne, VIC, Australia\njane@example.com\nProfessional Summary\nSenior data analyst with SQL, Python, reporting, and metadata experience.\nCore Skills\nSQL\nPython\nReporting\nMetadata\nProfessional Experience\nExample Org\nSenior Reporting Analyst | 2025\nBuilt reporting workflows.\n",
                encoding="utf-8",
            )
            (data_dir / "CL_sample.txt").write_text(
                "Dear Hiring Team,\nI am writing to apply for the position of Senior Data Analyst.\nI have also supported automation work in analyst environments.\nJane Doe\n",
                encoding="utf-8",
            )
            (jobs_dir / "all.jsonl").write_text(
                '{"id": "job-1", "title": "Senior Data Analyst", "company": "Example Org", "location": "Sydney", "description_text": "Senior Data Analyst\\nExample Org, Sydney\\nRequired skills: SQL, Python, reporting, automation.\\n", "url": "https://example.com/job-1"}\n',
                encoding="utf-8",
            )

            state = ProjectState.from_root(root)
            result = run_resume_tailored_draft_build(
                state,
                cv_path="data/CV_sample.txt",
                base_cover_letter_path="data/CL_sample.txt",
                jobs_file="outputs/jobs/all.jsonl",
                job_id="job-1",
                output_path="outputs/workbench/example-org-senior-data-analyst-tailored-resume.txt",
                export_docx=True,
                docx_output_path="outputs/workbench/example-org-senior-data-analyst-tailored-resume.docx",
            )

            self.assertTrue(result.output_path.exists())
            self.assertTrue(result.analysis_output_path.exists())
            self.assertIsNotNone(result.docx_output_path)
            self.assertTrue(result.docx_output_path.exists())
            self.assertEqual(result.run_manifest["workflow"], "tailor-cv-draft")
            self.assertEqual(len(result.run_manifest["artifacts"]), 3)
            self.assertIn("Automation", result.comparison["section_changes"]["skills_after"])
            self.assertIn("Senior Data Analyst", result.output_path.read_text(encoding="utf-8"))
            self.assertIn("Senior Data Analyst", read_document_text(result.docx_output_path))


if __name__ == "__main__":
    unittest.main()
