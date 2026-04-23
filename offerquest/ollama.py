from __future__ import annotations

import json
import os
import re
import shutil
import signal
import socket
import subprocess
import time
from pathlib import Path
from typing import Any, Callable
from urllib.error import URLError
from urllib.request import Request, urlopen

from .errors import OllamaError


DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434"
OLLAMA_LINUX_AMD64_DOWNLOAD_URL = "https://ollama.com/download/ollama-linux-amd64.tar.zst"
ProgressCallback = Callable[[dict[str, Any]], None]
RECOMMENDED_OLLAMA_MODELS = (
    "qwen3:8b",
    "gemma3:12b",
    "qwen3:14b",
)
STRETCH_OLLAMA_MODELS = (
    "gpt-oss:20b",
    "mistral-small",
)
LIGHTWEIGHT_OLLAMA_MODELS = (
    "qwen3:4b",
    "gemma3:4b",
)
OLLAMA_MODEL_METADATA: dict[str, dict[str, str]] = {
    "qwen3:4b": {
        "size_label": "2.5GB",
        "context_label": "256K",
        "summary": "Lightweight fallback when GPU setup is still incomplete.",
    },
    "qwen3:8b": {
        "size_label": "5.2GB",
        "context_label": "40K",
        "summary": "Balanced default for local writing quality and latency.",
    },
    "qwen3:14b": {
        "size_label": "9.3GB",
        "context_label": "40K",
        "summary": "Higher-quality writing pass that still fits many 12GB GPUs.",
    },
    "gemma3:4b": {
        "size_label": "3.3GB",
        "context_label": "128K",
        "summary": "Smaller long-context option for CPU or tighter VRAM budgets.",
    },
    "gemma3:12b": {
        "size_label": "8.1GB",
        "context_label": "128K",
        "summary": "Strong single-GPU option with longer context for job materials.",
    },
    "gpt-oss:20b": {
        "size_label": "14GB",
        "context_label": "128K",
        "summary": "Reasoning-heavy stretch model if you have extra VRAM headroom.",
    },
    "mistral-small": {
        "size_label": "14GB",
        "context_label": "32K",
        "summary": "Stretch option for stronger general reasoning on bigger GPUs.",
    },
}
GPU_VENDOR_NAMES = {
    "0x1002": "AMD",
    "0x1022": "AMD",
    "0x10de": "NVIDIA",
    "0x8086": "Intel",
}


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

    repo_wrapper = _repo_root() / "scripts" / "ollama-local.sh"
    if repo_wrapper.exists():
        if resolve_local_ollama_binary() is not None:
            return ["bash", str(repo_wrapper)]
        system_binary = shutil.which("ollama")
        if system_binary:
            return ["bash", str(repo_wrapper)]
        return None

    system_binary = shutil.which("ollama")
    if system_binary:
        return [system_binary]

    return None


def describe_ollama_command_source(command: list[str] | None) -> str | None:
    if not command:
        return None
    command_text = " ".join(command)
    if command_text == os.getenv("OFFERQUEST_OLLAMA_COMMAND", ""):
        return "env_override"
    if "ollama-local.sh" in command_text:
        return "repo_local_wrapper"
    return "system_binary"


def resolve_local_ollama_binary() -> Path | None:
    for candidate in (
        _repo_root() / ".tools" / "ollama" / "bin" / "ollama",
        _repo_root() / ".tools" / "ollama-partial" / "bin" / "ollama",
    ):
        if candidate.exists() and os.access(candidate, os.X_OK):
            return candidate
    return None


def has_local_ollama_runtime() -> bool:
    return resolve_local_ollama_binary() is not None


def has_local_ollama_installer() -> bool:
    return _local_ollama_installer_path().exists()


def install_local_ollama_runtime(
    *,
    progress_callback: ProgressCallback | None = None,
) -> dict[str, Any]:
    installer = _local_ollama_installer_path()
    if not installer.exists():
        raise OllamaError("The local Ollama installer script was not found in this repository.")

    archive_path = _local_ollama_archive_path()
    download_path = archive_path.with_name(f"{archive_path.name}.download")
    install_dir = _local_ollama_install_dir()
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    install_dir.mkdir(parents=True, exist_ok=True)

    if archive_path.exists() and _validate_archive_path(archive_path):
        _emit_progress(
            progress_callback,
            progress=75,
            message="Using cached Ollama archive",
            detail=str(archive_path),
        )
    else:
        if archive_path.exists():
            archive_path.unlink(missing_ok=True)
        _download_file_with_progress(
            OLLAMA_LINUX_AMD64_DOWNLOAD_URL,
            download_path,
            progress_callback=progress_callback,
            progress_start=2,
            progress_end=82,
        )
        _emit_progress(
            progress_callback,
            progress=84,
            message="Validating Ollama archive",
            detail="Checking downloaded archive integrity.",
        )
        if not _validate_archive_path(download_path):
            download_path.unlink(missing_ok=True)
            raise OllamaError(
                "Downloaded archive failed integrity validation. The partial file was removed; try again to download a clean copy."
            )
        download_path.replace(archive_path)

    _emit_progress(
        progress_callback,
        progress=90,
        message="Extracting Ollama runtime",
        detail=f"Installing runtime under {install_dir}.",
    )
    for child_name in ("bin", "lib"):
        child_path = install_dir / child_name
        if child_path.exists():
            shutil.rmtree(child_path)
    completed = subprocess.run(
        [
            "tar",
            "--use-compress-program=unzstd",
            "-xf",
            str(archive_path),
            "-C",
            str(install_dir),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        detail = _summarize_process_output(completed.stderr, completed.stdout)
        if not detail:
            detail = f"Extraction exited with code {completed.returncode}."
        raise OllamaError(f"Local Ollama runtime extraction failed. {detail}")

    command = resolve_ollama_command()
    local_runtime = resolve_local_ollama_binary()
    _emit_progress(
        progress_callback,
        progress=100,
        message="Local Ollama runtime is ready",
        detail=str(local_runtime) if local_runtime else "Runtime extracted.",
    )
    return {
        "command": command or [],
        "command_source": describe_ollama_command_source(command),
        "local_runtime_path": str(local_runtime) if local_runtime else None,
        "stdout": f"Installed local Ollama runtime to {install_dir}",
        "stderr": (completed.stderr or "").strip(),
    }


def get_managed_ollama_server_state() -> dict[str, Any]:
    pid_path = _managed_ollama_pid_path()
    log_path = _managed_ollama_log_path()
    pid = _read_managed_pid(pid_path)
    running = bool(pid and _pid_is_running(pid))
    if pid is not None and not running:
        pid_path.unlink(missing_ok=True)
        pid = None
    return {
        "running": running,
        "pid": pid,
        "pid_path": str(pid_path),
        "log_path": str(log_path),
    }


def restart_managed_ollama_server(
    *,
    base_url: str = DEFAULT_OLLAMA_BASE_URL,
    startup_timeout_seconds: int = 12,
) -> dict[str, Any]:
    command = resolve_ollama_command()
    if command is None:
        raise OllamaError(
            "Ollama CLI was not found. Download the local runtime first, or install Ollama system-wide."
        )

    server_state = get_managed_ollama_server_state()
    current_status = get_ollama_status(base_url, timeout_seconds=1)
    if current_status.get("reachable") and not server_state.get("running"):
        raise OllamaError(
            f"Ollama is already reachable at `{base_url}`, but it was not started by OfferQuest. Restart it from the same terminal or service manager that launched it."
        )

    if server_state.get("running") and server_state.get("pid"):
        _stop_managed_ollama_process(int(server_state["pid"]))

    log_path = _managed_ollama_log_path()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as log_handle:
        process = subprocess.Popen(
            [*command, "serve"],
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
            close_fds=True,
            text=True,
        )

    _managed_ollama_pid_path().write_text(f"{process.pid}\n", encoding="utf-8")
    last_status = get_ollama_status(base_url, timeout_seconds=1)
    deadline = time.monotonic() + startup_timeout_seconds
    while time.monotonic() < deadline:
        if process.poll() is not None:
            break
        last_status = get_ollama_status(base_url, timeout_seconds=1)
        if last_status.get("reachable"):
            return {
                "base_url": base_url,
                "pid": process.pid,
                "log_path": str(log_path),
                "ollama_status": last_status,
                "restarted_existing": bool(server_state.get("running")),
            }
        time.sleep(0.5)

    if process.poll() is not None:
        _managed_ollama_pid_path().unlink(missing_ok=True)
    log_tail = _read_log_tail(log_path)
    detail = (
        f" Recent log output: {log_tail}"
        if log_tail
        else " Check the managed server log for details."
    )
    raise OllamaError(
        f"Ollama did not become reachable at `{base_url}` within {startup_timeout_seconds} seconds.{detail}"
    )


def detect_gpu_environment() -> dict[str, Any]:
    devices: list[dict[str, Any]] = []
    seen: set[tuple[str | None, str | None, str | None]] = set()

    for device in _detect_nvidia_gpus():
        key = (
            str(device.get("vendor_id") or ""),
            str(device.get("device_id") or ""),
            str(device.get("name") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        devices.append(device)

    for device in _detect_drm_gpus():
        key = (
            str(device.get("vendor_id") or ""),
            str(device.get("device_id") or ""),
            str(device.get("name") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        devices.append(device)

    discrete_devices = [
        device for device in devices if device.get("vendor") in {"NVIDIA", "AMD"}
    ]
    primary_device = discrete_devices[0] if discrete_devices else (devices[0] if devices else None)

    accelerator_status = "none"
    summary = "No GPU detected."
    detail = "OfferQuest will rely on CPU inference, so smaller models are the safer default."

    if primary_device and primary_device.get("vendor") == "NVIDIA":
        summary = f"NVIDIA GPU detected: {primary_device.get('name') or 'Unknown GPU'}."
        if primary_device.get("smi_ok"):
            accelerator_status = "ready"
            detail = "The NVIDIA runtime looks healthy for Ollama GPU acceleration."
        else:
            accelerator_status = "driver_issue"
            detail = (
                "The NVIDIA driver is present, but `nvidia-smi` could not talk to it, "
                "so Ollama may fall back to CPU until that is fixed."
            )
    elif primary_device and primary_device.get("vendor") == "AMD":
        accelerator_status = "possible"
        summary = f"AMD GPU detected: {primary_device.get('name') or 'Unknown GPU'}."
        detail = "Ollama can use supported AMD GPUs on Linux when the ROCm runtime is installed."
    elif primary_device:
        summary = f"Graphics detected: {primary_device.get('name') or primary_device.get('vendor') or 'Unknown GPU'}."
        detail = "A discrete Ollama acceleration target was not verified, so lighter models remain the safer option."

    return {
        "device_count": len(devices),
        "devices": devices,
        "primary_device": primary_device,
        "accelerator_status": accelerator_status,
        "summary": summary,
        "detail": detail,
    }


def build_ollama_model_cards(model_names: list[str] | tuple[str, ...]) -> list[dict[str, str]]:
    cards: list[dict[str, str]] = []
    for model_name in model_names:
        metadata = OLLAMA_MODEL_METADATA.get(model_name, {})
        cards.append(
            {
                "name": model_name,
                "size_label": str(metadata.get("size_label") or "Unknown"),
                "context_label": str(metadata.get("context_label") or "Unknown"),
                "summary": str(metadata.get("summary") or ""),
            }
        )
    return cards


def pull_ollama_model(
    *,
    model: str,
    base_url: str = DEFAULT_OLLAMA_BASE_URL,
    progress_callback: ProgressCallback | None = None,
    timeout_seconds: int = 1800,
) -> dict[str, Any]:
    last_chunk: dict[str, Any] = {}
    for chunk in _iter_post_json_stream(
        f"{base_url}/api/pull",
        {"model": model, "stream": True},
        timeout_seconds=timeout_seconds,
    ):
        last_chunk = chunk
        if chunk.get("error"):
            raise OllamaError(str(chunk["error"]))
        _emit_progress(progress_callback, **chunk)
    return last_chunk


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
    chunks = list(
        _iter_post_json_stream(
            url,
            payload,
            timeout_seconds=timeout_seconds,
        )
    )
    if not chunks:
        raise OllamaError("Ollama returned an empty streamed response.")
    return chunks


def _iter_post_json_stream(
    url: str,
    payload: dict[str, Any],
    *,
    timeout_seconds: int = 60,
):
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
    yielded = False
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            for raw_line in response:
                line = raw_line.decode("utf-8").strip()
                if not line:
                    continue
                try:
                    yielded = True
                    yield json.loads(line)
                except json.JSONDecodeError as exc:
                    raise OllamaError("Ollama returned invalid streamed JSON.") from exc
    except (TimeoutError, socket.timeout) as exc:
        raise OllamaError(
            f"Ollama request timed out after {timeout_seconds} seconds."
        ) from exc
    except URLError as exc:
        raise OllamaError(str(exc.reason) if hasattr(exc, "reason") else str(exc)) from exc

    if not yielded:
        raise OllamaError("Ollama returned an empty streamed response.")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _local_ollama_installer_path() -> Path:
    return _repo_root() / "scripts" / "install-ollama-local.sh"


def _local_ollama_archive_path() -> Path:
    return _repo_root() / ".tools" / "ollama-linux-amd64.tar.zst"


def _local_ollama_install_dir() -> Path:
    return _repo_root() / ".tools" / "ollama"


def _managed_ollama_pid_path() -> Path:
    return _repo_root() / ".ollama-home" / "offerquest-managed-ollama.pid"


def _managed_ollama_log_path() -> Path:
    return _repo_root() / ".ollama-home" / "offerquest-managed-ollama.log"


def _read_managed_pid(pid_path: Path) -> int | None:
    if not pid_path.exists():
        return None
    try:
        pid = int(pid_path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        pid_path.unlink(missing_ok=True)
        return None
    return pid if pid > 0 else None


def _pid_is_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _stop_managed_ollama_process(pid: int, *, timeout_seconds: int = 5) -> None:
    try:
        os.killpg(pid, signal.SIGTERM)
    except ProcessLookupError:
        _managed_ollama_pid_path().unlink(missing_ok=True)
        return
    except PermissionError:
        os.kill(pid, signal.SIGTERM)

    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if not _pid_is_running(pid):
            _managed_ollama_pid_path().unlink(missing_ok=True)
            return
        time.sleep(0.2)

    try:
        os.killpg(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    except PermissionError:
        os.kill(pid, signal.SIGKILL)
    _managed_ollama_pid_path().unlink(missing_ok=True)


def _read_log_tail(path: Path, *, max_lines: int = 4) -> str:
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return ""
    tail = [line.strip() for line in lines[-max_lines:] if line.strip()]
    return " | ".join(tail)


def _detect_nvidia_gpus() -> list[dict[str, Any]]:
    nvidia_root = Path("/proc/driver/nvidia/gpus")
    if not nvidia_root.exists():
        return []

    driver_version = _extract_version(_read_text(Path("/proc/driver/nvidia/version")))
    smi_probe = _run_optional_command(["nvidia-smi", "-L"])
    devices: list[dict[str, Any]] = []
    for info_path in sorted(nvidia_root.glob("*/information")):
        info = _parse_key_value_file(info_path)
        devices.append(
            {
                "vendor": "NVIDIA",
                "vendor_id": "0x10de",
                "device_id": None,
                "name": info.get("Model") or "NVIDIA GPU",
                "bus_location": info.get("Bus Location") or info_path.parent.name,
                "driver_version": driver_version,
                "smi_ok": smi_probe["ok"],
                "smi_error": smi_probe["error"],
            }
        )
    return devices


def _detect_drm_gpus() -> list[dict[str, Any]]:
    drm_root = Path("/sys/class/drm")
    if not drm_root.exists():
        return []

    devices: list[dict[str, Any]] = []
    for candidate in sorted(drm_root.iterdir()):
        if not re.fullmatch(r"card\d+", candidate.name):
            continue
        device_dir = candidate / "device"
        vendor_id = _read_first_line(device_dir / "vendor")
        device_id = _read_first_line(device_dir / "device")
        if vendor_id is None and device_id is None:
            continue
        vendor = GPU_VENDOR_NAMES.get((vendor_id or "").lower(), vendor_id or "Unknown")
        devices.append(
            {
                "vendor": vendor,
                "vendor_id": vendor_id,
                "device_id": device_id,
                "name": _format_generic_gpu_name(vendor, device_id),
                "bus_location": candidate.name,
                "driver_version": _read_first_line(device_dir / "driver" / "module" / "version"),
                "smi_ok": None,
                "smi_error": None,
            }
        )
    return devices


def _format_generic_gpu_name(vendor: str, device_id: str | None) -> str:
    if device_id:
        return f"{vendor} GPU ({device_id})"
    return f"{vendor} GPU"


def _run_optional_command(command: list[str], *, timeout_seconds: int = 5) -> dict[str, Any]:
    binary = shutil.which(command[0])
    if binary is None:
        return {
            "available": False,
            "ok": False,
            "output": "",
            "error": f"{command[0]} was not found.",
        }

    try:
        completed = subprocess.run(
            [binary, *command[1:]],
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout_seconds,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "available": True,
            "ok": False,
            "output": "",
            "error": str(exc),
        }

    output = (completed.stdout or completed.stderr or "").strip()
    return {
        "available": True,
        "ok": completed.returncode == 0,
        "output": output,
        "error": None if completed.returncode == 0 else output or f"{command[0]} exited with code {completed.returncode}.",
    }


def _download_file_with_progress(
    url: str,
    destination: Path,
    *,
    progress_callback: ProgressCallback | None,
    progress_start: float,
    progress_end: float,
) -> None:
    destination.unlink(missing_ok=True)
    request = Request(url, headers={"User-Agent": "OfferQuest/ollama-runtime-installer"})
    _emit_progress(
        progress_callback,
        progress=progress_start,
        message="Downloading local Ollama runtime",
        detail="Connecting to Ollama download service.",
    )
    try:
        with urlopen(request, timeout=60) as response:
            total = _parse_content_length(response.headers.get("Content-Length"))
            downloaded = 0
            last_emit = 0.0
            with destination.open("wb") as output:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    output.write(chunk)
                    downloaded += len(chunk)
                    now = time.monotonic()
                    if now - last_emit < 0.25 and total and downloaded < total:
                        continue
                    last_emit = now
                    if total:
                        fraction = min(downloaded / total, 1.0)
                        progress = progress_start + (progress_end - progress_start) * fraction
                    else:
                        progress = progress_start
                    _emit_progress(
                        progress_callback,
                        progress=progress,
                        message="Downloading local Ollama runtime",
                        detail=_format_transfer_detail(downloaded, total),
                        completed_bytes=downloaded,
                        total_bytes=total,
                    )
    except (TimeoutError, socket.timeout) as exc:
        destination.unlink(missing_ok=True)
        raise OllamaError("Ollama runtime download timed out.") from exc
    except URLError as exc:
        destination.unlink(missing_ok=True)
        raise OllamaError(str(exc.reason) if hasattr(exc, "reason") else str(exc)) from exc
    except OSError as exc:
        destination.unlink(missing_ok=True)
        raise OllamaError(f"Could not write Ollama runtime download to {destination}.") from exc


def _validate_archive_path(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        completed = subprocess.run(
            ["zstd", "-t", str(path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
    except FileNotFoundError as exc:
        raise OllamaError("zstd is required to verify the Ollama archive.") from exc
    return completed.returncode == 0


def _emit_progress(progress_callback: ProgressCallback | None, **payload: Any) -> None:
    if progress_callback is not None:
        progress_callback(payload)


def _parse_content_length(raw_value: str | None) -> int | None:
    if raw_value is None:
        return None
    try:
        value = int(raw_value)
    except ValueError:
        return None
    return value if value >= 0 else None


def _format_transfer_detail(completed: int, total: int | None) -> str:
    if total:
        return f"{_format_bytes(completed)} of {_format_bytes(total)} downloaded."
    return f"{_format_bytes(completed)} downloaded."


def _format_bytes(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024


def _summarize_process_output(*parts: str | None, max_lines: int = 8) -> str:
    lines: list[str] = []
    for part in parts:
        if not part:
            continue
        for raw_line in part.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            lines.append(_redact_signed_urls(line))
    return "\n".join(lines[-max_lines:])


def _redact_signed_urls(line: str) -> str:
    line = re.sub(
        r"https://release-assets\.githubusercontent\.com/\S+",
        "https://release-assets.githubusercontent.com/... [signed asset URL redacted]",
        line,
    )
    return re.sub(r"(https://\S+?)\?\S+", r"\1?...", line)


def _parse_key_value_file(path: Path) -> dict[str, str]:
    payload: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return payload
    for line in lines:
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        payload[key.strip()] = value.strip()
    return payload


def _extract_version(raw_text: str) -> str | None:
    match = re.search(r"\b(\d+\.\d+\.\d+)\b", raw_text)
    return match.group(1) if match else None


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def _read_first_line(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="ignore").splitlines()[0].strip()
    except (IndexError, OSError):
        return None
