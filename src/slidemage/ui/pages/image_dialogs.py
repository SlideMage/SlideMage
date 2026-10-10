"""The two sheets of the Images page: replacing an image, and tuning the prompt that drafts one."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtWidgets import QCheckBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QVBoxLayout, QWidget

from ... import alt_draft, image_review
from ...ai.providers import ChatProvider
from .. import background
from ..kit import kit_qss as q
from ..kit.widgets import Button, Field, ModalSheet, Page, caption
from .image_jobs import Job
from .image_preview import ImagePreview

NAMING_HELP = ("Name as <type>-<slug>[-cropped].<ext>, so the kind of image is obvious from the file name. "
               "Common type prefixes: chart-, photo-, screenshot-, midjourney-, chapter-logo-. Append -cropped "
               "to a cropped version of a plain source image (keep the uncropped original too).")


class ReplaceImageSheet(ModalSheet):
    """Pick another file for an image: its copy in media/ gets a name of its own, and the slides using
    the old image can be pointed at it too. The old file is never touched."""

    def __init__(self, parent: QWidget, reference: str, others: list[str]) -> None:
        super().__init__("Replace image", parent, width=560)
        self.source: Optional[Path] = None
        self._auto_name = ""     # the name suggested last: replaced when another file is chosen, a typed one is not
        old_name = reference.rsplit("/", 1)[-1]
        self._suggested = old_name.rsplit(".", 1)[0] if "." in old_name else old_name
        page = Page()
        choose = Button("Choose file…", "secondary", compact=True)
        choose.clicked.connect(self._choose)
        self.chosen = QLabel("No file chosen")
        self.chosen.setObjectName(q.PANEL_MONO)
        picker = QHBoxLayout()
        picker.addWidget(self.chosen, 1)
        picker.addWidget(choose)
        picker_row = QWidget()
        picker_row.setLayout(picker)
        picker.setContentsMargins(0, 0, 0, 0)
        page.body.addWidget(Field(f"Replacement for {reference}", picker_row))
        self.name_edit = QLineEdit()
        self.name_edit.setObjectName(q.INPUT)
        self.name_edit.textEdited.connect(lambda _text: self._validate())
        self.extension = QLabel("")
        self.extension.setObjectName(q.PANEL_MONO)
        name_row = QWidget()
        name_line = QHBoxLayout(name_row)
        name_line.setContentsMargins(0, 0, 0, 0)
        name_line.addWidget(self.name_edit, 1)
        name_line.addWidget(self.extension)
        page.body.addWidget(Field("Name of the copy in media/", name_row))
        page.body.addWidget(caption(NAMING_HELP))
        self.problem = caption("")
        page.body.addWidget(self.problem)
        self.on_others = QCheckBox(f"Replace it on the {len(others)} other slide(s) using it too: {', '.join(others)}")
        self.on_others.setVisible(bool(others))
        page.body.addWidget(self.on_others)
        self.add_tab("Replace image", page)
        self.add_button("Cancel", role="reject")
        self.replace_button = self.add_button("Replace", kind="primary", role="accept")
        self._validate()

    @property
    def new_name(self) -> str:
        return self.name_edit.text().strip() + self.extension.text()

    def _choose(self) -> None:
        picked, _filter = QFileDialog.getOpenFileName(
            self, "Choose replacement image", "", "Images (*.png *.jpg *.jpeg *.pdf *.eps);;All files (*.*)")
        if not picked:
            return
        self.source = Path(picked)
        self.chosen.setText(self.source.name)
        self.extension.setText(self.source.suffix.lower() or ".png")
        if self.name_edit.text() in ("", self._auto_name):
            self._auto_name = image_review.free_media_stem(self._suggested, self.extension.text())
            self.name_edit.setText(self._auto_name)
        self._validate()

    def _validate(self) -> None:
        problem = ""
        if self.source is not None:
            problem = image_review.media_name_problem(self.name_edit.text().strip())
            if not problem and image_review.media_destination(self.new_name).exists():
                problem = f"media/{self.new_name} already exists: pick another name (an image is never overwritten)."
        self.problem.setText(problem)
        self.problem.setProperty("tone", "error")
        self.problem.style().unpolish(self.problem)
        self.problem.style().polish(self.problem)
        self.replace_button.setEnabled(self.source is not None and not problem)


class PromptTuningSheet(ModalSheet):
    """Draft one image with an editable prompt, again and again until it reads right. The one
    drafting that is deliberately not durable: nothing reaches the store until the page writes the
    accepted draft. Prompt tuning fixes misreadings (a wrong axis maximum, a mistaken chart type); it
    does not fix what the model cannot resolve at all (ALT_TEXT_NOTES.md).

    `on_over` runs once nothing of the sheet is running any more (it gives the Ollama slot back)."""

    def __init__(self, app, reference: str, image_path: Path, context: alt_draft.SlideContext,
                 provider: ChatProvider, hint: str, on_over: Callable[[], None]) -> None:
        super().__init__(f"Tune the prompt: {reference}", app, width=1100)
        self.setMinimumHeight(700)
        self._image_path, self._context, self._provider, self._on_over = image_path, context, provider, on_over
        self._job: Optional[Job] = None
        self.result_draft: Optional[alt_draft.DraftResult] = None
        page = Page()
        columns = QHBoxLayout()
        columns.setSpacing(18)
        left = QVBoxLayout()
        left.addWidget(ImagePreview(reference, app.log, max_size=(520, 640)))
        left.addStretch(1)
        columns.addLayout(left, 1)
        right = QVBoxLayout()
        right.setSpacing(10)
        self.hint_edit = QPlainTextEdit(hint)
        self.hint_edit.setObjectName(q.INPUT)
        self.hint_edit.setFixedHeight(64)
        self.hint_edit.setPlaceholderText("e.g. the y-axis maximum is 6800, not 250")
        right.addWidget(Field("Hint for this image", self.hint_edit))
        right.addWidget(caption("A short correction, stored with the image and reused by later redrafts. This is the "
                                "lever that works: it reaches the model without disturbing the output format."))
        self.prompt_edit = QPlainTextEdit(alt_draft.effective_system_prompt())
        self.prompt_edit.setObjectName(q.INPUT)
        self.prompt_edit.setFixedHeight(200)
        right.addWidget(Field("System prompt (this run only)", self.prompt_edit))
        right.addWidget(caption("Editing it often makes the model abandon the required output format and answer in "
                                "prose; the hint above is the reliable lever.", "warning"))
        buttons = QHBoxLayout()
        self.draft_button = Button("Draft", "primary", compact=True)
        self.draft_button.clicked.connect(self._draft)
        reset = Button("Reset prompt", "secondary", compact=True)
        reset.clicked.connect(lambda: self.prompt_edit.setPlainText(alt_draft.effective_system_prompt()))
        buttons.addWidget(self.draft_button)
        buttons.addWidget(reset)
        buttons.addStretch(1)
        right.addLayout(buttons)
        self.output = QPlainTextEdit()
        self.output.setObjectName(q.INPUT)
        self.output.setReadOnly(True)
        self.output.setPlaceholderText("Nothing drafted yet.")
        right.addWidget(Field("Result", self.output), 1)
        columns.addLayout(right, 1)
        page.body.addLayout(columns)
        self.add_tab("Tune", page)
        self.add_button("Cancel", role="reject")
        self.accept_button = self.add_button("Accept draft", kind="primary", role="accept")
        self.accept_button.setEnabled(False)

    @property
    def hint(self) -> str:
        return self.hint_edit.toPlainText().strip()

    def _draft(self) -> None:
        if self._job is not None:
            return
        context = replace(self._context, hint=self.hint)
        backend = alt_draft.ModelBackend(self._provider, system_prompt=self.prompt_edit.toPlainText())
        self._job = job = Job("Tuning", self._provider, lambda _job: backend.draft(self._image_path, context))
        job.result.connect(self._on_result)
        self.draft_button.setEnabled(False)
        self.accept_button.setEnabled(False)
        self.draft_button.setText("Drafting…")
        self.output.setPlainText("Drafting…")
        job.start()

    def _on_result(self, job: Job, outcome: object) -> None:
        if job is not self._job:    # the sheet was closed meanwhile: nobody waits for this
            return
        self._job = None
        job.wait()
        job.deleteLater()
        self.draft_button.setEnabled(True)
        self.draft_button.setText("Draft again")
        if isinstance(outcome, Exception) or not outcome.ok:
            error = str(outcome) if isinstance(outcome, Exception) else f"after {outcome.elapsed_s:.0f}s\n\n{outcome.error}"
            self.output.setPlainText(f"FAILED {error}")
            return
        self.result_draft = outcome
        warning = ("\n\n*** A value table was removed automatically: its numbers looked interpolated rather than "
                   "measured. ***" if outcome.suspected_fabrication else "")
        self.output.setPlainText(
            f"[{outcome.elapsed_s:.0f}s · role suggestion: {outcome.role_suggestion or 'n/a'}]\n\n"
            f"SHORT\n{outcome.short}\n\nLONG\n{outcome.long}\n\nTAKEAWAY\n{outcome.takeaway}{warning}")
        self.accept_button.setEnabled(True)

    def done(self, result: int) -> None:
        """Closing the sheet ends a running draft: its thread must not outlive the sheet."""
        job, self._job = self._job, None
        if job is not None:
            background.stop_worker(job, self._provider.abort, on_done=self._on_over)
        else:
            self._on_over()
        super().done(result)
