# OfferQuest

OfferQuest turns your CV and cover letter into a reusable job-fit profile so you can rank data roles by how well they match your background.

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
2. Fetch jobs from Adzuna and any public Greenhouse boards you want to monitor.
3. Import any manually collected job descriptions.
4. Merge the job-record files into one dataset.
5. Build or refresh your profile after updating your CV or cover letter.
6. Run `rank-jobs` and focus your effort on the highest-scoring roles.
7. Run `ats-check` on the top jobs to see missing keywords, section issues, and tailoring suggestions.
8. Use the reported strengths and gaps to tailor your next cover letter version.

## Notes

- The scoring is heuristic, not an ATS emulator.
- It is designed to surface fit quickly and consistently, not replace judgment.
- `ats-check` is an ATS-style heuristic review, not a vendor-specific simulation of Workday, Greenhouse, Lever, or Taleo.
- `fetch-adzuna` uses `ADZUNA_APP_ID` and `ADZUNA_APP_KEY` automatically if you do not pass them as flags.
