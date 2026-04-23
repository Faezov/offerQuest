import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from offerquest.web.app import validate_required_form_fields


class WebAppTests(unittest.TestCase):
    def test_validate_required_form_fields_formats_missing_labels(self) -> None:
        error = validate_required_form_fields(
            {
                "cv_path": "data/cv.txt",
                "jobs_file": "",
                "output_path": "",
            },
            required=[
                ("cv_path", "CV file"),
                ("jobs_file", "Jobs file"),
                ("output_path", "Output path"),
            ],
        )

        self.assertEqual(error, "Jobs file and Output path are required.")

    def test_dashboard_route_returns_html(self) -> None:
        try:
            from fastapi.testclient import TestClient
        except (ImportError, RuntimeError) as exc:
            self.skipTest(f"fastapi test client unavailable: {exc}")

        from offerquest.web.app import create_app

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            app = create_app(workspace_root=root)
            client = TestClient(app)

            with patch(
                "offerquest.web.app.build_dashboard_view",
                return_value={
                    "stats": {"run_count": 0, "artifact_count": 0, "workflow_count": 0},
                    "workflow_counts": [],
                    "recent_runs": [],
                    "has_runs": False,
                    "show_onboarding": True,
                    "doctor": {"checks": [], "recommended_next_steps": []},
                },
            ):
                response = client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("OfferQuest Local Workbench", response.text)

    def test_dashboard_route_shows_start_here_checklist_for_empty_workspace(self) -> None:
        try:
            from fastapi.testclient import TestClient
        except (ImportError, RuntimeError) as exc:
            self.skipTest(f"fastapi test client unavailable: {exc}")

        from offerquest.web.app import create_app

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            app = create_app(workspace_root=root)
            client = TestClient(app)

            with patch(
                "offerquest.web.app.build_dashboard_view",
                return_value={
                    "stats": {"run_count": 0, "artifact_count": 0, "workflow_count": 0},
                    "workflow_counts": [],
                    "recent_runs": [],
                    "has_runs": False,
                    "show_onboarding": True,
                    "doctor": {
                        "checks": [
                            {
                                "title": "Profile source documents",
                                "status_label": "WARN",
                                "status_css_class": "status-chip--warning",
                                "summary": "Missing CV and cover letter under `data/`.",
                                "detail": "No supported profile documents were found in `data/`.",
                                "next_step": "Add your own files under `data/`.",
                            }
                        ],
                        "recommended_next_steps": [
                            "Add your CV and base cover letter under `data/`.",
                            "Start the workbench with `offerquest-workbench --root .`.",
                        ],
                    },
                },
            ):
                response = client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Start Here", response.text)
        self.assertIn("Workspace Checks", response.text)
        self.assertIn("Add your CV and base cover letter under", response.text)

    def test_build_profile_page_renders(self) -> None:
        try:
            from fastapi.testclient import TestClient
        except (ImportError, RuntimeError) as exc:
            self.skipTest(f"fastapi test client unavailable: {exc}")

        from offerquest.web.app import create_app

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            data_dir = root / "data"
            data_dir.mkdir(parents=True, exist_ok=True)
            (data_dir / "CV_sample.txt").write_text("cv", encoding="utf-8")
            (data_dir / "CL_sample.txt").write_text("cl", encoding="utf-8")
            app = create_app(workspace_root=root)
            client = TestClient(app)

            response = client.get("/build-profile")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Build Candidate Profile", response.text)

    def test_resume_tailoring_page_renders(self) -> None:
        try:
            from fastapi.testclient import TestClient
        except (ImportError, RuntimeError) as exc:
            self.skipTest(f"fastapi test client unavailable: {exc}")

        from offerquest.web.app import create_app

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
            app = create_app(workspace_root=root)
            client = TestClient(app)

            response = client.get("/cv-tailoring/new?job_id=job-1")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Build CV Tailoring Plan", response.text)

    def test_resume_tailored_draft_page_renders(self) -> None:
        try:
            from fastapi.testclient import TestClient
        except (ImportError, RuntimeError) as exc:
            self.skipTest(f"fastapi test client unavailable: {exc}")

        from offerquest.web.app import create_app

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
            app = create_app(workspace_root=root)
            client = TestClient(app)

            response = client.get("/cv-tailoring/draft/new?job_id=job-1")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Build Tailored CV Draft", response.text)
        self.assertIn("Also export ATS-safe DOCX", response.text)

    def test_rankings_page_renders(self) -> None:
        try:
            from fastapi.testclient import TestClient
        except (ImportError, RuntimeError) as exc:
            self.skipTest(f"fastapi test client unavailable: {exc}")

        from offerquest.web.app import create_app

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            outputs_dir = root / "outputs"
            outputs_dir.mkdir(parents=True, exist_ok=True)
            (outputs_dir / "job-ranking.json").write_text(
                '{"job_count": 1, "rankings": [{"job_title": "Senior Data Analyst", "company": "Example Org", "location": "Sydney", "score": 95}]}',
                encoding="utf-8",
            )
            app = create_app(workspace_root=root)
            client = TestClient(app)

            response = client.get("/rankings")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Latest Ranking Output", response.text)
        self.assertIn("Rerank Top Jobs", response.text)

    def test_job_sources_page_renders(self) -> None:
        try:
            from fastapi.testclient import TestClient
        except (ImportError, RuntimeError) as exc:
            self.skipTest(f"fastapi test client unavailable: {exc}")

        from offerquest.web.app import create_app

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            jobs_dir = root / "jobs"
            jobs_dir.mkdir(parents=True, exist_ok=True)
            (jobs_dir / "sources.json").write_text(
                '{"sources": [{"name": "adzuna-reporting", "type": "adzuna", "what": "reporting analyst", "where": "Sydney", "output": "adzuna-reporting.jsonl"}]}',
                encoding="utf-8",
            )
            app = create_app(workspace_root=root)
            client = TestClient(app)

            response = client.get("/job-sources")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Credentials and Provider Guide", response.text)
        self.assertIn("Configured Job Streams", response.text)
        self.assertIn("Board token, not a private API key", response.text)

    def test_job_sources_submit_saves_credentials_file(self) -> None:
        try:
            from fastapi.testclient import TestClient
        except (ImportError, RuntimeError) as exc:
            self.skipTest(f"fastapi test client unavailable: {exc}")

        from offerquest.web.app import create_app

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            env_path = Path(tmpdir) / "adzuna.env"
            app = create_app(workspace_root=root)
            client = TestClient(app)

            with patch.dict(
                "os.environ",
                {"OFFERQUEST_ADZUNA_ENV_FILE": str(env_path)},
                clear=False,
            ):
                response = client.post(
                    "/job-sources",
                    data={
                        "app_id": "saved-app-id",
                        "app_key": "saved-app-key",
                    },
                )

            saved_text = env_path.read_text(encoding="utf-8")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Saved credentials file", response.text)
        self.assertIn("saved-app-id", saved_text)
        self.assertIn("saved-app-key", saved_text)

    def test_job_sources_submit_refreshes_jobs(self) -> None:
        try:
            from fastapi.testclient import TestClient
        except (ImportError, RuntimeError) as exc:
            self.skipTest(f"fastapi test client unavailable: {exc}")

        from offerquest.web.app import create_app
        from offerquest.workbench import BuildRefreshJobsResult

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            jobs_dir = root / "jobs"
            jobs_dir.mkdir(parents=True, exist_ok=True)
            (jobs_dir / "sources.json").write_text(
                '{"sources": [{"name": "adzuna-reporting", "type": "adzuna", "what": "reporting analyst", "where": "Sydney", "output": "adzuna-reporting.jsonl"}]}',
                encoding="utf-8",
            )
            app = create_app(workspace_root=root)
            client = TestClient(app)

            refresh_result = BuildRefreshJobsResult(
                summary={
                    "source_count": 1,
                    "merged_job_count": 12,
                    "sources": [
                        {
                            "name": "adzuna-reporting",
                            "job_count": 12,
                            "output": "outputs/jobs/adzuna-reporting.jsonl",
                        }
                    ],
                },
                summary_path=root / "outputs" / "jobs" / "refresh-summary.json",
                summary_path_relative="outputs/jobs/refresh-summary.json",
                merged_output_path=root / "outputs" / "jobs" / "all.jsonl",
                merged_output_path_relative="outputs/jobs/all.jsonl",
                run_manifest={"id": "refresh-run-1"},
            )

            with patch(
                "offerquest.web.app.run_refresh_jobs_build",
                return_value=refresh_result,
            ) as refresh_mock:
                response = client.post(
                    "/job-sources",
                    data={
                        "intent": "refresh_jobs",
                        "config_path": "jobs/sources.json",
                        "output_dir": "outputs/jobs",
                    },
                )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(refresh_mock.call_count, 1)
        self.assertIn("Refresh complete", response.text)
        self.assertIn("Open recorded refresh run", response.text)

    def test_job_sources_submit_saves_source_config(self) -> None:
        try:
            from fastapi.testclient import TestClient
        except (ImportError, RuntimeError) as exc:
            self.skipTest(f"fastapi test client unavailable: {exc}")

        from offerquest.web.app import create_app
        from offerquest.workbench import SaveJobSourceConfigResult

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            app = create_app(workspace_root=root)
            client = TestClient(app)

            save_result = SaveJobSourceConfigResult(
                config_path=root / "jobs" / "sources.json",
                config_path_relative="jobs/sources.json",
                action="created",
                source_name="manual",
                source_count=1,
            )

            with patch(
                "offerquest.web.app.run_job_source_save",
                return_value=save_result,
            ) as save_mock:
                response = client.post(
                    "/job-sources",
                    data={
                        "intent": "save_source",
                        "source_name": "manual",
                        "source_type": "manual",
                        "source_enabled": "true",
                        "source_output": "manual.jsonl",
                        "manual_input_path": "jobs",
                    },
                )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(save_mock.call_count, 1)
        self.assertIn("Created", response.text)
        self.assertIn("manual", response.text)

    def test_rerank_jobs_page_renders(self) -> None:
        try:
            from fastapi.testclient import TestClient
        except (ImportError, RuntimeError) as exc:
            self.skipTest(f"fastapi test client unavailable: {exc}")

        from offerquest.web.app import create_app

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
            app = create_app(workspace_root=root)
            client = TestClient(app)

            response = client.get("/rerank-jobs/new?ranking_file=outputs/job-ranking.json")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Rerank Top Jobs", response.text)
        self.assertIn("job-ranking.json", response.text)

    def test_cover_letter_page_renders(self) -> None:
        try:
            from fastapi.testclient import TestClient
        except (ImportError, RuntimeError) as exc:
            self.skipTest(f"fastapi test client unavailable: {exc}")

        from offerquest.web.app import create_app

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
            app = create_app(workspace_root=root)
            client = TestClient(app)

            response = client.get("/cover-letters/new?job_id=job-1")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Generate Cover Letter", response.text)

    def test_cover_letter_page_renders_llm_mode(self) -> None:
        try:
            from fastapi.testclient import TestClient
        except (ImportError, RuntimeError) as exc:
            self.skipTest(f"fastapi test client unavailable: {exc}")

        from offerquest.web.app import create_app

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
            app = create_app(workspace_root=root)
            client = TestClient(app)

            response = client.get("/cover-letters/new?job_id=job-1&mode=llm")

        self.assertEqual(response.status_code, 200)
        self.assertIn("LLM draft (Ollama)", response.text)

    def test_compare_cover_letters_page_renders(self) -> None:
        try:
            from fastapi.testclient import TestClient
        except (ImportError, RuntimeError) as exc:
            self.skipTest(f"fastapi test client unavailable: {exc}")

        from offerquest.web.app import create_app

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
            app = create_app(workspace_root=root)
            client = TestClient(app)

            response = client.get("/cover-letters/compare?job_id=job-1")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Compare Draft Styles", response.text)


if __name__ == "__main__":
    unittest.main()
