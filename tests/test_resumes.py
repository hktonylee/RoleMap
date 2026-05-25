import os
import sys
import tempfile
import unittest
from pathlib import Path

from careerops.resumes import discover_templates, generate_resume


class ResumeTemplateDiscoveryTest(unittest.TestCase):
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
                "description": "Build distributed internal tools.",
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
        self.assertIn("Example Systems", prompt)
        self.assertIn("Staff Platform Engineer", prompt)
        self.assertIn(str(result.template_copy_path), prompt)
        self.assertFalse(result.command_ran)

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
                "description": "Build APIs.",
                "url": "",
                "salary_range": "",
                "publish_date": "",
            }
            script = (
                "from pathlib import Path; "
                "import os; "
                "Path(os.environ['MARKER']).write_text("
                "os.environ['CAREEROPS_RESUME_PROMPT'], encoding='utf-8'"
                ")"
            )
            environ = {
                "CAREEROPS_RESUME_GENERATOR": f"{sys.executable} -c {script!r}",
                "MARKER": str(marker),
                **os.environ,
            }

            result = generate_resume(row, template, root=root, environ=environ)
            marker_text = marker.read_text(encoding="utf-8")

        self.assertTrue(result.command_ran)
        self.assertEqual(marker_text, str(result.prompt_path))


if __name__ == "__main__":
    unittest.main()
