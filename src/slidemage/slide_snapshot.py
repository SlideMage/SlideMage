"""Compile-time PNG snapshots of each slide's final build step.

Every compile that touches a slide -- a single-slide preview render, or a
full-deck instructor compile -- refreshes a PNG of that slide's last page
(its final `\\pause`/overlay step, i.e. what an instructor sees once
everything has built) into a flat, gitignored `.previews/slide_previews/`
directory (moved under previews/ 2026-09-18, then .previews/ the same day;
was a project-root folder before that; dot-prefixed since nothing here is
ever something the user needs to interact with).
The point is purely to let a review UI show *something current-ish* without
paying a LaTeX compile to do it -- these are a best-effort cache, refreshed
opportunistically whenever a compile happens to touch that slide, not a
guaranteed-fresh source of truth. See ALT_TEXT_NOTES.md.

Requires PyMuPDF (`fitz`) -- the one addition beyond this project's
previous "PySide6 only" dependency policy (requirements.txt). Justified by
precedent: `decks/render/compare_render.py`'s own page-identification
approach (every compiled page's footer carries "slide id: XXX", read via
`page.get_text()`) is reused here almost verbatim, and that tool already
proved PyMuPDF works cleanly for this project's PDFs.

**Template- and resolution-specific since 2026-08-15.** A slide can be
compiled under any of this project's three institution templates (Graz,
Innsbruck, MCI -- see TEMPLATES below), and looks meaningfully different
under each (different colors/logo). A single shared cache keyed only by
slide id would show whichever institution happened to compile it last,
regardless of which deck's preview you were actually looking at -- wrong
often enough to be worse than no cache. Every capture/lookup is keyed by
(template, bare id, pixel size) instead, filename
`<Template>-<bare id>-<width>-<height>.png`, e.g.
`UniGraz-22s-1920-1080.png`. Lookups are strict: no cross-template
fallback, so a Graz deck never shows an Innsbruck-only cached image by
accident -- it just shows "not captured yet".

**Filename is `<bare id>-<Template>-<width>-<height>.png`** (bare id
first, e.g. `22s-UniGraz-1920-1080.png`), not the reverse -- changed
2026-08-17 (direct instruction: "shift the three-letter slug to the front
of the filename to facilitate searching") from the original
`<Template>-<bare id>-...` order this module used through 2026-08-16. A
bare id never itself contains "-" (`\\setSlideID` takes everything up to
the *first* one), so leading with it also makes every filename in this
directory sort and glob-match by slide first, template second -- e.g.
`22s-*.png` finds both institutions' renders of one slide, which the old
order couldn't do without a wildcard *before* the id too.

**Gains an optional `<Lang>` segment right after the bare id (2026-08-24,
see LANGUAGE_NOTES.md)** for a slide whose own id-slug carries a language
segment (`EN`/`DE`/`mult` -- see slide_language.py): `22s-DE-UniGraz-
1920-1080.png`. Resolved from disk inside snapshot_path() itself, not
passed in by any caller, so this needed no changes anywhere else in the
app. A legacy, not-yet-migrated slide's filename is completely unchanged
(no segment at all), so the ~665 already-cached files never needed
mass-regenerating when this landed.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

# `import fitz` still works but is deprecated in current PyMuPDF releases
# ("Use `import pymupdf` instead") -- aliased so the rest of this module
# reads the same either way.
import pymupdf as fitz

from . import slide_language
from .deck_scan import PROJECT_ROOT

SNAPSHOT_DIR = PROJECT_ROOT / ".previews" / "slide_previews"

# Every compiled frame carries this footer element unconditionally (theme
# footer template, Slidemaster_preamble_base.tex) -- not something special
# to test builds. `\S+` stops at the space before a possible
# "| omitted from student deck" suffix, so the bare id is always what's
# captured regardless of that flag.
_SLIDE_ID_RE = re.compile(r"slide id:\s*(\S+)")

# Every institution template is a one-line \input{} swap on top of an
# otherwise-shared preamble (confirmed directly, 2026-08-15: all four
# decks/test*.tex files share an identical skeleton apart from which of
# these three files they \input) -- so detecting which one a deck uses is
# one regex against its own preamble text, not a whole-file diff.
# "uni-graz" is what GENERIC_PREAMBLE (slide_preview.py) and every current
# real deck actually use, so it's the reasonable default when detection
# finds nothing (a deck with a preamble this regex doesn't recognize at
# all, not merely "no institution chosen" -- there's no such thing as a
# deck with no institution). "slidemage" (2026-10-03) is the generic
# SlideMage template shipped in example/, not an institution's.
TEMPLATE_RE = re.compile(
    r"\\input\{Slidemaster_preamble_(uni-graz|uni-ibk|mci|slidemage)\}")
TEMPLATES = {
    "uni-graz": "UniGraz",
    "uni-ibk": "UniIbk",
    "mci": "Mci",
    "slidemage": "SlideMage",
}
# How the deck settings dialog names the templates (a key not listed shows as is).
TEMPLATE_LABELS = {
    "slidemage": "SlideMage",
    "uni-graz": "University of Graz",
    "uni-ibk": "University of Innsbruck",
    "mci": "MCI",
}
DEFAULT_TEMPLATE = "uni-graz"


def detect_template(preamble_text: str) -> str:
    """The template key (one of TEMPLATES) a deck's own preamble selects,
    defaulting to DEFAULT_TEMPLATE when the pattern isn't found."""
    match = TEMPLATE_RE.search(preamble_text)
    return match.group(1) if match else DEFAULT_TEMPLATE


def _template_name(template: str) -> str:
    return TEMPLATES.get(template, TEMPLATES[DEFAULT_TEMPLATE])


# The template a slide is rendered in when no deck is involved -- the slide
# editor's Render to PDF and Preview, tikz illustration renders (2026-10-03,
# direct instruction: chosen in Settings -> General, out of the box the
# generic SlideMage template). Only a template whose preamble file a deck of
# this project can find is offered; otherwise the choice falls back to the
# SlideMage template, then Graz, then whichever template there is.
RENDER_TEMPLATE_SETTING_KEY = "default_template"
OUT_OF_THE_BOX_RENDER_TEMPLATE = "slidemage"


def framework_dirs(root: Path | None = None) -> list[Path]:
    """The LaTeX framework folders a project's decks search (its .latexmkrc
    puts one on TEXINPUTS): $SLIDEMASTER_LATEX, else ../latex (a project
    next to the framework, like example/) or ../SlideMage/latex (a project
    next to a SlideMage checkout). Only folders holding
    Slidemaster_preamble_base.tex count."""
    root = root or PROJECT_ROOT
    candidates = []
    if os.environ.get("SLIDEMASTER_LATEX"):
        candidates.append(Path(os.environ["SLIDEMASTER_LATEX"]))
    candidates += [root.parent / "latex", root.parent / "SlideMage" / "latex"]
    return [d for d in candidates if (d / "Slidemaster_preamble_base.tex").is_file()]


def preamble_file(template: str, root: Path | None = None) -> Path:
    """The template's preamble file, Slidemaster_preamble_<key>.tex: the
    project's own (institution layers live in the project root), else the
    framework's (the SlideMage template, since v5.9.0). The project-root path
    when neither exists."""
    root = root or PROJECT_ROOT
    name = f"Slidemaster_preamble_{template}.tex"
    for folder in (root, *framework_dirs(root)):
        if (folder / name).is_file():
            return folder / name
    return root / name


def available_templates(root: Path | None = None) -> list[str]:
    """The TEMPLATES keys whose preamble file a deck of the project can find
    (project root or framework), in TEMPLATES order."""
    return [key for key in TEMPLATES if preamble_file(key, root).is_file()]


def render_template(root: Path | None = None) -> str:
    """The template single-slide renders use (see RENDER_TEMPLATE_SETTING_KEY)."""
    from . import app_settings  # app settings live in the project too

    available = available_templates(root)
    for key in (app_settings.get(RENDER_TEMPLATE_SETTING_KEY),
                OUT_OF_THE_BOX_RENDER_TEMPLATE, DEFAULT_TEMPLATE):
        if key in available:
            return key
    return available[0] if available else DEFAULT_TEMPLATE


# Full HD, requested directly rather than picked via a DPI value: this
# project's slides are all exactly 16:9 (aspectratio=169), so 1920x1080
# fits with no letterboxing, but a fixed DPI doesn't hit that pixel size
# exactly (150dpi measured at 945x532; the DPI that gets *closest* to
# 1920x1080 still lands a couple of pixels off after rounding). Computing a
# separate x/y zoom factor from each page's own point size instead --
# zoom = target_px / page_size_pt -- lands on exactly the target every
# time, regardless of tiny page-size variation between templates.
FULL_SIZE = (1920, 1080)
# Rendered directly from the PDF page at this size, not shrunk from the
# 1920x1080 bitmap: re-rasterizing vector content at the target resolution
# is crisper than downsampling an already-rasterized image, and it's what
# actually fixed the hover tooltip looking soft (it used to ask Qt's
# rich-text engine to shrink the full-size image 4x at display time,
# which does not use the same quality scaling QPixmap.scaled() does).
#
# 304x171 (2026-08-15, up from 240x135, ~26.7% wider -- the closest exact
# 16:9 pair to a plain 25% width increase, i.e. 300x168.75, which isn't an
# integer pixel size). Kept on an exact 16:9 multiple (16x19, 9x19) rather
# than rounding 168.75 to 169, same reasoning as FULL_SIZE above: the
# per-axis zoom (zoom = target_px / page_size_pt) is only distortion-free
# when the target's own aspect ratio exactly matches the page's (this
# project's slides are all aspectratio=169) -- a 300x169 target would
# apply very slightly different x/y zoom factors and stretch the image by
# a fraction of a percent, avoidable by staying on an exact 16:9 pair.
THUMB_SIZE = (304, 171)


def _slide_id_of(page: "fitz.Page") -> str | None:
    match = _SLIDE_ID_RE.search(page.get_text())
    return match.group(1) if match else None


def _save_page(page: "fitz.Page", slide_id: str, template: str,
               sizes: tuple[tuple[int, int], ...]) -> None:
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    for width, height in sizes:
        zoom_x = width / page.rect.width
        zoom_y = height / page.rect.height
        pixmap = page.get_pixmap(matrix=fitz.Matrix(zoom_x, zoom_y))
        pixmap.save(str(snapshot_path(slide_id, template, (width, height))))


def capture_single_slide(pdf_path: Path, slide_id: str, template: str,
                         sizes: tuple[tuple[int, int], ...] = (FULL_SIZE, THUMB_SIZE),
                         ) -> bool:
    """A single-slide preview PDF (slide_preview.py) is already just that
    one slide's own build steps -- the last page is its final reveal
    directly, no footer-scanning needed. True if a snapshot was written."""
    try:
        doc = fitz.open(pdf_path)
    except Exception:
        return False
    try:
        if doc.page_count == 0:
            return False
        _save_page(doc[doc.page_count - 1], slide_id, template, sizes)
        return True
    finally:
        doc.close()


def capture_deck(pdf_path: Path, template: str,
                 sizes: tuple[tuple[int, int], ...] = (FULL_SIZE, THUMB_SIZE),
                 ) -> int:
    """Scan a fully compiled deck PDF once; refresh every slide id it
    contains, taking the last page of each slide's contiguous run of pages
    (its final build step). One pass regardless of how many slides the
    deck has, rather than a separate render per slide. Returns how many
    slide ids were written (each written at every size in `sizes`).
    """
    try:
        doc = fitz.open(pdf_path)
    except Exception:
        return 0
    try:
        written = 0
        current_id: str | None = None
        current_page: "fitz.Page | None" = None
        for page in doc:
            slide_id = _slide_id_of(page)
            if slide_id is None:
                continue
            if slide_id != current_id:
                if current_id is not None:
                    _save_page(current_page, current_id, template, sizes)
                    written += 1
                current_id, current_page = slide_id, page
            else:
                current_page = page
        if current_id is not None:
            _save_page(current_page, current_id, template, sizes)
            written += 1
        return written
    finally:
        doc.close()


def _own_language_for_bare_id(bare_id_: str) -> str | None:
    """Resolves a bare id to its current on-disk id-slug and returns that
    slide's own language segment (EN/DE/mult, slide_language.own_language)
    -- None for a legacy, not-yet-migrated slide. Used to key the preview
    cache the same way Slidemaster_preamble_base.tex's own
    \\setSlideLanguageFromSlug derives language at compile time: from the
    filename alone, not from anything in the compiled PDF (a slide's
    *own* language never depends on which deck/template compiled it --
    only an "mult" slide's actually-*rendered* language would, and this
    cache deliberately doesn't split on that, see snapshot_path())."""
    id_slug = slide_language.current_id_slug_for_bare_id(bare_id_)
    if id_slug is None:
        return None
    return slide_language.own_language(id_slug)


def snapshot_path(slide_id: str, template: str = DEFAULT_TEMPLATE,
                  size: tuple[int, int] = FULL_SIZE, id_slug: str | None = None) -> Path:
    """Filename gains a <Lang> segment (2026-08-24, right after the bare
    id, matching the id-slug's own segment order) when `slide_id` resolves
    to a migrated slide -- omitted entirely for a legacy slide, so the
    already-cached files for the other ~665 slides never need
    mass-regenerating on rollout day. Resolved internally from disk
    (slide_language.current_id_slug_for_bare_id) rather than taken as a
    parameter, so every existing caller (slide_list.py,
    qt_slide_preview_popup.py, ...) gets the right cache key with no
    call-site changes needed.

    For an "mult" (multilingual) slide, the segment is the literal string
    "mult" -- a single shared thumbnail regardless of which language a
    deck last rendered it under, a deliberate simplification (not a full
    per-actually-rendered-language cache dimension) documented in
    LANGUAGE_NOTES.md/README.md: "mult" slides are meant to be light,
    mostly-visual content where a stale-language thumbnail is a minor
    cosmetic gap, already covered by this cache's own "best-effort, never
    guaranteed-fresh" disclaimer above."""
    safe_id = re.sub(r"[^A-Za-z0-9_-]", "_", slide_id)
    width, height = size
    # `id_slug` (a deck call's own) saves looking the slide up on disk: a
    # whole slide list asks for hundreds of these at once.
    language = (slide_language.own_language(id_slug) if id_slug
                else _own_language_for_bare_id(slide_id))
    lang_segment = f"-{language}" if language else ""
    return SNAPSHOT_DIR / f"{safe_id}{lang_segment}-{_template_name(template)}-{width}-{height}.png"


def is_fresh(slide_id: str, slide_path: Path, template: str = DEFAULT_TEMPLATE,
            size: tuple[int, int] = FULL_SIZE) -> bool:
    """Whether the cached snapshot is at least as new as the slide's own
    source file -- an mtime comparison, not a content hash: this is a
    best-effort "click to refresh" signal for a future preview UI, not a
    correctness guarantee, so it doesn't need to be hash-exact."""
    png = snapshot_path(slide_id, template, size)
    if not png.is_file():
        return False
    try:
        return png.stat().st_mtime >= slide_path.stat().st_mtime
    except OSError:
        return False


def bare_id(id_slug: str) -> str:
    """The short id a snapshot is keyed under, from a full `id_slug`
    ("22s-More-Exotic-Bonds", the `\\slide{}`/`\\slideversion{}` macro
    argument -- also a slide file's stem minus its `-current`/`-vX-Y-Z`
    suffix). \\setSlideID (Slidemaster_preamble_base.tex) takes everything
    up to the first "-" as \\slideID, which is what actually lands in a
    compiled page's footer and therefore what capture_deck()/
    capture_single_slide() key every snapshot under -- callers with only
    the full id_slug (deck/slide-editor rows, which need it whole to
    \\input{} the right file) need this to look one up.
    """
    return id_slug.partition("-")[0]
