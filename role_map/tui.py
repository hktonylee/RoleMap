from __future__ import annotations

import curses
import os
import shlex
import subprocess
import sys
import tempfile
import textwrap
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from role_map.jobs import JobRepository, JobRow
from role_map.resumes import generate_resume, run_resume_generator


_COLUMN_GAP = "  "
_READ_DOT_PREFIX_WIDTH = 2
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
_SORT_INDEX_BY_COLUMN = {
    column: index for index, (_key, column, _label) in enumerate(_SORT_COLUMNS)
}
_DETAIL_DESCRIPTION_START_ROW = 10
_DETAIL_DESCRIPTION_WRAP_WIDTH = 120
_LIST_FIRST_ROW = 3
_STRIKETHROUGH_MARK = "\u0336"
_BACKSPACE_KEYS = (curses.KEY_BACKSPACE, 127, 8)
_DELETE_KEYS = (curses.KEY_DC,)
_SEARCH_DELETE_KEYS = _BACKSPACE_KEYS + _DELETE_KEYS
_SHORTCUT_KEY_COLOR_PAIR = 1
_SHORTCUT_KEY_ORANGE = 208
_BROWSER_OPEN_WAIT_SECONDS = 1.0
_STARRED_COLOR_PAIR = 2
_DESCRIPTION_COLOR_PAIR = 3
_DESCRIPTION_BACKGROUND = 237
_READ_DOT_COLOR_PAIR = 4
_SELECTED_READ_DOT_COLOR_PAIR = 5


@dataclass(frozen=True)
class _ShortcutHelpSegment:
    text: str
    is_key: bool = False


def _shortcut_key(text: str) -> _ShortcutHelpSegment:
    return _ShortcutHelpSegment(text, is_key=True)


def _shortcut_text(text: str) -> _ShortcutHelpSegment:
    return _ShortcutHelpSegment(text)


def _shortcut_segments_width(segments: Sequence[_ShortcutHelpSegment]) -> int:
    return sum(len(segment.text) for segment in segments)


def run(repository: JobRepository, initial_query: str = "") -> None:
    curses.wrapper(lambda stdscr: _JobBrowser(stdscr, repository, initial_query).run())


def _init_shortcut_key_color() -> None:
    try:
        curses.start_color()
        curses.use_default_colors()
        if not curses.has_colors():
            return
        orange = (
            _SHORTCUT_KEY_ORANGE
            if getattr(curses, "COLORS", 0) > _SHORTCUT_KEY_ORANGE
            else curses.COLOR_YELLOW
        )
        curses.init_pair(_SHORTCUT_KEY_COLOR_PAIR, orange, -1)
    except curses.error:
        pass


def _init_starred_color() -> None:
    try:
        if not curses.has_colors():
            return
        curses.init_pair(_STARRED_COLOR_PAIR, curses.COLOR_YELLOW, -1)
    except curses.error:
        pass


def _init_description_color() -> None:
    try:
        if not curses.has_colors() or getattr(curses, "COLORS", 0) <= _DESCRIPTION_BACKGROUND:
            return
        curses.init_pair(_DESCRIPTION_COLOR_PAIR, -1, _DESCRIPTION_BACKGROUND)
    except curses.error:
        pass


def _init_read_dot_color() -> None:
    try:
        if not curses.has_colors():
            return
        curses.init_pair(_READ_DOT_COLOR_PAIR, curses.COLOR_RED, -1)
        curses.init_pair(_SELECTED_READ_DOT_COLOR_PAIR, -1, curses.COLOR_RED)
    except curses.error:
        pass


def _enable_mouse_input() -> None:
    events = getattr(curses, "BUTTON1_CLICKED", 0) | getattr(
        curses,
        "BUTTON1_PRESSED",
        0,
    )
    if not events:
        return
    try:
        curses.mousemask(events)
    except curses.error:
        pass


def _shortcut_key_attrs(attrs: int = curses.A_NORMAL) -> int:
    try:
        return attrs | curses.A_BOLD | curses.color_pair(_SHORTCUT_KEY_COLOR_PAIR)
    except curses.error:
        return attrs | curses.A_BOLD


def _list_column_widths(total_width: int) -> tuple[int, int, int, int]:
    usable_width = max(
        0,
        total_width - 1 - _READ_DOT_PREFIX_WIDTH - _LIST_PREFIX_WIDTH,
    )
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
        " " * (_READ_DOT_PREFIX_WIDTH + _LIST_PREFIX_WIDTH)
        + _format_cell("Publish date", publish_width)
        + _COLUMN_GAP
        + _format_cell("Company", company_width)
        + _COLUMN_GAP
        + _format_cell("Job title", title_width)
        + _COLUMN_GAP
        + _format_cell("Other", other_width)
    )


def _sort_list_rows(
    rows: Sequence[JobRow],
    column: str | None,
    reverse: bool = False,
) -> list[JobRow]:
    visible_rows = [row for row in rows if not _row_is_pruned(row)]
    active = [row for row in visible_rows if not _row_is_expired(row)]
    expired = [row for row in visible_rows if _row_is_expired(row)]
    if column is None:
        return active + expired
    return _sort_list_group(active, column, reverse) + _sort_list_group(
        expired,
        column,
        reverse,
    )


def _sort_list_group(
    rows: Sequence[JobRow],
    column: str,
    reverse: bool,
) -> list[JobRow]:
    populated = [row for row in rows if _row_text(row, column)]
    empty = [row for row in rows if not _row_text(row, column)]
    return sorted(populated, key=lambda row: _sort_value(row, column), reverse=reverse) + empty


def _sort_value(row: JobRow, column: str) -> tuple[bool, str]:
    text = _row_text(row, column)
    return text == "", text.casefold()


def _format_list_row(
    row: JobRow,
    widths: tuple[int, int, int, int],
    selected: bool,
) -> str:
    publish_width, company_width, title_width, other_width = widths
    read_marker = " " if _row_is_read(row) else "•"
    marker = " "
    line = (
        f"{read_marker} {marker} "
        + _format_cell(_row_text(row, "publish_date"), publish_width)
        + _COLUMN_GAP
        + _format_cell(_row_text(row, "company_name"), company_width)
        + _COLUMN_GAP
        + _format_cell(_row_text(row, "job_title"), title_width)
        + _COLUMN_GAP
        + _format_cell(_format_other_information(row), other_width)
    )
    if _row_is_expired(row):
        return _strikethrough(line)
    return line


def _list_row_attrs(row: JobRow, selected: bool) -> int:
    attrs = curses.A_REVERSE if selected else curses.A_NORMAL
    if _row_is_expired(row):
        attrs |= curses.A_DIM
    return _starred_attrs(row, attrs)


def _detail_text(row: JobRow, text: str) -> str:
    if _row_is_expired(row):
        return _strikethrough(text)
    return text


def _detail_attrs(row: JobRow, attrs: int = curses.A_NORMAL) -> int:
    if _row_is_expired(row):
        attrs |= curses.A_DIM
    return attrs


def _description_attrs(row: JobRow) -> int:
    attrs = _detail_attrs(row)
    try:
        return attrs | curses.color_pair(_DESCRIPTION_COLOR_PAIR)
    except curses.error:
        return attrs


def _basic_detail_attrs(row: JobRow, attrs: int = curses.A_NORMAL) -> int:
    return _starred_attrs(row, _detail_attrs(row, attrs))


def _starred_attrs(row: JobRow, attrs: int = curses.A_NORMAL) -> int:
    if not _row_is_starred(row):
        return attrs
    try:
        return attrs | curses.color_pair(_STARRED_COLOR_PAIR)
    except curses.error:
        return attrs | curses.A_BOLD


def _read_dot_attrs() -> int:
    try:
        return curses.color_pair(_READ_DOT_COLOR_PAIR)
    except curses.error:
        return curses.A_BOLD


def _selected_read_dot_attrs(row_attrs: int) -> int:
    attrs = row_attrs & ~curses.A_COLOR
    try:
        return attrs | curses.color_pair(_SELECTED_READ_DOT_COLOR_PAIR)
    except curses.error:
        return attrs | curses.A_BOLD


def _format_other_information(row: JobRow) -> str:
    values = [
        _row_text(row, "salary_range"),
        _row_text(row, "url"),
    ]
    return " | ".join(value for value in values if value)


def _row_text(row: JobRow, key: str) -> str:
    value = _row_value(row, key)
    if value is None:
        return ""
    return str(value)


def _row_id(row: JobRow) -> int | None:
    value = _row_value(row, "id")
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _row_value(row: JobRow, key: str) -> object:
    try:
        return row[key]
    except (IndexError, KeyError, TypeError):
        return None


def _row_is_expired(row: JobRow) -> bool:
    if _row_is_pruned(row):
        return True
    value = _row_value(row, "is_expired")
    if isinstance(value, str):
        return value.strip().casefold() in {"1", "true", "yes"}
    return bool(value)


def _row_is_pruned(row: JobRow) -> bool:
    value = _row_value(row, "is_pruned")
    if isinstance(value, str):
        return value.strip().casefold() in {"1", "true", "yes"}
    return bool(value)


def _row_is_read(row: JobRow) -> bool:
    value = _row_value(row, "is_read")
    if isinstance(value, str):
        return value.strip().casefold() in {"1", "true", "yes"}
    return bool(value)


def _row_is_starred(row: JobRow) -> bool:
    value = _row_value(row, "is_starred")
    if isinstance(value, str):
        return value.strip().casefold() in {"1", "true", "yes"}
    return bool(value)


def _copy_row_with_expired_state(row: JobRow, is_expired: bool) -> dict[str, object]:
    keys_method = getattr(row, "keys", None)
    keys = keys_method() if callable(keys_method) else ()
    values = {str(key): row[str(key)] for key in keys}
    values["is_expired"] = int(is_expired)
    return values


def _copy_row_with_starred_state(row: JobRow, is_starred: bool) -> dict[str, object]:
    keys_method = getattr(row, "keys", None)
    keys = keys_method() if callable(keys_method) else ()
    values = {str(key): row[str(key)] for key in keys}
    values["is_starred"] = int(is_starred)
    return values


def _copy_row_with_read_state(row: JobRow, is_read: bool) -> dict[str, object]:
    keys_method = getattr(row, "keys", None)
    keys = keys_method() if callable(keys_method) else ()
    values = {str(key): row[str(key)] for key in keys}
    values["is_read"] = int(is_read)
    return values


def _strikethrough(value: str) -> str:
    return "".join(
        character if character.isspace() else character + _STRIKETHROUGH_MARK
        for character in value
    )


def _clip_for_terminal(text: str, width: int) -> str:
    visible_limit = max(0, width - 1)
    result = []
    visible_count = 0
    index = 0
    while index < len(text) and visible_count < visible_limit:
        character = text[index]
        result.append(character)
        if character != _STRIKETHROUGH_MARK:
            visible_count += 1
        index += 1
        while index < len(text) and text[index] == _STRIKETHROUGH_MARK:
            result.append(text[index])
            index += 1
    return "".join(result)


def _format_cell(value: object, width: int) -> str:
    text = str(value)
    if len(text) > width:
        return text[: max(0, width - 3)] + "..."
    return text.ljust(width)


def _detail_description_lines(row: JobRow, width: int) -> list[str]:
    lines = []
    wrap_width = min(_DETAIL_DESCRIPTION_WRAP_WIDTH, max(20, width - 2))
    for paragraph in _row_text(row, "job_description").splitlines() or [""]:
        lines.extend(textwrap.wrap(paragraph, width=wrap_width) or [""])
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
        self.sort_reverse = False
        self.sort_selection_index = 0
        self.search_active = False
        self.detail_scroll = 0
        self.detail_job_id: int | None = None
        self.detail_return_index: int | None = None
        self.status_message = ""
        self.prune_confirmation_pending = False
        self.list_rows: list[JobRow] | None = None
        self.selected_row_id: object | None = None

    def run(self) -> None:
        curses.curs_set(0)
        _init_shortcut_key_color()
        _init_starred_color()
        _init_description_color()
        _init_read_dot_color()
        self.stdscr.keypad(True)
        _enable_mouse_input()
        while True:
            rows = self._current_rows()
            self._restore_selected_row(rows)
            self._sync_detail_selection(rows)
            if self.selected >= len(rows):
                self.selected = max(0, len(rows) - 1)

            self._draw(rows)
            key = self.stdscr.getch()
            if self.mode == "list":
                if self._handle_list_key(key, rows):
                    return
            elif self.mode == "sort":
                if self._handle_sort_key(key):
                    return
            elif self.mode == "detail":
                row = rows[self.selected] if rows else None
                if self._handle_detail_key(key, row):
                    return

    def _current_rows(self) -> list[JobRow]:
        if self.mode == "list" and self.list_rows is not None:
            return self.list_rows
        rows = _sort_list_rows(
            self.repository.search(self.query),
            self.sort_column,
            reverse=self.sort_reverse,
        )
        if self.mode == "list":
            self.list_rows = rows
        return rows

    def _restore_selected_row(self, rows: Sequence[JobRow]) -> None:
        if self.selected_row_id is None:
            return
        for index, row in enumerate(rows):
            if _row_value(row, "id") == self.selected_row_id:
                self.selected = index
                break
        self.selected_row_id = None

    def _clear_list_rows(self) -> None:
        self.list_rows = None

    def _replace_cached_expired_state(self, index: int, is_expired: bool) -> None:
        if self.list_rows is None or index >= len(self.list_rows):
            return
        self.list_rows[index] = _copy_row_with_expired_state(
            self.list_rows[index],
            is_expired,
        )

    def _replace_cached_starred_state(self, index: int, is_starred: bool) -> None:
        if self.list_rows is None or index >= len(self.list_rows):
            return
        self.list_rows[index] = _copy_row_with_starred_state(
            self.list_rows[index],
            is_starred,
        )

    def _replace_cached_read_state(self, index: int, is_read: bool) -> None:
        if self.list_rows is None or index >= len(self.list_rows):
            return
        self.list_rows[index] = _copy_row_with_read_state(
            self.list_rows[index],
            is_read,
        )

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
        sort_label = _SORT_LABEL_BY_COLUMN.get(self.sort_column, "Default")
        if self.sort_column is not None and self.sort_reverse:
            sort_label = f"{sort_label} desc"
        sort_shortcut_label = sort_label.title()
        if self.search_active:
            self._add_line(0, 0, f"Search: {self.query}_", width, curses.A_BOLD)
        else:
            primary_shortcuts = (
                _shortcut_key("/"),
                _shortcut_text(" Search "),
                _shortcut_key("o"),
                _shortcut_text(f" Sort ({sort_shortcut_label}) "),
                _shortcut_key("p"),
                _shortcut_text(" Prune "),
                _shortcut_key("q"),
                _shortcut_text(" Exit "),
                _shortcut_key("r"),
                _shortcut_text(" Refresh "),
                _shortcut_key("s"),
                _shortcut_text(" Star "),
                _shortcut_key("u"),
                _shortcut_text(" Unread"),
            )
            navigation_shortcuts = (
                _shortcut_key("Enter"),
                _shortcut_text(" Details "),
                _shortcut_key("Delete"),
                _shortcut_text(" Expire"),
            )
            combined_shortcuts = primary_shortcuts + (
                _shortcut_text(" "),
            ) + navigation_shortcuts
            if _shortcut_segments_width(combined_shortcuts) <= max(0, width - 1):
                self._add_shortcut_help_line(0, 0, combined_shortcuts, width)
            else:
                self._add_shortcut_help_line(0, 0, primary_shortcuts, width)
                self._add_shortcut_help_line(1, 0, navigation_shortcuts, width)

        if not rows:
            self._add_line(2, 0, "No jobs found.", width)
            self._draw_status_message()
            return

        widths = _list_column_widths(width)
        self._add_line(2, 0, _format_list_header(widths), width, curses.A_BOLD)

        visible_count = max(0, height - 3)
        page_start = (
            (self.selected // visible_count) * visible_count if visible_count else 0
        )
        visible_rows = rows[page_start : page_start + visible_count]
        for index, row in enumerate(visible_rows, start=page_start):
            y = index - page_start + _LIST_FIRST_ROW
            line = _format_list_row(row, widths, selected=index == self.selected)
            attrs = _list_row_attrs(row, selected=index == self.selected)
            self._add_line(y, 0, line, width, attrs)
            if not _row_is_read(row):
                dot_attrs = (
                    _selected_read_dot_attrs(attrs)
                    if index == self.selected
                    else _read_dot_attrs()
                )
                self._add_line(y, 0, "•", 2, dot_attrs)
        self._draw_status_message()

    def _draw_sort_selector(self) -> None:
        _height, width = self.stdscr.getmaxyx()
        self._add_line(0, 0, "Choose sort column", width, curses.A_BOLD)
        self._add_shortcut_help_line(
            1,
            0,
            (
                _shortcut_key("Up"),
                _shortcut_text("/"),
                _shortcut_key("Down"),
                _shortcut_text(" choose  "),
                _shortcut_key("Enter"),
                _shortcut_text(" apply  Lowercase asc  Uppercase desc  "),
                _shortcut_key("Esc"),
                _shortcut_text("/"),
                _shortcut_key("q"),
                _shortcut_text(" back"),
            ),
            width,
        )
        for index, (key, column, label) in enumerate(_SORT_COLUMNS, start=3):
            marker = "*" if column == self.sort_column else " "
            cursor = ">" if index - 3 == self.sort_selection_index else " "
            self._add_line(
                index,
                0,
                f"{cursor}{marker} {key}/{key.upper()}  {label}",
                width,
            )

    def _draw_detail(self, row: JobRow) -> None:
        height, width = self.stdscr.getmaxyx()
        title = f"{_row_text(row, 'job_title')} @ {_row_text(row, 'company_name')}"
        self._add_line(
            1,
            0,
            _detail_text(row, title),
            width,
            _basic_detail_attrs(row, curses.A_BOLD),
        )
        self._add_shortcut_help_line(
            0,
            0,
            (
                _shortcut_key("g"),
                _shortcut_text(" Generate Resume "),
                _shortcut_key("q"),
                _shortcut_text(" Go Back "),
                _shortcut_key("s"),
                _shortcut_text(" Star "),
                _shortcut_key("v"),
                _shortcut_text(" Edit "),
                _shortcut_key("Enter"),
                _shortcut_text(" Open URL "),
                _shortcut_key("Delete"),
                _shortcut_text(" Expire"),
            ),
            width,
        )

        detail_attrs = _basic_detail_attrs(row)
        description_attrs = _description_attrs(row)
        for y in range(9, height):
            self._add_line(y, 0, " " * width, width, description_attrs)
        self._add_line(
            2,
            0,
            _detail_text(row, _row_text(row, "url")),
            width,
            detail_attrs,
        )

        detail_rows = (
            ("ID", "id"),
            ("Published date", "publish_date"),
            ("Salary range", "salary_range"),
            ("Last update", "last_update"),
        )
        label_width = max(len(label) + 1 for label, _key in detail_rows)
        for y, (label, key) in enumerate(detail_rows, start=4):
            label_text = f"{label}:"
            self._add_line(
                y,
                0,
                _detail_text(row, f"{label_text:<{label_width}} {_row_text(row, key)}"),
                width,
                detail_attrs,
            )
        self._add_line(
            9,
            0,
            _detail_text(row, "Description:"),
            width,
            description_attrs,
        )

        lines = _detail_description_lines(row, width)
        visible = lines[
            self.detail_scroll : self.detail_scroll
            + max(0, height - _DETAIL_DESCRIPTION_START_ROW)
        ]
        for index, line in enumerate(visible, start=_DETAIL_DESCRIPTION_START_ROW):
            self._add_line(index, 0, _detail_text(row, line), width, description_attrs)
        self._draw_status_message()

    def _handle_list_key(self, key: int, rows: Sequence[JobRow]) -> bool:
        if self.prune_confirmation_pending:
            self.prune_confirmation_pending = False
            if key in (ord("y"), ord("Y")):
                pruned_count = self.repository.prune_expired()
                self._clear_list_rows()
                job_word = "job" if pruned_count == 1 else "jobs"
                self.status_message = f"Pruned {pruned_count} expired {job_word}."
            else:
                self.status_message = "Prune canceled."
            return False
        if self.search_active and self._handle_search_key(key):
            self._clear_list_rows()
            return False
        if key in _BACKSPACE_KEYS:
            self.query = self.query[:-1]
            self.selected = 0
            self._clear_list_rows()
            return False
        if key in (ord("q"), 27):
            self._clear_list_rows()
            return True
        if key in (curses.KEY_DOWN, 14):
            self.selected = min(self.selected + 1, max(0, len(rows) - 1))
            return False
        if key in (curses.KEY_UP, 16):
            self.selected = max(0, self.selected - 1)
            return False
        visible_count = max(1, self.stdscr.getmaxyx()[0] - 4)
        if key == curses.KEY_NPAGE:
            self.selected = min(self.selected + visible_count, max(0, len(rows) - 1))
            return False
        if key == curses.KEY_PPAGE:
            self.selected = max(0, self.selected - visible_count)
            return False
        if key == curses.KEY_HOME:
            self.selected = 0
            return False
        if key == curses.KEY_END:
            self.selected = max(0, len(rows) - 1)
            return False
        if key == curses.KEY_MOUSE and rows:
            self._handle_list_mouse(rows)
            return False
        if key in (curses.KEY_ENTER, curses.KEY_RIGHT, 10, 13) and rows:
            self._open_selected_row_details(rows)
            return False
        if key == ord("o"):
            self.sort_selection_index = _SORT_INDEX_BY_COLUMN.get(
                self.sort_column,
                0,
            )
            self.mode = "sort"
            return False
        if key in _DELETE_KEYS and rows:
            is_expired = self.repository.toggle_expired(int(rows[self.selected]["id"]))
            self._replace_cached_expired_state(self.selected, is_expired)
            return False
        if key == ord("s") and rows:
            is_starred = self.repository.toggle_starred(int(rows[self.selected]["id"]))
            self._replace_cached_starred_state(self.selected, is_starred)
            return False
        if key == ord("u") and rows:
            self.repository.mark_unread(int(rows[self.selected]["id"]))
            self._replace_cached_read_state(self.selected, False)
            return False
        if key == ord("p"):
            self.prune_confirmation_pending = True
            self.status_message = "Prune all expired jobs? [y/N]"
            return False
        if key == ord("r"):
            if rows:
                self.selected_row_id = _row_value(rows[self.selected], "id")
            self._clear_list_rows()
            self.status_message = "Refreshed."
            return False
        if key == ord("/"):
            self.search_active = True
            return False
        return False

    def _handle_list_mouse(self, rows: Sequence[JobRow]) -> None:
        try:
            _mouse_id, x, y, _z, bstate = curses.getmouse()
        except curses.error:
            return
        if x < 0:
            return
        left_click = getattr(curses, "BUTTON1_CLICKED", 0) | getattr(
            curses,
            "BUTTON1_PRESSED",
            0,
        )
        if left_click and bstate and not bstate & left_click:
            return
        row_index = self._list_row_index_at(y, len(rows))
        if row_index is None:
            return
        if row_index == self.selected:
            self._open_selected_row_details(rows)
        else:
            self.selected = row_index

    def _list_row_index_at(self, y: int, row_count: int) -> int | None:
        height, _width = self.stdscr.getmaxyx()
        visible_count = max(0, height - _LIST_FIRST_ROW)
        if visible_count <= 0:
            return None
        offset = y - _LIST_FIRST_ROW
        if offset < 0 or offset >= visible_count:
            return None
        page_start = (self.selected // visible_count) * visible_count
        row_index = page_start + offset
        if row_index >= row_count:
            return None
        return row_index

    def _open_selected_row_details(self, rows: Sequence[JobRow]) -> None:
        self.selected_row_id = _row_value(rows[self.selected], "id")
        self._clear_list_rows()
        self.mode = "detail"
        self.detail_scroll = 0
        self.detail_return_index = self.selected
        self.detail_job_id = _row_id(rows[self.selected])
        if self.detail_job_id is not None:
            self.repository.mark_read(self.detail_job_id)

    def _handle_search_key(self, key: int) -> bool:
        if key in (curses.KEY_ENTER, 10, 13, 27):
            self.search_active = False
            return True
        if key in _SEARCH_DELETE_KEYS:
            self.query = self.query[:-1]
            self.selected = 0
            return True
        if 32 <= key <= 126:
            self.query += chr(key)
            self.selected = 0
            return True
        return False

    def _handle_sort_key(self, key: int) -> bool:
        if key in (ord("q"), 27):
            self.mode = "list"
            return False
        if key in (curses.KEY_ENTER, 10, 13):
            self.mode = "list"
            self._clear_list_rows()
            return False
        if key == curses.KEY_DOWN:
            self._sync_sort_selection_index()
            self.sort_selection_index = min(
                self.sort_selection_index + 1,
                len(_SORT_COLUMNS) - 1,
            )
            self._set_sort_from_selection()
            return False
        if key == curses.KEY_UP:
            self._sync_sort_selection_index()
            self.sort_selection_index = max(0, self.sort_selection_index - 1)
            self._set_sort_from_selection()
            return False
        typed = chr(key) if 0 <= key <= 255 else ""
        column = _SORT_COLUMN_BY_KEY.get(typed.lower())
        if column is None:
            return False
        self.sort_column = column
        self.sort_selection_index = _SORT_INDEX_BY_COLUMN[column]
        self.sort_reverse = typed.isupper()
        self.selected = 0
        self.mode = "list"
        self._clear_list_rows()
        return False

    def _set_sort_from_selection(self) -> None:
        _key, column, _label = _SORT_COLUMNS[self.sort_selection_index]
        self.sort_column = column
        self.sort_reverse = False
        self.selected = 0
        self._clear_list_rows()

    def _sync_sort_selection_index(self) -> None:
        self.sort_selection_index = _SORT_INDEX_BY_COLUMN.get(
            self.sort_column,
            self.sort_selection_index,
        )

    def _handle_detail_key(
        self,
        key: int,
        row: JobRow | None = None,
        opener: Callable[[list[str]], object] | None = None,
        generate=generate_resume,
        run_generator=run_resume_generator,
        show_terminal=None,
        edit_description: Callable[[JobRow], None] | None = None,
    ) -> bool:
        if key in (ord("q"), 27, curses.KEY_LEFT):
            self.mode = "list"
            self.detail_job_id = None
            if self.detail_return_index is not None:
                self.selected = self.detail_return_index
                self.detail_return_index = None
            return False
        if key in (curses.KEY_ENTER, 10, 13) and row is not None:
            self._open_job_url(row, opener)
            return False
        if key in _DELETE_KEYS and row is not None:
            job_id = _row_id(row)
            if job_id is not None:
                self.repository.toggle_expired(job_id)
                self.detail_job_id = job_id
            return False
        if key == ord("s") and row is not None:
            job_id = _row_id(row)
            if job_id is not None:
                self.repository.toggle_starred(job_id)
                self.detail_job_id = job_id
            return False
        if key == ord("v") and row is not None:
            edit = self._edit_job_description if edit_description is None else edit_description
            edit(row)
            return False
        if key == ord("g") and row is not None:
            try:
                result = generate(row)
                terminal = self._show_terminal if show_terminal is None else show_terminal
                terminal(lambda: run_generator(result))
            except (OSError, subprocess.CalledProcessError, ValueError) as exc:
                self.status_message = f"Resume generation failed: {exc}"
            else:
                self.status_message = "Resume generation finished"
            self.mode = "detail"
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

    def _sync_detail_selection(self, rows: Sequence[JobRow]) -> None:
        if self.mode != "detail" or self.detail_job_id is None:
            return
        for index, row in enumerate(rows):
            if _row_id(row) == self.detail_job_id:
                self.selected = index
                return

    def _open_job_url(
        self,
        row: JobRow,
        opener: Callable[..., object] | None = None,
    ) -> None:
        url = _row_text(row, "url")
        if not url:
            self.status_message = "No URL saved for this job."
            return
        browser = os.environ.get("BROWSER", "").strip()
        if not browser:
            self.status_message = "BROWSER is not set."
            return
        launch = subprocess.Popen if opener is None else opener
        try:
            result = launch(
                shlex.split(browser) + [url],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        except OSError as exc:
            self.status_message = f"Open URL failed: {exc}"
        else:
            if hasattr(result, "communicate"):
                try:
                    stdout, stderr = result.communicate(timeout=_BROWSER_OPEN_WAIT_SECONDS)
                except subprocess.TimeoutExpired:
                    for stream_name in ("stdout", "stderr"):
                        stream = getattr(result, stream_name, None)
                        if stream is not None:
                            stream.close()
                    self.status_message = f"Opened URL: {url}"
                    return
            else:
                stdout = getattr(result, "stdout", "") or ""
                stderr = getattr(result, "stderr", "") or ""
            returncode = getattr(result, "returncode", 0)
            if returncode:
                sys.stdout.write(stdout or "")
                sys.stderr.write(stderr or "")
                self.status_message = f"Open URL failed: exit {returncode}"
            else:
                self.status_message = f"Opened URL: {url}"

    def _edit_job_description(
        self,
        row: JobRow,
        editor_command: str | None = None,
        runner: Callable[..., object] = subprocess.run,
        show_terminal=None,
    ) -> None:
        editor = (
            os.environ.get("EDITOR", "") if editor_command is None else editor_command
        ).strip()
        if not editor:
            self.status_message = "EDITOR is not set."
            return
        job_id = _row_id(row)
        if job_id is None:
            self.status_message = "Edit description failed: missing job id"
            return

        path = ""
        try:
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                prefix="rolemap-job-description-",
                suffix=".md",
                delete=False,
            ) as handle:
                path = handle.name
                handle.write(_row_text(row, "job_description"))
                handle.write("\n")

            command = shlex.split(editor) + [path]
            terminal = self._show_terminal if show_terminal is None else show_terminal
            terminal(lambda: runner(command, check=True))
            with open(path, encoding="utf-8") as handle:
                description = handle.read()
            if description.strip() == _row_text(row, "job_description").strip():
                self.status_message = "Description unchanged."
                return
            self.repository.update_description(job_id, description)
        except (OSError, subprocess.CalledProcessError, ValueError) as exc:
            self.status_message = f"Edit description failed: {exc}"
        else:
            self.detail_job_id = job_id
            self._clear_list_rows()
            self.status_message = "Description updated."
        finally:
            if path:
                try:
                    os.unlink(path)
                except OSError:
                    pass

    def _show_terminal(self, operation):
        curses.def_prog_mode()
        curses.endwin()
        try:
            return operation()
        finally:
            curses.reset_prog_mode()
            self.stdscr.keypad(True)
            try:
                curses.curs_set(0)
            except curses.error:
                pass

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
        clipped = _clip_for_terminal(text, width)
        try:
            self.stdscr.addstr(y, x, clipped, attrs)
        except curses.error:
            pass

    def _draw_status_message(self) -> None:
        if not self.status_message:
            return
        height, width = self.stdscr.getmaxyx()
        if height <= 0 or width <= 0:
            return
        self._add_line(height - 1, 0, self.status_message, width, curses.A_REVERSE)

    def _add_shortcut_help_line(
        self,
        y: int,
        x: int,
        segments: Sequence[_ShortcutHelpSegment],
        width: int,
        attrs: int = curses.A_NORMAL,
    ) -> None:
        if y >= self.stdscr.getmaxyx()[0]:
            return
        offset = x
        for segment in segments:
            if offset >= width:
                return
            clipped = _clip_for_terminal(segment.text, width - offset + 1)
            if not clipped:
                return
            segment_attrs = _shortcut_key_attrs(attrs) if segment.is_key else attrs
            try:
                self.stdscr.addstr(y, offset, clipped, segment_attrs)
            except curses.error:
                pass
            offset += len(clipped)
