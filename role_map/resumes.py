from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import os
from pathlib import Path
import subprocess

from role_map.jobs import JobRow


TEMPLATE_DIRECTORY_ENV_VAR = "ROLEMAP_RESUME_TEMPLATE_DIR"


@dataclass(frozen=True)
class ResumeGenerationResult:
    instruction_dir: Path
    prompt: str
    command_ran: bool


def generate_resume(
    row: JobRow,
    *,
    root: str | Path = ".",
    environ: Mapping[str, str] | None = None,
) -> ResumeGenerationResult:
    base = Path(root)
    env_source = dict(os.environ if environ is None else environ)
    instruction_dir = _instruction_directory(base, env_source)

    return ResumeGenerationResult(
        instruction_dir=instruction_dir,
        prompt=_format_prompt(row),
        command_ran=False,
    )


def run_resume_generator(
    result: ResumeGenerationResult,
    *,
    environ: Mapping[str, str] | None = None,
    command_runner=subprocess.run,
) -> None:
    env_source = dict(os.environ if environ is None else environ)
    run_env = {
        **_without_resume_environment(env_source),
        TEMPLATE_DIRECTORY_ENV_VAR: str(result.instruction_dir),
    }
    cwd = result.instruction_dir.resolve()
    command = ["codex", "--cd", str(cwd), result.prompt]
    command_runner(command, cwd=cwd, env=run_env, check=True)


def _without_resume_environment(environ: Mapping[str, str]) -> dict[str, str]:
    return {
        name: value
        for name, value in environ.items()
        if not name.startswith("ROLEMAP_RESUME_")
    }


def _format_prompt(row: JobRow) -> str:
    return (
        "Please generate the resume for this job:\n"
        "There is an example resume in this directory for reference.\n"
        f"Company: {_row_text(row, 'company_name')}\n"
        f"Title: {_row_text(row, 'job_title')}\n"
        f"Description: {_row_text(row, 'job_description')}\n"
    )


def _instruction_directory(
    base: Path,
    environ: Mapping[str, str],
) -> Path:
    configured_directory = environ.get(TEMPLATE_DIRECTORY_ENV_VAR, "").strip()
    if not configured_directory:
        raise FileNotFoundError(
            f"resume instruction directory not configured: set {TEMPLATE_DIRECTORY_ENV_VAR}"
        )
    instruction_dir = Path(configured_directory)
    if not instruction_dir.is_absolute():
        instruction_dir = base / instruction_dir
    if not instruction_dir.is_dir():
        raise FileNotFoundError(f"resume instruction directory not found: {instruction_dir}")
    return instruction_dir


def _row_text(row: JobRow, key: str) -> str:
    try:
        value = row[key]
    except (KeyError, IndexError):
        return ""
    if value is None:
        return ""
    return str(value).strip()
