from __future__ import annotations

import ast
import hashlib
import html
import json
import logging
import os
import re
import tempfile
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from .errors import JobSourceError
from .extractors import normalize_text, read_document_text
from .types import JobRecord
from .workspace import now_iso, relative_to_root, slugify

ADZUNA_ENV_PATH_ENVVAR = "OFFERQUEST_ADZUNA_ENV_FILE"
ADZUNA_ENV_FILENAME = "adzuna.env"
SUPPORTED_MANUAL_JOB_SUFFIXES = {".txt", ".md", ".doc", ".docx", ".odt"}
SUPPORTED_JOB_RECORD_SUFFIXES = {".json", ".jsonl"}
SENSITIVE_QUERY_PARAMETERS = frozenset(
    {
        "app_key",
        "api_key",
        "access_key",
        "access_token",
        "key",
        "password",
        "secret",
        "token",
    }
)
logger = logging.getLogger(__name__)
HEADER_LOCATION_ORG_MARKERS = frozenset(
    {
        "agency",
        "clinic",
        "college",
        "company",
        "corp",
        "corporation",
        "council",
        "department",
        "group",
        "health",
        "hospital",
        "inc",
        "institute",
        "lab",
        "labs",
        "llc",
        "ltd",
        "ministry",
        "org",
        "organisation",
        "organization",
        "school",
        "team",
        "university",
    }
)
HEADER_LOCATION_NON_LOCATION_TERMS = frozenset(
    {
        "analyst",
        "analytics",
        "consultant",
        "coordinator",
        "data",
        "developer",
        "director",
        "engineer",
        "engineering",
        "finance",
        "lead",
        "manager",
        "marketing",
        "officer",
        "operations",
        "platform",
        "principal",
        "product",
        "reporting",
        "scientist",
        "senior",
        "specialist",
        "strategy",
        "technology",
    }
)


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


def fetch_adzuna_job_pages(
    *,
    app_id: str,
    app_key: str,
    what: str | None = None,
    where: str | None = None,
    country: str = "au",
    pages: int = 1,
    results_per_page: int = 20,
) -> list[dict]:
    if pages < 1:
        raise JobSourceError("Adzuna pages must be at least 1.")

    extra_metadata = drop_none({"query_what": what, "query_where": where, "query_country": country})
    record_sets: list[list[dict]] = []
    for page in range(1, pages + 1):
        logger.info(
            "Fetching Adzuna page %s/%s for what=%r where=%r country=%s",
            page,
            pages,
            what,
            where,
            country,
        )
        batch = fetch_adzuna_jobs(
            app_id=app_id,
            app_key=app_key,
            what=what,
            where=where,
            country=country,
            page=page,
            results_per_page=results_per_page,
        )
        if not batch:
            logger.info("Adzuna returned no jobs on page %s; stopping early", page)
            break
        record_sets.append(annotate_job_records(batch, extra_metadata=extra_metadata))
    return merge_job_record_sets(*record_sets)


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


def refresh_job_sources(
    config_path: str | Path,
    *,
    workspace_root: str | Path,
    output_dir: str | Path | None = None,
    adzuna_app_id: str | None = None,
    adzuna_app_key: str | None = None,
) -> dict[str, Any]:
    root = Path(workspace_root).resolve()
    config_file = resolve_workspace_path(root, config_path)
    try:
        config = json.loads(config_file.read_text(encoding="utf-8"))
    except OSError as exc:
        raise JobSourceError(f"Could not read job refresh config: {config_file}") from exc
    except json.JSONDecodeError as exc:
        raise JobSourceError(f"Job refresh config is invalid JSON: {config_file}") from exc
    sources = config.get("sources", [])
    if not isinstance(sources, list):
        raise JobSourceError("Job refresh config must contain a `sources` list.")

    output_root = (
        resolve_workspace_path(
            root,
            output_dir,
            must_stay_inside=True,
            label="Job refresh output directory",
        )
        if output_dir is not None
        else root / "outputs" / "jobs"
    )
    output_root.mkdir(parents=True, exist_ok=True)
    logger.info("Refreshing job sources from %s into %s", config_file, output_root)

    refreshed_sources: list[dict[str, Any]] = []
    generated_outputs: list[Path] = []
    adzuna_credentials: tuple[str | None, str | None] | None = None

    for source in sources:
        if not isinstance(source, dict):
            raise JobSourceError("Each job source config entry must be an object.")
        if source.get("enabled", True) is False:
            continue

        source_type = str(source.get("type") or "").strip().lower()
        source_name = str(source.get("name") or source.get("output") or source_type).strip()
        if not source_type or not source_name:
            raise JobSourceError("Each enabled job source needs both `type` and `name`.")

        output_name = str(source.get("output") or f"{slugify(source_name, fallback='jobs')}.jsonl").strip()
        if not output_name:
            raise JobSourceError(f"Job source `{source_name}` is missing an output filename.")
        output_path = resolve_refresh_output_path(
            output_root,
            output_name,
            label=f"Output path for job source `{source_name}`",
        )
        logger.info("Refreshing source %s (%s)", source_name, source_type)

        if source_type == "adzuna":
            if adzuna_credentials is None:
                adzuna_credentials = resolve_adzuna_credentials(adzuna_app_id, adzuna_app_key)
            app_id, app_key = adzuna_credentials
            if not app_id or not app_key:
                raise JobSourceError(
                    "Adzuna credentials are required for refresh sources with type `adzuna`."
                )

            records = annotate_job_records(
                fetch_adzuna_job_pages(
                    app_id=app_id,
                    app_key=app_key,
                    what=string_or_none(source.get("what")),
                    where=string_or_none(source.get("where")),
                    country=string_or_none(source.get("country")) or "au",
                    pages=int(source.get("pages") or 1),
                    results_per_page=int(source.get("results_per_page") or 20),
                ),
                extra_metadata={"source_name": source_name},
            )
        elif source_type == "greenhouse":
            board_token = string_or_none(source.get("board_token"))
            if not board_token:
                raise JobSourceError(
                    f"Greenhouse source `{source_name}` is missing `board_token`."
                )
            records = annotate_job_records(
                fetch_greenhouse_jobs(board_token),
                extra_metadata={"source_name": source_name},
            )
        elif source_type == "manual":
            input_path = string_or_none(source.get("input_path"))
            if not input_path:
                raise JobSourceError(f"Manual source `{source_name}` is missing `input_path`.")
            records = annotate_job_records(
                import_manual_jobs(resolve_workspace_path(root, input_path)),
                extra_metadata={"source_name": source_name},
            )
        else:
            raise JobSourceError(f"Unsupported job source type: {source_type}")

        write_job_records(output_path, records)
        logger.info("Wrote %s job records for %s to %s", len(records), source_name, output_path)
        generated_outputs.append(output_path)
        refreshed_sources.append(
            {
                "name": source_name,
                "type": source_type,
                "job_count": len(records),
                "output": str(relative_to_root(output_path, root)),
            }
        )

    merge_config = config.get("merge") if isinstance(config.get("merge"), dict) else {}
    merge_enabled = bool(merge_config.get("enabled", True))
    merged_output_path: Path | None = None
    merged_job_count = 0

    if merge_enabled:
        merge_inputs = merge_config.get("inputs")
        if merge_inputs is not None and not isinstance(merge_inputs, list):
            raise JobSourceError("Job refresh config `merge.inputs` must be a list when provided.")

        if merge_inputs:
            input_paths = [resolve_refresh_input_path(output_root, item) for item in merge_inputs]
        else:
            input_paths = generated_outputs

        merged_records = collect_job_record_inputs(input_paths)
        merged_output_name = str(merge_config.get("output") or "all.jsonl").strip()
        if not merged_output_name:
            raise JobSourceError("Job refresh config merge output cannot be empty.")
        merged_output_path = resolve_refresh_output_path(
            output_root,
            merged_output_name,
            label="Job refresh merge output path",
        )
        write_job_records(merged_output_path, merged_records)
        merged_job_count = len(merged_records)
        logger.info("Merged %s job records into %s", merged_job_count, merged_output_path)

    summary_output_name = str(config.get("summary_output") or "refresh-summary.json").strip()
    if not summary_output_name:
        raise JobSourceError("Job refresh config summary output cannot be empty.")
    summary_path = resolve_refresh_output_path(
        output_root,
        summary_output_name,
        label="Job refresh summary output path",
    )

    summary = {
        "refreshed_at": now_iso(),
        "config_path": str(relative_to_root(config_file, root)),
        "output_dir": str(relative_to_root(output_root, root)),
        "source_count": len(refreshed_sources),
        "sources": refreshed_sources,
        "merge_enabled": merge_enabled,
        "merged_output": (
            str(relative_to_root(merged_output_path, root))
            if merged_output_path is not None
            else None
        ),
        "merged_job_count": merged_job_count if merge_enabled else None,
        "summary_output": str(relative_to_root(summary_path, root)),
    }
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    logger.info("Wrote job refresh summary to %s", summary_path)
    return summary


def fetch_json(url: str, *, timeout: int = 30, retries: int = 3) -> dict[str, Any]:
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "OfferQuest/0.1.0",
        },
    )
    redacted_url = redact_url_for_logs(url)
    last_error: Exception
    for attempt in range(retries):
        if attempt:
            time.sleep(2 ** attempt)
        try:
            with urlopen(request, timeout=timeout) as response:
                body = response.read().decode("utf-8")
            return json.loads(body)
        except Exception as exc:
            last_error = exc
            logger.warning(
                "Request to %s failed on attempt %s/%s: %s",
                redacted_url,
                attempt + 1,
                retries,
                exc,
            )
    raise JobSourceError(f"Failed to fetch JSON from {redacted_url}") from last_error


def redact_url_for_logs(url: str) -> str:
    parsed = urlsplit(url)
    if not parsed.query:
        return url

    query = urlencode(
        [
            (
                key,
                "[redacted]" if key.lower() in SENSITIVE_QUERY_PARAMETERS else value,
            )
            for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        ]
    )
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, query, parsed.fragment))


def normalize_adzuna_job(job: dict[str, Any], *, country: str) -> JobRecord:
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


def normalize_greenhouse_job(job: dict[str, Any], *, board_token: str, company: str) -> JobRecord:
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


def manual_job_record_from_file(path: Path) -> JobRecord:
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
        if possible_company and possible_location and looks_like_header_location_candidate(possible_location):
            return possible_company, possible_location

    company = first_line if not looks_like_location(first_line) else None
    location = None

    for line in header_lines[1:]:
        if looks_like_header_location_candidate(line):
            location = line
            break

    return company, location


def normalize_job_record(record: dict[str, Any]) -> JobRecord:
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


def annotate_job_records(
    records: list[dict],
    *,
    extra_metadata: dict[str, Any],
) -> list[dict]:
    extra = drop_none(extra_metadata) if extra_metadata else {}
    annotated: list[dict] = []
    for record in records:
        normalized = normalize_job_record(record)
        if extra:
            normalized["metadata"] = {
                **(normalized.get("metadata") or {}),
                **extra,
            }
        annotated.append(normalized)
    return annotated


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
    else:
        text = json.dumps(normalized, indent=2)

    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=output_path.parent, delete=False, suffix=".tmp"
    ) as handle:
        handle.write(text)
        tmp_path = Path(handle.name)
    tmp_path.replace(output_path)


def collect_job_record_inputs(paths: Sequence[str | Path]) -> list[dict]:
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


def index_job_records(records: list[dict]) -> dict[str, dict]:
    return {record["id"]: record for record in records if record.get("id")}


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
    from . import config as _config

    lowered = value.lower()
    cfg = _config.active()
    for term in cfg.location_primary_terms:
        if term in lowered:
            return True
    for term in cfg.location_remote_terms:
        if term in lowered:
            return True
    for term in cfg.location_secondary_terms:
        if term in lowered:
            return True
    return False


def looks_like_header_location_candidate(value: str) -> bool:
    cleaned = normalize_text(value or "")
    if looks_like_location(cleaned):
        return True
    if not cleaned or "@" in cleaned or "http" in cleaned.lower():
        return False
    if any(char.isdigit() for char in cleaned):
        return False

    tokens = re.findall(r"[A-Za-z]+(?:[-'][A-Za-z]+)?", cleaned)
    if not 1 <= len(tokens) <= 4:
        return False

    lowered_tokens = {token.lower() for token in tokens}
    if lowered_tokens.intersection(HEADER_LOCATION_ORG_MARKERS):
        return False
    if lowered_tokens.intersection(HEADER_LOCATION_NON_LOCATION_TERMS):
        return False

    allowed_lower_tokens = {"and", "of", "the"}
    if not all(token.isupper() or token[0].isupper() or token.lower() in allowed_lower_tokens for token in tokens):
        return False
    return True


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


def get_adzuna_env_path(raw_path: str | Path | None = None) -> Path:
    if raw_path is not None:
        return Path(raw_path).expanduser().resolve()

    env_override = os.getenv(ADZUNA_ENV_PATH_ENVVAR)
    if env_override:
        return Path(env_override).expanduser().resolve()

    return (Path.home() / ".config" / "offerquest" / ADZUNA_ENV_FILENAME).resolve()


def read_env_assignments(path: str | Path) -> dict[str, str]:
    env_path = Path(path)
    if not env_path.exists():
        return {}

    values: dict[str, str] = {}
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue

        key, raw_value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        values[key] = parse_env_assignment_value(raw_value)

    return values


def parse_env_assignment_value(raw_value: str) -> str:
    value = raw_value.strip()
    if not value:
        return ""
    if value[0] in {'"', "'"}:
        try:
            return str(ast.literal_eval(value))
        except (SyntaxError, ValueError):
            return value.strip("'\"")
    return value


def load_adzuna_credentials_file(
    raw_path: str | Path | None = None,
) -> dict[str, str]:
    values = read_env_assignments(get_adzuna_env_path(raw_path))
    return {
        "ADZUNA_APP_ID": values.get("ADZUNA_APP_ID", ""),
        "ADZUNA_APP_KEY": values.get("ADZUNA_APP_KEY", ""),
    }


def load_adzuna_credentials_status(
    raw_path: str | Path | None = None,
) -> dict[str, Any]:
    env_path = get_adzuna_env_path(raw_path)
    saved = load_adzuna_credentials_file(env_path)
    env_app_id = os.getenv("ADZUNA_APP_ID")
    env_app_key = os.getenv("ADZUNA_APP_KEY")
    saved_app_id = saved.get("ADZUNA_APP_ID") or None
    saved_app_key = saved.get("ADZUNA_APP_KEY") or None
    effective_app_id = env_app_id or saved_app_id
    effective_app_key = env_app_key or saved_app_key

    if env_app_id or env_app_key:
        effective_source = "environment"
    elif effective_app_id or effective_app_key:
        effective_source = "credentials_file"
    else:
        effective_source = "missing"

    return {
        "path": env_path,
        "file_exists": env_path.exists(),
        "saved_app_id": saved_app_id,
        "saved_app_key": saved_app_key,
        "saved_app_id_masked": mask_secret(saved_app_id),
        "saved_app_key_masked": mask_secret(saved_app_key),
        "has_saved_credentials": bool(saved_app_id and saved_app_key),
        "effective_app_id": effective_app_id,
        "effective_app_key": effective_app_key,
        "effective_app_id_masked": mask_secret(effective_app_id),
        "effective_app_key_masked": mask_secret(effective_app_key),
        "has_effective_credentials": bool(effective_app_id and effective_app_key),
        "effective_source": effective_source,
        "is_env_override": effective_source == "environment",
    }


def write_adzuna_credentials_file(
    app_id: str,
    app_key: str,
    *,
    raw_path: str | Path | None = None,
) -> Path:
    normalized_app_id = string_or_none(app_id)
    normalized_app_key = string_or_none(app_key)
    if not normalized_app_id or not normalized_app_key:
        raise ValueError("Both Adzuna app id and app key are required.")

    env_path = get_adzuna_env_path(raw_path)
    env_path.parent.mkdir(parents=True, exist_ok=True)
    content = (
        "# OfferQuest Adzuna credentials\n"
        f"ADZUNA_APP_ID={json.dumps(normalized_app_id)}\n"
        f"ADZUNA_APP_KEY={json.dumps(normalized_app_key)}\n"
    )

    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=env_path.parent,
        delete=False,
    ) as handle:
        handle.write(content)
        temporary_path = Path(handle.name)

    try:
        os.chmod(temporary_path, 0o600)
    except OSError:
        pass
    temporary_path.replace(env_path)
    try:
        os.chmod(env_path, 0o600)
    except OSError:
        pass
    return env_path


def mask_secret(value: str | None, *, head: int = 4, tail: int = 2) -> str | None:
    if value is None:
        return None
    if len(value) <= head + tail:
        return "*" * len(value)
    return f"{value[:head]}{'*' * (len(value) - head - tail)}{value[-tail:]}"


def resolve_workspace_path(
    root: Path,
    raw_path: str | Path,
    *,
    must_stay_inside: bool = False,
    label: str = "Path",
) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        resolved = path.resolve()
    else:
        resolved = (root / path).resolve()
    if must_stay_inside:
        return require_path_inside(resolved, root, label=label)
    return resolved


def resolve_refresh_input_path(output_root: Path, raw_path: str | Path) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        resolved = path.resolve()
    else:
        resolved = (output_root / path).resolve()
    return require_path_inside(resolved, output_root, label="Job refresh merge input path")


def resolve_refresh_output_path(output_root: Path, raw_path: str | Path, *, label: str) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        resolved = path.resolve()
    else:
        resolved = (output_root / path).resolve()
    return require_path_inside(resolved, output_root, label=label)


def require_path_inside(path: Path, root: Path, *, label: str) -> Path:
    resolved_root = root.resolve()
    resolved_path = path.resolve()
    try:
        resolved_path.relative_to(resolved_root)
    except ValueError as exc:
        raise JobSourceError(f"{label} must stay inside {resolved_root}.") from exc
    return resolved_path


def resolve_adzuna_credentials(
    app_id: str | None,
    app_key: str | None,
) -> tuple[str | None, str | None]:
    file_credentials = load_adzuna_credentials_file()
    return (
        app_id or os.getenv("ADZUNA_APP_ID") or string_or_none(file_credentials.get("ADZUNA_APP_ID")),
        app_key or os.getenv("ADZUNA_APP_KEY") or string_or_none(file_credentials.get("ADZUNA_APP_KEY")),
    )
