import unittest
import curses
import io
import os
from contextlib import redirect_stderr, redirect_stdout
from types import SimpleNamespace
from unittest.mock import patch

import role_map.tui as tui
from role_map.tui import (
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
        self.calls: list[SimpleNamespace] = []

    def erase(self) -> None:
        self.lines = {}

    def refresh(self) -> None:
        pass

    def addstr(self, y: int, x: int, text: str, attrs: int = curses.A_NORMAL) -> None:
        self.calls.append(SimpleNamespace(y=y, x=x, text=text, attrs=attrs))
        existing = self.lines.get(y, "")
        if x > len(existing):
            existing = existing.ljust(x)
        self.lines[y] = existing[:x] + text + existing[x + len(text) :]


class KeyScreen(RecordingScreen):
    def __init__(self, keys: list[int]) -> None:
        super().__init__()
        self.keys = keys

    def erase(self) -> None:
        pass

    def refresh(self) -> None:
        pass

    def getch(self) -> int:
        return self.keys.pop(0)


class NarrowRecordingScreen(RecordingScreen):
    def getmaxyx(self) -> tuple[int, int]:
        return (24, 20)


class ToggleRepository:
    def __init__(self) -> None:
        self.toggled_ids: list[int] = []

    def toggle_expired(self, job_id: int) -> bool:
        self.toggled_ids.append(job_id)
        return True


class ToggleSearchRepository:
    def __init__(self) -> None:
        self.toggled_ids: list[int] = []

    def search(self, query: str) -> list[dict[str, object]]:
        return [
            {"id": 1, "company_name": "Alpha", "is_expired": 0},
            {
                "id": 2,
                "company_name": "Beta",
                "is_expired": int(2 in self.toggled_ids),
            },
            {"id": 3, "company_name": "Gamma", "is_expired": 0},
        ]

    def toggle_expired(self, job_id: int) -> bool:
        self.toggled_ids.append(job_id)
        return True


class KeyScreen(RecordingScreen):
    def __init__(self, keys: list[int]) -> None:
        super().__init__()
        self.keys = keys
        self.drawn_lists: list[list[int]] = []

    def getch(self) -> int:
        return self.keys.pop(0)


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
    def __init__(self, rows: list[dict[str, object]] | None = None) -> None:
        self.rows = [] if rows is None else rows

    def search(self, query: str) -> list[dict[str, object]]:
        return self.rows


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
        self.assertNotIn(" \u0336", line)
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

        visible_text = screen.lines[0].replace("\u0336", "")
        self.assertEqual(
            screen.lines[0].count("\u0336"),
            sum(1 for character in visible_text if character != " "),
        )
        self.assertEqual(len(visible_text), 19)

    def test_other_column_omits_last_update_time(self) -> None:
        row = {
            "id": 42,
            "publish_date": "2026-05-24",
            "company_name": "Example Systems",
            "job_title": "Staff Engineer",
            "salary_range": "$180k-$220k",
            "url": "https://example.com/jobs/staff",
            "last_update": "2026-05-24T12:20:01-07:00",
        }

        line = _format_list_row(row, _list_column_widths(160), selected=False)

        self.assertIn("$180k-$220k | https://example.com/jobs/staff", line)
        self.assertNotIn("Updated", line)
        self.assertNotIn("2026-05-24T12:20:01-07:00", line)


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

    def test_sort_list_rows_can_reverse_selected_column(self) -> None:
        rows = [
            {"company_name": "Alpha Systems"},
            {"company_name": "Zulu Labs"},
        ]

        try:
            sorted_rows = tui._sort_list_rows(rows, "company_name", reverse=True)
        except TypeError:
            self.fail("_sort_list_rows should accept reverse=True")

        self.assertEqual(
            [row["company_name"] for row in sorted_rows],
            ["Zulu Labs", "Alpha Systems"],
        )

    def test_sort_list_rows_keeps_expired_rows_after_active_rows(self) -> None:
        rows = [
            {"id": 1, "company_name": "Zulu Labs", "is_expired": 0},
            {"id": 2, "company_name": "Alpha Systems", "is_expired": 1},
            {"id": 3, "company_name": "Beta Systems", "is_expired": 0},
        ]

        sorted_rows = tui._sort_list_rows(rows, "company_name")

        self.assertEqual([row["id"] for row in sorted_rows], [3, 1, 2])

    def test_reverse_sort_list_rows_keeps_expired_rows_after_active_rows(self) -> None:
        rows = [
            {"id": 1, "company_name": "Alpha Systems", "is_expired": 1},
            {"id": 2, "company_name": "Beta Systems", "is_expired": 0},
            {"id": 3, "company_name": "Zulu Labs", "is_expired": 1},
            {"id": 4, "company_name": "Acme Labs", "is_expired": 0},
        ]

        sorted_rows = tui._sort_list_rows(rows, "company_name", reverse=True)

        self.assertEqual([row["id"] for row in sorted_rows], [2, 4, 3, 1])

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

    def test_uppercase_sort_column_selection_reverses_active_sort(self) -> None:
        browser = _JobBrowser(FakeScreen(), repository=object())
        browser.mode = "sort"

        should_exit = browser._handle_sort_key(ord("C"))

        self.assertFalse(should_exit)
        self.assertEqual(browser.mode, "list")
        self.assertEqual(browser.sort_column, "company_name")
        self.assertTrue(hasattr(browser, "sort_reverse"))
        self.assertTrue(browser.sort_reverse)


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

    def test_printable_keys_do_not_change_query_until_search_is_focused(self) -> None:
        browser = _JobBrowser(FakeScreen(), repository=object())
        browser.query = "remote"
        browser.selected = 2

        should_quit = browser._handle_list_key(ord("a"), [])

        self.assertFalse(should_quit)
        self.assertEqual(browser.query, "remote")
        self.assertEqual(browser.selected, 2)

    def test_backspace_does_not_change_query_until_search_is_focused(self) -> None:
        browser = _JobBrowser(FakeScreen(), repository=object())
        browser.query = "remote"
        browser.selected = 2

        should_quit = browser._handle_list_key(curses.KEY_BACKSPACE, [])

        self.assertFalse(should_quit)
        self.assertEqual(browser.query, "remote")
        self.assertEqual(browser.selected, 2)

    def test_slash_focuses_search_so_o_types_query_instead_of_sorting(self) -> None:
        browser = _JobBrowser(FakeScreen(), repository=object())

        should_quit = browser._handle_list_key(ord("/"), [])
        self.assertFalse(should_quit)
        self.assertEqual(browser.query, "")

        should_quit = browser._handle_list_key(ord("o"), [])

        self.assertFalse(should_quit)
        self.assertEqual(browser.mode, "list")
        self.assertEqual(browser.query, "o")
        self.assertEqual(browser.selected, 0)

    def test_right_arrow_opens_selected_job_details(self) -> None:
        browser = _JobBrowser(FakeScreen(), repository=object())
        browser.detail_scroll = 3

        should_quit = browser._handle_list_key(curses.KEY_RIGHT, [object()])

        self.assertFalse(should_quit)
        self.assertEqual(browser.mode, "detail")
        self.assertEqual(browser.detail_scroll, 0)

    def test_enter_from_list_opens_details_without_opening_url(self) -> None:
        row = {
            "id": 42,
            "publish_date": "2026-05-24",
            "company_name": "Example Systems",
            "job_title": "Staff Engineer",
            "salary_range": "",
            "url": "https://example.com/jobs/staff",
            "last_update": "",
            "description": "Build systems.",
        }
        screen = KeyScreen([curses.KEY_ENTER, 27, ord("q")])
        browser = _JobBrowser(screen, repository=FakeRepository([row]))
        opened_urls = []

        with (
            patch.object(tui.curses, "curs_set"),
            patch.object(tui, "_init_shortcut_key_color"),
            patch.object(browser, "_open_job_url", lambda row, opener=None: opened_urls.append(row)),
        ):
            browser.run()

        self.assertEqual(opened_urls, [])

    def test_space_after_entering_detail_toggles_expired_state(self) -> None:
        row = {
            "id": 42,
            "publish_date": "2026-05-24",
            "company_name": "Example Systems",
            "job_title": "Staff Engineer",
            "salary_range": "",
            "url": "https://example.com/jobs/staff",
            "last_update": "",
            "description": "Build systems.",
            "is_expired": 0,
        }
        repository = FakeRepository([row])
        repository.toggle_expired = lambda job_id: setattr(
            repository,
            "toggled_id",
            job_id,
        ) or True
        screen = KeyScreen([curses.KEY_ENTER, ord(" "), 27, ord("q")])
        browser = _JobBrowser(screen, repository=repository)

        with patch("curses.curs_set"):
            browser.run()

        self.assertEqual(repository.toggled_id, 42)

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

    def test_toggle_keeps_list_order_until_leaving_list(self) -> None:
        repository = ToggleSearchRepository()
        screen = KeyScreen([curses.KEY_DOWN, ord(" "), ord("q")])
        browser = _JobBrowser(screen, repository=repository)
        original_draw_list = browser._draw_list

        def record_draw(rows: list[dict[str, object]]) -> None:
            screen.drawn_lists.append([int(row["id"]) for row in rows])
            original_draw_list(rows)

        browser._draw_list = record_draw

        with patch("curses.curs_set"):
            browser.run()

        self.assertEqual(screen.drawn_lists, [[1, 2, 3], [1, 2, 3], [1, 2, 3]])

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

    def test_space_toggles_current_job_expired_state_from_detail(self) -> None:
        repository = ToggleRepository()
        browser = _JobBrowser(FakeScreen(), repository=repository)
        browser.mode = "detail"

        should_quit = browser._handle_detail_key(ord(" "), {"id": 42})

        self.assertFalse(should_quit)
        self.assertEqual(repository.toggled_ids, [42])

    def test_detail_view_keeps_current_job_selected_after_rows_reorder(self) -> None:
        browser = _JobBrowser(FakeScreen(), repository=object())
        browser.mode = "detail"
        browser.selected = 1
        browser.detail_job_id = 42
        rows = [
            {"id": 41},
            {"id": 43},
            {"id": 42},
        ]

        browser._sync_detail_selection(rows)

        self.assertEqual(browser.selected, 2)


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
        self.assertIn("Enter open URL", screen.lines[1])
        self.assertIn("G resume", screen.lines[1])
        self.assertIn("Space toggle", screen.lines[1])

    def test_detail_help_highlights_enter_shortcut_key(self) -> None:
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

        enter_calls = [call for call in screen.calls if call.text == "Enter"]
        self.assertEqual(len(enter_calls), 1)
        self.assertNotEqual(enter_calls[0].attrs, curses.A_NORMAL)

    def test_shortcut_key_color_prefers_terminal_orange(self) -> None:
        initializer = getattr(tui, "_init_shortcut_key_color", None)
        self.assertIsNotNone(initializer)
        if initializer is None:
            return

        with (
            patch.object(tui.curses, "start_color"),
            patch.object(tui.curses, "use_default_colors"),
            patch.object(tui.curses, "has_colors", return_value=True),
            patch.object(tui.curses, "init_pair") as init_pair,
            patch.object(tui.curses, "COLORS", 256, create=True),
        ):
            initializer()

        init_pair.assert_called_once_with(tui._SHORTCUT_KEY_COLOR_PAIR, 208, -1)

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
        self.assertIn("Put your detailed resume in templates/", browser.status_message)
        self.assertIn("resume_templates/", browser.status_message)

    def test_enter_key_opens_job_url_with_browser_environment_variable(self) -> None:
        browser = _JobBrowser(FakeScreen(), repository=FakeRepository())
        browser.mode = "detail"
        launched_commands = []

        with patch.dict(os.environ, {"BROWSER": "firefox --new-tab"}):
            should_quit = browser._handle_detail_key(
                curses.KEY_ENTER,
                {
                    "id": 42,
                    "company_name": "Example Systems",
                    "job_title": "Staff Engineer",
                    "url": "https://example.com/jobs/staff",
                    "description": "Build systems.",
                },
                opener=lambda command, **_kwargs: (
                    launched_commands.append(command)
                    or SimpleNamespace(returncode=0, stdout="", stderr="")
                ),
            )

        self.assertFalse(should_quit)
        self.assertEqual(
            launched_commands,
            [["firefox", "--new-tab", "https://example.com/jobs/staff"]],
        )

    def test_opening_job_url_suppresses_browser_output_when_command_succeeds(self) -> None:
        browser = _JobBrowser(FakeScreen(), repository=FakeRepository())
        browser.mode = "detail"
        launched_kwargs = []
        stdout = io.StringIO()
        stderr = io.StringIO()

        with patch.dict(os.environ, {"BROWSER": "firefox --new-tab"}):
            with redirect_stdout(stdout), redirect_stderr(stderr):
                should_quit = browser._handle_detail_key(
                    curses.KEY_ENTER,
                    {
                        "id": 42,
                        "company_name": "Example Systems",
                        "job_title": "Staff Engineer",
                        "url": "https://example.com/jobs/staff",
                        "description": "Build systems.",
                    },
                    opener=lambda _command, **kwargs: (
                        launched_kwargs.append(kwargs)
                        or SimpleNamespace(returncode=0, stdout="out", stderr="err")
                    ),
                )

        self.assertFalse(should_quit)
        self.assertEqual(launched_kwargs, [{"capture_output": True, "text": True}])
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(stderr.getvalue(), "")

    def test_opening_job_url_prints_browser_output_when_command_fails(self) -> None:
        browser = _JobBrowser(FakeScreen(), repository=FakeRepository())
        browser.mode = "detail"
        stdout = io.StringIO()
        stderr = io.StringIO()

        with patch.dict(os.environ, {"BROWSER": "firefox --new-tab"}):
            with redirect_stdout(stdout), redirect_stderr(stderr):
                should_quit = browser._handle_detail_key(
                    curses.KEY_ENTER,
                    {
                        "id": 42,
                        "company_name": "Example Systems",
                        "job_title": "Staff Engineer",
                        "url": "https://example.com/jobs/staff",
                        "description": "Build systems.",
                    },
                    opener=lambda _command, **_kwargs: SimpleNamespace(
                        returncode=1,
                        stdout="browser stdout\n",
                        stderr="browser stderr\n",
                    ),
                )

        self.assertFalse(should_quit)
        self.assertEqual(stdout.getvalue(), "browser stdout\n")
        self.assertEqual(stderr.getvalue(), "browser stderr\n")

    def test_u_key_does_not_open_job_url_from_detail_view(self) -> None:
        browser = _JobBrowser(FakeScreen(), repository=FakeRepository())
        browser.mode = "detail"
        launched_commands = []

        with patch.dict(os.environ, {"BROWSER": "firefox --new-tab"}):
            should_quit = browser._handle_detail_key(
                ord("u"),
                {
                    "id": 42,
                    "company_name": "Example Systems",
                    "job_title": "Staff Engineer",
                    "url": "https://example.com/jobs/staff",
                    "description": "Build systems.",
                },
                opener=lambda command, **_kwargs: (
                    launched_commands.append(command)
                    or SimpleNamespace(returncode=0, stdout="", stderr="")
                ),
            )

        self.assertFalse(should_quit)
        self.assertEqual(launched_commands, [])

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
        terminal_sessions = []
        result = SimpleNamespace(
            output_dir="/tmp/generated/resume",
            result_html_path="/tmp/generated/resume/tailored-resume.html",
        )

        should_quit = browser._handle_template_key(
            curses.KEY_ENTER,
            generate=lambda job, selected_template, run_command=False: (
                generated.append((job, selected_template, run_command)) or result
            ),
            run_generator=lambda generation_result: terminal_sessions.append(generation_result),
            show_terminal=lambda operation: operation(),
        )

        self.assertFalse(should_quit)
        self.assertEqual(generated, [(row, template, False)])
        self.assertEqual(terminal_sessions, [result])
        self.assertEqual(browser.mode, "detail")
        self.assertIn("Resume HTML: /tmp/generated/resume/tailored-resume.html", browser.status_message)

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

    def test_expired_detail_text_uses_dim_attrs_and_strikethrough_text(self) -> None:
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
                "is_expired": 1,
            }
        )

        job_calls = [
            call for call in screen.calls if call.y in {0, 3, 4, 5, 6, 7, 9, 10}
        ]
        self.assertTrue(job_calls)
        self.assertTrue(all(call.attrs & curses.A_DIM for call in job_calls))
        self.assertTrue(all("\u0336" in call.text for call in job_calls))
        self.assertNotIn(" \u0336", "\n".join(call.text for call in job_calls))

    def test_detail_status_message_renders_inverted_in_bottom_left_corner(self) -> None:
        screen = RecordingScreen()
        browser = _JobBrowser(screen, repository=object())
        browser.status_message = "Opened URL: https://example.com/jobs/staff"

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

        status_call = screen.calls[-1]
        self.assertEqual(status_call.y, screen.getmaxyx()[0] - 1)
        self.assertEqual(status_call.x, 0)
        self.assertEqual(
            status_call.text,
            "Opened URL: https://example.com/jobs/staff",
        )
        self.assertTrue(status_call.attrs & curses.A_REVERSE)

    def test_detail_description_soft_wraps_at_120_characters(self) -> None:
        row = {
            "description": " ".join(["platform"] * 40),
        }

        lines = tui._detail_description_lines(row, 200)

        self.assertGreater(len(lines), 1)
        self.assertLessEqual(max(len(line) for line in lines), 120)


if __name__ == "__main__":
    unittest.main()
