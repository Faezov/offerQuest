from __future__ import annotations

import unittest

from offerquest.profile import build_candidate_profile
from offerquest.reranking import rerank_job_records

CV_TEXT = """Jane Doe
Sydney, NSW, Australia
jane@example.com
Professional Summary
Senior data analyst with SQL, Python, reporting, metadata, and healthcare research experience.
Core Skills
SQL
Python
Reporting
Metadata
Professional Experience
Example Health
Senior Reporting Analyst | 2025
Built reporting and data quality workflows for clinical teams.
Education
Master of Science
"""


class RerankingTests(unittest.TestCase):
    def test_rerank_job_records_promotes_stronger_ats_match_within_top_window(self) -> None:
        profile = build_candidate_profile(CV_TEXT, "", cv_path="resume.txt")
        jobs = [
            {
                "id": "job-1",
                "source": "manual",
                "title": "Senior Data Analyst",
                "company": "Example Org",
                "location": "Sydney",
                "description_text": "SQL reporting role in analytics.",
            },
            {
                "id": "job-2",
                "source": "manual",
                "title": "Data Officer",
                "company": "Example Org",
                "location": "Sydney",
                "description_text": "Required skills: SQL, reporting.",
            },
            {
                "id": "job-3",
                "source": "manual",
                "title": "Data Scientist",
                "company": "Example Org",
                "location": "Sydney",
                "description_text": "Machine learning and predictive modeling.",
            },
        ]

        results = rerank_job_records(
            jobs,
            profile,
            cv_text=CV_TEXT,
            cv_path="resume.txt",
            top_n=2,
        )

        self.assertEqual(results[0]["job_id"], "job-2")
        self.assertEqual(results[0]["original_rank"], 2)
        self.assertEqual(results[0]["rerank_rank"], 1)
        self.assertGreater(results[0]["rerank_score"], results[0]["initial_score"])
        self.assertEqual(results[0]["required_keyword_coverage_percent"], 100)
        self.assertTrue(results[0]["rerank_reasons"])

        self.assertEqual(results[1]["job_id"], "job-1")
        self.assertEqual(results[1]["rank_change"], -1)

        self.assertEqual(results[2]["job_id"], "job-3")
        self.assertFalse(results[2]["rerank_window"])
        self.assertEqual(results[2]["original_rank"], 3)
        self.assertEqual(results[2]["rerank_rank"], 3)
        self.assertEqual(results[2]["rerank_score"], results[2]["initial_score"])


if __name__ == "__main__":
    unittest.main()
