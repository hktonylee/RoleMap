import unittest
from pathlib import Path


class CodexSkillTest(unittest.TestCase):
    def test_add_job_description_skill_exists_and_documents_workflow(self) -> None:
        skill_path = (
            Path(__file__).resolve().parents[1]
            / "codex-skills"
            / "add-job-description"
            / "SKILL.md"
        )

        body = skill_path.read_text(encoding="utf-8")

        self.assertIn("careerops add-job", body)
        self.assertIn("job_title", body)
        self.assertIn("company_name", body)
        self.assertIn("description", body)
        self.assertIn("url", body)
        self.assertIn("salary_range", body)
        self.assertIn("publish_date", body)
        self.assertIn("last_update", body)
        self.assertIn("not a Gmail", body)
        self.assertIn("Do not generate", body)
        self.assertIn("source website", body)
        self.assertIn("backfill-descriptions", body)


if __name__ == "__main__":
    unittest.main()
