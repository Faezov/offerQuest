import tempfile
import unittest
from pathlib import Path


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
