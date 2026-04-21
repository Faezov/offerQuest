from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from offerquest.jobs import (
    collect_job_record_inputs,
    fetch_adzuna_jobs,
    fetch_greenhouse_jobs,
    import_manual_jobs,
    job_record_to_text,
    merge_job_record_sets,
    normalize_adzuna_job,
    normalize_greenhouse_job,
    write_job_records,
)
from offerquest.scoring import score_job_record


class JobsTests(unittest.TestCase):
    def test_normalize_adzuna_job_maps_core_fields(self) -> None:
        job = {
            "id": "123",
            "title": "Senior Data Analyst",
            "company": {"display_name": "NSW Health"},
            "location": {"display_name": "Sydney NSW"},
            "description": "SQL and Python reporting role",
            "salary_min": 120000,
            "salary_max": 140000,
            "salary_currency": "AUD",
            "redirect_url": "https://example.com/job/123",
            "created": "2026-04-22T01:00:00Z",
            "contract_type": "permanent",
            "category": {"label": "IT Jobs"},
        }

        record = normalize_adzuna_job(job, country="au")

        self.assertEqual(record["id"], "adzuna:123")
        self.assertEqual(record["company"], "NSW Health")
        self.assertEqual(record["location"], "Sydney NSW")
        self.assertEqual(record["salary_min"], 120000)
        self.assertEqual(record["currency"], "AUD")
        self.assertEqual(record["metadata"]["category"], "IT Jobs")

    def test_normalize_greenhouse_job_strips_html(self) -> None:
        job = {
            "id": 44,
            "title": "Metadata Analyst",
            "location": {"name": "Sydney"},
            "content": "<p>Metadata and data quality</p><div>SQL required</div>",
            "absolute_url": "https://boards.greenhouse.io/example/jobs/44",
            "updated_at": "2026-04-20T01:00:00Z",
            "departments": [{"name": "Data"}],
            "offices": [{"name": "Sydney"}],
        }

        record = normalize_greenhouse_job(job, board_token="example", company="Example Org")

        self.assertEqual(record["id"], "greenhouse:44")
        self.assertEqual(record["company"], "Example Org")
        self.assertIn("Metadata and data quality", record["description_text"])
        self.assertIn("SQL required", record["description_text"])
        self.assertEqual(record["metadata"]["departments"], ["Data"])

    def test_merge_job_record_sets_dedupes_by_url(self) -> None:
        existing = [
            {
                "source": "adzuna",
                "external_id": "1",
                "title": "Senior Data Analyst",
                "company": "NSW Health",
                "url": "https://example.com/jobs/1",
                "description_text": "Short text",
            }
        ]
        incoming = [
            {
                "source": "manual",
                "external_id": "/tmp/job.txt",
                "title": "Senior Data Analyst",
                "company": "NSW Health",
                "url": "https://example.com/jobs/1",
                "description_text": "Longer description with SQL and metadata",
            }
        ]

        merged = merge_job_record_sets(existing, incoming)

        self.assertEqual(len(merged), 1)
        self.assertIn("SQL and metadata", merged[0]["description_text"])

    def test_import_manual_jobs_creates_normalized_records(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "job1.txt"
            path.write_text(
                "Senior Data Analyst\nNSW Health, Sydney\nSQL and reporting\n",
                encoding="utf-8",
            )

            records = import_manual_jobs(path)

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["title"], "Senior Data Analyst")
        self.assertEqual(records[0]["company"], "NSW Health")
        self.assertEqual(records[0]["location"], "Sydney")
        self.assertIn("SQL and reporting", records[0]["description_text"])

    def test_write_and_collect_job_records_support_jsonl(self) -> None:
        jobs = [
            {
                "source": "manual",
                "external_id": "a",
                "title": "Role A",
                "company": "Company A",
            },
            {
                "source": "manual",
                "external_id": "b",
                "title": "Role B",
                "company": "Company B",
            },
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "jobs.jsonl"
            write_job_records(path, jobs)
            collected = collect_job_record_inputs([path])

        self.assertEqual(len(collected), 2)
        self.assertEqual(collected[0]["company"], "Company A")

    def test_job_record_to_text_includes_salary_and_metadata(self) -> None:
        record = {
            "source": "greenhouse",
            "external_id": "44",
            "title": "Metadata Analyst",
            "company": "Example Org",
            "location": "Sydney",
            "salary_min": 100000,
            "salary_max": 120000,
            "currency": "AUD",
            "description_text": "SQL and data quality",
            "metadata": {"departments": ["Data"]},
        }

        text = job_record_to_text(record)

        self.assertIn("Salary: 100000-120000 AUD", text)
        self.assertIn("Departments: Data", text)

    def test_fetch_adzuna_jobs_uses_payload_results(self) -> None:
        payload = {
            "results": [
                {
                    "id": "123",
                    "title": "Senior Data Analyst",
                    "company": {"display_name": "NSW Health"},
                    "location": {"display_name": "Sydney NSW"},
                    "description": "SQL and Python reporting role",
                }
            ]
        }

        with patch("offerquest.jobs.fetch_json", return_value=payload) as fetch_json_mock:
            records = fetch_adzuna_jobs(
                app_id="app",
                app_key="key",
                what="data analyst",
                where="Sydney",
            )

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["company"], "NSW Health")
        self.assertEqual(fetch_json_mock.call_count, 1)

    def test_fetch_greenhouse_jobs_uses_board_name(self) -> None:
        payloads = [
            {"name": "Example Org"},
            {
                "jobs": [
                    {
                        "id": 44,
                        "title": "Metadata Analyst",
                        "location": {"name": "Sydney"},
                        "content": "<p>Metadata role</p>",
                    }
                ]
            },
        ]

        with patch("offerquest.jobs.fetch_json", side_effect=payloads) as fetch_json_mock:
            records = fetch_greenhouse_jobs("example")

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["company"], "Example Org")
        self.assertEqual(fetch_json_mock.call_count, 2)

    def test_score_job_record_keeps_record_context(self) -> None:
        profile = {
            "years_experience": 10,
            "core_skills": ["SQL", "Python", "Metadata", "Reporting", "Data quality", "Automation"],
            "domains": ["Healthcare", "Research", "Public sector"],
            "search_focus": {"priority_titles": ["Senior Data Analyst", "Metadata Analyst"]},
        }
        record = {
            "source": "manual",
            "external_id": "abc",
            "title": "Metadata Analyst",
            "company": "NSW Health",
            "location": "Sydney",
            "description_text": "Metadata, SQL, reporting, and healthcare role",
            "url": "https://example.com/job",
            "salary_min": 120000,
            "salary_max": 140000,
            "currency": "AUD",
        }

        result = score_job_record(record, profile)

        self.assertEqual(result["company"], "NSW Health")
        self.assertEqual(result["salary_max"], 140000)
        self.assertGreaterEqual(result["score"], 70)


if __name__ == "__main__":
    unittest.main()
