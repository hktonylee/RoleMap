from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import sqlite3


@dataclass(frozen=True)
class JobInput:
    publish_date: str = ""
    job_title: str = ""
    company_name: str = ""
    description: str = ""
    url: str = ""
    salary_range: str = ""

    @classmethod
    def from_mapping(cls, data: dict[str, object]) -> "JobInput":
        return cls(
            publish_date=_text(data.get("publish_date")),
            job_title=_text(data.get("job_title")),
            company_name=_text(data.get("company_name")),
            description=_text(data.get("description")),
            url=_text(data.get("url")),
            salary_range=_text(data.get("salary_range")),
        )


class JobRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def add_or_update(self, job: JobInput) -> int:
        validated = _validate(job)
        now = _local_timestamp()
        existing_id = self._find_existing_id(validated.url)

        if existing_id is None:
            cursor = self.connection.execute(
                """
                INSERT INTO jobs (
                    publish_date,
                    job_title,
                    company_name,
                    description,
                    url,
                    salary_range,
                    last_update,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    validated.publish_date,
                    validated.job_title,
                    validated.company_name,
                    validated.description,
                    _nullable(validated.url),
                    validated.salary_range,
                    now,
                    now,
                ),
            )
            self.connection.commit()
            return int(cursor.lastrowid)

        self.connection.execute(
            """
            UPDATE jobs
            SET publish_date = ?,
                job_title = ?,
                company_name = ?,
                description = ?,
                url = ?,
                salary_range = ?,
                last_update = ?
            WHERE id = ?
            """,
            (
                validated.publish_date,
                validated.job_title,
                validated.company_name,
                validated.description,
                _nullable(validated.url),
                validated.salary_range,
                now,
                existing_id,
            ),
        )
        self.connection.commit()
        return existing_id

    def get(self, job_id: int) -> sqlite3.Row | None:
        return self.connection.execute(
            "SELECT * FROM jobs WHERE id = ?",
            (job_id,),
        ).fetchone()

    def list(self) -> list[sqlite3.Row]:
        return list(
            self.connection.execute(
                """
                SELECT * FROM jobs
                ORDER BY last_update DESC, id DESC
                """
            ).fetchall()
        )

    def search(self, query: str) -> list[sqlite3.Row]:
        needle = query.strip()
        if not needle:
            return self.list()

        pattern = f"%{needle}%"
        return list(
            self.connection.execute(
                """
                SELECT * FROM jobs
                WHERE publish_date LIKE ? COLLATE NOCASE
                   OR job_title LIKE ? COLLATE NOCASE
                   OR company_name LIKE ? COLLATE NOCASE
                   OR description LIKE ? COLLATE NOCASE
                   OR url LIKE ? COLLATE NOCASE
                   OR salary_range LIKE ? COLLATE NOCASE
                ORDER BY last_update DESC, id DESC
                """,
                (pattern, pattern, pattern, pattern, pattern, pattern),
            ).fetchall()
        )

    def _find_existing_id(self, url: str) -> int | None:
        if not url:
            return None
        row = self.connection.execute(
            "SELECT id FROM jobs WHERE url = ?",
            (url,),
        ).fetchone()
        if row is None:
            return None
        return int(row["id"])


def _validate(job: JobInput) -> JobInput:
    normalized = JobInput(
        publish_date=job.publish_date.strip(),
        job_title=job.job_title.strip(),
        company_name=job.company_name.strip(),
        description=job.description.strip(),
        url=job.url.strip(),
        salary_range=job.salary_range.strip(),
    )
    missing = [
        name
        for name, value in (
            ("job_title", normalized.job_title),
            ("company_name", normalized.company_name),
            ("description", normalized.description),
        )
        if not value
    ]
    if missing:
        raise ValueError(f"Missing required job fields: {', '.join(missing)}")
    return normalized


def _local_timestamp() -> str:
    return datetime.now().astimezone().replace(microsecond=0).isoformat()


def _nullable(value: str) -> str | None:
    return value or None


def _text(value: object) -> str:
    if value is None:
        return ""
    return str(value)
