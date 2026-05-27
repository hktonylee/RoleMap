# SQLite RoleMap Design

## Goal

Build a local, SQLite-centered RoleMap system for storing and browsing job descriptions. The first durable domain object is `jobs`; later modules should be able to generate resumes from the same job records, and a future web UI should be able to reuse the database and service layer without rewriting core logic.

## Requirements

- Store jobs in SQLite with at least: publish date, job title, company name, job_description, URL, salary range, expired flag, and last local update time.
- Provide a Codex skill that tells Codex how to add a job description from external sources such as email, company sites, or pasted JD text.
- Provide an interactive terminal UI with a filterable fzf-like job list and a details viewer.
- Keep the implementation dependency-light and local-first.
- Design the module boundaries so future resume generation and web UI work can call the same job repository.

## Architecture

- `role_map.db`: owns SQLite connection setup, schema creation, and migrations.
- `role_map.jobs`: owns the `JobInput` data shape, validation, upsert/add behavior, and read queries.
- `role_map.job_sources`: fetches job posting URLs and extracts source-backed job description text, preferring structured `JobPosting` data when available.
- `role_map.cli`: exposes scriptable commands for importing jobs, listing jobs, showing details, and launching the TUI.
- `role_map.tui`: owns curses-based interactive browsing only; it calls the repository instead of touching SQL directly.
- `codex-skills/add-job-description/SKILL.md`: project skill for Codex agents adding job descriptions.

This keeps storage, domain rules, and UI separate. Resume generation can later depend on `role_map.jobs` and add its own module without coupling to curses or CLI parsing. A web UI can do the same.

## Database

The `jobs` table uses a stable integer primary key and stores source data as text:

- `id`
- `publish_date`
- `job_title`
- `company_name`
- `job_description`
- `url`
- `salary_range`
- `is_expired`
- `last_update`
- `created_at`

`url` is unique when present so repeated imports from the same job posting update the existing row. `is_expired` is a local tracking flag for postings that should remain in history but no longer be treated as active. List and search views order by `is_expired` first so active jobs stay above expired jobs. `last_update` is always set by the local system in ISO-8601 local time when the record is inserted or updated.

## CLI And TUI

CLI commands:

- `rolemap init`
- `rolemap add-job --json FILE`
- `rolemap add-job --title ... --company ... --job-description ...`
- `rolemap backfill-descriptions [--dry-run] [--overwrite]`
- `rolemap clean-descriptions [--dry-run]`
- `rolemap list-jobs`
- `rolemap show-job ID`
- `rolemap tui`

The TUI starts with a searchable list. Typing filters by company, title, URL, salary, publish date, and job_description. Pressing Backspace or Delete toggles the selected job's `is_expired` flag; expired rows are dimmed, struck through, and sorted after active rows. Pressing `o` opens a sort-column selector for the list; lowercase column keys sort ascending, and uppercase keys sort descending. Enter or the right arrow opens a details viewer; Escape, `q`, or the left arrow returns from details; Escape or `q` exits from the list.

## Error Handling

Validation rejects missing title, company, job_description, and malformed empty JSON. Database setup is idempotent. CLI errors should be short and actionable, returning a non-zero exit code. The TUI should tolerate an empty database and show an empty list instead of crashing.

`job_description` should contain source-backed job posting text, not agent-generated summaries. Backfill replaces generated-looking descriptions with text pulled from the stored source URL; by default it only touches descriptions that start with `Source: ` so manually curated full descriptions are preserved.

Source extraction should remove non-JD site chrome where possible. The cleaner strips known LinkedIn navigation, search, sign-in, pay-range widget, and footer text while preserving the actual job/company/role sections.

## Tests

Initial tests cover:

- Schema creation includes the required columns.
- Adding a job writes required fields and sets local timestamps.
- Adding the same URL updates the existing row instead of duplicating it.
- Backfilling generated descriptions updates the row from source URL text without overwriting manual full descriptions by default.
- Cleaning descriptions removes known source-site chrome from already-stored descriptions.
- Search returns jobs across title, company, job_description, URL, salary, and publish date.
- The Codex skill document exists and names the required add-job workflow.
