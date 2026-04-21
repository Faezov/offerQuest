Put raw job descriptions here as `.txt`, `.md`, `.doc`, or `.odt` files, then run:

```bash
python3 -m offerquest import-manual-jobs \
  --input-path jobs \
  --output outputs/jobs/manual.jsonl
```

Then merge and rank:

```bash
python3 -m offerquest merge-jobs \
  --input outputs/jobs/manual.jsonl \
  --output outputs/jobs/all.jsonl

python3 -m offerquest rank-jobs \
  --profile outputs/bulat-profile.json \
  --jobs-file outputs/jobs/all.jsonl
```
