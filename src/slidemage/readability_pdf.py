"""What the readability check reads from a rendered PDF (readability.py judges it).

This is MuPDF work, so it runs in the raster child process (preview_raster.py asks for op "layout"; the GUI
process never opens the PDF itself). Per page it gives plain JSON data, in points on the page:

- the visible text, one entry per line with its dominant size, colour and box (invisible text -- the slide-id
  stamp, the alt-text of figures -- is left out);
- the placed raster images with their box and pixel size;
- the opaque filled rectangles in paint order (the background behind the text, the footer bar);
- the vector figures: clusters of many drawing paths, away from the full-width bars of the theme;
- the slide id the footer or the invisible stamp names (slide_snapshot.slide_id_of).
"""
from __future__ import annotations

FIGURE_MIN_PATHS = 12        # drawing paths that make a cluster a figure rather than a box or a rule
MIN_FILL_SIDE = 2.0          # points: thinner fills are rules and underlines, not backgrounds


def read_pages(path) -> list[dict]:
    import pymupdf

    from .slide_snapshot import slide_id_of

    with pymupdf.open(path) as doc:
        return [_page(page, slide_id_of(page)) for page in doc]


def _page(page, slide_id: str | None) -> dict:
    import pymupdf

    # Text outside the page is kept (MuPDF drops it unless it is asked for the whole plane): cut-off text is what
    # the check looks for.
    everything = pymupdf.INFINITE_RECT()
    width, height = page.rect.width, page.rect.height
    hidden = {(round(c[2][0], 2), round(c[2][1], 2))
              for trace in page.get_texttrace() if trace["type"] == 3 or not trace["opacity"] for c in trace["chars"]}
    drawings = page.get_drawings()
    return dict(
        width=width, height=height, slide_id=slide_id,
        lines=_lines(page.get_text("rawdict", clip=everything), hidden),
        images=[dict(bbox=list(info["bbox"]), width=info["width"], height=info["height"])
                for info in page.get_image_info()],
        fills=[[*_box(d["rect"]), _rgb(d["fill"])] for d in drawings
               if d["fill"] is not None and d.get("fill_opacity", 1) >= 0.99
               and d["rect"].width >= MIN_FILL_SIDE and d["rect"].height >= MIN_FILL_SIDE],
        figures=_figures(page, drawings, width, height))


def _box(rect) -> list[float]:
    return [round(value, 2) for value in rect]


def _rgb(color) -> int:
    red, green, blue = (round(part * 255) for part in color)
    return red << 16 | green << 8 | blue


def _lines(raw: dict, hidden: set) -> list[dict]:
    lines = []
    for block_index, block in enumerate(raw["blocks"]):
        if block["type"] != 0:
            continue
        for line in block["lines"]:
            spans = [s for s in line["spans"] if s["chars"] and s.get("alpha", 255)
                     and (round(s["origin"][0], 2), round(s["origin"][1], 2)) not in hidden]
            text = "".join(c["c"] for s in spans for c in s["chars"]).strip()
            if not text:
                continue
            # The dominant span carries the size and colour: a superscript marker or a bullet in another font
            # must not make a line small.
            main = max(spans, key=lambda s: (sum(c["c"].isalnum() for c in s["chars"]), s["size"]))
            lines.append(dict(
                text=text, size=main["size"], color=main["color"], origin_y=main["origin"][1], block=block_index,
                bbox=_box((min(s["bbox"][0] for s in spans), min(s["bbox"][1] for s in spans),
                           max(s["bbox"][2] for s in spans), max(s["bbox"][3] for s in spans))),
                vertical=abs(line["dir"][0]) < 0.7))
    return lines


def _figures(page, drawings, width: float, height: float) -> list[list[float]]:
    """The boxes of vector figures: clusters of at least FIGURE_MIN_PATHS paths, once the page-wide fills and the
    bars (header, footer, the frame's background) are set aside."""
    paths = [d for d in drawings if d["rect"].width < 0.9 * width and d["rect"].height < 0.5 * height]
    if len(paths) < FIGURE_MIN_PATHS:
        return []
    return [_box(box) for box in page.cluster_drawings(drawings=paths)
            if sum(1 for d in paths if box.contains(d["rect"])) >= FIGURE_MIN_PATHS]
