---
name: careerops-add-job-description
description: Add a job description to the local CareerOps SQLite database from pasted text, email extracts, company pages, or other JD sources.
---

# Add Job Description To CareerOps

Use this skill when the user asks Codex to add a job description to CareerOps. The source can be a pasted JD, email content, a company site extract, or another upstream collector.

Do not generate, summarize, rewrite, or infer the `description` yourself. The `description` field must be source-backed job-posting text. When a posting URL is available, fetch the source website and use the job description text from that page; prefer structured `JobPosting` content when present, then visible page text. Only use email snippets as a temporary placeholder when the source posting cannot be reached.

## Required Fields

Capture these fields for the `jobs` table:

- `publish_date`
- `job_title`
- `company_name`
- `description`
- `url`
- `salary_range`

Do not provide `last_update`; CareerOps sets `last_update` locally when `careerops add-job` inserts or updates the row.

## Workflow

1. Extract the best available job data from the source.
2. If a job posting URL is available, pull the description from the source website rather than writing a generated description.
3. Preserve the full source job description text in `description`.
4. Use an empty string for unknown optional fields such as `publish_date`, `url`, or `salary_range`.
5. Write a temporary JSON object with the required field names.
6. Run:

```bash
python -m careerops add-job --json /path/to/job.json
```

or, if installed as a console script:

```bash
careerops add-job --json /path/to/job.json
```

7. Report the returned job id and whether the source URL suggests this was an update to an existing job.

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

## Guardrails

- Keep claims source-grounded; do not invent salary, publish date, or URL.
- Prefer the canonical company posting URL over aggregator URLs.
- For email sources, extract the job posting link from the email body; `url` must be the job posting URL, not a Gmail thread URL.
- For email sources, follow the posting link and backfill `description` from the source website before treating the row as complete.
- To replace older generated/email-summary descriptions, run `python -m careerops backfill-descriptions` against the target database. Use `--dry-run` first when you want to preview which source URLs can be fetched.
- If the job text includes multiple roles, ask which one to add unless the user already named the role.
- If the same `url` is imported again, CareerOps updates that row and refreshes `last_update`.
