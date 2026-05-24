import argparse
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from careerops.cli import _handle_list_jobs
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


if __name__ == "__main__":
    unittest.main()
