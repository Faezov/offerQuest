# OfferQuest

OfferQuest turns your CV and cover letter into a reusable job-fit profile so you can rank data roles by how well they match your background.

## Setup

Create a local virtual environment, install the package in editable mode, and add the optional dev tools:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt
```

Run the test suite:

```bash
python3 -m unittest discover -s tests -q
```

Install the local web workbench dependencies too:

```bash
pip install -e .[web]
```

That web extra includes the form-parsing dependency used by browser workflows such as `Build Profile`.

## What It Does

- Extracts text from your current CV and cover letter files in `data/`
- Builds a structured candidate profile with strengths, likely target roles, and search keywords
- Fetches and normalizes jobs from public/official-friendly sources
- Scores individual job descriptions against that profile
- Runs ATS-style keyword, section, and parseability checks for one target role
- Ranks a folder of job descriptions so you can focus on the strongest opportunities first

## Current Search Focus

Based on the CV and cover letter currently in this repo, the strongest target zone is:

- Senior data analyst roles
- Metadata / data governance analyst roles
- Reporting and insights analyst roles
- Data quality analyst roles
- Health, research, university, and public-sector data teams

## Usage

OfferQuest now also writes lightweight run manifests under `outputs/state/` so a future UI can reason about profiles, rankings, ATS reports, and generated letters as named runs instead of scraping loose files.

Start the local workbench:

```bash
offerquest-workbench --root . --reload
```

Then open `http://127.0.0.1:8787` in your browser.
The `Job Sources` page can save Adzuna credentials into `~/.config/offerquest/adzuna.env` so browser-driven and CLI fetches can reuse them automatically.

Build a profile from the current documents:

```bash
python3 -m offerquest build-profile \
  --cv data/CV_BF_20260415.doc \
  --cover-letter data/CL_BF_20260415.doc \
  --output outputs/bulat-profile.json
```

Export a cleaner ATS-friendly `.docx`:

```bash
python3 -m offerquest export-docx \
  --input data/CV_BF_20260415.doc \
  --output data/CV_BF_20260415.docx
```

Generate a job-specific cover letter draft:

```bash
python3 -m offerquest generate-cover-letter \
  --cv data/CV_BF_20260415.docx \
  --base-cover-letter data/CL_BF_20260415.doc \
  --jobs-file outputs/jobs/all.jsonl \
  --job-id adzuna:5686608390 \
  --output outputs/cover-letter-mane.txt
```

Check whether Ollama is reachable:

```bash
python3 -m offerquest ollama-status
```

Start a repo-local Ollama server and keep its cache inside this project:

```bash
./scripts/start-ollama-local.sh
```

If you want GPU acceleration from a repo-local install, download the full Linux package first:

```bash
./scripts/install-ollama-local.sh
```

Pull a small model first to verify the workflow quickly:

```bash
./scripts/ollama-local.sh pull qwen3:0.6b
```

Move up to a stronger model once the local setup is working:

```bash
./scripts/ollama-local.sh pull qwen3:8b
```

Pull the curated stronger model set for cover-letter A/B testing:

```bash
./scripts/pull-cover-letter-models.sh
```

Include stretch models that may run slower on a ~12 GB laptop GPU:

```bash
./scripts/pull-cover-letter-models.sh --all
```

Generate an employer-specific cover letter with Ollama:

```bash
python3 -m offerquest generate-cover-letter-llm \
  --cv data/CV_BF_20260415.docx \
  --base-cover-letter data/CL_BF_20260415.doc \
  --jobs-file outputs/jobs/all.jsonl \
  --job-id adzuna:5686608390 \
  --model qwen3:8b \
  --timeout-seconds 180 \
  --output outputs/cover-letter-mane-llm.txt
```

Generate cover letters for the top 5 ranked jobs:

```bash
python3 -m offerquest generate-cover-letters \
  --cv data/CV_BF_20260415.docx \
  --base-cover-letter data/CL_BF_20260415.doc \
  --jobs-file outputs/jobs/all.jsonl \
  --ranking-file outputs/job-ranking-docx.json \
  --output-dir outputs/cover-letters-top5 \
  --top 5 \
  --docx
```

Generate employer-specific cover letters for the top 5 ranked jobs with Ollama:

```bash
python3 -m offerquest generate-cover-letters-llm \
  --cv data/CV_BF_20260415.docx \
  --base-cover-letter data/CL_BF_20260415.doc \
  --jobs-file outputs/jobs/all.jsonl \
  --ranking-file outputs/job-ranking-docx.json \
  --output-dir outputs/cover-letters-top5-llm \
  --top 5 \
  --docx \
  --model qwen3:8b \
  --timeout-seconds 180
```

Run a single-job A/B test across the curated stronger model set:

```bash
./scripts/run-cover-letter-ab-test.sh \
  --cv data/CV_BF_20260415.docx \
  --base-cover-letter data/CL_BF_20260415.doc \
  --jobs-file outputs/jobs/adzuna-au.jsonl \
  --job-id adzuna:5686608390 \
  --output-dir outputs/ab-tests/mane
```

Run a top-job A/B test across the curated stronger model set:

```bash
./scripts/run-cover-letter-ab-test.sh \
  --cv data/CV_BF_20260415.docx \
  --base-cover-letter data/CL_BF_20260415.doc \
  --jobs-file outputs/jobs/all.jsonl \
  --ranking-file outputs/job-ranking-docx.json \
  --output-dir outputs/ab-tests/top-jobs \
  --top 3 \
  --docx
```

Score one job description:

```bash
python3 -m offerquest score-job \
  --profile outputs/bulat-profile.json \
  --job jobs/example-role.txt
```

Run ATS-style checks for one target job:

```bash
python3 -m offerquest ats-check \
  --cv data/CV_BF_20260415.doc \
  --job jobs/example-role.txt \
  --output outputs/ats-check.json
```

Run ATS-style checks for one fetched job record:

```bash
python3 -m offerquest ats-check \
  --cv data/CV_BF_20260415.doc \
  --jobs-file outputs/jobs/all.jsonl \
  --job-id adzuna:5686608390 \
  --output outputs/ats-check.json
```

Rank every job description in a folder:

```bash
python3 -m offerquest rank-jobs \
  --profile outputs/bulat-profile.json \
  --jobs-dir jobs \
  --output outputs/job-ranking.json
```

Refresh the configured Adzuna and manual job sources into `outputs/jobs/*.jsonl` and rebuild `all.jsonl`:

```bash
python3 -m offerquest refresh-jobs
```

By default this reads [jobs/sources.json](/home/bulat/app/offerQuest/jobs/sources.json), writes refreshed source files into `outputs/jobs/`, and emits `outputs/jobs/refresh-summary.json` so you can see exactly which source produced which file.

Fetch jobs from Adzuna into normalized records:

```bash
python3 -m offerquest fetch-adzuna \
  --what "senior data analyst" \
  --where "Sydney" \
  --country au \
  --output outputs/jobs/adzuna-au.jsonl
```

Fetch public jobs from a Greenhouse board:

```bash
python3 -m offerquest fetch-greenhouse \
  --board-token example \
  --output outputs/jobs/greenhouse-example.jsonl
```

Turn local job descriptions into normalized records:

```bash
python3 -m offerquest import-manual-jobs \
  --input-path jobs \
  --output outputs/jobs/manual.jsonl
```

Merge multiple job-record files:

```bash
python3 -m offerquest merge-jobs \
  --input outputs/jobs/adzuna-au.jsonl \
  --input outputs/jobs/greenhouse-example.jsonl \
  --input outputs/jobs/manual.jsonl \
  --output outputs/jobs/all.jsonl
```

Rank normalized job records directly:

```bash
python3 -m offerquest rank-jobs \
  --profile outputs/bulat-profile.json \
  --jobs-file outputs/jobs/all.jsonl \
  --output outputs/job-ranking.json
```

Run a second-pass rerank over the top jobs using ATS-style signals from the current CV:

```bash
python3 -m offerquest rerank-jobs \
  --cv data/CV_BF_20260415.docx \
  --jobs-file outputs/jobs/all.jsonl \
  --top 20 \
  --output outputs/job-ranking-reranked.json
```

You can also skip the saved profile and score directly from the CV and cover letter:

```bash
python3 -m offerquest rank-jobs \
  --cv data/CV_BF_20260415.doc \
  --cover-letter data/CL_BF_20260415.doc \
  --jobs-dir jobs
```

## Supported Inputs

- Plain text: `.txt`, `.md`
- Microsoft Word `.docx`
- OpenDocument text files, including misnamed `.doc` files that are actually zipped ODT documents
- Legacy Microsoft Word `.doc` files through a local `strings` fallback
- Normalized job-record files: `.json`, `.jsonl`

## Recommended Workflow

1. Put job descriptions into `jobs/` as `.txt` or `.md` files.
2. Update [jobs/sources.json](/home/bulat/app/offerQuest/jobs/sources.json) with the Adzuna searches and any other sources you want to monitor.
3. Run `refresh-jobs` to regenerate the source `.jsonl` files and rebuild `outputs/jobs/all.jsonl`.
4. Add one-off `fetch-greenhouse` or `import-manual-jobs` runs only when you are debugging or testing a source in isolation.
5. Build or refresh your profile after updating your CV or cover letter.
6. Run `rank-jobs` and focus your effort on the highest-scoring roles.
7. Run `rerank-jobs` on the top set when you want a second-pass ordering that leans more on ATS-style fit.
8. Run `ats-check` on the top jobs to see missing keywords, section issues, and tailoring suggestions.
9. Use the reported strengths and gaps to tailor your next cover letter version.

## Notes

- The scoring is heuristic, not an ATS emulator.
- `rerank-jobs` is also heuristic; it adds a second-pass ATS-style signal, but it still does not replace judgment.
- It is designed to surface fit quickly and consistently, not replace judgment.
- `ats-check` is an ATS-style heuristic review, not a vendor-specific simulation of Workday, Greenhouse, Lever, or Taleo.
- `refresh-jobs` uses [jobs/sources.json](/home/bulat/app/offerQuest/jobs/sources.json) by default, so adding or removing search streams is a config change rather than a shell-history exercise.
- `fetch-adzuna` and `refresh-jobs` first use explicit flags, then process environment variables, then `~/.config/offerquest/adzuna.env` if present.
- The Ollama-backed cover letter commands require a local Ollama server and a pulled model such as `qwen3:0.6b` for a quick smoke test or `qwen3:8b` for better quality.
- The curated stronger model set currently favors `qwen3:8b`, `gemma3:12b`, and `qwen3:14b`, with `mistral-small` treated as a stretch option because it is more likely to spill beyond a ~12 GB GPU.
- `./scripts/ollama-local.sh` keeps the Ollama home directory and model cache under `.ollama-home/` in this repo, which avoids mixing job-search models into your normal shell environment.
- Qwen3 thinking is enabled by default in Ollama, so OfferQuest disables it for cover-letter generation and uses a longer request timeout to give local CPU inference enough time to return final JSON.
- The lightweight fallback binary under `.tools/ollama-partial/` is enough for CPU inference, but GPU acceleration needs the full local install from `./scripts/install-ollama-local.sh` or a normal system-wide Ollama install.
