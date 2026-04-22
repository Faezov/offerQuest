from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from offerquest.cover_letter import (
    generate_cover_letter_for_job_record,
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


if __name__ == "__main__":
    unittest.main()
