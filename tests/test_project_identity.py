import tomllib
import unittest
from pathlib import Path

from rolemap.cli import DEFAULT_DB_PATH, _build_parser, _database_path
from rolemap.resumes import GENERATOR_ENV_VAR


class ProjectIdentityTest(unittest.TestCase):
    def test_pyproject_links_rolemap_package_and_console_script(self) -> None:
        pyproject = tomllib.loads(
            (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(
                encoding="utf-8"
            )
        )

        self.assertEqual(pyproject["project"]["name"], "rolemap")
        self.assertEqual(pyproject["project"]["scripts"], {"rolemap": "rolemap.cli:main"})
        self.assertEqual(
            pyproject["tool"]["setuptools"]["packages"]["find"]["include"],
            ["rolemap*"],
        )

    def test_cli_uses_rolemap_names_for_prog_error_db_and_env(self) -> None:
        parser = _build_parser()

        self.assertEqual(parser.prog, "rolemap")
        self.assertEqual(DEFAULT_DB_PATH, Path("data") / "rolemap.sqlite3")
        self.assertEqual(_database_path(None), Path("data") / "rolemap.sqlite3")
        self.assertEqual(GENERATOR_ENV_VAR, "ROLEMAP_RESUME_GENERATOR")


if __name__ == "__main__":
    unittest.main()
