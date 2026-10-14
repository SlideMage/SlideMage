"""The readability check in the assistant: the results panel and the flow behind the two commands.

`ReadabilityPanel` takes the place of the conversation (assistant.py), like the image results, until Back to
conversation: the findings grouped by slide, each with its severity, class, measured value against the threshold, an
excerpt and the suggestion, a summary line, and Check again. Clicking a finding (or Show slide) focuses that slide in
the centre. A slide with findings it can fix (those not set by the template, which the panel marks "set by the
template" and tells where to change) has Make readable, the AI task of terminal/tasks.py. Nothing in the panel knows
where a report comes from.

`ReadabilityCheck` runs the checks on a worker thread, on every route (no AI is used): "this slide" renders a draft of
the slide in view as the top bar says (render_context, as the task card's Check preview does); "this deck" reads the
deck's compiled PDF, but only while it is current. When it is not, the panel says why and offers "Compile the deck
first", which starts the normal compile and runs the check when that run is over. Nothing is compiled silently.
Closing the panel stops the render in progress and drops its result. Every report is also kept per slide text
(readability_check.KnownFindings) for Make readable and the assistant header's button.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout

from ... import deck_outline, readability, readability_check, slide_language
from ...compile_status import DONE
from ...deck_scan import Deck
from ...readability_check import StalePdf
from .. import background
from ..kit import kit_qss as q
from ..kit.flow import FlowLayout
from ..kit.widgets import Button, ClickFrame, IconLabel, Surface, announce, clear_layout, set_property
from . import compile_actions
from .menus import VIEW_LABELS
from .preview_view import render_context

LOOK = {readability.ERROR: ("error", "error"), readability.WARNING: ("warning", "warning")}   # icon and tone
TEMPLATE_HINT = ("The slide does not set this size: it comes from the template's preamble (for the footnote and source "
                 "font, \\setbeamerfont{footnote}). Change it there, once for every slide; Make readable leaves it alone.")


class ReadabilityPanel(Surface):
    """The report of a check (see the module docstring); `back` is the assistant's ← Back to conversation."""

    closed = Signal()                  # Close, or Back to conversation
    again_clicked = Signal()           # Check again
    compile_clicked = Signal()         # Compile the deck first
    slide_clicked = Signal(object)     # a SlideReport: take the user to that slide
    make_readable_clicked = Signal(object)    # a SlideReport: run Make readable on that slide

    def __init__(self) -> None:
        super().__init__()
        self.report: Optional[readability.Report] = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self.back = Button("← Back to conversation", "ghost", compact=True)
        self.back.clicked.connect(self.closed)
        layout.addWidget(self.back, 0, Qt.AlignmentFlag.AlignLeft)
        frame = Surface()
        frame.setObjectName(q.TASK_CARD)
        body = QVBoxLayout(frame)
        body.setContentsMargins(14, 14, 14, 14)
        body.setSpacing(10)
        self.title = QLabel()
        self.title.setObjectName(q.TASK_TITLE)
        self.title.setWordWrap(True)
        body.addWidget(self.title)
        self.summary = QLabel()
        self.summary.setObjectName(q.TASK_STATE)
        self.summary.setWordWrap(True)
        body.addWidget(self.summary)
        self.list = QVBoxLayout()
        self.list.setSpacing(10)
        body.addLayout(self.list)
        self._buttons = FlowLayout(spacing=8)
        body.addLayout(self._buttons)
        layout.addWidget(frame)
        self.again = self.compile_button = self.close_button = None
        self.hide()

    # -- the states ----------------------------------------------------------------------------------

    def _show(self, title: str, summary: str, tone: str = "muted") -> None:
        self.report = None
        self.title.setText(title)
        self.summary.setText(summary)
        set_property(self.summary, "tone", tone)
        clear_layout(self.list)
        clear_layout(self._buttons)
        self.again = self.compile_button = None
        self.show()
        announce(self.title, f"{title}. {summary}")

    def _buttons_row(self, *, again: bool = False, compile_first: bool = False) -> None:
        if compile_first:
            self.compile_button = Button("Compile the deck first", "primary")
            self.compile_button.clicked.connect(self.compile_clicked)
            self._buttons.addWidget(self.compile_button)
        if again:
            self.again = Button("Check again", "primary")
            self.again.clicked.connect(self.again_clicked)
            self._buttons.addWidget(self.again)
        self.close_button = Button("Close", "secondary" if again or compile_first else "primary")
        self.close_button.clicked.connect(self.closed)
        self._buttons.addWidget(self.close_button)

    def show_running(self, title: str, message: str) -> None:
        self._show(title, message)
        self._buttons_row()

    def show_stale(self, title: str, why: str) -> None:
        self._show(title, f"The compiled PDF is out of date: {why}. The check reads the compiled deck, so compile "
                          "it first.", "warning")
        self._buttons_row(compile_first=True)

    def show_error(self, title: str, message: str) -> None:
        self._show(title, message, "error")
        self._buttons_row(again=True)

    def show_report(self, title: str, report: readability.Report, slide_titles: dict[str, str]) -> None:
        """`slide_titles`: slide id -> its title, for the group headings."""
        problems = [slide for slide in report.slides if slide.findings]
        clean = not problems
        self._show(title, report.summary + (". Nothing to report: every slide passes." if clean else "."),
                   "ok" if clean else "muted")
        self.report = report
        for slide in problems:
            self.list.addLayout(self._slide_group(slide, slide_titles.get(slide.slide_id, "")))
        self._buttons_row(again=True)

    # -- one slide's findings -----------------------------------------------------------------------

    def _slide_group(self, slide: readability.SlideReport, title: str) -> QVBoxLayout:
        group = QVBoxLayout()
        group.setSpacing(4)
        group.addLayout(self._slide_header(slide, title))
        for finding in slide.findings:
            group.addWidget(self._finding_row(slide, finding))
        return group

    def _slide_header(self, slide: readability.SlideReport, title: str) -> QHBoxLayout:
        header = QHBoxLayout()
        header.setSpacing(8)
        label = QLabel(f"{slide.slide_id} · {title}" if title else slide.slide_id)
        label.setObjectName(q.TASK_STATE)
        label.setWordWrap(True)
        header.addWidget(label, 1)
        show = Button("Show slide", "ghost", compact=True)
        show.setAccessibleName(f"Show slide {slide.slide_id}")
        show.setEnabled(bool(slide.file))
        show.clicked.connect(lambda: self.slide_clicked.emit(slide))
        header.addWidget(show)
        if slide.fixable and slide.file:
            fix = Button("Make readable", "secondary", compact=True)
            fix.setAccessibleName(f"Make slide {slide.slide_id} readable")
            fix.setToolTip("Let the AI enlarge the text and images and lay the slide out again")
            fix.clicked.connect(lambda: self.make_readable_clicked.emit(slide))
            header.addWidget(fix)
        return header

    def _finding_row(self, slide: readability.SlideReport, finding: readability.Finding) -> ClickFrame:
        row = ClickFrame()
        row.setCursor(Qt.CursorShape.PointingHandCursor)
        line = QHBoxLayout(row)
        line.setContentsMargins(6, 4, 6, 4)
        line.setSpacing(8)
        icon, tone = LOOK[finding.severity]
        mark = IconLabel(icon, 16)
        mark.set_tone(tone)
        mark.setAccessibleName(finding.severity.capitalize())
        line.addWidget(mark, 0, Qt.AlignmentFlag.AlignTop)
        words = QVBoxLayout()
        words.setSpacing(1)
        measure = QLabel(f"{readability.LABELS[finding.cls]} · {finding.measure_text}"
                         + (f" · {finding.count} lines" if finding.count > 1 else "")
                         + (" · set by the template" if finding.template_level else ""))
        measure.setObjectName(q.TASK_STATE)
        measure.setWordWrap(True)
        set_property(measure, "tone", tone)
        words.addWidget(measure)
        quoted = finding.image or finding.excerpt
        if quoted:
            excerpt = QLabel(quoted)
            excerpt.setObjectName(q.PANEL_MONO)
            excerpt.setWordWrap(True)
            words.addWidget(excerpt)
        suggestion = QLabel(TEMPLATE_HINT if finding.template_level else finding.suggestion)
        suggestion.setObjectName(q.PANEL_CAPTION)
        suggestion.setWordWrap(True)
        words.addWidget(suggestion)
        line.addLayout(words, 1)
        row.setToolTip(f"Show slide {slide.slide_id}")
        row.clicked.connect(lambda: self.slide_clicked.emit(slide))
        return row


class _Worker(QThread):
    done = Signal(object, object, object)      # this worker, the report or None, the exception or None

    def __init__(self, work: Callable[[], readability.Report]) -> None:
        super().__init__()
        self._work = work

    def run(self) -> None:
        try:
            report, error = self._work(), None
        except Exception as exc:  # noqa: BLE001 -- whatever the render or the read raised is the panel's message
            report, error = None, exc
        self.done.emit(self, report, error)


@dataclass
class _Request:
    """What a check is for, kept for Check again: a slide's file, or a deck with the view and language."""
    title: str
    path: Optional[Path] = None
    deck: Optional[Deck] = None
    view: str = ""
    language: str = ""
    text: str = ""                     # a slide's: what was measured (set when the check starts)


class ReadabilityCheck(QObject):
    """See the module docstring. `app` is the workspace window; `workspace` shows a slide for a click."""

    changed = Signal()                 # the panel came on show or went away
    reported = Signal()                # a report arrived (the slides' known findings changed)
    make_readable = Signal(object)     # the file (Path) of a slide whose Make readable was clicked

    def __init__(self, app, panel: ReadabilityPanel, workspace) -> None:
        super().__init__(panel)
        self.app, self.panel, self.workspace = app, panel, workspace
        self.active = False
        self._request: Optional[_Request] = None
        self._worker: Optional[_Worker] = None
        self._cancel = threading.Event()
        self._compiling: str = ""      # the job name of the compile "Compile the deck first" started
        panel.closed.connect(self.close)
        panel.again_clicked.connect(self.again)
        panel.compile_clicked.connect(self.compile_first)
        panel.slide_clicked.connect(self._show_slide)
        panel.make_readable_clicked.connect(lambda slide: self.make_readable.emit(self.app.project.slides_dir / slide.file))
        self._watching = False         # the compile slot is looked at once Compile the deck first has used it

    # -- the two checks ---------------------------------------------------------------------------------

    def check_slide(self) -> None:
        """The slide in the Source view, rendered as a draft."""
        path = self.app.centre.path
        if path is None or render_context(self.app, path) is None:
            self.app.toast.show_message("Open a slide first: the readability check reads a typeset slide.")
            return
        self._begin(_Request(f"Readability · {self._slide_label(path)}", path=path))

    def check_deck(self) -> None:
        """The open deck's compiled PDF for the current view and language."""
        state = self.app.state
        if state.deck is None:
            self.app.toast.show_message("Open a deck first.")
            return
        self._begin(_Request(f"Readability · {state.deck.name} · {VIEW_LABELS[state.view]} · {state.language}",
                             deck=state.deck, view=state.view, language=state.language))

    def again(self) -> None:
        if self._request is not None:
            self._begin(self._request)

    def close(self) -> None:
        self._cancel.set()
        self._worker = None
        self._compiling = ""
        self.panel.hide()
        self.panel.report = None
        self._set_active(False)

    def _set_active(self, active: bool) -> None:
        if self.active != active:
            self.active = active
            self.changed.emit()

    # -- running ----------------------------------------------------------------------------------------

    def _begin(self, request: _Request) -> None:
        self._cancel.set()                     # a check still going is dropped
        self._cancel = cancel = threading.Event()
        self._request, self._compiling = request, ""
        if request.path is not None:
            work = self._slide_work(request, cancel)
            if work is None:
                return
            message = "Typesetting the slide as a draft and measuring it…"
        else:
            deck, view, language = request.deck, request.view, request.language
            ctx = self.app.project
            work = lambda: readability_check.check_deck(ctx, deck, view, language)      # noqa: E731
            message = "Measuring the compiled deck…"
        self.panel.show_running(request.title, message)
        self._set_active(True)
        self._worker = worker = _Worker(work)
        worker.done.connect(self._done)
        background.start_detached(worker)

    def _slide_work(self, request: _Request, cancel: threading.Event) -> Optional[Callable[[], readability.Report]]:
        app, path = self.app, request.path
        context = render_context(app, path)
        if context is None:
            app.toast.show_message("Open a slide first: the readability check reads a typeset slide.")
            return None
        target, view, language, timestamp = context
        text = request.text = app.centre.slide_text(path)
        ctx = app.project
        return lambda: readability_check.check_slide(ctx, target, text, view, language, timestamp, cancel, log=app.log)

    def _done(self, worker: _Worker, report: Optional[readability.Report], error: Optional[Exception]) -> None:
        if worker is not self._worker:         # closed or restarted meanwhile
            return
        self._worker = None
        title = self._request.title
        if isinstance(error, StalePdf):
            self.panel.show_stale(title, str(error))
        elif error is not None:
            self.panel.show_error(title, f"The check could not run: {str(error) or type(error).__name__}")
        else:
            known = self.app.readability_known
            if self._request.path is not None:
                known.remember_slide(self._request.path, self._request.text, report)
            else:
                known.remember_deck(self.app.project, report)
            self.panel.show_report(title, report, self._titles(report))
            self.reported.emit()

    def _titles(self, report: readability.Report) -> dict[str, str]:
        titles = {}
        for slide in report.slides:
            path = slide_language.current_path_for_bare_id(self.app.project, slide.slide_id)
            if path is not None:
                titles[slide.slide_id] = deck_outline.slide_file_title(path, path.name.removesuffix(slide_language.CURRENT_SUFFIX))
        return titles

    def _slide_label(self, path: Path) -> str:
        id_slug = path.name.removesuffix(slide_language.CURRENT_SUFFIX)
        title = deck_outline.slide_file_title(path, id_slug)
        return f"{slide_language.bare_id(id_slug)} · {title}" if title else slide_language.bare_id(id_slug)

    # -- the clicks -------------------------------------------------------------------------------------

    def _show_slide(self, slide: readability.SlideReport) -> None:
        if slide.file:
            self.workspace.show_slide(self.app.project.slides_dir / slide.file)

    def compile_first(self) -> None:
        """The deck's PDF is out of date: start the normal compile (its questions and syntax check included); the
        check runs when the run is over."""
        request = self._request
        if request is None or request.deck is None:
            return
        if not self._watching:
            self.app.compile.settled.connect(self._compile_settled)
            self._watching = True
        compile_actions.compile_current(self.app, request.view)
        if self.app.compile.running:
            self._compiling = readability_check.deck_job(request.deck, request.view, request.language).jobname
            self.panel.show_running(request.title, "Compiling the deck; the check runs when it is done…")

    def _compile_settled(self, run) -> None:
        if not self._compiling or self._compiling not in run.rows:
            return
        row, self._compiling = run.rows[self._compiling], ""
        if row.state == DONE:
            self._begin(self._request)
        else:
            self.panel.show_error(self._request.title, "The compile did not finish, so the deck was not checked.")
