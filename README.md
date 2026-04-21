# OfferQuest

OfferQuest turns your CV and cover letter into a reusable job-fit profile so you can rank data roles by how well they match your background.

## What It Does

- Extracts text from your current CV and cover letter files in `data/`
- Builds a structured candidate profile with strengths, likely target roles, and search keywords
- Scores individual job descriptions against that profile
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

Score one job description:

```bash
python3 -m offerquest score-job \
  --profile outputs/bulat-profile.json \
  --job jobs/example-role.txt
```

Rank every job description in a folder:

```bash
python3 -m offerquest rank-jobs \
  --profile outputs/bulat-profile.json \
  --jobs-dir jobs \
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
- OpenDocument text files, including misnamed `.doc` files that are actually zipped ODT documents
- Legacy Microsoft Word `.doc` files through a local `strings` fallback

## Recommended Workflow

1. Put job descriptions into `jobs/` as `.txt` or `.md` files.
2. Build or refresh your profile after updating your CV or cover letter.
3. Run `rank-jobs` and focus your effort on the highest-scoring roles.
4. Use the reported strengths and gaps to tailor your next cover letter version.

## Notes

- The scoring is heuristic, not an ATS emulator.
- It is designed to surface fit quickly and consistently, not replace judgment.

