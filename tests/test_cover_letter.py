from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from offerquest.cover_letter import (
    build_cover_letter_text,
    generate_cover_letter_for_job_record,
    generate_cover_letter_for_job_record_llm,
    generate_cover_letters_from_ranking,
    select_top_unique_rankings,
    write_cover_letter,
)
from offerquest.errors import ProfileValidationError

CANDIDATE_CV_TEXT = """Jordan Lee
Sydney, NSW, Australia
jordan.lee@example.com
Professional Summary
Senior data analyst with 10+ years of experience across healthcare, research, reporting, and technical environments.
Core Skills
SQL querying
Python automation and analytics workflows
Reporting
Metadata
Data validation and quality checking
Professional Experience
Harbour Health Research Institute
Senior Reporting Analyst | 2024
Built reporting and data quality workflows.
Education
Master of Science in Biology
"""

BASE_COVER_LETTER_TEXT = """Dear Hiring Panel,
I am writing to apply for the position of Senior Data Analyst.
I bring more than 10 years of experience working with structured data, analysis, reporting, and process improvement.
With best regards,
Jordan Lee
"""


def write_candidate_inputs(root: Path) -> tuple[Path, Path]:
    cv_path = root / "candidate-cv.txt"
    cover_letter_path = root / "base-cover-letter.txt"
    cv_path.write_text(CANDIDATE_CV_TEXT, encoding="utf-8")
    cover_letter_path.write_text(BASE_COVER_LETTER_TEXT, encoding="utf-8")
    return cv_path, cover_letter_path


class CoverLetterTests(unittest.TestCase):
    def test_generate_cover_letter_for_job_record_mentions_role_and_company(self) -> None:
        job_record = {
            "id": "adzuna:123",
            "source": "adzuna",
            "title": "Senior Data Analyst",
            "company": "Mane Consulting",
            "location": "Sydney",
            "url": "https://example.com/jobs/123",
            "description_text": (
                "Senior Data Analyst\n"
                "Mane Consulting, Sydney\n"
                "Required skills: reporting, automation, SQL.\n"
            ),
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            cv_path, cover_letter_path = write_candidate_inputs(Path(tmpdir))
            payload = generate_cover_letter_for_job_record(
                cv_path,
                job_record,
                base_cover_letter_path=cover_letter_path,
            )

        self.assertEqual(payload["job_title"], "Senior Data Analyst")
        self.assertEqual(payload["company"], "Mane Consulting")
        self.assertIn("Senior Data Analyst", payload["cover_letter_text"])
        self.assertIn("Mane Consulting", payload["cover_letter_text"])
        self.assertIn("With best regards", payload["cover_letter_text"])

    def test_write_cover_letter_writes_plain_text(self) -> None:
        payload = {
            "job_title": "Senior Data Analyst",
            "company": "Mane Consulting",
            "cover_letter_text": "Dear Hiring Team,\n\nExample.\n",
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "letter.txt"
            write_cover_letter(output_path, payload)
            content = output_path.read_text(encoding="utf-8")

        self.assertIn("Dear Hiring Team", content)

    def test_generate_cover_letters_from_ranking_creates_top_unique_outputs(self) -> None:
        ranking_payload = {
            "rankings": [
                {
                    "job_id": "adzuna:1",
                    "company": "Mane Consulting",
                    "job_title": "Senior Data Analyst",
                },
                {
                    "job_id": "adzuna:2",
                    "company": "Mane Consulting",
                    "job_title": "Senior Data Analyst",
                },
                {
                    "job_id": "adzuna:3",
                    "company": "HAYS",
                    "job_title": "Senior Data Analyst",
                },
            ]
        }
        jobs = [
            {
                "id": "adzuna:1",
                "source": "adzuna",
                "title": "Senior Data Analyst",
                "company": "Mane Consulting",
                "location": "Sydney",
                "description_text": "Required skills: reporting, automation, SQL.",
                "url": "https://example.com/1",
            },
            {
                "id": "adzuna:2",
                "source": "adzuna",
                "title": "Senior Data Analyst",
                "company": "Mane Consulting",
                "location": "Sydney",
                "description_text": "Required skills: reporting, automation, SQL.",
                "url": "https://example.com/2",
            },
            {
                "id": "adzuna:3",
                "source": "adzuna",
                "title": "Senior Data Analyst",
                "company": "HAYS",
                "location": "Sydney",
                "description_text": "Required skills: reporting, SQL.",
                "url": "https://example.com/3",
            },
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            cv_path, cover_letter_path = write_candidate_inputs(Path(tmpdir))
            ranking_path = Path(tmpdir) / "ranking.json"
            ranking_path.write_text(json.dumps(ranking_payload), encoding="utf-8")

            jobs_path = Path(tmpdir) / "jobs.jsonl"
            jobs_path.write_text(
                "\n".join(json.dumps(job) for job in jobs) + "\n",
                encoding="utf-8",
            )

            output_dir = Path(tmpdir) / "letters"
            summary = generate_cover_letters_from_ranking(
                cv_path,
                jobs_path,
                ranking_path,
                output_dir,
                base_cover_letter_path=cover_letter_path,
                top_n=5,
                export_docx=True,
            )

            summary_path = output_dir / "summary.json"
            summary_path_exists = summary_path.exists()
            item_docx_paths = [Path(item["docx_path"]).exists() for item in summary["items"]]

        self.assertEqual(summary["job_count"], 2)
        self.assertTrue(summary_path_exists)
        self.assertTrue(any(item["company"] == "Mane Consulting" for item in summary["items"]))
        self.assertTrue(any(item["company"] == "HAYS" for item in summary["items"]))
        self.assertTrue(all("docx_path" in item for item in summary["items"]))
        self.assertTrue(all(item_docx_paths))

    def test_generate_cover_letter_for_job_record_llm_uses_structured_response(self) -> None:
        job_record = {
            "id": "adzuna:123",
            "source": "adzuna",
            "title": "Senior Data Analyst",
            "company": "Mane Consulting",
            "location": "Sydney",
            "url": "https://example.com/jobs/123",
            "description_text": (
                "Senior Data Analyst\n"
                "Mane Consulting, Sydney\n"
                "Required skills: reporting, automation, SQL.\n"
            ),
        }

        with mock.patch(
            "offerquest.cover_letter.generate_structured_response",
            return_value={
                "resume_headline": "Senior Data Analyst",
                "employer_specific_focus": ["Consulting environment", "Reporting reliability"],
                "evidence_used": ["Python and SQL automation", "Healthcare and research reporting"],
                "caution_flags": [],
                "cover_letter_text": "Dear Hiring Team,\n\nExample.\n\nWith best regards,\nJordan Lee",
            },
        ):
            with tempfile.TemporaryDirectory() as tmpdir:
                cv_path, cover_letter_path = write_candidate_inputs(Path(tmpdir))
                payload = generate_cover_letter_for_job_record_llm(
                    cv_path,
                    job_record,
                    base_cover_letter_path=cover_letter_path,
                    model="qwen3:8b",
                )

        self.assertEqual(payload["llm_provider"], "ollama")
        self.assertEqual(payload["llm_model"], "qwen3:8b")
        self.assertIn("Consulting environment", payload["employer_specific_focus"])

    def test_build_cover_letter_text_requires_candidate_name(self) -> None:
        with self.assertRaises(ProfileValidationError):
            build_cover_letter_text(
                profile={
                    "name": None,
                    "core_skills": ["SQL", "Reporting"],
                    "domains": [],
                    "recent_roles": [],
                    "summary": "Analyst",
                },
                ats_report={
                    "keyword_coverage": {"matched_keywords": ["SQL"]},
                    "required_keywords": {"missing": []},
                },
                job_context={"job_title": "Data Analyst", "company": "Acme"},
            )

    def test_build_cover_letter_text_avoids_hard_coded_identity_details(self) -> None:
        text = build_cover_letter_text(
            profile={
                "name": "Jane Doe",
                "location": None,
                "years_experience": None,
                "summary": "Analyst with experience in SQL reporting and process improvement.",
                "core_skills": ["SQL", "Reporting"],
                "domains": ["Public sector"],
                "recent_roles": [],
            },
            ats_report={
                "keyword_coverage": {"matched_keywords": ["SQL", "Reporting"]},
                "required_keywords": {"missing": []},
            },
            job_context={"job_title": "Data Analyst", "company": "Acme"},
        )

        self.assertIn("Jane Doe", text)
        self.assertNotIn("Jordan Lee", text)
        self.assertNotIn("Sydney, NSW, Australia", text)

    def test_select_top_unique_rankings_keeps_same_title_different_locations(self) -> None:
        rankings = [
            {"job_id": "1", "company": "BigCo", "job_title": "Data Analyst", "location": "Sydney"},
            {"job_id": "2", "company": "BigCo", "job_title": "Data Analyst", "location": "Melbourne"},
        ]

        selected = select_top_unique_rankings(rankings, limit=5)

        self.assertEqual(len(selected), 2)


if __name__ == "__main__":
    unittest.main()
