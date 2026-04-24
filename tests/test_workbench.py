from __future__ import annotations

import json
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
    build_job_sources_view,
    build_latest_rankings_view,
    build_ollama_setup_view,
    build_profile_form_view,
    build_rerank_jobs_form_view,
    build_resume_tailored_draft_form_view,
    build_resume_tailoring_form_view,
    build_run_detail_view,
    build_runs_view,
    resolve_workspace_input_path,
    run_cover_letter_build,
    run_cover_letter_compare,
    run_job_source_delete,
    run_job_source_save,
    run_job_source_toggle,
    run_ollama_models_pull,
    run_profile_build,
    run_refresh_jobs_build,
    run_rerank_jobs_build,
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

            with patch(
                "offerquest.workbench.runs.build_doctor_report",
                return_value={
                    "workspace_root": str(root),
                    "checks": [],
                    "blocking_issue_count": 0,
                    "warning_count": 0,
                    "ready_for_first_run": True,
                    "recommended_next_steps": [],
                },
            ):
                dashboard = build_dashboard_view(state)

        self.assertTrue(dashboard["has_runs"])
        self.assertEqual(dashboard["stats"]["run_count"], 1)
        self.assertEqual(dashboard["workflow_counts"][0]["workflow"], "build-profile")

    def test_build_dashboard_view_includes_onboarding_for_empty_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            state = ProjectState.from_root(root)

            with patch(
                "offerquest.workbench.runs.build_doctor_report",
                return_value={
                    "workspace_root": str(root),
                    "checks": [
                        {
                            "key": "profile_sources",
                            "title": "Profile source documents",
                            "status": "warn",
                            "status_label": "WARN",
                            "status_css_class": "status-chip--warning",
                            "blocking": True,
                            "summary": "Missing CV and cover letter under `data/`.",
                            "detail": "No supported profile documents were found in `data/`.",
                            "next_step": "Add your own files under `data/`.",
                        }
                    ],
                    "blocking_issue_count": 1,
                    "warning_count": 1,
                    "ready_for_first_run": False,
                    "recommended_next_steps": [
                        "Add your CV and base cover letter under `data/`.",
                    ],
                },
            ):
                dashboard = build_dashboard_view(state)

        self.assertFalse(dashboard["has_runs"])
        self.assertTrue(dashboard["show_onboarding"])
        self.assertEqual(
            dashboard["doctor"]["recommended_next_steps"][0],
            "Add your CV and base cover letter under `data/`.",
        )

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

    def test_build_job_sources_view_prefills_refresh_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            jobs_dir = root / "jobs"
            jobs_dir.mkdir(parents=True, exist_ok=True)
            (jobs_dir / "sources.json").write_text(
                '{"sources": [{"name": "adzuna-reporting", "type": "adzuna", "what": "reporting analyst", "where": "Sydney", "output": "adzuna-reporting.jsonl"}]}',
                encoding="utf-8",
            )

            state = ProjectState.from_root(root)
            with patch.dict(
                os.environ,
                {"OFFERQUEST_ADZUNA_ENV_FILE": str(root / "missing-adzuna.env")},
                clear=True,
            ):
                view = build_job_sources_view(state)

        self.assertEqual(view["selected_refresh_config_path"], "jobs/sources.json")
        self.assertEqual(view["selected_refresh_output_dir"], "outputs/jobs")
        self.assertEqual(view["source_summary"]["source_count"], 1)
        self.assertEqual(view["source_summary"]["adzuna_count"], 1)
        self.assertTrue(view["credentials_panel_open"])

    def test_build_job_sources_view_prefills_edit_form(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            jobs_dir = root / "jobs"
            jobs_dir.mkdir(parents=True, exist_ok=True)
            (jobs_dir / "sources.json").write_text(
                '{"sources": [{"name": "manual", "type": "manual", "input_path": "jobs", "output": "manual.jsonl"}]}',
                encoding="utf-8",
            )

            state = ProjectState.from_root(root)
            view = build_job_sources_view(state, edit_source_index=0)

        self.assertEqual(view["source_form_mode"], "edit")
        self.assertEqual(view["source_form"]["name"], "manual")
        self.assertEqual(view["source_form"]["input_path"], "jobs")

    def test_build_ollama_setup_view_summarizes_ready_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state = ProjectState.from_root(tmpdir)

            with patch(
                "offerquest.workbench.ollama_setup.get_ollama_status",
                return_value={
                    "reachable": True,
                    "command_available": True,
                    "command_source": "repo_local_wrapper",
                    "has_models": True,
                    "models": [{"name": "qwen3:8b"}],
                    "missing_recommended_models": ["gemma3:12b", "qwen3:14b"],
                },
            ):
                with patch(
                    "offerquest.workbench.ollama_setup.detect_gpu_environment",
                    return_value={"summary": "NVIDIA GPU detected.", "detail": "Ready", "devices": []},
                ):
                    with patch(
                        "offerquest.workbench.ollama_setup.get_managed_ollama_server_state",
                        return_value={"running": False, "pid": None, "log_path": "log", "pid_path": "pid"},
                    ):
                        view = build_ollama_setup_view(state)

        self.assertEqual(view["status_label"], "Ready")
        self.assertEqual(view["installed_models"], ["qwen3:8b"])
        self.assertTrue(view["can_pull_models"])

    def test_run_ollama_models_pull_uses_streaming_api_and_refreshes_status(self) -> None:
        with patch(
            "offerquest.workbench.ollama_setup.get_ollama_status",
            side_effect=[
                {
                    "reachable": True,
                    "command_available": False,
                    "has_models": False,
                    "models": [],
                    "missing_recommended_models": ["qwen3:8b"],
                },
                {
                    "reachable": True,
                    "command_available": False,
                    "has_models": True,
                    "models": [{"name": "qwen3:8b"}],
                    "missing_recommended_models": [],
                },
            ],
        ):
            progress_events: list[dict[str, object]] = []
            def fake_pull_ollama_model(**kwargs):
                progress_callback = kwargs["progress_callback"]
                progress_callback(
                    {
                        "status": "pulling manifest",
                    }
                )
                progress_callback(
                    {
                        "status": "downloading",
                        "digest": "sha256:layer-1",
                        "completed": 50,
                        "total": 100,
                    }
                )
                progress_callback(
                    {
                        "status": "downloading",
                        "digest": "sha256:layer-1",
                        "completed": 100,
                        "total": 100,
                    }
                )

            with patch("offerquest.workbench.ollama_setup.pull_ollama_model", side_effect=fake_pull_ollama_model) as pull_mock:
                result = run_ollama_models_pull(
                    base_url="http://localhost:11434",
                    models=["qwen3:8b"],
                    progress_callback=progress_events.append,
                )

        self.assertEqual(result.pulled_models, ("qwen3:8b",))
        self.assertEqual(result.ollama_status["models"][0]["name"], "qwen3:8b")
        self.assertEqual(pull_mock.call_args.kwargs["model"], "qwen3:8b")
        self.assertEqual(pull_mock.call_args.kwargs["base_url"], "http://localhost:11434")
        self.assertIn("50 B of 100 B", progress_events[1]["detail"])
        self.assertEqual(progress_events[-1]["progress"], 100)

    def test_run_job_source_save_creates_source_and_syncs_merge_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            state = ProjectState.from_root(root)

            result = run_job_source_save(
                state,
                source_form_data={
                    "source_index": "",
                    "name": "greenhouse-example",
                    "type": "greenhouse",
                    "enabled": "true",
                    "output": "greenhouse-example.jsonl",
                    "what": "",
                    "where": "",
                    "country": "",
                    "pages": "",
                    "results_per_page": "",
                    "board_token": "example",
                    "input_path": "",
                },
            )

            saved_payload = json.loads((root / "jobs" / "sources.json").read_text(encoding="utf-8"))

        self.assertEqual(result.action, "created")
        self.assertEqual(result.source_name, "greenhouse-example")
        self.assertEqual(saved_payload["sources"][0]["board_token"], "example")
        self.assertEqual(saved_payload["merge"]["inputs"], ["greenhouse-example.jsonl"])

    def test_run_job_source_save_rejects_duplicate_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            jobs_dir = root / "jobs"
            jobs_dir.mkdir(parents=True, exist_ok=True)
            (jobs_dir / "sources.json").write_text(
                '{"sources": [{"name": "manual", "type": "manual", "input_path": "jobs", "output": "shared.jsonl"}]}',
                encoding="utf-8",
            )

            state = ProjectState.from_root(root)
            with self.assertRaisesRegex(ValueError, "Output filenames must be unique"):
                run_job_source_save(
                    state,
                    source_form_data={
                        "source_index": "",
                        "name": "manual-copy",
                        "type": "manual",
                        "enabled": "true",
                        "output": "shared.jsonl",
                        "what": "",
                        "where": "",
                        "country": "",
                        "pages": "",
                        "results_per_page": "",
                        "board_token": "",
                        "input_path": "jobs",
                    },
                )

    def test_run_job_source_toggle_and_delete_update_merge_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            jobs_dir = root / "jobs"
            jobs_dir.mkdir(parents=True, exist_ok=True)
            (jobs_dir / "sources.json").write_text(
                json.dumps(
                    {
                        "sources": [
                            {"name": "a", "type": "manual", "input_path": "jobs", "output": "a.jsonl"},
                            {"name": "b", "type": "manual", "input_path": "jobs", "output": "b.jsonl"},
                        ],
                        "merge": {"enabled": True, "inputs": ["a.jsonl", "b.jsonl"], "output": "all.jsonl"},
                        "summary_output": "refresh-summary.json",
                    }
                ),
                encoding="utf-8",
            )

            state = ProjectState.from_root(root)
            toggle_result = run_job_source_toggle(state, source_index=1)
            toggled_payload = json.loads((root / "jobs" / "sources.json").read_text(encoding="utf-8"))
            delete_result = run_job_source_delete(state, source_index=0)
            deleted_payload = json.loads((root / "jobs" / "sources.json").read_text(encoding="utf-8"))

        self.assertEqual(toggle_result.action, "disabled")
        self.assertEqual(toggled_payload["merge"]["inputs"], ["a.jsonl"])
        self.assertEqual(delete_result.action, "deleted")
        self.assertEqual(deleted_payload["sources"][0]["name"], "b")
        self.assertEqual(deleted_payload["merge"]["inputs"], [])

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

    def test_run_refresh_jobs_build_records_run_and_summary_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            jobs_dir = root / "jobs"
            outputs_jobs_dir = root / "outputs" / "jobs"
            jobs_dir.mkdir(parents=True, exist_ok=True)
            outputs_jobs_dir.mkdir(parents=True, exist_ok=True)
            config_path = jobs_dir / "sources.json"
            config_path.write_text('{"sources": []}', encoding="utf-8")

            refresh_summary = {
                "refreshed_at": "2026-04-23T12:00:00Z",
                "config_path": "jobs/sources.json",
                "output_dir": "outputs/jobs",
                "source_count": 2,
                "sources": [
                    {
                        "name": "adzuna-reporting",
                        "type": "adzuna",
                        "job_count": 12,
                        "output": "outputs/jobs/adzuna-reporting.jsonl",
                    },
                    {
                        "name": "manual",
                        "type": "manual",
                        "job_count": 3,
                        "output": "outputs/jobs/manual.jsonl",
                    },
                ],
                "merge_enabled": True,
                "merged_output": "outputs/jobs/all.jsonl",
                "merged_job_count": 15,
                "summary_output": "outputs/jobs/refresh-summary.json",
            }

            state = ProjectState.from_root(root)
            with patch(
                "offerquest.workbench.job_sources.refresh_job_sources",
                return_value=refresh_summary,
            ) as refresh_mock:
                result = run_refresh_jobs_build(
                    state,
                    config_path="jobs/sources.json",
                    output_dir="outputs/jobs",
                )

        self.assertEqual(refresh_mock.call_count, 1)
        self.assertEqual(result.summary["merged_job_count"], 15)
        self.assertEqual(result.summary_path_relative, "outputs/jobs/refresh-summary.json")
        self.assertEqual(result.merged_output_path_relative, "outputs/jobs/all.jsonl")
        self.assertEqual(result.run_manifest["workflow"], "refresh-jobs")
        self.assertEqual(len(result.run_manifest["artifacts"]), 4)

    def test_resolve_workspace_input_path_rejects_paths_outside_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            state = ProjectState.from_root(root)

            with self.assertRaisesRegex(ValueError, "Input path must stay inside the current workspace"):
                resolve_workspace_input_path(state, "../outside.txt")

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
            with patch(
                "offerquest.workbench.documents.get_ollama_status",
                return_value={
                    "reachable": False,
                    "command_available": True,
                    "models": [],
                    "missing_recommended_models": ["qwen3:8b"],
                },
            ):
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
            with patch(
                "offerquest.workbench.documents.get_ollama_status",
                return_value={
                    "reachable": True,
                    "command_available": True,
                    "models": [
                        {"name": "qwen3:8b"},
                        {"name": "gemma3:12b"},
                    ],
                    "missing_recommended_models": ["qwen3:14b"],
                },
            ):
                view = build_cover_letter_form_view(state, job_id="job-1", draft_mode="llm")

        self.assertEqual(view["selected_draft_mode"], "llm")
        self.assertEqual(view["selected_output"], "outputs/workbench/example-org-senior-data-analyst-llm.txt")
        self.assertEqual(view["selected_llm_model"], "qwen3:8b")
        self.assertEqual(view["available_llm_models"], ["qwen3:8b", "gemma3:12b"])
        self.assertFalse(view["ollama_needs_setup"])

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
            with patch(
                "offerquest.workbench.documents.get_ollama_status",
                return_value={
                    "reachable": False,
                    "command_available": True,
                    "models": [],
                    "missing_recommended_models": ["qwen3:8b"],
                },
            ):
                view = build_cover_letter_compare_view(state, job_id="job-1")

        self.assertEqual(view["selected_rule_based_output"], "outputs/workbench/example-org-senior-data-analyst.txt")
        self.assertEqual(view["selected_llm_output"], "outputs/workbench/example-org-senior-data-analyst-llm.txt")
        self.assertEqual(view["selected_llm_model"], "qwen3:8b")
        self.assertTrue(view["ollama_needs_setup"])

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

    def test_build_rerank_jobs_form_view_prefills_output(self) -> None:
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
            view = build_rerank_jobs_form_view(state, ranking_file="outputs/job-ranking.json")

        self.assertEqual(view["selected_ranking_file"], "outputs/job-ranking.json")
        self.assertEqual(view["selected_jobs_file"], "outputs/jobs/all.jsonl")
        self.assertEqual(view["selected_top_n"], "1")
        self.assertEqual(view["selected_output"], "outputs/job-ranking-reranked.json")
        self.assertEqual(len(view["selected_ranking_preview"]), 1)

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
                "offerquest.workbench.documents.generate_cover_letter_for_job_record_llm",
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
                "offerquest.workbench.documents.generate_cover_letter_for_job_record_llm",
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

    def test_run_rerank_jobs_build_writes_output_and_records_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            data_dir = root / "data"
            outputs_dir = root / "outputs"
            jobs_dir = outputs_dir / "jobs"
            data_dir.mkdir(parents=True, exist_ok=True)
            jobs_dir.mkdir(parents=True, exist_ok=True)

            (data_dir / "CV_sample.txt").write_text(
                "Jane Doe\nSydney, NSW, Australia\njane@example.com\nProfessional Summary\nSenior data analyst with SQL, Python, reporting, metadata, and healthcare research experience.\nCore Skills\nSQL\nPython\nReporting\nMetadata\nProfessional Experience\nExample Health\nSenior Reporting Analyst | 2025\nBuilt reporting workflows.\n",
                encoding="utf-8",
            )
            (data_dir / "CL_sample.txt").write_text(
                "Dear Hiring Team,\nI am writing to apply for the position of Senior Data Analyst.\nJane Doe\n",
                encoding="utf-8",
            )
            (jobs_dir / "all.jsonl").write_text(
                "\n".join(
                    [
                        '{"id": "job-1", "title": "Senior Data Analyst", "company": "Example Org", "location": "Sydney", "description_text": "SQL reporting role in analytics.", "source": "manual"}',
                        '{"id": "job-2", "title": "Data Officer", "company": "Example Org", "location": "Sydney", "description_text": "Required skills: SQL, reporting.", "source": "manual"}',
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            (outputs_dir / "job-ranking.json").write_text(
                '{"job_count": 2, "rankings": [{"job_id": "job-1", "job_title": "Senior Data Analyst", "company": "Example Org", "location": "Sydney", "score": 81}, {"job_id": "job-2", "job_title": "Data Officer", "company": "Example Org", "location": "Sydney", "score": 76}]}',
                encoding="utf-8",
            )

            state = ProjectState.from_root(root)
            result = run_rerank_jobs_build(
                state,
                ranking_file="outputs/job-ranking.json",
                cv_path="data/CV_sample.txt",
                base_cover_letter_path="data/CL_sample.txt",
                jobs_file="outputs/jobs/all.jsonl",
                top_n=2,
                output_path="outputs/job-ranking-reranked.json",
            )

            self.assertTrue(result.output_path.exists())
            self.assertEqual(result.run_manifest["workflow"], "rerank-jobs")
            self.assertEqual(result.payload["reranked_count"], 2)
            self.assertEqual(result.payload["rerank_strategy"], "ats-hybrid-v1")
            self.assertEqual(result.payload["rankings"][0]["rerank_rank"], 1)


if __name__ == "__main__":
    unittest.main()
