from __future__ import annotations

from pathlib import Path

from .extractors import read_document_text
from .profile import DOMAIN_PATTERNS, SKILL_PATTERNS

ROLE_FAMILIES = {
    "analytics": ["analyst", "analytics", "insights", "reporting", "business intelligence", "bi"],
    "metadata": ["metadata", "data governance", "data dictionary", "data standards"],
    "quality": ["data quality", "validation", "integrity"],
    "engineering": ["data engineer", "pipeline", "warehousing", "infrastructure"],
    "science": ["data scientist", "machine learning", "predictive model"],
}

AUSTRALIA_LOCATION_TERMS = [
    "australia",
    "sydney",
    "nsw",
    "new south wales",
    "melbourne",
    "brisbane",
    "canberra",
    "perth",
    "remote",
    "hybrid",
]

NON_AUSTRALIA_LOCATION_TERMS = [
    "new york",
    "san francisco",
    "philadelphia",
    "london",
    "singapore",
    "usa",
    "united states",
    "uk",
]


def score_job_file(job_path: str | Path, profile: dict) -> dict:
    job_text = read_document_text(job_path)
    return score_job_text(job_text, profile, source_name=str(job_path))


def score_job_text(job_text: str, profile: dict, *, source_name: str | None = None) -> dict:
    lowered = job_text.lower()
    job_title = infer_job_title(job_text)
    job_skills = detect_matches(lowered, SKILL_PATTERNS)
    job_domains = detect_matches(lowered, DOMAIN_PATTERNS)

    candidate_skills = set(profile.get("core_skills", []))
    candidate_domains = set(profile.get("domains", []))
    target_titles = [title.lower() for title in profile.get("search_focus", {}).get("priority_titles", [])]

    matched_skills = sorted(candidate_skills.intersection(job_skills))
    missing_skills = sorted(set(job_skills) - candidate_skills)
    matched_domains = sorted(candidate_domains.intersection(job_domains))

    title_score, title_notes = score_title_alignment(job_title, target_titles)
    skill_score = score_ratio(len(matched_skills), len(job_skills), maximum=45, neutral=20)
    domain_score = score_ratio(len(matched_domains), len(job_domains), maximum=20, neutral=10)
    seniority_score = score_seniority(lowered, profile.get("years_experience"))
    location_score = score_location(lowered)
    penalty_score = 0

    if any(term in lowered for term in ROLE_FAMILIES["science"]):
        penalty_score += 20
    if any(term in lowered for term in ROLE_FAMILIES["engineering"]):
        penalty_score += 12

    total_score = max(
        0,
        min(
            100,
            title_score + skill_score + domain_score + seniority_score + location_score - penalty_score,
        ),
    )

    strengths: list[str] = []
    gaps: list[str] = []

    if matched_skills:
        strengths.append(f"Skill overlap: {', '.join(matched_skills[:6])}")
    if matched_domains:
        strengths.append(f"Domain overlap: {', '.join(matched_domains)}")
    if title_notes:
        strengths.extend(title_notes)
    if missing_skills:
        gaps.append(f"Missing or unclear skills: {', '.join(missing_skills[:6])}")

    if "machine learning" in lowered and "Data science" not in candidate_skills:
        gaps.append("The role leans toward machine learning more than the current CV does.")
    if any(term in lowered for term in ROLE_FAMILIES["engineering"]) and "Automation" not in candidate_skills:
        gaps.append("The role may lean more toward data engineering infrastructure than analytics/reporting.")

    return {
        "source_name": source_name,
        "job_title": job_title,
        "score": total_score,
        "matched_skills": matched_skills,
        "missing_skills": missing_skills,
        "matched_domains": matched_domains,
        "strengths": strengths,
        "gaps": gaps,
    }


def rank_job_files(job_paths: list[Path], profile: dict) -> list[dict]:
    ranked = [score_job_file(path, profile) for path in job_paths]
    return sorted(ranked, key=lambda item: item["score"], reverse=True)


def detect_matches(text: str, patterns: dict[str, list[str]]) -> set[str]:
    return {
        label
        for label, keywords in patterns.items()
        if any(keyword in text for keyword in keywords)
    }


def infer_job_title(job_text: str) -> str:
    for line in [line.strip() for line in job_text.splitlines() if line.strip()]:
        if len(line.split()) <= 14 and not line.endswith("."):
            return line
    return "Unknown title"


def score_title_alignment(job_title: str, target_titles: list[str]) -> tuple[int, list[str]]:
    lowered_title = job_title.lower()
    notes: list[str] = []

    if any(target in lowered_title for target in target_titles):
        notes.append("The role title directly matches the target search focus.")
        return 15, notes

    if any(keyword in lowered_title for keyword in ROLE_FAMILIES["metadata"]):
        notes.append("The title is aligned with metadata or governance work.")
        return 14, notes
    if any(keyword in lowered_title for keyword in ROLE_FAMILIES["analytics"]):
        notes.append("The title sits in the analytics/reporting family.")
        return 13, notes
    if any(keyword in lowered_title for keyword in ROLE_FAMILIES["quality"]):
        notes.append("The title maps well to data quality strengths.")
        return 12, notes
    if any(keyword in lowered_title for keyword in ROLE_FAMILIES["science"]):
        notes.append("The title shifts toward data science, which looks more like a stretch.")
        return 6, notes
    if any(keyword in lowered_title for keyword in ROLE_FAMILIES["engineering"]):
        notes.append("The title leans toward data engineering rather than analysis.")
        return 5, notes

    return 8, notes


def score_ratio(matches: int, total: int, *, maximum: int, neutral: int) -> int:
    if total == 0:
        return neutral
    return round((matches / total) * maximum)


def score_seniority(job_text: str, years_experience: int | None) -> int:
    if any(term in job_text for term in ("senior", "lead", "principal")):
        return 10 if (years_experience or 0) >= 8 else 6
    if "manager" in job_text:
        return 7 if (years_experience or 0) >= 8 else 5
    return 8


def score_location(job_text: str) -> int:
    if any(term in job_text for term in AUSTRALIA_LOCATION_TERMS):
        return 10
    if any(term in job_text for term in NON_AUSTRALIA_LOCATION_TERMS):
        return 2
    return 5
