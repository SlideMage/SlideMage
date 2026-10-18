"""The reveal steps of a slide, for the Preview's step bar.

A step is a beamer overlay: page k of a render that keeps every overlay is step k (slide_preview's
`all_steps` render selects `1-`, which also overrides a \\slidestep's steps, the final-state flag and
a spec on the slide's own raw frame). Nothing here counts steps by reading the slide: the count is the
page count of that render, and it is taken per deck version, because \\conditionalpause and the
\\deck... macros add or drop steps in some versions (docs/plans/reveal-step-slider.md, 3.2).

What this module does:
- scan_slide(): the few things worth knowing from the slide's text -- whether it has version-dependent
  reveal logic, the final-state flag, a spec on its own frame;
- plan_for(): which of the steps 1..n a deck call includes in a view (a StepPlan);
- read_pages(): the pages of a render as PNG bytes (in the raster child process, like every MuPDF read).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from . import preview_raster_client
from .deck_editor import DEFAULT_CONDITIONS, SlideCall, expand_steps

PAGE_DPI = 130
MAX_PAGES = 60
INSTRUCTOR = DEFAULT_CONDITIONS[0]

# Commands whose output depends on the deck version and so can change the number of steps.
_VERSION_DEPENDENT_RE = re.compile(
    r"\\(?:conditionalpause|deck(?:item|reveal|revealfinal|only|uncover|visible|alt|invisible)"
    r"|ifSM(?:Instructor|DuringCourse|AfterCourse)Version|ifdeckversioninlist|SMDeckVersion)(?![A-Za-z@])")
_FINAL_FLAG_RE = re.compile(r"^[ \t]*\\SMFinalStateForStudents[ \t]*(?:%.*)?\r?$", re.MULTILINE)
_FINAL_FLAG_ANY_RE = re.compile(r"\\SMFinalStateForStudents(?![A-Za-z@])")
_OWN_SPEC_RE = re.compile(r"\\begin\s*\{frame\}\s*<([^<>]*)>")
_FRAMEBREAKS_RE = re.compile(r"allowframebreaks")


@dataclass(frozen=True)
class SlideScan:
    version_dependent: bool = False      # \conditionalpause, \deck...: step numbers may differ per version
    final_flag: bool = False             # \SMFinalStateForStudents
    own_frame_spec: Optional[str] = None  # `2-3` of the slide's own \begin{frame}<2-3>
    frame_breaks: bool = False           # allowframebreaks: pages are not overlays


def scan_slide(text: str) -> SlideScan:
    from .latex_lint import _mask_comments_and_verbatim

    masked = _mask_comments_and_verbatim(text)[0]
    spec = _OWN_SPEC_RE.search(masked)
    return SlideScan(
        version_dependent=_VERSION_DEPENDENT_RE.search(masked) is not None,
        final_flag=_FINAL_FLAG_ANY_RE.search(masked) is not None,
        own_frame_spec=spec.group(1).strip() if spec else None,
        frame_breaks=_FRAMEBREAKS_RE.search(masked) is not None)


@dataclass(frozen=True)
class StepPlan:
    """Which of the steps 1..n the selected deck call includes in one view."""
    n: int
    included: frozenset[int]
    slide_excluded: frozenset[int] = frozenset()   # steps the slide's own frame spec drops
    shown: bool = True        # the call typesets the slide in this view at all
    marked: bool = True       # False: every step counts and nothing is to be told apart
    reliable: bool = True     # False: page k may not be step k (frame breaks)
    final_only: bool = False  # only the last step, by \SMFinalStateForStudents
    note: str = ""

    def is_included(self, step: int) -> bool:
        return step in self.included

    def stops(self, deck_only: bool) -> list[int]:
        """The step numbers the slider offers."""
        steps = range(1, self.n + 1)
        if deck_only and self.marked and self.included:
            return [step for step in steps if step in self.included]
        return list(steps)


def plan_for(call: Optional[SlideCall], view: str, n: int, scan: SlideScan) -> StepPlan:
    """The StepPlan of `call` (None: a file shown alone, no deck call) in `view` for a render of `n` steps."""
    everything = frozenset(range(1, n + 1))
    own_excluded: frozenset[int] = frozenset()
    reliable = not scan.frame_breaks
    if scan.own_frame_spec is not None:
        try:
            own_excluded = everything - expand_steps(scan.own_frame_spec, n)
        except ValueError:
            reliable = False
    if call is None:
        return StepPlan(n, everything, own_excluded, marked=bool(own_excluded), reliable=reliable)
    if not call.included_in(view):
        return StepPlan(n, frozenset(), own_excluded, shown=False, reliable=reliable,
                        note=f"The deck does not typeset this call in {view}.")
    if call.macro == "slidestep":
        try:
            included = expand_steps(call.steps, n)
        except ValueError:
            return StepPlan(n, everything, own_excluded, marked=False, reliable=False,
                            note=f"Steps {call.steps!r} cannot be read.")
        return StepPlan(n, included, own_excluded, reliable=reliable)
    if scan.final_flag and view != INSTRUCTOR and n:
        return StepPlan(n, frozenset({n}), own_excluded, reliable=reliable, final_only=True,
                        note="Students see only the final state (\\SMFinalStateForStudents).")
    return StepPlan(n, everything, own_excluded, marked=bool(own_excluded), reliable=reliable)


def read_pages(pdf: Path, dpi: int = PAGE_DPI) -> list[bytes]:
    """The pages of a rendered slide as PNG bytes (at most MAX_PAGES), read in the raster child process."""
    return list(preview_raster_client.read_document(pdf, "pdf_images", 1, MAX_PAGES, dpi)["images"])


# -- the final-state flag that no deck needs any longer (docs/plans/reveal-step-slider.md, 4c.1) ------------

STUDENT_VIEWS = tuple(v for v in DEFAULT_CONDITIONS if v != INSTRUCTOR)


def remove_final_flag(text: str) -> Optional[str]:
    r"""`text` without its own-line \SMFinalStateForStudents; None when it has no such line."""
    lines = text.splitlines(keepends=True)
    kept = [line for line in lines if not _FINAL_FLAG_RE.match(line.rstrip("\r\n"))]
    return "".join(kept) if len(kept) != len(lines) else None


def flag_acts(call: SlideCall, view: str) -> bool:
    r"""Whether \SMFinalStateForStudents decides what `call` typesets in the student version `view`: the call loads the
    slide's current file, typesets it in `view`, and has no \slidestep steps of its own (those win over the flag)."""
    return call.version is None and call.included_in(view) and call.macro != "slidestep"


def final_flag_is_dead(ctx, id_slug: str) -> bool:
    r"""True when no deck of the project needs the flag in `id_slug`'s file: it is called in at least one deck, and every
    call of it in every deck (archived ones too) is a \slidestep for each student version it typesets, is not typeset
    in that version, or pins a frozen file. A deck that cannot be read counts as needing it."""
    from . import slide_usage

    try:
        usages = slide_usage.find_usage(ctx, id_slug)
    except Exception:  # noqa: BLE001 -- never remove on doubt
        return False
    if not usages:
        return False
    return not any(flag_acts(call, view) for usage in usages for call in usage.calls for view in STUDENT_VIEWS)


def drop_dead_final_flag(ctx, id_slug: str) -> Optional[tuple[Path, str, str]]:
    r"""Take \SMFinalStateForStudents out of the slide's current file when no deck needs it: silently, with no new
    version, no "+" and no frozen file (the slide typesets exactly as before). Returns (path, text before, text
    after) for the undo, None when nothing was changed."""
    from . import slide_language, slide_source, slide_versioning
    from .fileio import StaleFileError

    path = ctx.slides_dir / slide_language.current_name(id_slug)
    if not path.is_file():
        return None
    text, eol = slide_source.read_slide_source(path)
    new = remove_final_flag(text)
    if new is None or not final_flag_is_dead(ctx, id_slug):
        return None
    try:
        written = slide_versioning.save_slide(ctx, path, new, eol, text, mark=False)[0]
    except (OSError, ValueError, StaleFileError):
        return None
    return path, text, written


def restore_final_flag(ctx, path: Path, before: str, after: str) -> bool:
    """Put `before` back over `after` (the undo of drop_dead_final_flag), byte for byte. False when the slide changed
    meanwhile (nothing is written)."""
    from . import slide_source, slide_versioning
    from .fileio import StaleFileError

    try:
        eol = slide_source.read_slide_source(path)[1]
        slide_versioning.save_slide(ctx, path, before, eol, after, mark=False)
    except (OSError, ValueError, StaleFileError):
        return False
    return True
