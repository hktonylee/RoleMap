import importlib
import tomllib
import unittest
from pathlib import Path
from unittest.mock import patch

import role_map.cli as cli
from role_map.cli import _build_parser, _database_path

class ProjectIdentityTest(unittest.TestCase):
    def test_pyproject_links_role_map_package_and_console_script(self) -> None:
        pyproject = tomllib.loads(
            (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(
                encoding="utf-8"
            )
        )

        self.assertEqual(pyproject["project"]["name"], "rolemap")
        self.assertEqual(pyproject["project"]["scripts"], {"rolemap": "role_map.cli:main"})
        self.assertEqual(
            pyproject["tool"]["setuptools"]["packages"]["find"]["include"],
            ["role_map*"],
        )

    def test_cli_uses_rolemap_names_for_prog_error_db_and_env(self) -> None:
        parser = _build_parser()
        default_db_path = Path.home() / ".local" / "state" / "rolemap" / "rolemap.sqlite3"

        self.assertEqual(parser.prog, "rolemap")
        self.assertEqual(cli.DEFAULT_DB_PATH, default_db_path)
        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(_database_path(None), default_db_path)
        with patch.dict("os.environ", {"XDG_STATE_HOME": "/tmp/state"}, clear=True):
            self.assertEqual(
                _database_path(None),
                Path("/tmp/state") / "rolemap" / "rolemap.sqlite3",
            )

    def test_default_db_path_uses_xdg_state_home(self) -> None:
        with patch.dict("os.environ", {"XDG_STATE_HOME": "/tmp/state"}, clear=True):
            importlib.reload(cli)
            self.assertEqual(
                cli.DEFAULT_DB_PATH,
                Path("/tmp/state") / "rolemap" / "rolemap.sqlite3",
            )

        with patch.dict("os.environ", {}, clear=True):
            importlib.reload(cli)

    def test_docs_describe_one_shot_add_job_contract(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        readme = (project_root / "README.md").read_text(encoding="utf-8")
        spec = (
            project_root
            / "docs"
            / "specs"
            / "2026-05-24-sqlite-rolemap-design.md"
        ).read_text(encoding="utf-8")
        normalized_readme = " ".join(readme.split())
        normalized_spec = " ".join(spec.split())

        self.assertIn("one-shot", normalized_readme)
        self.assertIn("fetch source", normalized_readme)
        self.assertIn(
            "job_description, salary_range, publish_date, and url",
            normalized_readme,
        )
        self.assertIn("Do not import email or search-result snippets", normalized_readme)
        self.assertIn("Leave salary_range empty", normalized_readme)

        self.assertIn("one-shot add flow", normalized_spec)
        self.assertIn("fetch source", normalized_spec)
        self.assertIn(
            "capture job_description, salary_range, publish_date, and url",
            normalized_spec,
        )
        self.assertIn("empty salary_range is valid", normalized_spec)
        self.assertNotIn("Backfilling generated descriptions", spec)

if __name__ == "__main__":
    unittest.main()
