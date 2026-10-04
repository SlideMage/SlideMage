"""Find and archive media/ and slides/ files nothing references anymore.

Two independent scans, both run by archive_unused_content():

- media/: a file is "in use" if any slides/*.tex file that is itself in
  use (see below) actually \\includegraphics{}s it (or similar -- \\chapterlogo{}, \\fullbleedframe{},
  \\begin{sideimageframe}{}{}, etc. all just take a bare "media/<name>"
  argument, so this looks for that literal substring rather than
  enumerating every macro that can carry one). A reference can omit the
  extension (LaTeX's own default-extension search, e.g.
  \\includegraphics{media/foo} with no extension) -- confirmed directly:
  slides/vpk-Collateralized-Debt-Obligations-current.tex does exactly this
  for media/midjourney-bankers-slicing-bonds.jpeg. Every media/ file is
  also grouped with every other file sharing its filename stem (e.g.
  chart-portfolio-frontier.svg and chart-portfolio-frontier.pdf); if any
  member of a stem group is used, the whole group counts as used, even
  though nothing ever references the .svg/.eps source directly --
  LaTeX/lualatex can only \\includegraphics the derived PDF, so a vector
  source would otherwise always look unused despite being exactly the
  thing worth keeping.

- slides/: a slides/<id>-current.tex or slides/<id>-vX-Y-Z.tex file is "in
  use" if actually \\slide{}/\\conditionalslide{}/\\omitslide{}/
  \\slidestep{}/\\slideversion{}/\\omitslideversion{}-ed from any *.tex file
  directly inside decks/ or decks/archive/ -- deliberately every *.tex file
  there,
  not just ones with \\documentclass (i.e. not deck_scan.scan_decks()):
  decks/test-slides.tex is a shared \\input{}-ed fragment with real
  \\slide{}/\\omitslide{} calls of its own (test.tex/test-mci.tex/
  test-ibk.tex/test-student.tex all \\input{} it rather than listing slides
  directly), so it has to be scanned too or its slides would look unused.

A 2026-09-27 direct report found two real false positives from this batch
run, both fixed here:

- \\slidestep{id-slug}[versions]{steps} (added to the project 2026-09-20)
  was never added to the slides/ scan's own macro list, so a slide
  referenced *only* via \\slidestep (e.g. IA2's 8gc, the Masterdeck's egk,
  test-slides.tex's own ZZH demo) looked completely unreferenced and got
  archived, even though a real deck compile still needs it.
- media/alt-text.json/.csv (the accessibility image-description store --
  see README.md's "Screen-reader accessibility"/"Describing images") sit
  directly inside media/, but are never \\includegraphics{}d -- they're
  read directly by SlideMage/Slidemaster_alt.lua, not referenced as a
  literal "media/<name>" string in any slide, so the media/ scan always
  treated them as unused. MEDIA_NEVER_UNUSED below is the fix: filenames
  excluded from the media/ scan outright, regardless of whether anything
  references them by name.

Both scans strip LaTeX comments first (2026-08-25, direct instruction --
previously a commented-out reference kept a file "in use" indefinitely,
silently masking otherwise-genuinely-unused content; now a reference only
counts if it's live). Neither scan looks inside slides/archive/ or
media/archive/ themselves (once archived, a file is out of scope until
moved back by hand).
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Callable

from .deck_scan import ARCHIVE_DIR, DECKS_DIR, PROJECT_ROOT

MEDIA_DIR = PROJECT_ROOT / "media"
MEDIA_ARCHIVE_DIR = MEDIA_DIR / "archive"
SLIDES_DIR = PROJECT_ROOT / "slides"
SLIDES_ARCHIVE_DIR = SLIDES_DIR / "archive"

# Never candidates for archiving, regardless of whether any slide's own
# text mentions them by name -- see the module docstring's 2026-09-27 entry.
MEDIA_NEVER_UNUSED = {"alt-text.json", "alt-text.csv"}

MEDIA_REF_RE = re.compile(r"media/([\w][\w.-]*)")
# These files belong to SlideMage's accessibility editor, not to a deck's
# media collection. In particular alt-text.json contains authored
# descriptions and must remain at its canonical path for the editor to use.
MEDIA_METADATA_FILENAMES = {"alt-text.json", "alt-text.csv"}


def _is_media_metadata_filename(name: str) -> bool:
    return (
        name in MEDIA_METADATA_FILENAMES
        or (name.startswith(".alt-text.json.") and name.endswith(".tmp"))
    )
# Same convention already used for syntax highlighting/other text scans in
# this project (qt_slide_source_tab.py's own COMMENT_RE, alt_blocks.py's) --
# an unescaped "%" starts a comment running to end of line; "\%" (a literal
# percent sign) does not.
COMMENT_RE = re.compile(r"(?<!\\)%.*")


def _strip_comments(text: str) -> str:
    """Text with every unescaped '%...' comment tail removed, so a
    reference that only exists inside a commented-out line no longer
    counts as "in use" -- see module docstring."""
    return COMMENT_RE.sub("", text)

SLIDE_CURRENT_RE = re.compile(
    r"\\slide\{([^}]+)\}"
    r"|\\slidefinal\{([^}]+)\}"
    r"|\\omitslide\{([^}]+)\}"
    r"|\\conditionalslide(?:\[[^\]]*\])?\{([^}]+)\}"
    # \slidestep{id-slug}[versions]{steps} -- id-slug comes first here,
    # unlike \conditionalslide's own [versions]{id-slug} order.
    r"|\\slidestep\{([^}]+)\}(?:\[[^\]]*\])?\{[^}]*\}"
)
SLIDE_VERSION_RE = re.compile(
    r"\\slideversion\{([^}]+)\}\{([^}]+)\}"
    r"|\\omitslideversion\{([^}]+)\}\{([^}]+)\}"
)

LogCallback = Callable[[str], None]


def _deck_texts() -> list[str]:
    """Raw text of deck and archived-deck .tex files, excluding generated wrappers."""
    texts: list[str] = []
    for directory in (DECKS_DIR, ARCHIVE_DIR):
        if not directory.is_dir():
            continue
        for path in directory.glob("*.tex"):
            if path.name.startswith("_"):
                continue
            texts.append(_strip_comments(path.read_text(encoding="utf-8", errors="replace")))
    return texts


def find_used_slide_filenames() -> set[str]:
    """Every slides/*.tex filename actually referenced from any deck."""
    used: set[str] = set()
    for text in _deck_texts():
        for match in SLIDE_CURRENT_RE.finditer(text):
            slide_id = next(g for g in match.groups() if g is not None)
            used.add(f"{slide_id}-current.tex")
        for match in SLIDE_VERSION_RE.finditer(text):
            id1, ver1, id2, ver2 = match.groups()
            slide_id, version = (id1, ver1) if id1 is not None else (id2, ver2)
            used.add(f"{slide_id}-v{version}.tex")
    return used


def find_unused_slides() -> list[Path]:
    """slides/*.tex files not referenced by any deck."""
    if not SLIDES_DIR.is_dir():
        return []
    used = find_used_slide_filenames()
    return sorted(p for p in SLIDES_DIR.glob("*.tex") if p.name not in used)


def find_used_media_filenames() -> set[str]:
    """Every media/ filename actually referenced (directly, or via a bare
    stem, or by sharing a stem with a file that is -- see module
    docstring) by a slide that is itself in use. A slide that is about to
    be archived does not keep its images (v5.14.2, direct report: one
    click archived the unused slides, and the next click found an image
    only one of those slides had used -- the media scan read every slide
    file, the ones being archived in the same run included)."""
    if not MEDIA_DIR.is_dir() or not SLIDES_DIR.is_dir():
        return set()

    media_files = [p for p in MEDIA_DIR.iterdir() if p.is_file()]
    by_name = {p.name: p for p in media_files}
    by_stem: dict[str, list[Path]] = {}
    for p in media_files:
        by_stem.setdefault(p.stem, []).append(p)

    directly_used: set[str] = set()
    used_slides = find_used_slide_filenames()
    for path in SLIDES_DIR.glob("*.tex"):
        if path.name not in used_slides:
            continue
        text = _strip_comments(path.read_text(encoding="utf-8", errors="replace"))
        for token in MEDIA_REF_RE.findall(text):
            if token in by_name:
                directly_used.add(token)
            elif token in by_stem:
                # No extension in the reference -- any file with this stem
                # could be the one LaTeX's default-extension search picks,
                # so treat them all as used rather than guessing which.
                directly_used.update(p.name for p in by_stem[token])

    used: set[str] = set()
    for siblings in by_stem.values():
        if any(p.name in directly_used for p in siblings):
            used.update(p.name for p in siblings)
    return used


def find_unused_media() -> list[Path]:
    """media/ files not referenced by any slide, directly or via a
    same-stem sibling that is."""
    if not MEDIA_DIR.is_dir():
        return []
    used = find_used_media_filenames()
    return sorted(
        p for p in MEDIA_DIR.iterdir()
        if p.is_file()
        and p.name not in used
        and p.name not in MEDIA_NEVER_UNUSED
        and not _is_media_metadata_filename(p.name)
    )


def _archive_files(
    files: list[Path], archive_dir: Path, kind: str, log: LogCallback
) -> int:
    """kind: singular noun for one file, e.g. "media file" or "slide"."""
    if not files:
        log(f"No unused {kind}s found.")
        return 0
    archive_dir.mkdir(parents=True, exist_ok=True)
    moved = 0
    for path in files:
        dest = archive_dir / path.name
        if dest.exists():
            log(f"Skipped {path.name} -- already exists in {archive_dir.name}/")
            continue
        shutil.move(str(path), str(dest))
        log(f"Archived {kind}: {path.name}")
        moved += 1
    return moved


def archive_unused_content(log: LogCallback) -> tuple[int, int]:
    """Move every unused media/ file into media/archive/ and every unused
    slides/ file into slides/archive/. Returns (media moved, slides
    moved)."""
    media_moved = _archive_files(find_unused_media(), MEDIA_ARCHIVE_DIR, "media file", log)
    slides_moved = _archive_files(find_unused_slides(), SLIDES_ARCHIVE_DIR, "slide", log)
    log(
        f"==== Archive unused content done: {media_moved} media file(s), "
        f"{slides_moved} slide(s) moved ===="
    )
    return media_moved, slides_moved
