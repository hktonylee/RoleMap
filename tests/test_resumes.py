import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from role_map.resumes import discover_templates, generate_resume, run_resume_generator


class ResumeTemplateDiscoveryTest(unittest.TestCase):
    def test_discovers_resume_templates_from_environment_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "project"
            root.mkdir()
            template_dir = Path(temp_dir) / "custom_templates"
            template_dir.mkdir()
            (template_dir / "master.md").write_text("# Resume", encoding="utf-8")

            with patch.dict(os.environ, {"ROLEMAP_RESUME_TEMPLATE_DIR": str(template_dir)}):
                templates = discover_templates(root)

        self.assertEqual([template.display_name for template in templates], ["master.md"])

    def test_discovers_resume_templates_from_supported_directories(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "templates").mkdir()
            (root / "resume_templates").mkdir()
            (root / "templates" / "master.html").write_text("<html>resume</html>", encoding="utf-8")
            (root / "resume_templates" / "senior.md").write_text("# Resume", encoding="utf-8")
            (root / "other.txt").write_text("ignored", encoding="utf-8")

            templates = discover_templates(root)

        self.assertEqual(
            [template.display_name for template in templates],
            ["resume_templates/senior.md", "templates/master.html"],
        )


class ResumeGenerationTest(unittest.TestCase):
    def test_generate_resume_writes_prompt_inputs_and_template_copy(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            template = root / "templates" / "master.html"
            template.parent.mkdir()
            template.write_text("<html>Detailed resume</html>", encoding="utf-8")
            row = {
                "id": 42,
                "company_name": "Example Systems",
                "job_title": "Staff Platform Engineer",
                "job_description": "Build distributed internal tools.",
                "url": "https://example.com/jobs/staff",
                "salary_range": "$180k-$220k",
                "publish_date": "2026-05-24",
            }

            result = generate_resume(row, template, root=root, environ={})
            template_copy = result.template_copy_path.read_text(encoding="utf-8")
            job_description = result.job_description_path.read_text(encoding="utf-8")
            prompt = result.prompt_path.read_text(encoding="utf-8")

        self.assertTrue(result.output_dir.name.startswith("42-example-systems-staff-platform-engineer-"))
        self.assertEqual(template_copy, "<html>Detailed resume</html>")
        self.assertIn("Build distributed internal tools.", job_description)
        self.assertEqual(
            prompt,
            "Please generate the resume for this job:\n"
            "Company: Example Systems\n"
            "Title: Staff Platform Engineer\n"
            "Description: Build distributed internal tools.\n",
        )
        self.assertEqual(result.result_html_path.name, "tailored-resume.html")
        self.assertFalse(result.command_ran)

    def test_generate_resume_writes_to_configured_destination_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            template = root / "templates" / "master.html"
            template.parent.mkdir()
            template.write_text("<html>Detailed resume</html>", encoding="utf-8")
            destination = root / "custom_resumes"
            row = {
                "id": 42,
                "company_name": "Example Systems",
                "job_title": "Staff Platform Engineer",
                "job_description": "Build distributed internal tools.",
                "url": "",
                "salary_range": "",
                "publish_date": "",
            }

            result = generate_resume(
                row,
                template,
                root=root,
                environ={"ROLEMAPE_RESUME_DESTINATION_DIR": str(destination)},
            )

        self.assertEqual(result.output_dir.parent, destination)
        self.assertEqual(result.template_copy_path.parent, result.output_dir)

    def test_generate_resume_runs_configured_command_with_generated_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            template = root / "templates" / "master.md"
            template.parent.mkdir()
            template.write_text("# Resume", encoding="utf-8")
            marker = root / "marker.txt"
            row = {
                "id": 7,
                "company_name": "Acme Labs",
                "job_title": "Backend Engineer",
                "job_description": "Build APIs.",
                "url": "",
                "salary_range": "",
                "publish_date": "",
            }
            script = (
                "from pathlib import Path; "
                "import os; "
                "Path(os.environ['MARKER']).write_text("
                "os.environ['ROLEMAP_RESUME_PROMPT'], encoding='utf-8'"
                ")"
            )
            environ = {
                "ROLEMAP_RESUME_GENERATOR": f"{sys.executable} -c {script!r}",
                "MARKER": str(marker),
                **os.environ,
            }

            result = generate_resume(row, template, root=root, environ=environ)
            marker_text = marker.read_text(encoding="utf-8")

        self.assertTrue(result.command_ran)
        self.assertEqual(marker_text, str(result.prompt_path))

    def test_run_resume_generator_defaults_to_template_directory_with_job_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            template = root / "templates" / "master.md"
            template.parent.mkdir()
            template.write_text("# Resume", encoding="utf-8")
            row = {
                "id": 7,
                "company_name": "Acme Labs",
                "job_title": "Backend Engineer",
                "job_description": "Build APIs.",
                "url": "",
                "salary_range": "",
                "publish_date": "",
            }
            result = generate_resume(row, template, root=root, environ={})
            calls = []

            run_resume_generator(
                result,
                environ={},
                command_runner=lambda command, **kwargs: calls.append((command, kwargs)),
            )

        command, kwargs = calls[0]
        self.assertEqual(command[0], "codex")
        self.assertEqual(command[1], "--cd")
        self.assertEqual(command[2], str(template.parent))
        self.assertEqual(kwargs["cwd"], template.parent)
        self.assertEqual(
            command[3],
            "Please generate the resume for this job:\n"
            "Company: Acme Labs\n"
            "Title: Backend Engineer\n"
            "Description: Build APIs.\n",
        )
        self.assertEqual(kwargs["env"]["ROLEMAP_RESUME_RESULT_HTML"], str(result.result_html_path))


if __name__ == "__main__":
    unittest.main()
