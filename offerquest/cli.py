from __future__ import annotations

import argparse
import json
from pathlib import Path

from .profile import build_profile_from_files
from .scoring import rank_job_files, score_job_file

SUPPORTED_JOB_SUFFIXES = {".txt", ".md", ".doc", ".odt"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="OfferQuest job-fit tooling")
    subparsers = parser.add_subparsers(dest="command", required=True)

    build_profile_parser = subparsers.add_parser(
        "build-profile",
        help="Build a structured candidate profile from a CV and cover letter",
    )
    add_profile_source_arguments(build_profile_parser)
    build_profile_parser.add_argument("--output", type=Path, help="Write profile JSON to this path")

    score_job_parser = subparsers.add_parser(
        "score-job",
        help="Score one job description against the candidate profile",
    )
    add_profile_reuse_arguments(score_job_parser)
    score_job_parser.add_argument("--job", type=Path, required=True, help="Job description file")
    score_job_parser.add_argument("--output", type=Path, help="Write score JSON to this path")

    rank_jobs_parser = subparsers.add_parser(
        "rank-jobs",
        help="Rank every supported job description file inside a folder",
    )
    add_profile_reuse_arguments(rank_jobs_parser)
    rank_jobs_parser.add_argument("--jobs-dir", type=Path, required=True, help="Folder of job files")
    rank_jobs_parser.add_argument("--output", type=Path, help="Write ranking JSON to this path")

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

    profile = load_profile(args, parser)

    if args.command == "score-job":
        result = score_job_file(args.job, profile)
        write_optional_json(args.output, result)
        print(json.dumps(result, indent=2))
        return 0

    if args.command == "rank-jobs":
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


def write_optional_json(path: Path | None, payload: dict) -> None:
    if path is None:
        return

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
