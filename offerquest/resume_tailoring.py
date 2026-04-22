from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .ats import build_ats_report
from .cover_letter import (
    build_profile_evidence_fragments,
    build_safe_skill_phrase,
    join_human_list,
    lower_keywords,
)
from .extractors import read_document_text
from .jobs import job_record_to_text
from .profile import build_candidate_profile, split_cv_sections

FOCUS_GUIDANCE = {
    "SQL": "Surface concrete SQL querying, reporting, or transformation work near the top of the resume.",
    "Python": "Highlight Python-based analysis, automation, or data preparation work with specific outcomes.",
    "Reporting": "Bring reporting cadence, stakeholder-ready outputs, or KPI reporting examples into top bullets.",
    "Dashboards": "If true, reference dashboard delivery, dashboard maintenance, or dashboard adoption outcomes.",
    "Power BI": "Only add Power BI if you can support it with real usage or adjacent BI tooling evidence.",
    "Metadata": "Emphasize metadata definitions, data dictionaries, governance, or standards work.",
    "Data quality": "Show validation, QA, integrity checking, or error-reduction work in recent experience.",
    "Stakeholder management": "Use bullets that show partnering with non-technical stakeholders and translating needs.",
    "Stakeholder collaboration": "Use bullets that show cross-functional delivery and collaboration with end users.",
    "Healthcare": "Foreground healthcare, clinical, or public-health context if it is already present in the CV.",
    "Research": "Call out research, evidence synthesis, or publication-facing analysis where relevant.",
    "Finance": "Only mention finance directly if your experience clearly supports it.",
    "Automation": "Surface workflow automation, repeatability, or process improvement outcomes.",
}

ROLE_TITLE_FAMILIES = {
    "analytics": ["analyst", "analytics", "reporting", "insights", "business intelligence", "bi"],
    "metadata": ["metadata", "governance"],
    "quality": ["quality", "validation", "integrity"],
    "science": ["scientist", "machine learning"],
    "engineering": ["engineer", "engineering", "pipeline", "warehousing", "infrastructure"],
}

TITLE_KEYWORDS = {"analyst", "analytics", "scientist", "engineer", "manager", "specialist"}
IGNORED_LEADING_TITLE_TOKENS = {
    "accomplished",
    "driven",
    "experienced",
    "motivated",
    "results",
    "seasoned",
}

GENERIC_PROFILE_TITLES = [
    ("Reporting", "Reporting Analyst"),
    ("Metadata", "Metadata Analyst"),
    ("Data quality", "Data Quality Analyst"),
]


def build_resume_tailoring_plan_for_job_record(
    cv_path: str | Path,
    job_record: dict[str, Any],
    *,
    cover_letter_path: str | Path | None = None,
) -> dict[str, Any]:
    cv_text = read_document_text(cv_path)
    cover_letter_text = read_optional_text(cover_letter_path)
    job_text = job_record_to_text(job_record)

    plan = build_resume_tailoring_plan(
        cv_text,
        job_text,
        cv_path=str(cv_path),
        cover_letter_text=cover_letter_text,
    )
    plan.update(
        {
            "job_id": job_record.get("id"),
            "job_title": job_record.get("title") or plan.get("job_title"),
            "company": job_record.get("company"),
            "location": job_record.get("location"),
            "job_url": job_record.get("url"),
            "job_source": job_record.get("source"),
        }
    )
    return plan


def build_resume_tailored_draft_for_job_record(
    cv_path: str | Path,
    job_record: dict[str, Any],
    *,
    cover_letter_path: str | Path | None = None,
) -> dict[str, Any]:
    cv_text = read_document_text(cv_path)
    cover_letter_text = read_optional_text(cover_letter_path)
    job_text = job_record_to_text(job_record)

    draft = build_resume_tailored_draft(
        cv_text,
        job_text,
        cv_path=str(cv_path),
        cover_letter_text=cover_letter_text,
    )
    draft.update(
        {
            "job_id": job_record.get("id"),
            "job_title": job_record.get("title") or draft.get("job_title"),
            "company": job_record.get("company"),
            "location": job_record.get("location"),
            "job_url": job_record.get("url"),
            "job_source": job_record.get("source"),
        }
    )
    return draft


def build_resume_tailoring_plan(
    cv_text: str,
    job_text: str,
    *,
    cv_path: str | None = None,
    cover_letter_text: str = "",
) -> dict[str, Any]:
    profile = build_candidate_profile(
        cv_text,
        cover_letter_text,
        cv_path=cv_path,
    )
    ats_report = build_ats_report(
        cv_text,
        job_text,
        cv_path=cv_path,
        cover_letter_text=cover_letter_text,
    )
    sections = split_cv_sections(cv_text)

    focus_keywords = prioritize_keywords(
        ats_report["required_keywords"]["matched"],
        ats_report["keyword_coverage"]["matched_keywords"],
    )
    missing_keywords = prioritize_keywords(
        ats_report["required_keywords"]["missing"],
        ats_report["keyword_coverage"]["missing_keywords"],
    )

    plan = {
        "job_title": ats_report["job_title"],
        "ats_snapshot": {
            "score_before": ats_report["ats_score"],
            "assessment": ats_report["assessment"],
            "suggested_resume_title": ats_report["suggested_resume_title"],
        },
        "keyword_plan": {
            "focus_keywords": focus_keywords[:8],
            "missing_keywords": missing_keywords[:8],
            "matched_required_keywords": ats_report["required_keywords"]["matched"],
            "missing_required_keywords": ats_report["required_keywords"]["missing"],
        },
        "sections_to_update_first": build_priority_sections(
            sections=sections,
            ats_report=ats_report,
            focus_keywords=focus_keywords,
            missing_keywords=missing_keywords,
        ),
        "headline_plan": build_headline_plan(profile, ats_report),
        "summary_plan": build_summary_plan(profile, ats_report, focus_keywords, missing_keywords),
        "skills_plan": build_skills_plan(profile, focus_keywords, missing_keywords),
        "experience_plan": build_experience_plan(profile, focus_keywords, missing_keywords),
        "format_plan": build_format_plan(ats_report),
        "truthfulness_notes": build_truthfulness_notes(missing_keywords),
        "profile_quality_warnings": profile.get("quality_warnings", []),
        "source_files": profile.get("source_files", {}),
    }
    return plan


def build_resume_tailored_draft(
    cv_text: str,
    job_text: str,
    *,
    cv_path: str | None = None,
    cover_letter_text: str = "",
) -> dict[str, Any]:
    plan = build_resume_tailoring_plan(
        cv_text,
        job_text,
        cv_path=cv_path,
        cover_letter_text=cover_letter_text,
    )
    profile = build_candidate_profile(
        cv_text,
        cover_letter_text,
        cv_path=cv_path,
    )
    sections = split_cv_sections(cv_text)

    headline = plan["headline_plan"]["recommended_title"]
    header_lines = build_tailored_header_lines(sections.get("_header", []), headline)
    summary_text = build_tailored_summary(profile, plan)
    skills_before = extract_current_skills(sections, profile)
    skills_after = build_tailored_skills(profile, plan, current_skills=skills_before)
    tailored_sections = build_tailored_sections(
        sections,
        header_lines=header_lines,
        summary_text=summary_text,
        skills=skills_after,
    )
    tailored_cv_text = render_tailored_resume_text(tailored_sections)

    ats_before = build_ats_report(
        cv_text,
        job_text,
        cv_path=cv_path,
        cover_letter_text=cover_letter_text,
    )
    ats_after = build_ats_report(
        tailored_cv_text,
        job_text,
        cv_path="tailored-resume.txt",
        cover_letter_text=cover_letter_text,
    )

    return {
        "job_title": plan["job_title"],
        "plan": plan,
        "original_cv_text": cv_text,
        "tailored_cv_text": tailored_cv_text,
        "ats_before": ats_before,
        "ats_after": ats_after,
        "ats_delta": build_ats_delta(ats_before, ats_after),
        "section_changes": {
            "headline_after": headline,
            "summary_before": plan["summary_plan"]["current_summary"],
            "summary_after": summary_text,
            "skills_before": skills_before,
            "skills_after": skills_after,
            "skills_added_from_candidate_docs": [
                skill for skill in skills_after if skill not in skills_before
            ],
        },
    }


def build_priority_sections(
    *,
    sections: dict[str, list[str]],
    ats_report: dict[str, Any],
    focus_keywords: list[str],
    missing_keywords: list[str],
) -> list[dict[str, str]]:
    priorities: list[dict[str, str]] = []
    suggested_title = ats_report["suggested_resume_title"]

    priorities.append(
        {
            "section": "Resume Headline",
            "priority": "high",
            "reason": f"Use a headline close to `{suggested_title}` if it truthfully matches the role you are targeting.",
        }
    )

    if sections.get("Professional Summary"):
        summary_reason = (
            "Refocus the existing summary around the target role and your strongest overlapping keywords: "
            + ", ".join(focus_keywords[:4])
        )
    else:
        summary_reason = (
            "Add a short Professional Summary near the top so ATS systems see the target role family and strongest overlap quickly."
        )
    priorities.append(
        {
            "section": "Professional Summary",
            "priority": "high",
            "reason": summary_reason,
        }
    )

    skills_reason = "Reorder Core Skills so the most relevant tools are visible first."
    if missing_keywords:
        skills_reason += " Add any of these only if they are genuinely supported: " + ", ".join(missing_keywords[:4])
    priorities.append(
        {
            "section": "Core Skills",
            "priority": "high",
            "reason": skills_reason,
        }
    )

    experience_reason = "Update the first one or two experience entries so they prove the job-facing keywords in action."
    if focus_keywords:
        experience_reason += " Start with evidence for " + ", ".join(focus_keywords[:4]) + "."
    priorities.append(
        {
            "section": "Professional Experience",
            "priority": "medium",
            "reason": experience_reason,
        }
    )

    if ats_report["section_checks"]["missing"] or ats_report["format_risks"]:
        priorities.append(
            {
                "section": "ATS Structure Pass",
                "priority": "medium",
                "reason": "Fix structural issues before deeper tailoring so the resume remains easy to parse.",
            }
        )

    return priorities


def build_headline_plan(profile: dict[str, Any], ats_report: dict[str, Any]) -> dict[str, Any]:
    current_target = profile.get("target_role_from_cover_letter")
    suggested_title = ats_report["suggested_resume_title"]
    supported_titles = collect_supported_resume_titles(profile)
    can_mirror_job_title = title_is_supported_by_profile(
        suggested_title,
        supported_titles=supported_titles,
    )
    recommended = suggested_title if can_mirror_job_title else choose_fallback_resume_title(
        profile,
        supported_titles=supported_titles,
    )

    if can_mirror_job_title:
        reason = (
            f"The job title `{suggested_title}` stays within the role family already supported by the current CV evidence."
        )
    else:
        reason = (
            f"The job title `{suggested_title}` looks like a stretch beyond the current CV evidence, so keep the headline grounded in `{recommended}`."
        )

    return {
        "current_target": current_target,
        "job_title_to_mirror": suggested_title,
        "can_mirror_job_title": can_mirror_job_title,
        "recommended_title": recommended,
        "recommended_title_source": "job_title" if can_mirror_job_title else "profile_evidence",
        "supported_profile_titles": supported_titles[:8],
        "reason": reason,
    }


def build_summary_plan(
    profile: dict[str, Any],
    ats_report: dict[str, Any],
    focus_keywords: list[str],
    missing_keywords: list[str],
) -> dict[str, Any]:
    guidance = [
        f"Open with a role family close to `{ats_report['suggested_resume_title']}` if that is a fair description of your target search.",
        "Use the first two lines to connect your strongest evidence to this job instead of listing every tool equally.",
    ]

    if focus_keywords:
        guidance.append(
            "Make these strengths easy to spot in the summary: " + ", ".join(focus_keywords[:4])
        )
    if missing_keywords:
        guidance.append(
            "Do not add unsupported claims. Only weave in these missing terms where you have real evidence: "
            + ", ".join(missing_keywords[:4])
        )

    return {
        "current_summary": profile.get("summary"),
        "focus_keywords": focus_keywords[:6],
        "keywords_to_add_if_true": missing_keywords[:6],
        "evidence_to_ground": build_evidence_items(profile, focus_keywords),
        "guidance": guidance,
    }


def build_skills_plan(
    profile: dict[str, Any],
    focus_keywords: list[str],
    missing_keywords: list[str],
) -> dict[str, Any]:
    current_skills = profile.get("core_skills", [])
    visible_first = [keyword for keyword in focus_keywords if keyword in current_skills]
    add_if_true = [keyword for keyword in missing_keywords if keyword not in current_skills]
    deprioritize = [
        skill
        for skill in current_skills
        if skill not in visible_first and skill not in add_if_true
    ]

    return {
        "current_skills": current_skills,
        "skills_to_keep_visible": visible_first[:8],
        "skills_to_add_if_true": add_if_true[:8],
        "skills_to_deprioritize": deprioritize[:5],
    }


def build_experience_plan(
    profile: dict[str, Any],
    focus_keywords: list[str],
    missing_keywords: list[str],
) -> dict[str, Any]:
    recent_roles = profile.get("recent_roles", [])
    roles_to_surface = [format_role(role) for role in recent_roles[:3]]
    bullet_focus = build_bullet_focus(focus_keywords, missing_keywords)

    return {
        "roles_to_surface": roles_to_surface,
        "bullet_focus": bullet_focus,
        "evidence_to_reuse": build_evidence_items(profile, focus_keywords)[:6],
    }


def build_format_plan(ats_report: dict[str, Any]) -> dict[str, Any]:
    return {
        "missing_sections": ats_report["section_checks"]["missing"],
        "format_risks": ats_report["format_risks"],
        "ats_suggestions": ats_report["suggestions"][:6],
    }


def build_truthfulness_notes(missing_keywords: list[str]) -> list[str]:
    notes = [
        "Do not add tools, domains, or responsibilities unless the CV can already support them truthfully.",
        "When a keyword is only adjacent to your experience, phrase it cautiously instead of claiming deep ownership.",
        "Prefer evidence and outcomes over keyword stuffing in the summary or skills section.",
    ]
    if missing_keywords:
        notes.append(
            "The main gap terms to treat carefully are: " + ", ".join(missing_keywords[:5])
        )
    return notes


def build_bullet_focus(focus_keywords: list[str], missing_keywords: list[str]) -> list[str]:
    prompts: list[str] = []

    for keyword in focus_keywords[:4]:
        prompts.append(FOCUS_GUIDANCE.get(keyword, f"Use a recent bullet that clearly demonstrates {keyword}."))

    for keyword in missing_keywords[:3]:
        prompts.append(
            f"Only if true, add a bullet or skills reference that gives real evidence for {keyword}."
        )

    return dedupe_preserve_order(prompts)


def build_tailored_header_lines(header_lines: list[str], headline: str) -> list[str]:
    lines = [line.strip() for line in header_lines if line.strip()]
    if not headline:
        return lines

    lowered_headline = headline.lower()
    if any(line.lower() == lowered_headline for line in lines):
        return lines

    insert_index = find_header_insert_index(lines)
    return lines[:insert_index] + [headline] + lines[insert_index:]


def find_header_insert_index(header_lines: list[str]) -> int:
    if not header_lines:
        return 0

    index = 1
    for candidate_index, line in enumerate(header_lines[1:], start=1):
        lowered = line.lower()
        if "@" in line or "," in line or "|" in line:
            index = candidate_index + 1
            continue
        if lowered in {"remote", "hybrid", "onsite"}:
            index = candidate_index + 1
            continue
        break
    return index


def build_tailored_summary(profile: dict[str, Any], plan: dict[str, Any]) -> str:
    recommended_title = plan["headline_plan"]["recommended_title"] or "Data Analyst"
    focus_keywords = list(plan["keyword_plan"]["focus_keywords"])
    safe_additions = build_safe_keyword_additions(profile, plan)

    priority_skills = [
        keyword
        for keyword in dedupe_preserve_order([*focus_keywords, *safe_additions])
        if keyword in profile.get("core_skills", [])
    ]
    domain_terms = [
        keyword
        for keyword in dedupe_preserve_order([*focus_keywords, *safe_additions])
        if keyword in profile.get("domains", [])
    ]

    if priority_skills:
        skill_phrase = join_human_list(lower_keywords(priority_skills[:4]))
    else:
        skill_phrase = build_safe_skill_phrase(profile)

    sentence_one = f"{recommended_title} with experience in {skill_phrase}"
    if domain_terms:
        sentence_one += f" across {join_human_list(lower_keywords(domain_terms[:2]))} settings"
    sentence_one += "."

    evidence_fragments = build_profile_evidence_fragments(profile)
    if evidence_fragments:
        sentence_two = f"Recent work includes {join_human_list(evidence_fragments[:2])}."
    elif plan["summary_plan"]["current_summary"]:
        sentence_two = plan["summary_plan"]["current_summary"].rstrip(".") + "."
    else:
        sentence_two = "Focus the top of the resume on recent analytical work with clear, evidence-based outcomes."

    return " ".join([sentence_one, sentence_two]).strip()


def extract_current_skills(sections: dict[str, list[str]], profile: dict[str, Any]) -> list[str]:
    core_skills_lines = [line.strip() for line in sections.get("Core Skills", []) if line.strip()]
    if core_skills_lines:
        return core_skills_lines
    return list(profile.get("core_skills", []))


def build_tailored_skills(
    profile: dict[str, Any],
    plan: dict[str, Any],
    *,
    current_skills: list[str],
) -> list[str]:
    keep_visible = [
        skill
        for skill in plan["skills_plan"]["skills_to_keep_visible"]
        if skill in profile.get("core_skills", []) or skill in current_skills
    ]
    safe_additions = [
        skill
        for skill in build_safe_keyword_additions(profile, plan)
        if skill in profile.get("core_skills", [])
    ]
    return dedupe_preserve_order([*keep_visible, *safe_additions, *current_skills])


def build_safe_keyword_additions(profile: dict[str, Any], plan: dict[str, Any]) -> list[str]:
    candidate_terms = set(profile.get("core_skills", [])) | set(profile.get("domains", []))
    return [
        keyword
        for keyword in plan["keyword_plan"]["missing_keywords"]
        if keyword in candidate_terms
    ]


def build_tailored_sections(
    sections: dict[str, list[str]],
    *,
    header_lines: list[str],
    summary_text: str,
    skills: list[str],
) -> dict[str, list[str]]:
    tailored = {
        "_header": header_lines,
        "Professional Summary": [summary_text],
        "Core Skills": skills,
    }

    for section_name, lines in sections.items():
        if section_name in {"_header", "Professional Summary", "Core Skills"}:
            continue
        tailored[section_name] = lines

    return tailored


def render_tailored_resume_text(sections: dict[str, list[str]]) -> str:
    blocks: list[str] = []

    header_lines = [line for line in sections.get("_header", []) if line]
    if header_lines:
        blocks.append("\n".join(header_lines))

    rendered_section_names = [
        "Professional Summary",
        "Core Skills",
        *[
            section_name
            for section_name in sections
            if section_name not in {"_header", "Professional Summary", "Core Skills"}
        ],
    ]

    for section_name in rendered_section_names:
        lines = [line for line in sections.get(section_name, []) if line]
        if not lines:
            continue
        blocks.append(section_name + "\n" + "\n".join(lines))

    return "\n\n".join(blocks).strip() + "\n"


def build_ats_delta(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    before_matched = set(before["keyword_coverage"]["matched_keywords"])
    after_matched = set(after["keyword_coverage"]["matched_keywords"])
    before_missing = set(before["keyword_coverage"]["missing_keywords"])
    after_missing = set(after["keyword_coverage"]["missing_keywords"])

    return {
        "score_before": before["ats_score"],
        "score_after": after["ats_score"],
        "score_change": after["ats_score"] - before["ats_score"],
        "gained_keywords": sorted(after_matched - before_matched),
        "resolved_missing_keywords": sorted(before_missing - after_missing),
        "remaining_missing_keywords": after["keyword_coverage"]["missing_keywords"],
    }


def build_evidence_items(profile: dict[str, Any], focus_keywords: list[str]) -> list[str]:
    evidence: list[str] = []
    summary = profile.get("summary")
    if summary:
        evidence.append(summary)

    domains = profile.get("domains", [])
    if domains:
        evidence.append("Relevant domain context already present: " + ", ".join(domains[:3]))

    matched_skills = [keyword for keyword in focus_keywords if keyword in profile.get("core_skills", [])]
    if matched_skills:
        evidence.append("Current strengths already visible in the CV: " + ", ".join(matched_skills[:5]))

    for role in profile.get("recent_roles", [])[:3]:
        evidence.append(format_role(role))

    return dedupe_preserve_order(evidence)


def prioritize_keywords(primary: list[str], secondary: list[str]) -> list[str]:
    return dedupe_preserve_order([*primary, *secondary])


def format_role(role: dict[str, Any]) -> str:
    title = str(role.get("title") or "").strip()
    organization = str(role.get("organization") or "").strip()
    period = str(role.get("period") or "").strip()

    parts = [part for part in [title, organization] if part]
    label = " at ".join(parts) if len(parts) == 2 else (parts[0] if parts else "Recent role")
    if period:
        return f"{label} ({period})"
    return label


def dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        cleaned = str(value).strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        result.append(cleaned)
    return result


def read_optional_text(path: str | Path | None) -> str:
    if path is None:
        return ""
    return read_document_text(path)


def collect_supported_resume_titles(profile: dict[str, Any]) -> list[str]:
    supported: list[str] = []

    summary = profile.get("summary")
    if summary:
        supported.extend(extract_title_candidates_from_summary(summary))

    for role in profile.get("recent_roles", []):
        title = str(role.get("title") or "").strip()
        if title:
            supported.append(title)

    supported.extend(build_generic_profile_titles(profile))
    return dedupe_preserve_order(supported)


def extract_title_candidates_from_summary(summary: str) -> list[str]:
    match = re.match(
        r"\s*([A-Za-z][A-Za-z/&\-\s]{0,60}?(?:analyst|analytics|scientist|engineer|manager|specialist))\b",
        summary,
        flags=re.IGNORECASE,
    )
    if not match:
        return []

    raw_title = normalize_role_title(match.group(1))
    if not raw_title:
        return []
    return [raw_title]


def build_generic_profile_titles(profile: dict[str, Any]) -> list[str]:
    skills = set(profile.get("core_skills", []))
    domains = set(profile.get("domains", []))
    max_seniority_rank = infer_profile_seniority_rank(profile)
    prefix = seniority_prefix_for_rank(max_seniority_rank)

    titles = []
    if skills.intersection({"SQL", "Python", "Reporting", "Data analysis"}):
        titles.append(prefix + "Data Analyst")
    for skill, title in GENERIC_PROFILE_TITLES:
        if skill in skills:
            titles.append(prefix + title)
    if "Healthcare" in domains:
        titles.append(prefix + "Health Data Analyst")
    if "Research" in domains:
        titles.append(prefix + "Research Data Analyst")
    return titles


def infer_profile_seniority_rank(profile: dict[str, Any]) -> int:
    candidates: list[str] = []
    summary = profile.get("summary")
    if summary:
        candidates.extend(extract_title_candidates_from_summary(summary))
    candidates.extend(
        str(role.get("title") or "").strip()
        for role in profile.get("recent_roles", [])
        if str(role.get("title") or "").strip()
    )

    if not candidates:
        years_experience = profile.get("years_experience") or 0
        return 3 if years_experience >= 8 else 2

    return max(infer_title_seniority_rank(title) for title in candidates)


def seniority_prefix_for_rank(rank: int) -> str:
    if rank >= 5:
        return "Principal "
    if rank >= 4:
        return "Lead "
    if rank >= 3:
        return "Senior "
    return ""


def title_is_supported_by_profile(candidate_title: str, *, supported_titles: list[str]) -> bool:
    normalized_candidate = normalize_role_title(candidate_title)
    normalized_supported = [normalize_role_title(title) for title in supported_titles if title]

    if not normalized_candidate:
        return False
    if normalized_candidate in normalized_supported:
        return True

    candidate_family = infer_title_family(normalized_candidate)
    if candidate_family is None:
        return False

    family_supported_titles = [
        title
        for title in normalized_supported
        if infer_title_family(title) == candidate_family
    ]
    if not family_supported_titles:
        return False

    candidate_rank = infer_title_seniority_rank(normalized_candidate)
    supported_rank = max(infer_title_seniority_rank(title) for title in family_supported_titles)
    return candidate_rank <= supported_rank


def choose_fallback_resume_title(profile: dict[str, Any], *, supported_titles: list[str]) -> str:
    if supported_titles:
        return supported_titles[0]

    domains = set(profile.get("domains", []))
    if "Healthcare" in domains:
        return "Health Data Analyst"
    if "Research" in domains:
        return "Research Data Analyst"
    return "Data Analyst"


def infer_title_family(title: str) -> str | None:
    lowered = title.lower()
    for family, keywords in ROLE_TITLE_FAMILIES.items():
        if any(keyword in lowered for keyword in keywords):
            return family
    return None


def infer_title_seniority_rank(title: str) -> int:
    lowered = title.lower()
    if any(keyword in lowered for keyword in {"director", "head"}):
        return 6
    if any(keyword in lowered for keyword in {"manager"}):
        return 5
    if "principal" in lowered:
        return 5
    if "lead" in lowered:
        return 4
    if "senior" in lowered:
        return 3
    if any(keyword in lowered for keyword in {"junior", "associate", "assistant", "intern"}):
        return 1
    return 2


def normalize_role_title(title: str) -> str:
    tokens = re.findall(r"[A-Za-z]+", title)
    if not tokens:
        return ""

    while tokens and tokens[0].lower() in IGNORED_LEADING_TITLE_TOKENS and len(tokens) > 1:
        tokens = tokens[1:]

    if not tokens or not any(token.lower() in TITLE_KEYWORDS for token in tokens):
        return ""

    return " ".join(token.upper() if token.isupper() else token.title() for token in tokens)
