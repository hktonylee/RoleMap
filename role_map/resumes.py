from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
import os
from pathlib import Path
import re
import subprocess

from role_map.jobs import JobRow


DEFAULT_OUTPUT_ROOT = Path("generated") / "resumes"
DEFAULT_RESULT_FILENAME = "tailored-resume.html"
TEMPLATE_DIRECTORY_ENV_VAR = "ROLEMAP_RESUME_TEMPLATE_DIR"
OUTPUT_DIRECTORY_ENV_VAR = "ROLEMAP_RESUME_OUTPUT_DIR"


@dataclass(frozen=True)
class ResumeGenerationResult:
    output_dir: Path
    instruction_dir: Path
    job_description_path: Path
    prompt_path: Path
    result_html_path: Path
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

    output_dir = _next_output_dir(_resume_output_root(base, env_source), row)
    output_dir.mkdir(parents=True, exist_ok=False)

    job_description_path = output_dir / "job-description.txt"
    job_description_path.write_text(_format_job_description(row), encoding="utf-8")

    result_html_path = output_dir / DEFAULT_RESULT_FILENAME
    prompt_path = output_dir / "tailoring-prompt.md"
    prompt_path.write_text(
        _format_prompt(row),
        encoding="utf-8",
    )

    return ResumeGenerationResult(
        output_dir=output_dir,
        instruction_dir=instruction_dir,
        job_description_path=job_description_path,
        prompt_path=prompt_path,
        result_html_path=result_html_path,
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
        **_result_environment(
            output_dir=result.output_dir,
            instruction_dir=result.instruction_dir,
        ),
    }
    cwd = result.instruction_dir.resolve()
    command = ["codex", "--cd", str(cwd), result.prompt_path.read_text(encoding="utf-8")]
    command_runner(command, cwd=cwd, env=run_env, check=True)


def _without_resume_environment(environ: Mapping[str, str]) -> dict[str, str]:
    return {
        name: value
        for name, value in environ.items()
        if not name.startswith("ROLEMAP_RESUME_")
    }


def _resume_output_root(base: Path, environ: Mapping[str, str]) -> Path:
    configured_directory = environ.get(OUTPUT_DIRECTORY_ENV_VAR, "").strip()
    if not configured_directory:
        return base / DEFAULT_OUTPUT_ROOT
    output_root = Path(configured_directory)
    if not output_root.is_absolute():
        output_root = base / output_root
    return output_root


def _next_output_dir(output_root: Path, row: JobRow) -> Path:
    timestamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    name = "-".join(
        part
        for part in (
            _row_text(row, "id"),
            _slug(_row_text(row, "company_name")),
            _slug(_row_text(row, "job_title")),
            timestamp,
        )
        if part
    )
    candidate = output_root / name
    suffix = 2
    while candidate.exists():
        candidate = output_root / f"{name}-{suffix}"
        suffix += 1
    return candidate


def _format_job_description(row: JobRow) -> str:
    fields = [
        ("Company", _row_text(row, "company_name")),
        ("Job title", _row_text(row, "job_title")),
        ("Publish date", _row_text(row, "publish_date")),
        ("URL", _row_text(row, "url")),
        ("Salary range", _row_text(row, "salary_range")),
    ]
    header = "\n".join(f"{label}: {value}" for label, value in fields if value)
    return f"{header}\n\nDescription:\n{_row_text(row, 'job_description')}\n"


def _format_prompt(row: JobRow) -> str:
    return (
        "Please generate the resume for this job:\n"
        f"Company: {_row_text(row, 'company_name')}\n"
        f"Title: {_row_text(row, 'job_title')}\n"
        f"Description: {_row_text(row, 'job_description')}\n"
    )


def _result_environment(
    *,
    output_dir: Path,
    instruction_dir: Path,
) -> dict[str, str]:
    return {
        TEMPLATE_DIRECTORY_ENV_VAR: str(instruction_dir),
        "ROLEMAP_RESUME_OUTPUT_DIR": str(output_dir),
    }


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


def _slug(value: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    return text[:80]
