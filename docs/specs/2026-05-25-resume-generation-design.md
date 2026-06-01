# Resume Generation Design

## Goal

Add a local-first resume generation flow to the job details view. A user keeps resume instructions under `ROLEMAP_RESUME_TEMPLATE_DIR`, opens a saved job, presses `g`, and RoleMap prepares a tailored resume generation run for that job.

## Requirements

- Use `ROLEMAP_RESUME_TEMPLATE_DIR` as the instruction directory.
- Let the TUI details view start resume generation with `g`.
- Temporarily leave the curses UI and show the Codex interactive CLI while generation runs.
- Redraw the job detail view after Codex exits, with a status message that generation finished.
- Run `codex` as the visible generator command.

## Architecture

- `role_map.resumes`: owns instruction directory resolution, prompt creation, and optional command execution.
- `role_map.tui`: owns only interaction state: details view and status messages.
- `role_map.cli`: keeps existing job commands unchanged for now; the first entry point is the TUI because the request centers on the job details page.

The generator command receives the instruction directory in the environment:

- `ROLEMAP_RESUME_TEMPLATE_DIR`: source instruction directory.

This keeps RoleMap independent from any one AI backend while still making the background step scriptable.

## Data Flow

1. Detail screen receives `g`.
2. TUI calls `role_map.resumes.generate_resume()`.
3. `role_map.resumes.generate_resume()` builds the job prompt from the selected row.
4. RoleMap suspends curses and launches the visible generator command, defaulting to interactive `codex --cd <ROLEMAP_RESUME_TEMPLATE_DIR>`.
5. Codex reads the template directory's `AGENTS.md` and handles output according to those instructions.
6. When the generator exits, RoleMap restores the details view and shows a short success or error message.

## Error Handling

If the instruction directory is not configured or does not exist, the TUI shows a status message and stays on the details view. If the configured generator exits non-zero, the error is surfaced in the status line.

## Tests

Tests cover prompt creation, visible Codex command construction, configured command execution, the detail help text, `g` starting generation, and generation failure handling.
