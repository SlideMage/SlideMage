"""Render a `\\tikzillustration{ID}` to a cached PNG for the vision-model
drafting pipeline (ALT_TEXT_NOTES.md's tikz-illustration extension of the
alt-text system -- see alt_blocks.py/alt_images.py for the rest of it).

There is no media/ file behind one of these at all, so unlike
media_render.py's own .pdf rendering (which just rasterizes an existing
file), this compiles the illustration's own *current* tikz source fresh
into a tiny standalone one-slide PDF first -- reusing slide_preview.py's
own wrapper-compile machinery (GENERIC_PREAMBLE and all), so the drawing
renders with the same colors/tikz libraries a real slide would give it --
then rasterizes and auto-crops that down to just the drawing itself.

Cached by (illustration id, a hash of its own tikz source) rather than by
mtime the way media_render.py's .pdf cache is: a tikz illustration has no
file whose mtime would mean anything. alt_images.tikz_source_hash() of the
*current* body -- always freshly re-read from the slide file via
alt_blocks.find_tikz_illustration(), never trusted stale -- plays the role
a real image's own bytes play for content_hash(): the cache key itself is
the content fingerprint, so a stale cache is structurally impossible
rather than something to separately check for.
"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Callable, Optional

import pymupdf as fitz
from PIL import Image, ImageChops

from . import alt_blocks, alt_images
from .deck_scan import PROJECT_ROOT
from .slide_preview import _compile_and_extract, default_preamble

# Gitignored, same regeneratable-cache reasoning as slide_previews/ and
# pdf_render_cache/ (media_render.py) -- nothing here is ever authored, it
# is entirely derived from a slide's own current tikz source. Moved under
# previews/ 2026-09-18, then .previews/ the same day (was a project-root
# folder before that; dot-prefixed since nothing here is ever something
# the user needs to interact with).
RENDER_DIR = PROJECT_ROOT / ".previews" / "tikz_illustration_previews"

# Same reasoning as media_render.py's own _ZOOM: enough detail for a vision
# model to read fine text/labels inside the diagram, without an oversized
# file for what is usually a small figure.
_ZOOM = 3.0

# White-background padding (rendered pixels, at _ZOOM) kept around the
# auto-detected content bounding box -- enough that a thin stroke or a
# label's own descender never looks clipped, small enough not to
# reintroduce a sea of blank margin around a small diagram.
_CROP_PADDING = 24

LogCallback = Callable[[str], None]


def _cache_path(illustration_id: str, source_hash: str) -> Path:
    safe_id = "".join(c if c.isalnum() or c in "-_" else "_" for c in illustration_id)
    return RENDER_DIR / f"{safe_id}-{source_hash}.png"


def _render_and_crop(pdf_path: Path, png_path: Path) -> None:
    """Rasterize `pdf_path`'s one page and crop it to its own non-white
    content, saving the result to `png_path`.

    Auto-crop rather than a tikz-side `standalone`/`preview`-package crop
    (this project has neither as a dependency, and adding one just for
    this would mean a second way to compile a tikz picture, alongside the
    one already proven for every real slide): the illustration is
    compiled as an ordinary in-flow beamer frame, then whatever isn't the
    solid white page background is treated as the drawing. Good enough for
    every real slide's own white canvas; a slide with a non-white
    background would need a different approach, but none in this project
    has one.
    """
    doc = fitz.open(pdf_path)
    try:
        page = doc[0]
        pixmap = page.get_pixmap(matrix=fitz.Matrix(_ZOOM, _ZOOM))
    finally:
        doc.close()

    # No alpha requested above, so this is a plain 3-bytes-per-pixel RGB
    # buffer -- exactly what Image.frombytes("RGB", ...) expects.
    image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
    background = Image.new("RGB", image.size, (255, 255, 255))
    bbox = ImageChops.difference(image, background).getbbox()
    if bbox is not None:
        x0, y0, x1, y1 = bbox
        x0 = max(0, x0 - _CROP_PADDING)
        y0 = max(0, y0 - _CROP_PADDING)
        x1 = min(image.width, x1 + _CROP_PADDING)
        y1 = min(image.height, y1 + _CROP_PADDING)
        image = image.crop((x0, y0, x1, y1))
    # else: a blank page (an empty or fully-decorative-looking picture) --
    # save the whole page rather than raising, so a genuinely empty
    # illustration still produces *something* to look at instead of a
    # drafting failure with a confusing cause.

    RENDER_DIR.mkdir(parents=True, exist_ok=True)
    image.save(png_path)


def _slide_preamble_text(slide_path: Path) -> str:
    """Everything in `slide_path`'s own file before its frame-family macro
    opens -- \\newcommand/\\definecolor/\\usetikzlibrary-style local helpers
    an illustration's own options or body can legitimately reference, the
    same way a real deck compile already sees them (a slide file is
    \\input{}'d straight into the deck body, so a bare \\definecolor{} or
    \\newcommand{} sitting above its own frame already runs post-
    \\begin{document} there too -- reproducing that here is not a new
    relaxation of scope, just matching what already happens).

    Found directly necessary (2026-09-14) against two real illustrations
    that compiled fine embedded in their real slide but failed standalone:
    eey-EN-Beliefs-about-Beta-Design's \\definecolor{mubGray}{...} and
    ebq-EN-Dissecting-the-CAPM-SML's \\newcommand{\\ebqDuringAsAfter}{...},
    both declared above the frame, both undefined the moment only the
    illustration's own [options]/body were extracted in isolation.

    Copied verbatim -- same "copy everything before the interesting part"
    idiom compiler.py's own per-chapter wrapper already uses for a deck's
    preamble -- rather than trying to pick out only the "needed" lines,
    which would mean re-implementing a dependency scanner for arbitrary
    LaTeX. No frame in the file at all (shouldn't happen for anything
    tikz_render.py is ever asked to render, since find_tikz_illustration()
    only ever returns a match found *inside* one) returns the whole file,
    which is safe but wasteful rather than actively wrong.
    """
    text = slide_path.read_text(encoding="utf-8")
    match = alt_blocks.FRAME_OPEN_RE.search(text)
    return text if match is None else text[: match.start()]


def _wrapper_text(illustration_id: str, options: str, body: str, slide_preamble: str) -> str:
    # `options` (e.g. "[box/.style={...}]", or "" for none) must be
    # reproduced verbatim -- dropping it silently degrades a *built-in*
    # tikz hook set there (every node/.style={...} just renders with the
    # default font instead) but hard-fails the moment the body references a
    # *custom* style name the options themselves defined (\node[box, ...]
    # after box/.style={...}), since that name is then never declared at
    # all. Found directly against five real illustrations before this fix
    # -- see alt_blocks.TIKZILLUSTRATION_RE's own comment.
    #
    # slide_preamble (see _slide_preamble_text() above) is placed right
    # after \begin{document} (the last line of GENERIC_PREAMBLE), before
    # the throwaway frame -- \newcommand/\definecolor/\usetikzlibrary all
    # work equally well there as in a real preamble.
    #
    # \pagewidth/\pageheight (LuaTeX-native primitives -- \pdfpagewidth/
    # \pdfpageheight, the pdfTeX-era names, are undefined under LuaHBTeX
    # and raise "Undefined control sequence") enlarge this one throwaway
    # document's own page well past a real slide's aspectratio=169 canvas
    # (128mm x 72mm) before the frame opens. Needed found directly
    # (2026-09-14): a slide that scales its own tikzillustration down to
    # fit via an *external* \resizebox{}{}{...} wrapper (outside the
    # environment itself, so never part of the extracted body) renders at
    # full native size here instead -- on a real slide's own small canvas
    # that clips silently, well before _render_and_crop()'s own bounding-box
    # crop ever gets a chance to see the missing part. 60cm is generous
    # for anything this project's own slides draw; _render_and_crop()
    # already trims the resulting acres of white margin back down to the
    # drawing's own content afterward, so an oversized canvas costs nothing
    # in the final PNG.
    #
    # \hoffset/\voffset (plain-TeX primitives, not LuaTeX-specific -- they
    # shift *where on the page* the shipped-out content lands, relative to
    # the usual 1-inch-from-top-left reference point) are needed alongside
    # \pagewidth/\pageheight, not made redundant by them: enlarging the
    # page only adds room to the *right*/*bottom* of the frame's own small
    # (~128mm x 72mm) content block, which \shipout still plants flush at
    # the page's true top-left corner by default -- zero margin on the
    # *left*/*top* regardless of how big \pagewidth/\pageheight are. Found
    # directly (2026-09-11) against a real illustration (ukm-tikz): a
    # `\node[overlay, anchor=north, align=center] at (\linexcm,-1.3)
    # {Age of universe};` centered within a hair's width of x=0 (so roughly
    # half its own text width bleeds into negative-x, deliberately excluded
    # from the tikzpicture's own bounding box by `overlay` the same way
    # ys3's own \resizebox overflow was) rendered fine on a real slide,
    # where that bleed lands inside the frame's own normal left margin, but
    # got clipped hard at the physical page edge here even after 60cm's own
    # \pagewidth fix -- the enlarged page never moved the frame's own
    # content away from that true corner in the first place. 20cm here (both
    # axes, well clear of the frame's own small size in either direction)
    # gives equal breathing room on *every* side an `overlay` node could
    # bleed toward, not just the right/bottom \pagewidth/\pageheight already
    # covered; \pagewidth/\pageheight still needed on top of this even so,
    # for genuinely oversized native content (ys3's own \resizebox case)
    # that's larger than any reasonable fixed margin would absorb.
    return (
        f"{default_preamble()}"
        f"\\pagewidth=60cm\n"
        f"\\pageheight=60cm\n"
        f"\\hoffset=20cm\n"
        f"\\voffset=20cm\n"
        f"{slide_preamble}"
        f"\\begin{{frame}}[plain]\n"
        f"\\begin{{tikzillustration}}{options}{{{illustration_id}}}\n"
        f"{body}\n"
        f"\\end{{tikzillustration}}\n"
        f"\\end{{frame}}\n"
        f"\\end{{document}}\n"
    )


def ensure_rendered(reference: str, log: Optional[LogCallback] = None) -> Path:
    """The cached PNG of `reference`'s (a "tikz:ID" key, alt_blocks.TIKZ_PREFIX)
    current tikz body, rendering and cropping it fresh first if not already
    cached for its exact current source. Raises RuntimeError -- for the
    illustration not being found in any slide any more, or for a genuine
    compile failure -- the same contract media_render.ensure_rendered()
    already has, so callers already written for that (alt_draft.py's
    _resolve_describable and friends) can treat both the same way.
    """
    log = log or (lambda line: None)
    if not reference.startswith(alt_blocks.TIKZ_PREFIX):
        raise RuntimeError(f"not a tikz reference: {reference}")
    illustration_id = reference[len(alt_blocks.TIKZ_PREFIX):]

    found = alt_blocks.find_tikz_illustration(illustration_id)
    if found is None:
        raise RuntimeError(
            f"tikz illustration '{illustration_id}' not found in any slide "
            f"-- it may have been renamed or removed"
        )
    slide_path, options, body = found
    slide_preamble = _slide_preamble_text(slide_path)

    # options and slide_preamble are both part of the hash too, not just
    # body -- editing only a style definition (box/.style={fill=red} ->
    # fill=blue) or only a \definecolor{} above the frame, body itself
    # untouched, must still invalidate the cache. A harmless side effect:
    # an unrelated edit elsewhere in the slide's own pre-frame text (a
    # version-note comment, say) also invalidates it -- an unnecessary
    # re-render, never a wrong cached result, so left as-is rather than
    # trying to hash only the "relevant" lines.
    source_hash = alt_images.tikz_source_hash(options + slide_preamble + body)
    png_path = _cache_path(illustration_id, source_hash)
    if png_path.is_file():
        return png_path

    log(f"==== Rendering tikz illustration {illustration_id} "
       f"(from {slide_path.name}) ====")
    wrapper_text = _wrapper_text(illustration_id, options, body, slide_preamble)
    pdf_path = _compile_and_extract(wrapper_text, f"tikz-{illustration_id}", log)
    try:
        _render_and_crop(pdf_path, png_path)
    finally:
        # _compile_and_extract() leaves the PDF in its own fresh temp
        # directory (slide_preview.py's convention, for a render meant to
        # stay open in a viewer) -- nothing here keeps the PDF itself, only
        # the PNG derived from it, so the temp directory is cleaned up
        # immediately rather than accumulating one per illustration drafted.
        shutil.rmtree(pdf_path.parent, ignore_errors=True)

    log(f"==== PASS: tikz illustration {illustration_id} -> {png_path} ====")
    return png_path
