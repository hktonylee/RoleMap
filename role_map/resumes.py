from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess

from role_map.jobs import JobRow


TEMPLATE_DIRECTORIES = ("resume_templates", "templates")
DEFAULT_OUTPUT_ROOT = Path("generated") / "resumes"
DEFAULT_RESULT_FILENAME = "tailored-resume.html"
GENERATOR_ENV_VAR = "ROLEMAP_RESUME_GENERATOR"
TEMPLATE_DIRECTORY_ENV_VAR = "ROLEMAP_RESUME_TEMPLATE_DIR"
DESTINATION_DIRECTORY_ENV_VAR = "ROLEMAPE_RESUME_DESTINATION_DIR"


@dataclass(frozen=True)
class ResumeTemplate:
    path: Path
    display_name: str


@dataclass(frozen=True)
class ResumeGenerationResult:
    output_dir: Path
    template_path: Path
    template_copy_path: Path
    job_description_path: Path
    prompt_path: Path
    result_html_path: Path
    command_ran: bool


def discover_templates(root: str | Path = ".") -> list[ResumeTemplate]:
    base = Path(root)
    templates: list[ResumeTemplate] = []
    template_directories: list[tuple[Path, Path]] = []
    environment_directory = os.environ.get(TEMPLATE_DIRECTORY_ENV_VAR, "").strip()
    if environment_directory:
        directory = Path(environment_directory)
        if not directory.is_absolute():
            directory = base / directory
        template_directories.append((directory, directory))
    template_directories.extend((base / directory_name, base) for directory_name in TEMPLATE_DIRECTORIES)
    for directory, display_base in template_directories:
        if not directory.is_dir():
            continue
        for path in sorted(directory.rglob("*")):
            relative_path = path.relative_to(display_base)
            if path.is_file() and not _has_hidden_part(relative_path):
                templates.append(
                    ResumeTemplate(
                        path=path,
                        display_name=relative_path.as_posix(),
                    )
                )
    return sorted(templates, key=lambda template: template.display_name.casefold())


def generate_resume(
    row: JobRow,
    template: ResumeTemplate | str | Path,
    *,
    root: str | Path = ".",
    environ: Mapping[str, str] | None = None,
    run_command: bool = True,
) -> ResumeGenerationResult:
    base = Path(root)
    env_source = dict(os.environ if environ is None else environ)
    source_template = _template_path(template)
    if not source_template.is_absolute():
        source_template = base / source_template
    if not source_template.is_file():
        raise FileNotFoundError(f"resume template not found: {source_template}")

    output_dir = _next_output_dir(_resume_output_root(base, env_source), row)
    output_dir.mkdir(parents=True, exist_ok=False)

    template_copy_path = output_dir / source_template.name
    shutil.copy2(source_template, template_copy_path)

    job_description_path = output_dir / "job-description.txt"
    job_description_path.write_text(_format_job_description(row), encoding="utf-8")

    result_html_path = output_dir / DEFAULT_RESULT_FILENAME
    prompt_path = output_dir / "tailoring-prompt.md"
    prompt_path.write_text(
        _format_prompt(row),
        encoding="utf-8",
    )

    command = env_source.get(GENERATOR_ENV_VAR, "").strip()
    if run_command and command:
        run_env = {
            **env_source,
            **_result_environment(
                output_dir=output_dir,
                source_template=source_template,
                template_copy_path=template_copy_path,
                prompt_path=prompt_path,
                job_description_path=job_description_path,
                result_html_path=result_html_path,
            ),
        }
        subprocess.run(shlex.split(command), cwd=output_dir, env=run_env, check=True)

    return ResumeGenerationResult(
        output_dir=output_dir,
        template_path=source_template,
        template_copy_path=template_copy_path,
        job_description_path=job_description_path,
        prompt_path=prompt_path,
        result_html_path=result_html_path,
        command_ran=bool(run_command and command),
    )


def run_resume_generator(
    result: ResumeGenerationResult,
    *,
    environ: Mapping[str, str] | None = None,
    command_runner=subprocess.run,
) -> None:
    env_source = dict(os.environ if environ is None else environ)
    run_env = {
        **env_source,
        **_result_environment(
            output_dir=result.output_dir,
            source_template=result.template_path,
            template_copy_path=result.template_copy_path,
            prompt_path=result.prompt_path,
            job_description_path=result.job_description_path,
            result_html_path=result.result_html_path,
        ),
    }
    configured_command = env_source.get(GENERATOR_ENV_VAR, "").strip()
    if configured_command:
        command = shlex.split(configured_command)
        cwd = result.output_dir
    else:
        cwd = result.template_path.parent.resolve()
        command = ["codex", "--cd", str(cwd), result.prompt_path.read_text(encoding="utf-8")]
    command_runner(command, cwd=cwd, env=run_env, check=True)


def _resume_output_root(base: Path, environ: Mapping[str, str]) -> Path:
    configured_directory = environ.get(DESTINATION_DIRECTORY_ENV_VAR, "").strip()
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
    return f"{header}\n\nDescription:\n{_row_text(row, 'description')}\n"


def _format_prompt(row: JobRow) -> str:
    return (
        "Please generate the resume for this job:\n"
        f"Company: {_row_text(row, 'company_name')}\n"
        f"Title: {_row_text(row, 'job_title')}\n"
        f"Description: {_row_text(row, 'description')}\n"
    )


def _result_environment(
    *,
    output_dir: Path,
    source_template: Path,
    template_copy_path: Path,
    prompt_path: Path,
    job_description_path: Path,
    result_html_path: Path,
) -> dict[str, str]:
    return {
        "ROLEMAP_RESUME_TEMPLATE": str(source_template),
        "ROLEMAP_RESUME_TEMPLATE_COPY": str(template_copy_path),
        "ROLEMAP_RESUME_PROMPT": str(prompt_path),
        "ROLEMAP_RESUME_JOB_DESCRIPTION": str(job_description_path),
        "ROLEMAP_RESUME_OUTPUT_DIR": str(output_dir),
        "ROLEMAP_RESUME_RESULT_HTML": str(result_html_path),
    }


def _template_path(template: ResumeTemplate | str | Path) -> Path:
    if isinstance(template, ResumeTemplate):
        return template.path
    return Path(template)


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


def _has_hidden_part(path: Path) -> bool:
    return any(part.startswith(".") for part in path.parts)
