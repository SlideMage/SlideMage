"""The readability check of a slide or a deck, from the rendered PDF to the report (readability.py has the rules).

- A slide is rendered as a draft, in the view and language being edited, through a RenderService (the same locked
  preview build as the Preview pane and the task card's Check preview); nothing is written.
- A deck is read from its compiled PDF for the view and language, but only while that PDF is current: the compile
  record (compile_records.py) holds the hash of every file the compile read, and the PDF is stale when any of them,
  or the PDF itself, changed since. A stale or missing PDF is not compiled here: `StalePdf` says why, and the caller
  offers to compile first.

Pages become slides as the slide snapshots do (slide_snapshot.slide_runs: runs of pages with the same footer slide
id); the report then names each slide's source file, and an image finding the picture's file when the slide's source
includes a raster file of that pixel size, and marks the findings that the template sets (`_mark_template_level`).
`KnownFindings` keeps the last report of each slide, for the "Make readable" task.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from PIL import Image

from . import alt_blocks, compile_records, compiler, preview_raster_client, readability, slide_language, slide_snapshot
from .deck_scan import Deck
from .preview_requests import RenderService
from .project import ProjectContext
from .slide_source import read_slide_source
from .tex_source import masked_same_length

RASTER_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff", ".webp")
_SIZE_COMMAND_RE = re.compile(
    r"\\(?:tiny|scriptsize|footnotesize|small|normalsize|large|Large|LARGE|huge|Huge|fontsize)\b"
    r"|\\begin\{(?:tiny|scriptsize|footnotesize|small|large|Large|LARGE|huge|Huge)\}")


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
              thresholds: readability.Thresholds = readability.DEFAULTS, text: Optional[str] = None) -> readability.Report:
    """The report for the PDF of a deck, or (`slide` is its bare id) for a render of that one slide, whose
    pages are all that slide's, made from `text` (a draft); a deck's slides are read from their files."""
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
        source = text if text is not None else read_slide_source(path)[0]
        _mark_template_level(entry, source)
        if any(f.rule == readability.IMAGE_SIZE for f in entry.findings):
            _name_images(ctx, source, entry)
    return report


def _mark_template_level(entry: readability.SlideReport, source: str) -> None:
    """Mark the citation-class text-size findings of a slide whose `source` sets no font size (no \\tiny,
    \\footnotesize, \\fontsize, ... outside comments): the size of a footnote or a source line is then the template's
    (\\setbeamerfont{footnote} in its preamble), the same on every slide, and a slide cannot change it without
    overriding the template."""
    if _SIZE_COMMAND_RE.search(masked_same_length(source)):
        return
    for finding in entry.findings:
        finding.template_level = finding.rule == readability.TEXT_SIZE and finding.cls == readability.CITATION


def check_slide(ctx: ProjectContext, target, text: str, view: str, language: str, timestamp: bool, cancel,
                renders: Optional[RenderService] = None, log=lambda _line: None) -> readability.Report:
    """Render `text` as the slide `target` (a preview_target.PreviewTarget) and check the draft. RuntimeError when
    it does not compile or `cancel` is set."""
    pdf = (renders or RenderService()).request(target, text, view, language, timestamp, log).wait(cancel)[0]
    return check_pdf(ctx, pdf, target.bare_id, text=text)


def check_deck(ctx: ProjectContext, deck: Deck, view: str, language: str) -> readability.Report:
    """The report for the deck's compiled PDF; StalePdf when there is none that is current."""
    return check_pdf(ctx, deck_pdf(ctx, deck, view, language))


def _name_images(ctx: ProjectContext, source: str, entry: readability.SlideReport) -> None:
    """Set the file of each image finding: the raster file the slide's `source` includes with the same pixel size (the
    files, when several of that size are included)."""
    sizes: dict[tuple, list[str]] = {}
    for reference in alt_blocks.referenced_images(source):
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


class KnownFindings:
    """The last report of each slide file, for the text it was measured on: what "Make readable" is offered on and
    sends. A slide whose text is not the one measured has no known findings, so a check is never run to decide a
    button, and an edit forgets them. Pure; the checks of the panel and of the task fill it."""

    def __init__(self) -> None:
        self._known: dict[Path, tuple[str, readability.Report]] = {}

    def remember_slide(self, path: Path, text: str, report: readability.Report) -> None:
        """The report of the draft `text` of the slide file `path`."""
        self._known[path] = (text, readability.Report(report.slides[:1], report.thresholds))

    def remember_deck(self, ctx: ProjectContext, report: readability.Report) -> None:
        """The slides of a deck's report, for the text of their files now (the PDF is current, so it is the text the
        deck was made from)."""
        for entry in report.slides:
            path = slide_language.current_path_for_bare_id(ctx, entry.slide_id)
            if path is not None:
                self.remember_slide(path, read_slide_source(path)[0], readability.Report([entry], report.thresholds))

    def get(self, path: Path, text: str) -> Optional[readability.Report]:
        """The one-slide report measured on exactly `text` of `path`, else None."""
        known = self._known.get(path)
        return known[1] if known is not None and known[0] == text else None

    def fixable(self, path: Path, text: str) -> list[readability.Finding]:
        """The findings of the slide that it can fix, if it was measured on `text`."""
        report = self.get(path, text)
        return report.slides[0].fixable if report is not None and report.slides else []

    def has_errors(self, path: Path, text: str) -> bool:
        return any(f.severity == readability.ERROR for f in self.fixable(path, text))
