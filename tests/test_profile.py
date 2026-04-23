from __future__ import annotations

import unittest

from offerquest.profile import build_candidate_profile

CV_TEXT = """Bulat Faezov, M.Sc.
Sydney, NSW, Australia
faezov.bulat@gmail.com
Professional Summary
Analytical and detail-oriented insights professional with 10+ years of experience across healthcare, research, and technical environments.
Core Skills
Data analysis and interpretation
SQL querying
Python automation and analytics workflows
Data validation and quality checking
Professional Experience
University of Washington Medicine
Senior Computer Specialist | 2024
Fox Chase Cancer Center
Scientific Associate | 2023
Technical Tools
Python
Pandas
Jupyter
Matplotlib
Microsoft Excel
Certifications
AWS Cloud Technical Essentials
"""

CL_TEXT = """Dear Hiring Panel,
I am writing to apply for the position of Senior Metadata and National Data Officer (REQ646085).
I bring more than 10 years of experience working with structured data, analysis, reporting, and process improvement.
Now that I am based in Sydney, I am especially motivated to contribute my skills in a role that supports the public health system here in New South Wales.
With best regards,
Bulat Faezov
"""

GENERAL_CV_TEXT = """JANE A. DOE
Melbourne, VIC, Australia
jane.doe@example.com
Professional Summary
Senior analyst with experience in SQL reporting, stakeholder communication, and public-sector delivery.
Core Skills
SQL
Reporting
Stakeholder collaboration
Professional Experience
Department of Education
Senior Reporting Analyst | 2025
"""


class ProfileTests(unittest.TestCase):
    def test_build_candidate_profile_extracts_core_data(self) -> None:
        profile = build_candidate_profile(CV_TEXT, CL_TEXT)

        self.assertEqual(profile["name"], "Bulat Faezov")
        self.assertEqual(profile["location"], "Sydney, NSW, Australia")
        self.assertEqual(profile["email"], "faezov.bulat@gmail.com")
        self.assertEqual(profile["years_experience"], 10)
        self.assertIn("SQL", profile["core_skills"])
        self.assertIn("Python", profile["core_skills"])
        self.assertIn("Metadata", profile["core_skills"])
        self.assertIn("Healthcare", profile["domains"])
        self.assertIn("Research", profile["domains"])

    def test_build_candidate_profile_creates_search_focus(self) -> None:
        profile = build_candidate_profile(CV_TEXT, CL_TEXT)
        titles = profile["search_focus"]["priority_titles"]

        self.assertTrue(titles[0].startswith("Senior Metadata"))
        self.assertIn("Senior Data Analyst", titles)
        self.assertIn("Metadata Analyst / Data Governance Analyst", titles)

    def test_build_candidate_profile_generalizes_name_and_location(self) -> None:
        profile = build_candidate_profile(GENERAL_CV_TEXT, "")

        self.assertEqual(profile["name"], "Jane A. Doe")
        self.assertEqual(profile["location"], "Melbourne, VIC, Australia")
        self.assertIn("Melbourne", profile["search_focus"]["location_preferences"])
        self.assertIn("VIC", profile["search_focus"]["location_preferences"])

    def test_build_candidate_profile_includes_keywords_for_expanded_tool_patterns(self) -> None:
        cv_text = """JANE DOE
Sydney, NSW, Australia
Professional Summary
Data analyst focused on Power BI dashboards and stakeholder reporting.
Core Skills
Power BI
Reporting
"""

        profile = build_candidate_profile(cv_text, "")

        self.assertIn("Power BI", profile["core_skills"])
        self.assertIn("Power BI", profile["search_focus"]["keywords_to_include"])


if __name__ == "__main__":
    unittest.main()
