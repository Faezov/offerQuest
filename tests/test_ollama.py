from __future__ import annotations

import unittest
from unittest.mock import patch

from offerquest.ollama import generate_structured_response, get_ollama_status


class OllamaTests(unittest.TestCase):
    def test_get_ollama_status_returns_models_when_reachable(self) -> None:
        payload = {
            "models": [
                {
                    "name": "qwen3:8b",
                    "size": 123,
                    "modified_at": "2026-04-22T00:00:00Z",
                }
            ]
        }

        with patch("offerquest.ollama._post_json", return_value=payload):
            status = get_ollama_status()

        self.assertTrue(status["reachable"])
        self.assertEqual(status["models"][0]["name"], "qwen3:8b")

    def test_generate_structured_response_parses_json_content(self) -> None:
        payload = {
            "message": {
                "content": '{"resume_headline":"Senior Data Analyst","cover_letter_text":"Hello","employer_specific_focus":[],"evidence_used":[],"caution_flags":[]}'
            }
        }
        schema = {"type": "object"}

        with patch("offerquest.ollama._post_json", return_value=payload):
            response = generate_structured_response(
                model="qwen3:8b",
                messages=[{"role": "user", "content": "Hi"}],
                schema=schema,
            )

        self.assertEqual(response["resume_headline"], "Senior Data Analyst")


if __name__ == "__main__":
    unittest.main()
