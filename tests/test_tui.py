import curses
import unittest

from careerops.tui import _JobBrowser


class FakeWindow:
    def keypad(self, enabled: bool) -> None:
        pass

    def getmaxyx(self) -> tuple[int, int]:
        return (24, 80)


class JobBrowserKeyHandlingTest(unittest.TestCase):
    def test_right_arrow_opens_selected_job_details(self) -> None:
        browser = _JobBrowser(FakeWindow(), repository=object())
        browser.detail_scroll = 3

        should_quit = browser._handle_list_key(curses.KEY_RIGHT, [object()])

        self.assertFalse(should_quit)
        self.assertEqual(browser.mode, "detail")
        self.assertEqual(browser.detail_scroll, 0)

    def test_left_arrow_returns_from_detail_to_list(self) -> None:
        browser = _JobBrowser(FakeWindow(), repository=object())
        browser.mode = "detail"

        should_quit = browser._handle_detail_key(curses.KEY_LEFT)

        self.assertFalse(should_quit)
        self.assertEqual(browser.mode, "list")


if __name__ == "__main__":
    unittest.main()
