Put raw job descriptions here as `.txt`, `.md`, `.doc`, or `.odt` files.

The default refresh workflow is driven by [sources.json](/home/bulat/app/offerQuest/jobs/sources.json):

```bash
python3 -m offerquest refresh-jobs
```

That command can regenerate:

- `outputs/jobs/adzuna-*.jsonl` from configured Adzuna searches
- `outputs/jobs/manual.jsonl` from the files in this folder
- `outputs/jobs/all.jsonl` as the merged dataset used by ranking
- `outputs/jobs/refresh-summary.json` as a machine-readable refresh report

Add more sources by editing `jobs/sources.json`. For example, a Greenhouse board entry looks like:

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
python3 -m offerquest import-manual-jobs \
  --input-path jobs \
  --output outputs/jobs/manual.jsonl
```

Then merge and rank manually if needed:

```bash
python3 -m offerquest merge-jobs \
  --input outputs/jobs/manual.jsonl \
  --output outputs/jobs/all.jsonl

python3 -m offerquest rank-jobs \
  --profile outputs/bulat-profile.json \
  --jobs-file outputs/jobs/all.jsonl
```
