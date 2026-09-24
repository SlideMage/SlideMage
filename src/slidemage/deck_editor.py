"""Parse and edit a single deck file's own \\slide{}-family call list.

Pure parsing/editing on top of deck_scan.Deck/Chapter -- no Tkinter here,
so this can be unit-tested and reused independently of the GUI. The GUI
layer (deck_editor_tab.py/add_slide_dialog.py) is the only caller that
knows about Tk widgets; everything here just reads/writes deck *.tex text.

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
from .deck_scan import COMMENT_RE, COURSE_URL_RE, DOCUMENT_BEGIN_LINE_RE, DOCUMENT_END_RE, PROJECT_ROOT, Chapter, Deck, find_decktags

SLIDES_DIR = PROJECT_ROOT / "slides"

# Macros that take a pinned version as a second brace argument.
VERSIONED_MACROS = {"slideversion", "omitslideversion"}
# The one macro that takes an optional leading [conditions] list.
# \slidestep{id-slug}[conditions]{steps} is a \conditionalslide that also restricts the
# typeset reveal steps (2026-09-20); it is parsed and displayed, but not offered in
# BASE_MACROS -- its steps live in the deck file and are edited there.
CONDITIONAL_MACROS = {"conditionalslide", "slidestep"}
ALL_MACROS = {
    "slide", "slidefinal", "slideversion", "omitslide",
    "omitslideversion", "conditionalslide", "slidestep",
}
DEFAULT_STEPS = "1"
DEFAULT_CONDITIONS = ["instructor", "during-course", "after-course"]

# Display order for the GUI's variant pickers (deck_editor_tab.py,
# add_slide_dialog.py) -- the four macros with no separate version file.
BASE_MACROS = ["slide", "slidefinal", "omitslide", "conditionalslide"]

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


def is_commented_out(deck_text: str, call: SlideCall) -> bool:
    """Whether `call`'s own "\\macro{...}" token sits after an unescaped "%"
    on its line. parse_slide_calls() below reports a call like this (and
    every other call sharing its line with anything else) as merely
    non-editable via SlideCall.editable/readonly_reason, still including
    it in its returned list -- the deck editor UI needs to show it either
    way, greyed out rather than hidden. A consumer that treats every
    returned call as something the compiled deck actually renders (the
    appendix's thumbnail grid, update_all_previews.py's preview-cache
    scan) needs this narrower, comment-specific check instead: a call
    sharing its line with other *live* code is still a real call and
    should still count, only a commented-out one shouldn't."""
    line_start = deck_text.rfind("\n", 0, call.call_start) + 1
    return bool(COMMENT_RE.search(deck_text, line_start, call.call_start))


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
            "reload the deck editor tab and retry."
        )
    new_text = mutate(current)
    _write(deck_path, new_text)
    return new_text


def remove_slide_call(deck_path: Path, expected_text: str, call: SlideCall) -> str:
    if not call.editable:
        raise ValueError(f"can't remove this call -- {call.readonly_reason}")

    def mutate(text: str) -> str:
        return text[: call.line_start] + text[call.line_end :]

    return _apply(deck_path, expected_text, mutate)


def remove_slide_calls(deck_path: Path, expected_text: str, calls: list[SlideCall]) -> str:
    """Bulk version of remove_slide_call() for the deck editor's checkbox
    selection (2026-09-19, direct instruction): every call's line is cut in
    one stale-check-then-write, so it is a single file write and a single
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


def set_course_url(deck_path: Path, expected_text: str, url: str) -> str:
    """Store or remove a course URL as a comment in the deck preamble."""
    clean = normalize_course_url(url) if url.strip() else ""

    def mutate(text: str) -> str:
        begin = DOCUMENT_BEGIN_LINE_RE.search(text)
        if begin is None and clean:
            raise ValueError(f"{deck_path.name} has no \\begin{{document}} to place the course link before.")
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

    return _apply(deck_path, expected_text, mutate)


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
                # Drop the whole line, like remove_slide_call() does.
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
) -> str:
    if not call.editable:
        raise ValueError(f"can't change this call -- {call.readonly_reason}")
    new_token = format_call(new_macro, call.id_slug, new_version, new_conditions)

    def mutate(text: str) -> str:
        return text[: call.call_start] + new_token + text[call.call_end :]

    return _apply(deck_path, expected_text, mutate)


def restore_deck_text(deck_path: Path, expected_text: str, previous_text: str) -> str:
    """Write back a whole-file snapshot captured before some earlier edit --
    the deck editor's Undo button (deck_editor_tab.py's own undo stack)
    is the only caller. Goes through the same stale-check-then-write path
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
) -> str:
    """Insert a new call as its own line at char offset `insert_at`, which
    must fall exactly at the start of an existing line (the GUI always
    derives it from an existing call's own line_start/line_end, both of
    which satisfy this by construction)."""
    token = format_call(macro, id_slug, version, conditions)

    def mutate(text: str) -> str:
        return _splice(text, insert_at, f"{indent}{token}{_eol(text)}")

    return _apply(deck_path, expected_text, mutate)


def insert_text(deck_path: Path, expected_text: str, insert_at: int, new_text: str) -> str:
    """Splice one or more complete, already-terminated lines in at
    `insert_at` as a single edit (one undo step, one stale-file check) --
    e.g. a whole stamped block (blocks.stamp_text())."""
    return _apply(deck_path, expected_text, lambda text: _splice(text, insert_at, new_text))


def move_slide_call(deck_path: Path, expected_text: str, call: SlideCall, neighbor: SlideCall) -> str:
    """Swap `call`'s line with `neighbor`'s (the adjacent call above or
    below it) as one edit. Only the two call lines trade places -- anything
    between them (a \\section, a block marker, a comment) stays put, so
    moving a slide past it moves the slide into that chapter or block copy.
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
    the end of the file for one without it -- a blocks/*.tex file, which
    is only ever a list of calls."""
    match = DOCUMENT_END_RE.search(text)
    if match is None:
        return len(text)
    return text.rfind("\n", 0, match.start()) + 1


def append_position(deck: Deck) -> tuple[int, str]:
    """(insert_at, indent) for new calls appended after every call `deck`
    already has: the last call's own line_end and indent, so appended
    calls match the file's existing indentation -- or end_insert_point()
    with no indent when there are no calls yet. If that last call sits
    inside a stamped block copy (blocks.py), after the copy's end marker
    instead: appending is never meant to extend someone's block copy (a
    second stamped block would otherwise end up nested inside the first,
    and imported slides inside a copy)."""
    from . import blocks

    calls = parse_slide_calls(deck)
    if not calls:
        return end_insert_point(deck.text), ""
    last = calls[-1]
    for span in blocks.find_spans(deck.text):
        if span.start <= last.call_start < span.end:
            indent = re.match(r"[ \t]*", deck.text[span.start:]).group()
            return span.end, indent
    return last.line_end, last.indent
