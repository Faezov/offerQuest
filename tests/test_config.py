from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from offerquest import config as offer_config
from offerquest.cli import build_parser
from offerquest.profile import build_candidate_profile


class ConfigTests(unittest.TestCase):
    def tearDown(self) -> None:
        offer_config.reset_to_defaults()

    def test_load_config_overlay_customizes_search_focus(self) -> None:
        overlay = {
            "search_focus": {
                "default_title": "Analytics Engineer",
                "titles_by_skill": {
                    "SQL": ["SQL Analyst"],
                },
                "stretch_roles_to_treat_cautiously": [
                    "Roles that are mostly platform engineering",
                ],
            }
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "offerquest.json"
            config_path.write_text(json.dumps(overlay), encoding="utf-8")

            loaded = offer_config.load_config(config_path)

        self.assertEqual(loaded.search_focus_default_title, "Analytics Engineer")
        self.assertEqual(loaded.search_focus_titles_by_skill["SQL"], ["SQL Analyst"])
        self.assertEqual(
            loaded.search_focus_stretch_roles,
            ("Roles that are mostly platform engineering",),
        )

    def test_active_uses_env_override_for_profile_build(self) -> None:
        overlay = {
            "search_focus": {
                "default_title": "Analytics Engineer",
                "titles_by_skill": {
                    "SQL": ["SQL Analyst"],
                },
                "stretch_roles_to_treat_cautiously": [
                    "Roles that are mostly platform engineering",
                ],
            }
        }
        cv_text = """Professional Summary
SQL-focused analyst building reporting workflows.
Core Skills
SQL
"""

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "offerquest.json"
            config_path.write_text(json.dumps(overlay), encoding="utf-8")

            with patch.dict(
                "os.environ",
                {offer_config.CONFIG_PATH_ENVVAR: str(config_path)},
                clear=False,
            ):
                offer_config.reset_to_defaults()
                profile = build_candidate_profile(cv_text, "")

        self.assertEqual(profile["search_focus"]["priority_titles"][0], "Analytics Engineer")
        self.assertIn("SQL Analyst", profile["search_focus"]["priority_titles"])
        self.assertEqual(
            profile["search_focus"]["stretch_roles_to_treat_cautiously"],
            ["Roles that are mostly platform engineering"],
        )

    def test_cli_parser_accepts_offerquest_config_flag(self) -> None:
        parser = build_parser()

        args = parser.parse_args(
            [
                "--offerquest-config",
                "config/custom.json",
                "build-profile",
                "--cv",
                "data/cv.txt",
                "--cover-letter",
                "data/cl.txt",
            ]
        )

        self.assertEqual(args.offerquest_config, Path("config/custom.json"))


if __name__ == "__main__":
    unittest.main()
