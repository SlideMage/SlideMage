"""Mint slide IDs and scaffold new slide files -- Python port of
.scripts/R_Slidemaster/R/{slide.new.id,SPslide,slide.new}.R for the GUI's
own "create new slide" path, so it doesn't need R/RStudio installed.
Mirrors those files' exact behavior (alphabet, collision-avoidance, CSV
format, template) rather than reimplementing it independently, so an ID
minted from either side can never collide with the other.
"""
from __future__ import annotations

import random
import re
from pathlib import Path
from typing import Optional

from . import slide_language
from .deck_scan import PROJECT_ROOT

SLIDE_IDS_CSV = PROJECT_ROOT / "slide_ids.csv"
SLIDES_DIR = PROJECT_ROOT / "slides"
TEMPLATE_PATH = PROJECT_ROOT / ".scripts" / "R_Slidemaster" / "inst" / "templates" / "slide-template.tex"

# Matches the *unadorned* two-line "Included in decks" block only -- unlike
# deck_headers.HEADER_RE, deliberately does NOT also consume a trailing
# blank line, so add_translation_backreference() below can insert its own
# line immediately after this block's closing "%%" and before that blank
# line, keeping both comment blocks stacked tightly rather than splitting
# them apart.
_INCLUDED_IN_DECKS_RE = re.compile(r"%% Included in decks: [^\r\n]*\r?\n%%\r?\n")

# Matches .scripts/R_Slidemaster/R/slide.new.id.R's legal.lowercase/legal.numeric
# exactly (SPslide()'s own defaults: id.n=3, use_lowercase=TRUE,
# use_uppercase=FALSE, use_numeric=TRUE) -- avoids confusable characters
# (no l/1, o/0).
ID_ALPHABET = "abcdefghijkmnpqrstuvwxyz23456789"
ID_LENGTH = 3

ALL_NUMERIC_RE = re.compile(r"^[0-9]+$")
# An id must never be readable as a number or another special value by any tool that
# touches the id lists (CSV/JSON readers, R, pandas, spreadsheets, PowerShell): all digits
# ("838"), scientific notation ("8e6" = 8,000,000), the float spellings "inf"/"nan", and
# the Windows device names (an id is the start of a file name). (2026-09-21, direct
# instruction after "838" and "538" turned up; the check found "258", "858", "2e6" and "8e6" too.)
SCIENTIFIC_NOTATION_RE = re.compile(r"^[0-9]+[eE][+-]?[0-9]+$")
FLOAT_WORDS = {"inf", "nan"}
WINDOWS_DEVICE_NAMES = {"aux", "con", "nul", "prn"}
# Real (or widely recognized) 3-character words/abbreviations that happen to
# be legal ids but read badly, vulgar, or offensive on a slide's own
# footer/in conversation (2026-09-27, direct instruction, after "pee" turned
# up as slide id_slug; expanded 2026-09-28 by direct request to a broader
# vulgarity/slur/slang denylist). Add to this set by hand as more turn up --
# there's no automated word-list check, just this explicit denylist. Mirrored
# in .scripts/R_Slidemaster/R/slide.new.id.R.
BANNED_WORDS = {
    "pee", "sex", "wtf", "ass", "cum", "tit", "fag", "cnt", "kkk",
    "fap", "ffs", "poo", "hos", "gun", "gay", "rip",
}


def illegal_id_reason(slide_id: str) -> Optional[str]:
    """Why `slide_id` must not be used as a slide id, or None if it is fine."""
    if ALL_NUMERIC_RE.match(slide_id):
        return "all digits (reads as a number)"
    if SCIENTIFIC_NOTATION_RE.match(slide_id):
        return "reads as a number in scientific notation"
    if slide_id.lower() in FLOAT_WORDS:
        return "reads as a floating-point special value"
    if slide_id.lower() in WINDOWS_DEVICE_NAMES:
        return "is a reserved Windows device name"
    if slide_id.lower() in BANNED_WORDS:
        return "is a banned word"
    return None
# Matches SPslide(refresh=TRUE)'s own "^([^-]+)-.*\\.tex$": the ID is
# everything before the first hyphen, for both ID-slug-current.tex and
# ID-slug-vX-Y-Z.tex.
ID_FROM_FILENAME_RE = re.compile(r"^([^-]+)-.*\.tex$")


def _existing_ids_from_csv() -> set[str]:
    if not SLIDE_IDS_CSV.exists():
        return set()
    with open(SLIDE_IDS_CSV, encoding="utf-8", newline="") as f:
        lines = f.read().splitlines()
    ids = {line.strip().strip('"') for line in lines[1:]}  # skip "id" header
    ids.discard("")
    return ids


def _existing_ids_from_disk() -> set[str]:
    if not SLIDES_DIR.is_dir():
        return set()
    ids = set()
    for path in SLIDES_DIR.glob("*.tex"):
        m = ID_FROM_FILENAME_RE.match(path.name)
        if m:
            ids.add(m.group(1))
    return ids


def list_id_slugs() -> list[str]:
    """Every id-slug with a slides/<id-slug>-current.tex file, sorted --
    shared between the "Add slide" dialog's own existing-slide picker
    (add_slide_dialog.py) and the main window's slide search box
    (gui.py)."""
    if not SLIDES_DIR.is_dir():
        return []
    suffix = "-current.tex"
    return sorted(
        p.name[: -len(suffix)]
        for p in SLIDES_DIR.glob(f"*{suffix}")
    )


def mint_slide_id() -> str:
    """Draw a random 3-char ID, avoiding collisions with both
    slide_ids.csv *and* every ID actually present under slides/ (a
    superset check -- this can only avoid more collisions than the R
    side's CSV-only check, never fewer, so the two mints can never
    collide with each other), and rejecting any draw illegal_id_reason()
    names (so an ID is never mistaken for a number or a special value
    elsewhere in the toolchain)."""
    existing = _existing_ids_from_csv() | _existing_ids_from_disk()
    while True:
        candidate = "".join(random.choice(ID_ALPHABET) for _ in range(ID_LENGTH))
        if candidate in existing or illegal_id_reason(candidate):
            continue
        return candidate


def append_slide_id(slide_id: str) -> None:
    """Append one CSV row for `slide_id`, byte-for-byte matching R's own
    write.csv(..., row.names=FALSE) format: quoted value, CRLF line
    ending. Creates the file (with just the "id" header) first if it
    doesn't exist yet."""
    if not SLIDE_IDS_CSV.exists():
        with open(SLIDE_IDS_CSV, "w", encoding="utf-8", newline="") as f:
            f.write('"id"\r\n')
    with open(SLIDE_IDS_CSV, "a", encoding="utf-8", newline="") as f:
        f.write(f'"{slide_id}"\r\n')


def build_new_slide_header(cross_ref_id_slug: Optional[str] = None) -> str:
    """The exact header block create_slide_file() writes for a brand-new
    file -- exposed on its own (2026-08-25) so a caller that needs to
    strip it back off a just-created file (qt_duplicate_slide_dialog.py's
    own "auto-translate the slide body" flow: translate everything *after*
    this header, never the header comments themselves) can compute its
    exact length without duplicating the literal string and risking the
    two copies drifting apart."""
    header = "%% Included in decks: (none)\r\n%%\r\n"
    if cross_ref_id_slug is not None:
        header += f"%% Translation of: {cross_ref_id_slug}\r\n%%\r\n"
    header += "\r\n"
    return header


def create_slide_file(
    slide_id: str,
    slug: str,
    language: str,
    base_on: Optional[Path] = None,
    cross_ref_id_slug: Optional[str] = None,
) -> Path:
    """Create slides/<id>-<LANG>-<slug>-current.tex (added 2026-08-24:
    `language`, one of slide_language.LANGUAGES, is always encoded into
    the filename itself -- Slidemaster_preamble_base.tex's own
    \\setSlideLanguageFromSlug parses it back out at compile time, see
    LANGUAGE_NOTES.md). Content is seeded byte-for-byte from `base_on`
    (an existing slide's own current.tex -- a translation starting point)
    when given, else from the packaged starter template as before (mirrors
    slide.new.R either way) -- `base_on`'s own header block (its
    "Included in decks"/cross-reference comments, which describe *that*
    file, not this new one) is stripped first, this function writes its
    own fresh header instead. When `cross_ref_id_slug` is given, writes a
    "%% Translation of: ..." header pointing at it; the caller is
    responsible for calling add_translation_backreference() on the
    *source* slide separately -- this function only ever touches the new
    file. Raises FileExistsError if the file is already there."""
    if language not in slide_language.LANGUAGES:
        raise ValueError(f"language must be one of {slide_language.LANGUAGES}, got {language!r}")
    dest = SLIDES_DIR / f"{slide_id}-{language}-{slug}-current.tex"
    if dest.exists():
        raise FileExistsError(f"{dest} already exists")
    SLIDES_DIR.mkdir(parents=True, exist_ok=True)

    if base_on is not None:
        body_text = base_on.read_bytes().decode("utf-8")
        # Each of these three comment kinds is its own two-line block (the
        # comment line itself plus a bare "%%" closer) -- strip the whole
        # block, not just the first line, or a dangling bare "%%" is left
        # behind. Order doesn't matter; none of the three patterns overlap.
        body_text = _INCLUDED_IN_DECKS_RE.sub("", body_text)
        body_text = re.sub(r"%% Translation of: [^\r\n]*\r?\n%%\r?\n", "", body_text)
        body_text = re.sub(r"%% (?:EN|DE|mult) translation: [^\r\n]*\r?\n%%\r?\n", "", body_text)
        # Collapse a run of now-orphaned blank lines at the very top down
        # to none, so the new file's own header (added below) sits flush
        # against real content, exactly like a template-seeded file does.
        body_text = re.sub(r"^(?:[ \t]*\r?\n)+", "", body_text)
    else:
        body_text = TEMPLATE_PATH.read_bytes().decode("utf-8")

    header = build_new_slide_header(cross_ref_id_slug)

    dest.write_text(header + body_text, encoding="utf-8", newline="")
    return dest


def add_translation_backreference(source_path: Path, language: str, new_id_slug: str) -> None:
    """Insert "%% <language> translation: <new_id_slug>" into an existing
    slide's own header block -- the other half of create_slide_file()'s
    "base on existing slide" cross-reference, written onto the *source*
    file being translated from. A surgical text insert, same style as
    slide_versioning.set_marker()'s own "insert right after the leading
    header-comment block" logic: right after the existing
    "%% Included in decks: ...\\n%%\\n" block if there is one, else at the
    very top of the file. Repeat calls (a slide translated into more than
    one other language) each add their own line rather than overwriting;
    slide_rename.regenerate_translation_links() already tolerates more
    than one "%% <LANG> translation: ..." line per file."""
    if language not in slide_language.LANGUAGES:
        raise ValueError(f"language must be one of {slide_language.LANGUAGES}, got {language!r}")
    text = source_path.read_text(encoding="utf-8", newline="")
    eol = "\r\n" if "\r\n" in text else "\n"
    new_line = f"%% {language} translation: {new_id_slug}{eol}%%{eol}"

    m = _INCLUDED_IN_DECKS_RE.search(text)
    if m:
        insert_at = m.end()
    else:
        m2 = re.search(r"\r?\n\r?\n", text)
        insert_at = m2.end() if m2 else 0
    new_text = text[:insert_at] + new_line + text[insert_at:]
    source_path.write_text(new_text, encoding="utf-8", newline="")
