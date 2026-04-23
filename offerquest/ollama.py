from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

from .errors import OllamaError


DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434"
RECOMMENDED_OLLAMA_MODELS = (
    "qwen3:8b",
    "gemma3:12b",
    "qwen3:14b",
)
STRETCH_OLLAMA_MODELS = (
    "mistral-small",
)


def get_ollama_status(
    base_url: str = DEFAULT_OLLAMA_BASE_URL,
    *,
    timeout_seconds: int = 5,
) -> dict:
    command = resolve_ollama_command()
    command_available = command is not None

    try:
        payload = _post_json(
            f"{base_url}/api/tags",
            None,
            method="GET",
            timeout_seconds=timeout_seconds,
        )
    except OllamaError as exc:
        return {
            "base_url": base_url,
            "reachable": False,
            "models": [],
            "has_models": False,
            "command_available": command_available,
            "command": command or [],
            "command_source": describe_ollama_command_source(command),
            "recommended_models": list(RECOMMENDED_OLLAMA_MODELS),
            "missing_recommended_models": list(RECOMMENDED_OLLAMA_MODELS),
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
    model_names = [str(model.get("name")) for model in models if model.get("name")]
    return {
        "base_url": base_url,
        "reachable": True,
        "models": models,
        "has_models": bool(models),
        "command_available": command_available,
        "command": command or [],
        "command_source": describe_ollama_command_source(command),
        "recommended_models": list(RECOMMENDED_OLLAMA_MODELS),
        "missing_recommended_models": [
            model for model in RECOMMENDED_OLLAMA_MODELS if model not in model_names
        ],
    }


def resolve_ollama_command() -> list[str] | None:
    env_command = os.getenv("OFFERQUEST_OLLAMA_COMMAND")
    if env_command:
        return [env_command]

    repo_wrapper = Path(__file__).resolve().parents[1] / "scripts" / "ollama-local.sh"
    if repo_wrapper.exists():
        return ["bash", str(repo_wrapper)]

    system_binary = shutil.which("ollama")
    if system_binary:
        return [system_binary]

    return None


def describe_ollama_command_source(command: list[str] | None) -> str | None:
    if not command:
        return None
    command_text = " ".join(command)
    if "ollama-local.sh" in command_text:
        return "repo_local_wrapper"
    return "system_binary"


def select_default_ollama_model(
    status: dict[str, Any] | None,
    *,
    explicit_model: str | None = None,
    fallback: str = "qwen3:8b",
) -> str:
    normalized_explicit_model = (explicit_model or "").strip()
    if normalized_explicit_model:
        return normalized_explicit_model

    available_models = [
        str(model.get("name"))
        for model in (status or {}).get("models", [])
        if model.get("name")
    ]
    for model in RECOMMENDED_OLLAMA_MODELS:
        if model in available_models:
            return model
    if available_models:
        return available_models[0]
    return fallback


def build_ollama_pull_selection(
    *,
    requested_models: list[str],
    use_recommended: bool = False,
    use_all: bool = False,
) -> list[str]:
    if requested_models:
        return requested_models
    if use_all:
        return [*RECOMMENDED_OLLAMA_MODELS, *STRETCH_OLLAMA_MODELS]
    if use_recommended or not requested_models:
        return list(RECOMMENDED_OLLAMA_MODELS)
    return []


def run_ollama_cli(
    args: list[str],
    *,
    check: bool = True,
    capture_output: bool = False,
) -> int:
    command = resolve_ollama_command()
    if command is None:
        raise OllamaError(
            "Ollama CLI was not found. Install Ollama first, or set OFFERQUEST_OLLAMA_COMMAND to a custom executable path."
        )

    try:
        run_kwargs: dict[str, Any] = {
            "check": check,
        }
        if capture_output:
            run_kwargs.update(
                {
                    "stdout": subprocess.PIPE,
                    "stderr": subprocess.PIPE,
                    "text": True,
                }
            )
        completed = subprocess.run([*command, *args], **run_kwargs)
    except FileNotFoundError as exc:
        raise OllamaError("Ollama CLI could not be started.") from exc
    except subprocess.CalledProcessError as exc:
        raise OllamaError(f"Ollama command failed with exit code {exc.returncode}.") from exc

    return completed.returncode


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
