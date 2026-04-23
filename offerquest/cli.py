from __future__ import annotations

import argparse
import json
from pathlib import Path

from .ats import ats_check_job_file, ats_check_job_record
from .cover_letter import (
    generate_cover_letter_for_job_file,
    generate_cover_letter_for_job_record,
    generate_cover_letter_for_job_record_llm,
    generate_cover_letters_from_ranking,
    generate_cover_letters_from_ranking_llm,
    write_cover_letter,
)
from .docx import export_document_as_docx
from .errors import OfferQuestError
from .extractors import read_document_text
from .jobs import (
    collect_job_record_inputs,
    fetch_adzuna_jobs,
    fetch_greenhouse_jobs,
    find_job_record,
    import_manual_jobs,
    read_job_records,
    refresh_job_sources,
    resolve_adzuna_credentials,
    write_job_records,
)
from . import __version__
from .ollama import DEFAULT_OLLAMA_BASE_URL, get_ollama_status
from .profile import build_candidate_profile, build_profile_from_files
from .reranking import rerank_job_files, rerank_job_records
from .scoring import rank_job_files, rank_job_records, score_job_file
from .workspace import ProjectState

SUPPORTED_JOB_SUFFIXES = {".txt", ".md", ".doc", ".docx", ".odt"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="OfferQuest job-fit tooling")
    parser.add_argument(
        "--version",
        action="version",
        version=f"OfferQuest {__version__}",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    build_profile_parser = subparsers.add_parser(
        "build-profile",
        help="Build a structured candidate profile from a CV and cover letter",
    )
    add_profile_source_arguments(build_profile_parser)
    build_profile_parser.add_argument("--output", type=Path, help="Write profile JSON to this path")

    export_docx_parser = subparsers.add_parser(
        "export-docx",
        help="Export a supported document as a simple ATS-friendly .docx file",
    )
    export_docx_parser.add_argument("--input", type=Path, required=True, help="Input document file")
    export_docx_parser.add_argument("--output", type=Path, required=True, help="Output .docx path")

    score_job_parser = subparsers.add_parser(
        "score-job",
        help="Score one job description against the candidate profile",
    )
    add_profile_reuse_arguments(score_job_parser)
    score_job_parser.add_argument("--job", type=Path, required=True, help="Job description file")
    score_job_parser.add_argument("--output", type=Path, help="Write score JSON to this path")

    cover_letter_parser = subparsers.add_parser(
        "generate-cover-letter",
        help="Generate a job-specific cover letter draft",
    )
    cover_letter_parser.add_argument("--cv", type=Path, required=True, help="CV file")
    cover_letter_parser.add_argument("--base-cover-letter", type=Path, help="Optional source cover letter for tone and context")
    cover_letter_job_group = cover_letter_parser.add_mutually_exclusive_group(required=True)
    cover_letter_job_group.add_argument("--job", type=Path, help="Raw job description file")
    cover_letter_job_group.add_argument("--jobs-file", type=Path, help="JSON or JSONL file of normalized job records")
    cover_letter_parser.add_argument("--job-id", help="Job id inside --jobs-file")
    cover_letter_parser.add_argument("--output", type=Path, required=True, help="Write generated cover letter to this path")

    cover_letter_llm_parser = subparsers.add_parser(
        "generate-cover-letter-llm",
        help="Generate an employer-specific cover letter draft with a local Ollama model",
    )
    cover_letter_llm_parser.add_argument("--cv", type=Path, required=True, help="CV file")
    cover_letter_llm_parser.add_argument("--base-cover-letter", type=Path, help="Optional source cover letter for tone and context")
    cover_letter_llm_parser.add_argument("--employer-context", type=Path, help="Optional employer-specific notes file")
    cover_letter_llm_parser.add_argument("--model", default="qwen3:8b", help="Ollama model name, default: qwen3:8b")
    cover_letter_llm_parser.add_argument("--base-url", default=DEFAULT_OLLAMA_BASE_URL, help="Ollama base URL, default: http://localhost:11434")
    cover_letter_llm_parser.add_argument("--timeout-seconds", type=int, default=180, help="Ollama request timeout in seconds, default: 180")
    cover_letter_llm_job_group = cover_letter_llm_parser.add_mutually_exclusive_group(required=True)
    cover_letter_llm_job_group.add_argument("--job", type=Path, help="Raw job description file")
    cover_letter_llm_job_group.add_argument("--jobs-file", type=Path, help="JSON or JSONL file of normalized job records")
    cover_letter_llm_parser.add_argument("--job-id", help="Job id inside --jobs-file")
    cover_letter_llm_parser.add_argument("--output", type=Path, required=True, help="Write generated cover letter to this path")

    cover_letters_parser = subparsers.add_parser(
        "generate-cover-letters",
        help="Generate cover letter drafts for the top ranked jobs",
    )
    cover_letters_parser.add_argument("--cv", type=Path, required=True, help="CV file")
    cover_letters_parser.add_argument("--base-cover-letter", type=Path, help="Optional source cover letter for tone and context")
    cover_letters_parser.add_argument("--jobs-file", type=Path, required=True, help="JSON or JSONL file of normalized job records")
    cover_letters_parser.add_argument("--ranking-file", type=Path, required=True, help="Ranking JSON file produced by rank-jobs")
    cover_letters_parser.add_argument("--output-dir", type=Path, required=True, help="Directory for generated cover letters")
    cover_letters_parser.add_argument("--top", type=int, default=5, help="How many top unique jobs to generate, default: 5")
    cover_letters_parser.add_argument("--docx", action="store_true", help="Also export each generated letter as .docx")

    cover_letters_llm_parser = subparsers.add_parser(
        "generate-cover-letters-llm",
        help="Generate employer-specific cover letters for the top ranked jobs with a local Ollama model",
    )
    cover_letters_llm_parser.add_argument("--cv", type=Path, required=True, help="CV file")
    cover_letters_llm_parser.add_argument("--base-cover-letter", type=Path, help="Optional source cover letter for tone and context")
    cover_letters_llm_parser.add_argument("--employer-context-dir", type=Path, help="Optional directory of employer-specific notes named after slugified companies")
    cover_letters_llm_parser.add_argument("--jobs-file", type=Path, required=True, help="JSON or JSONL file of normalized job records")
    cover_letters_llm_parser.add_argument("--ranking-file", type=Path, required=True, help="Ranking JSON file produced by rank-jobs")
    cover_letters_llm_parser.add_argument("--output-dir", type=Path, required=True, help="Directory for generated cover letters")
    cover_letters_llm_parser.add_argument("--top", type=int, default=5, help="How many top unique jobs to generate, default: 5")
    cover_letters_llm_parser.add_argument("--docx", action="store_true", help="Also export each generated letter as .docx")
    cover_letters_llm_parser.add_argument("--model", default="qwen3:8b", help="Ollama model name, default: qwen3:8b")
    cover_letters_llm_parser.add_argument("--base-url", default=DEFAULT_OLLAMA_BASE_URL, help="Ollama base URL, default: http://localhost:11434")
    cover_letters_llm_parser.add_argument("--timeout-seconds", type=int, default=180, help="Ollama request timeout in seconds, default: 180")

    ollama_status_parser = subparsers.add_parser(
        "ollama-status",
        help="Check whether a local Ollama server is reachable and list available models",
    )
    ollama_status_parser.add_argument("--base-url", default=DEFAULT_OLLAMA_BASE_URL, help="Ollama base URL, default: http://localhost:11434")

    ats_parser = subparsers.add_parser(
        "ats-check",
        help="Run ATS-style resume checks against one target job",
    )
    ats_parser.add_argument("--cv", type=Path, required=True, help="CV file")
    ats_parser.add_argument("--cover-letter", type=Path, help="Optional cover letter to improve role suggestions")
    ats_job_group = ats_parser.add_mutually_exclusive_group(required=True)
    ats_job_group.add_argument("--job", type=Path, help="Raw job description file")
    ats_job_group.add_argument("--jobs-file", type=Path, help="JSON or JSONL file of normalized job records")
    ats_parser.add_argument("--job-id", help="Job id inside --jobs-file")
    ats_parser.add_argument("--output", type=Path, help="Write ATS report JSON to this path")

    rank_jobs_parser = subparsers.add_parser(
        "rank-jobs",
        help="Rank every supported job description file inside a folder",
    )
    add_profile_reuse_arguments(rank_jobs_parser)
    rank_jobs_group = rank_jobs_parser.add_mutually_exclusive_group(required=True)
    rank_jobs_group.add_argument("--jobs-dir", type=Path, help="Folder of raw job description files")
    rank_jobs_group.add_argument("--jobs-file", type=Path, help="JSON or JSONL file of normalized job records")
    rank_jobs_parser.add_argument("--output", type=Path, help="Write ranking JSON to this path")

    rerank_jobs_parser = subparsers.add_parser(
        "rerank-jobs",
        help="Run a second-pass rerank over the top jobs using ATS-style signals",
    )
    rerank_jobs_parser.add_argument("--cv", type=Path, required=True, help="CV file")
    rerank_jobs_parser.add_argument("--cover-letter", type=Path, help="Optional cover letter to refine ATS and target-role context")
    rerank_jobs_parser.add_argument(
        "--profile",
        type=Path,
        help="Optional existing profile JSON; if omitted, OfferQuest builds a fresh profile from the CV and cover letter",
    )
    rerank_jobs_group = rerank_jobs_parser.add_mutually_exclusive_group(required=True)
    rerank_jobs_group.add_argument("--jobs-dir", type=Path, help="Folder of raw job description files")
    rerank_jobs_group.add_argument("--jobs-file", type=Path, help="JSON or JSONL file of normalized job records")
    rerank_jobs_parser.add_argument("--top", type=int, default=20, help="How many top jobs to rerank in the second pass, default: 20")
    rerank_jobs_parser.add_argument("--output", type=Path, help="Write reranked JSON to this path")

    adzuna_parser = subparsers.add_parser(
        "fetch-adzuna",
        help="Fetch job listings from the Adzuna API into normalized job records",
    )
    adzuna_parser.add_argument("--app-id", help="Adzuna app id; falls back to ADZUNA_APP_ID")
    adzuna_parser.add_argument("--app-key", help="Adzuna app key; falls back to ADZUNA_APP_KEY")
    adzuna_parser.add_argument("--what", help="Search keywords, e.g. senior data analyst")
    adzuna_parser.add_argument("--where", help="Search location, e.g. Sydney")
    adzuna_parser.add_argument("--country", default="au", help="Adzuna country code, default: au")
    adzuna_parser.add_argument("--page", type=int, default=1, help="Results page number")
    adzuna_parser.add_argument("--results-per-page", type=int, default=20, help="Results per page")
    adzuna_parser.add_argument("--output", type=Path, required=True, help="Write normalized jobs to this file")

    refresh_jobs_parser = subparsers.add_parser(
        "refresh-jobs",
        help="Refresh multiple job-source outputs from a config file and rebuild merged job datasets",
    )
    refresh_jobs_parser.add_argument(
        "--config",
        type=Path,
        default=Path("jobs/sources.json"),
        help="JSON config that declares Adzuna, Greenhouse, and manual job sources",
    )
    refresh_jobs_parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("outputs/jobs"),
        help="Directory where refreshed job .jsonl files and summary JSON should be written",
    )
    refresh_jobs_parser.add_argument("--app-id", help="Adzuna app id; falls back to ADZUNA_APP_ID")
    refresh_jobs_parser.add_argument("--app-key", help="Adzuna app key; falls back to ADZUNA_APP_KEY")

    greenhouse_parser = subparsers.add_parser(
        "fetch-greenhouse",
        help="Fetch public jobs from a Greenhouse board into normalized job records",
    )
    greenhouse_parser.add_argument("--board-token", required=True, help="Greenhouse board token")
    greenhouse_parser.add_argument("--output", type=Path, required=True, help="Write normalized jobs to this file")

    import_manual_parser = subparsers.add_parser(
        "import-manual-jobs",
        help="Turn local job description files into normalized job records",
    )
    import_manual_parser.add_argument("--input-path", type=Path, required=True, help="File or directory of job descriptions")
    import_manual_parser.add_argument("--output", type=Path, required=True, help="Write normalized jobs to this file")

    merge_jobs_parser = subparsers.add_parser(
        "merge-jobs",
        help="Merge JSON or JSONL job-record files into one deduplicated job dataset",
    )
    merge_jobs_parser.add_argument(
        "--input",
        action="append",
        dest="inputs",
        required=True,
        type=Path,
        help="Job-record file or directory; repeat for multiple inputs",
    )
    merge_jobs_parser.add_argument("--output", type=Path, required=True, help="Write merged jobs to this file")

    return parser


def add_profile_source_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--cv", type=Path, required=True, help="CV file")
    parser.add_argument("--cover-letter", type=Path, required=True, help="Cover letter file")


def add_profile_reuse_arguments(parser: argparse.ArgumentParser) -> None:
    source_group = parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument("--profile", type=Path, help="Existing profile JSON")
    source_group.add_argument("--cv", type=Path, help="CV file")
    parser.add_argument("--cover-letter", type=Path, help="Cover letter file, required with --cv")


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    project_state = ProjectState.from_root(Path.cwd())

    try:
        if args.command == "build-profile":
            profile = build_profile_from_files(args.cv, args.cover_letter)
            write_optional_json(args.output, profile)
            maybe_record_run(
                project_state,
                "build-profile",
                output_path=args.output,
                artifact_kind="profile",
                metadata={"source_files": profile.get("source_files", {})},
                label=args.output.stem if args.output else None,
            )
            print(json.dumps(profile, indent=2))
            return 0

        if args.command == "export-docx":
            export_document_as_docx(args.input, args.output)
            record_run(
                project_state,
                "export-docx",
                artifacts=[{"kind": "document", "path": args.output}],
                metadata={"source": str(args.input)},
                label=args.output.stem,
            )
            print(
                json.dumps(
                    {
                        "source": str(args.input),
                        "output": str(args.output),
                    },
                    indent=2,
                )
            )
            return 0

        if args.command == "generate-cover-letter":
            if args.job:
                payload = generate_cover_letter_for_job_file(
                    args.cv,
                    args.job,
                    base_cover_letter_path=args.base_cover_letter,
                )
            else:
                if not args.job_id:
                    parser.error("--job-id is required when using --jobs-file")
                jobs = read_job_records(args.jobs_file)
                job_record = find_job_record(jobs, args.job_id)
                if job_record is None:
                    parser.error(f"Job id not found in {args.jobs_file}: {args.job_id}")
                payload = generate_cover_letter_for_job_record(
                    args.cv,
                    job_record,
                    base_cover_letter_path=args.base_cover_letter,
                )

            write_cover_letter(args.output, payload)
            record_run(
                project_state,
                "generate-cover-letter",
                artifacts=[{"kind": "cover_letter", "path": args.output}],
                metadata={
                    "job_title": payload.get("job_title"),
                    "company": payload.get("company"),
                    "job_id": payload.get("job_id"),
                },
                label=args.output.stem,
            )
            print(
                json.dumps(
                    {
                        "job_title": payload.get("job_title"),
                        "company": payload.get("company"),
                        "output": str(args.output),
                    },
                    indent=2,
                )
            )
            return 0

        if args.command == "generate-cover-letter-llm":
            if args.job:
                parser.error("--job is not yet supported for generate-cover-letter-llm; use --jobs-file and --job-id")
            if not args.job_id:
                parser.error("--job-id is required when using --jobs-file")
            jobs = read_job_records(args.jobs_file)
            job_record = find_job_record(jobs, args.job_id)
            if job_record is None:
                parser.error(f"Job id not found in {args.jobs_file}: {args.job_id}")
            payload = generate_cover_letter_for_job_record_llm(
                args.cv,
                job_record,
                base_cover_letter_path=args.base_cover_letter,
                employer_context_path=args.employer_context,
                model=args.model,
                base_url=args.base_url,
                timeout_seconds=args.timeout_seconds,
            )
            write_cover_letter(args.output, payload)
            record_run(
                project_state,
                "generate-cover-letter-llm",
                artifacts=[{"kind": "llm_cover_letter", "path": args.output}],
                metadata={
                    "job_title": payload.get("job_title"),
                    "company": payload.get("company"),
                    "job_id": payload.get("job_id"),
                    "llm_model": payload.get("llm_model"),
                },
                label=args.output.stem,
            )
            print(
                json.dumps(
                    {
                        "job_title": payload.get("job_title"),
                        "company": payload.get("company"),
                        "model": payload.get("llm_model"),
                        "output": str(args.output),
                    },
                    indent=2,
                )
            )
            return 0

        if args.command == "generate-cover-letters":
            summary = generate_cover_letters_from_ranking(
                args.cv,
                args.jobs_file,
                args.ranking_file,
                args.output_dir,
                base_cover_letter_path=args.base_cover_letter,
                top_n=args.top,
                export_docx=args.docx,
            )
            record_run(
                project_state,
                "generate-cover-letters",
                artifacts=[{"kind": "cover_letter_batch", "path": Path(args.output_dir) / "summary.json"}],
                metadata={"output_dir": str(args.output_dir), "job_count": summary.get("job_count")},
                label=Path(args.output_dir).name,
            )
            print(json.dumps(summary, indent=2))
            return 0

        if args.command == "generate-cover-letters-llm":
            summary = generate_cover_letters_from_ranking_llm(
                args.cv,
                args.jobs_file,
                args.ranking_file,
                args.output_dir,
                base_cover_letter_path=args.base_cover_letter,
                employer_context_dir=args.employer_context_dir,
                top_n=args.top,
                export_docx=args.docx,
                model=args.model,
                base_url=args.base_url,
                timeout_seconds=args.timeout_seconds,
            )
            record_run(
                project_state,
                "generate-cover-letters-llm",
                artifacts=[{"kind": "llm_cover_letter_batch", "path": Path(args.output_dir) / "summary.json"}],
                metadata={
                    "output_dir": str(args.output_dir),
                    "job_count": summary.get("job_count"),
                    "llm_model": summary.get("llm_model"),
                },
                label=Path(args.output_dir).name,
            )
            print(json.dumps(summary, indent=2))
            return 0

        if args.command == "ollama-status":
            print(json.dumps(get_ollama_status(args.base_url), indent=2))
            return 0

        if args.command == "ats-check":
            if args.job:
                report = ats_check_job_file(
                    args.cv,
                    args.job,
                    cover_letter_path=args.cover_letter,
                )
            else:
                if not args.job_id:
                    parser.error("--job-id is required when using --jobs-file")
                jobs = read_job_records(args.jobs_file)
                job_record = find_job_record(jobs, args.job_id)
                if job_record is None:
                    parser.error(f"Job id not found in {args.jobs_file}: {args.job_id}")
                report = ats_check_job_record(
                    args.cv,
                    job_record,
                    cover_letter_path=args.cover_letter,
                )

            write_optional_json(args.output, report)
            maybe_record_run(
                project_state,
                "ats-check",
                output_path=args.output,
                artifact_kind="ats_report",
                metadata={"job_title": report.get("job_title"), "assessment": report.get("assessment")},
                label=args.output.stem if args.output else None,
            )
            print(json.dumps(report, indent=2))
            return 0

        if args.command == "fetch-adzuna":
            app_id, app_key = resolve_adzuna_credentials(args.app_id, args.app_key)
            if not app_id or not app_key:
                parser.error("Adzuna credentials are required via --app-id/--app-key or ADZUNA_APP_ID/ADZUNA_APP_KEY")

            jobs = fetch_adzuna_jobs(
                app_id=app_id,
                app_key=app_key,
                what=args.what,
                where=args.where,
                country=args.country,
                page=args.page,
                results_per_page=args.results_per_page,
            )
            write_job_records(args.output, jobs)
            record_run(
                project_state,
                "fetch-adzuna",
                artifacts=[{"kind": "jobs_file", "path": args.output}],
                metadata={"source": "adzuna", "job_count": len(jobs)},
                label=args.output.stem,
            )
            print(
                json.dumps(
                    {
                        "source": "adzuna",
                        "job_count": len(jobs),
                        "output": str(args.output),
                    },
                    indent=2,
                )
            )
            return 0

        if args.command == "refresh-jobs":
            summary = refresh_job_sources(
                args.config,
                workspace_root=Path.cwd(),
                output_dir=args.output_dir,
                adzuna_app_id=args.app_id,
                adzuna_app_key=args.app_key,
            )

            artifacts = [{"kind": "jobs_refresh_summary", "path": Path(summary["summary_output"])}]
            artifacts.extend(
                {"kind": "jobs_file", "path": Path(source["output"])}
                for source in summary.get("sources", [])
                if source.get("output")
            )
            if summary.get("merged_output"):
                artifacts.append({"kind": "jobs_file", "path": Path(summary["merged_output"])})

            record_run(
                project_state,
                "refresh-jobs",
                artifacts=artifacts,
                metadata={
                    "source_count": summary.get("source_count"),
                    "merged_job_count": summary.get("merged_job_count"),
                    "config_path": summary.get("config_path"),
                },
                label=Path(args.output_dir).name,
            )
            print(json.dumps(summary, indent=2))
            return 0

        if args.command == "fetch-greenhouse":
            jobs = fetch_greenhouse_jobs(args.board_token)
            write_job_records(args.output, jobs)
            record_run(
                project_state,
                "fetch-greenhouse",
                artifacts=[{"kind": "jobs_file", "path": args.output}],
                metadata={"source": "greenhouse", "job_count": len(jobs), "board_token": args.board_token},
                label=args.output.stem,
            )
            print(
                json.dumps(
                    {
                        "source": "greenhouse",
                        "board_token": args.board_token,
                        "job_count": len(jobs),
                        "output": str(args.output),
                    },
                    indent=2,
                )
            )
            return 0

        if args.command == "import-manual-jobs":
            jobs = import_manual_jobs(args.input_path)
            write_job_records(args.output, jobs)
            record_run(
                project_state,
                "import-manual-jobs",
                artifacts=[{"kind": "jobs_file", "path": args.output}],
                metadata={"source": "manual", "job_count": len(jobs), "input_path": str(args.input_path)},
                label=args.output.stem,
            )
            print(
                json.dumps(
                    {
                        "source": "manual",
                        "job_count": len(jobs),
                        "output": str(args.output),
                    },
                    indent=2,
                )
            )
            return 0

        if args.command == "merge-jobs":
            jobs = collect_job_record_inputs(args.inputs)
            write_job_records(args.output, jobs)
            record_run(
                project_state,
                "merge-jobs",
                artifacts=[{"kind": "jobs_file", "path": args.output}],
                metadata={"source": "merged", "job_count": len(jobs)},
                label=args.output.stem,
            )
            print(
                json.dumps(
                    {
                        "source": "merged",
                        "job_count": len(jobs),
                        "output": str(args.output),
                    },
                    indent=2,
                )
            )
            return 0

        if args.command == "rerank-jobs":
            if args.top < 1:
                parser.error("--top must be at least 1")

            cv_text = read_document_text(args.cv)
            cover_letter_text = read_document_text(args.cover_letter) if args.cover_letter else ""
            rerank_profile = (
                json.loads(args.profile.read_text(encoding="utf-8"))
                if args.profile
                else build_candidate_profile(
                    cv_text,
                    cover_letter_text,
                    cv_path=str(args.cv),
                    cover_letter_path=str(args.cover_letter) if args.cover_letter else None,
                )
            )

            if args.jobs_file:
                jobs = read_job_records(args.jobs_file)
                results = rerank_job_records(
                    jobs,
                    rerank_profile,
                    cv_text=cv_text,
                    cv_path=args.cv,
                    cover_letter_text=cover_letter_text,
                    top_n=args.top,
                )
            else:
                job_paths = collect_job_paths(args.jobs_dir)
                results = rerank_job_files(
                    job_paths,
                    rerank_profile,
                    cv_text=cv_text,
                    cv_path=args.cv,
                    cover_letter_text=cover_letter_text,
                    top_n=args.top,
                )

            payload = {
                "job_count": len(results),
                "reranked_count": min(args.top, len(results)),
                "rerank_strategy": "ats-hybrid-v1",
                "rankings": results,
            }
            write_optional_json(args.output, payload)
            maybe_record_run(
                project_state,
                "rerank-jobs",
                output_path=args.output,
                artifact_kind="ranking",
                metadata={
                    "job_count": payload["job_count"],
                    "reranked_count": payload["reranked_count"],
                    "rerank_strategy": payload["rerank_strategy"],
                },
                label=args.output.stem if args.output else None,
            )
            print(json.dumps(payload, indent=2))
            return 0

        profile = load_profile(args, parser)

        if args.command == "score-job":
            result = score_job_file(args.job, profile)
            write_optional_json(args.output, result)
            maybe_record_run(
                project_state,
                "score-job",
                output_path=args.output,
                artifact_kind="job_score",
                metadata={"job_title": result.get("job_title"), "score": result.get("score")},
                label=args.output.stem if args.output else None,
            )
            print(json.dumps(result, indent=2))
            return 0

        if args.command == "rank-jobs":
            if args.jobs_file:
                jobs = read_job_records(args.jobs_file)
                results = rank_job_records(jobs, profile)
            else:
                job_paths = collect_job_paths(args.jobs_dir)
                results = rank_job_files(job_paths, profile)
            payload = {
                "job_count": len(results),
                "rankings": results,
            }
            write_optional_json(args.output, payload)
            maybe_record_run(
                project_state,
                "rank-jobs",
                output_path=args.output,
                artifact_kind="ranking",
                metadata={"job_count": payload["job_count"]},
                label=args.output.stem if args.output else None,
            )
            print(json.dumps(payload, indent=2))
            return 0

        parser.error(f"Unsupported command: {args.command}")
        return 2
    except OfferQuestError as exc:
        parser.exit(2, f"error: {exc}\n")


def load_profile(args: argparse.Namespace, parser: argparse.ArgumentParser) -> dict:
    if args.profile:
        return json.loads(args.profile.read_text(encoding="utf-8"))

    if not args.cv or not args.cover_letter:
        parser.error("--cover-letter is required when building a profile from --cv")

    return build_profile_from_files(args.cv, args.cover_letter)


def collect_job_paths(jobs_dir: Path) -> list[Path]:
    return sorted(
        path
        for path in jobs_dir.rglob("*")
        if path.is_file()
        and path.suffix.lower() in SUPPORTED_JOB_SUFFIXES
        and not path.name.lower().startswith("readme")
    )


def write_optional_json(path: Path | None, payload: object) -> None:
    if path is None:
        return

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def maybe_record_run(
    project_state: ProjectState,
    workflow: str,
    *,
    output_path: Path | None,
    artifact_kind: str,
    metadata: dict[str, object] | None = None,
    label: str | None = None,
) -> None:
    if output_path is None:
        return
    record_run(
        project_state,
        workflow,
        artifacts=[{"kind": artifact_kind, "path": output_path}],
        metadata=metadata,
        label=label,
    )


def record_run(
    project_state: ProjectState,
    workflow: str,
    *,
    artifacts: list[dict[str, object]],
    metadata: dict[str, object] | None = None,
    label: str | None = None,
) -> None:
    project_state.record_run(
        workflow,
        artifacts=artifacts,
        metadata=metadata,
        label=label,
    )
