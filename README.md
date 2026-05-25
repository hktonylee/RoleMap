# CareerOps

CareerOps is a local-first career operations toolkit for collecting, storing, and browsing job descriptions. It keeps job records in SQLite so local scripts, Codex workflows, a terminal UI, and future resume-generation tools can work from the same source of truth.

The repository currently focuses on one durable domain object: `jobs`. Each job record stores the publish date, title, company, full source-backed description, canonical posting URL, salary range, expired flag, local update timestamp, and creation timestamp.

## What This Repository Is Used For

- Keep a private SQLite database of job descriptions under `data/careerops.sqlite3` by default.
- Import jobs from JSON files, one-off CLI arguments, or agent-produced job-description extracts.
- Update existing jobs by URL instead of creating duplicate rows.
- Search and inspect saved jobs from scripts or a curses-based terminal UI.
- Backfill generated or email-summary descriptions with text fetched from the original job posting URL.
- Clean known source-site navigation text, sign-in prompts, and footer chrome from stored descriptions.
- Prepare tailored resume generation runs from detailed resume templates and saved job descriptions.
- Provide a project-local Codex skill at `codex-skills/add-job-description/SKILL.md` for adding job descriptions consistently.

## Setup

Run commands from the repository root.

Use the module directly:

```bash
python -m careerops --help
```

Or install the console script in editable mode:

```bash
python -m pip install -e .
careerops --help
```

By default, CareerOps writes to:

```text
data/careerops.sqlite3
```

Use another database with either `--db` or `CAREEROPS_DB`:

```bash
python -m careerops --db /tmp/careerops.sqlite3 init
CAREEROPS_DB=/tmp/careerops.sqlite3 python -m careerops list-jobs
```

## Quick Start

Initialize the database:

```bash
python -m careerops init
```

Add a job from command-line fields:

```bash
python -m careerops add-job \
  --publish-date 2026-05-20 \
  --title "Senior Software Engineer" \
  --company "Example Systems" \
  --description "Full job description text..." \
  --url "https://example.com/jobs/123" \
  --salary-range '$150k-$190k'
```

Add a job from a description file:

```bash
python -m careerops add-job \
  --title "Staff Platform Engineer" \
  --company "Example Systems" \
  --description-file /tmp/job-description.txt \
  --url "https://example.com/jobs/platform-engineer"
```

List saved jobs:

```bash
python -m careerops list-jobs
```

Show one job in detail:

```bash
python -m careerops show-job 1
```

Open the terminal UI:

```bash
python -m careerops tui
```

`list-jobs` also opens the interactive list when stdin and stdout are both terminals. When output is redirected or piped, it prints tab-separated rows with `id`, `publish_date`, `company_name`, `job_title`, `salary_range`, `url`, `is_expired`, and `last_update`.

## JSON Imports

`add-job --json` accepts either one object or an array of objects.

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

Import one file:

```bash
python -m careerops add-job --json job.json
```

Import several jobs from one JSON array:

```json
[
  {
    "publish_date": "2026-05-20",
    "job_title": "Senior Software Engineer",
    "company_name": "Example Systems",
    "description": "Full job description text...",
    "url": "https://example.com/jobs/123",
    "salary_range": "$150k-$190k"
  },
  {
    "publish_date": "",
    "job_title": "Engineering Manager",
    "company_name": "Acme Labs",
    "description": "Full job description text...",
    "url": "https://acme.example/jobs/eng-manager",
    "salary_range": ""
  }
]
```

CareerOps treats `job_title`, `company_name`, and `description` as required fields. `publish_date`, `url`, and `salary_range` can be empty strings when unknown. `is_expired` is optional and defaults to false. Do not provide `last_update`; CareerOps sets it locally when a row is inserted or updated.

If a URL is present, importing the same URL again updates the existing row and refreshes `last_update`.

## Browsing And Searching

Search from the CLI:

```bash
python -m careerops list-jobs --query "platform"
```

Pipe tab-separated rows into another command:

```bash
python -m careerops list-jobs --query "remote" > /tmp/jobs.tsv
```

In the terminal UI:

- Type to filter jobs by publish date, company, title, description, URL, or salary range.
- Press `o` to choose a sort column. Use lowercase for ascending order or uppercase for descending order.
- Press Space to toggle the selected job's expired state. Expired rows are dimmed, struck through, and sorted after active rows.
- Press Enter or Right to open details.
- Press Up, Down, Page Up, Page Down, Home, or End to scroll.
- Press `G` from a job detail view to choose a resume template and prepare a tailored resume generation run.
- Press Esc, `q`, or Left to go back or quit.

## Resume Generation

Put detailed master resume files in either:

```text
templates/
resume_templates/
```

From the TUI job detail view, press `G`, choose a template, and press Enter. CareerOps creates a job-specific directory under:

```text
generated/resumes/
```

Each run contains:

- a copy of the selected resume template
- `job-description.txt`
- `tailoring-prompt.md`
- `tailored-resume.html`, written by the generator

After preparing those files, CareerOps temporarily leaves the job browser and opens the Codex interactive CLI in the terminal. When Codex exits, CareerOps redraws the job detail view with the path to `tailored-resume.html`.

To run a different visible generator command, set `CAREEROPS_RESUME_GENERATOR`. CareerOps runs the command from the generated output directory and provides these environment variables:

```text
CAREEROPS_RESUME_TEMPLATE
CAREEROPS_RESUME_TEMPLATE_COPY
CAREEROPS_RESUME_PROMPT
CAREEROPS_RESUME_JOB_DESCRIPTION
CAREEROPS_RESUME_OUTPUT_DIR
CAREEROPS_RESUME_RESULT_HTML
```

## Maintaining Source-Backed Descriptions

Keep `description` source-backed: store the original job posting text instead of generated or summarized copy.

Preview backfills for older generated or email-summary descriptions:

```bash
python -m careerops backfill-descriptions --dry-run
```

Apply the backfill:

```bash
python -m careerops backfill-descriptions
```

Overwrite existing full descriptions when you intentionally want to refetch them from source URLs:

```bash
python -m careerops backfill-descriptions --overwrite
```

Clean already-stored source text that contains known site chrome:

```bash
python -m careerops clean-descriptions --dry-run
python -m careerops clean-descriptions
```

The current cleaner handles known LinkedIn search, sign-in, pay-range widget, and footer text while preserving the job/company/role sections.

## Repository Layout

```text
careerops/db.py          SQLite connection and schema setup
careerops/jobs.py        Job data shape, validation, upsert, list, search, and detail queries
careerops/job_sources.py Job-posting fetch, extraction, and cleanup helpers
careerops/cli.py         Command-line interface
careerops/tui.py         curses-based job browser
codex-skills/            Project-local Codex workflows
docs/specs/              Design notes
tests/                   Unit tests
```
