from __future__ import annotations

import re
from pathlib import Path

from . import config as _config
from .extractors import read_document_text
from .jobs import infer_manual_title, job_record_to_text
from .matching import (
    MatchableText,
    contains_any_keyword,
    contains_keyword,
    find_pattern_matches,
    prepare_matchable_text,
)
from .types import ScoredJob


def score_job_file(job_path: str | Path, profile: dict) -> ScoredJob:
    job_text = read_document_text(job_path)
    return score_job_text(job_text, profile, source_name=str(job_path))


def score_job_record(job_record: dict, profile: dict) -> ScoredJob:
    result = score_job_text(
        job_record_to_text(job_record),
        profile,
        source_name=job_record.get("source") or job_record.get("id"),
    )
    result.update(
        {
            "job_id": job_record.get("id"),
            "company": job_record.get("company"),
            "location": job_record.get("location"),
            "url": job_record.get("url"),
            "source": job_record.get("source"),
            "salary_min": job_record.get("salary_min"),
            "salary_max": job_record.get("salary_max"),
            "currency": job_record.get("currency"),
            "employment_type": job_record.get("employment_type"),
            "posted_at": job_record.get("posted_at"),
        }
    )
    return result


def score_job_text(job_text: str, profile: dict, *, source_name: str | None = None) -> ScoredJob:
    cfg = _config.active()
    prepared = prepare_matchable_text(job_text)
    job_title = infer_job_title(job_text)
    job_skills = detect_matches(prepared, cfg.skill_patterns)
    job_domains = detect_matches(prepared, cfg.domain_patterns)

    candidate_skills = set(profile.get("core_skills", []))
    candidate_domains = set(profile.get("domains", []))
    target_titles = profile.get("search_focus", {}).get("priority_titles", [])

    matched_skills = sorted(candidate_skills.intersection(job_skills))
    missing_skills = sorted(set(job_skills) - candidate_skills)
    matched_domains = sorted(candidate_domains.intersection(job_domains))

    title_score, title_notes = score_title_alignment(job_title, target_titles)
    skill_score = score_ratio(len(matched_skills), len(job_skills), maximum=45, neutral=10)
    domain_score = score_ratio(len(matched_domains), len(job_domains), maximum=20, neutral=5)
    seniority_score = score_seniority(prepared, profile.get("years_experience"))
    location_score = score_location(prepared)
    penalty_score = 0

    for family, penalty in cfg.role_penalties.items():
        keywords = cfg.role_families.get(family)
        if keywords and contains_any_keyword(prepared, keywords):
            penalty_score += penalty

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

    if contains_keyword(prepared, "machine learning") and "Data science" not in candidate_skills:
        gaps.append("The role leans toward machine learning more than the current CV does.")
    if contains_any_keyword(prepared, cfg.role_families.get("engineering", [])) and "Automation" not in candidate_skills:
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


def rank_job_files(job_paths: list[Path], profile: dict) -> list[ScoredJob]:
    ranked = [score_job_file(path, profile) for path in job_paths]
    return sorted(ranked, key=lambda item: item["score"], reverse=True)


def rank_job_records(job_records: list[dict], profile: dict) -> list[ScoredJob]:
    ranked = [score_job_record(record, profile) for record in job_records]
    return sorted(ranked, key=lambda item: item["score"], reverse=True)


def detect_matches(text: str | MatchableText, patterns: dict[str, list[str]]) -> set[str]:
    return set(find_pattern_matches(text, patterns))


def infer_job_title(job_text: str) -> str:
    return infer_manual_title(job_text, fallback="Unknown title")


def score_title_alignment(job_title: str, target_titles: list[str]) -> tuple[int, list[str]]:
    cfg = _config.active()
    prepared = prepare_matchable_text(strip_parenthetical_text(job_title))
    notes: list[str] = []
    families = cfg.role_families

    if any(contains_keyword(prepared, strip_parenthetical_text(target)) for target in target_titles):
        notes.append("The role title directly matches the target search focus.")
        return 15, notes

    if contains_any_keyword(prepared, families.get("metadata", [])):
        notes.append("The title is aligned with metadata or governance work.")
        return 14, notes
    if contains_any_keyword(prepared, families.get("analytics", [])):
        notes.append("The title sits in the analytics/reporting family.")
        return 13, notes
    if contains_any_keyword(prepared, families.get("quality", [])):
        notes.append("The title maps well to data quality strengths.")
        return 12, notes
    if contains_any_keyword(prepared, families.get("science", [])):
        notes.append("The title shifts toward data science, which looks more like a stretch.")
        return 6, notes
    if contains_any_keyword(prepared, families.get("engineering", [])):
        notes.append("The title leans toward data engineering rather than analysis.")
        return 5, notes

    return 8, notes


def score_ratio(matches: int, total: int, *, maximum: int, neutral: int) -> int:
    if total == 0:
        return neutral
    return round((matches / total) * maximum)


def score_seniority(job_text: str | MatchableText, years_experience: int | None) -> int:
    if contains_any_keyword(job_text, ["senior", "lead", "principal"]):
        return 10 if (years_experience or 0) >= 8 else 6
    if contains_keyword(job_text, "manager"):
        return 7 if (years_experience or 0) >= 8 else 5
    return 8


def score_location(job_text: str | MatchableText) -> int:
    cfg = _config.active()
    if contains_any_keyword(job_text, cfg.location_secondary_terms):
        return 2
    if contains_any_keyword(job_text, cfg.location_primary_terms):
        return 10
    if contains_any_keyword(job_text, cfg.location_remote_terms):
        return 6
    return 5


def strip_parenthetical_text(value: str) -> str:
    return re.sub(r"\s*\(.*?\)", "", value).strip()
