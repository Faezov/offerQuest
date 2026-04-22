from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from offerquest.cover_letter import (
    generate_cover_letter_for_job_record,
    generate_cover_letter_for_job_record_llm,
    generate_cover_letters_from_ranking,
    write_cover_letter,
)


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

        payload = generate_cover_letter_for_job_record(
            "data/CV_BF_20260415.docx",
            job_record,
            base_cover_letter_path="data/CL_BF_20260415.doc",
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
            ranking_path = Path(tmpdir) / "ranking.json"
            ranking_path.write_text(json.dumps(ranking_payload), encoding="utf-8")

            jobs_path = Path(tmpdir) / "jobs.jsonl"
            jobs_path.write_text(
                "\n".join(json.dumps(job) for job in jobs) + "\n",
                encoding="utf-8",
            )

            output_dir = Path(tmpdir) / "letters"
            summary = generate_cover_letters_from_ranking(
                "data/CV_BF_20260415.docx",
                jobs_path,
                ranking_path,
                output_dir,
                base_cover_letter_path="data/CL_BF_20260415.doc",
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

        with unittest.mock.patch(
            "offerquest.cover_letter.generate_structured_response",
            return_value={
                "resume_headline": "Senior Data Analyst",
                "employer_specific_focus": ["Consulting environment", "Reporting reliability"],
                "evidence_used": ["Python and SQL automation", "Healthcare and research reporting"],
                "caution_flags": [],
                "cover_letter_text": "Dear Hiring Team,\n\nExample.\n\nWith best regards,\nBulat Faezov",
            },
        ):
            payload = generate_cover_letter_for_job_record_llm(
                "data/CV_BF_20260415.docx",
                job_record,
                base_cover_letter_path="data/CL_BF_20260415.doc",
                model="qwen3:8b",
            )

        self.assertEqual(payload["llm_provider"], "ollama")
        self.assertEqual(payload["llm_model"], "qwen3:8b")
        self.assertIn("Consulting environment", payload["employer_specific_focus"])


if __name__ == "__main__":
    unittest.main()
