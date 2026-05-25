# Resume Generation Design

## Goal

Add a local-first resume generation flow to the job details view. A user keeps detailed master resume files under `templates/` or `resume_templates/`, opens a saved job, presses `G`, chooses a template, and RoleMap prepares a tailored resume generation run for that job.

## Requirements

- Discover resume template files from `templates/` and `resume_templates/`.
- Let the TUI details view open a template picker with `G`.
- Generate a job-specific output directory containing the selected template copy, the job description, and a prompt for tailoring the resume.
- Temporarily leave the curses UI and show the Codex interactive CLI while generation runs.
- Redraw the job detail view after Codex exits, with a status message pointing at the result HTML file.
- Run a configured visible command when `ROLEMAP_RESUME_GENERATOR` is set; otherwise default to `codex`.

## Architecture

- `rolemap.resumes`: owns template discovery, output path naming, prompt creation, and optional command execution.
- `rolemap.tui`: owns only interaction state: details view, template picker, and status messages.
- `rolemap.cli`: keeps existing job commands unchanged for now; the first entry point is the TUI because the request centers on the job details page.

The generator command receives environment variables instead of hardcoded provider logic:

- `ROLEMAP_RESUME_TEMPLATE`: selected source template path.
- `ROLEMAP_RESUME_TEMPLATE_COPY`: copied template inside the output directory.
- `ROLEMAP_RESUME_PROMPT`: generated prompt path.
- `ROLEMAP_RESUME_JOB_DESCRIPTION`: generated job description path.
- `ROLEMAP_RESUME_OUTPUT_DIR`: output directory for the run.
- `ROLEMAP_RESUME_RESULT_HTML`: expected final tailored resume HTML path.

This keeps RoleMap independent from any one AI backend while still making the background step scriptable.

## Data Flow

1. Detail screen receives `G`.
2. TUI asks `rolemap.resumes` for available templates.
3. User selects a template.
4. `rolemap.resumes.generate_resume()` creates `generated/resumes/<job-id>-<company>-<title>-<timestamp>/`.
5. The module writes `job-description.txt`, `tailoring-prompt.md`, and a copy of the chosen template.
6. The prompt instructs the generator to write `tailored-resume.html` in the output directory.
7. RoleMap suspends curses and launches the visible generator command, defaulting to interactive `codex`.
8. When the generator exits, RoleMap restores the details view and shows the result HTML path or a short error.

## Error Handling

If no templates exist, the TUI shows a status message and stays on the details view. If the configured generator exits non-zero, the error is surfaced in the status line and the generated prompt files remain for manual retry.

## Tests

Tests cover template discovery, prompt/output creation, result HTML path creation, visible Codex command construction, configured command execution, the detail help text, `G` opening the template picker, no-template handling, and selecting a template from the picker.
