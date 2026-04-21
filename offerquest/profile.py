from __future__ import annotations

import re
from pathlib import Path

from .extractors import read_document_text

SECTION_HEADERS = {
    "Professional Summary",
    "Core Skills",
    "Professional Experience",
    "Education",
    "Technical Tools",
    "Certifications",
    "Languages",
}

SKILL_PATTERNS = {
    "SQL": ["sql", "querying"],
    "Python": ["python"],
    "Pandas": ["pandas"],
    "Jupyter": ["jupyter"],
    "Matplotlib": ["matplotlib"],
    "Excel": ["excel", "microsoft excel"],
    "Automation": ["automation", "automated", "workflow", "workflows"],
    "Reporting": ["reporting", "reports", "written reports"],
    "Data analysis": ["data analysis", "analysis and interpretation", "analytical"],
    "Data quality": ["data quality", "validation", "integrity", "quality checking"],
    "Metadata": ["metadata", "data dictionary", "data definitions", "standards"],
    "Data transformation": ["cleaning", "transformation", "extraction"],
    "Visualization": ["visualisation", "visualization"],
    "Stakeholder collaboration": [
        "stakeholder collaboration",
        "cross-functional collaboration",
        "multidisciplinary team",
    ],
    "Scientific communication": ["scientific publications", "scientific articles", "publications"],
    "AWS": ["aws"],
}

DOMAIN_PATTERNS = {
    "Healthcare": ["healthcare", "health", "clinical", "mental health"],
    "Research": ["research", "scientific", "science"],
    "Public sector": ["public value", "ministry", "government", "national"],
    "Higher education": ["university", "institute"],
    "Biotech": ["protein design", "biotechnology", "bioinformatics"],
}


def build_profile_from_files(
    cv_path: str | Path,
    cover_letter_path: str | Path,
) -> dict:
    cv_text = read_document_text(cv_path)
    cover_letter_text = read_document_text(cover_letter_path)
    return build_candidate_profile(
        cv_text,
        cover_letter_text,
        cv_path=str(cv_path),
        cover_letter_path=str(cover_letter_path),
    )


def build_candidate_profile(
    cv_text: str,
    cover_letter_text: str,
    *,
    cv_path: str | None = None,
    cover_letter_path: str | None = None,
) -> dict:
    sections = split_cv_sections(cv_text)
    combined_text = "\n".join([cv_text, cover_letter_text])

    skills = detect_pattern_matches(combined_text, SKILL_PATTERNS)
    domains = detect_pattern_matches(combined_text, DOMAIN_PATTERNS)
    target_role_from_cover_letter = extract_target_role(cover_letter_text)

    return {
        "name": extract_name(cv_text, cover_letter_text),
        "location": extract_location(cv_text, cover_letter_text),
        "email": extract_email(combined_text),
        "years_experience": extract_years_experience(combined_text),
        "summary": extract_summary(sections),
        "core_skills": skills,
        "domains": domains,
        "recent_roles": extract_recent_roles(sections.get("Professional Experience", [])),
        "target_role_from_cover_letter": target_role_from_cover_letter,
        "search_focus": build_search_focus(skills, domains, target_role_from_cover_letter),
        "source_files": {
            "cv": cv_path,
            "cover_letter": cover_letter_path,
        },
    }


def split_cv_sections(cv_text: str) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {"_header": []}
    current_section = "_header"

    for line in [line.strip() for line in cv_text.splitlines()]:
        if not line:
            continue
        if line in SECTION_HEADERS:
            current_section = line
            sections.setdefault(current_section, [])
            continue
        sections.setdefault(current_section, []).append(line)

    return sections


def extract_name(cv_text: str, cover_letter_text: str) -> str | None:
    combined_text = cv_text + "\n" + cover_letter_text
    combined_lines = [line.strip() for line in combined_text.splitlines() if line.strip()]
    email = extract_email(combined_text)

    if email:
        email_tokens = [
            token.lower()
            for token in re.split(r"[._-]", email.split("@", 1)[0])
            if token
        ]

        for line in combined_lines:
            normalized = normalize_name_candidate(line)
            if not normalized:
                continue
            lowered_name = normalized.lower()
            if all(token in lowered_name for token in email_tokens[:2]):
                return normalized

    for line in reversed(combined_lines):
        normalized = normalize_name_candidate(line)
        if normalized:
            return normalized

    return None


def normalize_name_candidate(line: str) -> str | None:
    candidate = line.replace("\t", " ").strip()
    candidate = re.sub(r",\s*M\.Sc\.$", "", candidate)
    candidate = re.sub(r",\s*M\.Sc\b", "", candidate)
    candidate = re.sub(r",\s*B\.Sc\b.*$", "", candidate)

    if "Dear " in candidate or candidate.startswith("I am writing"):
        return None
    if "@" in candidate or "|" in candidate:
        return None

    if re.fullmatch(r"[A-Z][a-z]+,\s*[A-Z][a-z]+", candidate):
        last_name, first_name = [part.strip() for part in candidate.split(",", 1)]
        return f"{first_name} {last_name}"

    if re.fullmatch(r"[A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3}", candidate):
        return candidate

    return None


def extract_location(cv_text: str, cover_letter_text: str) -> str | None:
    combined_lines = [line.strip() for line in (cv_text + "\n" + cover_letter_text).splitlines()]
    for line in combined_lines:
        if "Sydney" in line and "Australia" in line:
            return line
        if "Sydney" in line and "NSW" in line:
            return line
    return None


def extract_email(text: str) -> str | None:
    match = re.search(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", text)
    return match.group(0) if match else None


def extract_years_experience(text: str) -> int | None:
    plus_match = re.search(r"(\d+)\+\s*years", text, re.IGNORECASE)
    if plus_match:
        return int(plus_match.group(1))

    years = [int(value) for value in re.findall(r"\b(20\d{2})\b", text)]
    if years:
        return max(years) - min(years)

    return None


def extract_summary(sections: dict[str, list[str]]) -> str | None:
    summary_lines = sections.get("Professional Summary", [])
    if summary_lines:
        return " ".join(summary_lines[:2])
    header_lines = sections.get("_header", [])
    for line in header_lines:
        if len(line.split()) > 5:
            return line
    return None


def detect_pattern_matches(text: str, patterns: dict[str, list[str]]) -> list[str]:
    lowered = text.lower()
    matches = [
        label
        for label, keywords in patterns.items()
        if any(keyword in lowered for keyword in keywords)
    ]
    return sorted(matches)


def extract_target_role(cover_letter_text: str) -> str | None:
    match = re.search(
        r"position of\s+(.+?)(?:\.|$)",
        cover_letter_text,
        re.IGNORECASE,
    )
    if match:
        return match.group(1).strip()
    return None


def extract_recent_roles(experience_lines: list[str]) -> list[dict[str, str]]:
    roles: list[dict[str, str]] = []
    context_lines: list[str] = []

    for line in experience_lines:
        if "|" in line and not line.endswith("."):
            title, period = [part.strip() for part in line.split("|", 1)]
            organization = context_lines[0] if context_lines else ""
            location = context_lines[1] if len(context_lines) > 1 else ""
            role = {
                "title": title,
                "period": period,
                "organization": organization,
            }
            if location:
                role["location"] = location
            roles.append(role)
            continue

        if looks_like_context_line(line):
            if len(context_lines) == 2:
                context_lines = [line]
            else:
                context_lines.append(line)

    return roles


def looks_like_context_line(line: str) -> bool:
    if line.endswith("."):
        return False
    if len(line.split()) > 8:
        return False
    return True


def build_search_focus(
    skills: list[str],
    domains: list[str],
    target_role_from_cover_letter: str | None,
) -> dict:
    priority_titles = ["Senior Data Analyst"]

    if "Metadata" in skills:
        priority_titles.append("Metadata Analyst / Data Governance Analyst")
    if "Reporting" in skills:
        priority_titles.append("Reporting Analyst / Insights Analyst")
    if "Data quality" in skills:
        priority_titles.append("Data Quality Analyst")
    if "Healthcare" in domains:
        priority_titles.append("Health Data Analyst")
    if "Research" in domains:
        priority_titles.append("Research Data Analyst")
    if target_role_from_cover_letter:
        priority_titles.insert(0, target_role_from_cover_letter)

    keywords_to_include = [
        "SQL",
        "Python",
        "reporting",
        "data quality",
        "metadata",
        "automation",
        "health",
        "research",
    ]

    return {
        "priority_titles": dedupe(priority_titles),
        "priority_domains": domains,
        "location_preferences": ["Sydney", "NSW", "Australia", "Hybrid", "Remote"],
        "keywords_to_include": dedupe(keywords_to_include),
        "stretch_roles_to_treat_cautiously": [
            "Machine-learning-heavy Data Scientist roles",
            "Pure data platform or infrastructure engineering roles",
            "Roles that require deep BI tooling not shown in the CV",
        ],
    }


def dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
