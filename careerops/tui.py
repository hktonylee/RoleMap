from __future__ import annotations

import curses
import textwrap

from careerops.jobs import JobRepository


def run(repository: JobRepository) -> None:
    curses.wrapper(lambda stdscr: _JobBrowser(stdscr, repository).run())


class _JobBrowser:
    def __init__(self, stdscr: curses.window, repository: JobRepository) -> None:
        self.stdscr = stdscr
        self.repository = repository
        self.query = ""
        self.selected = 0
        self.mode = "list"
        self.detail_scroll = 0

    def run(self) -> None:
        curses.curs_set(0)
        self.stdscr.keypad(True)
        while True:
            rows = self.repository.search(self.query)
            if self.selected >= len(rows):
                self.selected = max(0, len(rows) - 1)

            self._draw(rows)
            key = self.stdscr.getch()
            if self.mode == "list" and self._handle_list_key(key, rows):
                return
            if self.mode == "detail" and self._handle_detail_key(key):
                return

    def _draw(self, rows: list[object]) -> None:
        self.stdscr.erase()
        if self.mode == "detail" and rows:
            self._draw_detail(rows[self.selected])
        else:
            self._draw_list(rows)
        self.stdscr.refresh()

    def _draw_list(self, rows: list[object]) -> None:
        height, width = self.stdscr.getmaxyx()
        self._add_line(0, 0, f"Search: {self.query}", width, curses.A_BOLD)
        self._add_line(1, 0, "Enter details  Esc/q quit  Up/Down or Ctrl-N/Ctrl-P move", width)

        if not rows:
            self._add_line(3, 0, "No jobs found.", width)
            return

        for index, row in enumerate(rows[: max(0, height - 3)]):
            marker = ">" if index == self.selected else " "
            line = (
                f"{marker} {row['id']:>3}  {row['company_name']}  "
                f"{row['job_title']}  {row['publish_date'] or ''}  "
                f"{row['salary_range'] or ''}"
            )
            attrs = curses.A_REVERSE if index == self.selected else curses.A_NORMAL
            self._add_line(index + 3, 0, line, width, attrs)

    def _draw_detail(self, row: object) -> None:
        height, width = self.stdscr.getmaxyx()
        title = f"{row['company_name']} - {row['job_title']}"
        self._add_line(0, 0, title, width, curses.A_BOLD)
        self._add_line(1, 0, "Esc/q back  Up/Down scroll", width)

        lines = [
            f"ID: {row['id']}",
            f"Publish date: {row['publish_date'] or ''}",
            f"URL: {row['url'] or ''}",
            f"Salary range: {row['salary_range'] or ''}",
            f"Last update: {row['last_update']}",
            "",
            "Description:",
        ]
        for paragraph in str(row["description"]).splitlines() or [""]:
            lines.extend(textwrap.wrap(paragraph, width=max(20, width - 2)) or [""])

        visible = lines[self.detail_scroll : self.detail_scroll + max(0, height - 3)]
        for index, line in enumerate(visible, start=3):
            self._add_line(index, 0, line, width)

    def _handle_list_key(self, key: int, rows: list[object]) -> bool:
        if key in (ord("q"), 27):
            return True
        if key in (curses.KEY_DOWN, 14):
            self.selected = min(self.selected + 1, max(0, len(rows) - 1))
            return False
        if key in (curses.KEY_UP, 16):
            self.selected = max(0, self.selected - 1)
            return False
        if key in (curses.KEY_ENTER, 10, 13) and rows:
            self.mode = "detail"
            self.detail_scroll = 0
            return False
        if key in (curses.KEY_BACKSPACE, 127, 8):
            self.query = self.query[:-1]
            self.selected = 0
            return False
        if 32 <= key <= 126:
            self.query += chr(key)
            self.selected = 0
        return False

    def _handle_detail_key(self, key: int) -> bool:
        if key in (ord("q"), 27):
            self.mode = "list"
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
