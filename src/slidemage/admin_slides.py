"""Admin slides: a title slide and/or a course-sessions table generated from the Uni Graz course
a deck links (the Admin slides tab of the Deck settings sheet, ui/dialogs/admin_slides.py).

The slides follow the deck's own \\decklanguage: an English deck gets English table headings, its
German schedule terms translated (course_schedule.translate_schedule()), UGO's English course
title and semester on the title slide, and EN instead of DE in the new slides' id-slugs.
"""
from __future__ import annotations

from pathlib import Path

from . import course_schedule, deck_editor, slide_ids, slide_language
from .deck_scan import Deck

LANGUAGE_NAMES = {"de": "German", "en": "English"}
TITLE_SLIDE, SESSIONS_SLIDE = "Title-Slide", "Course-Sessions"


def fetch(url: str, language: str) -> tuple[object, object]:
    """(schedule, detail) of the course at `url`, each independently: a CourseSchedule /
    CourseDetail, or the error text when that part failed (a course with no public session list
    still offers its title slide)."""
    try:
        schedule: object = course_schedule.fetch_schedule(url)
    except Exception as exc:  # noqa: BLE001 -- shown to the user as the reason it is unavailable
        schedule = str(exc)
    try:
        detail: object = course_schedule.fetch_course_detail(url, language)
    except Exception as exc:  # noqa: BLE001
        detail = str(exc)
    return schedule, detail


def language_warning(language: str, detail: course_schedule.CourseDetail) -> str:
    """Why the deck's language doesn't fit the course ("" when it does or the course names none) --
    most often a deck with no \\decklanguage, which counts as English."""
    if not detail.languages or language in detail.languages:
        return ""
    taught = " and ".join(LANGUAGE_NAMES.get(key, key.upper()) for key in detail.languages)
    deck = LANGUAGE_NAMES.get(language, language)
    return (f"Warning: this course is taught in {taught}, but the deck is {deck} -- "
            f"the slides will be {deck}. Check the deck's \\decklanguage if that's unintended.")


def _build_slide_source(body: str) -> str:
    """Wrap a generated LaTeX frame in the normal editable slide format."""
    body = body.strip().replace("\r\n", "\n").replace("\r", "\n")
    lines = [r"\setSlideVersion{1-0-0}", body, ""]
    return slide_ids.build_new_slide_header() + "\r\n".join(lines)


def build_sessions_slide_source(table: str, language: str = "de") -> str:
    title = course_schedule.LABELS.get(language, course_schedule.LABELS["de"])["title"]
    return _build_slide_source("\n".join((
        r"\begin{standardframe}{" + title + "}", table.strip(), r"\end{standardframe}",
    )))


def build_title_slide_source(titleframe_call: str) -> str:
    return _build_slide_source(titleframe_call)


def plan_slides(
    language: str, *, detail: course_schedule.CourseDetail | None = None,
    lecturers: tuple[course_schedule.Lecturer, ...] = (),
    group: course_schedule.CourseGroup | None = None,
) -> list[tuple[str, str]]:
    """The ``(id_suffix, slide_source)`` of every slide wanted: a title slide when `detail` is
    given (naming `lecturers`), a sessions table when `group` is."""
    specs: list[tuple[str, str]] = []
    if detail is not None:
        call = course_schedule.render_title_slide(detail, lecturers)
        specs.append((TITLE_SLIDE, build_title_slide_source(call)))
    if group is not None:
        if language == "en":
            group = course_schedule.translate_schedule(course_schedule.CourseSchedule((group,))).groups[0]
        table = course_schedule.render_group_table(group, language)
        specs.append((SESSIONS_SLIDE, build_sessions_slide_source(table, language)))
    return specs


def insert_admin_slides(
    deck: Deck, position: deck_editor.InsertPosition, slide_specs: list[tuple[str, str]],
    language: str = "de",
) -> list[Path]:
    """Create one new slide per ``(id_suffix, slide_source)`` spec, then add
    all their calls to the deck in one edit, in order, at the insert
    position. If anything fails, the new slide files are removed and the
    deck is left untouched."""
    slide_paths: list[Path] = []
    id_slugs: list[str] = []
    try:
        for id_suffix, source in slide_specs:
            slide_id = slide_ids.mint_slide_id()
            id_slug = f"{slide_id}-{'EN' if language == 'en' else 'DE'}-{id_suffix}"
            slide_path = slide_ids.SLIDES_DIR / slide_language.current_name(id_slug)
            slide_path.parent.mkdir(parents=True, exist_ok=True)
            # Reserve the ID before editing the deck, like the ordinary Add slide path.
            slide_ids.append_slide_id(slide_id)
            with slide_path.open("x", encoding="utf-8", newline="") as destination:
                destination.write(source)
            slide_paths.append(slide_path)
            id_slugs.append(id_slug)
        deck_editor.insert_slide_calls(
            deck.path, deck.text, position.insert_at, position.indent, id_slugs,
        )
    except Exception:
        for slide_path in slide_paths:
            slide_path.unlink(missing_ok=True)
        raise
    return slide_paths
