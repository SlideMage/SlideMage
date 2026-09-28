"""Fetch, parse, and render public Uni Graz course data.

The public course detail page is a client-rendered app, so this module
doesn't scrape it directly -- everything here comes from the same two
REST/JSON endpoints that page's own app calls, both keyed by the numeric
``pStpSpNr`` course id. See docs/UGO_api.md for how these were found and
what else they return.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
import re
from typing import Union
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request, urlopen


_UNIGRAZ_HOST = "online.uni-graz.at"
_COURSE_GROUPS_PATH = "/kfu_online/ee/rest/slc.tm.cp/student/courseGroups/firstGroups"
_COURSE_DATA_PATH = "/kfu_online/ee/rest/slc.tm.cp/student/courses"
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
    groups: tuple[CourseGroup, ...]
    # "firstGroups" can stop short of the course's totalCount of groups.
    truncated: bool = False


@dataclass(frozen=True)
class Lecturer:
    first_name: str
    last_name: str
    function: str


@dataclass(frozen=True)
class CourseDetail:
    number: str
    title: str
    semester: str
    lecturers: tuple[Lecturer, ...]


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


def course_groups_url(course_url: str) -> str:
    """Build the public course-groups REST URL for a public Uni Graz course URL."""
    number = _course_number(course_url)
    return f"https://{_UNIGRAZ_HOST}{_COURSE_GROUPS_PATH}/{number}"


def course_data_url(course_url: str) -> str:
    """Build the public course-data REST URL for a public Uni Graz course URL.

    This is the same JSON endpoint the course detail page's Angular app
    calls (and, unlike that page, answers without a browser or a session)
    -- it's what supplies title/number/semester/lecturers.
    """
    number = _course_number(course_url)
    return f"https://{_UNIGRAZ_HOST}{_COURSE_DATA_PATH}/{number}"


def _get_json(url: str, label: str) -> bytes:
    # The server picks each text field's default language from
    # Accept-Language; ask for German, the schedule's source language.
    # _localized() below picks translations explicitly either way.
    request = Request(url, headers={"Accept": "application/json", "Accept-Language": "de"})
    try:
        with urlopen(request, timeout=15) as response:  # nosec B310: URL is validated by the caller
            if urlsplit(response.geturl()).hostname != _UNIGRAZ_HOST:
                raise RuntimeError(f"Uni Graz {label} request redirected to another host")
            return response.read()
    except HTTPError as exc:
        raise RuntimeError(f"Uni Graz {label} request failed (HTTP {exc.code})") from exc
    except URLError as exc:
        raise RuntimeError(f"Unable to reach Uni Graz {label}: {exc.reason}") from exc
    except TimeoutError as exc:
        raise RuntimeError(f"Uni Graz {label} request timed out") from exc


def fetch_schedule(course_url: str) -> CourseSchedule:
    """Download and parse a public Uni Graz course's session groups."""
    return parse_schedule(_get_json(course_groups_url(course_url), "course groups"))


def fetch_course_detail(course_url: str, language: str = "de") -> CourseDetail:
    """Download and parse a public Uni Graz course's title/number/semester/lecturers,
    with the title and semester in `language` ("de" or "en") where UGO has it."""
    return parse_course_detail(_get_json(course_data_url(course_url), "course data"), language)


def _localized(langdata: dict | None, language: str = "de") -> str:
    """A UGO "langdata" field's text in `language`, else German, else its
    default value -- stripped, since UGO's translations can carry stray
    whitespace."""
    if not langdata:
        return ""
    translations = {
        translation.get("lang"): translation.get("value")
        for translation in (langdata.get("translations") or {}).get("translation") or []
    }
    for lang in (language, "de"):
        if translations.get(lang):
            return translations[lang].strip()
    return (langdata.get("value") or "").strip()


def _parse_appointment(appointment: dict) -> CourseSession:
    start = datetime.fromisoformat(appointment["timestampFrom"]["value"])
    end = datetime.fromisoformat(appointment["timestampTo"]["value"])
    event_type = appointment.get("appointmentEventTypeDto") or {}
    return CourseSession(
        date=start.strftime("%d.%m.%Y"),
        start=start.strftime("%H:%M"),
        end=end.strftime("%H:%M"),
        location=(appointment.get("resourceName") or "").strip(),
        event=_localized(event_type.get("name")),
        remark=(appointment.get("comment") or "").strip(),
    )


# Anything a malformed response can raise while being walked.
_SHAPE_ERRORS = (TypeError, ValueError, KeyError, IndexError, AttributeError)


def parse_schedule(json_source: Union[bytes, str]) -> CourseSchedule:
    """Parse the ``slc.tm.cp`` course-groups REST response without making a
    network request. Raises ``ValueError`` if it isn't that response shape.

    The response repeats the course's shared (standard-group) sessions
    inside every group. They're pulled out into one "Standardgruppe" group,
    listed first, and each other group keeps only its own sessions -- the
    same split as the old appointments page. A group with no sessions of
    its own is kept, with no sessions.
    """
    try:
        payload = json.loads(json_source)
        course_groups = payload["courseGroupDtos"] or []
        shared: dict[object, tuple[str, CourseSession]] = {}
        standard_group_ids: set[object] = set()
        listed: list[tuple[object, CourseGroup]] = []
        for group in course_groups:
            own: list[CourseSession] = []
            for appointment in group.get("appointmentDtos") or []:
                session = _parse_appointment(appointment)
                owner = appointment.get("courseGroupDto") or {}
                if owner.get("standardgroupFlag") == "J":
                    standard_group_ids.add(owner.get("id"))
                    key = appointment.get("id") or session
                    shared.setdefault(key, (appointment["timestampFrom"]["value"], session))
                else:
                    own.append(session)
            name = (group.get("name") or "").strip() or "Standardgruppe"
            listed.append((group.get("id"), CourseGroup(name, tuple(own))))
        # The standard group itself, if listed, is already the "Standardgruppe" below.
        groups = [group for group_id, group in listed
                  if group.sessions or group_id is None or group_id not in standard_group_ids]
        if shared:
            ordered = sorted(shared.values(), key=lambda item: item[0])
            groups.insert(0, CourseGroup("Standardgruppe", tuple(session for _, session in ordered)))
        total = payload.get("totalCount")
    except _SHAPE_ERRORS as exc:
        raise ValueError("course groups response is not the expected shape") from exc
    return CourseSchedule(
        groups=tuple(groups),
        truncated=isinstance(total, int) and total > len(course_groups),
    )


def parse_course_detail(json_source: Union[bytes, str], language: str = "de") -> CourseDetail:
    """Parse the ``slc.tm.cp`` course-data REST response without making a
    network request, with the title and semester in `language` where UGO
    has it. Raises ``ValueError`` if it isn't that response shape."""
    try:
        payload = json.loads(json_source)
        course = payload["resource"][0]["content"]["cpCourseDetailDto"]["cpCourseDto"]
        lecturers = tuple(
            Lecturer(
                first_name=(lectureship["identityLibDto"]["firstName"] or "").strip(),
                last_name=(lectureship["identityLibDto"]["lastName"] or "").strip(),
                function=(lectureship["teachingFunction"]["name"] or "").strip(),
            )
            for lectureship in course.get("lectureships") or []
        )
        return CourseDetail(
            number=course["courseNumber"]["courseNumber"],
            title=_localized(course["courseTitle"], language),
            semester=_localized(course["semesterDto"]["semesterDesignation"], language),
            lecturers=lecturers,
        )
    except _SHAPE_ERRORS as exc:
        raise ValueError("course data response is not the expected shape") from exc


def _escape_latex(text: str) -> str:
    return "".join(_LATEX_SPECIALS.get(character, character) for character in text)


# The slide's own wording per deck language ("de"/"en", as
# transcript.deck_language_of() reports it). UNIGRAZonline serves the
# schedule in German; an English deck gets its table translated by
# translate_to_english() below (v4.1.0, direct instruction).
LABELS = {
    "de": {
        "title": "Abhaltungstermine",
        "date": "Datum", "time": "Zeit", "location": "Ort", "event": "Termin",
        "no_sessions": "Keine Termine verfügbar.",
    },
    "en": {
        "title": "Course sessions",
        "date": "Date", "time": "Time", "location": "Location", "event": "Session",
        "no_sessions": "No sessions available.",
    },
}

# German terms UNIGRAZonline uses in group names, event types and
# remarks. Whole words only, longest first. Group names and event types
# are translated term by term ("Gruppe Wirtschaftsinformatik" -> "Group
# Wirtschaftsinformatik"); a free-text remark only when every word in it
# is known, since a half-translated sentence reads worse than German.
_GERMAN_TO_ENGLISH = {
    "Standardgruppe": "Standard group",
    "Gruppe": "Group",
    "Abhaltung": "Class",
    "Vorbesprechung": "Preliminary meeting",
    "Nachbesprechung": "Review meeting",
    "Einführung": "Introduction",
    "Vorlesung": "Lecture",
    "Übung": "Exercise",
    "Tutorium": "Tutorial",
    "Präsentation": "Presentation",
    "Präsentationen": "Presentations",
    "Prüfung": "Exam",
    "Klausur": "Exam",
    "Zwischenprüfung": "Midterm exam",
    "Endprüfung": "Final exam",
    "Abschlussprüfung": "Final exam",
    "Nachtermin": "Resit",
    "Wiederholungsprüfung": "Resit exam",
    "Ersatztermin": "Replacement session",
    "Zusatztermin": "Additional session",
    "Blocktermin": "Block session",
    "Exkursion": "Excursion",
    "Sprechstunde": "Office hours",
    "Fragestunde": "Q&A session",
    "Ausfall": "Cancelled",
    "entfällt": "cancelled",
    "abgesagt": "cancelled",
    "verschoben": "postponed",
    "Hörsaal": "Lecture hall",
    "Seminarraum": "Seminar room",
    "und": "and",
    "bis": "to",
    "mit": "with",
    "ohne": "without",
    "Anwesenheitspflicht": "attendance required",
    "Anmeldung": "registration",
}
_GERMAN_WORD_RE = re.compile(
    r"(?<!\w)(" + "|".join(
        re.escape(word) for word in sorted(_GERMAN_TO_ENGLISH, key=len, reverse=True)
    ) + r")(?!\w)"
)


# Letters only: numbers ("Gruppe 2", "Prüfung 1") need no translation.
_WORD_RE = re.compile(r"[^\W\d_]+")


def translate_to_english(text: str, whole_only: bool = False) -> str:
    """Replace the known German schedule terms in `text` with English.
    With `whole_only`, `text` comes back unchanged unless every word in it
    is a known term."""
    translated = _GERMAN_WORD_RE.sub(lambda match: _GERMAN_TO_ENGLISH[match.group(1)], text)
    if whole_only and _WORD_RE.search(_GERMAN_WORD_RE.sub(" ", text)):
        return text
    return translated


def translate_schedule(schedule: CourseSchedule) -> CourseSchedule:
    """The same schedule with group names, event types and (fully known)
    remarks translated from German to English; dates, times and rooms
    unchanged."""
    return CourseSchedule(
        truncated=schedule.truncated,
        groups=tuple(
            CourseGroup(
                name=translate_to_english(group.name),
                sessions=tuple(
                    CourseSession(
                        date=session.date, start=session.start, end=session.end,
                        location=session.location,
                        event=translate_to_english(session.event),
                        remark=translate_to_english(session.remark, whole_only=True),
                    )
                    for session in group.sessions
                ),
            )
            for group in schedule.groups
        ),
    )


def render_group_table(group: CourseGroup, language: str = "de") -> str:
    """Render one group as safe LaTeX that can be placed inside a frame,
    with the column headings in `language` ("de" or "en"). The cells are
    used as they are -- translate_schedule() first for an English deck."""
    labels = LABELS.get(language, LABELS["de"])
    if not group.sessions:
        return ("\\small \\textbf{" + _escape_latex(group.name) + "}\\par "
                + labels["no_sessions"])

    rows = []
    for session in group.sessions:
        time = "--".join(part for part in (session.start, session.end) if part)
        detail = " — ".join(part for part in (session.event, session.remark) if part)
        rows.append(" & ".join(_escape_latex(value) for value in (
            session.date, time, session.location, detail,
        )) + r" \\")
    heading = " & ".join(
        "\\textbf{" + labels[key] + "}" for key in ("date", "time", "location", "event"))
    return "\n".join((
        r"\scriptsize",
        "\\textbf{" + _escape_latex(group.name) + "}\\par\\vspace{2pt}",
        r"\renewcommand{\arraystretch}{1.08}",
        r"\setlength{\tabcolsep}{2pt}",
        r"\begin{tabular}{@{}p{.13\linewidth}p{.14\linewidth}p{.22\linewidth}p{.42\linewidth}@{}}",
        r"\toprule",
        heading + r" \\",
        r"\midrule",
        *rows,
        r"\bottomrule",
        r"\end{tabular}",
    ))


def render_title_slide(detail: CourseDetail, lecturers: tuple[Lecturer, ...]) -> str:
    """Render a ``\\titleframe{title}{names\\\\semester}`` call from fetched
    course data and a caller-selected subset of its lecturers."""
    names = _escape_latex(", ".join(f"{lecturer.first_name} {lecturer.last_name}" for lecturer in lecturers))
    semester = _escape_latex(detail.semester)
    subtitle = r"\\".join(part for part in (names, semester) if part)
    return r"\titleframe{" + _escape_latex(detail.title) + "}{" + subtitle + "}"
