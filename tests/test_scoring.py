from __future__ import annotations

import unittest

from offerquest.scoring import score_job_text

PROFILE = {
    "years_experience": 10,
    "core_skills": ["SQL", "Python", "Metadata", "Reporting", "Data quality", "Automation"],
    "domains": ["Healthcare", "Research", "Public sector"],
    "search_focus": {
        "priority_titles": [
            "Senior Metadata and National Data Officer (REQ646085)",
            "Senior Data Analyst",
            "Metadata Analyst / Data Governance Analyst",
        ]
    },
}


class ScoringTests(unittest.TestCase):
    def test_score_job_text_rewards_metadata_health_roles(self) -> None:
        job_text = """Senior Metadata Analyst
NSW Health, Sydney
We are seeking a senior analyst with metadata, SQL, reporting, data quality, and healthcare experience.
"""

        result = score_job_text(job_text, PROFILE)

        self.assertGreaterEqual(result["score"], 75)
        self.assertIn("Metadata", result["matched_skills"])
        self.assertIn("Healthcare", result["matched_domains"])

    def test_score_job_text_penalizes_ml_heavy_stretch_roles(self) -> None:
        job_text = """Senior Data Scientist
New York, USA
Build machine learning models, predictive systems, and advanced experimentation pipelines.
Python required.
"""

        result = score_job_text(job_text, PROFILE)

        self.assertLess(result["score"], 60)
        self.assertTrue(any("machine learning" in gap.lower() for gap in result["gaps"]))


if __name__ == "__main__":
    unittest.main()
