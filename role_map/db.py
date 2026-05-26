from __future__ import annotations

import sqlite3
from pathlib import Path


SCHEMA_VERSION = 5


def connect(path: str | Path) -> sqlite3.Connection:
    db_path = Path(path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def initialize_database(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            publish_date TEXT,
            job_title TEXT NOT NULL,
            company_name TEXT NOT NULL,
            job_description TEXT NOT NULL,
            url TEXT UNIQUE,
            salary_range TEXT,
            is_starred INTEGER NOT NULL DEFAULT 0,
            is_expired INTEGER NOT NULL DEFAULT 0,
            is_pruned INTEGER NOT NULL DEFAULT 0,
            last_update TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_jobs_company_title
            ON jobs (company_name, job_title);

        CREATE INDEX IF NOT EXISTS idx_jobs_last_update
            ON jobs (last_update);
        """
    )
    _migrate_jobs(connection)
    connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    connection.commit()


def _migrate_jobs(connection: sqlite3.Connection) -> None:
    columns = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(jobs)").fetchall()
    }
    if "description" in columns and "job_description" not in columns:
        connection.execute(
            "ALTER TABLE jobs RENAME COLUMN description TO job_description"
        )
    if "is_starred" not in columns:
        connection.execute(
            "ALTER TABLE jobs ADD COLUMN is_starred INTEGER NOT NULL DEFAULT 0"
        )
    if "is_expired" not in columns:
        connection.execute(
            "ALTER TABLE jobs ADD COLUMN is_expired INTEGER NOT NULL DEFAULT 0"
        )
    if "is_pruned" not in columns:
        connection.execute(
            "ALTER TABLE jobs ADD COLUMN is_pruned INTEGER NOT NULL DEFAULT 0"
        )
