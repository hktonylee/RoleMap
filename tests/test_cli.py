import argparse
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from careerops.cli import (
    _handle_backfill_descriptions,
    _handle_clean_descriptions,
    _handle_list_jobs,
)
from careerops.db import connect, initialize_database
from careerops.jobs import JobInput, JobRepository


class _TtyStringIO(io.StringIO):
    def isatty(self) -> bool:
        return True


class ListJobsCliTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.connection = connect(Path(self.temp_dir.name) / "careerops.sqlite3")
        self.addCleanup(self.connection.close)
        initialize_database(self.connection)
        self.repository = JobRepository(self.connection)
        self.repository.add_or_update(
            JobInput(
                publish_date="2026-05-24",
                job_title="Staff Engineer",
                company_name="Example Systems",
                description="Build internal tools.",
                url="https://example.com/jobs/staff",
                salary_range="$180k-$220k",
            )
        )

    def test_list_jobs_uses_interactive_browser_when_running_in_terminal(self) -> None:
        args = argparse.Namespace(query="systems")

        with (
            patch.object(sys, "stdin", _TtyStringIO()),
            patch.object(sys, "stdout", _TtyStringIO()),
            patch("careerops.tui.run") as run,
        ):
            exit_code = _handle_list_jobs(args, self.repository)

        self.assertEqual(exit_code, 0)
        run.assert_called_once_with(self.repository, initial_query="systems")

    def test_list_jobs_keeps_tabular_output_when_stdout_is_not_terminal(self) -> None:
        args = argparse.Namespace(query="")
        stdout = io.StringIO()

        with patch.object(sys, "stdout", stdout):
            exit_code = _handle_list_jobs(args, self.repository)

        self.assertEqual(exit_code, 0)
        self.assertIn(
            "Example Systems\tStaff Engineer\t$180k-$220k",
            stdout.getvalue(),
        )


class BackfillDescriptionsCliTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.connection = connect(Path(self.temp_dir.name) / "careerops.sqlite3")
        self.addCleanup(self.connection.close)
        initialize_database(self.connection)
        self.repository = JobRepository(self.connection)

    def test_backfill_updates_generated_description_from_source_url(self) -> None:
        generated_id = self.repository.add_or_update(
            JobInput(
                publish_date="2026-05-24",
                job_title="Staff Engineer",
                company_name="Example Systems",
                description="Source: LinkedIn Job Alert email. Email subject: Staff Engineer.",
                url="https://example.com/jobs/staff",
                salary_range="$180k-$220k",
            )
        )
        manual_id = self.repository.add_or_update(
            JobInput(
                publish_date="2026-05-24",
                job_title="Backend Engineer",
                company_name="Manual Systems",
                description="This is already the full source job description.",
                url="https://example.com/jobs/backend",
                salary_range="",
            )
        )
        search_page_id = self.repository.add_or_update(
            JobInput(
                publish_date="2026-05-24",
                job_title="Frontend Engineer",
                company_name="Search Result Systems",
                description="Source: Indeed job alert email. Email subject: Frontend Engineer.",
                url="https://ca.indeed.com/jobs?l=remote&q=frontend",
                salary_range="",
            )
        )
        args = argparse.Namespace(
            dry_run=False,
            limit=0,
            min_length=20,
            overwrite=False,
        )
        stdout = io.StringIO()
        stderr = io.StringIO()

        with (
            patch(
                "careerops.cli.fetch_source_description",
                return_value="Full source job description from the company website.",
            ) as fetch,
            patch.object(sys, "stdout", stdout),
            patch.object(sys, "stderr", stderr),
        ):
            exit_code = _handle_backfill_descriptions(args, self.repository)

        self.assertEqual(exit_code, 0)
        fetch.assert_called_once_with("https://example.com/jobs/staff")
        self.assertEqual(stdout.getvalue().strip(), str(generated_id))
        self.assertIn(
            f"skipped {search_page_id}: source URL does not look like a job posting",
            stderr.getvalue(),
        )
        self.assertIn("Backfilled 1 descriptions", stderr.getvalue())
        self.assertEqual(
            self.repository.get(generated_id)["description"],
            "Full source job description from the company website.",
        )
        self.assertEqual(
            self.repository.get(manual_id)["description"],
            "This is already the full source job description.",
        )
        self.assertEqual(
            self.repository.get(search_page_id)["description"],
            "Source: Indeed job alert email. Email subject: Frontend Engineer.",
        )

    def test_clean_descriptions_removes_site_text_from_existing_rows(self) -> None:
        job_id = self.repository.add_or_update(
            JobInput(
                publish_date="2026-05-24",
                job_title="Backend Engineer",
                company_name="Example Systems",
                description=(
                    "Skip to main content\n\n"
                    "Expand search\n\n"
                    "Report this job\n\n"
                    "Overview\n\n"
                    "Build reliable services.\n\n"
                    "Show more\n\n"
                    "Seniority level"
                ),
                url="https://www.linkedin.com/jobs/view/123/",
                salary_range="",
            )
        )
        args = argparse.Namespace(dry_run=False, limit=0, min_length=20)
        stdout = io.StringIO()
        stderr = io.StringIO()

        with (
            patch.object(sys, "stdout", stdout),
            patch.object(sys, "stderr", stderr),
        ):
            exit_code = _handle_clean_descriptions(args, self.repository)

        self.assertEqual(exit_code, 0)
        self.assertEqual(stdout.getvalue().strip(), str(job_id))
        self.assertEqual(stderr.getvalue().strip(), "Cleaned 1 descriptions")
        self.assertEqual(
            self.repository.get(job_id)["description"],
            "Overview\n\nBuild reliable services.",
        )


if __name__ == "__main__":
    unittest.main()
