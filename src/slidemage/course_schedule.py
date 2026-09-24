"""Fetch, parse, and render public Uni Graz course schedules.

The public course detail page and its appointment page use different paths,
but both identify a course with the numeric ``pStpSpNr`` query parameter.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Union
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit
from urllib.request import urlopen

from lxml import html


_UNIGRAZ_HOST = "online.uni-graz.at"
_SCHEDULE_PATH = "/kfu_online/wbTvw_List.lehrveranstaltung"
_WHITESPACE_RE = re.compile(r"\s+")
_LATEX_SPECIALS = {
    "\\": r"\textbackslash{}",
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}


@dataclass(frozen=True)
class CourseSession:
    date: str
    start: str
    end: str
    location: str
    event: str
    remark: str


@dataclass(frozen=True)
class CourseGroup:
    name: str
    sessions: tuple[CourseSession, ...]


@dataclass(frozen=True)
class CourseSchedule:
    title: str
    groups: tuple[CourseGroup, ...]


def _course_number(course_url: str) -> str:
    """Return the public Uni Graz course number or raise ``ValueError``."""
    if not isinstance(course_url, str):
        raise ValueError("course URL must be a string")
    parsed = urlsplit(course_url)
    if parsed.scheme != "https" or parsed.hostname != _UNIGRAZ_HOST:
        raise ValueError("course URL must use https://online.uni-graz.at")
    values = parse_qs(parsed.query, keep_blank_values=True).get("pStpSpNr", [])
    if len(values) != 1 or not values[0].isdigit():
        raise ValueError("course URL must contain one numeric pStpSpNr parameter")
    return values[0]


def schedule_url(course_url: str) -> str:
    """Build the public appointment URL for a public Uni Graz course URL."""
    number = _course_number(course_url)
    return urlunsplit(("https", _UNIGRAZ_HOST, _SCHEDULE_PATH,
                       urlencode({"pStpSpNr": number}), ""))


def fetch_schedule(course_url: str) -> CourseSchedule:
    """Download and parse a public Uni Graz schedule.

    ``urlopen`` follows the University's redirect to ``wbTermin_list``.  Both
    network failures and an unexpected redirected host are reported clearly.
    """
    url = schedule_url(course_url)
    try:
        with urlopen(url, timeout=15) as response:  # nosec B310: URL is validated above
            final_url = response.geturl()
            final_host = urlsplit(final_url).hostname
            if final_host != _UNIGRAZ_HOST:
                raise RuntimeError("Uni Graz schedule request redirected to another host")
            body = response.read()
    except HTTPError as exc:
        raise RuntimeError(f"Uni Graz schedule request failed (HTTP {exc.code})") from exc
    except URLError as exc:
        raise RuntimeError(f"Unable to reach Uni Graz schedule: {exc.reason}") from exc
    except TimeoutError as exc:
        raise RuntimeError("Uni Graz schedule request timed out") from exc
    return parse_schedule(body, final_url)


def _text(element: object) -> str:
    """Extract visible HTML text and normalize its whitespace."""
    if element is None:
        return ""
    return _WHITESPACE_RE.sub(" ", " ".join(element.itertext())).strip()


def parse_schedule(html_source: Union[bytes, str], source_url: str) -> CourseSchedule:
    """Parse a Uni Graz appointment page without making a network request.

    A missing appointments table is a valid empty schedule. ``source_url`` is
    accepted to make the source explicit and checked when it is supplied.
    """
    if source_url:
        parsed = urlsplit(source_url)
        if parsed.hostname and parsed.hostname != _UNIGRAZ_HOST:
            raise ValueError("schedule source is not hosted by online.uni-graz.at")
    try:
        document = html.fromstring(html_source)
    except (TypeError, ValueError, UnicodeDecodeError) as exc:
        raise ValueError("schedule response is not valid HTML") from exc

    tables = document.xpath('//table[@id="tabLvTermine"]')
    if not tables:
        return CourseSchedule(title="", groups=())
    table = tables[0]
    title = _text(table.xpath("./caption")[0] if table.xpath("./caption") else None)

    groups: list[CourseGroup] = []
    group_name: str | None = None
    sessions: list[CourseSession] = []

    def finish_group() -> None:
        nonlocal sessions
        if group_name is not None:
            groups.append(CourseGroup(group_name, tuple(sessions)))
        sessions = []

    for row in table.xpath("./tbody/tr"):
        cells = row.xpath("./td")
        if len(cells) == 1 and cells[0].get("colspan") == "8":
            finish_group()
            group_name = _text(cells[0]) or "Standardgruppe"
            continue
        if len(cells) < 8:
            continue
        if group_name is None:
            group_name = "Standardgruppe"
        sessions.append(CourseSession(
            date=_text(cells[1]),
            start=_text(cells[2]),
            end=_text(cells[3]),
            location=_text(cells[4]),
            event=_text(cells[5]),
            remark=_text(cells[7]),
        ))
    finish_group()
    return CourseSchedule(title=title, groups=tuple(groups))


def _escape_latex(text: str) -> str:
    return "".join(_LATEX_SPECIALS.get(character, character) for character in text)


def render_group_table(schedule: CourseSchedule, group: CourseGroup) -> str:
    """Render one group as safe LaTeX that can be placed inside a frame."""
    del schedule  # Reserved for callers that select a group from a schedule.
    if not group.sessions:
        return "\\small \\textbf{" + _escape_latex(group.name) + "}\\par Keine Termine verfügbar."

    rows = []
    for session in group.sessions:
        time = "--".join(part for part in (session.start, session.end) if part)
        detail = " — ".join(part for part in (session.event, session.remark) if part)
        rows.append(" & ".join(_escape_latex(value) for value in (
            session.date, time, session.location, detail,
        )) + r" \\")
    return "\n".join((
        r"\scriptsize",
        "\\textbf{" + _escape_latex(group.name) + "}\\par\\vspace{2pt}",
        r"\renewcommand{\arraystretch}{1.08}",
        r"\setlength{\tabcolsep}{2pt}",
        r"\begin{tabular}{@{}p{.13\linewidth}p{.14\linewidth}p{.22\linewidth}p{.42\linewidth}@{}}",
        r"\toprule",
        r"\textbf{Datum} & \textbf{Zeit} & \textbf{Ort} & \textbf{Termin} \\",
        r"\midrule",
        *rows,
        r"\bottomrule",
        r"\end{tabular}",
    ))
