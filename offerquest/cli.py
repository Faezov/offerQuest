from __future__ import annotations

import argparse
import json
from pathlib import Path

from .ats import ats_check_job_file, ats_check_job_record
from .cover_letter import (
    generate_cover_letter_for_job_file,
    generate_cover_letter_for_job_record,
    write_cover_letter,
)
from .docx import export_document_as_docx
from .jobs import (
    collect_job_record_inputs,
    fetch_adzuna_jobs,
    fetch_greenhouse_jobs,
    find_job_record,
    import_manual_jobs,
    read_job_records,
    resolve_adzuna_credentials,
    write_job_records,
)
from .profile import build_profile_from_files
from .scoring import rank_job_files, rank_job_records, score_job_file

SUPPORTED_JOB_SUFFIXES = {".txt", ".md", ".doc", ".docx", ".odt"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="OfferQuest job-fit tooling")
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

    if args.command == "build-profile":
        profile = build_profile_from_files(args.cv, args.cover_letter)
        write_optional_json(args.output, profile)
        print(json.dumps(profile, indent=2))
        return 0

    if args.command == "export-docx":
        export_document_as_docx(args.input, args.output)
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

    if args.command == "fetch-greenhouse":
        jobs = fetch_greenhouse_jobs(args.board_token)
        write_job_records(args.output, jobs)
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

    profile = load_profile(args, parser)

    if args.command == "score-job":
        result = score_job_file(args.job, profile)
        write_optional_json(args.output, result)
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
        print(json.dumps(payload, indent=2))
        return 0

    parser.error(f"Unsupported command: {args.command}")
    return 2


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
