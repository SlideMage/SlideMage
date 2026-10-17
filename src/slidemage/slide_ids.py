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

from .fileio import read_text_exact, write_text_exact
from . import project, slide_language
from .project import ProjectContext

TEMPLATE_RELATIVE = Path(".scripts") / "R_Slidemaster" / "inst" / "templates" / "slide-template.tex"

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
# A regular slide id starts with a letter (2026-10-04, direct instruction):
# ids starting with a digit are reserved for the SlideMage manual (1##) and
# the demo slides (2##), so the first character alone tells them apart.
ID_FIRST_ALPHABET = "".join(c for c in ID_ALPHABET if c.isalpha())
# First digits of the reserved ids: 1 = SlideMage manual, 2 = demo slides.
RESERVED_FIRST_DIGITS = "12"

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


def regular_id_reason(slide_id: str) -> Optional[str]:
    """illegal_id_reason() plus the letter-first rule for regular slides:
    why `slide_id` must not be given to a regular (non-manual, non-demo)
    slide, or None if it is fine."""
    reason = illegal_id_reason(slide_id)
    if reason:
        return reason
    if not slide_id[:1].isalpha():
        return "starts with a digit (reserved for the SlideMage manual and demo slides)"
    return None


def reserved_id_reason(slide_id: str) -> Optional[str]:
    """Why `slide_id` must not be given to a SlideMage manual or demo slide
    (form: a digit from RESERVED_FIRST_DIGITS, then a letter other than
    "e"), or None."""
    reason = illegal_id_reason(slide_id)
    if reason:
        return reason
    if slide_id[:1] not in RESERVED_FIRST_DIGITS:
        return f"a manual/demo slide id starts with one of {RESERVED_FIRST_DIGITS!r}"
    if not slide_id[1:2].isalpha() or slide_id[1:2] == "e":
        # never "e": "1e5" would read as scientific notation
        return "a manual/demo slide id has a letter other than 'e' in second place"
    return None
# Matches SPslide(refresh=TRUE)'s own "^([^-]+)-.*\\.tex$": the ID is
# everything before the first hyphen, for both ID-slug-current.tex and
# ID-slug-vX-Y-Z.tex.
ID_FROM_FILENAME_RE = re.compile(r"^([^-]+)-.*\.tex$")


def existing_ids_from_csv(ctx: ProjectContext) -> set[str]:
    if not ctx.slide_ids_csv.exists():
        return set()
    lines = read_text_exact(ctx.slide_ids_csv).splitlines()
    ids = {line.strip().strip('"') for line in lines[1:]}  # skip "id" header
    ids.discard("")
    return ids


def existing_ids_from_disk(ctx: ProjectContext) -> set[str]:
    if not ctx.slides_dir.is_dir():
        return set()
    ids = set()
    for path in ctx.slides_dir.glob("*.tex"):
        m = ID_FROM_FILENAME_RE.match(path.name)
        if m:
            ids.add(m.group(1))
    return ids


def list_id_slugs(ctx: ProjectContext) -> list[str]:
    """Every id-slug with a slides/<id-slug>-current.tex file, sorted --
    the Add slide sheet's slide picker."""
    if not ctx.slides_dir.is_dir():
        return []
    suffix = slide_language.CURRENT_SUFFIX
    return sorted(
        p.name[: -len(suffix)]
        for p in ctx.slides_dir.glob(f"*{suffix}")
    )


def mint_slide_id(ctx: ProjectContext, reserved: Optional[str] = None) -> str:
    """Draw a random 3-char ID, avoiding collisions with both
    slide_ids.csv *and* every ID actually present under slides/ (a
    superset check -- this can only avoid more collisions than the R
    side's CSV-only check, never fewer, so the two mints can never
    collide with each other), and rejecting any draw illegal_id_reason()
    names (so an ID is never mistaken for a number or a special value
    elsewhere in the toolchain). The first character is always a letter
    (ID_FIRST_ALPHABET), and the collision check ignores case, since
    Windows can't tell "zzh-..." from "ZZH-..." apart.

    `reserved` (one of RESERVED_FIRST_DIGITS) mints a SlideMage manual or
    demo slide id instead: that digit, a letter, then any character."""
    if reserved is not None and reserved not in RESERVED_FIRST_DIGITS:
        raise ValueError(f"reserved must be one of {RESERVED_FIRST_DIGITS!r}, got {reserved!r}")
    existing = {i.lower() for i in existing_ids_from_csv(ctx) | existing_ids_from_disk(ctx)}
    while True:
        if reserved is None:
            candidate = random.choice(ID_FIRST_ALPHABET) + "".join(
                random.choice(ID_ALPHABET) for _ in range(ID_LENGTH - 1)
            )
            reason = regular_id_reason(candidate)
        else:
            candidate = reserved + random.choice(ID_FIRST_ALPHABET) + "".join(
                random.choice(ID_ALPHABET) for _ in range(ID_LENGTH - 2)
            )
            reason = reserved_id_reason(candidate)
        if candidate in existing or reason:
            continue
        return candidate


def append_slide_id(ctx: ProjectContext, slide_id: str) -> None:
    """Append one CSV row for `slide_id`, byte-for-byte matching R's own
    write.csv(..., row.names=FALSE) format: quoted value, CRLF line
    ending. Creates the file (with just the "id" header) first if it
    doesn't exist yet."""
    if not ctx.slide_ids_csv.exists():
        with open(ctx.slide_ids_csv, "w", encoding="utf-8", newline="") as f:
            f.write('"id"\r\n')
    with open(ctx.slide_ids_csv, "a", encoding="utf-8", newline="") as f:
        f.write(f'"{slide_id}"\r\n')


def build_new_slide_header(cross_ref_id_slug: Optional[str] = None) -> str:
    """The exact header block create_slide_file() writes for a brand-new
    file -- exposed on its own so that the files written elsewhere (the
    PPTX/ODP import, the admin slides) use the same literal string instead
    of a copy that could drift apart."""
    header = "%% Included in decks: (none)\r\n%%\r\n"
    if cross_ref_id_slug is not None:
        header += f"%% Translation of: {cross_ref_id_slug}\r\n%%\r\n"
    header += "\r\n"
    return header


def slide_body(path: Path) -> str:
    """The content of the slide file `path` without its header comments (see body_of)."""
    return body_of(read_text_exact(path))


_HEADER_RE = re.compile(r"\A(?:%%[^\r\n]*\r?\n)*(?:[ \t]*\r?\n)*")


def split_header(text: str) -> tuple[str, str]:
    """(header, rest) of a slide file's `text`: the leading "%%" comment lines of the blocks
    build_new_slide_header writes, and the blank lines after them, and everything else."""
    end = _HEADER_RE.match(text).end()
    return text[:end], text[end:]


def body_of(body_text: str) -> str:
    """The content of a slide file's `body_text` without its header comments -- its "Included in
    decks", "Translation of" and "<LANG> translation" blocks describe *that* file, not a copy
    of it. Each is its own two-line block (the comment line plus a bare "%%" closer): strip
    the whole block, or a dangling "%%" is left behind."""
    body_text = _INCLUDED_IN_DECKS_RE.sub("", body_text)
    body_text = re.sub(r"%% Translation of: [^\r\n]*\r?\n%%\r?\n", "", body_text)
    body_text = re.sub(r"%% (?:EN|DE|mult) translation: [^\r\n]*\r?\n%%\r?\n", "", body_text)
    # Collapse a run of now-orphaned blank lines at the very top down to none, so the new
    # file's own header sits flush against real content, exactly like a template-seeded file.
    return re.sub(r"^(?:[ \t]*\r?\n)+", "", body_text)


def create_slide_file(
    ctx: ProjectContext,
    slide_id: str,
    slug: str,
    language: str,
    cross_ref_id_slug: Optional[str] = None,
    body: Optional[str] = None,
) -> Path:
    """Create slides/<id>-<LANG>-<slug>-current.tex (added 2026-08-24:
    `language`, one of slide_language.LANGUAGES, is always encoded into
    the filename itself -- Slidemaster_preamble_base.tex's own
    \\setSlideLanguageFromSlug parses it back out at compile time).
    The content is `body` when given (e.g. another slide's
    slide_body()), else the packaged starter template (mirrors slide.new.R);
    this function writes its own fresh header. When
    `cross_ref_id_slug` is given, writes a "%% Translation of: ..." header
    pointing at it; the caller is responsible for calling
    add_translation_backreference() on the *source* slide separately -- this
    function only ever touches the new file. Raises FileExistsError if the
    file is already there."""
    if language not in slide_language.LANGUAGES:
        raise ValueError(f"language must be one of {slide_language.LANGUAGES}, got {language!r}")
    dest = ctx.slides_dir / slide_language.current_name(f"{slide_id}-{language}-{slug}")
    if dest.exists():
        raise FileExistsError(f"{dest} already exists")
    ctx.slides_dir.mkdir(parents=True, exist_ok=True)

    if body is None:
        body = read_template(ctx)
    write_text_exact(dest, build_new_slide_header(cross_ref_id_slug) + body)
    return dest


def read_template(ctx: ProjectContext) -> str:
    """The project's starter slide, or the bundled example's when absent."""
    if ctx.slide_template_path.is_file():
        return read_text_exact(ctx.slide_template_path)
    example = project.template_dir("example")
    if example is not None:
        template = example / TEMPLATE_RELATIVE
        if template.is_file():
            return read_text_exact(template)
    raise FileNotFoundError(
        f"No slide template found at {ctx.slide_template_path} or in the bundled example project."
    )


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
    text = read_text_exact(source_path)
    write_text_exact(source_path, with_translation_backreference(text, language, new_id_slug))


def with_translation_backreference(text: str, language: str, new_id_slug: str) -> str:
    """`text` of a slide file with the "%% <language> translation: <new_id_slug>" block added (see
    add_translation_backreference)."""
    eol = "\r\n" if "\r\n" in text else "\n"
    new_line = f"%% {language} translation: {new_id_slug}{eol}%%{eol}"

    m = _INCLUDED_IN_DECKS_RE.search(text)
    if m:
        insert_at = m.end()
    else:
        m2 = re.search(r"\r?\n\r?\n", text)
        insert_at = m2.end() if m2 else 0
    return text[:insert_at] + new_line + text[insert_at:]
