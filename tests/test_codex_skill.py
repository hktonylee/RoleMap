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

        self.assertIn("name: add-job-description", body)
        self.assertNotIn("rolemap-add-job-description", body)
        self.assertIn("rolemap add-job", body)
        self.assertIn("job_title", body)
        self.assertIn("company_name", body)
        self.assertIn("job_description", body)
        self.assertIn("url", body)
        self.assertIn("salary_range", body)
        self.assertIn("publish_date", body)
        self.assertIn("last_update", body)
        self.assertIn("not a Gmail", body)
        self.assertIn("Do not generate", body)
        self.assertIn("Playwright", body)
        self.assertIn("full description", body)
        self.assertIn("datePosted", body)
        self.assertIn("email date", body)
        self.assertIn("Markdown", body)
        self.assertIn("source headings, lists, paragraphs, and links", body)
        self.assertIn("`#` headings", body)
        self.assertIn("` * ` bullets", body)
        self.assertIn("source website", body)
        self.assertIn("backfill-descriptions", body)

    def test_list_jobs_skill_exists_and_documents_workflow(self) -> None:
        skill_path = (
            Path(__file__).resolve().parents[1]
            / "codex-skills"
            / "list-jobs"
            / "SKILL.md"
        )

        body = skill_path.read_text(encoding="utf-8")

        self.assertIn("name: list-jobs", body)
        self.assertIn("rolemap list-jobs", body)
        self.assertIn("python -m role_map list-jobs", body)
        self.assertIn("--query", body)
        self.assertIn("--db", body)
        self.assertIn("ROLEMAP_DB", body)
        self.assertIn("noninteractive", body)
        self.assertIn("tab-separated", body)
        self.assertIn("id", body)
        self.assertIn("publish_date", body)
        self.assertIn("company_name", body)
        self.assertIn("job_title", body)
        self.assertIn("salary_range", body)
        self.assertIn("url", body)
        self.assertIn("is_expired", body)
        self.assertIn("last_update", body)
        self.assertIn("read-only", body)


if __name__ == "__main__":
    unittest.main()
