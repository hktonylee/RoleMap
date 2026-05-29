import unittest
import curses
import io
import os
import subprocess
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


class WideRecordingScreen(RecordingScreen):
    def getmaxyx(self) -> tuple[int, int]:
        return (24, 160)


class ToggleRepository:
    def __init__(self) -> None:
        self.toggled_ids: list[int] = []
        self.starred_ids: list[int] = []

    def toggle_expired(self, job_id: int) -> bool:
        self.toggled_ids.append(job_id)
        return True

    def toggle_starred(self, job_id: int) -> bool:
        self.starred_ids.append(job_id)
        return True


class ToggleSearchRepository:
    def __init__(self) -> None:
        self.toggled_ids: list[int] = []
        self.starred_ids: list[int] = []

    def search(self, query: str) -> list[dict[str, object]]:
        return [
            {"id": 1, "company_name": "Alpha", "is_expired": 0, "is_starred": 0},
            {
                "id": 2,
                "company_name": "Beta",
                "is_expired": int(2 in self.toggled_ids),
                "is_starred": int(2 in self.starred_ids),
            },
            {"id": 3, "company_name": "Gamma", "is_expired": 0, "is_starred": 0},
        ]

    def toggle_expired(self, job_id: int) -> bool:
        self.toggled_ids.append(job_id)
        return True

    def toggle_starred(self, job_id: int) -> bool:
        self.starred_ids.append(job_id)
        return True


class RefreshingRepository:
    def __init__(self) -> None:
        self.search_count = 0

    def search(self, query: str) -> list[dict[str, object]]:
        self.search_count += 1
        return [_row(self.search_count)]


class PruneRepository:
    def __init__(self) -> None:
        self.prune_count = 0

    def prune_expired(self) -> int:
        self.prune_count += 1
        return 2


class DescriptionRepository:
    def __init__(self) -> None:
        self.updated_descriptions: list[tuple[int, str]] = []

    def update_description(self, job_id: int, description: str) -> None:
        self.updated_descriptions.append((job_id, description.strip()))


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
        "is_read": 1,
    }


class FakeRepository:
    def __init__(self, rows: list[dict[str, object]] | None = None) -> None:
        self.rows = [] if rows is None else rows

    def search(self, query: str) -> list[dict[str, object]]:
        return self.rows

    def mark_read(self, job_id: int) -> None:
        pass


class ReadRepository(FakeRepository):
    def __init__(self, rows: list[dict[str, object]] | None = None) -> None:
        super().__init__(rows)
        self.read_ids: list[int] = []

    def mark_read(self, job_id: int) -> None:
        self.read_ids.append(job_id)


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
            "is_read": 1,
        }

        line = _format_list_row(row, _list_column_widths(160), selected=True)

        self.assertTrue(line.startswith("    2026-05-24"))
        self.assertLess(line.index("2026-05-24"), line.index("Example Systems"))
        self.assertIn("Staff Engineer", line)
        self.assertIn("$180k-$220k | https://example.com/jobs/staff", line)
        self.assertNotIn("42", line)

    def test_unread_list_row_uses_two_character_read_dot_column(self) -> None:
        row = {
            "id": 42,
            "publish_date": "2026-05-24",
            "company_name": "Example Systems",
            "job_title": "Staff Engineer",
            "salary_range": "$180k-$220k",
            "url": "https://example.com/jobs/staff",
            "last_update": "2026-05-24T12:20:01-07:00",
            "is_read": 0,
        }

        line = _format_list_row(row, _list_column_widths(160), selected=True)

        self.assertTrue(line.startswith("•   "))
        self.assertEqual(line[1], " ")

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
                "is_read": 1,
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

    def test_starred_list_row_uses_yellow_attrs(self) -> None:
        row = {
            "id": 42,
            "publish_date": "2026-05-24",
            "company_name": "Example Systems",
            "job_title": "Staff Engineer",
            "salary_range": "$180k-$220k",
            "url": "https://example.com/jobs/staff",
            "last_update": "2026-05-24T12:20:01-07:00",
            "is_starred": 1,
        }

        with patch.object(tui.curses, "color_pair", return_value=512) as color_pair:
            attrs = _list_row_attrs(row, selected=True)

        color_pair.assert_called_once_with(tui._STARRED_COLOR_PAIR)
        self.assertTrue(attrs & 512)
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

    def test_sort_list_rows_omits_pruned_rows(self) -> None:
        rows = [
            {"id": 1, "company_name": "Alpha Systems", "is_pruned": 0},
            {"id": 2, "company_name": "Beta Systems", "is_pruned": 1},
        ]

        sorted_rows = tui._sort_list_rows(rows, "company_name")

        self.assertEqual([row["id"] for row in sorted_rows], [1])

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

    def test_down_arrow_and_enter_select_sort_column(self) -> None:
        browser = _JobBrowser(FakeScreen(), repository=object())
        browser.mode = "sort"

        should_exit = browser._handle_sort_key(curses.KEY_DOWN)

        self.assertFalse(should_exit)
        self.assertEqual(browser.mode, "sort")
        self.assertEqual(browser.sort_column, "company_name")

        should_exit = browser._handle_sort_key(curses.KEY_ENTER)

        self.assertFalse(should_exit)
        self.assertEqual(browser.mode, "list")
        self.assertEqual(browser.sort_column, "company_name")
        self.assertFalse(browser.sort_reverse)

    def test_up_arrow_selects_previous_sort_column(self) -> None:
        browser = _JobBrowser(FakeScreen(), repository=object())
        browser.mode = "sort"
        browser.sort_column = "job_title"

        should_exit = browser._handle_sort_key(curses.KEY_UP)

        self.assertFalse(should_exit)
        self.assertEqual(browser.mode, "sort")
        self.assertEqual(browser.sort_column, "company_name")

    def test_sort_selector_draws_interactive_arrow_hint(self) -> None:
        screen = RecordingScreen()
        browser = _JobBrowser(screen, repository=object())
        browser.mode = "sort"

        browser._draw([])

        self.assertIn("Up/Down choose  Enter apply", screen.lines[1])


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

    def test_backspace_deletes_last_character_even_when_search_is_not_focused(self) -> None:
        browser = _JobBrowser(FakeScreen(), repository=object())
        browser.query = "remote"
        browser.selected = 2

        should_quit = browser._handle_list_key(curses.KEY_BACKSPACE, [])

        self.assertFalse(should_quit)
        self.assertEqual(browser.query, "remot")
        self.assertEqual(browser.selected, 0)

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
        row = {
            "id": 42,
            "publish_date": "2026-05-24",
            "company_name": "Example Systems",
            "job_title": "Staff Engineer",
            "salary_range": "",
            "url": "https://example.com/jobs/staff",
            "last_update": "",
            "job_description": "Build systems.",
            "is_read": 0,
        }
        repository = ReadRepository([row])
        browser = _JobBrowser(FakeScreen(), repository=repository)
        browser.detail_scroll = 3

        should_quit = browser._handle_list_key(curses.KEY_RIGHT, [row])

        self.assertFalse(should_quit)
        self.assertEqual(browser.mode, "detail")
        self.assertEqual(browser.detail_scroll, 0)
        self.assertEqual(repository.read_ids, [42])

    def test_enter_from_list_opens_details_without_opening_url(self) -> None:
        row = {
            "id": 42,
            "publish_date": "2026-05-24",
            "company_name": "Example Systems",
            "job_title": "Staff Engineer",
            "salary_range": "",
            "url": "https://example.com/jobs/staff",
            "last_update": "",
            "job_description": "Build systems.",
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

    def test_backspace_after_entering_detail_does_not_toggle_expired_state(self) -> None:
        row = {
            "id": 42,
            "publish_date": "2026-05-24",
            "company_name": "Example Systems",
            "job_title": "Staff Engineer",
            "salary_range": "",
            "url": "https://example.com/jobs/staff",
            "last_update": "",
            "job_description": "Build systems.",
            "is_expired": 0,
        }
        repository = FakeRepository([row])
        repository.toggle_expired = lambda job_id: setattr(
            repository,
            "toggled_id",
            job_id,
        ) or True
        screen = KeyScreen([curses.KEY_ENTER, curses.KEY_BACKSPACE, 27, ord("q")])
        browser = _JobBrowser(screen, repository=repository)

        with patch("curses.curs_set"):
            browser.run()

        self.assertIsNone(getattr(repository, "toggled_id", None))

    def test_backspace_deletes_last_character_when_search_is_focused(self) -> None:
        browser = _JobBrowser(FakeScreen(), repository=object())
        browser.search_active = True
        browser.query = "remote"
        browser.selected = 2

        should_quit = browser._handle_list_key(curses.KEY_BACKSPACE, [])

        self.assertFalse(should_quit)
        self.assertTrue(browser.search_active)
        self.assertEqual(browser.query, "remot")
        self.assertEqual(browser.selected, 0)

    def test_backspace_does_not_toggle_selected_job_expired_state(self) -> None:
        repository = ToggleRepository()
        browser = _JobBrowser(FakeScreen(), repository=repository)
        browser.selected = 1
        rows = [
            {"id": 41, "is_expired": 0},
            {"id": 42, "is_expired": 0},
        ]

        should_quit = browser._handle_list_key(curses.KEY_BACKSPACE, rows)

        self.assertFalse(should_quit)
        self.assertEqual(repository.toggled_ids, [])

    def test_delete_toggles_selected_job_expired_state(self) -> None:
        repository = ToggleRepository()
        browser = _JobBrowser(FakeScreen(), repository=repository)
        browser.selected = 1
        rows = [
            {"id": 41, "is_expired": 0},
            {"id": 42, "is_expired": 0},
        ]

        should_quit = browser._handle_list_key(curses.KEY_DC, rows)

        self.assertFalse(should_quit)
        self.assertEqual(repository.toggled_ids, [42])

    def test_space_does_not_toggle_selected_job_expired_state(self) -> None:
        repository = ToggleRepository()
        browser = _JobBrowser(FakeScreen(), repository=repository)
        browser.selected = 1
        rows = [
            {"id": 41, "is_expired": 0},
            {"id": 42, "is_expired": 0},
        ]

        should_quit = browser._handle_list_key(ord(" "), rows)

        self.assertFalse(should_quit)
        self.assertEqual(repository.toggled_ids, [])

    def test_s_toggles_selected_job_starred_state(self) -> None:
        repository = ToggleRepository()
        browser = _JobBrowser(FakeScreen(), repository=repository)
        browser.selected = 1
        rows = [
            {"id": 41, "is_starred": 0},
            {"id": 42, "is_starred": 0},
        ]

        should_quit = browser._handle_list_key(ord("s"), rows)

        self.assertFalse(should_quit)
        self.assertEqual(repository.starred_ids, [42])

    def test_p_prompts_before_pruning_expired_jobs_from_list(self) -> None:
        repository = PruneRepository()
        browser = _JobBrowser(FakeScreen(), repository=repository)
        browser.list_rows = [{"id": 41, "is_expired": 1}]

        should_quit = browser._handle_list_key(ord("p"), browser.list_rows)

        self.assertFalse(should_quit)
        self.assertEqual(repository.prune_count, 0)
        self.assertEqual(
            browser.status_message,
            "Prune all expired jobs? [y/N]",
        )
        self.assertIsNotNone(browser.list_rows)

    def test_uppercase_y_confirms_pruning_expired_jobs_from_list(self) -> None:
        repository = PruneRepository()
        browser = _JobBrowser(FakeScreen(), repository=repository)
        browser.list_rows = [{"id": 41, "is_expired": 1}]

        browser._handle_list_key(ord("p"), browser.list_rows)
        should_quit = browser._handle_list_key(ord("Y"), browser.list_rows)

        self.assertFalse(should_quit)
        self.assertEqual(repository.prune_count, 1)
        self.assertIsNone(browser.list_rows)
        self.assertEqual(browser.status_message, "Pruned 2 expired jobs.")

    def test_lowercase_y_confirms_pruning_expired_jobs_from_list(self) -> None:
        repository = PruneRepository()
        browser = _JobBrowser(FakeScreen(), repository=repository)
        browser.list_rows = [{"id": 41, "is_expired": 1}]

        browser._handle_list_key(ord("p"), browser.list_rows)
        should_quit = browser._handle_list_key(ord("y"), browser.list_rows)

        self.assertFalse(should_quit)
        self.assertEqual(repository.prune_count, 1)
        self.assertIsNone(browser.list_rows)
        self.assertEqual(browser.status_message, "Pruned 2 expired jobs.")

    def test_non_y_cancels_pruning_expired_jobs_from_list(self) -> None:
        repository = PruneRepository()
        browser = _JobBrowser(FakeScreen(), repository=repository)
        browser.list_rows = [{"id": 41, "is_expired": 1}]

        browser._handle_list_key(ord("p"), browser.list_rows)
        should_quit = browser._handle_list_key(ord("n"), browser.list_rows)

        self.assertFalse(should_quit)
        self.assertEqual(repository.prune_count, 0)
        self.assertIsNotNone(browser.list_rows)
        self.assertEqual(browser.status_message, "Prune canceled.")

    def test_toggle_keeps_list_order_until_leaving_list(self) -> None:
        repository = ToggleSearchRepository()
        screen = KeyScreen([curses.KEY_DOWN, curses.KEY_DC, ord("q")])
        browser = _JobBrowser(screen, repository=repository)
        original_draw_list = browser._draw_list

        def record_draw(rows: list[dict[str, object]]) -> None:
            screen.drawn_lists.append([int(row["id"]) for row in rows])
            original_draw_list(rows)

        browser._draw_list = record_draw

        with patch("curses.curs_set"):
            browser.run()

        self.assertEqual(screen.drawn_lists, [[1, 2, 3], [1, 2, 3], [1, 2, 3]])

    def test_star_toggle_keeps_list_order_until_leaving_list(self) -> None:
        repository = ToggleSearchRepository()
        screen = KeyScreen([curses.KEY_DOWN, ord("s"), ord("q")])
        browser = _JobBrowser(screen, repository=repository)
        original_draw_list = browser._draw_list

        def record_draw(rows: list[dict[str, object]]) -> None:
            screen.drawn_lists.append([int(row["id"]) for row in rows])
            original_draw_list(rows)

        browser._draw_list = record_draw

        with patch("curses.curs_set"):
            browser.run()

        self.assertEqual(screen.drawn_lists, [[1, 2, 3], [1, 2, 3], [1, 2, 3]])

    def test_r_refreshes_list_rows(self) -> None:
        repository = RefreshingRepository()
        screen = KeyScreen([ord("r"), ord("q")])
        browser = _JobBrowser(screen, repository=repository)
        original_draw_list = browser._draw_list

        def record_draw(rows: list[dict[str, object]]) -> None:
            screen.drawn_lists.append([int(row["id"]) for row in rows])
            original_draw_list(rows)

        browser._draw_list = record_draw

        with patch("curses.curs_set"):
            browser.run()

        self.assertEqual(screen.drawn_lists, [[1], [2]])

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
            "job_description": "\n".join(f"Line {index}" for index in range(30)),
        }

        should_quit = browser._handle_detail_key(curses.KEY_END, row)

        self.assertFalse(should_quit)
        self.assertEqual(browser.detail_scroll, 16)

        should_quit = browser._handle_detail_key(curses.KEY_HOME, row)

        self.assertFalse(should_quit)
        self.assertEqual(browser.detail_scroll, 0)

    def test_backspace_does_not_toggle_current_job_expired_state_from_detail(self) -> None:
        repository = ToggleRepository()
        browser = _JobBrowser(FakeScreen(), repository=repository)
        browser.mode = "detail"

        should_quit = browser._handle_detail_key(curses.KEY_BACKSPACE, {"id": 42})

        self.assertFalse(should_quit)
        self.assertEqual(repository.toggled_ids, [])

    def test_delete_toggles_current_job_expired_state_from_detail(self) -> None:
        repository = ToggleRepository()
        browser = _JobBrowser(FakeScreen(), repository=repository)
        browser.mode = "detail"

        should_quit = browser._handle_detail_key(curses.KEY_DC, {"id": 42})

        self.assertFalse(should_quit)
        self.assertEqual(repository.toggled_ids, [42])

    def test_space_does_not_toggle_current_job_expired_state_from_detail(self) -> None:
        repository = ToggleRepository()
        browser = _JobBrowser(FakeScreen(), repository=repository)
        browser.mode = "detail"

        should_quit = browser._handle_detail_key(ord(" "), {"id": 42})

        self.assertFalse(should_quit)
        self.assertEqual(repository.toggled_ids, [])

    def test_s_toggles_current_job_starred_state_from_detail(self) -> None:
        repository = ToggleRepository()
        browser = _JobBrowser(FakeScreen(), repository=repository)
        browser.mode = "detail"

        should_quit = browser._handle_detail_key(ord("s"), {"id": 42})

        self.assertFalse(should_quit)
        self.assertEqual(repository.starred_ids, [42])

    def test_v_key_edits_current_job_description_from_detail(self) -> None:
        browser = _JobBrowser(FakeScreen(), repository=object())
        browser.mode = "detail"
        edited_rows = []

        should_quit = browser._handle_detail_key(
            ord("v"),
            {"id": 42, "job_description": "Original description."},
            edit_description=lambda row: edited_rows.append(row),
        )

        self.assertFalse(should_quit)
        self.assertEqual(edited_rows, [{"id": 42, "job_description": "Original description."}])

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
    def test_list_draws_sort_state_in_shortcut_bar(self) -> None:
        screen = WideRecordingScreen()
        browser = _JobBrowser(screen, repository=object())
        browser.sort_column = "job_title"

        browser._draw_list([])

        self.assertNotIn("Sort:", screen.lines.get(0, ""))
        self.assertIn("o Sort (Job Title)", screen.lines[0])
        self.assertNotIn("Sort:", screen.lines[0])

    def test_list_draws_default_sort_state_in_sort_shortcut(self) -> None:
        screen = WideRecordingScreen()
        browser = _JobBrowser(screen, repository=object())

        browser._draw_list([])

        self.assertIn("o Sort (Default)", screen.lines[0])
        self.assertNotIn("Sort:", screen.lines[0])

    def test_list_starts_shortcut_bar_on_top_row(self) -> None:
        screen = WideRecordingScreen()
        browser = _JobBrowser(screen, repository=object())

        browser._draw_list([])

        self.assertIn("/ Search", screen.lines.get(0, ""))
        self.assertNotIn(0, [call.y for call in screen.calls if not call.text])

    def test_active_search_replaces_shortcut_bar(self) -> None:
        screen = RecordingScreen()
        browser = _JobBrowser(screen, repository=object())
        browser.search_active = True
        browser.query = "remote"

        browser._draw_list([])

        self.assertEqual(screen.lines[0], "Search: remote_")
        self.assertNotIn("Typing search", screen.lines[0])

    def test_list_draws_next_page_when_selection_moves_beyond_visible_rows(self) -> None:
        screen = RecordingScreen()
        browser = _JobBrowser(screen, repository=object())
        browser.selected = 21

        browser._draw_list([_row(index) for index in range(26)])

        rendered = "\n".join(screen.lines.values())
        self.assertTrue(
            any(
                line.startswith("    2026-05-24") and "Company 21" in line
                for line in screen.lines.values()
            )
        )
        self.assertNotIn("Company 0", rendered)

    def test_unread_list_draws_far_left_dot_in_red(self) -> None:
        screen = RecordingScreen()
        browser = _JobBrowser(screen, repository=object())
        row = {
            "id": 42,
            "publish_date": "2026-05-24",
            "company_name": "Example Systems",
            "job_title": "Staff Engineer",
            "salary_range": "",
            "url": "",
            "last_update": "",
            "is_read": 0,
        }

        with patch.object(tui.curses, "color_pair", return_value=2048) as color_pair:
            browser._draw_list([row])

        color_pair.assert_any_call(tui._READ_DOT_COLOR_PAIR)
        dot_calls = [
            call
            for call in screen.calls
            if call.y == 3 and call.x == 0 and call.text == "•"
        ]
        self.assertEqual(len(dot_calls), 1)
        self.assertTrue(dot_calls[0].attrs & 2048)

    def test_selected_unread_list_draws_far_left_dot_with_selection_attrs(self) -> None:
        screen = RecordingScreen()
        browser = _JobBrowser(screen, repository=object())
        row = {
            "id": 42,
            "publish_date": "2026-05-24",
            "company_name": "Example Systems",
            "job_title": "Staff Engineer",
            "salary_range": "",
            "url": "",
            "last_update": "",
            "is_read": 0,
        }

        with patch.object(tui.curses, "color_pair", return_value=2048):
            browser._draw_list([row])

        dot_calls = [
            call
            for call in screen.calls
            if call.y == 3 and call.x == 0 and call.text == "•"
        ]
        self.assertEqual(len(dot_calls), 1)
        self.assertTrue(dot_calls[0].attrs & 2048)
        self.assertTrue(dot_calls[0].attrs & curses.A_REVERSE)

    def test_list_help_highlights_all_shortcut_keys(self) -> None:
        screen = WideRecordingScreen()
        browser = _JobBrowser(screen, repository=object())

        browser._draw_list([])

        for key in (
            "/",
            "Delete",
            "o",
            "p",
            "r",
            "s",
            "Enter",
            "Right",
            "Esc",
            "q",
        ):
            calls = [
                call for call in screen.calls if call.y in (0, 1) and call.text == key
            ]
            self.assertTrue(calls, key)
            self.assertTrue(any(call.attrs != curses.A_NORMAL for call in calls), key)

    def test_list_help_names_main_shortcuts(self) -> None:
        screen = WideRecordingScreen()
        browser = _JobBrowser(screen, repository=object())

        browser._draw_list([])

        self.assertIn("/ Search", screen.lines[0])
        self.assertIn("Delete Expire", screen.lines[0])
        self.assertIn("s Star", screen.lines[0])
        self.assertIn("o Sort (Default)", screen.lines[0])
        self.assertIn("p Prune", screen.lines[0])
        self.assertIn("r Refresh", screen.lines[0])
        self.assertIn("Enter/Right Details", screen.lines[0])
        self.assertIn("Esc/q Exit", screen.lines[0])
        self.assertNotIn("Backspace/Delete expire", screen.lines[0])
        self.assertNotIn(1, screen.lines)

    def test_list_help_names_navigation_shortcuts_at_standard_width(self) -> None:
        screen = RecordingScreen()
        browser = _JobBrowser(screen, repository=object())

        browser._draw_list([])

        self.assertIn("Enter/Right Details", screen.lines[1])
        self.assertIn("Esc/q Exit", screen.lines[1])


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
                "job_description": "Build systems.",
            }
        )

        self.assertIn("PgUp/PgDn/Home/End", screen.lines[0])
        self.assertIn("Enter URL", screen.lines[0])
        self.assertIn("G resume", screen.lines[0])
        self.assertIn("Delete expire", screen.lines[0])
        self.assertNotIn("Backspace", screen.lines[0])
        self.assertIn("s star", screen.lines[0])
        self.assertIn("v edit", screen.lines[0])

    def test_detail_draws_shortcut_bar_before_title(self) -> None:
        screen = RecordingScreen()
        browser = _JobBrowser(screen, repository=object())

        browser._draw_detail(
            {
                "id": 42,
                "company_name": "Example Systems",
                "job_title": "Staff Engineer",
                "job_description": "Build systems.",
            }
        )

        self.assertIn("Esc/q/Left", screen.lines[0])
        self.assertEqual(screen.lines[1], "Staff Engineer @ Example Systems")

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
                "job_description": "Build systems.",
            }
        )

        enter_calls = [call for call in screen.calls if call.text == "Enter"]
        self.assertEqual(len(enter_calls), 1)
        self.assertNotEqual(enter_calls[0].attrs, curses.A_NORMAL)

    def test_shortcut_help_line_draws_structured_segments(self) -> None:
        segment_type = getattr(tui, "_ShortcutHelpSegment", None)
        self.assertIsNotNone(segment_type)
        if segment_type is None:
            return

        screen = RecordingScreen()
        browser = _JobBrowser(screen, repository=object())

        browser._add_shortcut_help_line(
            0,
            0,
            (
                segment_type("Enter", is_key=True),
                segment_type(" URL"),
            ),
            80,
        )

        self.assertEqual(screen.lines[0], "Enter URL")
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

    def test_starred_color_uses_terminal_yellow(self) -> None:
        initializer = getattr(tui, "_init_starred_color", None)
        self.assertIsNotNone(initializer)
        if initializer is None:
            return

        with (
            patch.object(tui.curses, "has_colors", return_value=True),
            patch.object(tui.curses, "init_pair") as init_pair,
        ):
            initializer()

        init_pair.assert_called_once_with(
            tui._STARRED_COLOR_PAIR,
            tui.curses.COLOR_YELLOW,
            -1,
        )

    def test_read_dot_color_uses_terminal_red(self) -> None:
        initializer = getattr(tui, "_init_read_dot_color", None)
        self.assertIsNotNone(initializer)
        if initializer is None:
            return

        with (
            patch.object(tui.curses, "has_colors", return_value=True),
            patch.object(tui.curses, "init_pair") as init_pair,
        ):
            initializer()

        init_pair.assert_called_once_with(
            tui._READ_DOT_COLOR_PAIR,
            tui.curses.COLOR_RED,
            -1,
        )

    def test_description_color_uses_terminal_background_237(self) -> None:
        initializer = getattr(tui, "_init_description_color", None)
        self.assertIsNotNone(initializer)
        if initializer is None:
            return

        with (
            patch.object(tui.curses, "has_colors", return_value=True),
            patch.object(tui.curses, "init_pair") as init_pair,
            patch.object(tui.curses, "COLORS", 256, create=True),
        ):
            initializer()

        init_pair.assert_called_once_with(tui._DESCRIPTION_COLOR_PAIR, -1, 237)

    def test_g_key_runs_resume_generation_from_detail_view(self) -> None:
        browser = _JobBrowser(FakeScreen(), repository=FakeRepository())
        browser.mode = "detail"
        row = {
            "id": 42,
            "company_name": "Example Systems",
            "job_title": "Staff Engineer",
            "job_description": "Build systems.",
        }
        generated: list[object] = []
        terminal_sessions = []
        result = SimpleNamespace()

        should_quit = browser._handle_detail_key(
            ord("G"),
            row,
            generate=lambda job: generated.append(job) or result,
            run_generator=lambda generation_result: terminal_sessions.append(generation_result),
            show_terminal=lambda operation: operation(),
        )

        self.assertFalse(should_quit)
        self.assertEqual(generated, [row])
        self.assertEqual(terminal_sessions, [result])
        self.assertEqual(browser.mode, "detail")
        self.assertEqual(browser.status_message, "Resume generation finished")

    def test_g_key_reports_resume_generation_failure(self) -> None:
        browser = _JobBrowser(FakeScreen(), repository=FakeRepository())
        browser.mode = "detail"

        should_quit = browser._handle_detail_key(
            ord("G"),
            {
                "id": 42,
                "company_name": "Example Systems",
                "job_title": "Staff Engineer",
                "job_description": "Build systems.",
            },
            generate=lambda job: (_ for _ in ()).throw(FileNotFoundError("missing AGENTS.md")),
        )

        self.assertFalse(should_quit)
        self.assertEqual(browser.mode, "detail")
        self.assertIn("Resume generation failed: missing AGENTS.md", browser.status_message)

    def test_edit_description_runs_editor_and_saves_changed_description(self) -> None:
        repository = DescriptionRepository()
        browser = _JobBrowser(FakeScreen(), repository=repository)

        def editor(command, **_kwargs):
            with open(command[-1], "w", encoding="utf-8") as handle:
                handle.write("Edited description.\n")

        browser._edit_job_description(
            {"id": 42, "job_description": "Original description."},
            editor_command="fake-editor",
            runner=editor,
            show_terminal=lambda operation: operation(),
        )

        self.assertEqual(repository.updated_descriptions, [(42, "Edited description.")])
        self.assertEqual(browser.detail_job_id, 42)
        self.assertEqual(browser.status_message, "Description updated.")

    def test_edit_description_reports_missing_editor(self) -> None:
        repository = DescriptionRepository()
        browser = _JobBrowser(FakeScreen(), repository=repository)

        browser._edit_job_description(
            {"id": 42, "job_description": "Original description."},
            editor_command="",
        )

        self.assertEqual(repository.updated_descriptions, [])
        self.assertEqual(browser.status_message, "EDITOR is not set.")

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
                    "job_description": "Build systems.",
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
                        "job_description": "Build systems.",
                    },
                    opener=lambda _command, **kwargs: (
                        launched_kwargs.append(kwargs)
                        or SimpleNamespace(returncode=0, stdout="out", stderr="err")
                    ),
                )

        self.assertFalse(should_quit)
        self.assertEqual(
            launched_kwargs,
            [{"stdout": subprocess.PIPE, "stderr": subprocess.PIPE, "text": True}],
        )
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
                        "job_description": "Build systems.",
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

    def test_opening_job_url_does_not_wait_for_long_running_browser(self) -> None:
        browser = _JobBrowser(FakeScreen(), repository=FakeRepository())
        browser.mode = "detail"

        class LongRunningBrowser:
            returncode = None

            def __init__(self) -> None:
                self.wait_timeout = None

            def communicate(self, timeout=None):
                self.wait_timeout = timeout
                raise subprocess.TimeoutExpired(["firefox"], timeout)

        process = LongRunningBrowser()
        launched_processes = []

        with patch.dict(os.environ, {"BROWSER": "firefox --new-tab"}):
            should_quit = browser._handle_detail_key(
                curses.KEY_ENTER,
                {
                    "id": 42,
                    "company_name": "Example Systems",
                    "job_title": "Staff Engineer",
                    "url": "https://example.com/jobs/staff",
                    "job_description": "Build systems.",
                },
                opener=lambda _command, **_kwargs: (
                    launched_processes.append(process) or process
                ),
            )

        self.assertFalse(should_quit)
        self.assertEqual(launched_processes, [process])
        self.assertIsNotNone(process.wait_timeout)
        self.assertEqual(
            browser.status_message,
            "Opened URL: https://example.com/jobs/staff",
        )

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
                    "job_description": "Build systems.",
                },
                opener=lambda command, **_kwargs: (
                    launched_commands.append(command)
                    or SimpleNamespace(returncode=0, stdout="", stderr="")
                ),
            )

        self.assertFalse(should_quit)
        self.assertEqual(launched_commands, [])

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
                "job_description": "\n".join(
                    [
                        "First description line.",
                        "Second description line.",
                        "Third description line.",
                    ]
                ),
            }
        )

        rendered = "\n".join(screen.lines.values())
        self.assertEqual(screen.lines[1].rstrip(), "Staff Engineer @ Example Systems")
        self.assertEqual(screen.lines[2].rstrip(), "https://example.com/jobs/staff")

        label_values = (
            ("ID:", "42"),
            ("Published date:", "2026-05-24"),
            ("Salary range:", "$180k-$220k"),
            ("Last update:", "2026-05-24T12:20:01-07:00"),
        )
        value_columns = []
        for y, (label, value) in zip((4, 5, 6, 7), label_values):
            line = screen.lines[y]
            self.assertIn(label, line)
            self.assertIn(value, line)
            value_columns.append(line.index(value))

        self.assertEqual(len(set(value_columns)), 1)
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
                "job_description": "Build systems.",
                "is_expired": 1,
            }
        )

        job_calls = [
            call
            for call in screen.calls
            if call.y in {1, 3, 4, 5, 6, 7, 9, 10} and call.text.strip()
        ]
        self.assertTrue(job_calls)
        self.assertTrue(all(call.attrs & curses.A_DIM for call in job_calls))
        self.assertTrue(all("\u0336" in call.text for call in job_calls))
        self.assertNotIn(" \u0336", "\n".join(call.text for call in job_calls))

    def test_starred_detail_basic_info_uses_yellow_attrs(self) -> None:
        screen = RecordingScreen()
        browser = _JobBrowser(screen, repository=object())

        def color_pair_value(pair: int) -> int:
            if pair == tui._STARRED_COLOR_PAIR:
                return 512
            return 1024

        with patch.object(tui.curses, "color_pair", side_effect=color_pair_value) as color_pair:
            browser._draw_detail(
                {
                    "id": 42,
                    "publish_date": "2026-05-24",
                    "company_name": "Example Systems",
                    "job_title": "Staff Engineer",
                    "url": "https://example.com/jobs/staff",
                    "salary_range": "$180k-$220k",
                    "last_update": "2026-05-24T12:20:01-07:00",
                    "job_description": "Build systems.",
                    "is_starred": 1,
                }
            )

        basic_info_calls = [
            call for call in screen.calls if call.y in {1, 3, 4, 5, 6, 7}
        ]
        description_calls = [
            call for call in screen.calls if call.y in {9, 10}
        ]
        self.assertTrue(basic_info_calls)
        self.assertTrue(description_calls)
        self.assertTrue(all(call.attrs & 512 for call in basic_info_calls))
        self.assertTrue(all(not call.attrs & 512 for call in description_calls))
        self.assertTrue(all(call.attrs & 1024 for call in description_calls))
        self.assertGreaterEqual(color_pair.call_count, len(basic_info_calls))

    def test_detail_description_uses_background_color_attrs(self) -> None:
        screen = RecordingScreen()
        browser = _JobBrowser(screen, repository=object())

        with patch.object(tui.curses, "color_pair", return_value=1024) as color_pair:
            browser._draw_detail(
                {
                    "id": 42,
                    "publish_date": "2026-05-24",
                    "company_name": "Example Systems",
                    "job_title": "Staff Engineer",
                    "url": "https://example.com/jobs/staff",
                    "salary_range": "$180k-$220k",
                    "last_update": "2026-05-24T12:20:01-07:00",
                    "job_description": "Build systems.",
                }
            )

        description_calls = [
            call for call in screen.calls if call.y in {9, 10}
        ]
        self.assertTrue(description_calls)
        self.assertTrue(all(call.attrs & 1024 for call in description_calls))
        color_pair.assert_called_with(tui._DESCRIPTION_COLOR_PAIR)

    def test_detail_description_background_fills_whole_region(self) -> None:
        screen = RecordingScreen()
        browser = _JobBrowser(screen, repository=object())

        with patch.object(tui.curses, "color_pair", return_value=1024):
            browser._draw_detail(
                {
                    "id": 42,
                    "publish_date": "2026-05-24",
                    "company_name": "Example Systems",
                    "job_title": "Staff Engineer",
                    "url": "https://example.com/jobs/staff",
                    "salary_range": "$180k-$220k",
                    "last_update": "2026-05-24T12:20:01-07:00",
                    "job_description": "Build systems.",
                }
            )

        background_calls = [
            call
            for call in screen.calls
            if 9 <= call.y < 24 and call.text == " " * 79
        ]
        self.assertEqual([call.y for call in background_calls], list(range(9, 24)))
        self.assertTrue(all(call.attrs & 1024 for call in background_calls))

    def test_pruned_detail_text_uses_dim_attrs_and_strikethrough_text(self) -> None:
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
                "job_description": "Build systems.",
                "is_pruned": 1,
            }
        )

        job_calls = [
            call
            for call in screen.calls
            if call.y in {1, 3, 4, 5, 6, 7, 9, 10} and call.text.strip()
        ]
        self.assertTrue(job_calls)
        self.assertTrue(all(call.attrs & curses.A_DIM for call in job_calls))
        self.assertTrue(all("\u0336" in call.text for call in job_calls))

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
                "job_description": "Build systems.",
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

    def test_list_status_message_renders_inverted_in_bottom_left_corner(self) -> None:
        screen = RecordingScreen()
        browser = _JobBrowser(screen, repository=object())
        browser.status_message = "Prune all expired jobs? [y/N]"

        browser._draw_list([])

        status_call = screen.calls[-1]
        self.assertEqual(status_call.y, screen.getmaxyx()[0] - 1)
        self.assertEqual(status_call.x, 0)
        self.assertEqual(
            status_call.text,
            "Prune all expired jobs? [y/N]",
        )
        self.assertTrue(status_call.attrs & curses.A_REVERSE)

    def test_detail_description_soft_wraps_at_120_characters(self) -> None:
        row = {
            "job_description": " ".join(["platform"] * 40),
        }

        lines = tui._detail_description_lines(row, 200)

        self.assertGreater(len(lines), 1)
        self.assertLessEqual(max(len(line) for line in lines), 120)


if __name__ == "__main__":
    unittest.main()
