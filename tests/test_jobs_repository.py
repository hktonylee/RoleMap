import sqlite3
import tempfile
import unittest
from pathlib import Path

from role_map.db import connect, initialize_database
from role_map.jobs import JobInput, JobRepository


class JobRepositoryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.db_path = Path(self.temp_dir.name) / "rolemap.sqlite3"
        self.connection = connect(self.db_path)
        self.addCleanup(self.connection.close)
        initialize_database(self.connection)
        self.repository = JobRepository(self.connection)

    def test_schema_includes_required_job_columns(self) -> None:
        columns = {
            row["name"]
            for row in self.connection.execute("PRAGMA table_info(jobs)").fetchall()
        }

        self.assertGreaterEqual(
            columns,
            {
                "publish_date",
                "job_title",
                "company_name",
                "job_description",
                "url",
                "salary_range",
                "is_starred",
                "is_expired",
                "is_pruned",
                "last_update",
                "created",
            },
        )
        self.assertNotIn("description", columns)

    def test_add_job_writes_fields_and_local_timestamps(self) -> None:
        job_id = self.repository.add_or_update(
            JobInput(
                publish_date="2026-05-20",
                job_title="Senior Software Engineer",
                company_name="Example Systems",
                job_description="Build internal systems and tooling.",
                url="https://example.com/jobs/123",
                salary_range="$150k-$190k",
            )
        )

        row = self.repository.get(job_id)

        self.assertIsNotNone(row)
        self.assertEqual(row["publish_date"], "2026-05-20")
        self.assertEqual(row["job_title"], "Senior Software Engineer")
        self.assertEqual(row["company_name"], "Example Systems")
        self.assertEqual(row["job_description"], "Build internal systems and tooling.")
        self.assertEqual(row["url"], "https://example.com/jobs/123")
        self.assertEqual(row["salary_range"], "$150k-$190k")
        self.assertEqual(row["is_starred"], 0)
        self.assertEqual(row["is_expired"], 0)
        self.assertEqual(row["is_pruned"], 0)
        self.assertRegex(row["last_update"], r"^\d{4}-\d{2}-\d{2}T")
        self.assertRegex(row["created"], r"^\d{4}-\d{2}-\d{2}T")
        self.assertRegex(row["created_at"], r"^\d{4}-\d{2}-\d{2}T")

    def test_toggle_starred_updates_local_flag(self) -> None:
        job_id = self.repository.add_or_update(
            JobInput(
                publish_date="2026-05-20",
                job_title="Senior Software Engineer",
                company_name="Example Systems",
                job_description="Build internal systems and tooling.",
                url="https://example.com/jobs/123",
                salary_range="$150k-$190k",
            )
        )

        first_value = self.repository.toggle_starred(job_id)
        second_value = self.repository.toggle_starred(job_id)

        self.assertTrue(first_value)
        self.assertFalse(second_value)
        self.assertEqual(self.repository.get(job_id)["is_starred"], 0)

    def test_toggle_expired_updates_local_flag(self) -> None:
        job_id = self.repository.add_or_update(
            JobInput(
                publish_date="2026-05-20",
                job_title="Senior Software Engineer",
                company_name="Example Systems",
                job_description="Build internal systems and tooling.",
                url="https://example.com/jobs/123",
                salary_range="$150k-$190k",
            )
        )

        first_value = self.repository.toggle_expired(job_id)
        second_value = self.repository.toggle_expired(job_id)

        self.assertTrue(first_value)
        self.assertFalse(second_value)
        self.assertEqual(self.repository.get(job_id)["is_expired"], 0)

    def test_prune_expired_marks_all_expired_jobs_pruned(self) -> None:
        active_id = self.repository.add_or_update(
            JobInput(
                publish_date="2026-05-20",
                job_title="Active Engineer",
                company_name="Example Systems",
                job_description="Build active systems.",
            )
        )
        expired_id = self.repository.add_or_update(
            JobInput(
                publish_date="2026-05-21",
                job_title="Expired Engineer",
                company_name="Example Systems",
                job_description="Build expired systems.",
                is_expired=True,
            )
        )
        already_pruned_id = self.repository.add_or_update(
            JobInput(
                publish_date="2026-05-22",
                job_title="Pruned Engineer",
                company_name="Example Systems",
                job_description="Build pruned systems.",
                is_expired=True,
                is_pruned=True,
            )
        )

        pruned_count = self.repository.prune_expired()

        self.assertEqual(pruned_count, 1)
        self.assertEqual(self.repository.get(active_id)["is_pruned"], 0)
        self.assertEqual(self.repository.get(expired_id)["is_pruned"], 1)
        self.assertEqual(self.repository.get(already_pruned_id)["is_pruned"], 1)

    def test_same_url_updates_existing_job(self) -> None:
        first_id = self.repository.add_or_update(
            JobInput(
                publish_date="2026-05-20",
                job_title="Backend Engineer",
                company_name="Example Systems",
                job_description="Original description.",
                url="https://example.com/jobs/456",
                salary_range="$140k-$170k",
            )
        )
        second_id = self.repository.add_or_update(
            JobInput(
                publish_date="2026-05-21",
                job_title="Backend Engineer, Platform",
                company_name="Example Systems",
                job_description="Updated description with platform ownership.",
                url="https://example.com/jobs/456",
                salary_range="$145k-$175k",
            )
        )

        rows = self.repository.list()

        self.assertEqual(first_id, second_id)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["publish_date"], "2026-05-21")
        self.assertEqual(rows[0]["job_title"], "Backend Engineer, Platform")
        self.assertIn("platform ownership", rows[0]["job_description"])

    def test_same_url_preserves_created_timestamp(self) -> None:
        first_id = self.repository.add_or_update(
            JobInput(
                publish_date="2026-05-20",
                job_title="Backend Engineer",
                company_name="Example Systems",
                job_description="Original description.",
                url="https://example.com/jobs/456",
                salary_range="$140k-$170k",
            )
        )
        self.connection.execute(
            "UPDATE jobs SET last_update = ?, created = ? WHERE id = ?",
            (
                "2026-05-30T12:00:00-07:00",
                "2026-05-24T12:20:01-07:00",
                first_id,
            ),
        )
        self.connection.commit()

        second_id = self.repository.add_or_update(
            JobInput(
                publish_date="2026-05-21",
                job_title="Backend Engineer, Platform",
                company_name="Example Systems",
                job_description="Updated description.",
                url="https://example.com/jobs/456",
                salary_range="$145k-$175k",
            )
        )

        row = self.repository.get(second_id)
        self.assertEqual(first_id, second_id)
        self.assertEqual(row["created"], "2026-05-24T12:20:01-07:00")
        self.assertNotEqual(row["last_update"], "2026-05-30T12:00:00-07:00")

    def test_list_orders_by_publish_date_desc_then_job_id_desc(self) -> None:
        oldest_id = self.repository.add_or_update(
            JobInput(
                publish_date="2026-05-20",
                job_title="Old Engineer",
                company_name="Old Systems",
                job_description="Build old systems.",
            )
        )
        newest_first_id = self.repository.add_or_update(
            JobInput(
                publish_date="2026-05-25",
                job_title="First New Engineer",
                company_name="New Systems",
                job_description="Build new systems.",
            )
        )
        newest_second_id = self.repository.add_or_update(
            JobInput(
                publish_date="2026-05-25",
                job_title="Second New Engineer",
                company_name="New Systems",
                job_description="Build newer systems.",
            )
        )
        self.connection.execute(
            "UPDATE jobs SET last_update = ? WHERE id = ?",
            ("2026-05-30T12:00:00-07:00", oldest_id),
        )
        self.connection.commit()

        rows = self.repository.list()

        self.assertEqual(
            [row["id"] for row in rows],
            [newest_second_id, newest_first_id, oldest_id],
        )

    def test_list_orders_expired_jobs_after_active_jobs(self) -> None:
        active_old_id = self.repository.add_or_update(
            JobInput(
                publish_date="2026-05-20",
                job_title="Active Old Engineer",
                company_name="Example Systems",
                job_description="Build active old systems.",
            )
        )
        expired_new_id = self.repository.add_or_update(
            JobInput(
                publish_date="2026-05-25",
                job_title="Expired New Engineer",
                company_name="Example Systems",
                job_description="Build expired new systems.",
                is_expired=True,
            )
        )
        active_new_id = self.repository.add_or_update(
            JobInput(
                publish_date="2026-05-22",
                job_title="Active New Engineer",
                company_name="Example Systems",
                job_description="Build active new systems.",
            )
        )
        expired_old_id = self.repository.add_or_update(
            JobInput(
                publish_date="2026-05-21",
                job_title="Expired Old Engineer",
                company_name="Example Systems",
                job_description="Build expired old systems.",
                is_expired=True,
            )
        )

        rows = self.repository.list()

        self.assertEqual(
            [row["id"] for row in rows],
            [active_new_id, active_old_id, expired_new_id, expired_old_id],
        )

    def test_search_orders_by_publish_date_desc_then_job_id_desc(self) -> None:
        oldest_id = self.repository.add_or_update(
            JobInput(
                publish_date="2026-05-20",
                job_title="Old Engineer",
                company_name="Example Systems",
                job_description="Build shared systems.",
            )
        )
        newest_first_id = self.repository.add_or_update(
            JobInput(
                publish_date="2026-05-25",
                job_title="First New Engineer",
                company_name="Example Systems",
                job_description="Build shared systems.",
            )
        )
        newest_second_id = self.repository.add_or_update(
            JobInput(
                publish_date="2026-05-25",
                job_title="Second New Engineer",
                company_name="Example Systems",
                job_description="Build shared systems.",
            )
        )
        self.connection.execute(
            "UPDATE jobs SET last_update = ? WHERE id = ?",
            ("2026-05-30T12:00:00-07:00", oldest_id),
        )
        self.connection.commit()

        rows = self.repository.search("Example Systems")

        self.assertEqual(
            [row["id"] for row in rows],
            [newest_second_id, newest_first_id, oldest_id],
        )

    def test_search_orders_expired_jobs_after_active_jobs(self) -> None:
        active_old_id = self.repository.add_or_update(
            JobInput(
                publish_date="2026-05-20",
                job_title="Active Old Engineer",
                company_name="Example Systems",
                job_description="Build shared systems.",
            )
        )
        expired_new_id = self.repository.add_or_update(
            JobInput(
                publish_date="2026-05-25",
                job_title="Expired New Engineer",
                company_name="Example Systems",
                job_description="Build shared systems.",
                is_expired=True,
            )
        )
        active_new_id = self.repository.add_or_update(
            JobInput(
                publish_date="2026-05-22",
                job_title="Active New Engineer",
                company_name="Example Systems",
                job_description="Build shared systems.",
            )
        )
        expired_old_id = self.repository.add_or_update(
            JobInput(
                publish_date="2026-05-21",
                job_title="Expired Old Engineer",
                company_name="Example Systems",
                job_description="Build shared systems.",
                is_expired=True,
            )
        )

        rows = self.repository.search("shared systems")

        self.assertEqual(
            [row["id"] for row in rows],
            [active_new_id, active_old_id, expired_new_id, expired_old_id],
        )

    def test_list_omits_pruned_jobs(self) -> None:
        active_id = self.repository.add_or_update(
            JobInput(
                publish_date="2026-05-22",
                job_title="Active Engineer",
                company_name="Example Systems",
                job_description="Build active systems.",
            )
        )
        self.repository.add_or_update(
            JobInput(
                publish_date="2026-05-25",
                job_title="Pruned Engineer",
                company_name="Example Systems",
                job_description="Build pruned systems.",
                is_pruned=True,
            )
        )

        rows = self.repository.list()

        self.assertEqual([row["id"] for row in rows], [active_id])

    def test_search_omits_pruned_jobs(self) -> None:
        active_id = self.repository.add_or_update(
            JobInput(
                publish_date="2026-05-22",
                job_title="Active Engineer",
                company_name="Example Systems",
                job_description="Build shared systems.",
            )
        )
        self.repository.add_or_update(
            JobInput(
                publish_date="2026-05-25",
                job_title="Pruned Engineer",
                company_name="Example Systems",
                job_description="Build shared systems.",
                is_pruned=True,
            )
        )

        rows = self.repository.search("shared systems")

        self.assertEqual([row["id"] for row in rows], [active_id])

    def test_search_matches_core_job_fields(self) -> None:
        self.repository.add_or_update(
            JobInput(
                publish_date="2026-05-20",
                job_title="Infrastructure Engineer",
                company_name="Northstar",
                job_description="Own deployment automation.",
                url="https://northstar.example/jobs/infra",
                salary_range="$160k-$200k",
            )
        )
        self.repository.add_or_update(
            JobInput(
                publish_date="2026-05-22",
                job_title="Product Engineer",
                company_name="Southline",
                job_description="Build customer-facing workflows.",
                url="https://southline.example/jobs/product",
                salary_range="$120k-$150k",
            )
        )

        self.assertEqual(
            [row["company_name"] for row in self.repository.search("automation")],
            ["Northstar"],
        )
        self.assertEqual(
            [row["job_title"] for row in self.repository.search("southline")],
            ["Product Engineer"],
        )
        self.assertEqual(
            [row["job_title"] for row in self.repository.search("$160k")],
            ["Infrastructure Engineer"],
        )

    def test_validation_rejects_missing_required_text(self) -> None:
        with self.assertRaises(ValueError):
            self.repository.add_or_update(
                JobInput(
                    publish_date="2026-05-20",
                    job_title="",
                    company_name="Example Systems",
                    job_description="Build things.",
                    url="https://example.com/jobs/789",
                    salary_range="",
                )
            )

    def test_validation_rejects_gmail_thread_url(self) -> None:
        with self.assertRaisesRegex(ValueError, "url must be the job posting URL"):
            self.repository.add_or_update(
                JobInput(
                    publish_date="2026-05-24",
                    job_title="Application and Product Security Principal",
                    company_name="Global Relay",
                    job_description="Source: Indeed job alert email.",
                    url="https://mail.google.com/mail/#all/19e5a1eac3590391",
                    salary_range="$125,000 - $160,000 a year",
                )
            )


class DatabaseConnectionTest(unittest.TestCase):
    def test_connect_returns_sqlite_rows_by_name(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            connection = connect(Path(temp_dir) / "rolemap.sqlite3")
            self.addCleanup(connection.close)

            connection.execute("CREATE TABLE sample (name TEXT)")
            connection.execute("INSERT INTO sample (name) VALUES (?)", ("ok",))
            row = connection.execute("SELECT name FROM sample").fetchone()

        self.assertIsInstance(row, sqlite3.Row)
        self.assertEqual(row["name"], "ok")

    def test_initialize_database_migrates_existing_jobs_to_is_starred_is_expired_is_pruned_and_created(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            connection = connect(Path(temp_dir) / "rolemap.sqlite3")
            self.addCleanup(connection.close)
            connection.executescript(
                """
                CREATE TABLE jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    publish_date TEXT,
                    job_title TEXT NOT NULL,
                    company_name TEXT NOT NULL,
                    description TEXT NOT NULL,
                    url TEXT UNIQUE,
                    salary_range TEXT,
                    last_update TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
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
                VALUES (
                    '2026-05-20',
                    'Senior Software Engineer',
                    'Example Systems',
                    'Build internal systems and tooling.',
                    'https://example.com/jobs/123',
                    '$150k-$190k',
                    '2026-05-24T12:20:01-07:00',
                    '2026-05-24T12:20:01-07:00'
                );
                PRAGMA user_version = 1;
                """
            )

            initialize_database(connection)
            row = connection.execute(
                "SELECT is_starred, is_expired, is_pruned, created FROM jobs"
            ).fetchone()
            version = connection.execute("PRAGMA user_version").fetchone()[0]

        self.assertEqual(row["is_starred"], 0)
        self.assertEqual(row["is_expired"], 0)
        self.assertEqual(row["is_pruned"], 0)
        self.assertEqual(row["created"], "2026-05-24T12:20:01-07:00")
        self.assertEqual(version, 6)

    def test_initialize_database_renames_existing_description_column(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            connection = connect(Path(temp_dir) / "rolemap.sqlite3")
            self.addCleanup(connection.close)
            connection.executescript(
                """
                CREATE TABLE jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    publish_date TEXT,
                    job_title TEXT NOT NULL,
                    company_name TEXT NOT NULL,
                    description TEXT NOT NULL,
                    url TEXT UNIQUE,
                    salary_range TEXT,
                    is_starred INTEGER NOT NULL DEFAULT 0,
                    is_expired INTEGER NOT NULL DEFAULT 0,
                    is_pruned INTEGER NOT NULL DEFAULT 0,
                    last_update TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
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
                VALUES (
                    '2026-05-20',
                    'Senior Software Engineer',
                    'Example Systems',
                    'Build internal systems and tooling.',
                    'https://example.com/jobs/123',
                    '$150k-$190k',
                    '2026-05-24T12:20:01-07:00',
                    '2026-05-24T12:20:01-07:00'
                );
                PRAGMA user_version = 4;
                """
            )

            initialize_database(connection)
            columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(jobs)").fetchall()
            }
            row = connection.execute(
                "SELECT job_description FROM jobs"
            ).fetchone()

        self.assertIn("job_description", columns)
        self.assertNotIn("description", columns)
        self.assertEqual(row["job_description"], "Build internal systems and tooling.")


if __name__ == "__main__":
    unittest.main()
