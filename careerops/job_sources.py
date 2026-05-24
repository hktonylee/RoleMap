from __future__ import annotations

from collections.abc import Callable
from html.parser import HTMLParser
import json
import re
from urllib.request import Request, urlopen


USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0 Safari/537.36"
)


def fetch_source_description(url: str) -> str:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=20) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        html = response.read().decode(charset, errors="replace")
    return extract_source_description(html)


def extract_source_description(html: str) -> str:
    json_ld_description = _extract_json_ld_job_description(html)
    if json_ld_description:
        return clean_source_description(json_ld_description)
    return clean_source_description(_VisibleTextParser.parse(html))


def clean_source_description(value: str) -> str:
    text = _normalize_text(value)
    text = _strip_linkedin_chrome(text)
    text = _remove_known_site_lines(text)
    return _normalize_text(text)


def _extract_json_ld_job_description(html: str) -> str:
    for payload in _ScriptParser.parse_json_ld(html):
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            continue
        description = _find_jobposting_description(data)
        if description:
            return _html_to_text(description)
    return ""


def _find_jobposting_description(data: object) -> str:
    if isinstance(data, list):
        for item in data:
            description = _find_jobposting_description(item)
            if description:
                return description
        return ""
    if not isinstance(data, dict):
        return ""

    item_type = data.get("@type")
    types = item_type if isinstance(item_type, list) else [item_type]
    if "JobPosting" in types:
        return _string_value(data.get("description"))

    graph = data.get("@graph")
    if graph:
        return _find_jobposting_description(graph)
    return ""


def _html_to_text(value: str) -> str:
    return _normalize_text(_VisibleTextParser.parse(value))


def _strip_linkedin_chrome(value: str) -> str:
    paragraphs = _paragraphs(value)
    if not _looks_like_linkedin_text(paragraphs):
        return value

    if "Report this job" in paragraphs:
        paragraphs = paragraphs[paragraphs.index("Report this job") + 1 :]

    end_index = _first_index(paragraphs, _is_linkedin_trailing_marker)
    if end_index is not None:
        paragraphs = paragraphs[:end_index]

    cookie_index = _last_index(
        paragraphs,
        lambda paragraph: paragraph.startswith("By clicking Continue")
        and "Cookie Policy" in paragraph,
    )
    if cookie_index is not None:
        paragraphs = paragraphs[cookie_index + 1 :]

    while paragraphs and _is_linkedin_leading_boilerplate(paragraphs[0]):
        paragraphs = paragraphs[1:]

    if paragraphs and paragraphs[0].endswith("provided pay range"):
        jd_start_index = _first_index(paragraphs, _is_probable_jd_start)
        if jd_start_index is not None:
            paragraphs = paragraphs[jd_start_index:]

    return "\n\n".join(paragraphs)


def _paragraphs(value: str) -> list[str]:
    return [paragraph.strip() for paragraph in re.split(r"\n\s*\n", value) if paragraph.strip()]


def _looks_like_linkedin_text(paragraphs: list[str]) -> bool:
    return "LinkedIn" in paragraphs or "Report this job" in paragraphs


def _is_linkedin_leading_boilerplate(paragraph: str) -> bool:
    boilerplate = {
        "Use AI to assess how you fit",
        "Get AI-powered advice on this job and more exclusive features.",
        "Am I a good fit for this job?",
        "Tailor my resume",
        "Sign in to access AI-powered advices",
        "Sign in to evaluate your skills",
        "Sign in to tailor your resume",
        "Email or phone",
        "Password",
        "Show",
        "Forgot password?",
        "Sign in",
        "Sign in with Email",
        "or",
        "New to LinkedIn? Join now",
        "Save",
        "Apply",
    }
    return paragraph in boilerplate or paragraph.startswith("By clicking Continue")


def _is_linkedin_trailing_marker(paragraph: str) -> bool:
    markers = {
        "Show more",
        "Show less",
        "Seniority level",
        "Employment type",
        "Job function",
        "Industries",
        "Referrals increase your chances of interviewing",
        "Similar jobs",
    }
    return paragraph in markers or paragraph.startswith("Referrals increase your chances")


def _is_probable_jd_start(paragraph: str) -> bool:
    starts = {
        "About The Company",
        "About The Team",
        "About The Role",
        "Company Overview",
        "Overview",
        "Position Overview",
        "The Role",
        "What You'll Do",
        "Who We Are",
        "WHO WE ARE",
    }
    return paragraph in starts


def _remove_known_site_lines(value: str) -> str:
    removed = {
        "Skip to main content",
        "Expand search",
        "This button displays the currently selected search type.",
        "When expanded it provides a list of search options that will switch the search inputs to match the current selection.",
        "Jobs",
        "People",
        "Learning",
        "Clear text",
    }
    return "\n\n".join(
        paragraph for paragraph in _paragraphs(value) if paragraph not in removed
    )


def _first_index(
    values: list[str],
    predicate: Callable[[str], bool],
) -> int | None:
    for index, value in enumerate(values):
        if predicate(value):
            return index
    return None


def _last_index(
    values: list[str],
    predicate: Callable[[str], bool],
) -> int | None:
    for index in range(len(values) - 1, -1, -1):
        if predicate(values[index]):
            return index
    return None


def _normalize_text(value: str) -> str:
    lines = [re.sub(r"[ \t\r\f\v]+", " ", line).strip() for line in value.splitlines()]
    collapsed: list[str] = []
    blank = False
    for line in lines:
        if not line:
            blank = True
            continue
        if collapsed and blank:
            collapsed.append("")
        collapsed.append(line)
        blank = False
    return "\n".join(collapsed).strip()


def _string_value(value: object) -> str:
    if value is None:
        return ""
    return str(value)


class _ScriptParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._capturing_json_ld = False
        self._current: list[str] = []
        self.payloads: list[str] = []

    @classmethod
    def parse_json_ld(cls, html: str) -> list[str]:
        parser = cls()
        parser.feed(html)
        parser.close()
        return parser.payloads

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "script":
            return
        attr_map = {name.lower(): value or "" for name, value in attrs}
        script_type = attr_map.get("type", "").lower()
        self._capturing_json_ld = script_type == "application/ld+json"
        self._current = []

    def handle_data(self, data: str) -> None:
        if self._capturing_json_ld:
            self._current.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "script" and self._capturing_json_ld:
            self.payloads.append("".join(self._current).strip())
            self._capturing_json_ld = False
            self._current = []


class _VisibleTextParser(HTMLParser):
    _SKIP_TAGS = {"script", "style", "svg", "noscript"}
    _BREAK_TAGS = {
        "article",
        "br",
        "div",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "li",
        "main",
        "p",
        "section",
        "tr",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self._parts: list[str] = []

    @classmethod
    def parse(cls, html: str) -> str:
        parser = cls()
        parser.feed(html)
        parser.close()
        return "".join(parser._parts)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        tag = tag.lower()
        if tag in self._SKIP_TAGS:
            self._skip_depth += 1
        if tag in self._BREAK_TAGS:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self._parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in self._SKIP_TAGS and self._skip_depth:
            self._skip_depth -= 1
        if tag in self._BREAK_TAGS:
            self._parts.append("\n")
