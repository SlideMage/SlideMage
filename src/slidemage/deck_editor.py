"""Parse and edit a single deck file's own \\slide{}-family call list.

Pure parsing/editing on top of deck_scan.Deck/Chapter -- no GUI code here,
so this can be unit-tested and reused independently of it. The slide list
(ui/workspace/slide_list.py) and the add-slide dialog are the callers;
everything here just reads/writes deck *.tex text.

Six call variants exist (see Slidemaster_preamble_base.tex): \\slide{},
\\slidefinal{} (renders fully revealed), \\slideversion{}{}/
\\omitslideversion{}{} (pin a frozen version), \\omitslide{} (excluded from
the student handout), \\conditionalslide[versions]{} (included only in the
listed deck versions). Each alternative in SLIDE_CALL_RE below gets its own
named groups (Python's re disallows reusing a group name across
alternatives in one pattern), listed longest-macro-name-first purely for
readability -- backtracking would resolve the shared-prefix cases (e.g.
"slide" vs "slideversion") correctly either way, since a short match that
can't complete the rest of its own alternative (no immediate "{" after
plain "slide" when the source text is really "slideversion{...}") forces
the engine to try the next alternative at the same position.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.parse import urlsplit

from .archive import _read, _write
from .deck_scan import (
    COMMENT_RE,
    COURSE_URL_RE,
    DOCUMENT_BEGIN_LINE_RE,
    DOCUMENT_END_RE,
    PROJECT_ROOT,
    Chapter,
    Deck,
    _parse_chapters,
    SECTION_RE,
    find_decktags,
    is_commented,
)

SLIDES_DIR = PROJECT_ROOT / "slides"

# Macros that take a pinned version as a second brace argument.
VERSIONED_MACROS = {"slideversion", "omitslideversion"}
# The one macro that takes an optional leading [conditions] list.
# \slidestep{id-slug}[conditions]{steps} is a \conditionalslide that also restricts the
# typeset reveal steps (2026-09-20); since 2026-09-26 it is offered in the variant
# pickers too (BASE_MACROS), with a "Steps" field next to the version checkboxes.
CONDITIONAL_MACROS = {"conditionalslide", "slidestep"}
OMIT_MACROS = {"omitslide", "omitslideversion"}
# The calls whose views can be set (set_calls_visibility); pinned versions and \slidefinal have no conditional form.
VISIBILITY_MACROS = {"slide", "omitslide", "conditionalslide", "slidestep"}
ALL_MACROS = {
    "slide", "slidefinal", "slideversion", "omitslide",
    "omitslideversion", "conditionalslide", "slidestep",
}
DEFAULT_STEPS = "1"
DEFAULT_CONDITIONS = ["instructor", "during-course", "after-course"]

# Display order for the GUI's variant pickers (slide_list.py,
# add_slide_dialog.py) -- the four macros with no separate version file.
BASE_MACROS = ["slide", "slidefinal", "omitslide", "conditionalslide", "slidestep"]

SLIDE_CALL_RE = re.compile(
    r"\\slideversion\{(?P<sv_idslug>[^}]+)\}\{(?P<sv_version>[^}]+)\}"
    r"|\\omitslideversion\{(?P<osv_idslug>[^}]+)\}\{(?P<osv_version>[^}]+)\}"
    r"|\\slidefinal\{(?P<sf_idslug>[^}]+)\}"
    r"|\\slide\{(?P<s_idslug>[^}]+)\}"
    r"|\\omitslide\{(?P<os_idslug>[^}]+)\}"
    r"|\\conditionalslide(?:\[(?P<cs_conditions>[^\]]*)\])?\{(?P<cs_idslug>[^}]+)\}"
    r"|\\slidestep\{(?P<ss_idslug>[^}]+)\}(?:\[(?P<ss_conditions>[^\]]*)\])?\{(?P<ss_steps>[^}]*)\}"
)

VERSION_FILE_RE = re.compile(r"-v([0-9]+(?:-[0-9]+)*)\.tex$")

_LEADING_BLANK_RE = re.compile(r"^[ \t]*$")
_TRAILING_OK_RE = re.compile(r"^[ \t]*(%.*)?$")


class StaleFileError(RuntimeError):
    """The deck file on disk no longer matches the text a caller last read
    (e.g. someone else -- another tab, TeXstudio, git -- changed it in the
    meantime). Callers should reload the deck and let the user retry rather
    than silently overwriting whatever's actually on disk now."""


@dataclass
class SlideCall:
    macro: str                    # one of ALL_MACROS
    id: str                       # e.g. "qxr"
    slug: str                     # e.g. "Introduction-to-R-Assignments"
    version: Optional[str]        # e.g. "1-0-0", only for VERSIONED_MACROS
    conditions: Optional[list]    # e.g. ["instructor"], only for \conditionalslide/\slidestep
    steps: Optional[str]          # e.g. "1,2", only for \slidestep (beamer overlay spec)
    call_start: int               # char offset of the "\macro..." token itself
    call_end: int
    line_start: int               # char offset of the whole line, including
    line_end: int                 # indent and the line's own terminator
    indent: str
    editable: bool
    readonly_reason: Optional[str]
    chapter: Optional[Chapter]

    @property
    def id_slug(self) -> str:
        return f"{self.id}-{self.slug}"

    @property
    def source_filename(self) -> str:
        """The exact slides/ file this call loads."""
        if self.version is not None:
            return f"{self.id_slug}-v{self.version}.tex"
        return f"{self.id_slug}-current.tex"

    def included_in(self, version: Optional[str]) -> bool:
        """Whether the deck version `version` (one of DEFAULT_CONDITIONS) typesets
        this slide: \\omitslide is instructor-only, the conditional macros
        follow their list, everything else is always in."""
        if version in (None, "presenter"):
            version = DEFAULT_CONDITIONS[0]
        if self.macro in OMIT_MACROS:
            return version == DEFAULT_CONDITIONS[0]
        if self.macro in CONDITIONAL_MACROS:
            return version in (self.conditions if self.conditions is not None else DEFAULT_CONDITIONS)
        return True


def _find_chapter(chapters: list[Chapter], offset: int) -> Optional[Chapter]:
    for chapter in chapters:
        if chapter.start <= offset < chapter.end:
            return chapter
    return None


def _line_span(text: str, call_start: int, call_end: int) -> tuple[int, int]:
    nl_before = text.rfind("\n", 0, call_start)
    line_start = nl_before + 1  # 0 if not found, i.e. first line of file
    nl_after = text.find("\n", call_end)
    line_end = len(text) if nl_after == -1 else nl_after + 1
    return line_start, line_end


def _editability(text: str, line_start: int, call_start: int, call_end: int, line_end: int) -> tuple[bool, Optional[str]]:
    leading = text[line_start:call_start]
    trailing_raw = text[call_end:line_end]
    # Strip the line's own terminator (bare \n, or \r\n for this project's
    # usual CRLF files) before checking what's left on the line.
    trailing = trailing_raw
    if trailing.endswith("\r\n"):
        trailing = trailing[:-2]
    elif trailing.endswith("\n"):
        trailing = trailing[:-1]

    if not _LEADING_BLANK_RE.match(leading):
        return False, "shares its line with other content before the call"
    if not _TRAILING_OK_RE.match(trailing):
        return False, "shares its line with other content after the call"
    return True, None


def parse_slide_calls(deck: Deck) -> list[SlideCall]:
    """Every \\slide{}-family call in this deck's file, in file order."""
    calls: list[SlideCall] = []
    for m in SLIDE_CALL_RE.finditer(deck.text):
        if m.group("sv_idslug") is not None:
            macro, idslug, version, conditions = "slideversion", m.group("sv_idslug"), m.group("sv_version"), None
        elif m.group("osv_idslug") is not None:
            macro, idslug, version, conditions = "omitslideversion", m.group("osv_idslug"), m.group("osv_version"), None
        elif m.group("sf_idslug") is not None:
            macro, idslug, version, conditions = "slidefinal", m.group("sf_idslug"), None, None
        elif m.group("s_idslug") is not None:
            macro, idslug, version, conditions = "slide", m.group("s_idslug"), None, None
        elif m.group("os_idslug") is not None:
            macro, idslug, version, conditions = "omitslide", m.group("os_idslug"), None, None
        elif m.group("ss_idslug") is not None:
            macro, idslug, version = "slidestep", m.group("ss_idslug"), None
            raw_conditions = m.group("ss_conditions")
            conditions = (
                [c.strip() for c in raw_conditions.split(",") if c.strip()]
                if raw_conditions is not None
                else list(DEFAULT_CONDITIONS)
            )
        else:
            macro, idslug, version = "conditionalslide", m.group("cs_idslug"), None
            raw_conditions = m.group("cs_conditions")
            conditions = (
                [c.strip() for c in raw_conditions.split(",") if c.strip()]
                if raw_conditions is not None
                else list(DEFAULT_CONDITIONS)
            )

        steps = m.group("ss_steps").strip() if macro == "slidestep" else None
        slide_id, _, slug = idslug.partition("-")
        line_start, line_end = _line_span(deck.text, m.start(), m.end())
        editable, readonly_reason = _editability(deck.text, line_start, m.start(), m.end(), line_end)

        calls.append(SlideCall(
            macro=macro,
            id=slide_id,
            slug=slug,
            version=version,
            conditions=conditions,
            steps=steps,
            call_start=m.start(),
            call_end=m.end(),
            line_start=line_start,
            line_end=line_end,
            indent=deck.text[line_start:m.start()] if editable else "",
            editable=editable,
            readonly_reason=readonly_reason,
            chapter=_find_chapter(deck.chapters, m.start()),
        ))
    return calls


def is_commented_out(deck_text: str, call: SlideCall) -> bool:
    """Whether `call`'s own "\\macro{...}" token sits inside a "%"-started
    LaTeX comment -- distinct from call.editable, which is False for *any*
    reason the call shares its line with other content, comment or not.
    appendix_toc.py's own TOC/appendix listing needs specifically this:
    "commented out, so doesn't really exist for the appendix" rather than
    "shares a line with something else, but still compiles for real"
    (2026-09-28, porting SlideMage upstream commit 34cdbd7 -- a
    commented-out \\section{}/\\slide{}-family call used to still show up in
    the generated appendix, since parse_slide_calls()'s own SLIDE_CALL_RE
    match has no notion of comments at all)."""
    return is_commented(deck_text, call.call_start)


def available_versions(id_slug: str) -> list[str]:
    """Every already-frozen slides/<id_slug>-vX-Y-Z.tex version, sorted
    numerically (not lexically -- "1-9-0" must sort before "1-10-0")."""
    if not SLIDES_DIR.is_dir():
        return []
    versions = []
    for path in SLIDES_DIR.glob(f"{id_slug}-v*.tex"):
        m = VERSION_FILE_RE.search(path.name)
        if m:
            versions.append(m.group(1))
    return sorted(versions, key=lambda v: tuple(int(part) for part in v.split("-")))


# A beamer overlay specification without the angle brackets, as \slidestep takes it:
# "1", "1,2", "2-", "1-2,4".
_STEPS_RE = re.compile(r"^\d+(?:-\d*)?(?:,\d+(?:-\d*)?)*$")


def normalize_steps(steps: str) -> str:
    """Whitespace-stripped `steps`, or ValueError when it is not a plain overlay
    specification (digits, commas and ranges such as "2-" or "1-2,4")."""
    cleaned = re.sub(r"\s+", "", steps or "")
    if not _STEPS_RE.match(cleaned):
        raise ValueError(
            f"{steps!r} is not a valid step list -- use numbers, commas and ranges, "
            "e.g. 1,2 or 2- or 1-2,4"
        )
    return cleaned


# Matches a bare `\end{document}` at the start of its own line (any leading
# whitespace) -- used only by empty_deck_insert_point() below.
_END_DOCUMENT_RE = re.compile(r"^[ \t]*\\end\{document\}", re.MULTILINE)


def empty_deck_insert_point(text: str) -> tuple[int, str]:
    """Where to insert a deck's very first \\slide{}-family call: right
    before \\end{document}, indented the same one tab every other deck's
    own \\slide{} calls use. For the slide list's "+ Slide" button while
    a deck has no calls of its own -- the same insert_at/indent shape its
    "+ before"/"+ after" entries hand to open_add_slide_dialog(), just with
    nothing to anchor "before"/"after" against. Raises ValueError if the
    deck has no \\end{document} at all (a malformed file, since
    deck_scan.py already requires one to even recognize it as a deck)."""
    match = _END_DOCUMENT_RE.search(text)
    if match is None:
        raise ValueError("no \\end{document} found in this deck")
    return match.start(), "\t"


def format_call(macro: str, id_slug: str, version: Optional[str] = None, conditions: Optional[list] = None,
                steps: Optional[str] = None) -> str:
    """Render one \\macro{...} token (no indent, no trailing newline) --
    the exact text spliced in for an insert, or over an existing call's own
    call_start:call_end span for a variant change."""
    if macro not in ALL_MACROS:
        raise ValueError(f"unknown slide-call macro: {macro!r}")
    if macro in VERSIONED_MACROS:
        if not version:
            raise ValueError(f"\\{macro} requires a version")
        return f"\\{macro}{{{id_slug}}}{{{version}}}"
    if macro == "slidestep":
        cond_list = conditions if conditions else DEFAULT_CONDITIONS
        return f"\\slidestep{{{id_slug}}}[{','.join(cond_list)}]{{{steps or DEFAULT_STEPS}}}"
    if macro in CONDITIONAL_MACROS:
        cond_list = conditions if conditions else DEFAULT_CONDITIONS
        return f"\\{macro}[{','.join(cond_list)}]{{{id_slug}}}"
    return f"\\{macro}{{{id_slug}}}"


def _apply(deck_path: Path, expected_text: str, mutate) -> str:
    """Shared stale-check-then-write path for every mutating function
    below: re-reads the file, verifies it still matches expected_text (the
    GUI tab's own last-loaded copy) before touching anything, applies
    `mutate(text) -> new_text`, writes the result, and returns it so the
    caller can refresh its own cached copy."""
    current = _read(deck_path)
    if current != expected_text:
        raise StaleFileError(
            f"{deck_path.name} changed on disk since it was last loaded -- "
            "reload the deck and retry."
        )
    new_text = mutate(current)
    _write(deck_path, new_text)
    return new_text


def remove_slide_calls(deck_path: Path, expected_text: str, calls: list[SlideCall]) -> str:
    """Remove slide calls: every call's line is cut in one
    stale-check-then-write, so it is a single file write and a single
    undo step. Cut from the last line to the first so each earlier call's
    offsets are still valid when its turn comes. Refuses the whole batch,
    changing nothing, if any one call isn't editable."""
    blocked = [c for c in calls if not c.editable]
    if blocked:
        raise ValueError(
            "can't remove " + ", ".join(c.id_slug for c in blocked)
            + f" -- {blocked[0].readonly_reason}"
        )

    def mutate(text: str) -> str:
        for call in sorted(calls, key=lambda c: c.line_start, reverse=True):
            text = text[: call.line_start] + text[call.line_end :]
        return text

    return _apply(deck_path, expected_text, mutate)


def normalize_course_url(url: str) -> str:
    """Accept a browser-safe HTTP(S) URL for a deck's course page."""
    clean = url.strip()
    if any(ch.isspace() or ord(ch) < 32 or ord(ch) == 127 for ch in clean):
        raise ValueError("Course link must not contain spaces or control characters.")
    try:
        parts = urlsplit(clean)
        if parts.scheme.lower() not in {"http", "https"} or not parts.hostname:
            raise ValueError("Enter a full http:// or https:// course URL.")
        _ = parts.port  # Reject malformed ports before storing the URL.
    except ValueError as exc:
        raise ValueError(f"Invalid course URL: {exc}") from exc
    return clean


def course_url_text(text: str, url: str, deck_name: str) -> str:
    """`text` with its course-URL comment set to `url` (removed when empty)."""
    clean = normalize_course_url(url) if url.strip() else ""
    begin = DOCUMENT_BEGIN_LINE_RE.search(text)
    if begin is None and clean:
        raise ValueError(f"{deck_name} has no \\begin{{document}} to place the course link before.")
    preamble_end = begin.start() if begin else len(text)
    for match in reversed(list(COURSE_URL_RE.finditer(text, 0, preamble_end))):
        line_start, line_end = _line_span(text, match.start(), match.end())
        text = text[:line_start] + text[line_end:]
    if not clean:
        return text
    begin = DOCUMENT_BEGIN_LINE_RE.search(text)
    newline = "\r\n" if "\r\n" in text else "\n"
    return (
        text[:begin.start()]
        + f"%% SlideMage course URL: {clean}{newline}"
        + text[begin.start():]
    )


def set_course_url(deck_path: Path, expected_text: str, url: str) -> str:
    """Store or remove a course URL as a comment in the deck preamble."""
    if url.strip():
        normalize_course_url(url)  # a bad URL is refused before anything is read

    return _apply(deck_path, expected_text, lambda text: course_url_text(text, url, deck_path.name))


def set_deck_tags(deck_path: Path, expected_text: str, tags: list[str]) -> str:
    """Writes `tags` as this deck's \\decktags{...} line (2026-09-19):
    replaces the deck's first live one in place, or inserts a new line just
    before \\begin{document} -- after the preamble \\input{}, which is what
    defines the inert \\decktags macro, so the deck keeps compiling. An
    empty list removes the directive. Refuses (changing nothing) for a deck
    that never loads the Slidemaster preamble, where the macro would be
    undefined."""
    clean = [t.strip().lower() for t in tags if t.strip()]

    def mutate(text: str) -> str:
        existing = find_decktags(text)
        if existing is not None:
            if not clean:
                # Drop the whole line, like remove_slide_calls() does.
                line_start, line_end = _line_span(text, existing.start(), existing.end())
                return text[:line_start] + text[line_end:]
            return text[: existing.start()] + f"\\decktags{{{','.join(clean)}}}" + text[existing.end():]
        if not clean:
            return text
        begin = DOCUMENT_BEGIN_LINE_RE.search(text)
        if begin is None:
            raise ValueError(f"{deck_path.name} has no \\begin{{document}} to tag before.")
        if "Slidemaster_preamble" not in text[: begin.start()]:
            raise ValueError(
                f"{deck_path.name} doesn't load the Slidemaster preamble, so "
                "\\decktags would not compile there."
            )
        newline = "\r\n" if "\r\n" in text else "\n"
        line = f"\\decktags{{{','.join(clean)}}}{newline}"
        return text[: begin.start()] + line + text[begin.start():]

    return _apply(deck_path, expected_text, mutate)


def change_slide_call_variant(
    deck_path: Path,
    expected_text: str,
    call: SlideCall,
    new_macro: str,
    new_version: Optional[str] = None,
    new_conditions: Optional[list] = None,
    new_steps: Optional[str] = None,
) -> str:
    if not call.editable:
        raise ValueError(f"can't change this call -- {call.readonly_reason}")
    if new_macro == "slidestep":
        new_steps = normalize_steps(new_steps or DEFAULT_STEPS)
    new_token = format_call(new_macro, call.id_slug, new_version, new_conditions, new_steps)

    def mutate(text: str) -> str:
        return text[: call.call_start] + new_token + text[call.call_end :]

    return _apply(deck_path, expected_text, mutate)


def set_calls_visibility(
    deck_path: Path, expected_text: str, calls: list[SlideCall], view: str, visible: bool,
) -> str:
    """Show or hide `calls` in the deck version `view` (one of
    DEFAULT_CONDITIONS), as one edit. A call that is not yet conditional
    becomes a \\conditionalslide listing the versions it stays in (and back
    to a plain \\slide when that is all of them); a \\slidestep keeps its
    steps. Pinned versions and \\slidefinal have no conditional form and are
    refused, as is hiding a slide from every version."""
    edits: list[tuple[SlideCall, str]] = []
    for call in calls:
        if not call.editable:
            raise ValueError(f"can't change {call.id_slug} -- {call.readonly_reason}")
        if call.macro not in VISIBILITY_MACROS:
            raise ValueError(f"\\{call.macro}{{{call.id_slug}}} can't be shown or hidden per view")
        if call.included_in(view) == visible:
            continue
        versions = [v for v in DEFAULT_CONDITIONS if call.included_in(v) != (v == view)]
        if not versions:
            raise ValueError(f"{call.id_slug} must stay in at least one view")
        macro = call.macro if call.macro in CONDITIONAL_MACROS else "conditionalslide"
        if macro == "conditionalslide" and versions == DEFAULT_CONDITIONS:
            macro = "slide"
        edits.append((call, format_call(macro, call.id_slug, None, versions, call.steps)))

    def mutate(text: str) -> str:
        for call, token in sorted(edits, key=lambda e: e[0].call_start, reverse=True):
            text = text[: call.call_start] + token + text[call.call_end :]
        return text

    return _apply(deck_path, expected_text, mutate)


def _section_title(title: str) -> str:
    """Validate a title placed directly inside ``\\section{}``."""
    clean = title.strip()
    if not clean:
        raise ValueError("Section title must not be empty.")
    if any(char in clean for char in "{}%\r\n"):
        raise ValueError("Section title must not contain braces, percent signs, or line breaks.")
    return clean


def _chapter_marker(text: str, chapter: Chapter) -> tuple[int, int, int, int]:
    """Return a live chapter marker's token and line bounds."""
    chapters = _parse_chapters(text)
    if chapter not in chapters:
        raise ValueError("This section is no longer at its scanned location; reload the deck and retry.")
    match = SECTION_RE.match(text, chapter.start)
    if match is None or match.group(1).strip() != chapter.title:
        raise ValueError("This section marker no longer matches its scanned location; reload the deck and retry.")
    token_end = match.end()
    line_start, line_end = _line_span(text, chapter.start, token_end)
    editable, reason = _editability(text, line_start, chapter.start, token_end, line_end)
    if not editable:
        raise ValueError(f"can't edit this section marker -- {reason}")
    return chapter.start, token_end, line_start, line_end


def _slide_marker(text: str, call: SlideCall) -> tuple[int, int]:
    """Return a live slide call's line bounds for a marker-line swap."""
    if call.call_start < 0 or call.call_end > len(text) or call.call_start >= call.call_end:
        raise ValueError("This slide is no longer at its scanned location; reload the deck and retry.")
    token = text[call.call_start:call.call_end]
    if SLIDE_CALL_RE.fullmatch(token) is None or not re.match(rf"\\{re.escape(call.macro)}(?:\{{|\[)", token):
        raise ValueError("This slide is no longer at its scanned location; reload the deck and retry.")
    line_start, line_end = _line_span(text, call.call_start, call.call_end)
    if (line_start, line_end) != (call.line_start, call.line_end):
        raise ValueError("This slide is no longer at its scanned location; reload the deck and retry.")
    editable, reason = _editability(text, line_start, call.call_start, call.call_end, line_end)
    if not editable:
        raise ValueError(f"can't move {call.id_slug} -- {reason}")
    return line_start, line_end


def add_section(deck_path: Path, expected_text: str, title: str, insert_at: int) -> str:
    """Insert a standalone ``\\section{title}`` line at ``insert_at``."""
    clean_title = _section_title(title)
    def mutate(text: str) -> str:
        return _splice(text, insert_at, f"\\section{{{clean_title}}}{_eol(text)}")

    return _apply(deck_path, expected_text, mutate)


def rename_section(deck_path: Path, expected_text: str, chapter: Chapter, title: str) -> str:
    """Rename one live, standalone section marker."""
    clean_title = _section_title(title)

    def mutate(text: str) -> str:
        token_start, token_end, _line_start, _line_end = _chapter_marker(text, chapter)
        return text[:token_start] + f"\\section{{{clean_title}}}" + text[token_end:]

    return _apply(deck_path, expected_text, mutate)


def _live_document_end(text: str) -> int:
    """The line start of the first live ``\\end{document}``, or EOF."""
    for match in DOCUMENT_END_RE.finditer(text):
        line_start = text.rfind("\n", 0, match.start()) + 1
        if not COMMENT_RE.search(text, line_start, match.start()):
            return line_start
    return len(text)


def section_editable(text: str, chapter: Chapter) -> bool:
    """Whether the section marker is a line of its own (a trailing comment is
    fine), so that it can be renamed, removed and moved."""
    match = SECTION_RE.match(text, chapter.start)
    if match is None:
        return False
    line_start, line_end = section_line_span(text, chapter)
    before = text[line_start:chapter.start]
    after = text[match.end():line_end].rstrip("\r\n")
    return not before.strip() and (not after.strip() or after.lstrip().startswith("%"))


def section_line_span(text: str, chapter: Chapter) -> tuple[int, int]:
    """Start and end (after its terminator) of the line holding the section marker."""
    return _line_span(text, chapter.start, chapter.start)


def section_append_point(deck: Deck, chapter: Optional[Chapter]) -> int:
    """Where a slide goes to become the last one of a section (None: the slides
    before the first one): after its last call, or below its marker line
    when it has none."""
    last = next((c for c in reversed(parse_slide_calls(deck)) if c.chapter == chapter), None)
    if last is not None:
        return last.line_end
    if chapter is None:
        raise ValueError("there are no slides before the first section")
    return section_line_span(deck.text, chapter)[1]


def remove_section(deck_path: Path, expected_text: str, chapter: Chapter) -> str:
    """Remove one section marker while retaining the slides it headed."""
    def mutate(text: str) -> str:
        _token_start, _token_end, line_start, line_end = _chapter_marker(text, chapter)
        return text[:line_start] + text[line_end:]

    return _apply(deck_path, expected_text, mutate)


def _swap_sections(text: str, chapter: Chapter, neighbor: Chapter) -> str:
    """`text` with two adjacent section blocks (each marker and all following
    content) swapped."""
    _chapter_marker(text, chapter)
    _chapter_marker(text, neighbor)
    chapters = _parse_chapters(text)
    chapter_index, neighbor_index = chapters.index(chapter), chapters.index(neighbor)
    if abs(chapter_index - neighbor_index) != 1:
        raise ValueError("Sections can only move past an adjacent section.")
    first, second = sorted((chapter, neighbor), key=lambda item: item.start)
    first_start = _line_span(text, first.start, first.start)[0]
    second_start = _line_span(text, second.start, second.start)[0]
    second_index = chapters.index(second)
    if second_index + 1 < len(chapters):
        next_chapter = chapters[second_index + 1]
        next_start = _line_span(text, next_chapter.start, next_chapter.start)[0]
    else:
        next_start = _live_document_end(text)
    if not first_start < second_start < next_start:
        raise ValueError("Section block boundaries are invalid; reload the deck and retry.")
    return text[:first_start] + text[second_start:next_start] + text[first_start:second_start] + text[next_start:]


def move_section(deck_path: Path, expected_text: str, chapter: Chapter, neighbor: Chapter) -> str:
    """Swap two adjacent section blocks, each marker and all following content."""
    return _apply(deck_path, expected_text, lambda text: _swap_sections(text, chapter, neighbor))


def move_section_to(deck_path: Path, expected_text: str, chapter: Chapter, index: int) -> str:
    """Move a section block so that it becomes the `index`-th section (0-based)
    of the deck, as one edit."""
    def mutate(text: str) -> str:
        chapters = _parse_chapters(text)
        if chapter not in chapters or not 0 <= index < len(chapters):
            raise ValueError("This section is no longer at its scanned location; reload the deck and retry.")
        position = chapters.index(chapter)
        while position != index:
            step = 1 if index > position else -1
            text = _swap_sections(text, chapters[position], chapters[position + step])
            chapters, position = _parse_chapters(text), position + step
        return text

    return _apply(deck_path, expected_text, mutate)


def move_slide_past_section(deck_path: Path, expected_text: str, call: SlideCall, chapter: Chapter) -> str:
    """Swap a slide marker and an immediately adjacent section marker line."""
    def mutate(text: str) -> str:
        slide_start, slide_end = _slide_marker(text, call)
        _token_start, _token_end, section_start, section_end = _chapter_marker(text, chapter)
        if slide_end == section_start:
            first_start, first_end, second_start, second_end = slide_start, slide_end, section_start, section_end
        elif section_end == slide_start:
            first_start, first_end, second_start, second_end = section_start, section_end, slide_start, slide_end
        else:
            first_start, first_end, second_start, second_end = (
                (slide_start, slide_end, section_start, section_end)
                if slide_start < section_start
                else (section_start, section_end, slide_start, slide_end)
            )
        for marker in _parse_chapters(text):
            if first_end <= marker.start < second_start:
                raise ValueError("A slide can cross only the neighboring section marker.")
        for match in SLIDE_CALL_RE.finditer(text, first_end, second_start):
            line_start = text.rfind("\n", 0, match.start()) + 1
            if not COMMENT_RE.search(text, line_start, match.start()):
                raise ValueError("A slide can cross only the neighboring section marker.")
        first_body = text[first_start:first_end].rstrip("\r\n")
        second_body = text[second_start:second_end].rstrip("\r\n")
        return (text[:first_start] + second_body + text[first_start + len(first_body):second_start]
                + first_body + text[second_start + len(second_body):])

    return _apply(deck_path, expected_text, mutate)


def restore_deck_text(deck_path: Path, expected_text: str, previous_text: str) -> str:
    """Write back a whole-file snapshot captured before some earlier edit --
    the slide list's Undo (its own undo stack) is the only caller. Goes through the same stale-check-then-write path
    as every other mutator here, so undo refuses (rather than silently
    clobbering) if the file changed on disk since the edit being undone --
    e.g. a Refresh picked up an outside edit in between."""
    return _apply(deck_path, expected_text, lambda _text: previous_text)


def insert_slide_call(
    deck_path: Path,
    expected_text: str,
    insert_at: int,
    indent: str,
    macro: str,
    id_slug: str,
    version: Optional[str] = None,
    conditions: Optional[list] = None,
    steps: Optional[str] = None,
) -> str:
    """Insert a new call as its own line at char offset `insert_at`, which
    must fall exactly at the start of an existing line (the GUI always
    derives it from an existing call's own line_start/line_end, both of
    which satisfy this by construction)."""
    if macro == "slidestep":
        steps = normalize_steps(steps or DEFAULT_STEPS)
    token = format_call(macro, id_slug, version, conditions, steps)

    def mutate(text: str) -> str:
        return _splice(text, insert_at, f"{indent}{token}{_eol(text)}")

    return _apply(deck_path, expected_text, mutate)


def insert_slide_calls(
    deck_path: Path, expected_text: str, insert_at: int, indent: str, id_slugs: list[str],
) -> str:
    """Insert one plain ``\\slide{}`` line per slug, consecutively and in
    order, at `insert_at` as a single edit -- so either all land or none."""

    def mutate(text: str) -> str:
        eol = _eol(text)
        lines = "".join(f"{indent}{format_call('slide', slug)}{eol}" for slug in id_slugs)
        return _splice(text, insert_at, lines)

    return _apply(deck_path, expected_text, mutate)


def move_slide_call(deck_path: Path, expected_text: str, call: SlideCall, neighbor: SlideCall) -> str:
    """Swap `call`'s line with `neighbor`'s (the adjacent call above or
    below it) as one edit. Only the two call lines trade places -- anything
    between them (a \\section or a comment) stays put, so
    moving a slide past it moves the slide into that chapter.
    Each line keeps its own terminator, so a last line without one stays
    that way."""
    for c in (call, neighbor):
        if not c.editable:
            raise ValueError(f"can't move {c.id_slug} -- {c.readonly_reason}")
    first, second = sorted((call, neighbor), key=lambda c: c.line_start)

    def body(text: str, c: SlideCall) -> str:
        return text[c.line_start:c.line_end].rstrip("\r\n")

    def mutate(text: str) -> str:
        a, b = body(text, first), body(text, second)
        return (
            text[:first.line_start] + b
            + text[first.line_start + len(a):second.line_start] + a
            + text[second.line_start + len(b):]
        )

    return _apply(deck_path, expected_text, mutate)


def move_slide_calls(deck_path: Path, expected_text: str, calls: list[SlideCall], insert_at: int) -> str:
    """Move the lines of `calls` (kept in their deck order, one after the
    other) to `insert_at`, a line start or the end of the file in the text
    they were scanned from -- into another section, to the end of one, or
    just up and down. Nothing but those lines changes place. One edit, so
    one undo step."""
    for c in calls:
        if not c.editable:
            raise ValueError(f"can't move {c.id_slug} -- {c.readonly_reason}")
    moved = sorted(calls, key=lambda c: c.line_start)

    def mutate(text: str) -> str:
        eol = _eol(text)
        lines = "".join(text[c.line_start:c.line_end].rstrip("\r\n") + eol for c in moved)
        rest = text
        for c in reversed(moved):
            rest = rest[:c.line_start] + rest[c.line_end:]
        shift = sum(c.line_end - c.line_start for c in moved if c.line_end <= insert_at)
        return _splice(rest, insert_at - shift, lines)

    return _apply(deck_path, expected_text, mutate)


def _eol(text: str) -> str:
    return "\r\n" if "\r\n" in text else "\n"


def _splice(text: str, insert_at: int, new_text: str) -> str:
    """`new_text` (complete lines) inserted at `insert_at`, which must be a
    line start or the end of the file. At the end of a file whose last
    line has no terminator, one is added first -- otherwise the new line
    would be glued onto that last line."""
    if insert_at < 0 or insert_at > len(text):
        raise ValueError(f"insert_at {insert_at} out of range for a {len(text)}-char file")
    if insert_at not in (0, len(text)) and text[insert_at - 1] != "\n":
        raise ValueError("insert_at must fall at the start of a line")
    prefix = _eol(text) if insert_at == len(text) and text and not text.endswith("\n") else ""
    return text[:insert_at] + prefix + new_text + text[insert_at:]


def end_insert_point(text: str) -> int:
    """Where a call goes in a file with no calls yet: the start of the
    \\end{document} line (it never shares its line with anything else), or
    the end of the file when there is no document-end marker."""
    match = DOCUMENT_END_RE.search(text)
    if match is None:
        return len(text)
    return text.rfind("\n", 0, match.start()) + 1


@dataclass
class InsertPosition:
    label: str
    insert_at: int
    indent: str


def slide_insert_positions(deck: Deck) -> list[InsertPosition]:
    """Places for inserting a slide before the first or after each existing call."""
    calls = parse_slide_calls(deck)
    if not calls:
        return [InsertPosition("At the end of the deck", end_insert_point(deck.text), "")]
    return [InsertPosition("At the beginning", calls[0].line_start, calls[0].indent)] + [
        InsertPosition(f"After {number}. {call.id_slug}", call.line_end, call.indent)
        for number, call in enumerate(calls, start=1)
    ]


def append_position(deck: Deck) -> tuple[int, str]:
    """(insert_at, indent) for a call appended after the last slide."""
    calls = parse_slide_calls(deck)
    if not calls:
        return end_insert_point(deck.text), ""
    last = calls[-1]
    return last.line_end, last.indent
