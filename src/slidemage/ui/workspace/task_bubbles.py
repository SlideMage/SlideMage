# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The tasks the assistant header offers and what a click does (Claude Code tasks plan, step 2).

`bubbles(window)` says which tasks fit the slide in the Source view (and translation partner); `contextual` picks the
two the header shows. A click goes through TaskRunner:
`start` captures the task on the GUI thread (the slide's text as its buffer has it, the request), a worker thread
runs ai/claude_runner.run_task, and the outcome comes back to the GUI thread as a signal.
A task on one slide is shown as a task card (task_card_model.py, task_card.py), its phases the runner's: the
answer stops in Review with the proposed change, and Apply writes it, unless the chat's "Edit automatically" is on
(then Apply follows at once); a fix goes into the buffer (Ctrl+Z undoes it) or, for a closed file, onto disk with a
backup, the update of a translation changes the translation, wherever it is open, a translation creates the partner
slide, links it to the source (a change of the source's header) and puts its call after the source's in the deck.
Both writes happen only if the slide still has the captured text. Typing in the slide meanwhile makes the card a
conflict: nothing is written and the proposal is kept. After the write the card renders the slide through the
preview's shared RenderService (Check preview) and tells whether it compiled. A route that cannot run the task makes
the card ask for setup, nothing sent.
The image bubbles (describe, translate the descriptions) are different: an _ImageWorker works through the slide's
images one process after another and alt_draft's batch stores each draft as it is done (nothing of the slide
changes); the Images panel is shown again at the end, and the assistant shows what became of each image in the
results panel (`result`; pages/image_results.py) with Retry failed, which runs a new task over the failed images
only, on the route active then.
The deck bubbles (`deck_bubbles`, shown while the assistant's scope is Whole deck) run one of these tasks over the deck's
slides: a batch with up to WORKERS processes at a time. Each slide is captured when its turn comes, so what the user
typed meanwhile is in the request; every result is applied by `_on_done` on the GUI thread, one after the other,
whichever process finished first, so writes, ids and links never race. A rate-limit error drops the batch to one
process and gives that slide a second try; a usage-limit error ends it. A batch, the image tasks and the summary have
no card: their progress is the task row's status line, what became of each slide is in the "Show result" sheet.
"Describe images" is one image run over the deck's images, a summary one process whose answer is shown, never written.
One task or batch at a time; Stop and closing the window end its processes.

The tasks on a selection (Rewrite selection, Proofread selection; ai_tasks.REWRITE and PROOFREAD_SELECTION) work
on the text selected in the Source view's slide: `_capture_selection` takes the file, its text and the range when the
button is clicked (selection.py refuses a blank selection, a frozen version and a protected part), and the model gets
the range with some context around it. The proposal is the whole file with only the range replaced, so Review's diff
shows it in its place, and the write is the usual one: into the editor buffer (Ctrl+Z undoes it, the card's Undo does too)
if the file has changed in no way since, else the card ends in Conflict with the proposal kept. The header offers the
two tasks, in place of the slide tasks, while the Source view has a selection to work on.

Which backend runs a task is the active route's (ai_profile.resolve, captured when the task starts; the kind of
each task is KINDS). On Cloud · Claude Code every task is a `claude -p` process, as above. On Local and
Cloud · API only the tasks with an equivalent on a provider run. Each run holds its captured route lease:
 the image tasks (alt_draft's batch with a ModelBackend / ModelTranslationBackend),
Translate (slide_add.translate_body, its answer checked like Claude's) and Make readable (ai/provider_tasks.py: the
task's rules and schema as JSON on the provider, the same check and one repair round). Every other task is refused
with "not available on <route>", nothing sent and no other route or model used.
Make readable works from the findings of the last readability check of the slide (readability_check.KnownFindings,
the window's `readability_known`, valid for exactly the text that was measured): the header offers it, and the
palette and the findings panel start it, only for a slide with such findings, and its request carries the ones the
slide can fix (not those set by the template). The worker also measures the proposal as a draft
(readability_check.check_slide), so Review says "After the change: 0 errors, 1 warning (was 4 errors)"; text cut
off or overlapping after the change ends the card in Overflow (Undo, Run again). The Check preview renders the written
slide as usual; its numbers are those of the proposal, which is the text that was written. A card in Done with findings
left offers Run again, which sends the findings that remain.
"""
from __future__ import annotations

import re
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path

from PySide6.QtCore import QObject, QThread, QTimer, Signal

from ... import (ai_review, alt_blocks, alt_draft, alt_images, deck_editor, deck_language, deck_outline, latex_lint, readability,
                  readability_check, slide_add, slide_ids, slide_language, slide_source, slide_versioning)
from ...project import ProjectContext
from ...selection import Selection, SelectionError
from ...tex_source import masked_same_length
from ...ai import (ai_profile, routes, claude_images, claude_runner, tasks as ai_tasks, provider_tasks, resolver,
                    translation_style)
from ...ai.agent_types import EditApplied
from ...ai.tools.base import ToolError
from ...ai.tools.edits import write_text
from ...ai.claude_runner import CANCELLED, DONE, FAILED, NOTHING, Outcome
from ...batch_result import DRAFT, TRANSLATE, BatchResult
from .. import background
from ..ai_models import confirm_if_new
from ..pages.image_results import confirm as confirm_batch
from . import task_card_model as card_model
from .ai_work import RunningWork
from .menus import VIEW_LABELS
from .preview_view import render_context
from .task_card_model import TaskCard

CONFLICT = "The slide changed while Claude worked."
_VERBS = {ai_tasks.TRANSLATE.name: "Translating", ai_tasks.UPDATE_TRANSLATION.name: "Updating",
          ai_tasks.FIX_LATEX.name: "Fixing", claude_images.DESCRIBE.name: "Describing",
          claude_images.TRANSLATE.name: "Translating", ai_tasks.SUMMARISE.name: "Summarising",
          ai_tasks.READABLE.name: "Making readable", ai_tasks.REWRITE.name: "Rewriting",
          ai_tasks.PROOFREAD_SELECTION.name: "Proofreading"}
# What each task is, for the route's models (ai_profile.TASKS).
KINDS = {ai_tasks.TRANSLATE.name: ai_profile.TRANSLATION, ai_tasks.UPDATE_TRANSLATION.name: ai_profile.TRANSLATION,
         claude_images.TRANSLATE.name: ai_profile.TRANSLATION, claude_images.DESCRIBE.name: ai_profile.IMAGE_DESCRIPTION,
         **dict.fromkeys((ai_tasks.FIX_LATEX.name, ai_tasks.PROOFREAD.name, ai_tasks.CONCISE.name,
                          ai_tasks.TITLE.name, ai_tasks.NOTE.name, ai_tasks.SUMMARISE.name,
                          ai_tasks.READABLE.name, ai_tasks.REWRITE.name, ai_tasks.PROOFREAD_SELECTION.name),
                         ai_profile.FIXES)}
# The tasks that also run on a provider, as the Add slide sheet and the Images page do (see the docstring).
PROVIDER_TASKS = (ai_tasks.TRANSLATE, ai_tasks.READABLE, ai_tasks.REWRITE, ai_tasks.PROOFREAD_SELECTION,
                  claude_images.DESCRIBE, claude_images.TRANSLATE)
SELECTION_TASKS = (ai_tasks.REWRITE, ai_tasks.PROOFREAD_SELECTION)      # on the text selected in the Source view
# The tasks on one slide, shown as a task card (the others are batches, image runs and the summary).
CARD_TASKS = (ai_tasks.TRANSLATE, ai_tasks.UPDATE_TRANSLATION, ai_tasks.FIX_LATEX, ai_tasks.PROOFREAD,
              ai_tasks.CONCISE, ai_tasks.TITLE, ai_tasks.NOTE, ai_tasks.READABLE, *SELECTION_TASKS)
_NAMES = {ai_tasks.TRANSLATE.name: "Translating a slide", ai_tasks.UPDATE_TRANSLATION.name: "Updating a translation",
          ai_tasks.FIX_LATEX.name: "Fixing LaTeX errors", ai_tasks.PROOFREAD.name: "Proofreading",
          ai_tasks.CONCISE.name: "Making a slide more concise", ai_tasks.TITLE.name: "Retitling a slide",
          ai_tasks.NOTE.name: "Adding a speaker note", ai_tasks.SUMMARISE.name: "Summarising a deck",
          ai_tasks.READABLE.name: "Making a slide readable", ai_tasks.REWRITE.name: "Rewriting a selection",
          ai_tasks.PROOFREAD_SELECTION.name: "Proofreading a selection",
          claude_images.DESCRIBE.name: "Describing images", claude_images.TRANSLATE.name: "Translating image descriptions"}


def _runner_of(ctx: ProjectContext, route: ai_profile.Route):
    """The task runner of the route when it runs the tasks itself (Claude Code's `claude -p`), else None: core runs
    them on the route's provider (provider_tasks)."""
    found = routes.get(route.route)
    return found.task_runner(ctx, route) if found is not None else None


WORKERS = 2                            # processes at a time in a batch
DECK_LABEL = "the deck"
BATCH_TASKS = (ai_tasks.TRANSLATE, ai_tasks.UPDATE_TRANSLATION, ai_tasks.FIX_LATEX)
SLOWED = "Slowed to one worker: rate limit"
PROSE_WORDS = 10                       # words of running text that make a slide "have text" for the bubbles
_WORD_RE = re.compile(r"[^\W\d_]{3,}")
_MARKUP_RE = re.compile(r"\\(?:begin|end)\{[^}]*\}|\\[A-Za-z]+\*?|\$[^$]*\$|\\\(.*?\\\)")


@dataclass(frozen=True)
class Bubble:
    task: ai_tasks.Task
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
    task: ai_tasks.Task    # claude_images.DESCRIBE or TRANSLATE
    label: str                 # the slide's id, or DECK_LABEL: what the status line names
    images: list[str]          # store keys: what to describe, what to translate
    rows: list[alt_blocks.SlideRow]    # to describe: the slides, each image on the first one that shows it


@dataclass(frozen=True)
class _Capture:
    """A task as it was when its bubble was clicked: neither a focus change nor typing alters it."""
    task: ai_tasks.Task
    path: Path                 # the file the result goes into: the slide, or the translation to update
    id_slug: str
    text: str                  # the whole file: the freshness check and the header link work on it
    header: str                # what stands before `sent` in `text` and is not sent (an update keeps it)
    sent: str                  # what the model works on: `text`, or a body
    request: str
    language: str              # a translation's: the language to translate into, else ""
    eol: str                   # of the file: the line ends of a new slide
    deck_path: Path | None
    span: tuple[int, int] | None = None   # a selection's range in `text`: the task is on that part only
    instruction: str = ""      # of a rewrite: what it should do


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


def _text_offers(ctx: ProjectContext, focus: _Focus, link: slide_language.TranslationLink | None,
                 known: readability_check.KnownFindings | None = None) -> list[Bubble]:
    """The tasks on the text that fit the slide `focus` with its translation partner `link`; Make readable only when
    `known` has errors measured on the slide's text."""
    own = slide_language.own_language(focus.id_slug)
    found = []
    if link is None and own in slide_language.TRANSLATION_LANGUAGES:
        other = next(language for language in slide_language.TRANSLATION_LANGUAGES if language != own)
        found.append(Bubble(ai_tasks.TRANSLATE, f"Translate to {ai_tasks.LANGUAGE_NAMES[other]}"))
    if link is not None and link.outdated:
        language = own if link.is_translation else link.language
        found.append(Bubble(ai_tasks.UPDATE_TRANSLATION, f"Update {ai_tasks.LANGUAGE_NAMES[language]} translation"))
    if _errors(ctx, focus.text):
        found.append(Bubble(ai_tasks.FIX_LATEX, "Fix LaTeX errors"))
    if known is not None and known.has_errors(focus.path, focus.text):
        found.append(Bubble(ai_tasks.READABLE, "Make readable"))
    text = _has_text(focus.text)
    if text and own in ai_tasks.LANGUAGE_NAMES:
        found.append(Bubble(ai_tasks.PROOFREAD, "Proofread"))
    if text:
        found.append(Bubble(ai_tasks.CONCISE, "Make more concise"))
    if slide_source.title_span(focus.text) is not None:
        found.append(Bubble(ai_tasks.TITLE, "Better title"))
    if text and not slide_source.note_calls(focus.text):
        found.append(Bubble(ai_tasks.NOTE, "Add speaker notes"))
    return found


def _offers(ctx: ProjectContext, focus: _Focus, link: slide_language.TranslationLink | None,
            known: readability_check.KnownFindings | None = None) -> list[Bubble]:
    """The tasks that fit the slide `focus` with its translation partner `link`."""
    found = _text_offers(ctx, focus, link, known)
    describe, translate = _slide_images(ctx, focus.text)
    if describe:
        found.append(Bubble(claude_images.DESCRIBE, f"Describe images ({len(describe)})"))
    if translate:
        found.append(Bubble(claude_images.TRANSLATE, f"Translate image descriptions ({len(translate)})"))
    return found


def bubbles(window) -> list[Bubble]:
    """The tasks that fit the slide in the Source view right now."""
    focus = _focus(window)
    if focus is None:
        return []
    found = _offers(window.project, focus, slide_language.translation_link(window.project, focus.id_slug), window.readability_known)
    if selection_of(window) is not None:
        found = [Bubble(ai_tasks.REWRITE, "Rewrite selection"), Bubble(ai_tasks.PROOFREAD_SELECTION, "Proofread selection"),
                 *found]
    return found


def selection_of(window) -> Selection | None:
    """The text selected in the slide the Source view shows, when a task can work on it."""
    try:
        return window.centre.source.selection()
    except SelectionError:
        return None


def deck_slides(window) -> list[Path]:
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
    paths = deck_slides(window)
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
    return found + [Bubble(ai_tasks.SUMMARISE, "Summarise this deck", tuple(paths))]


# Which of the tasks that fit come first in the header (the prototype: the translation, then shortening).
PRIORITY = (ai_tasks.REWRITE, ai_tasks.PROOFREAD_SELECTION, ai_tasks.UPDATE_TRANSLATION, ai_tasks.TRANSLATE, ai_tasks.FIX_LATEX, ai_tasks.READABLE,
            ai_tasks.CONCISE, ai_tasks.PROOFREAD, ai_tasks.TITLE, ai_tasks.NOTE, claude_images.DESCRIBE,
            claude_images.TRANSLATE, ai_tasks.SUMMARISE)


# What `bubbles` can offer, as palette commands; Make readable has its own command, which checks the slide first, and
# the tasks on a selection theirs, which are there without a selection too.
SLIDE_TASKS = tuple(task for task in PRIORITY if task not in (ai_tasks.SUMMARISE, ai_tasks.READABLE, *SELECTION_TASKS))
DECK_TASKS = (*BATCH_TASKS, claude_images.DESCRIBE, ai_tasks.SUMMARISE)                # what `deck_bubbles` can


def contextual(found: list[Bubble], runner: "TaskRunner", limit: int = 2) -> list[Bubble]:
    """The `limit` most relevant of the tasks `found` that the active route can run (a refused one is not offered)."""
    runnable = [bubble for bubble in found if not runner.refusal(bubble.task)]
    return sorted(runnable, key=lambda bubble: PRIORITY.index(bubble.task))[:limit]


def _capture_selection(window, task: ai_tasks.Task, instruction: str) -> _Capture:
    """REWRITE (as `instruction` says) or PROOFREAD_SELECTION on the text selected in the Source view now; SelectionError
    says why there is none to work on."""
    chosen = window.centre.source.selection()
    path, text, start, end = chosen.path, chosen.text, chosen.start, chosen.end
    id_slug = _id_slug(path)
    if task is ai_tasks.REWRITE:
        request = ai_tasks.rewrite_request(text, start, end, instruction)
    else:
        request = ai_tasks.proofread_selection_request(
            text, start, end, slide_language.own_language(id_slug) or "EN", translation_style.de_address(window.project))
    deck = window.state.deck
    return _Capture(task, path, id_slug, text, "", text, request, "", slide_source.read_slide_source(path)[1],
                    deck.path if deck is not None else None, (start, end), instruction)


def _capture(window, task: ai_tasks.Task, focus: _Focus | None, instruction: str = "") -> _Capture | None:
    """The task on the slide `focus` (the selection, for a task on that), or None when it no longer fits it."""
    if task in SELECTION_TASKS:
        return _capture_selection(window, task, instruction)
    if focus is None:
        return None
    link = slide_language.translation_link(window.project, focus.id_slug)
    known = window.readability_known
    if not (known.fixable(focus.path, focus.text) if task is ai_tasks.READABLE
            else any(bubble.task is task for bubble in _offers(window.project, focus, link))):
        return None
    path, id_slug, text, header, sent, language = focus.path, focus.id_slug, focus.text, "", focus.text, ""
    own = slide_language.own_language(id_slug)
    style = (translation_style.de_address(window.project), translation_style.glossary(window.project))
    if task is ai_tasks.TRANSLATE:
        language = next(code for code in slide_language.TRANSLATION_LANGUAGES if code != own)
        sent = slide_versioning.strip_marker(slide_ids.body_of(text))
        request = ai_tasks.translate_request(sent, own, language, *style)
    elif task is ai_tasks.UPDATE_TRANSLATION:
        path, source_path = (focus.path, link.path) if link.is_translation else (link.path, focus.path)
        id_slug = _id_slug(path)
        text = focus.text if path == focus.path else window.centre.slide_text(path)
        source = focus.text if source_path == focus.path else window.centre.slide_text(source_path)
        header, sent = slide_ids.split_header(text)
        request = ai_tasks.update_request(
            slide_versioning.strip_marker(slide_ids.body_of(source)), sent,
            slide_language.own_language(_id_slug(source_path)), slide_language.own_language(id_slug), *style)
    elif task is ai_tasks.FIX_LATEX:
        request = ai_tasks.fix_request(text, _errors(window.project, text))
    elif task is ai_tasks.PROOFREAD:
        request = ai_tasks.proofread_request(text, own, style[0])
    elif task is ai_tasks.CONCISE:
        request = ai_tasks.concise_request(text)
    elif task is ai_tasks.READABLE:
        request = ai_tasks.readable_request(text, known.get(focus.path, text).to_dict(fixable_only=True))
    elif task is ai_tasks.TITLE:
        request = ai_tasks.title_request(text)
    else:
        request = ai_tasks.note_request(text)
    deck = window.state.deck
    return _Capture(task, path, id_slug, text, header, sent, request, language,
                    slide_source.read_slide_source(path)[1], deck.path if deck is not None else None)


def _capture_summary(window, paths) -> _Capture:
    """The summary of the deck whose slides are `paths`: the request carries their bodies as they are now."""
    bodies = [slide_versioning.strip_marker(slide_ids.body_of(window.centre.slide_text(path))) for path in paths]
    deck = window.state.deck.path
    return _Capture(ai_tasks.SUMMARISE, deck, DECK_LABEL, "", "", "", ai_tasks.summarise_request(bodies),
                    "", "", deck)


def _capture_images(window, task: ai_tasks.Task, paths) -> _ImageCapture | None:
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
            if outcome is None:
                outcome = Outcome(NOTHING, message="No result was returned.")
        except Exception as exc:  # a route must not strand the task when its runner raises
            outcome = Outcome(FAILED, message=str(exc))
        self.done.emit(self, outcome)


class _PreviewWorker(QThread):
    done = Signal(object, str)         # this worker, "" or why the render failed

    def __init__(self, render: Callable[[], object]) -> None:
        super().__init__()
        self._render = render

    def run(self) -> None:
        try:
            self._render()
        except Exception as exc:  # noqa: BLE001 -- whatever the render raised is the card's message
            self.done.emit(self, str(exc) or type(exc).__name__)
        else:
            self.done.emit(self, "")


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
        new, problems = ai_tasks.check(ctx, capture.task, capture.sent, {capture.task.answer: text})
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
        self.images = list(capture.images)             # the images the run goes over (the readable ones, to describe)

    def _progress(self, index: int, total: int, _item) -> None:
        self.position = (index, total)

    def run(self) -> None:
        capture = self.capture
        if capture.task is claude_images.DESCRIBE:
            entries = alt_images.load_store(self.ctx)
            jobs = [job for row in capture.rows for job in alt_draft.slide_jobs(self.ctx, row, entries)]
            self.images = [job.image for job in jobs]
            summary = alt_draft.run_batch(self.ctx, jobs, self.backend, on_progress=self._progress,
                                          should_stop=self.cancel.is_set)
        else:
            summary = alt_draft.run_translation_batch(self.ctx, capture.images, self.backend, on_progress=self._progress,
                                                      should_stop=self.cancel.is_set)
        self.done.emit(self, summary)


@dataclass
class _Item:
    task: ai_tasks.Task
    path: Path                 # the slide (current file) as the deck has it
    retried: bool = False      # put back once after a rate limit


@dataclass
class _Batch:
    """A deck bubble's run: the slides still to start and what became of the others."""
    task: ai_tasks.Task
    queue: deque[_Item]
    total: int
    limit: int = WORKERS       # processes at a time: 1 after a rate limit
    applied: int = 0
    failed: int = 0
    lines: list[str] = field(default_factory=list)    # per slide, as it was settled
    note: str = ""             # for the status line: SLOWED
    reason: str = ""           # why the batch ended by itself: the usage limit's message


class TaskRunner(QObject):
    status = Signal(str, str)          # the task row's text and tone ("muted", "ok", "warning", "error"): batches, images
    busy_changed = Signal(bool)
    summary = Signal(str)              # the summary of the deck, to show
    card_changed = Signal()            # the task card (`card`) appeared, moved on or went
    result_changed = Signal()          # the image results (`result`) appeared or went

    def __init__(self, window, workspace, parent: QObject | None = None, *, edit_auto: Callable[[], bool] = lambda: False) -> None:
        """`window` is the main window, `workspace` the GuiWorkspace that applies edits to its buffers and renders
        the preview. `edit_auto()` says whether the chat's "Edit automatically" is on."""
        super().__init__(parent)
        self._window, self._workspace, self._edit_auto = window, workspace, edit_auto
        self.card: TaskCard | None = None                  # the task on one slide, or what became of the last
        self.result: BatchResult | None = None             # what became of the images of the last image task
        self._result_capture: _ImageCapture | None = None  # that task, for Retry failed
        self._proposal: tuple[_Capture, str] | None = None  # of the card in Review or Conflict: the task, the new text
        self._applied: EditApplied | None = None           # of the card's write: what Undo puts back
        self._preview: _PreviewWorker | None = None        # Check preview
        self._preview_cancel = threading.Event()
        self._was_busy = False
        self._running: dict[_Worker | _ImageWorker, _Item | None] = {}    # with the batch item it works on
        self._batch: _Batch | None = None
        self._route: ai_profile.Route | None = None        # of the task or batch under way, captured at its start
        self._lease = None
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
        """AI work is under way: a process, a batch or a card that generates, writes or renders."""
        return bool(self._running) or self._batch is not None or (self.card is not None and self.card.running)

    @property
    def occupied(self) -> bool:
        """No other task starts: one is under way, or a proposal waits for the user's answer."""
        return self.busy or (self.card is not None and self.card.phase == card_model.REVIEW)

    def _notify_busy(self) -> None:
        if self.busy != self._was_busy:
            self._was_busy = self.busy
            self.busy_changed.emit(self.busy)

    def running_work(self) -> list[RunningWork]:
        """The task or batch under way, for the AI switch's busy popup (ai_work.py)."""
        if not self.busy:
            return []
        if (card := self.card) is not None and card.phase in (card_model.APPLY, card_model.CHECK):
            writing = card.phase == card_model.APPLY       # a write that has started finishes; a render can be cancelled
            return [RunningWork(f"{_NAMES[card.task.name]} · {card.target}", card.route.label, False,
                                None if writing else self.stop, "A file write that has started finishes" if writing else "")]
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
        return [RunningWork(text, self._route.label, self._route.is_local, self.stop, note)]

    def refusal(self, task: ai_tasks.Task, route: ai_profile.Route | None = None) -> str:
        """Why `task` cannot run on the active route (it has no implementation there, or the route is not ready),
        or "" when it can."""
        route = route or ai_profile.resolve(self._window.project, KINDS[task.name])
        if routes.get(route.route) is None:
            return resolver.problem(self._window.project, route)
        try:
            runner = _runner_of(self._window.project, route)
        except resolver.RouteUnavailable as exc:
            return str(exc)
        if runner is None and task not in PROVIDER_TASKS:
            return resolver.not_offered(route, _NAMES[task.name], "It needs a route that runs its own tasks: switch the route to use it.")
        return resolver.problem(self._window.project, route)

    def start(self, task: ai_tasks.Task, paths: tuple[Path, ...] = (), title: str = "", focus: Path | None = None,
              images: _ImageCapture | None = None, instruction: str = "") -> None:
        """Run `task` on the slide in the Source view (or on `focus`, a slide's current file) with a task card, or for
        a deck bubble on its slides `paths`, unless one is running, the active route cannot run it (a card asks for
        setup, the task row says why) or it no longer fits. `title` is what the card calls it. `images` is the capture
        of an image task to run as it is (Retry failed) instead of the slide's. `instruction` is what a rewrite should do."""
        if self.busy:
            return
        if (card := self.card) is not None and card.phase == card_model.REVIEW:
            self.show_card()                    # its proposal waits for an answer first
            return
        project = self._window.project
        route = ai_profile.resolve(project, KINDS[task.name])
        on_card = task in CARD_TASKS and not paths
        capture = None
        if on_card:
            try:
                capture = _capture(self._window, task, _focus_at(self._window, focus) if focus else _focus(self._window),
                                   instruction)
            except SelectionError as exc:
                self.status.emit(str(exc), "warning")
                return
            if capture is None:
                self.status.emit("That no longer fits this slide.", "warning")
                return
        if reason := self.refusal(task, route):
            self._refused(capture, route, title, reason, card_model.SETUP)
            return
        if not confirm_if_new(self._window, project, route, "the slide text and images this task works on"):
            self._refused(capture, route, title, "Nothing was sent: using the cloud was not confirmed.", card_model.STOPPED)
            return
        lease = self._window.acquire_route_task(route.route, _NAMES[task.name].lower())
        if lease is None:
            return
        self._route, self._lease = route, lease
        try:
            self._cancel = threading.Event()
            self._started = time.monotonic()
            self.unapplied = self.report = ""
            self._set_result(None)
            self._set_card(self._new_card(capture, route, title) if on_card else None)
            if on_card:
                self.status.emit("", "muted")
            elif paths and task in BATCH_TASKS:
                self._batch = _Batch(task, deque(_Item(task, path) for path in paths), len(paths),
                                     limit=WORKERS if _runner_of(project, route) is not None else 1)
                self._notify_busy()
                self._ticker.start()
                self._tick()
                self._pump()
                return
            elif task is ai_tasks.SUMMARISE:
                capture = _capture_summary(self._window, paths)
            else:
                capture = images or _capture_images(self._window, task, paths)
            if capture is None:
                self._release()
                self.status.emit("That no longer fits this slide.", "warning")
                return
            self._launch(capture)
            self._notify_busy()
            self._tick()
            self._ticker.start()
        except BaseException:
            self.shutdown()
            raise

    def _refused(self, capture: _Capture | None, route: ai_profile.Route, title: str, reason: str, phase: str) -> None:
        """The task will not start: a task on a slide says so on its card, the others in the task row."""
        if capture is None:
            self.status.emit(reason, "warning")
        else:
            self._set_card(self._new_card(capture, route, title, phase=phase, note=reason))

    def _new_card(self, capture: _Capture, route: ai_profile.Route, title: str, **fields) -> TaskCard:
        task = capture.task
        language = capture.language
        if task is ai_tasks.UPDATE_TRANSLATION:
            language = slide_language.own_language(capture.id_slug) or ""
        card = TaskCard(task, title or _NAMES[task.name], route, target=slide_language.bare_id(capture.id_slug),
                        target_title=deck_outline.slide_file_title(capture.path, capture.id_slug), focus=capture.path,
                        file=capture.path.name, language=language, t0=time.monotonic(),
                        instruction=capture.instruction, **fields)
        if task is ai_tasks.READABLE:
            card.readable = card_model.Readable(tuple(self._window.readability_known.fixable(capture.path, capture.text)))
        return card

    def _release(self) -> None:
        """The run is over: release its route and forget its providers."""
        self._providers = []
        lease, self._lease = self._lease, None
        if lease is not None:
            lease.release()

    def _launch(self, capture: _Capture | _ImageCapture, item: _Item | None = None) -> None:
        if isinstance(capture, _ImageCapture):
            backend = self._image_backend(capture.task)
            if (provider := getattr(backend, "provider", None)) is not None:
                self._providers.append(provider)
            worker = _ImageWorker(self._window.project, capture, backend, self._cancel)
        else:
            worker = _Worker(capture, self._text_task(capture))
        worker.done.connect(self._on_done)
        self._running[worker] = item
        background.start_detached(worker)

    def _image_backend(self, task: ai_tasks.Task):
        """What describes or translates images on the captured route."""
        ctx, route, describe = self._window.project, self._route, task is claude_images.DESCRIBE
        found = routes.get(route.route)
        if found is not None:
            backend = (found.draft_backend if describe else found.translation_backend)(ctx, route, self._cancel)
            if backend is not None:
                return backend
        return (resolver.draft_backend if describe else resolver.translation_backend)(ctx, route)

    def _text_task(self, capture: _Capture) -> Callable[[], Outcome]:
        """The call of a worker that runs `capture` on the captured route."""
        ctx, route, cancel = self._window.project, self._route, self._cancel
        if (runner := _runner_of(ctx, route)) is not None:
            run = lambda: runner(capture.task, capture.sent, capture.request, cancel, capture.span)  # noqa: E731
        else:
            provider = resolver.provider_for(ctx, route)
            self._providers.append(provider)
            if capture.task is ai_tasks.TRANSLATE:
                run = lambda: _translate_on_provider(ctx, provider, capture, cancel)       # noqa: E731
            else:
                run = lambda: provider_tasks.run_task(ctx, provider, capture.task, capture.sent, capture.request, cancel,  # noqa: E731
                                                      capture.span)
        return self._measuring(capture, run) if capture.task is ai_tasks.READABLE else run

    def _measuring(self, capture: _Capture, run: Callable[[], Outcome]) -> Callable[[], Outcome]:
        """`run`, then the text it proposes rendered as a draft and measured (Make readable): the Report, or why the
        draft could not be measured, in `Outcome.measured`."""
        window, cancel, context = self._window, self._cancel, render_context(self._window, capture.path)

        def measured() -> Outcome:
            outcome = run()
            if outcome is None or outcome.status != DONE or context is None:
                return outcome
            target, view, language = context
            try:
                outcome.measured = readability_check.check_slide(window.project, target, outcome.text, view, language,
                                                                 cancel, log=window.log)
            except Exception as exc:  # noqa: BLE001 -- why the draft could not be measured is the card's text
                if cancel.is_set():
                    outcome.status = CANCELLED
                outcome.measured = card_model.first_error(str(exc))
            return outcome

        return measured

    def stop(self) -> None:
        self._cancel.set()
        self._preview_cancel.set()
        for provider in self._providers:
            provider.abort()

    def shutdown(self) -> None:
        """The view is going away: end the processes; their outcomes are not looked at."""
        self._ticker.stop()
        self.stop()
        running, self._running, self._batch, self.card = self._running, {}, None, None
        preview, self._preview = self._preview, None
        lease, self._lease = self._lease, None
        pending = set(running)
        def ended(worker):
            pending.discard(worker)
            if not pending and lease is not None:
                lease.release()
        for worker in running:
            background.stop_worker(worker, on_done=lambda w=worker: ended(w))
        if not running and lease is not None:
            lease.release()
        if preview is not None:
            background.stop_worker(preview)
        self._providers = []

    def describe(self) -> str:
        """What is running, by verb and slide: "Updating 1y8", "Translating the deck"."""
        if (batch := self._batch) is not None:
            return f"{_VERBS[batch.task.name]} {DECK_LABEL}"
        worker = next(iter(self._running))
        capture = worker.capture
        if isinstance(worker, _ImageWorker):
            return f"{_VERBS[capture.task.name]} images of {capture.label}"
        return f"{_VERBS[capture.task.name]} {slide_language.bare_id(capture.id_slug)}"

    def _tick(self) -> None:
        if (card := self.card) is not None and card.phase == card_model.GENERATE:
            card.elapsed = round(time.monotonic() - card.t0)
            self.card_changed.emit()
            return
        seconds = round(time.monotonic() - self._started)
        what = self.describe()
        if (batch := self._batch) is not None:
            parts = [f"{what} … {len(batch.lines)}/{batch.total}",
                     *([f"{batch.failed} failed"] if batch.failed else []), f"{seconds} s", *([batch.note] if batch.note else [])]
            self.status.emit(" · ".join(parts), "muted")
            return
        worker = next(iter(self._running))
        if isinstance(worker, _ImageWorker):
            self.status.emit(f"{what} … {worker.position[0]}/{worker.position[1]} · {seconds} s", "muted")
        else:
            self.status.emit(f"{what} … {seconds} s", "muted")

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
            self._set_result(BatchResult.of(DRAFT if worker.capture.task is claude_images.DESCRIBE else TRANSLATE,
                                            self._route, worker.images, outcome.outcomes), worker.capture)
            self._window.side_panels.refresh()         # shows the drafts that were stored
        elif worker.capture.task in CARD_TASKS:
            self._generated(worker.capture, outcome)
            return
        else:
            report = self._result(worker.capture, outcome)
        self._notify_busy()                    # after the change: the bubbles look at the slide as it is now
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
        self._notify_busy()
        self.status.emit(*report)

    def _images_report(self, task: ai_tasks.Task, summary) -> tuple[str, str]:
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

    def _set_result(self, result: BatchResult | None, capture: _ImageCapture | None = None) -> None:
        self.result, self._result_capture = result, capture
        self.result_changed.emit()

    def close_result(self) -> None:
        self._set_result(None)

    def retry_failed(self) -> None:
        """Retry failed: the image task again over only the images that failed, on the route active now (asked about
        again, as the Images page does)."""
        result, capture = self.result, self._result_capture
        if result is None or capture is None or self.busy:
            return
        failed = result.failed
        route = ai_profile.resolve(self._window.project, KINDS[capture.task.name])
        if not self.refusal(capture.task, route) and not confirm_batch(
                self._window, result.kind, len(failed), self._window.project.root.name, route)[0]:
            return
        rows = [replace(row, images=[image for image in row.images if image in failed]) for row in capture.rows]
        self.start(capture.task, images=replace(capture, images=failed, rows=[row for row in rows if row.images]))

    # -- the task card ------------------------------------------------------------------------------------

    def _set_card(self, card: TaskCard | None) -> None:
        self.card, self._proposal, self._applied = card, None, None
        self.card_changed.emit()

    def _phase(self, card: TaskCard, phase: str, **fields) -> None:
        """Move `card` to `phase` (with the fields that go with it) and tell the views."""
        card.phase = phase
        for name, value in fields.items():
            setattr(card, name, value)
        self.card_changed.emit()
        self._notify_busy()

    def show_card(self) -> None:
        if self.card is not None and self.card.hidden:
            self.card.hidden = False
            self.card_changed.emit()

    def hide_card(self) -> None:
        """Back to conversation: a card that is still going on stays, as a pill; one that has ended goes."""
        if self.card is None:
            return
        if self.card.phase in (card_model.GENERATE, card_model.REVIEW, card_model.APPLY, card_model.CHECK):
            self.card.hidden = True
            self.card_changed.emit()
        else:
            self.close_card()

    def close_card(self) -> None:
        """Close, Dismiss, Reject: the card goes. A card that is still going on stays (Stop first)."""
        if self.card is None or self.card.running:
            return
        self._set_card(None)

    def _generated(self, capture: _Capture, outcome: Outcome) -> None:
        """The answer of a task on a slide: its proposal goes to Review, or, with Edit automatically, straight to
        Apply; no change, a stop and a failure end the card."""
        card = self.card
        if outcome.status == CANCELLED:
            self._phase(card, card_model.STOPPED)
        elif outcome.status == NOTHING:
            self._phase(card, card_model.DONE, nothing=True, remark=outcome.note)
        elif outcome.status != DONE:
            login = outcome.message == claude_runner.NOT_LOGGED_IN
            self._phase(card, card_model.SETUP if login else card_model.FAILED, can_sign_in=login,
                        note=outcome.message if login else f"{outcome.message.rstrip('.')}. Nothing was changed.")
        else:
            card.before, card.after = ("", outcome.text) if capture.language else (capture.text, capture.header + outcome.text)
            card.changed = card_model.changed_lines(card.before, card.after)
            card.remark = outcome.note
            if card.readable is not None:
                self._take_measure(capture, card, outcome)
            self._proposal = capture, outcome.text
            if not self._fresh(capture):
                self._phase(card, card_model.CONFLICT)
            elif self._edit_auto():
                card.auto = True
                self._write_soon(card)
            else:
                self._phase(card, card_model.REVIEW)

    def _take_measure(self, capture: _Capture, card: TaskCard, outcome: Outcome) -> None:
        """Make readable: the measurement of the proposal goes on the card, and, for the text it was made on, into the
        known findings (so Run again, and the header's button, start from what remains)."""
        measured = outcome.measured
        if isinstance(measured, readability.Report):
            self._window.readability_known.remember_slide(capture.path, capture.header + outcome.text, measured)
            card.readable.after = tuple(measured.slides[0].fixable) if measured.slides else ()
        else:
            card.readable.problem = measured or ""

    def apply(self) -> None:
        """Review's Apply."""
        if self.card is not None and self.card.phase == card_model.REVIEW:
            self._write_soon(self.card)

    def _write_soon(self, card: TaskCard) -> None:
        """The card shows the write, which happens a moment later (it cannot be interrupted)."""
        self._phase(card, card_model.APPLY)
        QTimer.singleShot(0, lambda: self._write_card(card))

    def _write_card(self, card: TaskCard) -> None:
        if self.card is not card or card.phase != card_model.APPLY:
            return                                          # closed meanwhile (the window shut down)
        capture, text = self._proposal
        try:
            written = self._fresh(capture) and self._commit(card, capture, text)
        except OSError as exc:
            self._phase(card, card_model.FAILED, note=f"{exc} Nothing was changed.")
            return
        if written:
            self._check_preview(card)
        else:
            self._phase(card, card_model.CONFLICT)

    def _commit(self, card: TaskCard, capture: _Capture, text: str) -> bool:
        """Write the proposal; False if the slide changed after all."""
        if capture.language:
            if (made := self._translate(capture, text)) is None:
                return False
            card.result_path, card.warnings = made[0].path, made[1]
        elif (applied := self._write(capture, text)) is None:
            return False
        else:
            card.result_path, card.undoable, self._applied = capture.path, True, applied
        return True

    def _check_preview(self, card: TaskCard) -> None:
        """Render the slide that was written, in the view and language being edited, through the preview's shared
        render service (the chat's render tool takes the same way); the card ends when it has compiled or not."""
        window, path = self._window, card.result_path
        if (context := render_context(window, path)) is None:   # not a slide file: nothing to render
            return self._phase(card, card_model.DONE, preview_skipped=True)
        target, view, language = context
        text = window.centre.slide_text(path)
        self._preview_cancel = cancel = threading.Event()
        self._preview = worker = _PreviewWorker(lambda: self._workspace.render_preview(target, text, view, language, cancel))
        worker.done.connect(self._on_preview)
        self._phase(card, card_model.CHECK, where=f"{slide_language.bare_id(path.name)} · {VIEW_LABELS[view]} · {language}")
        background.start_detached(worker)

    def _on_preview(self, worker: _PreviewWorker, error: str) -> None:
        if worker is not self._preview:                     # the view was closed meanwhile
            return
        self._preview = None
        worker.wait()
        worker.deleteLater()
        card = self.card
        end = card_model.OVERFLOW if card.readable is not None and card.readable.overflows else card_model.DONE
        if self._preview_cancel.is_set():
            self._phase(card, end, preview_skipped=True)
        elif error:
            self._phase(card, card_model.PREVIEW_FAILED, preview_error=card_model.first_error(error))
        else:
            self._phase(card, end)

    def show_result(self) -> None:
        """View DE version: the new slide in the centre column."""
        self._workspace.show_slide(self.card.result_path)

    def run_again(self) -> None:
        """The same task on the same slide, on the route that is active now."""
        card = self.card
        if card is not None and not card.running:
            self.start(card.task, title=card.title, focus=card.focus, instruction=card.instruction)

    def current_text(self) -> str:
        """What the card's proposal is compared with: the text the slide has now (a translation's source, the body that
        would be sent)."""
        capture, _text = self._proposal
        text = self._window.centre.slide_text(capture.path)
        return slide_versioning.strip_marker(slide_ids.body_of(text)) if capture.language else text

    def compare_texts(self) -> tuple[Path, str, str] | None:
        """What Compare rendered shows for the card: (the slide file, the text before, the text after), or None when
        the card has nothing to compare. In Conflict it is the slide as it is now against the proposal."""
        card = self.card
        if card is None or not card.can_compare:
            return None
        return self._proposal[0].path, self.current_text() if card.phase == card_model.CONFLICT else card.before, card.after

    def undo(self) -> str:
        """Take the written change back. "" when done, else why not (the file changed since)."""
        card = self.card
        if card is None or self._applied is None:
            return "Nothing to undo."
        problem = self._workspace.undo_in_buffer(self._applied)
        if not problem:
            self._set_card(None)
        return problem

    # -- applying ----------------------------------------------------------------------------------------

    def _apply(self, capture: _Capture, outcome: Outcome) -> tuple[str, str]:
        """Change the slide as the result of a batch item says, if it still has the captured text (a batch has no
        Review): (status text, tone)."""
        if capture.task is ai_tasks.SUMMARISE:
            self.summary.emit(outcome.text)
            return f"Done in {outcome.elapsed_s:.1f} s", "ok"
        try:
            if capture.language:
                created = self._translate(capture, outcome.text)
                note = None if created is None else f": {created[0].id_slug} created" + "".join(f", {w}" for w in created[1])
            elif (applied := self._write(capture, outcome.text)) is None:
                note = None
            else:
                self._refresh_preview(capture, applied.after)
                note = f": {capture.id_slug} updated" if capture.task is ai_tasks.UPDATE_TRANSLATION else ""
        except OSError as exc:
            return str(exc), "error"
        if note is None:
            self.unapplied = outcome.text
            return CONFLICT, "warning"
        return f"Done in {outcome.elapsed_s:.1f} s{note}", "ok"

    def _refresh_preview(self, capture: _Capture, new: str) -> None:
        """A batch wrote the slide that the Preview shows from the buffer: render it again (no mode switch, no
        question); otherwise the preview offers it."""
        window = self._window
        if (window.centre.path == capture.path and self._workspace.is_open(capture.path)
                and window.state.mode in ("preview", "split") and not _errors(window.project, new)):
            window.centre.preview.render_buffer()

    def _fresh(self, capture: _Capture) -> bool:
        """Whether the slide still has the text the task was started on (and a translation still has no partner). The
        "+" an autosave put on the version line meanwhile is no change."""
        window = self._window
        now = window.centre.slide_text(capture.path)
        return slide_versioning.without_plus(now) == slide_versioning.without_plus(capture.text) and not (
            capture.language and slide_language.translation_link(window.project, capture.id_slug))

    def _write(self, capture: _Capture, result: str) -> EditApplied | None:
        """Put `result` in place of the captured text (after the part of it that was not sent) and show it; None if
        the file has changed. What Undo puts back."""
        new = capture.header + result
        try:
            via_buffer = write_text(self._workspace, capture.path, capture.text, new,
                                    kind="translation" if capture.task is ai_tasks.UPDATE_TRANSLATION else "edit",
                                    source=capture.task.name)
        except ToolError:
            return None
        # a file on disk is shown again by the refresh of its write
        return EditApplied("", capture.path, capture.text, new, via_buffer)

    def _translate(self, capture: _Capture, translated: str) -> tuple[slide_add.CreatedSlide, list[str]] | None:
        """Create the partner slide from `translated`, link it to the source and add it to the deck that was open;
        None, with nothing created, if the source has changed or has a partner by now (another slide of the batch or
        the user made one). The new slide and what could not be done around it."""
        window = self._window
        if not self._fresh(capture):
            return None
        created = slide_add.create_translation(
            window.project, capture.id_slug, slide_add.slug_of(capture.id_slug), capture.language, translated.replace("\n", capture.eol))
        ai_review.mark(window.project, created.path, "translation", capture.task.name)
        self._workspace.review_changed()
        linked = slide_ids.with_translation_backreference(capture.text, capture.language, created.id_slug)
        warnings = []
        try:
            write_text(self._workspace, capture.path, capture.text, linked,
                       kind="translation", source=capture.task.name)
        except ToolError as exc:
            warnings.append(f"not linked to {capture.id_slug} ({exc})")
        if not self._add_to_deck(capture, created.id_slug):
            warnings.append("not added to the deck")
        return created, warnings

    def _add_to_deck(self, capture: _Capture, id_slug: str) -> bool:
        """Put the call of `id_slug` right after the source's first call in the deck that was open, called the way the
        source is (slide_add.translation_call). Whether it was."""
        window = self._window
        deck = next((d for d in window.decks if d.path == capture.deck_path), None)
        call = slide_add.translation_call(deck, capture.id_slug) if deck is not None else None
        if call is None:
            return False
        spec = slide_add.translation_spec(call)
        try:
            updated = deck_editor.insert_slide_call(deck.path, deck.text, call.line_end, call.indent, spec.macro, id_slug,
                                                    spec.version, spec.conditions, spec.steps)
            ai_review.inserted_slides(window.project, deck.path, deck.text, updated, capture.task.name)
            self._workspace.review_changed()
        except (deck_editor.StaleFileError, ValueError, OSError):
            return False
        window.after_deck_edit(deck.path, f"Added \\slide{{{id_slug}}} to {deck.name}", previous_text=deck.text)
        return True
