from __future__ import annotations

from pathlib import Path
from typing import Any

from .ats import build_ats_report
from .extractors import read_document_text
from .jobs import job_record_to_text
from .scoring import score_job_file, score_job_record


def rerank_job_files(
    job_paths: list[Path],
    profile: dict[str, Any],
    *,
    cv_text: str,
    cv_path: str | Path,
    cover_letter_text: str = "",
    top_n: int = 20,
) -> list[dict[str, Any]]:
    scored_candidates = [
        {
            "result": score_job_file(path, profile),
            "job_text": read_document_text(path),
        }
        for path in job_paths
    ]
    scored_candidates.sort(key=lambda item: item["result"]["score"], reverse=True)
    return rerank_scored_candidates(
        scored_candidates,
        cv_text=cv_text,
        cv_path=cv_path,
        cover_letter_text=cover_letter_text,
        top_n=top_n,
    )


def rerank_job_records(
    job_records: list[dict[str, Any]],
    profile: dict[str, Any],
    *,
    cv_text: str,
    cv_path: str | Path,
    cover_letter_text: str = "",
    top_n: int = 20,
) -> list[dict[str, Any]]:
    scored_candidates = [
        {
            "result": score_job_record(record, profile),
            "job_text": job_record_to_text(record),
        }
        for record in job_records
    ]
    scored_candidates.sort(key=lambda item: item["result"]["score"], reverse=True)
    return rerank_scored_candidates(
        scored_candidates,
        cv_text=cv_text,
        cv_path=cv_path,
        cover_letter_text=cover_letter_text,
        top_n=top_n,
    )


def rerank_scored_candidates(
    scored_candidates: list[dict[str, Any]],
    *,
    cv_text: str,
    cv_path: str | Path,
    cover_letter_text: str,
    top_n: int,
) -> list[dict[str, Any]]:
    rerank_window = min(max(top_n, 0), len(scored_candidates))
    reranked_window: list[dict[str, Any]] = []
    untouched_tail: list[dict[str, Any]] = []

    for original_rank, candidate in enumerate(scored_candidates, start=1):
        item = dict(candidate["result"])
        initial_score = int(item["score"])
        item["original_rank"] = original_rank
        item["initial_score"] = initial_score
        item["rerank_window"] = original_rank <= rerank_window

        if original_rank <= rerank_window:
            ats_report = build_ats_report(
                cv_text,
                candidate["job_text"],
                cv_path=str(cv_path),
                cover_letter_text=cover_letter_text,
            )
            rerank_score = compute_rerank_score(initial_score, ats_report)

            item["score"] = rerank_score
            item["rerank_score"] = rerank_score
            item["ats_score"] = ats_report["ats_score"]
            item["ats_assessment"] = ats_report["assessment"]
            item["required_keyword_coverage_percent"] = ats_report["required_keywords"][
                "coverage_percent"
            ]
            item["matched_required_keywords"] = ats_report["required_keywords"]["matched"]
            item["missing_required_keywords"] = ats_report["required_keywords"]["missing"]
            item["keyword_signal_detected"] = ats_report["keyword_coverage"]["has_signal"]
            item["rerank_reasons"] = build_rerank_reasons(initial_score, ats_report)
            reranked_window.append(item)
        else:
            item["rerank_score"] = initial_score
            item["rerank_reasons"] = [
                "Left in the original ranking order outside the rerank window."
            ]
            untouched_tail.append(item)

    reranked_window.sort(
        key=lambda item: (
            item["rerank_score"],
            item["required_keyword_coverage_percent"],
            item["initial_score"],
        ),
        reverse=True,
    )

    final_rankings = reranked_window + untouched_tail
    for rerank_rank, item in enumerate(final_rankings, start=1):
        item["rerank_rank"] = rerank_rank
        item["rank_change"] = item["original_rank"] - rerank_rank

    return final_rankings


def compute_rerank_score(initial_score: int, ats_report: dict[str, Any]) -> int:
    ats_score = ats_report["ats_score"]
    required_coverage = ats_report["required_keywords"]["coverage_percent"]
    return round(initial_score * 0.55 + ats_score * 0.30 + required_coverage * 0.15)


def build_rerank_reasons(initial_score: int, ats_report: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    ats_score = ats_report["ats_score"]
    required_coverage = ats_report["required_keywords"]["coverage_percent"]
    missing_required = ats_report["required_keywords"]["missing"]

    if not ats_report["keyword_coverage"]["has_signal"]:
        reasons.append(
            "Low ATS keyword signal means this rerank result is lower confidence and should be reviewed manually."
        )
    elif required_coverage >= 80:
        reasons.append(
            "Strong required-keyword coverage improved this role in the rerank pass."
        )
    elif missing_required:
        reasons.append(
            "Missing required keywords limited this role in reranking: "
            + ", ".join(missing_required[:4])
        )

    if ats_score >= initial_score + 8:
        reasons.append(
            "ATS alignment is stronger than the first-pass heuristic score suggested."
        )
    elif ats_score + 8 < initial_score:
        reasons.append(
            "ATS alignment is weaker than the first-pass heuristic score, so this role was tempered."
        )

    if not reasons:
        reasons.append(
            "First-pass fit and ATS alignment were broadly consistent, so this role stayed close to its original position."
        )
    return reasons
