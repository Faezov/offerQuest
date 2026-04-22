import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class WebAppTests(unittest.TestCase):
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

            response = client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("OfferQuest Local Workbench", response.text)

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
        self.assertIn("Adzuna Credentials", response.text)
        self.assertIn("Configured Job Streams", response.text)

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
