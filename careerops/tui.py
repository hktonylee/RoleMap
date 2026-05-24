from __future__ import annotations

import curses
import textwrap
from collections.abc import Sequence

from careerops.jobs import JobRepository, JobRow


_COLUMN_GAP = "  "
_LIST_PREFIX_WIDTH = 2
_SORT_COLUMNS = (
    ("p", "publish_date", "Publish date"),
    ("c", "company_name", "Company"),
    ("t", "job_title", "Job title"),
    ("s", "salary_range", "Salary"),
    ("u", "url", "URL"),
    ("l", "last_update", "Last update"),
)
_SORT_COLUMN_BY_KEY = {key: column for key, column, _label in _SORT_COLUMNS}
_SORT_LABEL_BY_COLUMN = {column: label for _key, column, label in _SORT_COLUMNS}
_DETAIL_DESCRIPTION_START_ROW = 10


def run(repository: JobRepository, initial_query: str = "") -> None:
    curses.wrapper(lambda stdscr: _JobBrowser(stdscr, repository, initial_query).run())


def _list_column_widths(total_width: int) -> tuple[int, int, int, int]:
    usable_width = max(0, total_width - 1 - _LIST_PREFIX_WIDTH)
    gap_width = len(_COLUMN_GAP) * 3
    content_width = max(0, usable_width - gap_width)

    publish_width = 12 if content_width >= 50 else max(8, content_width // 6)
    company_width = min(24, max(12, content_width // 4))
    title_width = min(36, max(16, content_width // 3))
    other_width = max(10, content_width - publish_width - company_width - title_width)
    return publish_width, company_width, title_width, other_width


def _format_list_header(widths: tuple[int, int, int, int]) -> str:
    publish_width, company_width, title_width, other_width = widths
    return (
        " " * _LIST_PREFIX_WIDTH
        + _format_cell("Publish date", publish_width)
        + _COLUMN_GAP
        + _format_cell("Company", company_width)
        + _COLUMN_GAP
        + _format_cell("Job title", title_width)
        + _COLUMN_GAP
        + _format_cell("Other", other_width)
    )


def _sort_list_rows(rows: Sequence[JobRow], column: str | None) -> list[JobRow]:
    if column is None:
        return list(rows)
    return sorted(rows, key=lambda row: _sort_value(row, column))


def _sort_value(row: JobRow, column: str) -> tuple[bool, str]:
    text = _row_text(row, column)
    return text == "", text.casefold()


def _format_list_row(
    row: JobRow,
    widths: tuple[int, int, int, int],
    selected: bool,
) -> str:
    publish_width, company_width, title_width, other_width = widths
    marker = ">" if selected else " "
    return (
        f"{marker} "
        + _format_cell(_row_text(row, "publish_date"), publish_width)
        + _COLUMN_GAP
        + _format_cell(_row_text(row, "company_name"), company_width)
        + _COLUMN_GAP
        + _format_cell(_row_text(row, "job_title"), title_width)
        + _COLUMN_GAP
        + _format_cell(_format_other_information(row), other_width)
    )


def _format_other_information(row: JobRow) -> str:
    last_update = _row_text(row, "last_update")
    values = [
        _row_text(row, "salary_range"),
        _row_text(row, "url"),
        f"Updated {last_update}" if last_update else "",
    ]
    return " | ".join(value for value in values if value)


def _row_text(row: JobRow, key: str) -> str:
    value = row[key]
    if value is None:
        return ""
    return str(value)


def _format_cell(value: object, width: int) -> str:
    text = str(value)
    if len(text) > width:
        return text[: max(0, width - 3)] + "..."
    return text.ljust(width)


def _detail_description_lines(row: JobRow, width: int) -> list[str]:
    lines = []
    for paragraph in _row_text(row, "description").splitlines() or [""]:
        lines.extend(textwrap.wrap(paragraph, width=max(20, width - 2)) or [""])
    return lines


class _JobBrowser:
    def __init__(
        self,
        stdscr: curses.window,
        repository: JobRepository,
        initial_query: str = "",
    ) -> None:
        self.stdscr = stdscr
        self.repository = repository
        self.query = initial_query
        self.selected = 0
        self.mode = "list"
        self.sort_column: str | None = None
        self.detail_scroll = 0

    def run(self) -> None:
        curses.curs_set(0)
        self.stdscr.keypad(True)
        while True:
            rows = _sort_list_rows(self.repository.search(self.query), self.sort_column)
            if self.selected >= len(rows):
                self.selected = max(0, len(rows) - 1)

            self._draw(rows)
            key = self.stdscr.getch()
            if self.mode == "list" and self._handle_list_key(key, rows):
                return
            if self.mode == "sort" and self._handle_sort_key(key):
                return
            row = rows[self.selected] if self.mode == "detail" and rows else None
            if self.mode == "detail" and self._handle_detail_key(key, row):
                return

    def _draw(self, rows: Sequence[JobRow]) -> None:
        self.stdscr.erase()
        if self.mode == "detail" and rows:
            self._draw_detail(rows[self.selected])
        elif self.mode == "sort":
            self._draw_sort_selector()
        else:
            self._draw_list(rows)
        self.stdscr.refresh()

    def _draw_list(self, rows: Sequence[JobRow]) -> None:
        height, width = self.stdscr.getmaxyx()
        self._add_line(0, 0, f"Search: {self.query}", width, curses.A_BOLD)
        sort_label = _SORT_LABEL_BY_COLUMN.get(self.sort_column, "Default")
        self._add_line(
            1,
            0,
            f"Sort: {sort_label}  o sort  Enter/Right details  Esc/q quit  Up/Down move",
            width,
        )

        if not rows:
            self._add_line(3, 0, "No jobs found.", width)
            return

        widths = _list_column_widths(width)
        self._add_line(3, 0, _format_list_header(widths), width, curses.A_BOLD)

        for index, row in enumerate(rows[: max(0, height - 4)]):
            line = _format_list_row(row, widths, selected=index == self.selected)
            attrs = curses.A_REVERSE if index == self.selected else curses.A_NORMAL
            self._add_line(index + 4, 0, line, width, attrs)

    def _draw_sort_selector(self) -> None:
        _height, width = self.stdscr.getmaxyx()
        self._add_line(0, 0, "Choose sort column", width, curses.A_BOLD)
        self._add_line(1, 0, "Esc/q cancel", width)
        for index, (key, column, label) in enumerate(_SORT_COLUMNS, start=3):
            marker = "*" if column == self.sort_column else " "
            self._add_line(index, 0, f"{marker} {key}  {label}", width)

    def _draw_detail(self, row: JobRow) -> None:
        height, width = self.stdscr.getmaxyx()
        title = f"{_row_text(row, 'company_name')} - {_row_text(row, 'job_title')}"
        self._add_line(0, 0, title, width, curses.A_BOLD)
        self._add_line(1, 0, "Esc/q/Left back  Up/Down/PgUp/PgDn/Home/End scroll", width)

        self._add_line(3, 0, f"ID: {_row_text(row, 'id')}", width)
        self._add_line(4, 0, f"Publish date: {_row_text(row, 'publish_date')}", width)
        self._add_line(5, 0, f"URL: {_row_text(row, 'url')}", width)
        self._add_line(6, 0, f"Salary range: {_row_text(row, 'salary_range')}", width)
        self._add_line(7, 0, f"Last update: {_row_text(row, 'last_update')}", width)
        self._add_line(9, 0, "Description:", width)

        lines = _detail_description_lines(row, width)
        visible = lines[
            self.detail_scroll : self.detail_scroll
            + max(0, height - _DETAIL_DESCRIPTION_START_ROW)
        ]
        for index, line in enumerate(visible, start=_DETAIL_DESCRIPTION_START_ROW):
            self._add_line(index, 0, line, width)

    def _handle_list_key(self, key: int, rows: Sequence[JobRow]) -> bool:
        if key in (ord("q"), 27):
            return True
        if key in (curses.KEY_DOWN, 14):
            self.selected = min(self.selected + 1, max(0, len(rows) - 1))
            return False
        if key in (curses.KEY_UP, 16):
            self.selected = max(0, self.selected - 1)
            return False
        if key in (curses.KEY_ENTER, curses.KEY_RIGHT, 10, 13) and rows:
            self.mode = "detail"
            self.detail_scroll = 0
            return False
        if key == ord("o"):
            self.mode = "sort"
            return False
        if key in (curses.KEY_BACKSPACE, 127, 8):
            self.query = self.query[:-1]
            self.selected = 0
            return False
        if 32 <= key <= 126:
            self.query += chr(key)
            self.selected = 0
        return False

    def _handle_sort_key(self, key: int) -> bool:
        if key in (ord("q"), 27):
            self.mode = "list"
            return False
        column = _SORT_COLUMN_BY_KEY.get(chr(key).lower()) if 0 <= key <= 255 else None
        if column is None:
            return False
        self.sort_column = column
        self.selected = 0
        self.mode = "list"
        return False

    def _handle_detail_key(self, key: int, row: JobRow | None = None) -> bool:
        if key in (ord("q"), 27, curses.KEY_LEFT):
            self.mode = "list"
            return False
        height, width = self.stdscr.getmaxyx()
        visible_height = max(0, height - _DETAIL_DESCRIPTION_START_ROW)
        page_step = max(1, visible_height // 2)
        if key == curses.KEY_NPAGE:
            self.detail_scroll += page_step
            return False
        if key == curses.KEY_PPAGE:
            self.detail_scroll = max(0, self.detail_scroll - page_step)
            return False
        if key == curses.KEY_HOME:
            self.detail_scroll = 0
            return False
        if key == curses.KEY_END and row is not None:
            self.detail_scroll = max(
                0,
                len(_detail_description_lines(row, width)) - visible_height,
            )
            return False
        if key == curses.KEY_DOWN:
            self.detail_scroll += 1
            return False
        if key == curses.KEY_UP:
            self.detail_scroll = max(0, self.detail_scroll - 1)
            return False
        return False

    def _add_line(
        self,
        y: int,
        x: int,
        text: str,
        width: int,
        attrs: int = curses.A_NORMAL,
    ) -> None:
        if y >= self.stdscr.getmaxyx()[0]:
            return
        clipped = text[: max(0, width - 1)]
        try:
            self.stdscr.addstr(y, x, clipped, attrs)
        except curses.error:
            pass
