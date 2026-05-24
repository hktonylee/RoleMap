# SQLite CareerOps Design

## Goal

Build a local, SQLite-centered CareerOps system for storing and browsing job descriptions. The first durable domain object is `jobs`; later modules should be able to generate resumes from the same job records, and a future web UI should be able to reuse the database and service layer without rewriting core logic.

## Requirements

- Store jobs in SQLite with at least: publish date, job title, company name, description, URL, salary range, and last local update time.
- Provide a Codex skill that tells Codex how to add a job description from external sources such as email, company sites, or pasted JD text.
- Provide an interactive terminal UI with a filterable fzf-like job list and a details viewer.
- Keep the implementation dependency-light and local-first.
- Design the module boundaries so future resume generation and web UI work can call the same job repository.

## Architecture

- `careerops.db`: owns SQLite connection setup, schema creation, and migrations.
- `careerops.jobs`: owns the `JobInput` data shape, validation, upsert/add behavior, and read queries.
- `careerops.cli`: exposes scriptable commands for importing jobs, listing jobs, showing details, and launching the TUI.
- `careerops.tui`: owns curses-based interactive browsing only; it calls the repository instead of touching SQL directly.
- `codex-skills/add-job-description/SKILL.md`: project skill for Codex agents adding job descriptions.

This keeps storage, domain rules, and UI separate. Resume generation can later depend on `careerops.jobs` and add its own module without coupling to curses or CLI parsing. A web UI can do the same.

## Database

The `jobs` table uses a stable integer primary key and stores source data as text:

- `id`
- `publish_date`
- `job_title`
- `company_name`
- `description`
- `url`
- `salary_range`
- `last_update`
- `created_at`

`url` is unique when present so repeated imports from the same job posting update the existing row. `last_update` is always set by the local system in ISO-8601 local time when the record is inserted or updated.

## CLI And TUI

CLI commands:

- `careerops init`
- `careerops add-job --json FILE`
- `careerops add-job --title ... --company ... --description ...`
- `careerops list-jobs`
- `careerops show-job ID`
- `careerops tui`

The TUI starts with a searchable list. Typing filters by company, title, URL, salary, publish date, and description. Enter opens a details viewer; Escape, `q`, or the left arrow returns from details; Escape or `q` exits from the list.

## Error Handling

Validation rejects missing title, company, description, and malformed empty JSON. Database setup is idempotent. CLI errors should be short and actionable, returning a non-zero exit code. The TUI should tolerate an empty database and show an empty list instead of crashing.

## Tests

Initial tests cover:

- Schema creation includes the required columns.
- Adding a job writes required fields and sets local timestamps.
- Adding the same URL updates the existing row instead of duplicating it.
- Search returns jobs across title, company, description, URL, salary, and publish date.
- The Codex skill document exists and names the required add-job workflow.
