---
name: list-jobs
description: Use when the user asks to get, list, search, inspect, or summarize saved jobs from the local RoleMap SQLite database.
---

# List Jobs From RoleMap

Use this skill when the user asks Codex to get the list of saved jobs in RoleMap, search saved jobs, or report what jobs are currently stored.

This is a read-only workflow. Do not add, update, expire, clean, backfill, or delete jobs unless the user explicitly asks for that separate action.

## Workflow

1. Use the local RoleMap CLI from the repository root.
2. If the user gives a database path, pass it with `--db`. If they mention `ROLEMAP_DB`, preserve or set that environment variable for the command.
3. If the user gives search text, pass it with `--query`.
4. Run the command in a noninteractive context so `list-jobs` prints rows instead of opening the TUI.
5. Report the job rows exactly enough for the user's request. Keep IDs visible so follow-up `show-job` or resume actions can target the right row.

## Commands

Installed command:

```bash
rolemap list-jobs
rolemap list-jobs --query "platform"
rolemap --db /path/to/rolemap.sqlite3 list-jobs
```

Module form when the console script is unavailable:

```bash
python -m role_map list-jobs
python -m role_map list-jobs --query "platform"
python -m role_map --db /path/to/rolemap.sqlite3 list-jobs
```

Environment-selected database:

```bash
ROLEMAP_DB=/path/to/rolemap.sqlite3 rolemap list-jobs
```

## Output

Noninteractive `rolemap list-jobs` output is tab-separated with these columns:

- `id`
- `publish_date`
- `company_name`
- `job_title`
- `salary_range`
- `url`
- `is_expired`
- `last_update`

If the user wants full details for one row, run `rolemap show-job ID` after listing. Do not infer details from truncated list rows.
