from __future__ import annotations

import unittest
from typing import Any

from offerquest.scoring import score_job_text

PROFILE = {
    "years_experience": 10,
    "core_skills": ["SQL", "Python", "Metadata", "Reporting", "Data quality", "Automation"],
    "domains": ["Healthcare", "Research", "Public sector"],
    "search_focus": {
        "priority_titles": [
            "Senior Data Analyst",
            "Metadata Analyst / Data Governance Analyst",
            "Reporting Analyst / Insights Analyst",
        ]
    },
}

GOOD_FIT_CASES: list[dict[str, Any]] = [
    {
        "name": "metadata health role",
        "job_text": (
            "Senior Metadata Analyst\n"
            "NSW Health, Sydney\n"
            "Required skills: metadata, SQL, reporting, data quality.\n"
            "Healthcare experience is highly regarded.\n"
        ),
        "min_score": 75,
    },
    {
        "name": "public sector reporting role",
        "job_text": (
            "Senior Reporting Analyst\n"
            "Melbourne, VIC, Australia\n"
            "Government reporting role focused on SQL, reporting, automation, and stakeholder updates.\n"
        ),
        "min_score": 68,
    },
]

BAD_FIT_CASES: list[dict[str, Any]] = [
    {
        "name": "biologist should not look like BI",
        "job_text": (
            "Biologist\n"
            "Melbourne, VIC, Australia\n"
            "Laboratory experiments, specimen handling, and biological analysis.\n"
        ),
        "max_score": 45,
    },
    {
        "name": "remote united states engineering role",
        "job_text": (
            "Senior Data Engineer\n"
            "Remote, United States\n"
            "Build warehousing infrastructure, data pipelines, and platform tooling.\n"
        ),
        "max_score": 45,
    },
    {
        "name": "machine learning scientist stretch role",
        "job_text": (
            "Senior Data Scientist\n"
            "New York, USA\n"
            "Build machine learning models, predictive systems, and experimentation pipelines.\n"
        ),
        "max_score": 55,
    },
]


class ScoringRegressionTests(unittest.TestCase):
    def test_good_fit_roles_stay_high(self) -> None:
        for case in GOOD_FIT_CASES:
            with self.subTest(case=case["name"]):
                result = score_job_text(case["job_text"], PROFILE)
                self.assertGreaterEqual(result["score"], case["min_score"])

    def test_bad_fit_roles_stay_low(self) -> None:
        for case in BAD_FIT_CASES:
            with self.subTest(case=case["name"]):
                result = score_job_text(case["job_text"], PROFILE)
                self.assertLessEqual(result["score"], case["max_score"])


if __name__ == "__main__":
    unittest.main()
