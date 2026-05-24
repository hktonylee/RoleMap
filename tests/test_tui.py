import unittest
import curses

import careerops.tui as tui
from careerops.tui import (
    _JobBrowser,
    _format_list_header,
    _format_list_row,
    _list_column_widths,
)


class FakeScreen:
    def keypad(self, enabled: bool) -> None:
        pass

    def getmaxyx(self) -> tuple[int, int]:
        return (24, 80)


class RecordingScreen(FakeScreen):
    def __init__(self) -> None:
        self.lines: dict[int, str] = {}

    def addstr(self, y: int, x: int, text: str, attrs: int = curses.A_NORMAL) -> None:
        self.lines[y] = text


class TuiListFormattingTest(unittest.TestCase):
    def test_list_row_uses_requested_column_order_without_job_id(self) -> None:
        row = {
            "id": 42,
            "publish_date": "2026-05-24",
            "company_name": "Example Systems",
            "job_title": "Staff Engineer",
            "salary_range": "$180k-$220k",
            "url": "https://example.com/jobs/staff",
            "last_update": "2026-05-24T12:20:01-07:00",
        }

        line = _format_list_row(row, _list_column_widths(160), selected=True)

        self.assertTrue(line.startswith("> 2026-05-24"))
        self.assertLess(line.index("2026-05-24"), line.index("Example Systems"))
        self.assertIn("Staff Engineer", line)
        self.assertIn("$180k-$220k | https://example.com/jobs/staff", line)
        self.assertNotIn("42", line)

    def test_list_header_aligns_with_rows(self) -> None:
        widths = _list_column_widths(120)
        header = _format_list_header(widths)
        row = _format_list_row(
            {
                "id": 42,
                "publish_date": "2026-05-24",
                "company_name": "Example Systems",
                "job_title": "Staff Engineer",
                "salary_range": "$180k-$220k",
                "url": "",
                "last_update": "2026-05-24T12:20:01-07:00",
            },
            widths,
            selected=False,
        )

        self.assertEqual(header.index("Company"), row.index("Example Systems"))
        self.assertEqual(header.index("Job title"), row.index("Staff Engineer"))
        self.assertEqual(header.index("Other"), row.index("$180k-$220k"))

    def test_list_header_keeps_publish_date_label_at_standard_terminal_width(self) -> None:
        self.assertIn("Publish date", _format_list_header(_list_column_widths(80)))


class TuiSortingTest(unittest.TestCase):
    def test_sort_list_rows_uses_selected_column(self) -> None:
        rows = [
            {
                "id": 1,
                "publish_date": "2026-05-22",
                "company_name": "Zulu Labs",
                "job_title": "Engineer",
                "salary_range": "$120k",
                "url": "https://zulu.example/jobs/engineer",
                "last_update": "2026-05-24T09:00:00-07:00",
            },
            {
                "id": 2,
                "publish_date": "2026-05-20",
                "company_name": "Alpha Systems",
                "job_title": "Staff Engineer",
                "salary_range": "$180k",
                "url": "https://alpha.example/jobs/staff",
                "last_update": "2026-05-24T08:00:00-07:00",
            },
        ]

        self.assertTrue(hasattr(tui, "_sort_list_rows"))
        sorted_rows = tui._sort_list_rows(rows, "company_name")

        self.assertEqual(
            [row["company_name"] for row in sorted_rows],
            ["Alpha Systems", "Zulu Labs"],
        )

    def test_o_key_opens_sort_column_selection(self) -> None:
        browser = _JobBrowser(FakeScreen(), repository=object())

        browser._handle_list_key(ord("o"), [])

        self.assertEqual(browser.mode, "sort")

    def test_sort_column_selection_updates_active_sort(self) -> None:
        browser = _JobBrowser(FakeScreen(), repository=object())
        browser.mode = "sort"
        browser.selected = 3

        self.assertTrue(hasattr(browser, "_handle_sort_key"))
        should_exit = browser._handle_sort_key(ord("c"))

        self.assertFalse(should_exit)
        self.assertEqual(browser.mode, "list")
        self.assertEqual(browser.sort_column, "company_name")
        self.assertEqual(browser.selected, 0)


class JobBrowserKeyHandlingTest(unittest.TestCase):
    def test_right_arrow_opens_selected_job_details(self) -> None:
        browser = _JobBrowser(FakeScreen(), repository=object())
        browser.detail_scroll = 3

        should_quit = browser._handle_list_key(curses.KEY_RIGHT, [object()])

        self.assertFalse(should_quit)
        self.assertEqual(browser.mode, "detail")
        self.assertEqual(browser.detail_scroll, 0)

    def test_left_arrow_returns_from_detail_to_list(self) -> None:
        browser = _JobBrowser(FakeScreen(), repository=object())
        browser.mode = "detail"

        should_quit = browser._handle_detail_key(curses.KEY_LEFT)

        self.assertFalse(should_quit)
        self.assertEqual(browser.mode, "list")

    def test_page_down_and_page_up_scroll_detail_by_half_screen(self) -> None:
        browser = _JobBrowser(FakeScreen(), repository=object())
        browser.mode = "detail"

        should_quit = browser._handle_detail_key(curses.KEY_NPAGE)

        self.assertFalse(should_quit)
        self.assertEqual(browser.detail_scroll, 10)

        should_quit = browser._handle_detail_key(curses.KEY_PPAGE)

        self.assertFalse(should_quit)
        self.assertEqual(browser.detail_scroll, 0)


class JobBrowserDetailViewTest(unittest.TestCase):
    def test_detail_help_names_page_scroll_keys(self) -> None:
        screen = RecordingScreen()
        browser = _JobBrowser(screen, repository=object())

        browser._draw_detail(
            {
                "id": 42,
                "publish_date": "2026-05-24",
                "company_name": "Example Systems",
                "job_title": "Staff Engineer",
                "url": "https://example.com/jobs/staff",
                "salary_range": "$180k-$220k",
                "last_update": "2026-05-24T12:20:01-07:00",
                "description": "Build systems.",
            }
        )

        self.assertIn("PgUp/PgDn", screen.lines[1])


if __name__ == "__main__":
    unittest.main()
