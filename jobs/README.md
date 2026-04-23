Put manual job descriptions here as `.txt`, `.md`, `.doc`, `.docx`, or `.odt` files.

The default refresh flow is driven by [sources.json](sources.json):

```bash
offerquest refresh-jobs
```

That command can regenerate:

- `outputs/jobs/manual.jsonl` from the files in this folder
- `outputs/jobs/all.jsonl` as the merged dataset used by ranking
- `outputs/jobs/refresh-summary.json` as a machine-readable refresh report

You can add more sources by editing `jobs/sources.json` or by using the workbench `Job Sources` page. A Greenhouse board entry looks like:

```json
{
  "name": "greenhouse-example",
  "type": "greenhouse",
  "board_token": "example",
  "output": "greenhouse-example.jsonl"
}
```

If you want to debug the manual-import step by itself, run:

```bash
offerquest import-manual-jobs \
  --input-path jobs \
  --output outputs/jobs/manual.jsonl
```

Then merge and rank manually if needed:

```bash
offerquest merge-jobs \
  --input outputs/jobs/manual.jsonl \
  --output outputs/jobs/all.jsonl

offerquest rank-jobs \
  --profile outputs/profiles/candidate-profile.json \
  --jobs-file outputs/jobs/all.jsonl \
  --output outputs/job-ranking.json
```
