import unittest
import curses

import careerops.tui as tui
from careerops.tui import (
    _JobBrowser,
    _format_list_header,
    _format_list_row,
    _list_row_attrs,
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


class NarrowRecordingScreen(RecordingScreen):
    def getmaxyx(self) -> tuple[int, int]:
        return (24, 20)


class ToggleRepository:
    def __init__(self) -> None:
        self.toggled_ids: list[int] = []

    def toggle_expired(self, job_id: int) -> bool:
        self.toggled_ids.append(job_id)
        return True


def _row(index: int) -> dict[str, object]:
    return {
        "id": index,
        "publish_date": "2026-05-24",
        "company_name": f"Company {index}",
        "job_title": f"Job {index}",
        "salary_range": "",
        "url": "",
        "last_update": "",
    }


class FakeRepository:
    pass


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

    def test_expired_list_row_uses_dim_attrs_and_strikethrough_text(self) -> None:
        row = {
            "id": 42,
            "publish_date": "2026-05-24",
            "company_name": "Example Systems",
            "job_title": "Staff Engineer",
            "salary_range": "$180k-$220k",
            "url": "https://example.com/jobs/staff",
            "last_update": "2026-05-24T12:20:01-07:00",
            "is_expired": 1,
        }

        line = _format_list_row(row, _list_column_widths(160), selected=False)
        attrs = _list_row_attrs(row, selected=True)

        self.assertIn("\u0336", line)
        self.assertTrue(attrs & curses.A_DIM)
        self.assertTrue(attrs & curses.A_REVERSE)

    def test_expired_list_row_clips_by_visible_width(self) -> None:
        screen = NarrowRecordingScreen()
        browser = _JobBrowser(screen, repository=object())
        row = {
            "id": 42,
            "publish_date": "2026-05-24",
            "company_name": "Example Systems",
            "job_title": "Staff Engineer",
            "salary_range": "$180k-$220k",
            "url": "https://example.com/jobs/staff",
            "last_update": "2026-05-24T12:20:01-07:00",
            "is_expired": 1,
        }

        browser._add_line(
            0,
            0,
            _format_list_row(row, _list_column_widths(80), selected=False),
            20,
        )

        self.assertEqual(screen.lines[0].count("\u0336"), 19)


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
    def test_page_down_and_page_up_move_list_selection_by_visible_page(self) -> None:
        browser = _JobBrowser(FakeScreen(), repository=object())
        rows = [_row(index) for index in range(45)]

        should_quit = browser._handle_list_key(curses.KEY_NPAGE, rows)

        self.assertFalse(should_quit)
        self.assertEqual(browser.selected, 20)

        should_quit = browser._handle_list_key(curses.KEY_PPAGE, rows)

        self.assertFalse(should_quit)
        self.assertEqual(browser.selected, 0)

    def test_home_and_end_move_list_selection_to_first_and_last_job(self) -> None:
        browser = _JobBrowser(FakeScreen(), repository=object())
        rows = [_row(index) for index in range(45)]
        browser.selected = 12

        should_quit = browser._handle_list_key(curses.KEY_END, rows)

        self.assertFalse(should_quit)
        self.assertEqual(browser.selected, 44)

        should_quit = browser._handle_list_key(curses.KEY_HOME, rows)

        self.assertFalse(should_quit)
        self.assertEqual(browser.selected, 0)

    def test_right_arrow_opens_selected_job_details(self) -> None:
        browser = _JobBrowser(FakeScreen(), repository=object())
        browser.detail_scroll = 3

        should_quit = browser._handle_list_key(curses.KEY_RIGHT, [object()])

        self.assertFalse(should_quit)
        self.assertEqual(browser.mode, "detail")
        self.assertEqual(browser.detail_scroll, 0)

    def test_space_toggles_selected_job_expired_state(self) -> None:
        repository = ToggleRepository()
        browser = _JobBrowser(FakeScreen(), repository=repository)
        browser.selected = 1
        rows = [
            {"id": 41, "is_expired": 0},
            {"id": 42, "is_expired": 0},
        ]

        should_quit = browser._handle_list_key(ord(" "), rows)

        self.assertFalse(should_quit)
        self.assertEqual(repository.toggled_ids, [42])

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
        self.assertEqual(browser.detail_scroll, 7)

        should_quit = browser._handle_detail_key(curses.KEY_PPAGE)

        self.assertFalse(should_quit)
        self.assertEqual(browser.detail_scroll, 0)

    def test_home_and_end_scroll_detail_to_top_and_bottom(self) -> None:
        browser = _JobBrowser(FakeScreen(), repository=object())
        browser.mode = "detail"
        row = {
            "id": 42,
            "publish_date": "2026-05-24",
            "company_name": "Example Systems",
            "job_title": "Staff Engineer",
            "url": "https://example.com/jobs/staff",
            "salary_range": "$180k-$220k",
            "last_update": "2026-05-24T12:20:01-07:00",
            "description": "\n".join(f"Line {index}" for index in range(30)),
        }

        should_quit = browser._handle_detail_key(curses.KEY_END, row)

        self.assertFalse(should_quit)
        self.assertEqual(browser.detail_scroll, 16)

        should_quit = browser._handle_detail_key(curses.KEY_HOME, row)

        self.assertFalse(should_quit)
        self.assertEqual(browser.detail_scroll, 0)


class JobBrowserListViewTest(unittest.TestCase):
    def test_list_draws_next_page_when_selection_moves_beyond_visible_rows(self) -> None:
        screen = RecordingScreen()
        browser = _JobBrowser(screen, repository=object())
        browser.selected = 20

        browser._draw_list([_row(index) for index in range(25)])

        rendered = "\n".join(screen.lines.values())
        self.assertTrue(
            any(
                line.startswith("> 2026-05-24") and "Company 20" in line
                for line in screen.lines.values()
            )
        )
        self.assertNotIn("Company 0", rendered)


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

        self.assertIn("PgUp/PgDn/Home/End", screen.lines[1])
        self.assertIn("G generate resume", screen.lines[1])

    def test_g_key_opens_template_selection_from_detail_view(self) -> None:
        browser = _JobBrowser(FakeScreen(), repository=FakeRepository())
        browser.mode = "detail"

        should_quit = browser._handle_detail_key(
            ord("G"),
            {
                "id": 42,
                "company_name": "Example Systems",
                "job_title": "Staff Engineer",
                "description": "Build systems.",
            },
            templates=[object()],
        )

        self.assertFalse(should_quit)
        self.assertEqual(browser.mode, "template")
        self.assertEqual(browser.template_selected, 0)

    def test_g_key_stays_on_detail_view_when_no_templates_exist(self) -> None:
        browser = _JobBrowser(FakeScreen(), repository=FakeRepository())
        browser.mode = "detail"

        should_quit = browser._handle_detail_key(
            ord("G"),
            {
                "id": 42,
                "company_name": "Example Systems",
                "job_title": "Staff Engineer",
                "description": "Build systems.",
            },
            templates=[],
        )

        self.assertFalse(should_quit)
        self.assertEqual(browser.mode, "detail")
        self.assertIn("No resume templates found", browser.status_message)

    def test_template_selection_runs_resume_generation(self) -> None:
        browser = _JobBrowser(FakeScreen(), repository=FakeRepository())
        template = object()
        row = {
            "id": 42,
            "company_name": "Example Systems",
            "job_title": "Staff Engineer",
            "description": "Build systems.",
        }
        browser.mode = "template"
        browser.template_templates = [template]
        browser.template_job = row
        generated: list[tuple[object, object]] = []

        should_quit = browser._handle_template_key(
            curses.KEY_ENTER,
            generate=lambda job, selected_template: generated.append((job, selected_template)),
        )

        self.assertFalse(should_quit)
        self.assertEqual(generated, [(row, template)])
        self.assertEqual(browser.mode, "detail")
        self.assertIn("Resume generation prepared", browser.status_message)

    def test_detail_basic_info_stays_visible_while_description_scrolls(self) -> None:
        screen = RecordingScreen()
        browser = _JobBrowser(screen, repository=object())
        browser.detail_scroll = 2

        browser._draw_detail(
            {
                "id": 42,
                "publish_date": "2026-05-24",
                "company_name": "Example Systems",
                "job_title": "Staff Engineer",
                "url": "https://example.com/jobs/staff",
                "salary_range": "$180k-$220k",
                "last_update": "2026-05-24T12:20:01-07:00",
                "description": "\n".join(
                    [
                        "First description line.",
                        "Second description line.",
                        "Third description line.",
                    ]
                ),
            }
        )

        rendered = "\n".join(screen.lines.values())
        self.assertIn("ID: 42", rendered)
        self.assertIn("Publish date: 2026-05-24", rendered)
        self.assertIn("URL: https://example.com/jobs/staff", rendered)
        self.assertIn("Salary range: $180k-$220k", rendered)
        self.assertIn("Last update: 2026-05-24T12:20:01-07:00", rendered)
        self.assertNotIn("First description line.", rendered)
        self.assertIn("Third description line.", rendered)

    def test_detail_description_soft_wraps_at_120_characters(self) -> None:
        row = {
            "description": " ".join(["platform"] * 40),
        }

        lines = tui._detail_description_lines(row, 200)

        self.assertGreater(len(lines), 1)
        self.assertLessEqual(max(len(line) for line in lines), 120)


if __name__ == "__main__":
    unittest.main()
