# OfferQuest

OfferQuest is a web-first Python package for job search workflows. It helps you turn your CV and base cover letter into a reusable candidate profile, refresh job feeds, rank opportunities, run ATS-style checks, and generate tailored application drafts from one local workspace.

## Quick Start

Create a virtual environment and install the package:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e .[web]
```

Create a fresh workspace:

```bash
offerquest init-workspace --path ~/offerquest-workspace
cd ~/offerquest-workspace
```

Check the workspace and see the next setup steps:

```bash
offerquest doctor --path .
```

Start the local workbench:

```bash
offerquest-workbench --root .
```

Then open `http://localhost:8787` in your browser.

If you want OfferQuest to pick a free port automatically:

```bash
offerquest-workbench --root . --port auto
```

## Workspace Layout

An OfferQuest workspace keeps user-owned files separate from the installed package:

- `data/` for your CV, resume, and base cover letter
- `jobs/` for manual job descriptions and `jobs/sources.json`
- `outputs/` for generated profiles, rankings, ATS reports, tailored resumes, and run manifests

The `init-workspace` command creates this layout, adds starter docs, and writes a generic `jobs/sources.json` that can be used immediately for manual job imports.

## Common Commands

Check Ollama connectivity:

```bash
offerquest ollama-status
```

Build a candidate profile:

```bash
offerquest build-profile \
  --cv data/candidate-cv.docx \
  --cover-letter data/base-cover-letter.docx \
  --output outputs/profiles/candidate-profile.json
```

Refresh configured job sources:

```bash
offerquest refresh-jobs
```

Rank refreshed jobs against an existing profile:

```bash
offerquest rank-jobs \
  --profile outputs/profiles/candidate-profile.json \
  --jobs-file outputs/jobs/all.jsonl \
  --output outputs/job-ranking.json
```

Run ATS-style checks for one fetched job:

```bash
offerquest ats-check \
  --cv data/candidate-cv.docx \
  --jobs-file outputs/jobs/all.jsonl \
  --job-id example-job-id \
  --output outputs/ats-check.json
```

Generate a tailored cover letter draft:

```bash
offerquest generate-cover-letter \
  --cv data/candidate-cv.docx \
  --base-cover-letter data/base-cover-letter.docx \
  --jobs-file outputs/jobs/all.jsonl \
  --job-id example-job-id \
  --output outputs/workbench/example-cover-letter.txt
```

If you want Ollama-powered drafts, start a local Ollama server first and then use the `generate-cover-letter-llm` or `generate-cover-letters-llm` commands.

## Packaging and Release Workflow

OfferQuest currently targets versioned local release artifacts rather than PyPI publication or desktop bundling. Install the release tooling when you need to build packages:

```bash
pip install -e .[release]
```

Build a wheel and source distribution:

```bash
./scripts/build-release.sh
```

Run the release smoke test workflow:

```bash
./scripts/smoke-test-install.sh
```

## Development

Developer setup, testing, and release notes live in [DEVELOPMENT.md](DEVELOPMENT.md).
