from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .ats import build_ats_report
from .docx import export_document_as_docx
from .errors import ProfileValidationError
from .extractors import read_document_text
from .jobs import find_job_record, index_job_records, job_record_to_text, read_job_records
from .ollama import DEFAULT_OLLAMA_BASE_URL, generate_structured_response
from .profile import build_candidate_profile, looks_like_location_line
from .scoring import infer_job_title


def generate_cover_letter_for_job_file(
    cv_path: str | Path,
    job_path: str | Path,
    *,
    base_cover_letter_path: str | Path | None = None,
) -> dict:
    cv_text = read_document_text(cv_path)
    job_text = read_document_text(job_path)
    base_cover_letter_text = read_optional_text(base_cover_letter_path)

    profile = build_candidate_profile(cv_text, base_cover_letter_text)
    validate_cover_letter_profile(profile)
    ats_report = build_ats_report(
        cv_text,
        job_text,
        cv_path=str(cv_path),
        cover_letter_text=base_cover_letter_text,
    )

    job_context = infer_job_context(job_text)
    cover_letter_text = build_cover_letter_text(
        profile=profile,
        ats_report=ats_report,
        job_context=job_context,
    )

    return {
        "job_title": job_context["job_title"],
        "company": job_context["company"],
        "location": job_context["location"],
        "cover_letter_text": cover_letter_text,
        "ats_score": ats_report["ats_score"],
        "matched_keywords": ats_report["keyword_coverage"]["matched_keywords"],
        "missing_keywords": ats_report["keyword_coverage"]["missing_keywords"],
    }


def generate_cover_letter_for_job_record(
    cv_path: str | Path,
    job_record: dict,
    *,
    base_cover_letter_path: str | Path | None = None,
) -> dict:
    cv_text = read_document_text(cv_path)
    base_cover_letter_text = read_optional_text(base_cover_letter_path)
    profile = build_candidate_profile(cv_text, base_cover_letter_text)
    validate_cover_letter_profile(profile)
    job_text = job_record_to_text(job_record)

    ats_report = build_ats_report(
        cv_text,
        job_text,
        cv_path=str(cv_path),
        cover_letter_text=base_cover_letter_text,
    )

    job_context = {
        "job_title": job_record.get("title") or infer_job_title(job_text),
        "company": job_record.get("company"),
        "location": job_record.get("location"),
    }
    cover_letter_text = build_cover_letter_text(
        profile=profile,
        ats_report=ats_report,
        job_context=job_context,
    )

    return {
        "job_id": job_record.get("id"),
        "job_title": job_context["job_title"],
        "company": job_context["company"],
        "location": job_context["location"],
        "job_url": job_record.get("url"),
        "cover_letter_text": cover_letter_text,
        "ats_score": ats_report["ats_score"],
        "matched_keywords": ats_report["keyword_coverage"]["matched_keywords"],
        "missing_keywords": ats_report["keyword_coverage"]["missing_keywords"],
    }


def generate_cover_letter_for_job_record_llm(
    cv_path: str | Path,
    job_record: dict,
    *,
    base_cover_letter_path: str | Path | None = None,
    employer_context_path: str | Path | None = None,
    model: str = "qwen3:8b",
    base_url: str = DEFAULT_OLLAMA_BASE_URL,
    timeout_seconds: int = 180,
) -> dict:
    cv_text = read_document_text(cv_path)
    base_cover_letter_text = read_optional_text(base_cover_letter_path)
    employer_context_text = read_optional_text(employer_context_path)
    profile = build_candidate_profile(cv_text, base_cover_letter_text)
    validate_cover_letter_profile(profile)
    job_text = job_record_to_text(job_record)

    ats_report = build_ats_report(
        cv_text,
        job_text,
        cv_path=str(cv_path),
        cover_letter_text=base_cover_letter_text,
    )

    job_context = {
        "job_title": job_record.get("title") or infer_job_title(job_text),
        "company": job_record.get("company"),
        "location": job_record.get("location"),
    }
    llm_payload = build_cover_letter_with_ollama(
        profile=profile,
        ats_report=ats_report,
        job_context=job_context,
        job_text=job_text,
        base_cover_letter_text=base_cover_letter_text,
        employer_context_text=employer_context_text,
        model=model,
        base_url=base_url,
        timeout_seconds=timeout_seconds,
    )

    return {
        "job_id": job_record.get("id"),
        "job_title": job_context["job_title"],
        "company": job_context["company"],
        "location": job_context["location"],
        "job_url": job_record.get("url"),
        "cover_letter_text": llm_payload["cover_letter_text"],
        "resume_headline": llm_payload["resume_headline"],
        "employer_specific_focus": llm_payload["employer_specific_focus"],
        "evidence_used": llm_payload["evidence_used"],
        "caution_flags": llm_payload["caution_flags"],
        "ats_score": ats_report["ats_score"],
        "matched_keywords": ats_report["keyword_coverage"]["matched_keywords"],
        "missing_keywords": ats_report["keyword_coverage"]["missing_keywords"],
        "llm_provider": "ollama",
        "llm_model": model,
    }


def generate_cover_letters_from_ranking(
    cv_path: str | Path,
    jobs_file: str | Path,
    ranking_file: str | Path,
    output_dir: str | Path,
    *,
    base_cover_letter_path: str | Path | None = None,
    top_n: int = 5,
    export_docx: bool = False,
) -> dict:
    job_records = read_job_records(jobs_file)
    job_index = index_job_records(job_records)
    ranking_payload = json.loads(Path(ranking_file).read_text(encoding="utf-8"))
    rankings = ranking_payload.get("rankings", [])

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    selected_rankings = select_top_unique_rankings(rankings, limit=top_n)
    generated: list[dict] = []

    for index, ranking in enumerate(selected_rankings, start=1):
        job_id = ranking.get("job_id")
        if not job_id:
            continue
        job_record = job_index.get(job_id)
        if job_record is None:
            continue

        payload = generate_cover_letter_for_job_record(
            cv_path,
            job_record,
            base_cover_letter_path=base_cover_letter_path,
        )
        filename_stem = build_cover_letter_filename(index, payload)
        text_path = output_path / f"{filename_stem}.txt"
        write_cover_letter(text_path, payload)

        item = {
            "rank": index,
            "job_id": payload.get("job_id"),
            "company": payload.get("company"),
            "job_title": payload.get("job_title"),
            "location": payload.get("location"),
            "job_url": payload.get("job_url"),
            "ats_score": payload.get("ats_score"),
            "text_path": str(text_path),
            "missing_keywords": payload.get("missing_keywords", []),
        }

        if export_docx:
            docx_path = output_path / f"{filename_stem}.docx"
            export_document_as_docx(text_path, docx_path)
            item["docx_path"] = str(docx_path)

        generated.append(item)

    summary = {
        "job_count": len(generated),
        "output_dir": str(output_path),
        "items": generated,
    }
    (output_path / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def generate_cover_letters_from_ranking_llm(
    cv_path: str | Path,
    jobs_file: str | Path,
    ranking_file: str | Path,
    output_dir: str | Path,
    *,
    base_cover_letter_path: str | Path | None = None,
    employer_context_dir: str | Path | None = None,
    top_n: int = 5,
    export_docx: bool = False,
    model: str = "qwen3:8b",
    base_url: str = DEFAULT_OLLAMA_BASE_URL,
    timeout_seconds: int = 180,
) -> dict:
    job_records = read_job_records(jobs_file)
    job_index = index_job_records(job_records)
    ranking_payload = json.loads(Path(ranking_file).read_text(encoding="utf-8"))
    rankings = ranking_payload.get("rankings", [])

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    employer_context_root = Path(employer_context_dir) if employer_context_dir else None

    selected_rankings = select_top_unique_rankings(rankings, limit=top_n)
    generated: list[dict] = []

    for index, ranking in enumerate(selected_rankings, start=1):
        job_id = ranking.get("job_id")
        if not job_id:
            continue
        job_record = job_index.get(job_id)
        if job_record is None:
            continue

        employer_context_path = resolve_employer_context_path(
            employer_context_root,
            job_record=job_record,
        )
        payload = generate_cover_letter_for_job_record_llm(
            cv_path,
            job_record,
            base_cover_letter_path=base_cover_letter_path,
            employer_context_path=employer_context_path,
            model=model,
            base_url=base_url,
            timeout_seconds=timeout_seconds,
        )

        filename_stem = build_cover_letter_filename(index, payload)
        text_path = output_path / f"{filename_stem}.txt"
        json_path = output_path / f"{filename_stem}.json"
        write_cover_letter(text_path, payload)
        write_cover_letter(json_path, payload)

        item = {
            "rank": index,
            "job_id": payload.get("job_id"),
            "company": payload.get("company"),
            "job_title": payload.get("job_title"),
            "location": payload.get("location"),
            "job_url": payload.get("job_url"),
            "ats_score": payload.get("ats_score"),
            "text_path": str(text_path),
            "json_path": str(json_path),
            "resume_headline": payload.get("resume_headline"),
            "employer_specific_focus": payload.get("employer_specific_focus", []),
            "missing_keywords": payload.get("missing_keywords", []),
            "llm_model": payload.get("llm_model"),
        }

        if employer_context_path:
            item["employer_context_path"] = str(employer_context_path)

        if export_docx:
            docx_path = output_path / f"{filename_stem}.docx"
            export_document_as_docx(text_path, docx_path)
            item["docx_path"] = str(docx_path)

        generated.append(item)

    summary = {
        "job_count": len(generated),
        "output_dir": str(output_path),
        "llm_provider": "ollama",
        "llm_model": model,
        "items": generated,
    }
    (output_path / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def build_cover_letter_text(*, profile: dict, ats_report: dict, job_context: dict) -> str:
    validate_cover_letter_profile(profile)
    job_title = job_context.get("job_title") or "the advertised role"
    company = job_context.get("company") or "your team"
    location = profile.get("location")
    years = profile.get("years_experience")

    matched_keywords = ats_report["keyword_coverage"]["matched_keywords"][:4]
    missing_keywords = ats_report["required_keywords"]["missing"][:2]
    recent_roles = profile.get("recent_roles", [])
    top_roles = recent_roles[:2]

    matched_phrase = join_human_list(lower_keywords(matched_keywords)) or build_safe_skill_phrase(profile)
    role_phrase = build_role_phrase(top_roles)
    domain_phrase = build_domain_phrase(profile.get("domains", []))
    evidence_phrase = join_human_list(build_profile_evidence_fragments(profile))
    opening_background = build_opening_background(profile)

    opening = (
        f"Dear Hiring Team,\n\n"
        f"I am writing to apply for the {job_title} position"
        f"{format_company_phrase(company)}."
        f"{opening_background} "
        f"What especially attracts me to this opportunity is the chance to contribute with strengths in {matched_phrase}."
    )

    experience = (
        f"{build_recent_experience_opening(role_phrase)} I have worked with complex datasets in environments where accuracy, "
        f"clarity, and reliable reporting mattered. That has included {evidence_phrase}."
    )

    if domain_phrase == "data-rich":
        alignment = (
            f"That experience aligns well with the requirements suggested by this role, particularly around "
            f"{matched_phrase}. I would bring a practical, detail-oriented approach to the position, with a focus on "
            f"structured analysis, dependable delivery, and clear communication."
        )
    else:
        alignment = (
            f"That experience aligns well with the requirements suggested by this role, particularly around "
            f"{matched_phrase}. I would bring a practical, detail-oriented approach to the position, along with "
            f"experience from {domain_phrase} settings where structured data, consistency, and clear communication were essential."
        )

    gap_paragraph = ""
    if missing_keywords:
        missing_phrase = join_human_list(lower_keywords(missing_keywords))
        gap_paragraph = (
            f"\n\nI also want to be candid about one point. If deeper experience in {missing_phrase} is central to the role, "
            f"I would position myself as strong on the underlying analytical and reporting capabilities first, while being "
            f"ready to learn the domain-specific context quickly and carefully."
        )

    closing = (
        f"\n\nThank you for considering my application. I would welcome the opportunity to discuss how my background in "
        f"{build_safe_skill_phrase(profile)} could contribute to {company or 'your team'}.\n\n"
        f"With best regards,\n"
        f"{profile['name']}"
    )

    return opening + "\n\n" + experience + "\n\n" + alignment + gap_paragraph + closing


def build_cover_letter_with_ollama(
    *,
    profile: dict,
    ats_report: dict,
    job_context: dict,
    job_text: str,
    base_cover_letter_text: str,
    employer_context_text: str,
    model: str,
    base_url: str,
    timeout_seconds: int,
) -> dict:
    schema = cover_letter_schema()
    messages = [
        {
            "role": "system",
            "content": (
                "You write employer-specific cover letters for job applications. "
                "Only use facts present in the candidate evidence provided below. "
                "Do not invent tools, industries, achievements, metrics, employers, or domain knowledge. "
                "If an employer-specific detail is not provided, stay specific to the role and company name without fabricating mission statements or culture claims. "
                "Return valid JSON matching the schema."
            ),
        },
        {
            "role": "user",
            "content": build_cover_letter_prompt(
                profile=profile,
                ats_report=ats_report,
                job_context=job_context,
                job_text=job_text,
                base_cover_letter_text=base_cover_letter_text,
                employer_context_text=employer_context_text,
                schema=schema,
            ),
        },
    ]

    response = generate_structured_response(
        model=model,
        messages=messages,
        schema=schema,
        base_url=base_url,
        temperature=0.2,
        think=False,
        timeout_seconds=timeout_seconds,
    )
    return normalize_llm_cover_letter_response(response, profile=profile)


def cover_letter_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "resume_headline": {"type": "string"},
            "employer_specific_focus": {
                "type": "array",
                "items": {"type": "string"},
            },
            "evidence_used": {
                "type": "array",
                "items": {"type": "string"},
            },
            "caution_flags": {
                "type": "array",
                "items": {"type": "string"},
            },
            "cover_letter_text": {"type": "string"},
        },
        "required": [
            "resume_headline",
            "employer_specific_focus",
            "evidence_used",
            "caution_flags",
            "cover_letter_text",
        ],
    }


def build_cover_letter_prompt(
    *,
    profile: dict,
    ats_report: dict,
    job_context: dict,
    job_text: str,
    base_cover_letter_text: str,
    employer_context_text: str,
    schema: dict[str, Any],
) -> str:
    base_cover_letter_style_reference = build_base_cover_letter_style_reference(
        base_cover_letter_text
    )
    llm_profile_context = build_llm_profile_context(profile)
    return (
        "Write a strong employer-specific cover letter draft for this job.\n\n"
        "Requirements:\n"
        "- 4 to 5 short paragraphs\n"
        "- natural, credible tone\n"
        "- clearly tailored to the employer and role\n"
        "- the target job is only the role described in Job context and Job description text\n"
        "- grounded only in the candidate evidence below\n"
        "- do not claim missing skills as if they are proven facts\n"
        "- if there is a gap, frame it honestly and constructively\n"
        "- never reuse a different role title, req number, employer name, or location from the base cover letter reference\n"
        "- do not treat prior target-role guesses from other applications as the current target job\n"
        "- end with 'With best regards,' and the candidate name\n"
        "- return JSON only\n\n"
        f"JSON schema:\n{json.dumps(schema, indent=2)}\n\n"
        f"Job context:\n{json.dumps(job_context, indent=2)}\n\n"
        f"Candidate evidence profile:\n{json.dumps(llm_profile_context, indent=2)}\n\n"
        f"ATS report:\n{json.dumps(ats_report, indent=2)}\n\n"
        "Base cover letter tone reference:\n"
        f"{base_cover_letter_style_reference}\n\n"
        "Employer-specific context:\n"
        f"{employer_context_text or '[none provided]'}\n\n"
        "Job description text:\n"
        f"{job_text}\n"
    )


def build_base_cover_letter_style_reference(base_cover_letter_text: str) -> str:
    if not base_cover_letter_text.strip():
        return "[none]"
    return (
        "Use the candidate's base cover letter only as a tone reference.\n"
        "- professional, direct, and evidence-based\n"
        "- specific about data/reporting work\n"
        "- honest about fit gaps without underselling\n"
        "- do not copy any role title, req number, employer name, or location from it"
    )


def build_llm_profile_context(profile: dict) -> dict:
    return {
        "name": profile.get("name"),
        "location": profile.get("location"),
        "years_experience": profile.get("years_experience"),
        "summary": profile.get("summary"),
        "core_skills": profile.get("core_skills", []),
        "domains": profile.get("domains", []),
        "recent_roles": profile.get("recent_roles", []),
        "quality_warnings": profile.get("quality_warnings", []),
    }


def normalize_llm_cover_letter_response(response: dict, *, profile: dict) -> dict:
    text = str(response.get("cover_letter_text", "")).strip()
    if profile.get("name") and profile["name"] not in text:
        text = text.rstrip() + f"\n\nWith best regards,\n{profile['name']}"

    return {
        "resume_headline": str(response.get("resume_headline", "")).strip(),
        "employer_specific_focus": ensure_string_list(response.get("employer_specific_focus")),
        "evidence_used": ensure_string_list(response.get("evidence_used")),
        "caution_flags": ensure_string_list(response.get("caution_flags")),
        "cover_letter_text": text,
    }


def infer_job_context(job_text: str) -> dict:
    lines = [line.strip() for line in job_text.splitlines() if line.strip()]
    job_title = infer_job_title(job_text)
    remaining = [line for line in lines if line != job_title]

    company = None
    location = None
    for line in remaining[:3]:
        if "," in line:
            left, right = [part.strip() for part in line.split(",", 1)]
            if not company and left and not looks_like_location(left):
                company = left
            if not location and looks_like_location(right):
                location = right
        elif not company and not looks_like_location(line):
            company = line
        elif not location and looks_like_location(line):
            location = line

    return {
        "job_title": job_title,
        "company": company,
        "location": location,
    }


def build_role_phrase(roles: list[dict]) -> str:
    fragments: list[str] = []
    for role in roles:
        title = role.get("title")
        organization = role.get("organization")
        if title and organization:
            fragments.append(f"as {title} at {organization}")
        elif title:
            fragments.append(f"as {title}")

    if not fragments:
        return ""

    return " " + join_human_list(fragments)


def build_domain_phrase(domains: list[str]) -> str:
    preferred = [
        domain
        for domain in domains
        if domain in {"Healthcare", "Research", "Higher education", "Public sector", "Biotech"}
    ]
    return join_human_list(lower_keywords(preferred[:3])) or "data-rich"


def format_company_phrase(company: str | None) -> str:
    if not company:
        return ""
    return f" at {company}"


def looks_like_location(value: str) -> bool:
    return bool(value and looks_like_location_line(value))


def lower_keywords(values: list[str]) -> list[str]:
    lowered: list[str] = []
    for value in values:
        if not value:
            lowered.append(value)
        elif value.isupper():
            lowered.append(value)
        else:
            lowered.append(value[0].lower() + value[1:])
    return lowered


def join_human_list(values: list[str]) -> str:
    if not values:
        return ""
    if len(values) == 1:
        return values[0]
    if len(values) == 2:
        return f"{values[0]} and {values[1]}"
    return ", ".join(values[:-1]) + f", and {values[-1]}"


def read_optional_text(path: str | Path | None) -> str:
    if path is None:
        return ""
    return read_document_text(path)


def write_cover_letter(path: str | Path, payload: dict) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if output_path.suffix.lower() == ".json":
        output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return

    output_path.write_text(payload["cover_letter_text"], encoding="utf-8")


def select_top_unique_rankings(rankings: list[dict], *, limit: int) -> list[dict]:
    seen: set[tuple[str, str, str]] = set()
    selected: list[dict] = []

    for ranking in rankings:
        company = (ranking.get("company") or "").strip().lower()
        job_title = (ranking.get("job_title") or "").strip().lower()
        location = (ranking.get("location") or "").strip().lower()
        dedupe_key = (company, job_title, location)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        selected.append(ranking)
        if len(selected) >= limit:
            break

    return selected


def build_cover_letter_filename(index: int, payload: dict) -> str:
    company = slugify(payload.get("company") or "unknown-company")
    title = slugify(payload.get("job_title") or "job")
    return f"{index:02d}-{company}-{title}"


def slugify(value: str) -> str:
    lowered = value.lower()
    lowered = re.sub(r"[^a-z0-9]+", "-", lowered)
    return lowered.strip("-") or "item"


def ensure_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def resolve_employer_context_path(
    employer_context_root: Path | None,
    *,
    job_record: dict,
) -> Path | None:
    if employer_context_root is None:
        return None

    company = slugify(job_record.get("company") or "")
    candidates = [
        employer_context_root / f"{company}.txt",
        employer_context_root / f"{company}.md",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def validate_cover_letter_profile(profile: dict) -> None:
    missing: list[str] = []
    if not profile.get("name"):
        missing.append("a candidate name")
    if not profile.get("summary") and not profile.get("recent_roles") and not profile.get("core_skills"):
        missing.append("usable candidate evidence")

    if missing:
        raise ProfileValidationError(
            "Cannot generate a cover letter safely because the profile is missing "
            + join_human_list(missing)
            + "."
        )


def build_opening_background(profile: dict) -> str:
    years = profile.get("years_experience")
    location = profile.get("location")
    summary = profile.get("summary")

    parts: list[str] = []
    if location:
        parts.append(f"Based in {location}")
    if years:
        parts.append(f"I bring more than {years} years of experience across {build_safe_skill_phrase(profile)}")
    elif summary:
        parts.append(summary)
    else:
        parts.append(f"I bring experience across {build_safe_skill_phrase(profile)}")
    return " ".join(parts).strip()


def build_recent_experience_opening(role_phrase: str) -> str:
    if role_phrase:
        return f"In recent roles{role_phrase},"
    return "In my recent work,"


def build_profile_evidence_fragments(profile: dict) -> list[str]:
    skills = set(profile.get("core_skills", []))
    fragments: list[str] = []

    if {"Python", "SQL", "Automation"}.issubset(skills):
        fragments.append("automating recurring analytical work with Python and SQL")
    elif {"SQL", "Reporting"}.issubset(skills):
        fragments.append("building reporting workflows with SQL")

    if "Data quality" in skills:
        fragments.append("checking data quality and consistency")
    if "Metadata" in skills:
        fragments.append("working carefully with metadata, definitions, and structured information")
    if "Reporting" in skills and "building reporting workflows with SQL" not in fragments:
        fragments.append("turning analysis into clear reporting")
    if "Visualization" in skills:
        fragments.append("presenting findings in a more accessible way")
    if "Stakeholder collaboration" in skills:
        fragments.append("working closely with stakeholders to translate requirements into usable outputs")

    if not fragments:
        summary = profile.get("summary")
        if summary:
            fragments.append("delivering careful, evidence-based analytical work")
        else:
            fragments.append(f"applying strengths in {build_safe_skill_phrase(profile)}")

    return fragments[:3]


def build_safe_skill_phrase(profile: dict) -> str:
    preferred_order = [
        "SQL",
        "Python",
        "Reporting",
        "Data quality",
        "Metadata",
        "Automation",
        "Visualization",
    ]
    skills = [skill for skill in preferred_order if skill in profile.get("core_skills", [])]
    if skills:
        return join_human_list(lower_keywords(skills[:3]))
    return "data analysis and structured problem-solving"
