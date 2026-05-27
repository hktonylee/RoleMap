# Resume Generation Design

## Goal

Add a local-first resume generation flow to the job details view. A user keeps resume instructions under `ROLEMAP_RESUME_TEMPLATE_DIR`, opens a saved job, presses `G`, and RoleMap prepares a tailored resume generation run for that job.

## Requirements

- Use `ROLEMAP_RESUME_TEMPLATE_DIR` as the instruction directory.
- Let the TUI details view start resume generation with `G`.
- Generate a job-specific output directory containing the job description and a prompt for tailoring the resume.
- Temporarily leave the curses UI and show the Codex interactive CLI while generation runs.
- Redraw the job detail view after Codex exits, with a status message pointing at the result HTML file.
- Run `codex` as the visible generator command.

## Architecture

- `role_map.resumes`: owns instruction directory resolution, output path naming, prompt creation, and optional command execution.
- `role_map.tui`: owns only interaction state: details view and status messages.
- `role_map.cli`: keeps existing job commands unchanged for now; the first entry point is the TUI because the request centers on the job details page.

The generator command receives environment variables instead of hardcoded provider logic:

- `ROLEMAP_RESUME_TEMPLATE_DIR`: source instruction directory.
- `ROLEMAP_RESUME_OUTPUT_DIR`: output directory for the run.

This keeps RoleMap independent from any one AI backend while still making the background step scriptable.

## Data Flow

1. Detail screen receives `G`.
2. TUI calls `role_map.resumes.generate_resume()`.
3. `role_map.resumes.generate_resume()` creates `generated/resumes/<job-id>-<company>-<title>-<timestamp>/`.
4. The module writes `job-description.txt` and `tailoring-prompt.md`.
5. The prompt instructs the generator to write `tailored-resume.html` in the output directory.
6. RoleMap suspends curses and launches the visible generator command, defaulting to interactive `codex`.
7. When the generator exits, RoleMap restores the details view and shows the result HTML path or a short error.

## Error Handling

If the instruction directory is not configured or does not exist, the TUI shows a status message and stays on the details view. If the configured generator exits non-zero, the error is surfaced in the status line and the generated prompt files remain for manual retry.

## Tests

Tests cover prompt/output creation, result HTML path creation, visible Codex command construction, configured command execution, the detail help text, `G` starting generation, and generation failure handling.
