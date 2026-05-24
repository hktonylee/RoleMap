from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sqlite3
import sys
from typing import Sequence

from careerops.db import connect, initialize_database
from careerops.jobs import JobInput, JobRepository


DEFAULT_DB_PATH = Path("data") / "careerops.sqlite3"


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
        print(f"careerops: {exc}", file=sys.stderr)
        return 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="careerops")
    parser.add_argument("--db", help="SQLite database path")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="initialize the database")
    init_parser.set_defaults(handler=_handle_init)

    add_parser = subparsers.add_parser("add-job", help="add or update a job")
    add_parser.add_argument("--json", help="path to a JSON job object or array")
    add_parser.add_argument("--publish-date", default="")
    add_parser.add_argument("--title", dest="job_title", default="")
    add_parser.add_argument("--company", dest="company_name", default="")
    add_parser.add_argument("--description", default="")
    add_parser.add_argument("--description-file", default="")
    add_parser.add_argument("--url", default="")
    add_parser.add_argument("--salary-range", default="")
    add_parser.set_defaults(handler=_handle_add_job)

    list_parser = subparsers.add_parser("list-jobs", help="list jobs")
    list_parser.add_argument("--query", default="")
    list_parser.set_defaults(handler=_handle_list_jobs)

    show_parser = subparsers.add_parser("show-job", help="show job details")
    show_parser.add_argument("id", type=int)
    show_parser.set_defaults(handler=_handle_show_job)

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
        from careerops.tui import run

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


def _handle_tui(args: argparse.Namespace, repository: JobRepository) -> int:
    del args
    from careerops.tui import run

    run(repository)
    return 0


def _database_path(value: str | None) -> Path:
    return Path(value or os.environ.get("CAREEROPS_DB") or DEFAULT_DB_PATH)


def _load_jobs(args: argparse.Namespace) -> list[JobInput]:
    if args.json:
        raw = json.loads(Path(args.json).read_text(encoding="utf-8"))
        items = raw if isinstance(raw, list) else [raw]
        if not all(isinstance(item, dict) for item in items):
            raise ValueError("JSON input must be an object or an array of objects")
        return [JobInput.from_mapping(item) for item in items]

    description = args.description
    if args.description_file:
        description = Path(args.description_file).read_text(encoding="utf-8")

    return [
        JobInput(
            publish_date=args.publish_date,
            job_title=args.job_title,
            company_name=args.company_name,
            description=description,
            url=args.url,
            salary_range=args.salary_range,
        )
    ]


def _format_job(row: sqlite3.Row) -> str:
    fields = [
        ("ID", row["id"]),
        ("Publish date", row["publish_date"]),
        ("Job title", row["job_title"]),
        ("Company", row["company_name"]),
        ("URL", row["url"]),
        ("Salary range", row["salary_range"]),
        ("Last update", row["last_update"]),
        ("Created at", row["created_at"]),
        ("Description", row["description"]),
    ]
    return "\n".join(f"{label}: {value or ''}" for label, value in fields)
