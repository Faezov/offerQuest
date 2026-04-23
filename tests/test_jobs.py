from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from offerquest.jobs import (
    collect_job_record_inputs,
    fetch_adzuna_jobs,
    fetch_adzuna_job_pages,
    fetch_greenhouse_jobs,
    infer_manual_company_and_location,
    import_manual_jobs,
    job_record_to_text,
    load_adzuna_credentials_file,
    load_adzuna_credentials_status,
    merge_job_record_sets,
    normalize_adzuna_job,
    normalize_greenhouse_job,
    read_job_records,
    refresh_job_sources,
    resolve_adzuna_credentials,
    write_adzuna_credentials_file,
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

    def test_infer_manual_company_and_location_handles_generic_region_name_after_comma(self) -> None:
        text = "Senior Data Analyst\nNSW Health, Victoria\nSQL and reporting\n"

        company, location = infer_manual_company_and_location(text, title="Senior Data Analyst")

        self.assertEqual(company, "NSW Health")
        self.assertEqual(location, "Victoria")

    def test_infer_manual_company_and_location_handles_generic_region_name_on_next_line(self) -> None:
        text = "Senior Data Analyst\nAtlassian\nQueensland\nSQL and reporting\n"

        company, location = infer_manual_company_and_location(text, title="Senior Data Analyst")

        self.assertEqual(company, "Atlassian")
        self.assertEqual(location, "Queensland")

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

    def test_fetch_adzuna_job_pages_merges_pages_and_adds_query_metadata(self) -> None:
        payloads = [
            [
                {
                    "source": "adzuna",
                    "external_id": "1",
                    "title": "Senior Data Analyst",
                    "company": "NSW Health",
                    "url": "https://example.com/jobs/1",
                    "description_text": "Short description",
                }
            ],
            [
                {
                    "source": "adzuna",
                    "external_id": "1",
                    "title": "Senior Data Analyst",
                    "company": "NSW Health",
                    "url": "https://example.com/jobs/1",
                    "description_text": "Longer SQL and metadata description",
                },
                {
                    "source": "adzuna",
                    "external_id": "2",
                    "title": "Reporting Analyst",
                    "company": "Healthscope",
                    "url": "https://example.com/jobs/2",
                    "description_text": "Reporting and dashboard role",
                },
            ],
        ]

        with patch("offerquest.jobs.fetch_adzuna_jobs", side_effect=payloads) as fetch_mock:
            records = fetch_adzuna_job_pages(
                app_id="app",
                app_key="key",
                what="data analyst",
                where="Sydney",
                country="au",
                pages=2,
                results_per_page=20,
            )

        self.assertEqual(fetch_mock.call_count, 2)
        self.assertEqual(len(records), 2)

        merged = next(record for record in records if record["id"] == "adzuna:1")
        self.assertIn("SQL and metadata", merged["description_text"])
        self.assertEqual(merged["metadata"]["query_what"], "data analyst")
        self.assertEqual(merged["metadata"]["query_where"], "Sydney")
        self.assertEqual(merged["metadata"]["query_country"], "au")

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

    def test_write_and_load_adzuna_credentials_file_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = Path(tmpdir) / "adzuna.env"
            saved_path = write_adzuna_credentials_file(
                "app-1234",
                "key-!@#'42",
                raw_path=env_path,
            )

            credentials = load_adzuna_credentials_file(env_path)
            status = load_adzuna_credentials_status(env_path)

        self.assertEqual(saved_path, env_path.resolve())
        self.assertEqual(credentials["ADZUNA_APP_ID"], "app-1234")
        self.assertEqual(credentials["ADZUNA_APP_KEY"], "key-!@#'42")
        self.assertTrue(status["file_exists"])
        self.assertTrue(status["has_saved_credentials"])
        self.assertEqual(status["saved_app_id_masked"], "app-**34")

    def test_resolve_adzuna_credentials_falls_back_to_saved_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = Path(tmpdir) / "adzuna.env"
            write_adzuna_credentials_file(
                "saved-app",
                "saved-key",
                raw_path=env_path,
            )

            with patch.dict(
                "os.environ",
                {
                    "OFFERQUEST_ADZUNA_ENV_FILE": str(env_path),
                },
                clear=True,
            ):
                app_id, app_key = resolve_adzuna_credentials(None, None)

        self.assertEqual(app_id, "saved-app")
        self.assertEqual(app_key, "saved-key")

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

    def test_refresh_job_sources_writes_source_outputs_merge_and_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            jobs_dir = root / "jobs"
            jobs_dir.mkdir()
            (jobs_dir / "manual-role.txt").write_text(
                "Senior Reporting Analyst\nNSW Health, Sydney\nSQL and reporting\n",
                encoding="utf-8",
            )

            config = {
                "sources": [
                    {
                        "name": "adzuna-reporting",
                        "type": "adzuna",
                        "what": "reporting analyst",
                        "where": "Sydney",
                        "country": "au",
                        "pages": 2,
                        "results_per_page": 20,
                        "output": "adzuna-reporting.jsonl",
                    },
                    {
                        "name": "greenhouse-example",
                        "type": "greenhouse",
                        "board_token": "example",
                        "output": "greenhouse-example.jsonl",
                    },
                    {
                        "name": "manual",
                        "type": "manual",
                        "input_path": "jobs",
                        "output": "manual.jsonl",
                    },
                ],
                "merge": {
                    "enabled": True,
                    "inputs": [
                        "adzuna-reporting.jsonl",
                        "greenhouse-example.jsonl",
                        "manual.jsonl",
                    ],
                    "output": "all.jsonl",
                },
                "summary_output": "refresh-summary.json",
            }
            config_path = root / "jobs-sources.json"
            config_path.write_text(json.dumps(config), encoding="utf-8")

            adzuna_records = [
                {
                    "source": "adzuna",
                    "external_id": "1",
                    "title": "Reporting Analyst",
                    "company": "NSW Health",
                    "location": "Sydney",
                    "description_text": "SQL reporting role",
                    "url": "https://example.com/adzuna/1",
                }
            ]
            greenhouse_records = [
                {
                    "source": "greenhouse",
                    "external_id": "44",
                    "title": "Metadata Analyst",
                    "company": "Example Org",
                    "location": "Sydney",
                    "description_text": "Metadata and governance role",
                    "url": "https://example.com/greenhouse/44",
                }
            ]

            with patch(
                "offerquest.jobs.fetch_adzuna_job_pages",
                return_value=adzuna_records,
            ) as adzuna_mock, patch(
                "offerquest.jobs.fetch_greenhouse_jobs",
                return_value=greenhouse_records,
            ) as greenhouse_mock:
                summary = refresh_job_sources(
                    config_path,
                    workspace_root=root,
                    adzuna_app_id="app",
                    adzuna_app_key="key",
                )
            self.assertEqual(adzuna_mock.call_count, 1)
            self.assertEqual(greenhouse_mock.call_count, 1)
            self.assertEqual(summary["source_count"], 3)
            self.assertEqual(summary["merged_output"], "outputs/jobs/all.jsonl")
            self.assertEqual(summary["merged_job_count"], 3)

            output_root = root / "outputs" / "jobs"
            merged_records = read_job_records(output_root / "all.jsonl")
            adzuna_output = read_job_records(output_root / "adzuna-reporting.jsonl")
            greenhouse_output = read_job_records(output_root / "greenhouse-example.jsonl")
            manual_output = read_job_records(output_root / "manual.jsonl")

            self.assertEqual(len(merged_records), 3)
            self.assertEqual(len(adzuna_output), 1)
            self.assertEqual(len(greenhouse_output), 1)
            self.assertEqual(len(manual_output), 1)
            self.assertEqual(adzuna_output[0]["metadata"]["source_name"], "adzuna-reporting")
            self.assertEqual(
                greenhouse_output[0]["metadata"]["source_name"], "greenhouse-example"
            )
            self.assertEqual(manual_output[0]["metadata"]["source_name"], "manual")

            summary_path = output_root / "refresh-summary.json"
            self.assertTrue(summary_path.exists())
            persisted_summary = json.loads(summary_path.read_text(encoding="utf-8"))
            self.assertEqual(
                persisted_summary["summary_output"], "outputs/jobs/refresh-summary.json"
            )


if __name__ == "__main__":
    unittest.main()
