# RoleMap

RoleMap is a local-first job search workspace. It keeps every job description,
company, salary range, URL, and local status in a private SQLite database so
you can search roles quickly, reopen the original posting, mark expired jobs,
and generate tailored resume prompts from the same source of truth.

If your job search is spread across browser tabs, emails, pasted notes, and
one-off resume drafts, RoleMap gives you one durable place to keep the roles
that matter.

![RoleMap demo](docs/Demo.gif)

## Why Use RoleMap

- Private by default: your job database stays on your machine.
- Fast to search: browse saved roles from a terminal UI or scriptable CLI.
- Built for real job posts: store full source-backed descriptions, not only
  short summaries.
- Duplicate-aware: importing the same URL updates the existing job instead of
  creating clutter.
- Resume-ready: open a saved role and prepare a tailored generation run from
  template-directory instructions.
- Agent-friendly: includes a project-local Codex skill for adding job
  descriptions consistently.

## Install

RoleMap requires Python 3.12 or newer.

Clone the repository and install the console command:

```bash
git clone <repository-url>
cd RoleMap
python -m pip install -e .
```

Check the command:

```bash
rolemap --help
```

You can also run it without installing:

```bash
python -m role_map --help
```

## Quick Start

Initialize your local database:

```bash
rolemap init
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

Open the interactive job browser:

```bash
rolemap tui
```

Search from the CLI:

```bash
rolemap list-jobs --query "platform"
```

Show one saved job:

```bash
rolemap show-job 1
```

By default, RoleMap writes to:

```text
$XDG_STATE_HOME/rolemap/rolemap.sqlite3
```

If `XDG_STATE_HOME` is unset, RoleMap falls back to:

```text
~/.local/state/rolemap/rolemap.sqlite3
```

Use another database with either `--db` or `ROLEMAP_DB`:

```bash
rolemap --db /tmp/rolemap.sqlite3 init
ROLEMAP_DB=/tmp/rolemap.sqlite3 rolemap list-jobs
```

## Terminal UI

The TUI is the fastest way to work through saved jobs.

- Type to filter by publish date, company, title, description, URL, or salary.
- Press `o` to choose a sort column.
- Use lowercase sort keys for ascending order and uppercase keys for descending.
- Press Backspace or Delete to toggle whether the selected job is expired.
- Press Enter or Right to open details.
- Press Up, Down, Page Up, Page Down, Home, or End to scroll.
- Press `G` from a job detail view to prepare a tailored resume generation run.
- Press Esc, `q`, or Left to go back or quit.

Expired rows are dimmed, struck through, and sorted after active jobs.

## Import Jobs

Add a job from a text file:

```bash
rolemap add-job \
  --title "Staff Platform Engineer" \
  --company "Example Systems" \
  --job-description-file /tmp/job-description.txt \
  --url "https://example.com/jobs/platform-engineer"
```

Import one JSON object:

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

`add-job --json` also accepts an array of job objects.

RoleMap requires `job_title`, `company_name`, and `job_description`. `publish_date`,
`url`, and `salary_range` can be empty strings when unknown. `is_expired` is
optional and defaults to false. Do not provide `last_update`; RoleMap sets it
when a row is inserted or updated.

If a URL is present, importing the same URL again updates the existing row and
refreshes `last_update`.

## Project-Local Codex Skill

RoleMap includes a Codex skill for importing source-backed job descriptions:

```text
codex-skills/add-job-description/SKILL.md
```

Example request:

```text
Use the RoleMap add-job-description skill to import all jobs from Gmail.

Search Gmail for job-posting emails, extract each posting URL, fetch the
canonical posting text, write the jobs to a temporary JSON file, and run:

python -m role_map add-job --json /path/to/jobs.json

Use empty strings for unknown optional fields. Do not summarize descriptions.
```

The skill tells Codex to prefer company posting text over email snippets, keep
the full source-backed description, and let RoleMap upsert duplicates by URL.

## Resume Generation

Configure the resume workspace directory:

```text
ROLEMAP_RESUME_TEMPLATE_DIR
```

This directory is not treated as a single static template file. It is the
working directory for the resume agent. Put the resume source files and
instructions there, such as `AGENTS.md`, examples, or any files the agent should
use when creating a tailored resume.

From a job detail view in the TUI, press `G`. RoleMap creates a job-specific
output directory under:

```text
generated/resumes/
```

Set `ROLEMAP_RESUME_OUTPUT_DIR` to write runs somewhere else.

Each run prepares:

- `job-description.txt`
- `tailoring-prompt.md`
- `tailored-resume.html`, written by the generator

RoleMap then opens `codex` in your terminal from the configured workspace
directory with `--cd`. Codex reads the workspace instructions, receives the job
prompt, and writes the tailored resume into the output directory.

The generator receives these environment variables:

```text
ROLEMAP_RESUME_TEMPLATE_DIR
ROLEMAP_RESUME_OUTPUT_DIR
```

## Keep Descriptions Source-Backed

RoleMap works best when `job_description` contains the original job posting text
instead of generated summaries.

Preview backfills for older generated or email-summary descriptions:

```bash
rolemap backfill-descriptions --dry-run
```

Apply the backfill:

```bash
rolemap backfill-descriptions
```

Overwrite existing full descriptions when you intentionally want to refetch
them from source URLs:

```bash
rolemap backfill-descriptions --overwrite
```

Fill missing salary ranges from saved descriptions:

```bash
rolemap backfill-salaries --dry-run
rolemap backfill-salaries
```

Clean already-stored source text that contains known site chrome:

```bash
rolemap clean-descriptions --dry-run
rolemap clean-descriptions
```

The current cleaner handles known LinkedIn search, sign-in, pay-range widget,
and footer text while preserving job, company, and role sections.

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

When `list-jobs` output is redirected or piped, it prints tab-separated rows
with `id`, `publish_date`, `company_name`, `job_title`, `salary_range`, `url`,
`is_expired`, and `last_update`.

## Repository Layout

```text
role_map/db.py          SQLite connection and schema setup
role_map/jobs.py        Job data shape, validation, upsert, list, search, and detail queries
role_map/job_sources.py Job-posting fetch, extraction, and cleanup helpers
role_map/resumes.py     Resume instruction setup, prompt creation, and generator execution
role_map/cli.py         Command-line interface
role_map/tui.py         curses-based job browser
codex-skills/           Project-local Codex workflows
docs/specs/             Design notes
tests/                  Unit tests
```

## Development

Run the test suite:

```bash
python -m unittest discover -s tests
```
