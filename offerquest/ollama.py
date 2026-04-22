from __future__ import annotations

import json
import socket
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
    think: bool = False,
    timeout_seconds: int = 180,
) -> dict[str, Any]:
    payload = {
        "model": model,
        "messages": messages,
        "stream": True,
        "format": schema,
        "think": think,
        "options": {
            "temperature": temperature,
        },
    }
    chunks = _post_json_stream(
        f"{base_url}/api/chat",
        payload,
        timeout_seconds=timeout_seconds,
    )
    content_parts: list[str] = []
    for chunk in chunks:
        message = chunk.get("message", {})
        if message.get("content"):
            content_parts.append(message["content"])

    content = "".join(content_parts).strip()
    try:
        return json.loads(content)
    except json.JSONDecodeError as exc:
        raise OllamaError(
            "Ollama returned non-JSON content for a structured response request."
        ) from exc


def _post_json(
    url: str,
    payload: dict[str, Any] | None,
    *,
    method: str = "POST",
    timeout_seconds: int = 60,
) -> dict[str, Any]:
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
        with urlopen(request, timeout=timeout_seconds) as response:
            body = response.read().decode("utf-8")
    except (TimeoutError, socket.timeout) as exc:
        raise OllamaError(
            f"Ollama request timed out after {timeout_seconds} seconds."
        ) from exc
    except URLError as exc:
        raise OllamaError(str(exc.reason) if hasattr(exc, "reason") else str(exc)) from exc

    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise OllamaError("Ollama returned invalid JSON.") from exc


def _post_json_stream(
    url: str,
    payload: dict[str, Any],
    *,
    timeout_seconds: int = 60,
) -> list[dict[str, Any]]:
    data = json.dumps(payload).encode("utf-8")
    request = Request(
        url,
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    chunks: list[dict[str, Any]] = []
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            for raw_line in response:
                line = raw_line.decode("utf-8").strip()
                if not line:
                    continue
                try:
                    chunks.append(json.loads(line))
                except json.JSONDecodeError as exc:
                    raise OllamaError("Ollama returned invalid streamed JSON.") from exc
    except (TimeoutError, socket.timeout) as exc:
        raise OllamaError(
            f"Ollama request timed out after {timeout_seconds} seconds."
        ) from exc
    except URLError as exc:
        raise OllamaError(str(exc.reason) if hasattr(exc, "reason") else str(exc)) from exc

    if not chunks:
        raise OllamaError("Ollama returned an empty streamed response.")
    return chunks
