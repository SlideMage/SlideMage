"""The state of a task card and what it says (workspace v6 handoff, sections 4 and 8). Pure: no Qt.

A task card is the host-managed run of one AI task on one slide: Generate, Review, Apply, Check preview, and the
ends it can come to (done, conflict, preview failed, stopped, failed, setup needed). The TaskRunner
(terminal/tasks.py) owns the card and moves it between phases; the view (task_card.py) shows what this module
says: the state line, the steps and the buttons of a phase.
"""
from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from pathlib import Path

from ...ai import ai_profile, claude_tasks

GENERATE, REVIEW, APPLY, CHECK = "generate", "review", "apply", "check_preview"
DONE, CONFLICT, PREVIEW_FAILED, STOPPED, FAILED, SETUP = "done", "conflict", "preview_failed", "stopped", "failed", "setup_needed"
STEPS = ((GENERATE, "Generate"), (REVIEW, "Review"), (APPLY, "Apply"), (CHECK, "Check preview"))
RUNNING = (GENERATE, APPLY, CHECK)         # a card in one of these phases is AI work under way
# What the pill in the assistant's header says about a card that was left with "Back to conversation".
PILL_WORDS = {GENERATE: "generating", REVIEW: "waiting for review", APPLY: "applying", CHECK: "checking preview",
              DONE: "done", CONFLICT: "conflict", PREVIEW_FAILED: "preview failed", STOPPED: "stopped",
              FAILED: "failed", SETUP: "setup needed"}
# Icon and tone of the state line.
LOOKS = {GENERATE: ("autorenew", "strong"), REVIEW: ("rate_review", "strong"), APPLY: ("save", "strong"),
         CHECK: ("autorenew", "strong"), DONE: ("check_circle", "ok"), CONFLICT: ("warning", "warning"),
         PREVIEW_FAILED: ("error", "error"), STOPPED: ("stop_circle", "muted"), FAILED: ("error", "error"),
         SETUP: ("cloud_off", "warning")}
_GENERATING = {  # the sentence of the Generate phase, by task: {id}, {src} and {dst} (language names)
    claude_tasks.TRANSLATE.name: "Translating {id} from {src} to {dst}. LaTeX commands, labels and the glossary are kept.",
    claude_tasks.UPDATE_TRANSLATION.name: "Updating the {dst} translation of {id} from the {src} slide. LaTeX commands, "
                                          "labels and the glossary are kept.",
    claude_tasks.FIX_LATEX.name: "Fixing the LaTeX errors of {id}. Only what the errors need is changed.",
    claude_tasks.PROOFREAD.name: "Proofreading {id}. The meaning, the LaTeX commands and the labels are kept.",
    claude_tasks.CONCISE.name: "Shortening {id}. The frame, reveal steps and version tags are kept.",
    claude_tasks.TITLE.name: "Looking for a better title for {id}. The rest of the slide is kept.",
    claude_tasks.NOTE.name: "Writing a speaker note for {id}. The slide itself is kept."}


@dataclass
class TaskCard:
    task: claude_tasks.Task
    title: str                         # what the user asked for: "Update DE translation"
    route: ai_profile.Route            # captured when the task started
    phase: str = GENERATE
    target: str = ""                   # the slide it was started on (its id), captured then
    target_title: str = ""
    focus: Path | None = None          # the file it was started on: Run again starts there
    file: str = ""                     # the file the change goes into
    language: str = ""                 # of a translation: the language it is written in ("DE")
    t0: float = 0.0                    # time.monotonic() at the start
    elapsed: int = 0                   # seconds, while it generates
    auto: bool = False                 # "Edit automatically": Review is skipped
    nothing: bool = False              # the model found nothing to change
    note: str = ""                     # the end's own message: why it failed, why it cannot run
    can_sign_in: bool = False          # a setup card that Sign in… helps
    before: str = ""                   # the proposal: what the file says now, and what it would say
    after: str = ""
    changed: int = 0                   # lines the change touches
    result_path: Path | None = None    # the file written, or the new slide
    warnings: list[str] = field(default_factory=list)   # of the new slide: what could not be done around it
    undoable: bool = False             # a backup or the editor's undo can take the change back
    where: str = ""                    # what Check preview renders: "1y8 · Instructor · DE"
    preview_skipped: bool = False      # Check preview was stopped
    preview_error: str = ""            # the first line of the compile error
    hidden: bool = False               # "Back to conversation": only the pill in the header shows it

    @property
    def running(self) -> bool:
        return self.phase in RUNNING

    @property
    def is_translation(self) -> bool:
        return self.task is claude_tasks.TRANSLATE

    @property
    def skipped(self) -> set[str]:
        """The steps that did not happen."""
        found = {REVIEW} if self.auto else set()
        if self.nothing:
            found |= {REVIEW, APPLY, CHECK}
        if self.preview_skipped:
            found.add(CHECK)
        return found

    @property
    def can_compare(self) -> bool:
        """Compare rendered fits a change to a slide that exists: not a new slide, not a proposal that changes nothing."""
        return bool(self.before) and self.after != self.before and not self.nothing

    @property
    def diff_title(self) -> str:
        return f"New {self.language} slide, translated from {self.file}" if self.is_translation else self.file


def other_language(code: str) -> str:
    return "DE" if code == "EN" else "EN"


def changed_lines(before: str, after: str) -> int:
    """How many lines of `before` the change touches (an added or removed line counts too)."""
    old, new = before.splitlines(), after.splitlines()
    return sum(max(i2 - i1, j2 - j1) for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, old, new).get_opcodes()
               if tag != "equal")


def first_error(log: str) -> str:
    """The first error of a compile log's tail, as a line: "Undefined control sequence on line 9"."""
    lines = [line.strip() for line in log.splitlines() if line.strip()]
    error = next((line for line in lines if line.startswith("!")), "")
    if not error:
        return lines[0] if lines else "the render failed"
    number = next((line[2:].split()[0] for line in lines if line.startswith("l.") and line[2:3].isdigit()), "")
    return error.lstrip("! ").rstrip(".") + (f" on line {number}" if number else "")


# -- what a phase says ---------------------------------------------------------------------

def state_text(card: TaskCard) -> str:
    """The state line of the card's phase (the handoff's table)."""
    names = claude_tasks.LANGUAGE_NAMES
    source = names.get(other_language(card.language), card.language)
    target = names.get(card.language, card.language)
    phase, file = card.phase, card.file
    if phase == GENERATE:
        return _GENERATING[card.task.name].format(id=card.target, src=source, dst=target)
    if phase == REVIEW:
        what = f"translation of {card.target} into {target}, as a new slide" if card.is_translation else f"change to {file}"
        return f"Proposed {what}. Nothing is written yet."
    if phase == APPLY:
        return (f"Creating the {target} slide." if card.is_translation else f"Writing {file}.") + " This step cannot be interrupted."
    if phase == CHECK:
        return f"Changes applied. Rendering {card.where}. The old preview is marked as older."
    if phase == DONE:
        return _done_text(card, source)
    if phase == CONFLICT:
        return f"{card.target} changed while this task ran. The proposal is kept but not applied."
    if phase == PREVIEW_FAILED:
        return f"Changes applied to {card.result_path.name}. The preview failed: {card.preview_error}. Nothing was rolled back."
    if phase == STOPPED:
        return card.note or "Stopped. Nothing was changed."
    if phase == SETUP:
        return f"{card.note} The slide is unchanged."
    return card.note


def _done_text(card: TaskCard, source: str) -> str:
    if card.nothing:
        return f"Nothing to change in {card.target}. Nothing was written."
    name = card.result_path.name
    if card.is_translation:
        links = f"It stays linked to the {source} slide." if not card.warnings else f"It is not complete: {'; '.join(card.warnings)}."
        text = f"Created {name}. {links}"
    elif card.task is claude_tasks.UPDATE_TRANSLATION:
        text = f"Updated {name}. It stays linked to the {source} slide."
    else:
        text = f"Changed {card.changed} line{'s' if card.changed != 1 else ''} in {name}."
    text += " The preview was not rendered because the task was stopped." if card.preview_skipped else " The preview is current."
    return ("Applied automatically (Edit automatically is on). " if card.auto else "") + text


STEP_WORDS = {"check_circle": "done", "radio_button_checked": "in progress", "radio_button_unchecked": "not started",
              "remove_circle_outline": "skipped", "warning": "needs attention", "error": "failed",
              "stop_circle": "stopped", "cloud_off": "setup needed"}      # what a step's icon says, for a screen reader


@dataclass(frozen=True)
class Step:
    label: str
    icon: str
    tone: str
    note: str

    @property
    def word(self) -> str:
        return STEP_WORDS[self.icon]


def steps(card: TaskCard) -> list[Step]:
    """The four steps with where the card is in them."""
    phase = card.phase
    here = {GENERATE: 0, REVIEW: 1, APPLY: 2, CHECK: 3, DONE: 4, PREVIEW_FAILED: 3, CONFLICT: 1, STOPPED: 0, FAILED: 0, SETUP: 0}[phase]
    exceptions = {(CONFLICT, 1): ("warning", "warning", "slide changed"), (PREVIEW_FAILED, 3): ("error", "error", "failed"),
                  (STOPPED, 0): ("stop_circle", "muted", "stopped"), (FAILED, 0): ("error", "error", "failed"),
                  (SETUP, 0): ("cloud_off", "warning", "setup needed")}
    found = []
    for index, (key, label) in enumerate(STEPS):
        icon, tone, note = "radio_button_unchecked", "muted", ""
        if index < here:
            icon, tone = "check_circle", "ok"
        elif index == here and phase != DONE:
            icon, tone, note = "radio_button_checked", "strong", "now"
        if key in card.skipped:
            icon, tone, note = "remove_circle_outline", "muted", "skipped"
            if key == REVIEW and card.auto:
                note += " · Edit automatically"
            elif key == CHECK and card.preview_skipped:
                note = "not rendered"
        icon, tone, note = exceptions.get((phase, index), (icon, tone, note))
        found.append(Step(label, icon, tone, note))
    return found


def steps_text(card: TaskCard) -> str:
    """"Steps · 2 of 4 done"."""
    return "Steps · all done" if card.phase == DONE else f"Steps · {sum(s.icon == 'check_circle' for s in steps(card))} of 4 done"


# -- the buttons ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Action:
    key: str            # what the view does: stop, apply, reject, diff, view, undo, close, compare, rendered, again, source, log, sign_in
    label: str
    primary: bool = False


def actions(card: TaskCard) -> list[Action]:
    """The buttons of the card's phase, the primary first."""
    phase = card.phase
    rendered = [Action("rendered", "Compare rendered")] if card.can_compare else []
    if phase == GENERATE:
        return [Action("stop", "Stop")]
    if phase == REVIEW:
        return [Action("apply", "Apply", True), Action("reject", "Reject"), Action("diff", "View full diff"), *rendered]
    if phase == DONE:
        if card.nothing:
            return [Action("close", "Close", True)]
        view = f"View {card.language} version" if card.is_translation else "View change"
        return [Action("view", view, True), *([Action("undo", "Undo")] if card.undoable else []), *rendered,
                Action("close", "Close")]
    if phase == CONFLICT:
        return [Action("compare", "Compare with current", True), *rendered, Action("again", "Run again"), Action("close", "Dismiss")]
    if phase == PREVIEW_FAILED:
        return [Action("source", "Open source", True), Action("log", "View log"), Action("close", "Close")]
    if phase in (STOPPED, FAILED):
        return [Action("again", "Run again", True), Action("close", "Close")]
    if phase == SETUP:
        return [*([Action("sign_in", "Sign in…", True)] if card.can_sign_in else []), Action("again", "Run again"),
                Action("close", "Close")]
    return []
