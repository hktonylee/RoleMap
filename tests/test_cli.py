import argparse
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from rolemap.cli import (
    _format_job,
    _handle_add_job,
    _handle_backfill_descriptions,
    _handle_backfill_salaries,
    _handle_clean_descriptions,
    _handle_list_jobs,
)
from rolemap.job_sources import SourceJob
from rolemap.db import connect, initialize_database
from rolemap.jobs import JobInput, JobRepository


class _TtyStringIO(io.StringIO):
    def isatty(self) -> bool:
        return True


class ListJobsCliTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.connection = connect(Path(self.temp_dir.name) / "rolemap.sqlite3")
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
            patch("rolemap.tui.run") as run,
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
            "Example Systems\tStaff Engineer\t$180k-$220k\thttps://example.com/jobs/staff\t0\t",
            stdout.getvalue(),
        )

    def test_format_job_includes_expired_state(self) -> None:
        row = self.repository.list()[0]

        output = _format_job(row)

        self.assertIn("Expired: no", output)


class BackfillDescriptionsCliTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.connection = connect(Path(self.temp_dir.name) / "rolemap.sqlite3")
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
                "rolemap.cli.fetch_source_job",
                return_value=SourceJob(
                    description="Full source job description from the company website.",
                    salary_range="",
                ),
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


class AddJobSalaryExtractionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.connection = connect(Path(self.temp_dir.name) / "rolemap.sqlite3")
        self.addCleanup(self.connection.close)
        initialize_database(self.connection)
        self.repository = JobRepository(self.connection)

    def test_add_job_extracts_missing_indeed_salary_from_description(self) -> None:
        args = argparse.Namespace(
            json=None,
            publish_date="2026-05-25",
            job_title="Full Stack Developer",
            company_name="Example Systems",
            description=(
                "Build AI-enabled internal products.\n\n"
                "Job Types: Full-time, Permanent\n\n"
                "Pay: $70,000.00-$80,000.00 per year"
            ),
            description_file="",
            url="https://ca.indeed.com/viewjob?jk=a85f6585460cb5c0",
            salary_range="",
        )
        stdout = io.StringIO()

        with patch.object(sys, "stdout", stdout):
            exit_code = _handle_add_job(args, self.repository)

        self.assertEqual(exit_code, 0)
        job_id = int(stdout.getvalue().strip())
        self.assertEqual(
            self.repository.get(job_id)["salary_range"],
            "$70,000-$80,000 per year",
        )


class BackfillSalariesCliTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.connection = connect(Path(self.temp_dir.name) / "rolemap.sqlite3")
        self.addCleanup(self.connection.close)
        initialize_database(self.connection)
        self.repository = JobRepository(self.connection)

    def test_backfill_salaries_updates_empty_salary_from_existing_description(self) -> None:
        job_id = self.repository.add_or_update(
            JobInput(
                publish_date="2026-05-25",
                job_title="Senior Full Stack Engineer",
                company_name="Total Life",
                description=(
                    "Build healthcare integrations.\n\n"
                    "What We Offer\n\n"
                    "Salary: $120,000 – $150,000 CAD, commensurate with experience"
                ),
                url="https://ca.indeed.com/viewjob?jk=1582d610d03dbd6f",
                salary_range="",
            )
        )
        args = argparse.Namespace(dry_run=False, limit=0, overwrite=False, fetch=False)
        stdout = io.StringIO()
        stderr = io.StringIO()

        with (
            patch.object(sys, "stdout", stdout),
            patch.object(sys, "stderr", stderr),
        ):
            exit_code = _handle_backfill_salaries(args, self.repository)

        self.assertEqual(exit_code, 0)
        self.assertEqual(stdout.getvalue().strip(), str(job_id))
        self.assertEqual(stderr.getvalue().strip(), "Backfilled 1 salary ranges")
        self.assertEqual(
            self.repository.get(job_id)["salary_range"],
            "$120,000-$150,000 CAD",
        )

    def test_backfill_salaries_can_fetch_source_when_description_has_no_salary(self) -> None:
        job_id = self.repository.add_or_update(
            JobInput(
                publish_date="2026-05-25",
                job_title="Software Engineer",
                company_name="Example Systems",
                description="Source: Indeed job alert email.",
                url="https://ca.indeed.com/viewjob?jk=61b27402bd23ef5f",
                salary_range="",
            )
        )
        args = argparse.Namespace(dry_run=False, limit=0, overwrite=False, fetch=True)
        stdout = io.StringIO()
        stderr = io.StringIO()

        with (
            patch(
                "rolemap.cli.fetch_source_job",
                return_value=SourceJob(
                    description="Full source job description.",
                    salary_range="$125,000-$160,000 CAD",
                ),
            ) as fetch,
            patch.object(sys, "stdout", stdout),
            patch.object(sys, "stderr", stderr),
        ):
            exit_code = _handle_backfill_salaries(args, self.repository)

        self.assertEqual(exit_code, 0)
        fetch.assert_called_once_with("https://ca.indeed.com/viewjob?jk=61b27402bd23ef5f")
        self.assertEqual(stdout.getvalue().strip(), str(job_id))
        self.assertEqual(
            self.repository.get(job_id)["salary_range"],
            "$125,000-$160,000 CAD",
        )

    def test_backfill_salaries_treats_indeed_alert_description_as_indeed_source(self) -> None:
        job_id = self.repository.add_or_update(
            JobInput(
                publish_date="2026-05-18",
                job_title="Software Engineer (Backend)",
                company_name="Kabam",
                description="Source: Indeed job alert email. Email subject: Kabam is hiring.",
                url="https://www.glassdoor.ca/partner/jobListing.htm?jobListingId=1010136759800",
                salary_range="",
            )
        )
        args = argparse.Namespace(
            dry_run=False,
            limit=0,
            overwrite=False,
            fetch=True,
            source="indeed",
        )
        stdout = io.StringIO()
        stderr = io.StringIO()

        with (
            patch(
                "rolemap.cli.fetch_source_job",
                return_value=SourceJob(
                    description="Full source job description.",
                    salary_range="CA$95,000-CA$120,000 a year",
                ),
            ) as fetch,
            patch.object(sys, "stdout", stdout),
            patch.object(sys, "stderr", stderr),
        ):
            exit_code = _handle_backfill_salaries(args, self.repository)

        self.assertEqual(exit_code, 0)
        fetch.assert_called_once_with(
            "https://www.glassdoor.ca/partner/jobListing.htm?jobListingId=1010136759800"
        )
        self.assertEqual(stdout.getvalue().strip(), str(job_id))
        self.assertEqual(
            self.repository.get(job_id)["salary_range"],
            "CA$95,000-CA$120,000 a year",
        )


if __name__ == "__main__":
    unittest.main()
