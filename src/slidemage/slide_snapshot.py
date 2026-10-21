# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
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
guaranteed-fresh source of truth.

Requires PyMuPDF (`fitz`) -- the one addition beyond this project's
previous "PySide6 only" dependency policy (requirements.txt). Justified by
precedent: `decks/render/compare_render.py`'s own page-identification
approach (every compiled page's footer carries "slide id: XXX", read via
`page.get_text()`) is reused here almost verbatim, and that tool already
proved PyMuPDF works cleanly for this project's PDFs.

**Template- and resolution-specific since 2026-08-15.** A slide can be
compiled under any of this project's institution templates (see
TEMPLATES below), and looks meaningfully different
under each (different colors/logo). A single shared cache keyed only by
slide id would show whichever institution happened to compile it last,
regardless of which deck's preview you were actually looking at -- wrong
often enough to be worse than no cache. Every capture/lookup is keyed by
(template, bare id, pixel size) instead, filename
`<Template>-<bare id>-<width>-<height>.png`, e.g.
`<Template>-22s-1920-1080.png`. Lookups are strict: no cross-template
fallback, so a deck never shows another template's cached image by
accident -- it just shows "not captured yet".

**Filename is `<bare id>-<Template>-<width>-<height>.png`** (bare id
first, e.g. `22s-<Template>-1920-1080.png`), not the reverse -- changed
2026-08-17 (direct instruction: "shift the three-letter slug to the front
of the filename to facilitate searching") from the original
`<Template>-<bare id>-...` order this module used through 2026-08-16. A
bare id never itself contains "-" (`\\setSlideID` takes everything up to
the *first* one), so leading with it also makes every filename in this
directory sort and glob-match by slide first, template second -- e.g.
`22s-*.png` finds both institutions' renders of one slide, which the old
order couldn't do without a wildcard *before* the id too.

**Gains an optional `<Lang>` segment right after the bare id (2026-08-24)**
for a slide whose own id-slug carries a language
segment (`EN`/`DE`/`mult` -- see slide_language.py): `22s-DE-<Template>-
1920-1080.png`. Resolved from disk inside snapshot_path() itself, not
passed in by any caller, so this needed no changes anywhere else in the
app. A legacy, not-yet-migrated slide's filename is completely unchanged
(no segment at all), so the ~665 already-cached files never needed
mass-regenerating when this landed.
"""
from __future__ import annotations

import os
import re
import hashlib
import threading
from collections import OrderedDict
from pathlib import Path

# `import fitz` still works but is deprecated in current PyMuPDF releases
# ("Use `import pymupdf` instead") -- aliased so the rest of this module
# reads the same either way.
import pymupdf as fitz

from . import project, slide_language
from .preview_cache import THUMBNAIL_MAX
from .preview_metrics import measure


# PDF content, dimensions -> PNG. Paths alone are unsafe when a job is rebuilt.
# Bounded by bytes as well as entries; no permanent extra artifacts on disk.
_PNG_CACHE: OrderedDict = OrderedDict()
_PNG_CACHE_BYTES = 32 * 1024 * 1024
_PNG_LOCK = threading.RLock()

# Every compiled frame carries this footer element unconditionally (theme
# footer template, Slidemaster_preamble_base.tex) -- not something special
# to test builds. `\S+` stops at the space before a possible
# "| omitted from student deck" suffix, so the bare id is always what's
# captured regardless of that flag.
SLIDE_ID_RE = re.compile(r"slide id:\s*(\S+)")

# Every institution template is a one-line \input{} swap on top of an
# otherwise-shared preamble, so detecting which one a deck uses is one regex
# against its own preamble text, not a whole-file diff. A template is any
# Slidemaster_preamble_<key>.tex the project (or the framework next to it)
# holds; the app knows none by name except its own, "slidemage", the generic
# template shipped in latex/. It is also the default when detection finds
# nothing (a deck with a preamble this regex doesn't recognize at all).
TEMPLATE_PREFIX = "Slidemaster_preamble_"
TEMPLATE_RE = re.compile(r"\\input\{Slidemaster_preamble_([A-Za-z0-9_-]+)\}")
DEFAULT_TEMPLATE = "slidemage"
_NOT_TEMPLATES = ("base",)           # the shared layer every template inputs, never a deck's choice
_LABEL_RE = re.compile(r"^%+\s*SlideMage template name:\s*(.+?)\s*$", re.MULTILINE)


def template_name(key: str) -> str:
    """The name a template has in cached preview file names: "my-template" -> "MyTemplate" (each hyphen-separated part
    capitalised), the app's own "slidemage" -> "SlideMage"."""
    return "SlideMage" if key == DEFAULT_TEMPLATE else "".join(part.capitalize() for part in key.split("-"))


class _TemplateNames:
    """TEMPLATES[key] / TEMPLATES.get(key, default): the file-name form of any template key."""

    def __getitem__(self, key: str) -> str:
        return template_name(key)

    def get(self, key: str, default: str = "") -> str:
        return template_name(key) if key else default


TEMPLATES = _TemplateNames()


def template_label(key: str, root: Path | None = None) -> str:
    """How the dialogs name a template: the `% SlideMage template name: ...` line in the first lines of its preamble
    file when it has one, else its key read as words ("my-template" -> "My Template")."""
    if root is not None:
        try:
            head = "\n".join(preamble_file(key, root).read_text(encoding="utf-8", errors="replace").splitlines()[:30])
        except OSError:
            head = ""
        found = _LABEL_RE.search(head)
        if found:
            return found.group(1)
    return "SlideMage" if key == DEFAULT_TEMPLATE else " ".join(part.capitalize() for part in key.split("-"))


def detect_template(preamble_text: str) -> str:
    """The template key a deck's own preamble selects, defaulting to DEFAULT_TEMPLATE when the pattern isn't found."""
    for match in TEMPLATE_RE.finditer(preamble_text):
        if match.group(1) not in _NOT_TEMPLATES:
            return match.group(1)
    return DEFAULT_TEMPLATE


def _template_name(template: str) -> str:
    return template_name(template)


# The template a slide is rendered in when no deck is involved -- the slide
# editor's Render to PDF and Preview, tikz illustration renders (2026-10-03,
# direct instruction: chosen in Settings -> General, out of the box the
# generic SlideMage template). Only a template whose preamble file a deck of
# this project can find is offered; otherwise the choice falls back to the
# SlideMage template, then the default one, then whichever template there is.
RENDER_TEMPLATE_SETTING_KEY = "default_template"
OUT_OF_THE_BOX_RENDER_TEMPLATE = "slidemage"


def framework_dirs(root: Path) -> list[Path]:
    """The LaTeX framework folders a project's decks search (its .latexmkrc
    puts one on TEXINPUTS): $SLIDEMASTER_LATEX, else ../latex (a project
    next to the framework, like example/) or ../SlideMage/latex (a project
    next to a SlideMage checkout). Only folders holding
    Slidemaster_preamble_base.tex count."""
    candidates = []
    if os.environ.get("SLIDEMASTER_LATEX"):
        candidates.append(Path(os.environ["SLIDEMASTER_LATEX"]))
    candidates += [root.parent / "latex", root.parent / "SlideMage" / "latex"]
    return [d for d in candidates if (d / "Slidemaster_preamble_base.tex").is_file()]


def preamble_file(template: str, root: Path) -> Path:
    """The template's preamble file, Slidemaster_preamble_<key>.tex: the
    project's own (institution layers live in the project root), else the
    framework's (the SlideMage template, since v5.9.0). The project-root path
    when neither exists."""
    name = f"Slidemaster_preamble_{template}.tex"
    for folder in (root, *framework_dirs(root)):
        if (folder / name).is_file():
            return folder / name
    return root / name


def available_templates(root: Path) -> list[str]:
    """The keys of the templates whose preamble file a deck of the project can find (project root or framework):
    the app's own first, then the others alphabetically."""
    keys = {file.stem[len(TEMPLATE_PREFIX):] for folder in (root, *framework_dirs(root))
            for file in folder.glob(f"{TEMPLATE_PREFIX}*.tex")}
    keys -= set(_NOT_TEMPLATES)
    return sorted(keys, key=lambda key: (key != DEFAULT_TEMPLATE, key))


def render_template(ctx: project.ProjectContext) -> str:
    """The template single-slide renders use (see RENDER_TEMPLATE_SETTING_KEY)."""
    from . import app_settings  # app settings live in the project too

    available = available_templates(ctx.root)
    for key in (app_settings.get(ctx, RENDER_TEMPLATE_SETTING_KEY),
                OUT_OF_THE_BOX_RENDER_TEMPLATE, DEFAULT_TEMPLATE):
        if key in available:
            return key
    return available[0] if available else DEFAULT_TEMPLATE


def set_render_template(ctx: project.ProjectContext, key: str) -> None:
    """Choose the template single-slide renders use (a template key)."""
    from . import app_settings

    if key not in available_templates(ctx.root):
        raise ValueError(f"'{key}' is not a template.")
    app_settings.set(ctx, RENDER_TEMPLATE_SETTING_KEY, key)


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


def slide_id_of(page: "fitz.Page") -> str | None:
    match = SLIDE_ID_RE.search(page.get_text())
    return match.group(1) if match else None


def _save_page(ctx: project.ProjectContext, page: "fitz.Page", slide_id: str, template: str,
               sizes: tuple[tuple[int, int], ...]) -> None:
    ctx.slide_previews_dir.mkdir(parents=True, exist_ok=True)
    for width, height in sizes:
        zoom_x = width / page.rect.width
        zoom_y = height / page.rect.height
        pixmap = page.get_pixmap(matrix=fitz.Matrix(zoom_x, zoom_y))
        pixmap.save(str(snapshot_path(ctx, slide_id, template, (width, height))))


@measure('png')
def _preview_pngs(pdf_path: Path, sizes) -> tuple[bytes, ...]:
    data = pdf_path.read_bytes()
    digest = hashlib.sha256(data).digest()
    with _PNG_LOCK:
        keys = [(digest, size) for size in sizes]
        missing = [key for key in keys if key not in _PNG_CACHE]
        if missing:
            from .preview_raster_client import render
            # Only bytes cross the boundary. MuPDF is unsafe in Python threads,
            # even with a mutex around calls (another thread can run its GC).
            images = render(data, tuple(key[1] for key in missing), FULL_SIZE)
            if not images:
                return ()
            _PNG_CACHE.update(zip(missing, images))
        result = tuple(_PNG_CACHE[key] for key in keys)
        for key in keys:
            _PNG_CACHE.move_to_end(key)
        while len(_PNG_CACHE) > 16 or sum(map(len, _PNG_CACHE.values())) > _PNG_CACHE_BYTES:
            _PNG_CACHE.popitem(last=False)
        return result


@measure('raster_sequence')
def preview_sequence(pdf_path: Path):
    """Complete reveal evidence for the verified cache; snapshots stay final-page only."""
    from .preview_raster_client import render_sequence

    return render_sequence(pdf_path.read_bytes())


def prepare_preview(pdf_path: Path, snapshots: bool = False):
    """Prepare the display and optional canonical PNGs without publishing them.

    The GUI accepts the request first, then writes its canonical snapshots.
    Full-slide display reuses the already rasterized full-size snapshot.
    """
    displays, images = prepare_preview_images(pdf_path, snapshots, (FULL_SIZE[0],))
    return displays[0], images


def prepare_preview_images(pdf_path: Path, snapshots: bool, widths):
    """Pane and tool display sizes in one raster subprocess, with optional snapshots.

    The display PNGs come back in `widths` order, followed by one more: the cache's list thumbnail
    (preview_cache.THUMBNAIL_MAX, aspect kept), so the cache need not decode and re-encode a display PNG for it.
    """
    displays = tuple((width, None) for width in widths) + ((*THUMBNAIL_MAX, 'fit'),)
    sizes = (FULL_SIZE, THUMB_SIZE) + displays if snapshots else displays
    images = _preview_pngs(pdf_path, sizes)
    if not images:
        raise RuntimeError('Preview PDF has no pages')
    return images[-len(displays):], tuple(zip(sizes[:2], images[:2])) if snapshots else ()


@measure('snapshot_write')
def publish_preview(ctx: project.ProjectContext, images, slide_id: str, template: str) -> None:
    ctx.slide_previews_dir.mkdir(parents=True, exist_ok=True)
    for size, data in images:
        # Refresh freshness even when a source edit leaves identical PDF pixels.
        path = snapshot_path(ctx, slide_id, template, size)
        if path.exists() and path.read_bytes() == data:
            path.touch()
        else:
            path.write_bytes(data)


def page_png(pdf_path: Path, width: int = FULL_SIZE[0]) -> bytes | None:
    """The last page of a single-slide preview PDF (its final build step) as
    PNG bytes `width` pixels wide, at the page's own aspect ratio (a cropped
    element preview is not 16:9). None if the PDF cannot be read."""
    try:
        images = _preview_pngs(pdf_path, ((width, None),))
        return images[0] if images else None
    except Exception:
        return None


def capture_single_slide(ctx: project.ProjectContext, pdf_path: Path, slide_id: str, template: str,
                         sizes: tuple[tuple[int, int], ...] = (FULL_SIZE, THUMB_SIZE),
                         ) -> bool:
    """A single-slide preview PDF (slide_preview.py) is already just that
    one slide's own build steps -- the last page is its final reveal
    directly, no footer-scanning needed. True if a snapshot was written."""
    try:
        images = _preview_pngs(pdf_path, sizes)
    except Exception:
        return False
    if not images:
        return False
    publish_preview(ctx, tuple(zip(sizes, images)), slide_id, template)
    return True


def slide_runs(slide_ids) -> list[tuple[str, list[int]]]:
    """The slides of a deck PDF from the slide id of each page (None: a page that names none, skipped): each
    run of consecutive pages with one id is a slide, with its page indexes -- the last is its final build step."""
    runs: list[tuple[str, list[int]]] = []
    for index, slide_id in enumerate(slide_ids):
        if slide_id is None:
            continue
        if runs and runs[-1][0] == slide_id:
            runs[-1][1].append(index)
        else:
            runs.append((slide_id, [index]))
    return runs


def capture_deck(ctx: project.ProjectContext, pdf_path: Path, template: str,
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
        runs = slide_runs([slide_id_of(page) for page in doc])
        for slide_id, pages in runs:
            _save_page(ctx, doc[pages[-1]], slide_id, template, sizes)
        return len(runs)
    finally:
        doc.close()


def _own_language_for_bare_id(ctx: project.ProjectContext, bare_id_: str) -> str | None:
    """Resolves a bare id to its current on-disk id-slug and returns that
    slide's own language segment (EN/DE/mult, slide_language.own_language)
    -- None for a legacy, not-yet-migrated slide. Used to key the preview
    cache the same way Slidemaster_preamble_base.tex's own
    \\setSlideLanguageFromSlug derives language at compile time: from the
    filename alone, not from anything in the compiled PDF (a slide's
    *own* language never depends on which deck/template compiled it --
    only an "mult" slide's actually-*rendered* language would, and this
    cache deliberately doesn't split on that, see snapshot_path())."""
    id_slug = slide_language.current_id_slug_for_bare_id(ctx, bare_id_)
    if id_slug is None:
        return None
    return slide_language.own_language(id_slug)


def snapshot_path(ctx: project.ProjectContext, slide_id: str, template: str = DEFAULT_TEMPLATE,
                  size: tuple[int, int] = FULL_SIZE, id_slug: str | None = None) -> Path:
    """Filename gains a <Lang> segment (2026-08-24, right after the bare
    id, matching the id-slug's own segment order) when `slide_id` resolves
    to a migrated slide -- omitted entirely for a legacy slide, so the
    already-cached files for the other ~665 slides never need
    mass-regenerating on rollout day. Resolved internally from disk
    (slide_language.current_id_slug_for_bare_id) rather than taken as a
    parameter, so every existing caller (slide_list.py,
    preview_target.py, ...) gets the right cache key with no
    call-site changes needed.

    For an "mult" (multilingual) slide, the segment is the literal string
    "mult" -- a single shared thumbnail regardless of which language a
    deck last rendered it under, a deliberate simplification (not a full
    per-actually-rendered-language cache dimension) documented in
    README.md: "mult" slides are meant to be light,
    mostly-visual content where a stale-language thumbnail is a minor
    cosmetic gap, already covered by this cache's own "best-effort, never
    guaranteed-fresh" disclaimer above."""
    safe_id = re.sub(r"[^A-Za-z0-9_-]", "_", slide_id)
    width, height = size
    # `id_slug` (a deck call's own) saves looking the slide up on disk: a
    # whole slide list asks for hundreds of these at once.
    language = (slide_language.own_language(id_slug) if id_slug
                else _own_language_for_bare_id(ctx, slide_id))
    lang_segment = f"-{language}" if language else ""
    return ctx.slide_previews_dir / f"{safe_id}{lang_segment}-{_template_name(template)}-{width}-{height}.png"


def is_fresh(ctx: project.ProjectContext, slide_id: str, slide_path: Path, template: str = DEFAULT_TEMPLATE,
            size: tuple[int, int] = FULL_SIZE) -> bool:
    """Whether the cached snapshot is at least as new as the slide's own
    source file -- an mtime comparison, not a content hash: this is a
    best-effort "click to refresh" signal for a future preview UI, not a
    correctness guarantee, so it doesn't need to be hash-exact."""
    png = snapshot_path(ctx, slide_id, template, size)
    if not png.is_file():
        return False
    try:
        return png.stat().st_mtime >= slide_path.stat().st_mtime
    except OSError:
        return False
