from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sqlite3
import sys
from typing import Sequence
from urllib.parse import urlparse

from role_map.db import connect, initialize_database
from role_map.job_sources import (
    clean_source_description,
    extract_salary_range,
    fetch_source_job,
)
from role_map.jobs import JobInput, JobRepository


DEFAULT_DB_PATH = Path.home() / ".local" / "state" / "rolemap" / "rolemap.sqlite3"


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        db_path = _database_path(args.db)
        connection = connect(db_path)
        try:
            initialize_database(connection)
            repository = JobRepository(connection)
            return int(args.handler(args, repository))
        finally:
            connection.close()
    except (ValueError, OSError, sqlite3.Error, json.JSONDecodeError) as exc:
        print(f"rolemap: {exc}", file=sys.stderr)
        return 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rolemap")
    parser.add_argument("--db", help="SQLite database path")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="initialize the database")
    init_parser.set_defaults(handler=_handle_init)

    add_parser = subparsers.add_parser("add-job", help="add or update a job")
    add_parser.add_argument("--json", help="path to a JSON job object or array")
    add_parser.add_argument("--publish-date", default="")
    add_parser.add_argument("--title", dest="job_title", default="")
    add_parser.add_argument("--company", dest="company_name", default="")
    add_parser.add_argument("--job-description", default="")
    add_parser.add_argument("--job-description-file", default="")
    add_parser.add_argument("--url", default="")
    add_parser.add_argument("--salary-range", default="")
    add_parser.set_defaults(handler=_handle_add_job)

    list_parser = subparsers.add_parser("list-jobs", help="list jobs")
    list_parser.add_argument("--query", default="")
    list_parser.set_defaults(handler=_handle_list_jobs)

    show_parser = subparsers.add_parser("show-job", help="show job details")
    show_parser.add_argument("id", type=int)
    show_parser.set_defaults(handler=_handle_show_job)

    backfill_parser = subparsers.add_parser(
        "backfill-descriptions",
        help="replace generated descriptions with text fetched from source URLs",
    )
    backfill_parser.add_argument("--dry-run", action="store_true")
    backfill_parser.add_argument("--limit", type=int, default=0)
    backfill_parser.add_argument("--min-length", type=int, default=120)
    backfill_parser.add_argument("--overwrite", action="store_true")
    backfill_parser.set_defaults(handler=_handle_backfill_descriptions)

    salary_parser = subparsers.add_parser(
        "backfill-salaries",
        help="fill missing salary ranges from saved descriptions or source URLs",
    )
    salary_parser.add_argument("--dry-run", action="store_true")
    salary_parser.add_argument("--limit", type=int, default=0)
    salary_parser.add_argument("--overwrite", action="store_true")
    salary_parser.add_argument("--source", choices=("indeed", "all"), default="indeed")
    salary_parser.add_argument(
        "--fetch",
        action="store_true",
        help="fetch source URLs when the saved description has no salary text",
    )
    salary_parser.set_defaults(handler=_handle_backfill_salaries)

    clean_parser = subparsers.add_parser(
        "clean-descriptions",
        help="remove source-site navigation text from stored descriptions",
    )
    clean_parser.add_argument("--dry-run", action="store_true")
    clean_parser.add_argument("--limit", type=int, default=0)
    clean_parser.add_argument("--min-length", type=int, default=120)
    clean_parser.set_defaults(handler=_handle_clean_descriptions)

    tui_parser = subparsers.add_parser("tui", help="open the interactive TUI")
    tui_parser.set_defaults(handler=_handle_tui)

    return parser


def _handle_init(args: argparse.Namespace, repository: JobRepository) -> int:
    del repository
    print(f"Initialized {Path(_database_path(args.db))}")
    return 0


def _handle_add_job(args: argparse.Namespace, repository: JobRepository) -> int:
    jobs = _load_jobs(args)
    ids = [repository.add_or_update(job) for job in jobs]
    for job_id in ids:
        print(job_id)
    return 0


def _handle_list_jobs(args: argparse.Namespace, repository: JobRepository) -> int:
    if _should_use_interactive_list():
        from role_map.tui import run

        run(repository, initial_query=args.query)
        return 0

    rows = repository.search(args.query) if args.query else repository.list()
    for row in rows:
        print(
            "\t".join(
                [
                    str(row["id"]),
                    row["publish_date"] or "",
                    row["company_name"],
                    row["job_title"],
                    row["salary_range"] or "",
                    row["url"] or "",
                    str(row["is_expired"] or 0),
                    row["last_update"],
                ]
            )
        )
    return 0


def _should_use_interactive_list() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def _handle_show_job(args: argparse.Namespace, repository: JobRepository) -> int:
    row = repository.get(args.id)
    if row is None:
        raise ValueError(f"Job not found: {args.id}")
    print(_format_job(row))
    return 0


def _handle_backfill_descriptions(args: argparse.Namespace, repository: JobRepository) -> int:
    attempted = 0
    updated = 0
    for row in repository.list():
        url = str(row["url"] or "")
        if not url:
            continue
        if not _looks_like_job_posting_url(url):
            print(
                f"skipped {row['id']}: source URL does not look like a job posting",
                file=sys.stderr,
            )
            continue
        if not args.overwrite and not _looks_generated_description(str(row["job_description"])):
            continue
        if args.limit and attempted >= args.limit:
            break

        attempted += 1
        try:
            source_job = fetch_source_job(url)
            description = source_job.description.strip()
        except OSError as exc:
            print(f"skipped {row['id']}: {exc}", file=sys.stderr)
            continue

        if len(description) < args.min_length:
            print(f"skipped {row['id']}: fetched description is too short", file=sys.stderr)
            continue

        if args.dry_run:
            preview = " ".join(description.split())[:160]
            print(f"{row['id']}\t{len(description)}\t{url}\t{preview}")
            continue

        repository.update_description(int(row["id"]), description)
        if source_job.salary_range and (args.overwrite or not row["salary_range"]):
            repository.update_salary_range(int(row["id"]), source_job.salary_range)
        updated += 1
        print(row["id"])

    print(f"Backfilled {updated} descriptions", file=sys.stderr)
    return 0


def _handle_backfill_salaries(args: argparse.Namespace, repository: JobRepository) -> int:
    attempted = 0
    updated = 0
    for row in repository.list():
        url = str(row["url"] or "")
        if getattr(args, "source", "indeed") == "indeed" and not _is_indeed_source(row):
            continue
        if row["salary_range"] and not args.overwrite:
            continue
        if args.limit and attempted >= args.limit:
            break
        attempted += 1

        salary_range = extract_salary_range(str(row["job_description"] or ""))
        source = "description"
        if not salary_range and args.fetch and url and _looks_like_job_posting_url(url):
            try:
                source_job = fetch_source_job(url)
            except OSError as exc:
                print(f"skipped {row['id']}: {exc}", file=sys.stderr)
                continue
            salary_range = source_job.salary_range
            source = "source"

        if not salary_range:
            continue

        if args.dry_run:
            print(f"{row['id']}\t{source}\t{salary_range}\t{url}")
            updated += 1
            continue

        repository.update_salary_range(int(row["id"]), salary_range)
        updated += 1
        print(row["id"])

    print(f"Backfilled {updated} salary ranges", file=sys.stderr)
    return 0


def _handle_clean_descriptions(args: argparse.Namespace, repository: JobRepository) -> int:
    updated = _clean_descriptions(args, repository)
    print(f"Cleaned {updated} descriptions", file=sys.stderr)
    return 0


def _clean_descriptions(args: argparse.Namespace, repository: JobRepository) -> int:
    updated = 0
    for row in repository.list():
        if args.limit and updated >= args.limit:
            break
        original = str(row["job_description"] or "")
        if _looks_generated_description(original):
            continue

        cleaned = clean_source_description(original)
        if cleaned == original.strip():
            continue
        if len(cleaned) < args.min_length:
            print(f"skipped {row['id']}: cleaned description is too short", file=sys.stderr)
            continue

        if args.dry_run:
            preview = " ".join(cleaned.split())[:160]
            print(f"{row['id']}\t{len(original)}\t{len(cleaned)}\t{preview}")
        else:
            repository.update_description(int(row["id"]), cleaned)
            print(row["id"])
        updated += 1
    return updated


def _handle_tui(args: argparse.Namespace, repository: JobRepository) -> int:
    del args
    from role_map.tui import run

    run(repository)
    return 0


def _database_path(value: str | None) -> Path:
    if value or os.environ.get("ROLEMAP_DB"):
        return Path(value or os.environ["ROLEMAP_DB"])
    if os.environ.get("XDG_STATE_HOME"):
        return Path(os.environ["XDG_STATE_HOME"]) / "rolemap" / "rolemap.sqlite3"
    return DEFAULT_DB_PATH


def _load_jobs(args: argparse.Namespace) -> list[JobInput]:
    if args.json:
        raw = json.loads(Path(args.json).read_text(encoding="utf-8"))
        items = raw if isinstance(raw, list) else [raw]
        if not all(isinstance(item, dict) for item in items):
            raise ValueError("JSON input must be an object or an array of objects")
        return [_with_extracted_salary(JobInput.from_mapping(item)) for item in items]

    job_description = args.job_description
    if args.job_description_file:
        job_description = Path(args.job_description_file).read_text(encoding="utf-8")

    return [
        _with_extracted_salary(
            JobInput(
                publish_date=args.publish_date,
                job_title=args.job_title,
                company_name=args.company_name,
                job_description=job_description,
                url=args.url,
                salary_range=args.salary_range,
            )
        )
    ]


def _with_extracted_salary(job: JobInput) -> JobInput:
    if job.salary_range or not _is_indeed_url(job.url):
        return job

    salary_range = extract_salary_range(job.job_description)
    if not salary_range:
        return job

    return JobInput(
        publish_date=job.publish_date,
        job_title=job.job_title,
        company_name=job.company_name,
        job_description=job.job_description,
        url=job.url,
        salary_range=salary_range,
        is_expired=job.is_expired,
        is_pruned=job.is_pruned,
    )


def _format_job(row: sqlite3.Row) -> str:
    fields = [
        ("ID", row["id"]),
        ("Publish date", row["publish_date"]),
        ("Job title", row["job_title"]),
        ("Company", row["company_name"]),
        ("URL", row["url"]),
        ("Salary range", row["salary_range"]),
        ("Expired", "yes" if row["is_expired"] else "no"),
        ("Last update", row["last_update"]),
        ("Created at", row["created_at"]),
        ("Description", row["job_description"]),
    ]
    return "\n".join(f"{label}: {value or ''}" for label, value in fields)


def _looks_generated_description(value: str) -> bool:
    return value.lstrip().startswith("Source: ")


def _looks_like_job_posting_url(value: str) -> bool:
    parsed = urlparse(value)
    host = parsed.netloc.lower()
    path = parsed.path.lower()

    if "indeed." in host:
        return path == "/viewjob"
    if "linkedin." in host:
        return path.startswith("/jobs/view/")
    if "glassdoor." in host:
        return path.startswith("/partner/joblisting") or path.startswith("/job-listing/")
    return True


def _is_indeed_url(value: str) -> bool:
    return "indeed." in urlparse(value).netloc.lower()


def _is_indeed_source(row: sqlite3.Row) -> bool:
    if _is_indeed_url(str(row["url"] or "")):
        return True
    description = str(row["job_description"] or "").lstrip().lower()
    return description.startswith("source: indeed")
