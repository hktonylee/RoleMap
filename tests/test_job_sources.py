import unittest

from careerops.job_sources import (
    clean_source_description,
    extract_salary_range,
    extract_source_description,
    extract_source_job,
)


class JobSourceExtractionTest(unittest.TestCase):
    def test_extract_source_description_prefers_jobposting_json_ld(self) -> None:
        html = """
        <html>
          <head>
            <script type="application/ld+json">
              {
                "@context": "https://schema.org",
                "@type": "JobPosting",
                "description": "<p>Build source-backed workflows.</p><p>No generated copy.</p>"
              }
            </script>
          </head>
          <body>Navigation text</body>
        </html>
        """

        self.assertEqual(
            extract_source_description(html),
            "Build source-backed workflows.\n\nNo generated copy.",
        )

    def test_extract_source_job_includes_jobposting_base_salary(self) -> None:
        html = """
        <html>
          <head>
            <script type="application/ld+json">
              {
                "@context": "https://schema.org",
                "@type": "JobPosting",
                "description": "<p>Own secure backend services.</p>",
                "baseSalary": {
                  "@type": "MonetaryAmount",
                  "currency": "CAD",
                  "value": {
                    "@type": "QuantitativeValue",
                    "minValue": 125000,
                    "maxValue": 160000,
                    "unitText": "YEAR"
                  }
                }
              }
            </script>
          </head>
          <body>Navigation text</body>
        </html>
        """

        source_job = extract_source_job(html)

        self.assertEqual(source_job.description, "Own secure backend services.")
        self.assertEqual(source_job.salary_range, "CA$125,000-CA$160,000 a year")

    def test_extract_source_description_falls_back_to_visible_page_text(self) -> None:
        html = """
        <html>
          <head><style>.hidden { display: none; }</style></head>
          <body>
            <nav>Jobs</nav>
            <main>
              <h1>Backend Engineer</h1>
              <p>Own APIs and production services.</p>
            </main>
            <script>window.generated = true;</script>
          </body>
        </html>
        """

        self.assertEqual(
            extract_source_description(html),
            "Backend Engineer\n\nOwn APIs and production services.",
        )

    def test_extract_salary_range_from_indeed_visible_text(self) -> None:
        source = """
        TITLE: Full Stack Developer

        POSITION OVERVIEW

        Build AI-enabled internal products.

        Job Types: Full-time, Permanent

        Pay: $70,000.00-$80,000.00 per year

        Benefits:

        Dental care
        """

        self.assertEqual(
            extract_salary_range(source),
            "$70,000-$80,000 per year",
        )

    def test_clean_source_description_removes_linkedin_chrome(self) -> None:
        source = """
        Example hiring Backend Engineer in Canada | LinkedIn

        Skip to main content

        LinkedIn

        Backend Engineer in Vancouver, BC

        Expand search

        This button displays the currently selected search type.

        Report this job

        Use AI to assess how you fit

        Email or phone

        Password

        By clicking Continue to join or sign in, you agree to LinkedIn's User Agreement, Privacy Policy, and Cookie Policy.

        We build reliable backend systems for restaurants.

        What You'll Do

        Own APIs and production services.

        Show more

        Seniority level

        Entry level

        Expand search
        """

        self.assertEqual(
            clean_source_description(source),
            "We build reliable backend systems for restaurants.\n\nWhat You'll Do\n\nOwn APIs and production services.",
        )

    def test_extract_source_description_cleans_linkedin_fallback_text(self) -> None:
        html = """
        <html>
          <body>
            <main>
              <h1>Example hiring Backend Engineer in Canada | LinkedIn</h1>
              <p>Skip to main content</p>
              <p>Expand search</p>
              <p>Report this job</p>
              <p>Overview</p>
              <p>Build source-backed systems.</p>
              <p>Show more</p>
              <p>Seniority level</p>
            </main>
          </body>
        </html>
        """

        self.assertEqual(
            extract_source_description(html),
            "Overview\n\nBuild source-backed systems.",
        )

    def test_clean_source_description_removes_linkedin_pay_range_chrome(self) -> None:
        source = """
        Report this job

        Example provided pay range

        This range is provided by Example. Your actual pay will be based on your skills and experience.

        Base pay range

        CA$90,000.00/yr - CA$130,000.00/yr

        Direct message the job poster from Example

        Recruiter Name

        Company Overview

        We build useful products.

        Position Overview

        Own backend services.

        Show more
        """

        self.assertEqual(
            clean_source_description(source),
            "Company Overview\n\nWe build useful products.\n\nPosition Overview\n\nOwn backend services.",
        )


if __name__ == "__main__":
    unittest.main()
