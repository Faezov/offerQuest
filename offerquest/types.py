from __future__ import annotations

from typing import Any, NotRequired, TypedDict


class JobRecord(TypedDict):
    id: str
    source: str
    external_id: str | None
    title: str | None
    company: str | None
    location: str | None
    country: str | None
    description_text: str
    employment_type: str | None
    salary_min: float | None
    salary_max: float | None
    currency: str | None
    url: str | None
    posted_at: str | None
    fetched_at: str | None
    metadata: dict[str, Any]


class SearchFocus(TypedDict):
    priority_titles: list[str]
    mapped_focus: NotRequired[str | None]


class SourceFiles(TypedDict):
    cv: str | None
    cover_letter: str | None


class CandidateProfile(TypedDict):
    name: str | None
    location: str | None
    email: str | None
    years_experience: int | None
    summary: str | None
    core_skills: list[str]
    domains: list[str]
    recent_roles: list[str]
    target_role_from_cover_letter: str | None
    search_focus: SearchFocus
    source_files: SourceFiles
    quality_warnings: list[str]


class ScoredJob(TypedDict):
    source_name: str | None
    job_title: str
    score: int
    matched_skills: list[str]
    missing_skills: list[str]
    matched_domains: list[str]
    strengths: list[str]
    gaps: list[str]
    # Fields added when scoring from a job record
    job_id: NotRequired[str | None]
    company: NotRequired[str | None]
    location: NotRequired[str | None]
    url: NotRequired[str | None]
    source: NotRequired[str | None]
    salary_min: NotRequired[float | None]
    salary_max: NotRequired[float | None]
    currency: NotRequired[str | None]
    employment_type: NotRequired[str | None]
    posted_at: NotRequired[str | None]


class KeywordCoverage(TypedDict):
    has_signal: bool
    coverage_percent: float
    matched_count: int
    total_count: int
    matched_keywords: list[str]
    missing_keywords: list[str]


class RequiredKeywords(TypedDict):
    has_signal: bool
    coverage_percent: float
    matched: list[str]
    missing: list[str]


class ATSReport(TypedDict):
    job_title: str
    ats_score: int
    assessment: str
    suggested_resume_title: str
    fit_snapshot: ScoredJob
    keyword_coverage: KeywordCoverage
    required_keywords: RequiredKeywords
    section_checks: dict[str, Any]
    contact_checks: dict[str, Any]
    format_risks: list[str]
    suggestions: list[str]
    # Fields added when checking from a job record
    job_id: NotRequired[str | None]
    company: NotRequired[str | None]
    location: NotRequired[str | None]
    job_url: NotRequired[str | None]
    job_source: NotRequired[str | None]
