from __future__ import annotations

from pathlib import Path

from .extractors import read_document_text
from .jobs import job_record_to_text
from .matching import contains_any_keyword, contains_keyword
from .profile import (
    DOMAIN_PATTERNS,
    SKILL_PATTERNS,
    build_candidate_profile,
    split_cv_sections,
)
from .scoring import infer_job_title, score_job_text, score_title_alignment

ATS_EXTRA_PATTERNS = {
    "Agile": ["agile", "scrum", "kanban"],
    "Business intelligence": ["business intelligence", "bi analyst"],
    "Cloud": ["cloud"],
    "Dashboards": ["dashboard", "dashboards"],
    "Data governance": ["data governance", "governance"],
    "Data warehousing": ["data warehouse", "data warehousing", "warehouse"],
    "ETL": ["etl", "extract transform load"],
    "Finance": ["finance", "financial", "investment"],
    "Power BI": ["power bi", "powerbi"],
    "Stakeholder management": ["stakeholder", "stakeholders"],
    "Tableau": ["tableau"],
}

ATS_PATTERNS = {
    **SKILL_PATTERNS,
    **DOMAIN_PATTERNS,
    **ATS_EXTRA_PATTERNS,
}

ATS_SECTION_HEADINGS = [
    "Professional Summary",
    "Core Skills",
    "Professional Experience",
    "Education",
]

REQUIRED_MARKERS = (
    "required",
    "must",
    "essential",
    "need",
    "needs",
    "seeking",
    "looking for",
    "experience with",
    "proficient in",
    "strong",
)


def ats_check_job_file(
    cv_path: str | Path,
    job_path: str | Path,
    *,
    cover_letter_path: str | Path | None = None,
) -> dict:
    cv_text = read_document_text(cv_path)
    job_text = read_document_text(job_path)
    cover_letter_text = read_optional_text(cover_letter_path)

    report = build_ats_report(
        cv_text,
        job_text,
        cv_path=str(cv_path),
        cover_letter_text=cover_letter_text,
    )
    report["job_source"] = str(job_path)
    return report


def ats_check_job_record(
    cv_path: str | Path,
    job_record: dict,
    *,
    cover_letter_path: str | Path | None = None,
) -> dict:
    cv_text = read_document_text(cv_path)
    cover_letter_text = read_optional_text(cover_letter_path)
    job_text = job_record_to_text(job_record)

    report = build_ats_report(
        cv_text,
        job_text,
        cv_path=str(cv_path),
        cover_letter_text=cover_letter_text,
    )
    report.update(
        {
            "job_id": job_record.get("id"),
            "company": job_record.get("company"),
            "location": job_record.get("location"),
            "job_url": job_record.get("url"),
            "job_source": job_record.get("source"),
        }
    )
    return report


def build_ats_report(
    cv_text: str,
    job_text: str,
    *,
    cv_path: str | None = None,
    cover_letter_text: str = "",
) -> dict:
    cv_profile = build_candidate_profile(cv_text, cover_letter_text)
    job_title = infer_job_title(job_text)

    keyword_analysis = analyze_keyword_coverage(cv_text, job_text, job_title=job_title)
    section_checks = analyze_sections(cv_text)
    contact_checks = analyze_contact_fields(cv_profile)
    format_risks = detect_format_risks(
        cv_text,
        cv_path=cv_path,
        section_checks=section_checks,
        contact_checks=contact_checks,
    )
    suggestions = build_ats_suggestions(
        keyword_analysis=keyword_analysis,
        section_checks=section_checks,
        format_risks=format_risks,
        job_title=job_title,
    )

    fit_snapshot = score_job_text(job_text, cv_profile)
    title_alignment_score = score_title_alignment(
        job_title,
        [title.lower() for title in cv_profile.get("search_focus", {}).get("priority_titles", [])],
    )[0]
    section_score = round((len(section_checks["present"]) / len(ATS_SECTION_HEADINGS)) * 10)
    contact_score = sum(
        [
            2 if contact_checks["name_detected"] else 0,
            2 if contact_checks["email_detected"] else 0,
            1 if contact_checks["location_detected"] else 0,
        ]
    )
    parseability_score = max(0, 10 - min(6, len(format_risks) * 2))

    ats_score = round(
        min(
            100,
            keyword_analysis["coverage_percent"] * 0.35
            + keyword_analysis["required_coverage_percent"] * 0.25
            + title_alignment_score
            + section_score
            + contact_score
            + parseability_score,
        )
    )

    return {
        "job_title": job_title,
        "ats_score": ats_score,
        "assessment": describe_ats_score(ats_score),
        "suggested_resume_title": suggest_resume_title(job_title, cv_profile),
        "fit_snapshot": fit_snapshot,
        "keyword_coverage": {
            "coverage_percent": keyword_analysis["coverage_percent"],
            "matched_count": len(keyword_analysis["matched_keywords"]),
            "total_count": keyword_analysis["total_keywords"],
            "matched_keywords": keyword_analysis["matched_keywords"],
            "missing_keywords": keyword_analysis["missing_keywords"],
        },
        "required_keywords": {
            "coverage_percent": keyword_analysis["required_coverage_percent"],
            "matched": keyword_analysis["matched_required_keywords"],
            "missing": keyword_analysis["missing_required_keywords"],
        },
        "section_checks": section_checks,
        "contact_checks": contact_checks,
        "format_risks": format_risks,
        "suggestions": suggestions,
    }


def analyze_keyword_coverage(cv_text: str, job_text: str, *, job_title: str) -> dict:
    lines = [line.strip().lower() for line in job_text.splitlines() if line.strip()]

    entries: list[dict] = []
    for label, patterns in ATS_PATTERNS.items():
        if not contains_any_keyword(job_text, patterns):
            continue

        in_title = contains_keyword(job_title, label) or contains_any_keyword(job_title, patterns)
        required = any(
            contains_any_keyword(line, patterns)
            and any(marker in line for marker in REQUIRED_MARKERS)
            for line in lines
        ) or in_title
        matched = contains_any_keyword(cv_text, patterns)

        entries.append(
            {
                "label": label,
                "required": required,
                "matched": matched,
                "priority": (2 if required else 0) + (1 if in_title else 0),
            }
        )

    entries = dedupe_keyword_entries(entries)
    entries.sort(key=lambda item: (-item["priority"], item["label"]))

    matched_keywords = [entry["label"] for entry in entries if entry["matched"]]
    missing_keywords = [entry["label"] for entry in entries if not entry["matched"]]
    required_entries = [entry for entry in entries if entry["required"]]
    matched_required_keywords = [
        entry["label"] for entry in required_entries if entry["matched"]
    ]
    missing_required_keywords = [
        entry["label"] for entry in required_entries if not entry["matched"]
    ]

    total_keywords = len(entries)
    total_required = len(required_entries)

    coverage_percent = ratio_as_percent(len(matched_keywords), total_keywords)
    required_coverage_percent = ratio_as_percent(
        len(matched_required_keywords),
        total_required,
    )

    return {
        "total_keywords": total_keywords,
        "coverage_percent": coverage_percent,
        "required_coverage_percent": required_coverage_percent,
        "matched_keywords": matched_keywords,
        "missing_keywords": missing_keywords,
        "matched_required_keywords": matched_required_keywords,
        "missing_required_keywords": missing_required_keywords,
    }


def dedupe_keyword_entries(entries: list[dict]) -> list[dict]:
    merged: dict[str, dict] = {}
    for entry in entries:
        label = entry["label"]
        if label not in merged:
            merged[label] = entry
            continue
        merged[label]["required"] = merged[label]["required"] or entry["required"]
        merged[label]["matched"] = merged[label]["matched"] or entry["matched"]
        merged[label]["priority"] = max(merged[label]["priority"], entry["priority"])
    return list(merged.values())


def analyze_sections(cv_text: str) -> dict:
    sections = split_cv_sections(cv_text)
    present = [heading for heading in ATS_SECTION_HEADINGS if sections.get(heading)]
    missing = [heading for heading in ATS_SECTION_HEADINGS if heading not in present]
    return {
        "present": present,
        "missing": missing,
    }


def analyze_contact_fields(profile: dict) -> dict:
    return {
        "name_detected": bool(profile.get("name")),
        "email_detected": bool(profile.get("email")),
        "location_detected": bool(profile.get("location")),
    }


def detect_format_risks(
    cv_text: str,
    *,
    cv_path: str | None,
    section_checks: dict,
    contact_checks: dict,
) -> list[str]:
    risks: list[str] = []
    suffix = Path(cv_path).suffix.lower() if cv_path else ""
    word_count = len(cv_text.split())
    lines = [line.strip() for line in cv_text.splitlines() if line.strip()]
    short_line_ratio = (
        sum(1 for line in lines if len(line.split()) <= 2) / len(lines)
        if lines
        else 1
    )

    if suffix == ".doc":
        risks.append("Legacy .doc files are less ATS-friendly than a clean .docx export.")
    if word_count < 150:
        risks.append("The extracted CV text is quite short, which may indicate missing content or a very thin resume.")
    if short_line_ratio > 0.55 and word_count < 350:
        risks.append("The resume text looks fragmented, which can happen when ATS parsers struggle with layout-heavy formatting.")
    if section_checks["missing"]:
        risks.append(
            "Some standard ATS-friendly sections are missing: "
            + ", ".join(section_checks["missing"])
        )
    if not contact_checks["email_detected"]:
        risks.append("No email address was detected in the extracted resume text.")
    if not contact_checks["name_detected"]:
        risks.append("No clear candidate name was detected in the extracted resume text.")

    return risks


def build_ats_suggestions(
    *,
    keyword_analysis: dict,
    section_checks: dict,
    format_risks: list[str],
    job_title: str,
) -> list[str]:
    suggestions: list[str] = []

    missing_required = keyword_analysis["missing_required_keywords"]
    missing_keywords = keyword_analysis["missing_keywords"]

    if missing_required:
        suggestions.append(
            "Add evidence-based mentions of these required keywords if they are true for you: "
            + ", ".join(missing_required[:6])
        )
    elif missing_keywords:
        suggestions.append(
            "Mirror more of the job language in the summary or top bullets, especially: "
            + ", ".join(missing_keywords[:6])
        )

    if "Core Skills" in section_checks["missing"]:
        suggestions.append(
            "Add a clear `Core Skills` section near the top so ATS systems see the main tools and domains quickly."
        )
    if "Professional Summary" in section_checks["missing"]:
        suggestions.append(
            "Add a short `Professional Summary` that names the target role family and your strongest data skills."
        )
    if job_title != "Unknown title":
        suggestions.append(
            f"Use a resume headline close to `{job_title}` if it truthfully matches the role you are targeting."
        )
    if any(".doc" in risk for risk in format_risks):
        suggestions.append(
            "Export the resume to `.docx` with plain headings and avoid text boxes, columns, or decorative layouts."
        )

    return dedupe_preserve_order(suggestions)


def suggest_resume_title(job_title: str, profile: dict) -> str:
    if job_title != "Unknown title":
        return job_title
    priority_titles = profile.get("search_focus", {}).get("priority_titles", [])
    if priority_titles:
        return priority_titles[0]
    return "Senior Data Analyst"


def describe_ats_score(score: int) -> str:
    if score >= 85:
        return "Strong ATS alignment"
    if score >= 70:
        return "Good ATS alignment with some tailoring opportunities"
    if score >= 55:
        return "Moderate ATS alignment; tailoring is recommended"
    return "Weak ATS alignment; substantial tailoring is recommended"


def ratio_as_percent(matches: int, total: int) -> int:
    if total == 0:
        return 100
    return round((matches / total) * 100)


def dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def read_optional_text(path: str | Path | None) -> str:
    if path is None:
        return ""
    return read_document_text(path)
