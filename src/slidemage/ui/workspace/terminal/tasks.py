"""The suggestion bubbles of the Claude Code tab and what a click does (Claude Code tasks plan, step 2).

`bubbles(window)` says which tasks fit the slide in the Source view. A click goes through TaskRunner:
`start` captures the task on the GUI thread (the slide's text as its buffer has it, the request), a worker thread
runs ai/claude_runner.run_task, and the outcome comes back to the GUI thread as a signal. Only then is anything
changed, and only if the slide still has the captured text: a fix goes into the buffer (Ctrl+Z undoes it) or, for
a closed file, onto disk with a backup; a translation creates the partner slide, links it to the source (a
change of the source's header, subject to the same check) and puts its call after the source's in the deck.
Typing in the slide meanwhile makes it a conflict: nothing is written and the result is kept for the user.
One task at a time; Stop and closing the window end its process.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, QThread, QTimer, Signal

from .... import deck_editor, latex_lint, slide_add, slide_ids, slide_language, slide_source, slide_versioning
from ....ai import claude_runner, claude_tasks, translation_style
from ....ai.claude_runner import CANCELLED, DONE, FAILED, NOTHING, Outcome
from ... import background

CONFLICT = "The slide changed while Claude worked."
_VERBS = {claude_tasks.TRANSLATE.name: "Translating", claude_tasks.FIX_LATEX.name: "Fixing"}


@dataclass(frozen=True)
class Bubble:
    task: claude_tasks.Task
    label: str


@dataclass(frozen=True)
class _Focus:
    path: Path
    id_slug: str
    text: str                  # as the Source view has it, unsaved edits included


@dataclass(frozen=True)
class _Capture:
    """A task as it was when its bubble was clicked: neither a focus change nor typing alters it."""
    task: claude_tasks.Task
    path: Path
    id_slug: str
    text: str                  # the whole slide file: the freshness check and the header link work on it
    sent: str                  # what the model works on: `text`, or the body of a slide to translate
    request: str
    language: str              # a translation's: the language to translate into, else ""
    eol: str                   # of the file: the line ends of a new slide
    deck_path: Path | None


def _focus(window) -> _Focus | None:
    """The slide the Source view shows, if it is a slide's current file."""
    path = window.centre.path
    if path is None or path.parent != slide_source.SLIDES_DIR or not slide_language.is_current_file(path):
        return None
    return _Focus(path, path.name.removesuffix(slide_language.CURRENT_SUFFIX), window.centre.slide_text(path))


def _translate_into(id_slug: str) -> str | None:
    """The other language of EN/DE, when the slide has no translation partner yet."""
    own = slide_language.own_language(id_slug)
    if own not in slide_language.TRANSLATION_LANGUAGES or slide_language.translation_link(id_slug) is not None:
        return None
    return next(language for language in slide_language.TRANSLATION_LANGUAGES if language != own)


def _errors(text: str) -> list[latex_lint.LintIssue]:
    return [issue for issue in latex_lint.lint_text(text) if issue.severity == latex_lint.ERROR]


def bubbles(window) -> list[Bubble]:
    """The tasks that fit the slide in the Source view right now."""
    focus = _focus(window)
    if focus is None:
        return []
    found = []
    language = _translate_into(focus.id_slug)
    if language is not None:
        found.append(Bubble(claude_tasks.TRANSLATE, f"Translate to {claude_tasks.LANGUAGE_NAMES[language]}"))
    if _errors(focus.text):
        found.append(Bubble(claude_tasks.FIX_LATEX, "Fix LaTeX errors"))
    return found


def _capture(window, task: claude_tasks.Task) -> _Capture | None:
    """The task on the slide in the Source view, or None when it no longer fits it."""
    focus = _focus(window)
    if focus is None:
        return None
    language, sent = "", focus.text
    if task is claude_tasks.TRANSLATE:
        language = _translate_into(focus.id_slug)
        if language is None:
            return None
        sent = slide_versioning.strip_marker(slide_ids.body_of(focus.text))
        request = claude_tasks.translate_request(
            sent, slide_language.own_language(focus.id_slug), language, translation_style.de_address(),
            translation_style.glossary())
    else:
        errors = _errors(focus.text)
        if not errors:
            return None
        request = claude_tasks.fix_request(sent, errors)
    deck = window.state.deck
    return _Capture(task, focus.path, focus.id_slug, focus.text, sent, request, language,
                    slide_source.read_slide_source(focus.path)[1], deck.path if deck is not None else None)


class _Worker(QThread):
    done = Signal(object, object)      # this worker, the Outcome

    def __init__(self, claude: Path, capture: _Capture, model: str, effort: str, cancel: threading.Event) -> None:
        super().__init__()
        self.claude, self.capture, self.model, self.effort, self.cancel = claude, capture, model, effort, cancel

    def run(self) -> None:
        capture = self.capture
        try:
            outcome = claude_runner.run_task(self.claude, capture.task, capture.sent, capture.request,
                                             self.model, self.effort, cancel=self.cancel)
        except OSError as exc:         # `claude` could not be started
            outcome = Outcome(FAILED, message=str(exc))
        self.done.emit(self, outcome)


class TaskRunner(QObject):
    status = Signal(str, str)          # the status line's text and tone ("muted", "ok", "warning", "error")
    busy_changed = Signal(bool)

    def __init__(self, window, claude: Path, workspace, parent: QObject | None = None) -> None:
        """`window` is the main window, `workspace` the GuiWorkspace that applies edits to its buffers."""
        super().__init__(parent)
        self._window, self._claude, self._workspace = window, claude, workspace
        self._worker: _Worker | None = None
        self._cancel = threading.Event()
        self._started = 0.0
        self._ticker = QTimer(self)
        self._ticker.setInterval(1000)
        self._ticker.timeout.connect(self._tick)
        self.unapplied = ""            # the result a conflict did not apply, for the user to copy

    @property
    def busy(self) -> bool:
        return self._worker is not None

    def start(self, task: claude_tasks.Task, model: str, effort: str) -> None:
        """Run `task` on the slide in the Source view, unless one is running or it no longer fits."""
        if self.busy:
            return
        capture = _capture(self._window, task)
        if capture is None:
            self.status.emit("That no longer fits this slide.", "warning")
            return
        self._cancel = threading.Event()
        self._started = time.monotonic()
        self.unapplied = ""
        self._worker = _Worker(self._claude, capture, model, effort, self._cancel)
        self._worker.done.connect(self._on_done)
        self.busy_changed.emit(True)
        self._tick()
        self._ticker.start()
        background.start_detached(self._worker)

    def stop(self) -> None:
        self._cancel.set()

    def shutdown(self) -> None:
        """The view is going away: end the process; its outcome is not looked at."""
        self._ticker.stop()
        self._cancel.set()
        worker, self._worker = self._worker, None
        if worker is not None:
            background.stop_worker(worker)

    def _tick(self) -> None:
        capture = self._worker.capture
        seconds = round(time.monotonic() - self._started)
        self.status.emit(f"{_VERBS[capture.task.name]} {slide_language.bare_id(capture.id_slug)} … {seconds} s", "muted")

    def _on_done(self, worker: _Worker, outcome: Outcome) -> None:
        if worker is not self._worker:         # the view was closed meanwhile
            return
        self._worker = None
        self._ticker.stop()
        worker.wait()
        worker.deleteLater()
        if outcome.status == DONE:
            report = self._apply(worker.capture, outcome)
        else:
            report = {CANCELLED: ("Cancelled", "muted"), NOTHING: ("Nothing to change", "muted")}.get(
                outcome.status, (outcome.message, "error"))
        self.busy_changed.emit(False)          # after the change: the bubbles look at the slide as it is now
        self.status.emit(*report)

    # -- applying ----------------------------------------------------------------------------------------

    def _apply(self, capture: _Capture, outcome: Outcome) -> tuple[str, str]:
        """Change the slide as the result says, if it still has the captured text: (status text, tone)."""
        try:
            note = self._translate(capture, outcome.text) if capture.language else self._fix(capture, outcome.text)
        except OSError as exc:
            return str(exc), "error"
        if note is None:
            self.unapplied = outcome.text
            return CONFLICT, "warning"
        return f"Done in {outcome.elapsed_s:.1f} s{note}", "ok"

    def _fix(self, capture: _Capture, fixed: str) -> str | None:
        """Put `fixed` in place of the slide's text and show it; None if the slide has changed."""
        if claude_runner.apply_result(self._workspace, capture.path, capture.text, fixed) is not None:
            return None
        window = self._window
        centre = window.centre
        if (centre.path == capture.path and self._workspace.is_open(capture.path)
                and window.state.mode in ("preview", "split") and not _errors(fixed)):
            centre.preview.render_buffer()             # no mode switch, no question; else the preview offers it
        return ""                                      # a file on disk is shown again by the refresh of its write

    def _translate(self, capture: _Capture, translated: str) -> str | None:
        """Create the partner slide from `translated`, link it to the source and add it to the deck, and show it;
        None, with nothing created, if the source has changed. What to append to the status line."""
        window = self._window
        if window.centre.slide_text(capture.path) != capture.text:
            return None
        created = slide_add.create_translation(
            capture.id_slug, slide_add.slug_of(capture.id_slug), capture.language, translated.replace("\n", capture.eol))
        linked = slide_ids.with_translation_backreference(capture.text, capture.language, created.id_slug)
        note = f": {created.id_slug} created"
        if (problem := claude_runner.apply_result(self._workspace, capture.path, capture.text, linked)) is not None:
            note += f", not linked to {capture.id_slug} ({problem})"
        if not self._add_to_deck(capture, created.id_slug):
            note += ", not added to the deck"
        window.open_slide_editor(created.path)
        return note

    def _add_to_deck(self, capture: _Capture, id_slug: str) -> bool:
        """Put the call of `id_slug` right after the source's in the deck that was open. Whether it was."""
        window = self._window
        deck = next((d for d in window.decks if d.path == capture.deck_path), None)
        call = next((c for c in deck_editor.parse_slide_calls(deck) if c.id == slide_language.bare_id(capture.id_slug)),
                    None) if deck is not None else None
        if call is None:
            return False
        try:
            deck_editor.insert_slide_call(deck.path, deck.text, call.line_end, call.indent, "slide", id_slug)
        except (deck_editor.StaleFileError, ValueError, OSError):
            return False
        window.after_deck_edit(deck.path, f"Added \\slide{{{id_slug}}} to {deck.name}", previous_text=deck.text)
        return True
