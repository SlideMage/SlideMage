"""The suggestion bubbles of the Claude Code tab and what a click does (Claude Code tasks plan, step 2).

`bubbles(window)` says which tasks fit the slide in the Source view (and translation partner). A click goes through TaskRunner:
`start` captures the task on the GUI thread (the slide's text as its buffer has it, the request), a worker thread
runs ai/claude_runner.run_task, and the outcome comes back to the GUI thread as a signal. Only then is anything
changed, and only if the slide still has the captured text: a fix goes into the buffer (Ctrl+Z undoes it) or, for
a closed file, onto disk with a backup; the update of a translation changes the translation, wherever it is
open; a translation creates the partner slide, links it to the source (a change of the source's header,
subject to the same check) and puts its call after the source's in the deck.
Typing in the slide meanwhile makes it a conflict: nothing is written and the result is kept for the user.
The image bubbles (describe, translate the descriptions) are different: an _ImageWorker works through the slide's
images one process after another and alt_draft's batch stores each draft as it is done (nothing of the slide
changes); the Images panel is shown again at the end.
One task at a time; Stop and closing the window end its process.
"""
from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, QThread, QTimer, Signal

from .... import (alt_blocks, alt_draft, alt_images, deck_editor, latex_lint, slide_add, slide_ids, slide_language,
                  slide_source, slide_versioning)
from ....tex_source import masked_same_length
from ....ai import claude_images, claude_runner, claude_tasks, translation_style
from ....ai.claude_runner import CANCELLED, DONE, FAILED, NOTHING, Outcome
from ... import background

CONFLICT = "The slide changed while Claude worked."
_VERBS = {claude_tasks.TRANSLATE.name: "Translating", claude_tasks.UPDATE_TRANSLATION.name: "Updating",
          claude_tasks.FIX_LATEX.name: "Fixing", claude_tasks.PROOFREAD.name: "Proofreading",
          claude_tasks.CONCISE.name: "Shortening", claude_tasks.TITLE.name: "Retitling",
          claude_tasks.NOTE.name: "Adding a note to", claude_images.DESCRIBE.name: "Describing",
          claude_images.TRANSLATE.name: "Translating"}
PROSE_WORDS = 10                       # words of running text that make a slide "have text" for the bubbles
_WORD_RE = re.compile(r"[^\W\d_]{3,}")
_MARKUP_RE = re.compile(r"\\(?:begin|end)\{[^}]*\}|\\[A-Za-z]+\*?|\$[^$]*\$|\\\(.*?\\\)")


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
class _ImageCapture:
    """An image task as it was when its bubble was clicked."""
    task: claude_tasks.Task    # claude_images.DESCRIBE or TRANSLATE
    path: Path                 # of the slide
    id_slug: str
    images: list[str]          # store keys: what to describe, what to translate


@dataclass(frozen=True)
class _Capture:
    """A task as it was when its bubble was clicked: neither a focus change nor typing alters it."""
    task: claude_tasks.Task
    path: Path                 # the file the result goes into: the slide, or the translation to update
    id_slug: str
    text: str                  # the whole file: the freshness check and the header link work on it
    header: str                # what stands before `sent` in `text` and is not sent (an update keeps it)
    sent: str                  # what the model works on: `text`, or a body
    request: str
    language: str              # a translation's: the language to translate into, else ""
    eol: str                   # of the file: the line ends of a new slide
    deck_path: Path | None


def _id_slug(path: Path) -> str:
    return path.name.removesuffix(slide_language.CURRENT_SUFFIX)


def _focus(window) -> _Focus | None:
    """The slide the Source view shows, if it is a slide's current file."""
    path = window.centre.path
    if path is None or path.parent != slide_source.SLIDES_DIR or not slide_language.is_current_file(path):
        return None
    return _Focus(path, _id_slug(path), window.centre.slide_text(path))


def _errors(text: str) -> list[latex_lint.LintIssue]:
    return [issue for issue in latex_lint.lint_text(text) if issue.severity == latex_lint.ERROR]


def _has_text(text: str) -> bool:
    """Whether the slide has running text: PROSE_WORDS words of three letters or more, after the comments,
    LaTeX commands and inline math are taken out (a rough count: file names and macro arguments count too)."""
    return len(_WORD_RE.findall(_MARKUP_RE.sub(" ", masked_same_length(text)))) >= PROSE_WORDS


def _slide_images(text: str) -> tuple[list[str], list[str]]:
    """The slide's images (store keys) without a description, and those with an English text that has no
    current German one (alt_draft.images_needing_translation). Whether a model can read the image is only
    known at the run: a vector file or a missing one drops out there."""
    references = alt_blocks.referenced_images(text)
    if not references:
        return [], []
    entries = alt_images.load_store()
    found = {entry.image: entry for entry in (alt_images.lookup(entries, reference) for reference in references)
             if entry is not None}
    translate = set(alt_draft.images_needing_translation())
    return ([image for image, entry in found.items() if not (entry.short or entry.long or entry.is_decorative)],
            [image for image in found if image in translate])


def _offers(focus: _Focus, link: slide_language.TranslationLink | None) -> list[Bubble]:
    """The tasks that fit the slide `focus` with its translation partner `link`."""
    own = slide_language.own_language(focus.id_slug)
    found = []
    if link is None and own in slide_language.TRANSLATION_LANGUAGES:
        other = next(language for language in slide_language.TRANSLATION_LANGUAGES if language != own)
        found.append(Bubble(claude_tasks.TRANSLATE, f"Translate to {claude_tasks.LANGUAGE_NAMES[other]}"))
    if link is not None and link.outdated:
        language = own if link.is_translation else link.language
        found.append(Bubble(claude_tasks.UPDATE_TRANSLATION, f"Update {claude_tasks.LANGUAGE_NAMES[language]} translation"))
    if _errors(focus.text):
        found.append(Bubble(claude_tasks.FIX_LATEX, "Fix LaTeX errors"))
    text = _has_text(focus.text)
    if text and own in claude_tasks.LANGUAGE_NAMES:
        found.append(Bubble(claude_tasks.PROOFREAD, "Proofread"))
    if text:
        found.append(Bubble(claude_tasks.CONCISE, "Make more concise"))
    if slide_source.title_span(focus.text) is not None:
        found.append(Bubble(claude_tasks.TITLE, "Better title"))
    if text and not slide_source.note_calls(focus.text):
        found.append(Bubble(claude_tasks.NOTE, "Add speaker notes"))
    describe, translate = _slide_images(focus.text)
    if describe:
        found.append(Bubble(claude_images.DESCRIBE, f"Describe images ({len(describe)})"))
    if translate:
        found.append(Bubble(claude_images.TRANSLATE, f"Translate image descriptions ({len(translate)})"))
    return found


def bubbles(window) -> list[Bubble]:
    """The tasks that fit the slide in the Source view right now."""
    focus = _focus(window)
    return [] if focus is None else _offers(focus, slide_language.translation_link(focus.id_slug))


def _capture(window, task: claude_tasks.Task) -> _Capture | None:
    """The task on the slide in the Source view, or None when it no longer fits it."""
    focus = _focus(window)
    if focus is None:
        return None
    link = slide_language.translation_link(focus.id_slug)
    if not any(bubble.task is task for bubble in _offers(focus, link)):
        return None
    path, id_slug, text, header, sent, language = focus.path, focus.id_slug, focus.text, "", focus.text, ""
    own = slide_language.own_language(id_slug)
    style = (translation_style.de_address(), translation_style.glossary())
    if task is claude_tasks.TRANSLATE:
        language = next(code for code in slide_language.TRANSLATION_LANGUAGES if code != own)
        sent = slide_versioning.strip_marker(slide_ids.body_of(text))
        request = claude_tasks.translate_request(sent, own, language, *style)
    elif task is claude_tasks.UPDATE_TRANSLATION:
        path, source_path = (focus.path, link.path) if link.is_translation else (link.path, focus.path)
        id_slug = _id_slug(path)
        text = focus.text if path == focus.path else window.centre.slide_text(path)
        source = focus.text if source_path == focus.path else window.centre.slide_text(source_path)
        header, sent = slide_ids.split_header(text)
        request = claude_tasks.update_request(
            slide_versioning.strip_marker(slide_ids.body_of(source)), sent,
            slide_language.own_language(_id_slug(source_path)), slide_language.own_language(id_slug), *style)
    elif task is claude_tasks.FIX_LATEX:
        request = claude_tasks.fix_request(text, _errors(text))
    elif task is claude_tasks.PROOFREAD:
        request = claude_tasks.proofread_request(text, own, style[0])
    elif task is claude_tasks.CONCISE:
        request = claude_tasks.concise_request(text)
    elif task is claude_tasks.TITLE:
        request = claude_tasks.title_request(text)
    else:
        request = claude_tasks.note_request(text)
    deck = window.state.deck
    return _Capture(task, path, id_slug, text, header, sent, request, language,
                    slide_source.read_slide_source(path)[1], deck.path if deck is not None else None)


def _capture_images(window, task: claude_tasks.Task) -> _ImageCapture | None:
    """The image task on the slide in the Source view, or None when there is nothing for it any more."""
    focus = _focus(window)
    if focus is None:
        return None
    describe, translate = _slide_images(focus.text)
    images = describe if task is claude_images.DESCRIBE else translate
    return _ImageCapture(task, focus.path, focus.id_slug, images) if images else None


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


class _ImageWorker(QThread):
    done = Signal(object, object)      # this worker, the summary of alt_draft's batch

    def __init__(self, claude: Path, capture: _ImageCapture, model: str, effort: str, cancel: threading.Event) -> None:
        super().__init__()
        self.capture, self.cancel = capture, cancel
        self.backend = (claude_images.ClaudeDraftBackend if capture.task is claude_images.DESCRIBE
                        else claude_images.ClaudeTranslationBackend)(claude, model, effort, cancel)
        self.position = (1, len(capture.images))       # the image at work and how many: the status line reads it

    def _progress(self, index: int, total: int, _item) -> None:
        self.position = (index, total)

    def run(self) -> None:
        capture = self.capture
        if capture.task is claude_images.DESCRIBE:
            row = alt_blocks.SlideRow(capture.path, slide_language.bare_id(capture.id_slug), "", capture.images)
            summary = alt_draft.run_batch(alt_draft.slide_jobs(row, alt_images.load_store()), self.backend,
                                          on_progress=self._progress, should_stop=self.cancel.is_set)
        else:
            summary = alt_draft.run_translation_batch(capture.images, self.backend, on_progress=self._progress,
                                                      should_stop=self.cancel.is_set)
        self.done.emit(self, summary)


class TaskRunner(QObject):
    status = Signal(str, str)          # the status line's text and tone ("muted", "ok", "warning", "error")
    busy_changed = Signal(bool)

    def __init__(self, window, claude: Path, workspace, parent: QObject | None = None) -> None:
        """`window` is the main window, `workspace` the GuiWorkspace that applies edits to its buffers."""
        super().__init__(parent)
        self._window, self._claude, self._workspace = window, claude, workspace
        self._worker: _Worker | _ImageWorker | None = None
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
        images = task in (claude_images.DESCRIBE, claude_images.TRANSLATE)
        capture = (_capture_images if images else _capture)(self._window, task)
        if capture is None:
            self.status.emit("That no longer fits this slide.", "warning")
            return
        self._cancel = threading.Event()
        self._started = time.monotonic()
        self.unapplied = ""
        self._worker = (_ImageWorker if images else _Worker)(self._claude, capture, model, effort, self._cancel)
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
        worker = self._worker
        seconds = round(time.monotonic() - self._started)
        verb, slide = _VERBS[worker.capture.task.name], slide_language.bare_id(worker.capture.id_slug)
        if isinstance(worker, _ImageWorker):
            self.status.emit(f"{verb} images of {slide} … {worker.position[0]}/{worker.position[1]} · {seconds} s",
                             "muted")
        else:
            self.status.emit(f"{verb} {slide} … {seconds} s", "muted")

    def _on_done(self, worker: _Worker | _ImageWorker, outcome) -> None:
        if worker is not self._worker:         # the view was closed meanwhile
            return
        self._worker = None
        self._ticker.stop()
        worker.wait()
        worker.deleteLater()
        if isinstance(worker, _ImageWorker):
            report = self._images_report(worker.capture.task, outcome)
            self._window.side_panels.refresh()         # shows the drafts that were stored
        elif outcome.status == DONE:
            report = self._apply(worker.capture, outcome)
        else:
            report = {CANCELLED: ("Cancelled", "muted"), NOTHING: ("Nothing to change", "muted")}.get(
                outcome.status, (outcome.message, "error"))
        self.busy_changed.emit(False)          # after the change: the bubbles look at the slide as it is now
        self.status.emit(*report)

    def _images_report(self, task: claude_tasks.Task, summary) -> tuple[str, str]:
        """(status text, tone) of a finished or stopped run over images, `summary` being the batch's."""
        did = "described" if task is claude_images.DESCRIBE else "translated"
        if self._cancel.is_set():
            return f"Stopped after {summary.seconds:.1f} s: {summary.written} {did}", "muted"
        if not summary.attempted:
            return "None of these images can be read", "warning"
        text = f"Done in {summary.seconds:.1f} s: {summary.written} {did}"
        failed = summary.attempted - summary.written
        if not failed:
            return text, "ok"
        return f"{text}, {failed} failed ({summary.errors[0]})", "warning" if summary.written else "error"

    # -- applying ----------------------------------------------------------------------------------------

    def _apply(self, capture: _Capture, outcome: Outcome) -> tuple[str, str]:
        """Change the slide as the result says, if it still has the captured text: (status text, tone)."""
        try:
            note = self._translate(capture, outcome.text) if capture.language else self._write(capture, outcome.text)
        except OSError as exc:
            return str(exc), "error"
        if note is None:
            self.unapplied = outcome.text
            return CONFLICT, "warning"
        return f"Done in {outcome.elapsed_s:.1f} s{note}", "ok"

    def _write(self, capture: _Capture, result: str) -> str | None:
        """Put `result` in place of the captured text (after the part of it that was not sent) and show it;
        None if the file has changed. What to append to the status line."""
        new = capture.header + result
        if claude_runner.apply_result(self._workspace, capture.path, capture.text, new) is not None:
            return None
        window = self._window
        centre = window.centre
        if (centre.path == capture.path and self._workspace.is_open(capture.path)
                and window.state.mode in ("preview", "split") and not _errors(new)):
            centre.preview.render_buffer()             # no mode switch, no question; else the preview offers it
        # a file on disk is shown again by the refresh of its write
        return f": {capture.id_slug} updated" if capture.task is claude_tasks.UPDATE_TRANSLATION else ""

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
