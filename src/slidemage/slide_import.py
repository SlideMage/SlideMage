# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Import a PowerPoint (.pptx) or OpenDocument Presentation (.odp) file as
new Slidemaster slides, with real, editable LaTeX text -- not a rendered
image of each source slide. Direct instruction, 2026-09-23.

Per-slide content is mapped onto the two existing layouts that fit it
best (see slide_content_to_tex() below): standardframe (title + nested
bullets, any embedded images placed after the text) for a slide with
real text content, or figureframe (title + one full image, the same
"Converted from ExampleSlides.pptx" convention slides/ZZP-EN-Figure-only
-current.tex already documents by hand) for a slide that turns out to be
image-only. A slide with neither text nor an image is skipped, not
turned into an empty frame.

Text extraction can never perfectly recover an arbitrary source deck's
own visual design (tables, multi-column layouts, diagrams, speaker notes,
custom fonts/positioning) -- this gets the *content* onto a slide as real
editable text, not a pixel-perfect recreation; expect to clean up the
result, same as any other text->LaTeX conversion.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .project import ProjectContext



# -- LaTeX escaping ---------------------------------------------------------

# Every character LaTeX gives special meaning to outside math mode.
# Order matters: backslash first (every other replacement below inserts
# one, which must not itself be re-escaped on a later pass), and this is
# a single combined regex substitution (not one .replace() per character)
# so none of the inserted backslashes are ever seen as new input to a
# later rule -- re.sub with a function callback runs each match exactly
# once, left to right, over the *original* string.
_LATEX_SPECIAL_RE = re.compile(r"[\\&%$#_{}~^]")
_LATEX_SPECIAL_MAP = {
    "\\": r"\textbackslash{}",
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}


def escape_latex(text: str) -> str:
    """Plain text -> safe-to-emit-verbatim LaTeX. Every character LaTeX
    treats specially outside math mode is escaped -- without this, source
    text containing any of them (e.g. "50% growth", "R&D", "a_b", a stray
    "#" in a URL) either breaks the compile outright or silently changes
    meaning (an unescaped "%" turns the rest of its line into a comment)."""
    return _LATEX_SPECIAL_RE.sub(lambda m: _LATEX_SPECIAL_MAP[m.group()], text)


# -- Extracted-content shape (format-independent) ---------------------------

@dataclass
class Bullet:
    text: str
    level: int = 0  # 0 = top level, matching Slidemaster's own itemize nesting


@dataclass
class TableCell:
    paragraphs: list[str]
    colspan: int = 1


@dataclass
class SlideContent:
    title: str = ""
    bullets: list[Bullet] = field(default_factory=list)
    # Each table is a list of rows; each row a list of cells.
    tables: list[list[list[TableCell]]] = field(default_factory=list)
    # Raw image bytes plus a suggested extension (".png"/".jpeg"/...), in
    # the slide's own document order -- media_filename() below turns one
    # into an actual on-disk name once we know this slide's own id_slug.
    images: list[tuple[bytes, str]] = field(default_factory=list)

    @property
    def has_text(self) -> bool:
        return bool(self.title.strip()) or bool(self.bullets) or bool(self.tables)

    @property
    def is_blank(self) -> bool:
        return not self.has_text and not self.images


# -- PowerPoint (.pptx) -------------------------------------------------

def extract_pptx(path: Path) -> list[SlideContent]:
    from pptx import Presentation
    from pptx.enum.shapes import MSO_SHAPE_TYPE

    prs = Presentation(str(path))
    slides: list[SlideContent] = []
    for slide in prs.slides:
        content = SlideContent()
        title_shape = slide.shapes.title
        # python-pptx wraps a shape freshly on every access/iteration (a
        # plain `shape is title_shape` never matches even for the actual
        # title shape, confirmed directly) -- shape_id is the one stable
        # identity two separate accesses of "the same shape" actually share.
        title_shape_id = title_shape.shape_id if title_shape is not None else None
        if title_shape is not None and title_shape.has_text_frame:
            content.title = title_shape.text_frame.text.strip()

        # Images tagged with their on-slide position, then sorted
        # top-to-bottom/left-to-right -- slide.shapes comes off in z-order
        # (draw order), not layout position, so a picture added early but
        # placed lower down would otherwise land before one added later
        # but placed higher up.
        positioned_images: list[tuple[tuple[int, int], tuple[bytes, str]]] = []
        for shape in slide.shapes:
            if shape.shape_id == title_shape_id:
                continue
            if shape.has_text_frame:
                for paragraph in shape.text_frame.paragraphs:
                    text = "".join(run.text for run in paragraph.runs).strip()
                    if text:
                        content.bullets.append(Bullet(text=text, level=paragraph.level))
            if shape.shape_type == MSO_SHAPE_TYPE.PICTURE:
                image = shape.image
                positioned_images.append(
                    ((shape.top or 0, shape.left or 0), (image.blob, f".{image.ext}"))
                )
        positioned_images.sort(key=lambda pair: pair[0])
        content.images = [img for _pos, img in positioned_images]
        slides.append(content)
    return slides


# -- OpenDocument Presentation (.odp) ---------------------------------------

def _odp_walk_text_box(node, level: int, bullets: list[Bullet], *, root: bool = False) -> None:
    """Appends one Bullet per direct text:p at the current level. A text:list
    directly inside the text box is the top-level list (level 0); lists
    nested inside a text:list-item add one level each time. This follows
    ODF's nested-element structure while matching pptx's flat paragraph
    level attribute."""
    from odf.namespaces import TEXTNS
    from odf.teletype import extractText

    # Raw (namespace, local-name) qname tuples, not odf.text.P/List/
    # ListItem's own factory functions -- those are plain functions with
    # no .qname of their own until called (P(...).qname would work, but
    # constructing a throwaway element on every single comparison just to
    # read a constant back off it is pointless indirection).
    p_qname, list_qname, item_qname = (TEXTNS, "p"), (TEXTNS, "list"), (TEXTNS, "list-item")

    for child in node.childNodes:
        if child.qname == p_qname:
            text = extractText(child).strip()
            if text:
                bullets.append(Bullet(text=text, level=level))
        elif child.qname == list_qname:
            for item in child.childNodes:
                if item.qname == item_qname:
                    # The first list inside the text box is level 0.
                    # Further lists nested inside list items add one level.
                    _odp_walk_text_box(item, level if root else level + 1, bullets)
        elif child.qname == item_qname:
            _odp_walk_text_box(child, level, bullets)


# Layout placeholders (slide number, footer, date) and the speaker-notes
# page, whose frames sit inside <presentation:notes> under the same page.
_ODP_SKIPPED_FRAME_CLASSES = {"page-number", "footer", "date-time", "header", "notes", "page"}


def _odp_table(table) -> list[list[TableCell]]:
    """Rows of cells for one <table:table>. A covered cell that belongs to
    the previous cell's column span is dropped; any other covered cell
    (the lower part of a row span) becomes an empty cell so the columns
    stay aligned."""
    from odf.namespaces import TABLENS
    from odf.table import TableRow
    from odf.teletype import extractText
    from odf.text import P

    cell_qname, covered_qname = (TABLENS, "table-cell"), (TABLENS, "covered-table-cell")
    rows: list[list[TableCell]] = []
    for row in table.getElementsByType(TableRow):
        cells: list[TableCell] = []
        pending_span = 0
        for child in row.childNodes:
            if child.qname == cell_qname:
                paragraphs = [extractText(p).strip() for p in child.getElementsByType(P)]
                colspan = int(child.getAttrNS(TABLENS, "number-columns-spanned") or 1)
                cells.append(TableCell([p for p in paragraphs if p], colspan))
                pending_span = colspan - 1
            elif child.qname == covered_qname:
                if pending_span:
                    pending_span -= 1
                else:
                    cells.append(TableCell([]))
        if cells:
            rows.append(cells)
    return rows


def extract_odp(path: Path) -> list[SlideContent]:
    from odf.draw import Frame, Image, Page, TextBox
    from odf.namespaces import PRESENTATIONNS
    from odf.opendocument import load
    from odf.table import Table

    doc = load(str(path))
    slides: list[SlideContent] = []
    for page in doc.presentation.getElementsByType(Page):
        content = SlideContent()
        positioned_images: list[tuple[tuple[str, str], tuple[bytes, str]]] = []
        # getElementsByType() is unqualified-recursive, but called once
        # per *page* here -- each page's own direct <draw:frame> children,
        # not frames belonging to some other page, since it's invoked on
        # `page`, not on the whole document.
        for frame in page.getElementsByType(Frame):
            frame_class = frame.getAttrNS(PRESENTATIONNS, "class")
            if frame_class in _ODP_SKIPPED_FRAME_CLASSES:
                continue
            for text_box in frame.getElementsByType(TextBox):
                bullets: list[Bullet] = []
                _odp_walk_text_box(text_box, 0, bullets, root=True)
                if frame_class == "title" and bullets:
                    content.title = " ".join(b.text for b in bullets)
                else:
                    content.bullets.extend(bullets)
            tables = [t for t in (_odp_table(t) for t in frame.getElementsByType(Table)) if t]
            if tables:
                # A table frame also carries LibreOffice's rendered
                # preview of the same table (Pictures/TablePreviewN.svm)
                # -- the table itself is the content, not that picture.
                content.tables.extend(tables)
                continue
            for image in frame.getElementsByType(Image):
                href = image.getAttribute("href")
                picture = doc.Pictures.get(href)
                if picture is None:
                    continue
                _flag, blob, mimetype = picture
                if blob.startswith(b"VCLMTF"):
                    # LibreOffice's own StarView Metafile (e.g. an OLE
                    # object's replacement image), often mislabeled
                    # image/png in the manifest. Nothing but LibreOffice
                    # itself can render it, and \includegraphics fails on
                    # it at PDF build time, so it can't be imported.
                    continue
                ext = "." + (mimetype.rsplit("/", 1)[-1] if mimetype else "png")
                position = (frame.getAttribute("y") or "", frame.getAttribute("x") or "")
                positioned_images.append((position, (blob, ext)))
        positioned_images.sort(key=lambda pair: pair[0])
        content.images = [img for _pos, img in positioned_images]
        slides.append(content)
    return slides


# -- LaTeX generation ---------------------------------------------------

_TAB = "\t"
_MAX_ITEMIZE_LEVEL = 3  # Slidemaster_preamble_base.tex supports four itemize levels.


def _bullets_to_itemize(bullets: list[Bullet]) -> str:
    """Render bullets as nested itemize environments.

    Missing source levels collapse to the next available depth. A stack of
    source-level ancestors keeps repeated bullets at a jumped level together
    as siblings. Nesting is capped at the four levels supported by the
    project's Beamer preamble.
    """
    lines: list[str] = []
    source_levels: list[tuple[int, int]] = []
    current_level = -1  # nothing open yet
    for bullet in bullets:
        source_level = max(0, bullet.level)
        while source_levels and source_levels[-1][0] > source_level:
            source_levels.pop()
        if source_levels and source_levels[-1][0] == source_level:
            level = source_levels[-1][1]
        else:
            parent_level = source_levels[-1][1] if source_levels else -1
            level = min(parent_level + 1, _MAX_ITEMIZE_LEVEL)
            source_levels.append((source_level, level))

        while current_level < level:
            current_level += 1
            lines.append(_TAB * (current_level + 1) + r"\begin{itemize}")
        while current_level > level:
            lines.append(_TAB * (current_level + 1) + r"\end{itemize}")
            current_level -= 1
        text = escape_latex(bullet.text)
        if text.startswith(("<", "[")):
            # Otherwise beamer reads it as \item's overlay spec / label.
            text = "{}" + text
        lines.append(_TAB * (current_level + 2) + r"\item " + text)
    while current_level >= 0:
        lines.append(_TAB * (current_level + 1) + r"\end{itemize}")
        current_level -= 1
    return "\n".join(lines)


# gothamtable's [gap=12pt] option writes the flush-edge column spec (zero
# \tabcolsep, @{} outer edges, this gap after each column -- the rule-bleed
# convention in Slidemaster_preamble_base.tex); a \multicolumn cell still
# spells its own spec out, so it needs the same gap by hand.
_TABLE_GAP = r"<{\hspace{12pt}}"


def _cell_to_tex(cell: TableCell) -> str:
    lines = [escape_latex(p) for p in cell.paragraphs]
    if len(lines) > 1:
        return r"\begin{tabular}[t]{@{}l@{}}" + r" \\ ".join(lines) + r"\end{tabular}"
    return lines[0] if lines else ""


def _table_block(rows: list[list[TableCell]]) -> str:
    """A gothamtable for one extracted table, shrunk (never enlarged) to
    fit the frame's width and 0.8\\textheight."""
    ncols = max(sum(cell.colspan for cell in row) for row in rows)
    lines = [
        r"\sbox0{%",
        r"\begin{gothamtable}[gap=12pt]{" + "l" * ncols + "}",
        _TAB + r"\toprule",
    ]
    for index, row in enumerate(rows):
        cells: list[str] = []
        column = 0
        for cell in row:
            text = _cell_to_tex(cell)
            if cell.colspan > 1:
                left = "@{}" if column == 0 else ""
                right = "@{}" if column + cell.colspan >= ncols else _TABLE_GAP
                text = f"\\multicolumn{{{cell.colspan}}}{{{left}l{right}}}{{{text}}}"
            cells.append(text)
            column += cell.colspan
        cells.extend([""] * (ncols - column))
        lines.append(_TAB + " & ".join(cells) + r" \\")
        if index == 0 and len(rows) > 1:
            lines.append(_TAB + r"\midrule")
    lines += [
        _TAB + r"\bottomrule",
        r"\end{gothamtable}}",
        r"\ifdim\wd0>\linewidth\sbox0{\resizebox{\linewidth}{!}{\usebox0}}\fi",
        r"\ifdim\dimexpr\ht0+\dp0\relax>0.8\textheight"
        r"\sbox0{\resizebox*{!}{0.8\textheight}{\usebox0}}\fi",
        r"\usebox0",
    ]
    block = [r"\begin{center}", *(_TAB + line for line in lines), r"\end{center}"]
    return "\n".join(_TAB + line for line in block)


def _images_block(image_paths: list[str], *, full_slide: bool) -> str:
    """`\\includegraphics` calls for `image_paths` (media/-relative,
    already written to disk by the caller) -- full_slide=True (an
    image-only slide, no text at all) sizes the first one the same
    height/textheight ratio slides/ZZP-EN-Figure-only-current.tex's own
    hand-converted "Converted from ExampleSlides.pptx" comment already
    established as this project's own convention; any further images on
    a slide that turned out to have no text at all get a shrinking share
    of the same height so multiple don't just overflow the frame stacked
    at full size. full_slide=False (images alongside real text) instead
    centers each at a fixed width fraction, stacked below the bullets."""
    if not image_paths:
        return ""
    if full_slide:
        height = 0.72 / len(image_paths)
        graphics = [
            f"\\includegraphics[height={height:.2f}\\textheight]{{{image_path}}}"
            for image_path in image_paths
        ]
    else:
        graphics = [
            f"\\includegraphics[width=0.6\\linewidth]{{{image_path}}}"
            for image_path in image_paths
        ]
    lines = [r"\begin{center}", *(_TAB + g for g in graphics), r"\end{center}"]
    return "\n".join(_TAB + line for line in lines)


def slide_content_to_tex(content: SlideContent, image_paths: list[str]) -> tuple[str, str]:
    """(macro used, slide body) for one imported slide -- `image_paths`
    are media/-relative paths already written to disk by the caller, in
    the same order as content.images, so this function only ever
    generates \\includegraphics references, never touches the filesystem
    itself.

    A slide with real text uses standardframe (nested itemize for its
    bullets, any images centered below); a slide with no text at all but
    at least one image uses figureframe instead (title + full image,
    the "Converted from ExampleSlides.pptx" convention
    slides/ZZP-EN-Figure-only-current.tex already documents by hand).
    Caller is responsible for skipping a genuinely blank slide (no text,
    no images) before ever calling this -- there is no sensible macro for
    that case, and creating an empty slide for it would just be clutter
    the next housekeeping pass has to notice and clean up."""
    title = escape_latex(content.title) or "Untitled"
    if content.has_text:
        blocks = [_bullets_to_itemize(content.bullets)] if content.bullets else []
        blocks += [_table_block(rows) for rows in content.tables]
        images = _images_block(image_paths, full_slide=False)
        if images:
            blocks.append(images)
        body = "\n\n".join(blocks)
        return "standardframe", f"\\begin{{standardframe}}{{{title}}}\n{body}\n\\end{{standardframe}}"

    images = _images_block(image_paths, full_slide=True)
    return "figureframe", f"\\begin{{figureframe}}{{{title}}}\n{images}\n\\end{{figureframe}}"


# -- Orchestration -------------------------------------------------------

# Same shape as slide_add.SLUG_RE (letters/digits,
# single hyphens between groups, no leading/trailing/doubled hyphen) --
# an id_slug built here has to satisfy every other part of the app that
# assumes a slide's slug looks like this (slide_rename.py's own parsing,
# in particular).
_SLUG_WORD_RE = re.compile(r"[A-Za-z0-9]+")


def slug_from_title(title: str, fallback: str) -> str:
    """A title like "Growth of R&D spend (50% YoY)" -> "Growth-of-R-D
    -spend-50-YoY" -- every run of letters/digits becomes one hyphen-
    joined word, everything else (punctuation, whitespace, the "&"/"%"
    themselves) is a separator, never emitted. `fallback` (e.g.
    "Imported-Slide-3") is used verbatim when the title has no
    letters/digits at all (blank title, or one that's pure punctuation)."""
    words = _SLUG_WORD_RE.findall(title)
    return "-".join(words) if words else fallback


@dataclass
class ImportedSlide:
    id_slug: str
    layout: str  # "standardframe" or "figureframe" -- the slide's own
    # environment, not the (always plain \slide{}) deck-call macro.
    title: str


@dataclass
class ImportSummary:
    imported: list[ImportedSlide] = field(default_factory=list)
    skipped_blank: int = 0


def media_filename(id_slug: str, index: int, ext: str) -> str:
    suffix = f"-{index + 1}" if index else ""
    return f"imported-{id_slug}{suffix}{ext}"


def import_presentation(ctx: ProjectContext, source_path: Path, deck, language: str, log=None) -> ImportSummary:
    """Extracts every slide from `source_path` (.pptx or .odp) and appends
    one new Slidemaster slide per non-blank source slide to the end of
    `deck` -- new slide files under slides/, their images (if any) under
    media/, a fresh \\slide{} call for each appended to `deck` in source
    order, and each new id registered in slide_ids.csv, same conventions
    slide_ids.create_slide_file()/append_slide_id() use for a slide
    created by hand.

    `log`, if given, is called once per slide actually imported (not for
    a skipped blank one) -- this can create many files in one call, and a
    caller driving a GUI wants to show progress, not just a final count.

    Raises ValueError for an unrecognized file extension, and whatever
    the underlying extractor itself raises for a corrupt/unreadable file
    (python-pptx's own PackageNotFoundError, odfpy's) -- neither is
    caught here, so a caller can show the real underlying error rather
    than a generic "import failed"."""
    from . import deck_editor, slide_ids, slide_language

    extractor = {".pptx": extract_pptx, ".odp": extract_odp}.get(source_path.suffix.lower())
    if extractor is None:
        raise ValueError(
            f"Unsupported file type: {source_path.suffix!r} (only .pptx and .odp are supported)"
        )
    contents = extractor(source_path)

    summary = ImportSummary()
    expected_text = deck.text
    insert_at, indent = deck_editor.append_position(deck)
    media_dir = ctx.media_dir

    for content in contents:
        if content.is_blank:
            summary.skipped_blank += 1
            continue

        slide_id = slide_ids.mint_slide_id(ctx)
        fallback_slug = f"Imported-Slide-{len(summary.imported) + summary.skipped_blank + 1}"
        slug = slug_from_title(content.title, fallback_slug)
        id_slug = f"{slide_id}-{language}-{slug}"

        image_rel_paths: list[str] = []
        media_dir.mkdir(parents=True, exist_ok=True)
        for index, (blob, ext) in enumerate(content.images):
            filename = media_filename(id_slug, index, ext)
            (media_dir / filename).write_bytes(blob)
            image_rel_paths.append(f"media/{filename}")

        # `layout` is which frame environment the slide's own new .tex
        # file uses (standardframe/figureframe) -- unrelated to which
        # \slide-family macro the deck calls it with below. Every
        # imported slide is referenced the plain, unconditional way
        # (\slide{}), regardless of which layout its own content ended
        # up using.
        layout, body = slide_content_to_tex(content, image_rel_paths)
        header = slide_ids.build_new_slide_header()
        dest = ctx.slides_dir / slide_language.current_name(id_slug)
        ctx.slides_dir.mkdir(parents=True, exist_ok=True)
        dest.write_text(header + body + "\n", encoding="utf-8", newline="")
        # Registered immediately, not batched until the end of the loop --
        # mint_slide_id() checks slide_ids.csv fresh on every call, so the
        # *next* iteration's mint would otherwise be free to draw this
        # same id again before it's ever recorded anywhere.
        slide_ids.append_slide_id(ctx, slide_id)

        new_text = deck_editor.insert_slide_call(
            deck.path, expected_text, insert_at, indent, "slide", id_slug,
        )
        insert_at += len(new_text) - len(expected_text)
        expected_text = new_text

        summary.imported.append(ImportedSlide(id_slug=id_slug, layout=layout, title=content.title))
        if log is not None:
            log(f"Imported {id_slug} ({layout})")

    return summary
