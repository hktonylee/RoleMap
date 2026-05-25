from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import sqlite3
from typing import Protocol, TypeAlias
from urllib.parse import urlparse


class JobRow(Protocol):
    def __getitem__(self, key: str) -> object: ...


JobRows: TypeAlias = list[sqlite3.Row]
_JOB_LIST_ORDER = "is_expired ASC, publish_date DESC, id DESC"


@dataclass(frozen=True)
class JobInput:
    publish_date: str = ""
    job_title: str = ""
    company_name: str = ""
    description: str = ""
    url: str = ""
    salary_range: str = ""
    is_expired: bool | None = None

    @classmethod
    def from_mapping(cls, data: dict[str, object]) -> "JobInput":
        return cls(
            publish_date=_text(data.get("publish_date")),
            job_title=_text(data.get("job_title")),
            company_name=_text(data.get("company_name")),
            description=_text(data.get("description")),
            url=_text(data.get("url")),
            salary_range=_text(data.get("salary_range")),
            is_expired=_optional_bool(data.get("is_expired")),
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
                    is_expired,
                    last_update,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    validated.publish_date,
                    validated.job_title,
                    validated.company_name,
                    validated.description,
                    _nullable(validated.url),
                    validated.salary_range,
                    _stored_bool(validated.is_expired),
                    now,
                    now,
                ),
            )
            self.connection.commit()
            if cursor.lastrowid is None:
                raise sqlite3.DatabaseError("failed to read inserted job id")
            return cursor.lastrowid

        self.connection.execute(
            """
            UPDATE jobs
            SET publish_date = ?,
                job_title = ?,
                company_name = ?,
                description = ?,
                url = ?,
                salary_range = ?,
                is_expired = COALESCE(?, is_expired),
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
                _stored_optional_bool(validated.is_expired),
                now,
                existing_id,
            ),
        )
        self.connection.commit()
        return existing_id

    def toggle_expired(self, job_id: int) -> bool:
        row = self.get(job_id)
        if row is None:
            raise ValueError(f"Job not found: {job_id}")

        is_expired = not _stored_bool(row["is_expired"])
        self.connection.execute(
            """
            UPDATE jobs
            SET is_expired = ?,
                last_update = ?
            WHERE id = ?
            """,
            (_stored_bool(is_expired), _local_timestamp(), job_id),
        )
        self.connection.commit()
        return is_expired

    def get(self, job_id: int) -> sqlite3.Row | None:
        return self.connection.execute(
            "SELECT * FROM jobs WHERE id = ?",
            (job_id,),
        ).fetchone()

    def update_description(self, job_id: int, description: str) -> None:
        normalized = description.strip()
        if not normalized:
            raise ValueError("description must not be empty")

        cursor = self.connection.execute(
            """
            UPDATE jobs
            SET description = ?,
                last_update = ?
            WHERE id = ?
            """,
            (normalized, _local_timestamp(), job_id),
        )
        if cursor.rowcount == 0:
            raise ValueError(f"Job not found: {job_id}")
        self.connection.commit()

    def update_salary_range(self, job_id: int, salary_range: str) -> None:
        normalized = salary_range.strip()
        if not normalized:
            raise ValueError("salary_range must not be empty")

        cursor = self.connection.execute(
            """
            UPDATE jobs
            SET salary_range = ?,
                last_update = ?
            WHERE id = ?
            """,
            (normalized, _local_timestamp(), job_id),
        )
        if cursor.rowcount == 0:
            raise ValueError(f"Job not found: {job_id}")
        self.connection.commit()

    def list(self) -> JobRows:
        return list(
            self.connection.execute(
                f"""
                SELECT * FROM jobs
                ORDER BY {_JOB_LIST_ORDER}
                """
            ).fetchall()
        )

    def search(self, query: str) -> JobRows:
        needle = query.strip()
        if not needle:
            return self.list()

        pattern = f"%{needle}%"
        return list(
            self.connection.execute(
                f"""
                SELECT * FROM jobs
                WHERE publish_date LIKE ? COLLATE NOCASE
                   OR job_title LIKE ? COLLATE NOCASE
                   OR company_name LIKE ? COLLATE NOCASE
                   OR description LIKE ? COLLATE NOCASE
                   OR url LIKE ? COLLATE NOCASE
                   OR salary_range LIKE ? COLLATE NOCASE
                ORDER BY {_JOB_LIST_ORDER}
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
        is_expired=job.is_expired,
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
    if _is_gmail_url(normalized.url):
        raise ValueError("url must be the job posting URL, not a Gmail thread URL")
    return normalized


def _local_timestamp() -> str:
    return datetime.now().astimezone().replace(microsecond=0).isoformat()


def _nullable(value: str) -> str | None:
    return value or None


def _stored_bool(value: object) -> int:
    return 1 if bool(value) else 0


def _stored_optional_bool(value: bool | None) -> int | None:
    if value is None:
        return None
    return _stored_bool(value)


def _optional_bool(value: object) -> bool | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().casefold()
        if normalized in {"1", "true", "yes"}:
            return True
        if normalized in {"0", "false", "no"}:
            return False
    raise ValueError("is_expired must be a boolean")


def _text(value: object) -> str:
    if value is None:
        return ""
    return str(value)


def _is_gmail_url(value: str) -> bool:
    if not value:
        return False
    parsed = urlparse(value)
    return parsed.netloc.lower() in {"mail.google.com", "gmail.com"}
