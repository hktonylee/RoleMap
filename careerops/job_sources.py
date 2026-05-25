from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from html.parser import HTMLParser
import json
import re
from urllib.request import Request, urlopen


USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0 Safari/537.36"
)


@dataclass(frozen=True)
class SourceJob:
    description: str = ""
    salary_range: str = ""


def fetch_source_description(url: str) -> str:
    return fetch_source_job(url).description


def fetch_source_job(url: str) -> SourceJob:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=20) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        html = response.read().decode(charset, errors="replace")
    return extract_source_job(html)


def extract_source_description(html: str) -> str:
    return extract_source_job(html).description


def extract_source_job(html: str) -> SourceJob:
    json_ld_job = _extract_json_ld_job(html)
    visible_text = clean_source_description(_VisibleTextParser.parse(html))
    description = json_ld_job.description or visible_text
    salary_range = json_ld_job.salary_range or extract_salary_range(visible_text)
    return SourceJob(
        description=clean_source_description(description),
        salary_range=salary_range,
    )


def extract_salary_range(value: str) -> str:
    text = _normalize_text(value)
    if not text:
        return ""

    paragraphs = _paragraphs(text)
    for index, paragraph in enumerate(paragraphs):
        window = paragraph
        if _looks_like_salary_context(paragraph) and index + 1 < len(paragraphs):
            window = f"{paragraph} {paragraphs[index + 1]}"
        salary_range = _extract_salary_from_text(window)
        if salary_range and (
            _looks_like_salary_context(window) or _starts_with_money(paragraph)
        ):
            return salary_range

    return _extract_salary_from_text(text)


def clean_source_description(value: str) -> str:
    text = _normalize_text(value)
    text = _strip_linkedin_chrome(text)
    text = _strip_indeed_chrome(text)
    text = _remove_known_site_lines(text)
    return _normalize_text(text)


def _extract_json_ld_job(html: str) -> SourceJob:
    for payload in _ScriptParser.parse_json_ld(html):
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            continue
        job_posting = _find_jobposting(data)
        if job_posting:
            return SourceJob(
                description=_html_to_text(_string_value(job_posting.get("description"))),
                salary_range=_extract_jobposting_salary(job_posting),
            )
    return SourceJob()


def _find_jobposting(data: object) -> dict[str, object] | None:
    if isinstance(data, list):
        for item in data:
            job_posting = _find_jobposting(item)
            if job_posting:
                return job_posting
        return None
    if not isinstance(data, dict):
        return None

    item_type = data.get("@type")
    types = item_type if isinstance(item_type, list) else [item_type]
    if "JobPosting" in types:
        return data

    graph = data.get("@graph")
    if graph:
        return _find_jobposting(graph)
    return None


def _extract_jobposting_salary(job_posting: dict[str, object]) -> str:
    base_salary = job_posting.get("baseSalary")
    currency = _string_value(job_posting.get("salaryCurrency"))
    return _format_base_salary(base_salary, currency)


def _format_base_salary(value: object, fallback_currency: str) -> str:
    if isinstance(value, list):
        for item in value:
            salary_range = _format_base_salary(item, fallback_currency)
            if salary_range:
                return salary_range
        return ""
    if not isinstance(value, dict):
        return _format_single_salary_value(value, fallback_currency, "")

    currency = _string_value(value.get("currency")) or fallback_currency
    amount = value.get("value")
    if isinstance(amount, dict):
        unit_text = _string_value(amount.get("unitText"))
        min_value = amount.get("minValue")
        max_value = amount.get("maxValue")
        exact_value = amount.get("value")
        if min_value is not None and max_value is not None:
            return _format_salary_range(
                _format_money_amount(min_value, currency),
                _format_money_amount(max_value, currency),
                "",
                _salary_unit_suffix(unit_text, prefer_a=True),
            )
        if exact_value is not None:
            return _format_single_salary_value(exact_value, currency, unit_text)
    return _format_single_salary_value(amount, currency, "")


def _format_single_salary_value(value: object, currency: str, unit_text: str) -> str:
    amount = _format_money_amount(value, currency)
    if not amount:
        return ""
    suffix = _salary_unit_suffix(unit_text, prefer_a=True)
    return f"{amount} {suffix}".strip()


def _format_money_amount(value: object, currency: str) -> str:
    if value is None:
        return ""
    try:
        numeric = float(str(value).replace(",", ""))
    except ValueError:
        return _normalize_money(str(value))

    if numeric.is_integer():
        formatted = f"{int(numeric):,}"
    else:
        formatted = f"{numeric:,.2f}".rstrip("0").rstrip(".")
    return f"{_currency_prefix(currency)}{formatted}"


def _currency_prefix(currency: str) -> str:
    normalized = currency.upper()
    if normalized == "CAD":
        return "CA$"
    if normalized == "USD":
        return "$"
    return "$"


def _salary_unit_suffix(unit_text: str, *, prefer_a: bool = False) -> str:
    normalized = unit_text.strip().lower()
    if normalized in {"year", "yr", "annually"}:
        return "a year" if prefer_a else "per year"
    if normalized in {"hour", "hr"}:
        return "an hour" if prefer_a else "per hour"
    return ""


def _extract_salary_from_text(value: str) -> str:
    text = _normalize_salary_text(value)
    money = r"(?:CA\s*)?\$\s*\d[\d,]*(?:\.\d{2})?(?:\s*[Kk])?"
    range_pattern = re.compile(
        rf"({money})\s*(?:-|to)\s*({money})(?:\s*(CAD|USD))?"
        rf"(?:\s*(per|a)\s+(year|yr|hour|hr)|\s*/\s*(year|yr|hour|hr)|\s*(annually))?",
        re.IGNORECASE,
    )
    single_pattern = re.compile(
        rf"(?:Pay|Salary|Compensation|Rate|From|Up to|Base pay range|Base salary range)"
        rf"\s*:?\s*-?\s*({money})(?:\s*(CAD|USD))?"
        rf"(?:\s*(per|a)\s+(year|yr|hour|hr)|\s*/\s*(year|yr|hour|hr)|\s*(annually))?",
        re.IGNORECASE,
    )

    match = range_pattern.search(text)
    if match:
        amount_a, amount_b, currency, unit_prefix, unit_a, unit_b, annually = match.groups()
        unit = unit_a or unit_b or annually or ""
        suffix = _visible_salary_suffix(unit, unit_prefix)
        return _format_salary_range(
            _normalize_money(amount_a),
            _normalize_money(amount_b),
            currency or "",
            suffix,
        )

    match = single_pattern.search(text)
    if match:
        amount, currency, unit_prefix, unit_a, unit_b, annually = match.groups()
        unit = unit_a or unit_b or annually or ""
        salary = _normalize_money(amount)
        if currency:
            salary = f"{salary} {currency.upper()}"
        suffix = _visible_salary_suffix(unit, unit_prefix)
        return f"{salary} {suffix}".strip()
    return ""


def _normalize_salary_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("–", "-").replace("—", "-")).strip()


def _normalize_money(value: str) -> str:
    amount = re.sub(r"\s+", "", value.strip().rstrip(".,;:"))
    amount = amount.replace("CA$", "CA$")
    return re.sub(r"\.00\b", "", amount)


def _format_salary_range(amount_a: str, amount_b: str, currency: str, suffix: str) -> str:
    salary_range = f"{amount_a}-{amount_b}"
    if currency and not amount_a.upper().startswith("CA$"):
        salary_range = f"{salary_range} {currency.upper()}"
    if suffix:
        salary_range = f"{salary_range} {suffix}"
    return salary_range


def _visible_salary_suffix(unit: str, unit_prefix: str | None) -> str:
    normalized = unit.strip().lower()
    if normalized == "annually":
        return "annually"
    if normalized in {"year", "yr"}:
        return "a year" if unit_prefix and unit_prefix.lower() == "a" else "per year"
    if normalized in {"hour", "hr"}:
        return "an hour" if unit_prefix and unit_prefix.lower() == "a" else "per hour"
    return ""


def _looks_like_salary_context(value: str) -> bool:
    lower = value.lower()
    return any(
        marker in lower
        for marker in (
            "salary",
            "base pay",
            "pay range",
            "compensation",
            "pay:",
            "rate-",
            "rate:",
        )
    )


def _starts_with_money(value: str) -> bool:
    return bool(re.match(r"^(?:CA\s*)?\$", value.strip()))


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


def _strip_indeed_chrome(value: str) -> str:
    paragraphs = _paragraphs(value)
    if not _looks_like_indeed_text(paragraphs):
        return value

    start_index = _first_index(paragraphs, _is_indeed_content_boundary)
    if start_index is None:
        return value

    paragraphs = paragraphs[start_index + 1 :]
    while paragraphs and _is_indeed_leading_boilerplate(paragraphs[0]):
        paragraphs = paragraphs[1:]
    return "\n\n".join(paragraphs)


def _looks_like_indeed_text(paragraphs: list[str]) -> bool:
    markers = {
        "Company reviews",
        "Salary guide",
        "Employers / Post Job",
        "Start of main content",
    }
    return any(paragraph in markers for paragraph in paragraphs)


def _is_indeed_content_boundary(paragraph: str) -> bool:
    return paragraph == "Start of main content" or _is_indeed_search_controls(paragraph)


def _is_indeed_leading_boilerplate(paragraph: str) -> bool:
    boilerplate = {
        "Home",
        "Company reviews",
        "Salary guide",
        "Sign in",
        "Employers / Post Job",
        "Start of main content",
    }
    return (
        paragraph in boilerplate
        or paragraph.endswith(" new update")
        or _is_indeed_locale_switcher(paragraph)
        or _is_indeed_search_controls(paragraph)
    )


def _is_indeed_locale_switcher(paragraph: str) -> bool:
    return (
        (paragraph.startswith("En") and "English" in paragraph)
        or (paragraph.startswith("Fr") and "Français" in paragraph)
    )


def _is_indeed_search_controls(paragraph: str) -> bool:
    return paragraph.startswith("What") and paragraph.endswith("Find Jobs")


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
