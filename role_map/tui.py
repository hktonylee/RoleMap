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
from role_map.resumes import (
    ResumeTemplate,
    discover_templates,
    generate_resume,
    run_resume_generator,
)


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
_DETAIL_DESCRIPTION_WRAP_WIDTH = 120
_STRIKETHROUGH_MARK = "\u0336"
_SHORTCUT_KEY_COLOR_PAIR = 1
_SHORTCUT_KEY_ORANGE = 208
_SHORTCUT_HELP_KEY_PATTERN = re.compile(
    r"(?<!\S)/(?!\S)|"
    r"\b(?:Backspace|Down|Enter|Esc|G|Home|Left|PgDn|PgUp|Right|Up|o|q)\b"
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
    active = [row for row in rows if not _row_is_expired(row)]
    expired = [row for row in rows if _row_is_expired(row)]
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
    return attrs


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


def _row_value(row: JobRow, key: str) -> object:
    try:
        return row[key]
    except (IndexError, KeyError, TypeError):
        return None


def _row_is_expired(row: JobRow) -> bool:
    value = _row_value(row, "is_expired")
    if isinstance(value, str):
        return value.strip().casefold() in {"1", "true", "yes"}
    return bool(value)


def _copy_row_with_expired_state(row: JobRow, is_expired: bool) -> dict[str, object]:
    keys_method = getattr(row, "keys", None)
    keys = keys_method() if callable(keys_method) else ()
    values = {str(key): row[str(key)] for key in keys}
    values["is_expired"] = int(is_expired)
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
    for paragraph in _row_text(row, "description").splitlines() or [""]:
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
        self.search_active = False
        self.detail_scroll = 0
        self.status_message = ""
        self.template_templates: list[ResumeTemplate] = []
        self.template_selected = 0
        self.template_job: JobRow | None = None
        self.list_rows: list[JobRow] | None = None
        self.selected_row_id: object | None = None

    def run(self) -> None:
        curses.curs_set(0)
        _init_shortcut_key_color()
        self.stdscr.keypad(True)
        while True:
            rows = self._current_rows()
            self._restore_selected_row(rows)
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
            if self.mode == "template" and self._handle_template_key(key):
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

    def _draw(self, rows: Sequence[JobRow]) -> None:
        self.stdscr.erase()
        if self.mode == "template":
            self._draw_template_selector()
        elif self.mode == "detail" and rows:
            self._draw_detail(rows[self.selected])
        elif self.mode == "sort":
            self._draw_sort_selector()
        else:
            self._draw_list(rows)
        self.stdscr.refresh()

    def _draw_list(self, rows: Sequence[JobRow]) -> None:
        height, width = self.stdscr.getmaxyx()
        search_suffix = "_" if self.search_active else ""
        self._add_line(0, 0, f"Search: {self.query}{search_suffix}", width, curses.A_BOLD)
        sort_label = _SORT_LABEL_BY_COLUMN.get(self.sort_column, "Default")
        if self.sort_column is not None and self.sort_reverse:
            sort_label = f"{sort_label} desc"
        help_text = (
            "Typing search  Enter/Esc done  Backspace delete"
            if self.search_active
            else (
                "/ search  o sort  Enter/Right details  Esc/q quit  "
                "Up/Down/PgUp/PgDn/Home/End move"
            )
        )
        self._add_shortcut_help_line(
            1,
            0,
            f"Sort: {sort_label}  {help_text}",
            width,
        )

        if not rows:
            self._add_line(3, 0, "No jobs found.", width)
            return

        widths = _list_column_widths(width)
        self._add_line(3, 0, _format_list_header(widths), width, curses.A_BOLD)

        visible_count = max(0, height - 4)
        page_start = (
            (self.selected // visible_count) * visible_count if visible_count else 0
        )
        visible_rows = rows[page_start : page_start + visible_count]
        for index, row in enumerate(visible_rows, start=page_start):
            line = _format_list_row(row, widths, selected=index == self.selected)
            attrs = _list_row_attrs(row, selected=index == self.selected)
            self._add_line(index - page_start + 4, 0, line, width, attrs)

    def _draw_sort_selector(self) -> None:
        _height, width = self.stdscr.getmaxyx()
        self._add_line(0, 0, "Choose sort column", width, curses.A_BOLD)
        self._add_shortcut_help_line(
            1,
            0,
            "Lowercase asc  Uppercase desc  Esc/q cancel",
            width,
        )
        for index, (key, column, label) in enumerate(_SORT_COLUMNS, start=3):
            marker = "*" if column == self.sort_column else " "
            self._add_line(index, 0, f"{marker} {key}/{key.upper()}  {label}", width)

    def _draw_detail(self, row: JobRow) -> None:
        height, width = self.stdscr.getmaxyx()
        title = f"{_row_text(row, 'company_name')} - {_row_text(row, 'job_title')}"
        self._add_line(0, 0, title, width, curses.A_BOLD)
        self._add_shortcut_help_line(
            1,
            0,
            "Esc/q/Left back  PgUp/PgDn/Home/End  Enter open URL  G generate resume",
            width,
        )

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
        self._draw_status_message()

    def _draw_template_selector(self) -> None:
        height, width = self.stdscr.getmaxyx()
        self._add_line(0, 0, "Choose resume template", width, curses.A_BOLD)
        self._add_shortcut_help_line(
            1,
            0,
            "Enter generate  Esc/q/Left cancel  Up/Down move",
            width,
        )
        for index, template in enumerate(self.template_templates[: max(0, height - 4)]):
            marker = ">" if index == self.template_selected else " "
            attrs = curses.A_REVERSE if index == self.template_selected else curses.A_NORMAL
            self._add_line(index + 4, 0, f"{marker} {template.display_name}", width, attrs)
        self._draw_status_message()

    def _handle_list_key(self, key: int, rows: Sequence[JobRow]) -> bool:
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
            return False
        if key == ord("o"):
            self.mode = "sort"
            return False
        if key == ord(" ") and rows:
            is_expired = self.repository.toggle_expired(int(rows[self.selected]["id"]))
            self._replace_cached_expired_state(self.selected, is_expired)
            return False
        if key == ord("/"):
            self.search_active = True
            return False
        return False

    def _handle_search_key(self, key: int) -> bool:
        if key in (curses.KEY_ENTER, 10, 13, 27):
            self.search_active = False
            return True
        if key in (curses.KEY_BACKSPACE, 127, 8):
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
        typed = chr(key) if 0 <= key <= 255 else ""
        column = _SORT_COLUMN_BY_KEY.get(typed.lower())
        if column is None:
            return False
        self.sort_column = column
        self.sort_reverse = typed.isupper()
        self.selected = 0
        self.mode = "list"
        self._clear_list_rows()
        return False

    def _handle_detail_key(
        self,
        key: int,
        row: JobRow | None = None,
        templates: Sequence[ResumeTemplate] | None = None,
        opener: Callable[[list[str]], object] | None = None,
    ) -> bool:
        if key in (ord("q"), 27, curses.KEY_LEFT):
            self.mode = "list"
            return False
        if key in (curses.KEY_ENTER, 10, 13) and row is not None:
            self._open_job_url(row, opener)
            return False
        if key in (ord("G"), ord("g")) and row is not None:
            available_templates = list(discover_templates() if templates is None else templates)
            if not available_templates:
                self.status_message = (
                    "No resume templates found. Put your detailed resume in templates/ "
                    "or resume_templates/."
                )
                return False
            self.template_templates = available_templates
            self.template_selected = 0
            self.template_job = row
            self.status_message = ""
            self.mode = "template"
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
        launch = subprocess.run if opener is None else opener
        try:
            result = launch(shlex.split(browser) + [url], capture_output=True, text=True)
        except OSError as exc:
            self.status_message = f"Open URL failed: {exc}"
        else:
            returncode = getattr(result, "returncode", 0)
            if returncode:
                sys.stdout.write(getattr(result, "stdout", "") or "")
                sys.stderr.write(getattr(result, "stderr", "") or "")
                self.status_message = f"Open URL failed: exit {returncode}"
            else:
                self.status_message = f"Opened URL: {url}"

    def _handle_template_key(
        self,
        key: int,
        generate=generate_resume,
        run_generator=run_resume_generator,
        show_terminal=None,
    ) -> bool:
        if key in (ord("q"), 27, curses.KEY_LEFT):
            self.mode = "detail"
            return False
        if key == curses.KEY_DOWN:
            self.template_selected = min(
                self.template_selected + 1,
                max(0, len(self.template_templates) - 1),
            )
            return False
        if key == curses.KEY_UP:
            self.template_selected = max(0, self.template_selected - 1)
            return False
        if key not in (curses.KEY_ENTER, 10, 13):
            return False
        if self.template_job is None or not self.template_templates:
            self.status_message = "No resume template selected."
            self.mode = "detail"
            return False

        try:
            result = generate(
                self.template_job,
                self.template_templates[self.template_selected],
                run_command=False,
            )
            terminal = self._show_terminal if show_terminal is None else show_terminal
            terminal(lambda: run_generator(result))
        except (OSError, subprocess.CalledProcessError, ValueError) as exc:
            self.status_message = f"Resume generation failed: {exc}"
        else:
            self.status_message = f"Resume HTML: {result.result_html_path}"
        self.mode = "detail"
        return False

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
