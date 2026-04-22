from __future__ import annotations

import json
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen


DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434"


class OllamaError(RuntimeError):
    """Raised when an Ollama request fails."""


def get_ollama_status(base_url: str = DEFAULT_OLLAMA_BASE_URL) -> dict:
    try:
        payload = _post_json(f"{base_url}/api/tags", None, method="GET")
    except OllamaError as exc:
        return {
            "base_url": base_url,
            "reachable": False,
            "models": [],
            "error": str(exc),
        }

    models = [
        {
            "name": model.get("name"),
            "size": model.get("size"),
            "modified_at": model.get("modified_at"),
        }
        for model in payload.get("models", [])
    ]
    return {
        "base_url": base_url,
        "reachable": True,
        "models": models,
    }


def generate_structured_response(
    *,
    model: str,
    messages: list[dict[str, str]],
    schema: dict[str, Any],
    base_url: str = DEFAULT_OLLAMA_BASE_URL,
    temperature: float = 0.2,
) -> dict[str, Any]:
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "format": schema,
        "options": {
            "temperature": temperature,
        },
    }
    response = _post_json(f"{base_url}/api/chat", payload)
    try:
        content = response["message"]["content"]
    except KeyError as exc:
        raise OllamaError("Ollama response did not include message content.") from exc

    try:
        return json.loads(content)
    except json.JSONDecodeError as exc:
        raise OllamaError(
            "Ollama returned non-JSON content for a structured response request."
        ) from exc


def _post_json(url: str, payload: dict[str, Any] | None, *, method: str = "POST") -> dict[str, Any]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(
        url,
        data=data,
        method=method,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urlopen(request, timeout=60) as response:
            body = response.read().decode("utf-8")
    except URLError as exc:
        raise OllamaError(str(exc.reason) if hasattr(exc, "reason") else str(exc)) from exc

    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise OllamaError("Ollama returned invalid JSON.") from exc
