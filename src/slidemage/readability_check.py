"""The readability check of a slide or a deck, from the rendered PDF to the report (readability.py has the rules).

- A slide is rendered as a draft, in the view and language being edited, through a RenderService (the same locked
  preview build as the Preview pane and the task card's Check preview); nothing is written.
- A deck is read from its compiled PDF for the view and language, but only while that PDF is current: the compile
  record (compile_records.py) holds the hash of every file the compile read, and the PDF is stale when any of them,
  or the PDF itself, changed since. A stale or missing PDF is not compiled here: `StalePdf` says why, and the caller
  offers to compile first.

Pages become slides as the slide snapshots do (slide_snapshot.slide_runs: runs of pages with the same footer slide
id); the report then names each slide's source file, and an image finding the picture's file when the slide's source
includes a raster file of that pixel size.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PIL import Image

from . import alt_blocks, compile_records, compiler, preview_raster_client, readability, slide_language, slide_snapshot
from .deck_scan import Deck
from .preview_requests import RenderService
from .project import ProjectContext

RASTER_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff", ".webp")


class StalePdf(Exception):
    """The deck's PDF for the view is missing or out of date; str(exc) says why."""


def deck_job(deck: Deck, view: str, language: str) -> compiler.CompileJob:
    """The whole-deck compile of `view` in `language`, as the Compile menu builds it."""
    job = compiler.build_jobs(deck, view)[0]
    job.language = language
    return job


def deck_pdf(ctx: ProjectContext, deck: Deck, view: str, language: str) -> Path:
    """The deck's last compiled PDF for the view and language, if nothing it was made from has changed since;
    else StalePdf."""
    job = deck_job(deck, view, language)
    record = compile_records.read_record(ctx.build_dir, job.jobname)
    if record is None:
        raise StalePdf(f"{job.jobname} has not been compiled yet")
    stale = compile_records.check_record(record, None, compile_records.aux_dir(ctx.build_dir, job.jobname))
    if stale:
        raise StalePdf(", ".join(stale.reasons) + " since it was compiled")
    return Path(record["pdf"])


def check_pdf(ctx: ProjectContext, pdf: Path, slide: Optional[str] = None,
              thresholds: readability.Thresholds = readability.DEFAULTS) -> readability.Report:
    """The report for the PDF of a deck, or (`slide` is its bare id) for a render of that one slide, whose
    pages are all that slide's."""
    pages = [readability.Page.from_dict(data) for data in preview_raster_client.read_layout(pdf)]
    if slide is None:
        runs = slide_snapshot.slide_runs([page.slide_id for page in pages])
    else:
        runs = [(slide, list(range(len(pages))))] if pages else []
    report = readability.analyse(pages, runs, thresholds)
    for entry in report.slides:
        path = slide_language.current_path_for_bare_id(ctx, entry.slide_id)
        if path is None:
            continue
        entry.file = path.name
        for finding in entry.findings:
            finding.file = path.name
        if any(f.rule == readability.IMAGE_SIZE for f in entry.findings):
            _name_images(ctx, path, entry)
    return report


def check_slide(ctx: ProjectContext, target, text: str, view: str, language: str, timestamp: bool, cancel,
                renders: Optional[RenderService] = None, log=lambda _line: None) -> readability.Report:
    """Render `text` as the slide `target` (a preview_target.PreviewTarget) and check the draft. RuntimeError when
    it does not compile or `cancel` is set."""
    pdf = (renders or RenderService()).request(target, text, view, language, timestamp, log).wait(cancel)[0]
    return check_pdf(ctx, pdf, target.bare_id)


def check_deck(ctx: ProjectContext, deck: Deck, view: str, language: str) -> readability.Report:
    """The report for the deck's compiled PDF; StalePdf when there is none that is current."""
    return check_pdf(ctx, deck_pdf(ctx, deck, view, language))


def _name_images(ctx: ProjectContext, path: Path, entry: readability.SlideReport) -> None:
    """Set the file of each image finding: the raster file the slide's source includes with the same pixel size (the
    files, when several of that size are included)."""
    sizes: dict[tuple, list[str]] = {}
    for reference in alt_blocks.referenced_images(path.read_text(encoding="utf-8", errors="replace")):
        found = alt_blocks.resolve_image(ctx, reference)
        if found is None or found.suffix.lower() not in RASTER_SUFFIXES:
            continue
        try:
            with Image.open(found) as picture:
                names = sizes.setdefault(tuple(picture.size), [])
                if found.name not in names:
                    names.append(found.name)
        except OSError:
            continue
    for finding in entry.findings:
        if finding.rule == readability.IMAGE_SIZE:
            names = sizes.get(tuple(finding.pixels), [])
            finding.image = " or ".join(names[:3]) + (" or more" if len(names) > 3 else "")
