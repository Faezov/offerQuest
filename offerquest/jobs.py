from __future__ import annotations

import hashlib
import html
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .extractors import normalize_text, read_document_text

SUPPORTED_MANUAL_JOB_SUFFIXES = {".txt", ".md", ".doc", ".odt"}
SUPPORTED_JOB_RECORD_SUFFIXES = {".json", ".jsonl"}


def fetch_adzuna_jobs(
    *,
    app_id: str,
    app_key: str,
    what: str | None = None,
    where: str | None = None,
    country: str = "au",
    page: int = 1,
    results_per_page: int = 20,
) -> list[dict]:
    params = {
        "app_id": app_id,
        "app_key": app_key,
        "results_per_page": results_per_page,
        "content-type": "application/json",
    }
    if what:
        params["what"] = what
    if where:
        params["where"] = where

    query = urlencode(params)
    url = f"https://api.adzuna.com/v1/api/jobs/{country}/search/{page}?{query}"
    payload = fetch_json(url)
    results = payload.get("results", [])
    return [normalize_adzuna_job(result, country=country) for result in results]


def fetch_greenhouse_jobs(board_token: str) -> list[dict]:
    board_url = f"https://boards-api.greenhouse.io/v1/boards/{board_token}"
    jobs_url = f"https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs?content=true"

    board_payload = fetch_json(board_url)
    jobs_payload = fetch_json(jobs_url)

    company = board_payload.get("name") or board_token
    results = jobs_payload.get("jobs", [])
    return [
        normalize_greenhouse_job(job, board_token=board_token, company=company)
        for job in results
    ]


def fetch_json(url: str, *, timeout: int = 30) -> dict[str, Any]:
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "OfferQuest/0.1.0",
        },
    )
    with urlopen(request, timeout=timeout) as response:
        body = response.read().decode("utf-8")
    return json.loads(body)


def normalize_adzuna_job(job: dict[str, Any], *, country: str) -> dict:
    company = value_at(job, "company", "display_name")
    location = value_at(job, "location", "display_name")
    category = value_at(job, "category", "label")
    salary_is_predicted = bool(job.get("salary_is_predicted"))

    metadata = {
        "category": category,
        "contract_time": job.get("contract_time"),
        "contract_type": job.get("contract_type"),
        "salary_is_predicted": salary_is_predicted,
    }

    return normalize_job_record(
        {
            "source": "adzuna",
            "external_id": str(job.get("id") or ""),
            "title": job.get("title"),
            "company": company,
            "location": location,
            "country": country,
            "description_text": clean_text(job.get("description", "")),
            "employment_type": job.get("contract_type") or job.get("contract_time"),
            "salary_min": job.get("salary_min"),
            "salary_max": job.get("salary_max"),
            "currency": job.get("salary_currency"),
            "url": job.get("redirect_url"),
            "posted_at": job.get("created"),
            "fetched_at": now_iso(),
            "metadata": drop_none(metadata),
        }
    )


def normalize_greenhouse_job(job: dict[str, Any], *, board_token: str, company: str) -> dict:
    departments = [
        item.get("name")
        for item in job.get("departments", [])
        if item.get("name")
    ]
    offices = [
        item.get("name")
        for item in job.get("offices", [])
        if item.get("name")
    ]

    metadata = {
        "board_token": board_token,
        "departments": departments,
        "offices": offices,
        "language": job.get("language"),
        "internal_job_id": job.get("internal_job_id"),
        "metadata": job.get("metadata"),
    }

    return normalize_job_record(
        {
            "source": "greenhouse",
            "external_id": str(job.get("id") or ""),
            "title": job.get("title"),
            "company": company,
            "location": value_at(job, "location", "name"),
            "description_text": html_to_text(job.get("content", "")),
            "url": job.get("absolute_url"),
            "posted_at": job.get("updated_at"),
            "fetched_at": now_iso(),
            "metadata": drop_none(metadata),
        }
    )


def import_manual_jobs(path: str | Path) -> list[dict]:
    input_path = Path(path)
    if input_path.is_file():
        return [manual_job_record_from_file(input_path)]

    paths = sorted(
        file_path
        for file_path in input_path.rglob("*")
        if file_path.is_file()
        and file_path.suffix.lower() in SUPPORTED_MANUAL_JOB_SUFFIXES
        and not file_path.name.lower().startswith("readme")
    )
    return [manual_job_record_from_file(file_path) for file_path in paths]


def manual_job_record_from_file(path: Path) -> dict:
    text = read_document_text(path)
    title = infer_manual_title(text, fallback=path.stem.replace("_", " ").replace("-", " "))
    company, location = infer_manual_company_and_location(text, title=title)
    return normalize_job_record(
        {
            "source": "manual",
            "external_id": str(path.resolve()),
            "title": title,
            "company": company,
            "location": location,
            "description_text": text,
            "url": str(path.resolve()),
            "fetched_at": now_iso(),
            "metadata": {
                "input_path": str(path),
            },
        }
    )


def infer_manual_title(text: str, *, fallback: str) -> str:
    for line in [line.strip() for line in text.splitlines() if line.strip()]:
        if len(line.split()) <= 14 and not line.endswith("."):
            return line
    return fallback


def infer_manual_company_and_location(text: str, *, title: str) -> tuple[str | None, str | None]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    try:
        title_index = lines.index(title)
    except ValueError:
        title_index = -1

    header_lines = [
        line
        for line in lines[title_index + 1 : title_index + 4]
        if len(line.split()) <= 10 and not line.endswith(".")
    ]

    if not header_lines:
        return None, None

    first_line = header_lines[0]
    if "," in first_line:
        possible_company, possible_location = [part.strip() for part in first_line.split(",", 1)]
        if possible_company and possible_location and looks_like_location(possible_location):
            return possible_company, possible_location

    company = first_line if not looks_like_location(first_line) else None
    location = None

    for line in header_lines[1:]:
        if looks_like_location(line):
            location = line
            break

    return company, location


def normalize_job_record(record: dict[str, Any]) -> dict:
    normalized = {
        "id": record.get("id") or build_job_record_id(record),
        "source": record.get("source") or "unknown",
        "external_id": string_or_none(record.get("external_id")),
        "title": string_or_none(record.get("title")),
        "company": string_or_none(record.get("company")),
        "location": string_or_none(record.get("location")),
        "country": string_or_none(record.get("country")),
        "description_text": clean_text(record.get("description_text", "")),
        "employment_type": string_or_none(record.get("employment_type")),
        "salary_min": number_or_none(record.get("salary_min")),
        "salary_max": number_or_none(record.get("salary_max")),
        "currency": string_or_none(record.get("currency")),
        "url": string_or_none(record.get("url")),
        "posted_at": string_or_none(record.get("posted_at")),
        "fetched_at": string_or_none(record.get("fetched_at")) or now_iso(),
        "metadata": record.get("metadata") or {},
    }
    return normalized


def build_job_record_id(record: dict[str, Any]) -> str:
    source = record.get("source") or "unknown"
    external_id = record.get("external_id")
    if external_id:
        return f"{source}:{external_id}"

    fingerprint = "|".join(
        [
            source,
            str(record.get("title") or ""),
            str(record.get("company") or ""),
            str(record.get("location") or ""),
            str(record.get("url") or ""),
        ]
    )
    digest = hashlib.sha1(fingerprint.encode("utf-8")).hexdigest()[:16]
    return f"{source}:{digest}"


def merge_job_record_sets(*record_sets: list[dict]) -> list[dict]:
    merged: dict[str, dict] = {}
    for record_set in record_sets:
        for record in record_set:
            normalized = normalize_job_record(record)
            dedupe_key = choose_dedupe_key(normalized)
            if dedupe_key in merged:
                merged[dedupe_key] = merge_two_job_records(merged[dedupe_key], normalized)
            else:
                merged[dedupe_key] = normalized

    return sorted(merged.values(), key=sort_key_for_record)


def merge_two_job_records(existing: dict, incoming: dict) -> dict:
    merged = dict(existing)
    for key in (
        "title",
        "company",
        "location",
        "country",
        "description_text",
        "employment_type",
        "salary_min",
        "salary_max",
        "currency",
        "url",
        "posted_at",
    ):
        merged[key] = choose_richer_value(existing.get(key), incoming.get(key))

    merged["metadata"] = {
        **(existing.get("metadata") or {}),
        **(incoming.get("metadata") or {}),
    }
    merged["fetched_at"] = incoming.get("fetched_at") or existing.get("fetched_at")
    return normalize_job_record(merged)


def choose_dedupe_key(record: dict) -> str:
    if record.get("url"):
        return f"url:{record['url']}"
    return record["id"]


def choose_richer_value(existing: Any, incoming: Any) -> Any:
    if is_missing(existing) and not is_missing(incoming):
        return incoming
    if is_missing(incoming):
        return existing
    if isinstance(existing, str) and isinstance(incoming, str) and len(incoming) > len(existing):
        return incoming
    return existing


def is_missing(value: Any) -> bool:
    return value in (None, "", [], {})


def sort_key_for_record(record: dict) -> tuple[str, str, str]:
    return (
        record.get("company") or "",
        record.get("title") or "",
        record.get("id") or "",
    )


def read_job_records(path: str | Path) -> list[dict]:
    job_path = Path(path)
    suffix = job_path.suffix.lower()

    if suffix == ".jsonl":
        records = [
            normalize_job_record(json.loads(line))
            for line in job_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        return records

    payload = json.loads(job_path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return [normalize_job_record(item) for item in payload]
    if isinstance(payload, dict) and "jobs" in payload:
        return [normalize_job_record(item) for item in payload["jobs"]]

    raise ValueError(f"Unsupported job records payload in {job_path}")


def write_job_records(path: str | Path, records: list[dict]) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    normalized = [normalize_job_record(record) for record in records]

    if output_path.suffix.lower() == ".jsonl":
        text = "\n".join(json.dumps(record, sort_keys=True) for record in normalized)
        if text:
            text += "\n"
        output_path.write_text(text, encoding="utf-8")
        return

    output_path.write_text(json.dumps(normalized, indent=2), encoding="utf-8")


def collect_job_record_inputs(paths: list[str | Path]) -> list[dict]:
    record_sets: list[list[dict]] = []
    for raw_path in paths:
        path = Path(raw_path)
        if path.is_dir():
            files = sorted(
                file_path
                for file_path in path.rglob("*")
                if file_path.is_file()
                and file_path.suffix.lower() in SUPPORTED_JOB_RECORD_SUFFIXES
                and not file_path.name.lower().startswith("readme")
            )
            record_sets.extend(read_job_records(file_path) for file_path in files)
        else:
            record_sets.append(read_job_records(path))

    return merge_job_record_sets(*record_sets)


def find_job_record(records: list[dict], job_id: str) -> dict | None:
    for record in records:
        if record.get("id") == job_id:
            return record
    return None


def job_record_to_text(record: dict) -> str:
    metadata = record.get("metadata") or {}
    metadata_lines: list[str] = []

    if metadata.get("category"):
        metadata_lines.append(str(metadata["category"]))
    if metadata.get("departments"):
        metadata_lines.append("Departments: " + ", ".join(metadata["departments"]))
    if metadata.get("offices"):
        metadata_lines.append("Offices: " + ", ".join(metadata["offices"]))

    salary_line = format_salary(record)

    lines = [
        record.get("title") or "",
        record.get("company") or "",
        record.get("location") or "",
        record.get("employment_type") or "",
        salary_line,
        *metadata_lines,
        record.get("description_text") or "",
    ]
    return normalize_text("\n".join(line for line in lines if line))


def format_salary(record: dict) -> str:
    salary_min = record.get("salary_min")
    salary_max = record.get("salary_max")
    currency = record.get("currency") or ""

    if salary_min is None and salary_max is None:
        return ""
    if salary_min is not None and salary_max is not None:
        return f"Salary: {salary_min:g}-{salary_max:g} {currency}".strip()
    if salary_min is not None:
        return f"Salary from: {salary_min:g} {currency}".strip()
    return f"Salary up to: {salary_max:g} {currency}".strip()


def html_to_text(value: str) -> str:
    if not value:
        return ""

    text = html.unescape(value)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</(p|div|li|h\d)>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    return clean_text(text)


def clean_text(value: str) -> str:
    return normalize_text(value or "")


def looks_like_location(value: str) -> bool:
    lowered = value.lower()
    location_terms = (
        "sydney",
        "melbourne",
        "brisbane",
        "perth",
        "canberra",
        "nsw",
        "victoria",
        "queensland",
        "australia",
        "remote",
        "hybrid",
        "usa",
        "uk",
        "london",
    )
    return any(term in lowered for term in location_terms)


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def value_at(payload: dict[str, Any], *keys: str) -> Any:
    current: Any = payload
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
        if current is None:
            return None
    return current


def string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def number_or_none(value: Any) -> float | int | None:
    if value in (None, ""):
        return None
    return value


def drop_none(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value not in (None, "", [], {})}


def resolve_adzuna_credentials(
    app_id: str | None,
    app_key: str | None,
) -> tuple[str | None, str | None]:
    return app_id or os.getenv("ADZUNA_APP_ID"), app_key or os.getenv("ADZUNA_APP_KEY")
