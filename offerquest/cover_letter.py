from __future__ import annotations

import json
from pathlib import Path

from .ats import build_ats_report
from .extractors import read_document_text
from .jobs import job_record_to_text
from .profile import build_candidate_profile
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


def build_cover_letter_text(*, profile: dict, ats_report: dict, job_context: dict) -> str:
    job_title = job_context.get("job_title") or "the advertised role"
    company = job_context.get("company") or "your team"
    location = profile.get("location") or "Sydney, NSW, Australia"
    years = profile.get("years_experience") or 10

    matched_keywords = ats_report["keyword_coverage"]["matched_keywords"][:4]
    missing_keywords = ats_report["required_keywords"]["missing"][:2]
    recent_roles = profile.get("recent_roles", [])
    top_roles = recent_roles[:2]

    matched_phrase = join_human_list(lower_keywords(matched_keywords)) or "data analysis and reporting"
    role_phrase = build_role_phrase(top_roles)
    domain_phrase = build_domain_phrase(profile.get("domains", []))

    opening = (
        f"Dear Hiring Team,\n\n"
        f"I am writing to apply for the {job_title} position"
        f"{format_company_phrase(company)}. Based in {location}, I bring more than {years} years "
        f"of experience across data analysis, reporting, workflow improvement, and structured problem-solving. "
        f"What especially attracts me to this opportunity is the chance to contribute with strengths in {matched_phrase}."
    )

    experience = (
        f"In recent roles{role_phrase}, I have worked with complex datasets in environments where accuracy, "
        f"clarity, and reliable reporting mattered. My background includes building and improving analytics workflows, "
        f"automating recurring processes with Python and SQL, checking data quality, and translating technical outputs "
        f"into clear, decision-ready information."
    )

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
        f"data analysis, reporting, automation, and quality-focused problem-solving could contribute to {company or 'your team'}.\n\n"
        f"With best regards,\n"
        f"{profile.get('name') or 'Bulat Faezov'}"
    )

    return opening + "\n\n" + experience + "\n\n" + alignment + gap_paragraph + closing


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
    lowered = value.lower()
    return any(
        token in lowered
        for token in (
            "sydney",
            "nsw",
            "australia",
            "melbourne",
            "brisbane",
            "perth",
            "canberra",
            "remote",
            "hybrid",
            "region",
            "cbd",
        )
    )


def lower_keywords(values: list[str]) -> list[str]:
    return [value[0].lower() + value[1:] if value else value for value in values]


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
