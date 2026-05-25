# Resume Generation Design

## Goal

Add a local-first resume generation flow to the job details view. A user keeps detailed master resume files under `templates/` or `resume_templates/`, opens a saved job, presses `G`, chooses a template, and CareerOps prepares a tailored resume generation run for that job.

## Requirements

- Discover resume template files from `templates/` and `resume_templates/`.
- Let the TUI details view open a template picker with `G`.
- Generate a job-specific output directory containing the selected template copy, the job description, and a prompt for tailoring the resume.
- Run a configured background command when `CAREEROPS_RESUME_GENERATOR` is set.
- Fall back to writing the prompt and template copy without calling an external generator when no command is configured.

## Architecture

- `careerops.resumes`: owns template discovery, output path naming, prompt creation, and optional command execution.
- `careerops.tui`: owns only interaction state: details view, template picker, and status messages.
- `careerops.cli`: keeps existing job commands unchanged for now; the first entry point is the TUI because the request centers on the job details page.

The generator command receives environment variables instead of hardcoded provider logic:

- `CAREEROPS_RESUME_TEMPLATE`: selected source template path.
- `CAREEROPS_RESUME_TEMPLATE_COPY`: copied template inside the output directory.
- `CAREEROPS_RESUME_PROMPT`: generated prompt path.
- `CAREEROPS_RESUME_JOB_DESCRIPTION`: generated job description path.
- `CAREEROPS_RESUME_OUTPUT_DIR`: output directory for the run.

This keeps CareerOps independent from any one AI backend while still making the background step scriptable.

## Data Flow

1. Detail screen receives `G`.
2. TUI asks `careerops.resumes` for available templates.
3. User selects a template.
4. `careerops.resumes.generate_resume()` creates `generated/resumes/<job-id>-<company>-<title>-<timestamp>/`.
5. The module writes `job-description.txt`, `tailoring-prompt.md`, and a copy of the chosen template.
6. If `CAREEROPS_RESUME_GENERATOR` is set, CareerOps runs it with the generated paths in the environment.
7. The TUI shows success or a short error message.

## Error Handling

If no templates exist, the TUI shows a status message and stays on the details view. If the configured generator exits non-zero, the error is surfaced in the status line and the generated prompt files remain for manual retry.

## Tests

Tests cover template discovery, prompt/output creation, configured command execution, the detail help text, `G` opening the template picker, no-template handling, and selecting a template from the picker.
