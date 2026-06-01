---
name: add-job-description
description: Add a job description to the local RoleMap SQLite database from pasted text, email extracts, company pages, or other JD sources.
---

# Add Job Description To RoleMap

Use this skill when the user asks Codex to add a job description to RoleMap. The source can be a pasted JD, email content, a company site extract, or another upstream collector.

Do not generate, summarize, rewrite, infer, or synthesize the `job_description` yourself. The `job_description` field is copied source text, not a generated summary and not a combined description assembled from metadata, email snippets, salary fields, requirements, benefits, or multiple sources. When a posting URL is available, use Playwright to download the source website and copy 100% of the actual job description section from that page; prefer structured `JobPosting` content when present, then visible page text. Incoming source is often HTML, so store extracted `job_description` as Markdown that preserves source headings, lists, paragraphs, and links without adding new claims. Markdown conversion is formatting only: keep the source wording, order, scope, and meaning intact.

## Required Fields

Capture these fields for the `jobs` table:

- `publish_date`
- `job_title`
- `company_name`
- `job_description`
- `url`
- `salary_range`

Do not provide `last_update` or `created`; RoleMap sets them locally. `last_update` changes when `rolemap add-job` inserts or updates the row, while `created` stays fixed at the row's original insert time.

## Workflow

1. Extract metadata fields from the best available source evidence.
2. If a job posting URL is available, use Playwright to load the source website and copy the full description from the page rather than writing a generated description.
3. Preserve the full source job description text in `job_description`. Do not invent, condense, paraphrase, reorder, or merge text from other sources. Copy 100% from the job site description section.
4. Prefer Markdown output for `job_description` when the source is HTML. Convert structural HTML to Markdown (`#` headings, ` * ` bullets, paragraphs, and links) while keeping the description text source-backed and complete.
5. If only an email or search result is available, use it to find the posting URL and metadata, but do not store the email/search snippet as `job_description`. If the source website cannot be reached and no pasted full JD was provided, do not add the job; report that the description still needs source-site text.
6. Infer `publish_date` from the source website first, using structured `datePosted`, visible posted-date text, or nearby page metadata. If the website does not expose a publish date and the source came from email, infer `publish_date` from the email date. Use an empty string only after both website and email evidence are unavailable.
7. Use an empty string for unknown optional fields such as `salary_range`.
8. Write a temporary JSON object with the required field names.
9. Run:

```bash
python -m role_map add-job --json /path/to/job.json
```

or, if installed as a console script:

```bash
rolemap add-job --json /path/to/job.json
```

10. Report the returned job id and whether the source URL suggests this was an update to an existing job.

## JSON Shape

```json
{
  "publish_date": "2026-05-20",
  "job_title": "Senior Software Engineer",
  "company_name": "Example Systems",
  "job_description": "Full job description text...",
  "url": "https://example.com/jobs/123",
  "salary_range": "$150k-$190k"
}
```

## Guardrails

- Keep claims source-grounded; do not invent salary, publish date, or URL.
- Prefer Markdown for extracted HTML job descriptions, but do not rewrite, summarize, combine, or polish the source text to make it prettier.
- Prefer the canonical company posting URL over aggregator URLs.
- For email sources, extract the job posting link from the email body; `url` must be the job posting URL, not a Gmail thread URL.
- For email sources, follow the posting link with Playwright and backfill `job_description` from the source website before treating the row as complete; never use an email snippet as the final description.
- For email sources, use the email date for `publish_date` only when the website does not provide a publish date.
- To replace older generated/email-summary descriptions, run `python -m role_map backfill-descriptions` against the target database. Use `--dry-run` first when you want to preview which source URLs can be fetched.
- If fetched source text includes site chrome such as `Skip to main content`, `Expand search`, sign-in prompts, or footers, run `python -m role_map clean-descriptions` to remove known non-JD text from stored descriptions.
- If the job text includes multiple roles, ask which one to add unless the user already named the role.
- If the same `url` is imported again, RoleMap updates that row and refreshes `last_update`; `created` keeps the original insert time.
