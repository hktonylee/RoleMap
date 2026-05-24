# CareerOps

CareerOps is a local-first, SQLite-centered system for collecting and browsing job descriptions.

## Quick Start

Initialize a database:

```bash
python -m careerops init
```

Add a job from JSON:

```bash
python -m careerops add-job --json job.json
```

Backfill generated/email-summary descriptions from job posting URLs:

```bash
python -m careerops backfill-descriptions --dry-run
python -m careerops backfill-descriptions
python -m careerops clean-descriptions
```

Open the terminal UI:

```bash
python -m careerops list-jobs
```

When output is redirected or piped, `list-jobs` prints tab-separated rows.
In the interactive list, press `o` to choose the sort column.

By default the database lives at `data/careerops.sqlite3`. Set `CAREEROPS_DB` or pass `--db` to use another path.

## JSON Shape

```json
{
  "publish_date": "2026-05-20",
  "job_title": "Senior Software Engineer",
  "company_name": "Example Systems",
  "description": "Full job description text...",
  "url": "https://example.com/jobs/123",
  "salary_range": "$150k-$190k"
}
```

`last_update` is managed locally by CareerOps when a row is inserted or updated.
Keep `description` source-backed: fetch the job posting page and store the original job description text instead of generated or summarized copy.
If a fetched page includes source-site navigation text, `clean-descriptions` removes known chrome such as LinkedIn search, sign-in, and footer text from stored descriptions.
