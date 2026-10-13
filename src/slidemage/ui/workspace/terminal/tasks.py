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
The deck bubbles (`deck_bubbles`, shown while the tab's scope is Deck) run one of these tasks over the deck's
slides: a batch with up to WORKERS processes at a time. Each slide is captured when its turn comes, so what the user
typed meanwhile is in the request; every result is applied by `_on_done` on the GUI thread, one after the other,
whichever process finished first, so writes, ids and links never race. A rate-limit error drops the batch to one
process and gives that slide a second try; a usage-limit error ends it. Its progress is the task row's status line,
what became of each slide is in the "Show result" sheet. "Describe images" is one image run over the deck's images, a
summary one process whose answer is shown, never written.
One task or batch at a time; Stop and closing the window end its processes.

Which backend runs a task is the active route's (ai_profile.resolve, captured when the task starts; the kind of
each task is KINDS). On Cloud · Claude Code every task is a `claude -p` process, as above. On Local and
Cloud · API only the tasks with an equivalent on a provider run, one at a time on that provider (the Ollama slot
is held for the run): the image tasks (alt_draft's batch with a ModelBackend / ModelTranslationBackend) and
Translate (slide_add.translate_body, its answer checked like Claude's). Every other task is refused with
"not available on <route>", nothing sent and no other route or model used.
"""
from __future__ import annotations

import re
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QObject, QThread, QTimer, Signal

from .... import (ai_review, alt_blocks, alt_draft, alt_images, deck_editor, deck_language, latex_lint, slide_add, slide_ids,
                  slide_language, slide_source, slide_versioning)
from ....project import ProjectContext
from ....tex_source import masked_same_length
from ....ai import ai_profile, claude_images, claude_runner, claude_tasks, resolver, translation_style
from ....ai.tools.base import ToolError
from ....ai.tools.edits import write_text
from ....ai.claude_runner import CANCELLED, DONE, FAILED, NOTHING, Outcome
from ... import background
from ...ai_models import confirm_if_new
from ..ai_work import RunningWork

CONFLICT = "The slide changed while Claude worked."
_VERBS = {claude_tasks.TRANSLATE.name: "Translating", claude_tasks.UPDATE_TRANSLATION.name: "Updating",
          claude_tasks.FIX_LATEX.name: "Fixing", claude_tasks.PROOFREAD.name: "Proofreading",
          claude_tasks.CONCISE.name: "Shortening", claude_tasks.TITLE.name: "Retitling",
          claude_tasks.NOTE.name: "Adding a note to", claude_images.DESCRIBE.name: "Describing",
          claude_images.TRANSLATE.name: "Translating", claude_tasks.SUMMARISE.name: "Summarising"}
# What each task is, for the route's models (ai_profile.TASKS).
KINDS = {claude_tasks.TRANSLATE.name: ai_profile.TRANSLATION, claude_tasks.UPDATE_TRANSLATION.name: ai_profile.TRANSLATION,
         claude_images.TRANSLATE.name: ai_profile.TRANSLATION, claude_images.DESCRIBE.name: ai_profile.IMAGE_DESCRIPTION,
         **dict.fromkeys((claude_tasks.FIX_LATEX.name, claude_tasks.PROOFREAD.name, claude_tasks.CONCISE.name,
                          claude_tasks.TITLE.name, claude_tasks.NOTE.name, claude_tasks.SUMMARISE.name),
                         ai_profile.FIXES)}
# The tasks that also run on a provider, as the Add slide sheet and the Images page do (see the docstring).
PROVIDER_TASKS = (claude_tasks.TRANSLATE, claude_images.DESCRIBE, claude_images.TRANSLATE)
_NAMES = {claude_tasks.TRANSLATE.name: "Translating a slide", claude_tasks.UPDATE_TRANSLATION.name: "Updating a translation",
          claude_tasks.FIX_LATEX.name: "Fixing LaTeX errors", claude_tasks.PROOFREAD.name: "Proofreading",
          claude_tasks.CONCISE.name: "Making a slide more concise", claude_tasks.TITLE.name: "Retitling a slide",
          claude_tasks.NOTE.name: "Adding a speaker note", claude_tasks.SUMMARISE.name: "Summarising a deck",
          claude_images.DESCRIBE.name: "Describing images", claude_images.TRANSLATE.name: "Translating image descriptions"}
WORKERS = 2                            # processes at a time in a batch
DECK_LABEL = "the deck"
BATCH_TASKS = (claude_tasks.TRANSLATE, claude_tasks.UPDATE_TRANSLATION, claude_tasks.FIX_LATEX)
SLOWED = "Slowed to one worker: rate limit"
PROSE_WORDS = 10                       # words of running text that make a slide "have text" for the bubbles
_WORD_RE = re.compile(r"[^\W\d_]{3,}")
_MARKUP_RE = re.compile(r"\\(?:begin|end)\{[^}]*\}|\\[A-Za-z]+\*?|\$[^$]*\$|\\\(.*?\\\)")


@dataclass(frozen=True)
class Bubble:
    task: claude_tasks.Task
    label: str
    paths: tuple[Path, ...] = ()       # a deck bubble: the slides (current files) it works on


@dataclass(frozen=True)
class _Focus:
    path: Path
    id_slug: str
    text: str                  # as the Source view has it, unsaved edits included


@dataclass(frozen=True)
class _ImageCapture:
    """An image task as it was when its bubble was clicked."""
    task: claude_tasks.Task    # claude_images.DESCRIBE or TRANSLATE
    label: str                 # the slide's id, or DECK_LABEL: what the status line names
    images: list[str]          # store keys: what to describe, what to translate
    rows: list[alt_blocks.SlideRow]    # to describe: the slides, each image on the first one that shows it


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


def _focus_at(window, path: Path) -> _Focus:
    return _Focus(path, _id_slug(path), window.centre.slide_text(path))


def _focus(window) -> _Focus | None:
    """The slide the Source view shows, if it is a slide's current file."""
    path = window.centre.path
    if path is None or path.parent != window.project.slides_dir or not slide_language.is_current_file(path):
        return None
    return _focus_at(window, path)


def _errors(ctx: ProjectContext, text: str) -> list[latex_lint.LintIssue]:
    return [issue for issue in latex_lint.lint_text(ctx, text) if issue.severity == latex_lint.ERROR]


def _has_text(text: str) -> bool:
    """Whether the slide has running text: PROSE_WORDS words of three letters or more, after the comments,
    LaTeX commands and inline math are taken out (a rough count: file names and macro arguments count too)."""
    return len(_WORD_RE.findall(_MARKUP_RE.sub(" ", masked_same_length(text)))) >= PROSE_WORDS


def _images_of(text: str, entries: dict[str, alt_images.ImageEntry]) -> dict[str, alt_images.ImageEntry]:
    """The store entries of the images the slide `text` shows, by store key."""
    found = (alt_images.lookup(entries, reference) for reference in alt_blocks.referenced_images(text))
    return {entry.image: entry for entry in found if entry is not None}


def _undescribed(found: dict[str, alt_images.ImageEntry]) -> list[str]:
    return [image for image, entry in found.items() if not (entry.short or entry.long or entry.is_decorative)]


def _slide_images(ctx: ProjectContext, text: str) -> tuple[list[str], list[str]]:
    """The slide's images (store keys) without a description, and those with an English text that has no
    current German one (alt_draft.images_needing_translation). Whether a model can read the image is only
    known at the run: a vector file or a missing one drops out there."""
    found = _images_of(text, alt_images.load_store(ctx))
    if not found:
        return [], []
    translate = set(alt_draft.images_needing_translation(ctx))
    return _undescribed(found), [image for image in found if image in translate]


def _describe_rows(window, paths) -> list[alt_blocks.SlideRow]:
    """For each of the slides `paths` that shows images without a description, a row of those images, an image
    shared by slides on the first of them only."""
    entries, seen, rows = alt_images.load_store(window.project), set(), []
    for path in paths:
        images = [image for image in _undescribed(_images_of(window.centre.slide_text(path), entries))
                  if image not in seen]
        if images:
            seen.update(images)
            rows.append(alt_blocks.SlideRow(path, slide_language.bare_id(_id_slug(path)), "", images))
    return rows


def _text_offers(ctx: ProjectContext, focus: _Focus, link: slide_language.TranslationLink | None) -> list[Bubble]:
    """The tasks on the text that fit the slide `focus` with its translation partner `link`."""
    own = slide_language.own_language(focus.id_slug)
    found = []
    if link is None and own in slide_language.TRANSLATION_LANGUAGES:
        other = next(language for language in slide_language.TRANSLATION_LANGUAGES if language != own)
        found.append(Bubble(claude_tasks.TRANSLATE, f"Translate to {claude_tasks.LANGUAGE_NAMES[other]}"))
    if link is not None and link.outdated:
        language = own if link.is_translation else link.language
        found.append(Bubble(claude_tasks.UPDATE_TRANSLATION, f"Update {claude_tasks.LANGUAGE_NAMES[language]} translation"))
    if _errors(ctx, focus.text):
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
    return found


def _offers(ctx: ProjectContext, focus: _Focus, link: slide_language.TranslationLink | None) -> list[Bubble]:
    """The tasks that fit the slide `focus` with its translation partner `link`."""
    found = _text_offers(ctx, focus, link)
    describe, translate = _slide_images(ctx, focus.text)
    if describe:
        found.append(Bubble(claude_images.DESCRIBE, f"Describe images ({len(describe)})"))
    if translate:
        found.append(Bubble(claude_images.TRANSLATE, f"Translate image descriptions ({len(translate)})"))
    return found


def bubbles(window) -> list[Bubble]:
    """The tasks that fit the slide in the Source view right now."""
    focus = _focus(window)
    return [] if focus is None else _offers(window.project, focus, slide_language.translation_link(window.project, focus.id_slug))


def _deck_slides(window) -> list[Path]:
    """The current files of the slides of the open deck in the current view and language, in the deck's order,
    each once however often the deck calls it."""
    state = window.state
    if state.deck is None:
        return []
    calls = [slot.call for slot in deck_language.deck_slots(window.project, state.deck, state.language)
             if slot.call.included_in(state.view)]
    paths = dict.fromkeys(window.project.slides_dir / slide_language.current_name(call.id_slug) for call in calls)
    return [path for path in paths if path.is_file()]


def deck_bubbles(window) -> list[Bubble]:
    """The tasks that fit the open deck: the slide tasks of BATCH_TASKS with the number of slides each fits (the
    same test as the slide's own bubble, no compile), the images still to describe, and the summary."""
    paths = _deck_slides(window)
    if not paths:
        return []
    fits: dict[str, list[Path]] = {task.name: [] for task in BATCH_TASKS}      # the slides each task fits
    links = slide_language.TranslationLinks(window.project.slides_dir)
    for path in paths:
        focus = _focus_at(window, path)
        for bubble in _text_offers(window.project, focus, slide_language.translation_link(window.project, focus.id_slug, links=links)):
            if bubble.task.name in fits:
                fits[bubble.task.name].append(path)
    labels = ("Translate missing slides ({})", "Update outdated translations ({})", "Fix LaTeX errors ({} slides)")
    found = [Bubble(task, label.format(len(fits[task.name])), tuple(fits[task.name]))
             for task, label in zip(BATCH_TASKS, labels) if fits[task.name]]
    rows = _describe_rows(window, paths)
    if rows:
        found.append(Bubble(claude_images.DESCRIBE, f"Describe images ({sum(len(row.images) for row in rows)})",
                            tuple(row.path for row in rows)))
    return found + [Bubble(claude_tasks.SUMMARISE, "Summarise this deck", tuple(paths))]


def _capture(window, task: claude_tasks.Task, focus: _Focus | None) -> _Capture | None:
    """The task on the slide `focus`, or None when it no longer fits it."""
    if focus is None:
        return None
    link = slide_language.translation_link(window.project, focus.id_slug)
    if not any(bubble.task is task for bubble in _offers(window.project, focus, link)):
        return None
    path, id_slug, text, header, sent, language = focus.path, focus.id_slug, focus.text, "", focus.text, ""
    own = slide_language.own_language(id_slug)
    style = (translation_style.de_address(window.project), translation_style.glossary(window.project))
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
        request = claude_tasks.fix_request(text, _errors(window.project, text))
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


def _capture_summary(window, paths) -> _Capture:
    """The summary of the deck whose slides are `paths`: the request carries their bodies as they are now."""
    bodies = [slide_versioning.strip_marker(slide_ids.body_of(window.centre.slide_text(path))) for path in paths]
    deck = window.state.deck.path
    return _Capture(claude_tasks.SUMMARISE, deck, DECK_LABEL, "", "", "", claude_tasks.summarise_request(bodies),
                    "", "", deck)


def _capture_images(window, task: claude_tasks.Task, paths) -> _ImageCapture | None:
    """The image task on the slides `paths` (a deck bubble) or the slide in the Source view, or None when there
    is nothing for it any more."""
    focus = None if paths else _focus(window)
    if not paths and focus is None:
        return None
    label = DECK_LABEL if paths else slide_language.bare_id(focus.id_slug)
    if task is claude_images.DESCRIBE:
        rows = _describe_rows(window, paths or [focus.path])
        images = [image for row in rows for image in row.images]
    else:
        rows, images = [], _slide_images(window.project, focus.text)[1]
    return _ImageCapture(task, label, images, rows) if images else None


class _Worker(QThread):
    done = Signal(object, object)      # this worker, the Outcome

    def __init__(self, capture: _Capture, run: Callable[[], Outcome]) -> None:
        super().__init__()
        self.capture, self._outcome = capture, run

    def run(self) -> None:
        try:
            outcome = self._outcome()
        except OSError as exc:         # `claude` could not be started
            outcome = Outcome(FAILED, message=str(exc))
        self.done.emit(self, outcome)


def _translate_on_provider(ctx: ProjectContext, provider, capture: _Capture, cancel: threading.Event) -> Outcome:
    """The Translate task on the provider of Local or the API (slide_add.translate_body). Its answer is checked as
    a Claude answer is: the protected parts stay and the text has no new LaTeX error."""
    started = time.monotonic()
    text, error = slide_add.translate_body(ctx, provider, capture.sent)
    outcome = Outcome(FAILED, attempts=1)
    if cancel.is_set():
        outcome.status = CANCELLED
    elif error:
        outcome.message = error
    else:
        new, problems = claude_tasks.check(ctx, capture.task, capture.sent, {capture.task.answer: text})
        if problems:
            outcome.message = "The translation was refused: " + "; ".join(problems)
        else:
            outcome.status, outcome.text = (NOTHING, "") if new == capture.sent else (DONE, new)
    outcome.elapsed_s = time.monotonic() - started
    return outcome


class _ImageWorker(QThread):
    done = Signal(object, object)      # this worker, the summary of alt_draft's batch

    def __init__(self, ctx: ProjectContext, capture: _ImageCapture, backend, cancel: threading.Event) -> None:
        """`backend` is a DraftBackend (to describe) or a TranslationBackend of any route."""
        super().__init__()
        self.ctx, self.capture, self.backend, self.cancel = ctx, capture, backend, cancel
        self.position = (1, len(capture.images))       # the image at work and how many: the status line reads it

    def _progress(self, index: int, total: int, _item) -> None:
        self.position = (index, total)

    def run(self) -> None:
        capture = self.capture
        if capture.task is claude_images.DESCRIBE:
            entries = alt_images.load_store(self.ctx)
            jobs = [job for row in capture.rows for job in alt_draft.slide_jobs(self.ctx, row, entries)]
            summary = alt_draft.run_batch(self.ctx, jobs, self.backend, on_progress=self._progress,
                                          should_stop=self.cancel.is_set)
        else:
            summary = alt_draft.run_translation_batch(self.ctx, capture.images, self.backend, on_progress=self._progress,
                                                      should_stop=self.cancel.is_set)
        self.done.emit(self, summary)


@dataclass
class _Item:
    task: claude_tasks.Task
    path: Path                 # the slide (current file) as the deck has it
    retried: bool = False      # put back once after a rate limit


@dataclass
class _Batch:
    """A deck bubble's run: the slides still to start and what became of the others."""
    task: claude_tasks.Task
    queue: deque[_Item]
    total: int
    limit: int = WORKERS       # processes at a time: 1 after a rate limit
    applied: int = 0
    failed: int = 0
    lines: list[str] = field(default_factory=list)    # per slide, as it was settled
    note: str = ""             # for the status line: SLOWED
    reason: str = ""           # why the batch ended by itself: the usage limit's message


class TaskRunner(QObject):
    status = Signal(str, str)          # the status line's text and tone ("muted", "ok", "warning", "error")
    busy_changed = Signal(bool)
    summary = Signal(str)              # the summary of the deck, to show

    def __init__(self, window, claude: Path, workspace, parent: QObject | None = None) -> None:
        """`window` is the main window, `workspace` the GuiWorkspace that applies edits to its buffers."""
        super().__init__(parent)
        self._window, self._claude, self._workspace = window, claude, workspace
        self._running: dict[_Worker | _ImageWorker, _Item | None] = {}    # with the batch item it works on
        self._batch: _Batch | None = None
        self._route: ai_profile.Route | None = None        # of the task or batch under way, captured at its start
        self._holds_slot = False                           # the app-wide Ollama slot, for a Local run
        self._providers: list = []                         # what Stop aborts: the providers or backends of the run
        self._cancel = threading.Event()
        self._started = 0.0
        self._ticker = QTimer(self)
        self._ticker.setInterval(1000)
        self._ticker.timeout.connect(self._tick)
        self.unapplied = ""            # the result a conflict did not apply, for the user to copy
        self.report = ""               # what became of each slide of the last batch

    @property
    def busy(self) -> bool:
        return bool(self._running) or self._batch is not None

    def running_work(self) -> list[RunningWork]:
        """The task or batch under way, for the AI switch's busy popup (ai_work.py)."""
        if not self.busy:
            return []
        if (batch := self._batch) is not None:
            text, note = (f"{_NAMES[batch.task.name]} · {len(batch.lines)} of {batch.total} done",
                          "Slides not started are cancelled, not moved to the other route")
        else:
            worker = next(iter(self._running))
            if isinstance(worker, _ImageWorker):
                text = f"{_NAMES[worker.capture.task.name]} · {worker.position[0] - 1} of {worker.position[1]} done"
                note = "Pending images are cancelled, not moved to the other route"
            else:
                text, note = f"{_NAMES[worker.capture.task.name]} · {slide_language.bare_id(worker.capture.id_slug)}", ""
        return [RunningWork(text, self._route.label, self._holds_slot, self.stop, note)]

    def refusal(self, task: claude_tasks.Task, route: ai_profile.Route | None = None) -> str:
        """Why `task` cannot run on the active route (it has no implementation there, or the route is not ready),
        or "" when it can."""
        route = route or ai_profile.resolve(self._window.project, KINDS[task.name])
        if route.route == ai_profile.CLAUDE_CODE:
            return ""
        if task not in PROVIDER_TASKS:
            return resolver.not_offered(route, _NAMES[task.name], "It runs on Cloud · Claude Code: switch the route to use it.")
        return resolver.problem(self._window.project, route)

    def start(self, task: claude_tasks.Task, paths: tuple[Path, ...] = ()) -> None:
        """Run `task` on the slide in the Source view, or for a deck bubble on its slides `paths`, unless one is
        running, the active route cannot run it (the status line says why) or it no longer fits."""
        if self.busy:
            return
        project = self._window.project
        route = ai_profile.resolve(project, KINDS[task.name])
        if reason := self.refusal(task, route):
            self.status.emit(reason, "warning")
            return
        if not confirm_if_new(self._window, project, route, "the slide text and images this task works on"):
            self.status.emit("Nothing was sent: using the cloud was not confirmed.", "warning")
            return
        if route.is_local and not self._window.try_start_ollama_task(_NAMES[task.name].lower()):
            return
        self._route, self._holds_slot = route, route.is_local
        self._cancel = threading.Event()
        self._started = time.monotonic()
        self.unapplied = self.report = ""
        if paths and task in BATCH_TASKS:
            self._batch = _Batch(task, deque(_Item(task, path) for path in paths), len(paths),
                                 limit=WORKERS if route.route == ai_profile.CLAUDE_CODE else 1)
            self.busy_changed.emit(True)
            self._ticker.start()
            self._tick()
            self._pump()
            return
        if task is claude_tasks.SUMMARISE:
            capture = _capture_summary(self._window, paths)
        elif task in (claude_images.DESCRIBE, claude_images.TRANSLATE):
            capture = _capture_images(self._window, task, paths)
        else:
            capture = _capture(self._window, task, _focus(self._window))
        if capture is None:
            self._release()
            self.status.emit("That no longer fits this slide.", "warning")
            return
        self._launch(capture)
        self.busy_changed.emit(True)
        self._tick()
        self._ticker.start()

    def _release(self) -> None:
        """The run is over: give the Ollama slot back and forget its providers."""
        self._providers = []
        if self._holds_slot:
            self._holds_slot = False
            self._window.end_ollama_task()

    def _launch(self, capture: _Capture | _ImageCapture, item: _Item | None = None) -> None:
        if isinstance(capture, _ImageCapture):
            backend = self._image_backend(capture.task)
            self._providers.append(backend.provider)
            worker = _ImageWorker(self._window.project, capture, backend, self._cancel)
        else:
            worker = _Worker(capture, self._text_task(capture))
        worker.done.connect(self._on_done)
        self._running[worker] = item
        background.start_detached(worker)

    def _image_backend(self, task: claude_tasks.Task):
        """What describes or translates images on the captured route."""
        ctx, route, describe = self._window.project, self._route, task is claude_images.DESCRIBE
        if route.route == ai_profile.CLAUDE_CODE:
            return (claude_images.ClaudeDraftBackend if describe else claude_images.ClaudeTranslationBackend)(
                ctx, self._claude, route.model, route.effort, self._cancel)
        return (resolver.draft_backend if describe else resolver.translation_backend)(ctx, route)

    def _text_task(self, capture: _Capture) -> Callable[[], Outcome]:
        """The call of a worker that runs `capture` on the captured route."""
        ctx, route, cancel = self._window.project, self._route, self._cancel
        if route.route == ai_profile.CLAUDE_CODE:
            return lambda: claude_runner.run_task(ctx, self._claude, capture.task, capture.sent, capture.request,
                                                  route.model, route.effort, cancel=cancel)
        provider = resolver.provider_for(ctx, route)
        self._providers.append(provider)
        return lambda: _translate_on_provider(ctx, provider, capture, cancel)

    def stop(self) -> None:
        self._cancel.set()
        for provider in self._providers:
            provider.abort()

    def shutdown(self) -> None:
        """The view is going away: end the processes; their outcomes are not looked at."""
        self._ticker.stop()
        self.stop()
        running, self._running, self._batch = self._running, {}, None
        for worker in running:
            background.stop_worker(worker)
        self._release()

    def _tick(self) -> None:
        seconds = round(time.monotonic() - self._started)
        if (batch := self._batch) is not None:
            parts = [f"{_VERBS[batch.task.name]} {DECK_LABEL} … {len(batch.lines)}/{batch.total}",
                     *([f"{batch.failed} failed"] if batch.failed else []), f"{seconds} s", *([batch.note] if batch.note else [])]
            self.status.emit(" · ".join(parts), "muted")
            return
        worker = next(iter(self._running))
        if isinstance(worker, _ImageWorker):
            self.status.emit(f"{_VERBS[worker.capture.task.name]} images of {worker.capture.label} … "
                             f"{worker.position[0]}/{worker.position[1]} · {seconds} s", "muted")
        else:
            self.status.emit(f"{_VERBS[worker.capture.task.name]} {slide_language.bare_id(worker.capture.id_slug)}"
                             f" … {seconds} s", "muted")

    def _on_done(self, worker: _Worker | _ImageWorker, outcome) -> None:
        if worker not in self._running:        # the view was closed meanwhile
            return
        item = self._running.pop(worker)
        worker.wait()
        worker.deleteLater()
        if item is not None:
            self._settle(worker.capture, item, outcome)
            self._pump()
            return
        self._ticker.stop()
        self._release()
        if isinstance(worker, _ImageWorker):
            report = self._images_report(worker.capture.task, outcome)
            self._window.side_panels.refresh()         # shows the drafts that were stored
        else:
            report = self._result(worker.capture, outcome)
        self.busy_changed.emit(False)          # after the change: the bubbles look at the slide as it is now
        self.status.emit(*report)

    def _result(self, capture: _Capture, outcome: Outcome) -> tuple[str, str]:
        """(status text, tone) of an outcome; a result is applied here."""
        if outcome.status == DONE:
            return self._apply(capture, outcome)
        return {CANCELLED: ("Cancelled", "muted"), NOTHING: ("Nothing to change", "muted")}.get(
            outcome.status, (outcome.message, "error"))

    # -- batches -----------------------------------------------------------------------------------------

    def _settle(self, capture: _Capture, item: _Item, outcome: Outcome) -> None:
        """Note what became of a batch item, applying its result; or, after a rate limit, put it back."""
        batch = self._batch
        limit = claude_runner.limit_kind(outcome.message) if outcome.status == FAILED else ""
        if limit == claude_runner.RATE_LIMIT and not item.retried:
            item.retried, batch.limit, batch.note = True, 1, SLOWED
            batch.queue.appendleft(item)
            return
        if limit == claude_runner.USAGE_LIMIT:
            batch.reason = outcome.message
            self._cancel.set()
        text, tone = self._result(capture, outcome)
        batch.lines.append(f"{capture.id_slug}: {text}")
        batch.applied += tone == "ok"
        batch.failed += tone in ("warning", "error")

    def _pump(self) -> None:
        """Start the next slides while there is room for a process, each captured now; end the batch when
        nothing is running and nothing will start."""
        batch = self._batch
        while batch.queue and len(self._running) < batch.limit and not self._cancel.is_set():
            item = batch.queue.popleft()
            capture = _capture(self._window, item.task, _focus_at(self._window, item.path))
            if capture is None:
                batch.lines.append(f"{_id_slug(item.path)}: no longer fits")
            else:
                self._launch(capture, item)
        if not self._running:
            self._finish(batch)

    def _finish(self, batch: _Batch) -> None:
        self._ticker.stop()
        self._release()
        self._batch = None
        self.report = "\n".join(batch.lines)
        seconds = time.monotonic() - self._started
        counts = f"{batch.applied} applied" + (f", {batch.failed} failed" if batch.failed else "")
        if batch.reason:
            report = f"Stopped: {batch.reason} ({counts})", "error"
        elif self._cancel.is_set():
            report = f"Stopped after {seconds:.0f} s: {counts}", "muted"
        else:
            report = f"Done in {seconds:.0f} s: {counts}", "warning" if batch.failed else "ok"
        self.busy_changed.emit(False)
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
        if capture.task is claude_tasks.SUMMARISE:
            self.summary.emit(outcome.text)
            return f"Done in {outcome.elapsed_s:.1f} s", "ok"
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
        try:
            write_text(self._workspace, capture.path, capture.text, new,
                       kind="translation" if capture.task is claude_tasks.UPDATE_TRANSLATION else "edit",
                       source=capture.task.name)
        except ToolError:
            return None
        window = self._window
        centre = window.centre
        if (centre.path == capture.path and self._workspace.is_open(capture.path)
                and window.state.mode in ("preview", "split") and not _errors(window.project, new)):
            centre.preview.render_buffer()             # no mode switch, no question; else the preview offers it
        # a file on disk is shown again by the refresh of its write
        return f": {capture.id_slug} updated" if capture.task is claude_tasks.UPDATE_TRANSLATION else ""

    def _translate(self, capture: _Capture, translated: str) -> str | None:
        """Create the partner slide from `translated`, link it to the source and add it to the deck, and show it;
        None, with nothing created, if the source has changed or has a partner by now (another slide of the batch or
        the user made one). What to append to the status line."""
        window = self._window
        if window.centre.slide_text(capture.path) != capture.text or slide_language.translation_link(window.project, capture.id_slug):
            return None
        created = slide_add.create_translation(
            window.project, capture.id_slug, slide_add.slug_of(capture.id_slug), capture.language, translated.replace("\n", capture.eol))
        ai_review.mark(window.project, created.path, "translation", capture.task.name)
        self._workspace.review_changed()
        linked = slide_ids.with_translation_backreference(capture.text, capture.language, created.id_slug)
        note = f": {created.id_slug} created"
        try:
            write_text(self._workspace, capture.path, capture.text, linked,
                       kind="translation", source=capture.task.name)
        except ToolError as exc:
            note += f", not linked to {capture.id_slug} ({exc})"
        if not self._add_to_deck(capture, created.id_slug):
            note += ", not added to the deck"
        if self._batch is None:
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
            updated = deck_editor.insert_slide_call(deck.path, deck.text, call.line_end, call.indent, "slide", id_slug)
            ai_review.inserted_slides(window.project, deck.path, deck.text, updated, capture.task.name)
            self._workspace.review_changed()
        except (deck_editor.StaleFileError, ValueError, OSError):
            return False
        window.after_deck_edit(deck.path, f"Added \\slide{{{id_slug}}} to {deck.name}", previous_text=deck.text)
        return True
