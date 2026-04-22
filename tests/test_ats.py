from __future__ import annotations

import unittest

from offerquest.ats import build_ats_report, ats_check_job_record

CV_TEXT = """Bulat Faezov
Sydney, NSW, Australia
faezov.bulat@gmail.com
Professional Summary
Senior data analyst with SQL, Python, reporting, metadata, and healthcare research experience.
Core Skills
SQL
Python
Reporting
Metadata
Professional Experience
University of Washington Medicine
Senior Computer Specialist | 2024
Built reporting and data quality workflows.
Education
Master of Science in Biology
"""

JOB_TEXT = """Senior Data Analyst
Sydney, NSW
Required skills: SQL, Python, Power BI, reporting, stakeholder management.
Experience with healthcare dashboards and metadata is highly regarded.
"""


class AtsTests(unittest.TestCase):
    def test_build_ats_report_surfaces_missing_required_keywords(self) -> None:
        report = build_ats_report(CV_TEXT, JOB_TEXT, cv_path="resume.doc")

        self.assertEqual(report["job_title"], "Senior Data Analyst")
        self.assertGreaterEqual(report["ats_score"], 70)
        self.assertIn("Power BI", report["required_keywords"]["missing"])
        self.assertIn("Stakeholder management", report["required_keywords"]["missing"])
        self.assertEqual(report["suggested_resume_title"], "Senior Data Analyst")
        self.assertTrue(
            any("legacy .doc" in risk.lower() for risk in report["format_risks"])
        )

    def test_build_ats_report_flags_missing_sections_and_contact_fields(self) -> None:
        sparse_cv = """Data Analyst
Worked on reporting and dashboards.
"""

        report = build_ats_report(sparse_cv, JOB_TEXT, cv_path="resume.txt")

        self.assertFalse(report["contact_checks"]["email_detected"])
        self.assertIn("Core Skills", report["section_checks"]["missing"])
        self.assertTrue(report["suggestions"])
        self.assertTrue(any("Core Skills" in suggestion for suggestion in report["suggestions"]))

    def test_ats_check_job_record_keeps_job_context(self) -> None:
        job_record = {
            "id": "adzuna:123",
            "source": "adzuna",
            "title": "Senior Data Analyst",
            "company": "NSW Health",
            "location": "Sydney",
            "url": "https://example.com/jobs/123",
            "description_text": JOB_TEXT,
        }

        report = ats_check_job_record("data/CV_BF_20260415.doc", job_record)

        self.assertEqual(report["job_id"], "adzuna:123")
        self.assertEqual(report["company"], "NSW Health")
        self.assertEqual(report["job_url"], "https://example.com/jobs/123")


if __name__ == "__main__":
    unittest.main()
