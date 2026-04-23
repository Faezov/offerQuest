from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from offerquest.ollama import (
    build_ollama_pull_selection,
    generate_structured_response,
    get_ollama_status,
    select_default_ollama_model,
)


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
        self.assertTrue(status["has_models"])

    def test_select_default_ollama_model_prefers_installed_recommended_model(self) -> None:
        status = {
            "models": [
                {"name": "gemma3:12b"},
                {"name": "custom-model:latest"},
            ]
        }

        model = select_default_ollama_model(status)

        self.assertEqual(model, "gemma3:12b")

    def test_build_ollama_pull_selection_defaults_to_recommended_models(self) -> None:
        models = build_ollama_pull_selection(
            requested_models=[],
            use_recommended=False,
            use_all=False,
        )

        self.assertEqual(models, ["qwen3:8b", "gemma3:12b", "qwen3:14b"])

    def test_generate_structured_response_parses_json_content(self) -> None:
        payload = {
            "message": {
                "content": '{"resume_headline":"Senior Data Analyst","cover_letter_text":"Hello","employer_specific_focus":[],"evidence_used":[],"caution_flags":[]}'
            }
        }
        schema = {"type": "object"}

        with patch(
            "offerquest.ollama._post_json_stream",
            return_value=[{"message": {"content": payload["message"]["content"]}, "done": True}],
        ):
            response = generate_structured_response(
                model="qwen3:8b",
                messages=[{"role": "user", "content": "Hi"}],
                schema=schema,
            )

        self.assertEqual(response["resume_headline"], "Senior Data Analyst")

    def test_generate_structured_response_disables_thinking_and_uses_longer_timeout(self) -> None:
        payload = {
            "message": {
                "content": '{"resume_headline":"Senior Data Analyst","cover_letter_text":"Hello","employer_specific_focus":[],"evidence_used":[],"caution_flags":[]}'
            }
        }
        captured: dict[str, object] = {}

        def fake_post_json_stream(url, payload, **kwargs):
            captured["url"] = url
            captured["payload"] = payload
            captured["kwargs"] = kwargs
            return [{"message": {"content": payload_response["message"]["content"]}, "done": True}]

        payload_response = payload

        with patch("offerquest.ollama._post_json_stream", side_effect=fake_post_json_stream):
            generate_structured_response(
                model="qwen3:8b",
                messages=[{"role": "user", "content": "Hi"}],
                schema={"type": "object"},
            )

        self.assertFalse(captured["payload"]["think"])
        self.assertTrue(captured["payload"]["stream"])
        self.assertEqual(captured["kwargs"]["timeout_seconds"], 180)


if __name__ == "__main__":
    unittest.main()
