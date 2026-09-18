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

from .archive import _read, _write
from .deck_scan import PROJECT_ROOT, Chapter, Deck

SLIDES_DIR = PROJECT_ROOT / "slides"

# Macros that take a pinned version as a second brace argument.
VERSIONED_MACROS = {"slideversion", "omitslideversion"}
# The one macro that takes an optional leading [conditions] list.
CONDITIONAL_MACROS = {"conditionalslide"}
ALL_MACROS = {
    "slide", "slidefinal", "slideversion", "omitslide",
    "omitslideversion", "conditionalslide",
}
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
    conditions: Optional[list]    # e.g. ["instructor"], only for \conditionalslide
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
        else:
            macro, idslug, version = "conditionalslide", m.group("cs_idslug"), None
            raw_conditions = m.group("cs_conditions")
            conditions = (
                [c.strip() for c in raw_conditions.split(",") if c.strip()]
                if raw_conditions is not None
                else list(DEFAULT_CONDITIONS)
            )

        slide_id, _, slug = idslug.partition("-")
        line_start, line_end = _line_span(deck.text, m.start(), m.end())
        editable, readonly_reason = _editability(deck.text, line_start, m.start(), m.end(), line_end)

        calls.append(SlideCall(
            macro=macro,
            id=slide_id,
            slug=slug,
            version=version,
            conditions=conditions,
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


def format_call(macro: str, id_slug: str, version: Optional[str] = None, conditions: Optional[list] = None) -> str:
    """Render one \\macro{...} token (no indent, no trailing newline) --
    the exact text spliced in for an insert, or over an existing call's own
    call_start:call_end span for a variant change."""
    if macro not in ALL_MACROS:
        raise ValueError(f"unknown slide-call macro: {macro!r}")
    if macro in VERSIONED_MACROS:
        if not version:
            raise ValueError(f"\\{macro} requires a version")
        return f"\\{macro}{{{id_slug}}}{{{version}}}"
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
        if insert_at < 0 or insert_at > len(text):
            raise ValueError(f"insert_at {insert_at} out of range for a {len(text)}-char file")
        if insert_at not in (0, len(text)) and text[insert_at - 1] != "\n":
            raise ValueError("insert_at must fall at the start of a line")
        eol = "\r\n" if "\r\n" in text else "\n"
        new_line = f"{indent}{token}{eol}"
        return text[:insert_at] + new_line + text[insert_at:]

    return _apply(deck_path, expected_text, mutate)
