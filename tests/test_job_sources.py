import unittest

from careerops.job_sources import extract_source_description


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
            "Jobs\n\nBackend Engineer\n\nOwn APIs and production services.",
        )


if __name__ == "__main__":
    unittest.main()
