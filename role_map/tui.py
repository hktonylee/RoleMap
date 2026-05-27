from __future__ import annotations

import curses
import os
import re
import shlex
import subprocess
import sys
import textwrap
from collections.abc import Callable, Sequence

from role_map.jobs import JobRepository, JobRow
from role_map.resumes import generate_resume, run_resume_generator


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
_SORT_INDEX_BY_COLUMN = {
    column: index for index, (_key, column, _label) in enumerate(_SORT_COLUMNS)
}
_DETAIL_DESCRIPTION_START_ROW = 10
_DETAIL_DESCRIPTION_WRAP_WIDTH = 120
_STRIKETHROUGH_MARK = "\u0336"
_BACKSPACE_KEYS = (curses.KEY_BACKSPACE, 127, 8)
_DELETE_KEYS = (curses.KEY_DC,)
_SEARCH_DELETE_KEYS = _BACKSPACE_KEYS + _DELETE_KEYS
_SHORTCUT_KEY_COLOR_PAIR = 1
_SHORTCUT_KEY_ORANGE = 208
_BROWSER_OPEN_WAIT_SECONDS = 1.0
_STARRED_COLOR_PAIR = 2
_SHORTCUT_HELP_KEYS = (
    "Delete",
    "Down",
    "Enter",
    "Esc",
    "G",
    "Home",
    "Left",
    "PgDn",
    "PgUp",
    "Right",
    "Up",
    "o",
    "p",
    "q",
    "r",
    "s",
)
_SHORTCUT_HELP_KEY_PATTERN = re.compile(
    r"(?<!\S)/(?!\S)|"
    rf"\b(?:{'|'.join(re.escape(key) for key in _SHORTCUT_HELP_KEYS)})\b"
)


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


def _shortcut_key_attrs(attrs: int = curses.A_NORMAL) -> int:
    try:
        return attrs | curses.A_BOLD | curses.color_pair(_SHORTCUT_KEY_COLOR_PAIR)
    except curses.error:
        return attrs | curses.A_BOLD


def _shortcut_help_segments(text: str) -> list[tuple[str, bool]]:
    segments: list[tuple[str, bool]] = []
    offset = 0
    for match in _SHORTCUT_HELP_KEY_PATTERN.finditer(text):
        if match.start() > offset:
            segments.append((text[offset : match.start()], False))
        segments.append((match.group(), True))
        offset = match.end()
    if offset < len(text):
        segments.append((text[offset:], False))
    return segments


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
    marker = ">" if selected else " "
    line = (
        f"{marker} "
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
    return _starred_attrs(row, attrs)


def _starred_attrs(row: JobRow, attrs: int = curses.A_NORMAL) -> int:
    if not _row_is_starred(row):
        return attrs
    try:
        return attrs | curses.color_pair(_STARRED_COLOR_PAIR)
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
        self.status_message = ""
        self.prune_confirmation_pending = False
        self.list_rows: list[JobRow] | None = None
        self.selected_row_id: object | None = None

    def run(self) -> None:
        curses.curs_set(0)
        _init_shortcut_key_color()
        _init_starred_color()
        self.stdscr.keypad(True)
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
            self._add_shortcut_help_line(
                0,
                0,
                (
                    "/ Search  Delete Expire  s Star  "
                    f"o Sort ({sort_shortcut_label})  "
                    "p Prune  r Refresh  Enter/Right Esc/q"
                ),
                width,
            )

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
            line = _format_list_row(row, widths, selected=index == self.selected)
            attrs = _list_row_attrs(row, selected=index == self.selected)
            self._add_line(index - page_start + 3, 0, line, width, attrs)
        self._draw_status_message()

    def _draw_sort_selector(self) -> None:
        _height, width = self.stdscr.getmaxyx()
        self._add_line(0, 0, "Choose sort column", width, curses.A_BOLD)
        self._add_shortcut_help_line(
            1,
            0,
            "Up/Down choose  Enter apply  Lowercase asc  Uppercase desc  Esc/q back",
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
        title = f"{_row_text(row, 'company_name')} - {_row_text(row, 'job_title')}"
        self._add_line(
            0,
            0,
            _detail_text(row, title),
            width,
            _detail_attrs(row, curses.A_BOLD),
        )
        self._add_shortcut_help_line(
            1,
            0,
            "Esc/q/Left Delete expire s star PgUp/PgDn/Home/End Enter URL G resume",
            width,
        )

        detail_attrs = _detail_attrs(row)
        for y, label, key in (
            (3, "ID", "id"),
            (4, "Publish date", "publish_date"),
            (5, "URL", "url"),
            (6, "Salary range", "salary_range"),
            (7, "Last update", "last_update"),
        ):
            self._add_line(
                y,
                0,
                _detail_text(row, f"{label}: {_row_text(row, key)}"),
                width,
                detail_attrs,
            )
        self._add_line(9, 0, _detail_text(row, "Description:"), width, detail_attrs)

        lines = _detail_description_lines(row, width)
        visible = lines[
            self.detail_scroll : self.detail_scroll
            + max(0, height - _DETAIL_DESCRIPTION_START_ROW)
        ]
        for index, line in enumerate(visible, start=_DETAIL_DESCRIPTION_START_ROW):
            self._add_line(index, 0, _detail_text(row, line), width, detail_attrs)
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
        if key in (curses.KEY_ENTER, curses.KEY_RIGHT, 10, 13) and rows:
            self.selected_row_id = _row_value(rows[self.selected], "id")
            self._clear_list_rows()
            self.mode = "detail"
            self.detail_scroll = 0
            self.detail_job_id = _row_id(rows[self.selected])
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
    ) -> bool:
        if key in (ord("q"), 27, curses.KEY_LEFT):
            self.mode = "list"
            self.detail_job_id = None
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
        if key in (ord("G"), ord("g")) and row is not None:
            try:
                result = generate(row)
                terminal = self._show_terminal if show_terminal is None else show_terminal
                terminal(lambda: run_generator(result))
            except (OSError, subprocess.CalledProcessError, ValueError) as exc:
                self.status_message = f"Resume generation failed: {exc}"
            else:
                self.status_message = f"Resume HTML: {result.result_html_path}"
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
        text: str,
        width: int,
        attrs: int = curses.A_NORMAL,
    ) -> None:
        if y >= self.stdscr.getmaxyx()[0]:
            return
        offset = x
        for segment, is_key in _shortcut_help_segments(text):
            if offset >= width - 1:
                return
            clipped = _clip_for_terminal(segment, width - offset)
            if not clipped:
                return
            segment_attrs = _shortcut_key_attrs(attrs) if is_key else attrs
            try:
                self.stdscr.addstr(y, offset, clipped, segment_attrs)
            except curses.error:
                pass
            offset += len(clipped)
