from __future__ import annotations

import unittest

from offerquest.resume_tailoring import (
    build_resume_tailored_draft,
    build_resume_tailoring_plan,
)

CV_TEXT = """Jane Doe
Melbourne, VIC, Australia
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

JOB_TEXT = """Senior Data Analyst
Example Org, Sydney
Required skills: SQL, Python, Power BI, reporting, stakeholder management.
Experience with healthcare dashboards and metadata is highly regarded.
"""

COVER_LETTER_TEXT = """Dear Hiring Team,
I am writing to apply for the position of Senior Data Analyst.
I have also built visualization outputs to communicate findings clearly.
Jane Doe
"""


class ResumeTailoringTests(unittest.TestCase):
    def test_build_resume_tailoring_plan_surfaces_priority_sections_and_keywords(self) -> None:
        plan = build_resume_tailoring_plan(CV_TEXT, JOB_TEXT, cv_path="resume.txt")

        self.assertEqual(plan["job_title"], "Senior Data Analyst")
        self.assertEqual(plan["ats_snapshot"]["suggested_resume_title"], "Senior Data Analyst")
        self.assertIn("SQL", plan["keyword_plan"]["focus_keywords"])
        self.assertIn("Power BI", plan["keyword_plan"]["missing_keywords"])
        self.assertEqual(plan["sections_to_update_first"][0]["section"], "Resume Headline")
        self.assertEqual(plan["headline_plan"]["recommended_title"], "Senior Data Analyst")
        self.assertTrue(plan["summary_plan"]["guidance"])
        self.assertTrue(plan["experience_plan"]["roles_to_surface"])
        self.assertTrue(plan["truthfulness_notes"])

    def test_build_resume_tailored_draft_generates_compare_payload(self) -> None:
        job_text = """Senior Data Analyst
Example Org, Sydney
Required skills: SQL, Python, reporting, visualization.
Experience with healthcare dashboards and metadata is highly regarded.
"""

        draft = build_resume_tailored_draft(
            CV_TEXT,
            job_text,
            cv_path="resume.txt",
            cover_letter_text=COVER_LETTER_TEXT,
        )

        self.assertIn("Senior Data Analyst", draft["tailored_cv_text"])
        self.assertIn("Professional Summary", draft["tailored_cv_text"])
        self.assertIn("Core Skills", draft["tailored_cv_text"])
        self.assertIn("Visualization", draft["section_changes"]["skills_after"])
        self.assertIn("Visualization", draft["ats_delta"]["gained_keywords"])
        self.assertGreaterEqual(
            draft["ats_after"]["ats_score"],
            draft["ats_before"]["ats_score"],
        )

    def test_build_resume_tailored_draft_does_not_promote_unsupported_stretch_title(self) -> None:
        stretch_job_text = """Principal Data Scientist
Example Org, Sydney
Seeking machine learning leadership and predictive modeling expertise.
"""

        draft = build_resume_tailored_draft(
            CV_TEXT,
            stretch_job_text,
            cv_path="resume.txt",
        )

        self.assertEqual(draft["section_changes"]["headline_after"], "Senior Data Analyst")
        self.assertNotIn("Principal Data Scientist\n", draft["tailored_cv_text"])
        self.assertFalse(draft["plan"]["headline_plan"]["can_mirror_job_title"])
        self.assertEqual(draft["plan"]["headline_plan"]["job_title_to_mirror"], "Principal Data Scientist")


if __name__ == "__main__":
    unittest.main()
