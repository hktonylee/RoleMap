import os
import tempfile
import unittest
from pathlib import Path

from role_map.resumes import generate_resume, run_resume_generator


class ResumeGenerationTest(unittest.TestCase):
    def test_generate_resume_writes_prompt_inputs_without_template_copy(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            instruction_dir = root / "templates"
            instruction_dir.mkdir()
            (instruction_dir / "AGENTS.md").write_text(
                "Generate resume from instructions.",
                encoding="utf-8",
            )
            row = {
                "id": 42,
                "company_name": "Example Systems",
                "job_title": "Staff Platform Engineer",
                "job_description": "Build distributed internal tools.",
                "url": "https://example.com/jobs/staff",
                "salary_range": "$180k-$220k",
                "publish_date": "2026-05-24",
            }

            result = generate_resume(
                row,
                root=root,
                environ={"ROLEMAP_RESUME_TEMPLATE_DIR": str(instruction_dir)},
            )
            job_description = result.job_description_path.read_text(encoding="utf-8")
            prompt = result.prompt_path.read_text(encoding="utf-8")

        self.assertTrue(
            result.output_dir.name.startswith("42-example-systems-staff-platform-engineer-")
        )
        self.assertEqual(result.instruction_dir, instruction_dir)
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
            instruction_dir = root / "templates"
            instruction_dir.mkdir()
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
                root=root,
                environ={
                    "ROLEMAP_RESUME_OUTPUT_DIR": str(destination),
                    "ROLEMAP_RESUME_TEMPLATE_DIR": str(instruction_dir),
                },
            )

        self.assertEqual(result.output_dir.parent, destination)
        self.assertEqual(result.instruction_dir, instruction_dir)

    def test_run_resume_generator_defaults_to_instruction_directory_with_job_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            instruction_dir = root / "templates"
            instruction_dir.mkdir()
            row = {
                "id": 7,
                "company_name": "Acme Labs",
                "job_title": "Backend Engineer",
                "job_description": "Build APIs.",
                "url": "",
                "salary_range": "",
                "publish_date": "",
            }
            result = generate_resume(
                row,
                root=root,
                environ={"ROLEMAP_RESUME_TEMPLATE_DIR": str(instruction_dir)},
            )
            calls = []

            run_resume_generator(
                result,
                environ={
                    "ROLEMAP_RESUME_PROMPT": "stale",
                    "ROLEMAP_RESUME_TEMPLATE": "stale",
                    "PATH": "/usr/bin",
                },
                command_runner=lambda command, **kwargs: calls.append((command, kwargs)),
            )

        command, kwargs = calls[0]
        self.assertEqual(command[0], "codex")
        self.assertEqual(command[1], "--cd")
        self.assertEqual(command[2], str(instruction_dir))
        self.assertEqual(kwargs["cwd"], instruction_dir)
        self.assertEqual(
            command[3],
            "Please generate the resume for this job:\n"
            "Company: Acme Labs\n"
            "Title: Backend Engineer\n"
            "Description: Build APIs.\n",
        )
        resume_env = {
            name: value
            for name, value in kwargs["env"].items()
            if name.startswith("ROLEMAP_RESUME_")
        }
        self.assertEqual(
            resume_env,
            {
                "ROLEMAP_RESUME_TEMPLATE_DIR": str(result.instruction_dir),
                "ROLEMAP_RESUME_OUTPUT_DIR": str(result.output_dir),
            },
        )


if __name__ == "__main__":
    unittest.main()
