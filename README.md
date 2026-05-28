# RoleMap

RoleMap is a local-first job search workspace. It stores job descriptions,
companies, salary ranges, URLs, and status in a private SQLite DB so you can
search roles, track what matters, and generate a tailored resume from a saved
job.

![RoleMap demo](docs/Demo.gif)

## What It Does

- Saves full, source-backed job descriptions.
- Searches jobs from a terminal UI or CLI.
- Updates duplicate URLs instead of creating duplicate rows.
- Tracks starred, expired, and pruned jobs.
- Generates a tailored resume from a job detail view with one key: `G`.
- Uses your own resume workspace, so resume generation is fully customizable.

## Install

RoleMap requires Python 3.12 or newer.

```bash
git clone <repository-url>
cd RoleMap
python -m pip install -e .
rolemap --help
```

Without installing:

```bash
python -m role_map --help
```

## Quick Start

```bash
rolemap init
rolemap tui
```

Add a job:

```bash
rolemap add-job \
  --publish-date 2026-05-20 \
  --title "Senior Software Engineer" \
  --company "Example Systems" \
  --job-description "Full job description text..." \
  --url "https://example.com/jobs/123" \
  --salary-range '$150k-$190k'
```

Search and inspect from CLI:

```bash
rolemap list-jobs --query "platform"
rolemap show-job 1
```

Default DB path:

```text
$XDG_STATE_HOME/rolemap/rolemap.sqlite3
```

If `XDG_STATE_HOME` is unset:

```text
~/.local/state/rolemap/rolemap.sqlite3
```

Use another DB:

```bash
rolemap --db /tmp/rolemap.sqlite3 init
ROLEMAP_DB=/tmp/rolemap.sqlite3 rolemap list-jobs
```

## Terminal UI

Run:

```bash
rolemap tui
```

Keys:

- `/`: search jobs.
- `o`: choose sort column.
- lowercase sort key: ascending.
- uppercase sort key: descending.
- `Delete`: toggle expired.
- `s`: toggle starred.
- `p`: prune expired jobs after confirmation.
- `r`: refresh.
- `Enter` or `Right`: open details.
- `Up`, `Down`, `Page Up`, `Page Down`, `Home`, `End`: scroll.
- `G`: generate a tailored resume from selected job details.
- `Esc`, `q`, or `Left`: go back or quit.

Expired rows are dimmed, struck through, and sorted after active jobs. Starred
rows are highlighted. Pruned jobs are hidden from list and search results.

## Resume Generation

Resume generation starts from a saved job detail view:

1. Open `rolemap tui`.
2. Select a job.
3. Press Enter or Right.
4. Press `G`.

`G` opens `codex` from your resume workspace and sends the selected job's
company, title, and description. Your workspace controls the output, so resume
format, style, file layout, and instructions are fully customizable.

Set your resume workspace:

```text
ROLEMAP_RESUME_TEMPLATE_DIR
```

This directory is an agent workspace, not one static template file. Put your
resume sources, examples, and instructions there, such as `AGENTS.md` and any
files Codex should use.

## Import Jobs

Add a job from a text file:

```bash
rolemap add-job \
  --title "Staff Platform Engineer" \
  --company "Example Systems" \
  --job-description-file /tmp/job-description.txt \
  --url "https://example.com/jobs/platform-engineer"
```

Import JSON:

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

```bash
rolemap add-job --json job.json
```

`add-job --json` also accepts an array of job objects. Required fields:
`job_title`, `company_name`, and `job_description`.

Optional fields: `publish_date`, `url`, `salary_range`, `is_starred`,
`is_expired`, and `is_pruned`. Do not provide `last_update`; RoleMap sets it.

If a URL is present, importing the same URL updates the existing row.

## Keep Descriptions Source-Backed

RoleMap works best when `job_description` contains original job posting text,
not generated summaries.

Backfill older generated or email-summary descriptions:

```bash
rolemap backfill-descriptions --dry-run
rolemap backfill-descriptions
```

Overwrite existing descriptions when you intentionally want to refetch from
source URLs:

```bash
rolemap backfill-descriptions --overwrite
```

Fill missing salary ranges:

```bash
rolemap backfill-salaries --dry-run
rolemap backfill-salaries
```

Clean stored source text that contains known site chrome:

```bash
rolemap clean-descriptions --dry-run
rolemap clean-descriptions
```

## CLI Reference

```text
rolemap init
rolemap add-job --json FILE
rolemap add-job --title ... --company ... --job-description ...
rolemap list-jobs [--query TEXT]
rolemap show-job ID
rolemap backfill-descriptions [--dry-run] [--overwrite]
rolemap backfill-salaries [--dry-run] [--overwrite] [--fetch]
rolemap clean-descriptions [--dry-run]
rolemap tui
```

When `list-jobs` output is redirected or piped, it prints tab-separated rows:
`id`, `publish_date`, `company_name`, `job_title`, `salary_range`, `url`,
`is_expired`, and `last_update`.

## Development

```bash
python -m unittest discover -s tests
```
