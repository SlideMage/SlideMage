# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""One image of the slide shown on the Images page: its picture and the fields that describe it.

Everything about an image (role, short and long description, source, the German counterparts)
lives once in media/alt-text.json (alt_images.py), shared by every slide that shows the image;
only the takeaway can differ per slide. The form shows English or German at a time (the page's
EN/DE switch); both sets of fields keep what was typed. What the form means for the store, which
fields were changed and how a finished translation merges in, is image_review's (FormEdit,
apply_translation); the form only holds the text, so a widget never decides what gets saved.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QSignalBlocker, Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QMessageBox, QPlainTextEdit, QVBoxLayout

from ... import alt_images, image_review
from ..ai_models import cloud_label
from ..kit import kit_qss as q
from ..kit.widgets import Button, Chip, Field, SegmentedControl, Surface, caption
from .image_preview import ImagePreview

ROLES = ((alt_images.ROLE_INFORMATIVE, "Informative"), (alt_images.ROLE_DECORATIVE, "Decorative"))
# Chip tone of an alt_images state.
STATE_TONES = {alt_images.STATE_NONE: "error", alt_images.STATE_DRAFT: "info",
               alt_images.STATE_STALE: "warning", alt_images.STATE_REVIEWED: "ok"}
# Chip tone of the review state of the source (alt_images.SOURCE_LABELS has the texts).
SOURCE_TONES = {alt_images.SOURCE_TO_REVIEW: "warning", alt_images.SOURCE_REVIEWED: "ok"}
STATE_TEXT = {alt_images.STATE_NONE: "No description", alt_images.STATE_DRAFT: "Saved, not reviewed",
              alt_images.STATE_STALE: "Needs re-check", alt_images.STATE_REVIEWED: "Reviewed"}
TRANSLATION_TEXT = {alt_images.STATE_NONE: "not translated yet",
                    alt_images.STATE_STALE: "stale: the English text was edited since the translation",
                    alt_images.STATE_REVIEWED: "matches the current English text"}
DECORATIVE_NOTE = ("Decorative: no description needed. It is marked as a PDF artifact and noted in one line "
                   "in the transcript. The source is still printed.")
SOURCE_HELP = ("Feeds the automatic \"Image source(s):\" footnote. For an AI-generated image write: AI-generated -- "
               "<engine> <version>, prompt: ``<prompt exactly as entered>''. Any other image just gets its "
               "ordinary credit (e.g. Own illustration.).")


def review_refused(parent, images: list[tuple[str, str, str]]) -> bool:
    """Warn and return True when an image of `images` ((reference, role, long description) as typed) is
    informative without a long description: it cannot be marked reviewed. Shared by the Images page and
    the inspector's panel."""
    missing = [reference for reference, role, long in images if image_review.needs_long_description(role, long)]
    if missing:
        QMessageBox.warning(
            parent, "Nothing to review yet",
            "These images are marked informative but have no long description yet:\n\n" + "\n".join(missing)
            + "\n\nEither write one, or set the role to decorative.")
    return bool(missing)


# (key, label, tooltip, height, placeholder) of the source field of each language; the side panel's
# Image descriptions shows the same ones.
SOURCE_SPECS = {
    "source": ("source", "Source (citation or attribution)", "", 48, "e.g. Own illustration, data from …"),
    "source_de": ("source_de", "Quelle (source_de; leave blank to use the English source)", "", 48, ""),
}


def labelled_edit(spec: tuple[str, str, str, int, str], value: str) -> tuple[QPlainTextEdit, Field]:
    """The text box of a field `spec` showing `value`, and the labelled field around it."""
    _key, label, tip, height, placeholder = spec
    edit = QPlainTextEdit(value)
    edit.setFixedHeight(height)
    edit.setPlaceholderText(placeholder)
    edit.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)   # the text wraps
    field = Field(label, edit)
    field.setToolTip(tip)
    return edit, field


class SourceStatus(Surface):
    """Under a source field: whether the citation (both languages) is to review or reviewed, and the
    button that confirms it. The form that holds it saves nothing: `review_clicked` is its to handle."""

    review_clicked = Signal()

    def __init__(self) -> None:
        super().__init__()
        line = QHBoxLayout(self)
        line.setContentsMargins(0, 0, 0, 0)
        line.setSpacing(8)
        self.chip = Chip("", "neutral")
        self.button = Button("Mark reviewed", "ghost", compact=True)
        self.button.setAccessibleName("Mark source reviewed")
        self.button.clicked.connect(self.review_clicked)
        line.addWidget(self.chip)
        line.addWidget(self.button)
        line.addStretch(1)

    def show_state(self, stored: str, typed: tuple[str, str], baseline: tuple[str, str]) -> None:
        """`stored` is alt_images.source_state() of the entry; `typed` and `baseline` are the (source, source_de)
        in the boxes and as they were shown. A citation changed in the boxes is to review once saved, and
        cannot be marked reviewed before that."""
        pending = typed != baseline
        state = (alt_images.SOURCE_TO_REVIEW if any(typed) else "") if pending else stored
        self.setVisible(bool(state))
        self.chip.set_text(alt_images.SOURCE_LABELS.get(state, ""))
        self.chip.set_tone(SOURCE_TONES.get(state, "neutral"))
        self.button.setVisible(state == alt_images.SOURCE_TO_REVIEW)
        self.button.setEnabled(not pending)
        self.button.setToolTip("Save the change first." if pending else
                               "Confirm the citation, in both languages, as it stands.")


# The fields of each language, in the order they are shown.
ENGLISH = (
    ("short", "Short description (alt text)", "One locating sentence; goes into the PDF. Shared by every slide "
     "using this image.", 64, "What a sighted reader takes from the image, in one or two sentences"),
    ("long", "Long description", "Structured; goes into the transcript. Shared by every slide using this image.",
     190, "Values, axes, structure"),
    ("takeaway", "Takeaway (why this image is on this slide)", "", 64, "What the slide wants the reader to conclude"),
    SOURCE_SPECS["source"],
)
GERMAN = (
    ("short_de", "Kurzbeschreibung", "", 64, "Not translated yet"),
    ("long_de", "Langbeschreibung", "", 190, "Not translated yet"),
    ("takeaway_de", "Erkenntnis (takeaway_de)", "", 64, "Not translated yet"),
    SOURCE_SPECS["source_de"],
)


class ImageForm(Surface):
    edited = Signal()
    source_reviewed = Signal()               # the citation was marked reviewed (and stored)
    replace_clicked = Signal(object)         # this form
    tune_clicked = Signal(object)
    translate_clicked = Signal(object, bool)  # this form, whether to save the slide first

    def __init__(self, app, reference: str, entry: alt_images.ImageEntry, slide_id: str, slide_hash: str) -> None:
        super().__init__()
        self.setObjectName(q.PANEL_ROW)   # a hairline under the form
        self.app = app
        self.reference, self.slide_id = reference, slide_id
        self.entry = entry
        # Values as the form was first shown. `entry` itself is refreshed by "Set as default", so it
        # cannot serve as the conflict baseline of the other fields at the next save.
        self.baseline = image_review.form_baseline(entry, slide_id)
        self.baseline_en_hash = alt_images.en_text_hash(entry)
        self.provenance: Optional[dict] = None   # of a translation applied to the form
        self.translating = False   # a translation of this form is under way
        self.busy = False          # the page runs a job: no second one is started from here
        self.can_translate = True  # a translation model is available
        self._asked: Optional[tuple[dict[str, str], tuple[str, str, str]]] = None   # what a request was sent from
        self.fields: dict[str, QPlainTextEdit] = {}
        self._groups: dict[str, Surface] = {}
        self._source_status: list[SourceStatus] = []   # one under the source field of each language

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 18)
        layout.setSpacing(10)
        head = QHBoxLayout()
        head.setSpacing(10)
        name = QLabel(reference)
        name.setObjectName(q.PANEL_MONO)
        name.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        head.addWidget(name, 1)
        self.state_chip = Chip("", "neutral")
        self._state = alt_images.slide_use_state(entry, slide_id, slide_hash)     # of the stored description
        head.addWidget(self.state_chip)
        self.tune_button = Button("Tune prompt…", "ghost", compact=True)
        self.tune_button.setToolTip("Draft this image with an editable prompt until it reads right. Nothing is "
                                    "written until you accept.")
        self.tune_button.clicked.connect(lambda: self.tune_clicked.emit(self))
        head.addWidget(self.tune_button)
        if not entry.is_tikz:   # a drawn illustration has no file to swap
            replace = Button("Replace image…", "secondary", compact=True)
            replace.setToolTip("Pick another image file, copy it into media/ under a new name and point this slide "
                               "(and optionally every other slide using this image) at it.")
            replace.clicked.connect(lambda: self.replace_clicked.emit(self))
            head.addWidget(replace)
        layout.addLayout(head)
        others = sorted(sid for sid in entry.used_on if sid != slide_id)
        if others:
            shared = caption(f"Also used on: {', '.join(others)}. Editing the description here changes it there too.",
                             "warning")
            layout.addWidget(shared)
        layout.addWidget(ImagePreview(app.project, reference, app.log))

        role_line = QHBoxLayout()
        self.roles = SegmentedControl(ROLES, current=entry.role)
        self.roles.changed.connect(self._on_role)
        role_line.addWidget(self.roles)
        role_line.addStretch(1)
        layout.addLayout(role_line)
        self.decorative_note = caption(DECORATIVE_NOTE)
        layout.addWidget(self.decorative_note)

        english_group = self._group(layout, "en", ENGLISH)
        self.german_group = self._group(layout, "de", GERMAN)
        english_group.layout().addWidget(caption(SOURCE_HELP))
        self.takeaway_state = caption("")
        self.default_button = Button("Set as default", "ghost", compact=True)
        self.default_button.setToolTip("Make this slide's takeaway the image's default: what any other slide "
                                       "using it that has not written its own shows. Saved at once, apart from Save.")
        self.default_button.clicked.connect(self._set_default)
        self.fields["takeaway"].parentWidget().layout().addWidget(self._line(self.takeaway_state, self.default_button))
        self._build_translation_line()
        self.fields["short"].textChanged.connect(self._english_edited)
        self.fields["long"].textChanged.connect(self._english_edited)
        self.fields["takeaway"].textChanged.connect(self._refresh_takeaway_state)
        self.edited.connect(self._show_state)
        self.edited.connect(self._show_source_state)
        self._apply_role()
        self._show_state()
        self._show_source_state()
        self.set_language("en")

    # -- building -------------------------------------------------------------------------------

    @staticmethod
    def _line(*widgets) -> Surface:
        line = Surface()
        row = QHBoxLayout(line)
        row.setContentsMargins(0, 0, 0, 0)
        for index, widget in enumerate(widgets):
            row.addWidget(widget, 1 if index == 0 else 0)
        return line

    def _group(self, layout: QVBoxLayout, language: str, specs) -> Surface:
        group = Surface()
        column = QVBoxLayout(group)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(10)
        for spec in specs:
            key = spec[0]
            edit, field = labelled_edit(spec, self.baseline[key])
            edit.textChanged.connect(self.edited)   # connected after the text is set: showing is no edit
            column.addWidget(field)
            self.fields[key] = edit
            if key in SOURCE_SPECS:
                status = SourceStatus()
                status.review_clicked.connect(self._mark_source_reviewed)
                column.addWidget(status)
                self._source_status.append(status)
        layout.addWidget(group)
        self._groups[language] = group
        return group

    def _build_translation_line(self) -> None:
        self.translation_state = caption("")
        self.translate_button = Button("Translate", "secondary", compact=True)
        self.translate_button.setToolTip("Translate the English short, long and takeaway into German. It fills "
                                         "the fields below; nothing is saved until you save.")
        self.translate_button.clicked.connect(lambda: self.translate_clicked.emit(self, False))
        self.save_translate_button = Button("Save, then translate", "ghost", compact=True)
        self.save_translate_button.setToolTip("Save this slide's draft (every image on it), then translate this "
                                              "image's saved English text.")
        self.save_translate_button.clicked.connect(lambda: self.translate_clicked.emit(self, True))
        self.german_group.layout().insertWidget(0, self._line(self.translation_state, self.translate_button,
                                                        self.save_translate_button))
        self._show_translation_state(alt_images.translation_state(self.entry))
        self.refresh_route()

    # -- what the form holds --------------------------------------------------------------------

    @property
    def role(self) -> str:
        return self.roles.current() or alt_images.ROLE_INFORMATIVE

    def values(self) -> dict[str, str]:
        return {"role": self.role, **{key: edit.toPlainText().strip() for key, edit in self.fields.items()}}

    @property
    def changed(self) -> bool:
        return self.values() != self.baseline

    def english(self) -> tuple[str, str, str]:
        values = self.values()
        return values["short"], values["long"], values["takeaway"]

    def saved_english(self) -> tuple[str, str, str]:
        """The English text as the store had it when the form was shown (or last set a default)."""
        return self.entry.short, self.entry.long, self.entry.takeaway_for(self.slide_id)

    def form_edit(self) -> image_review.FormEdit:
        return image_review.FormEdit(self.reference, self.values(), self.baseline, self.baseline_en_hash,
                                     self.provenance)

    # -- showing --------------------------------------------------------------------------------

    def set_language(self, language: str) -> None:
        for key, group in self._groups.items():
            group.setVisible(key == language)

    def _show_source_state(self) -> None:
        typed = (self.fields["source"].toPlainText().strip(), self.fields["source_de"].toPlainText().strip())
        for status in self._source_status:
            status.show_state(alt_images.source_state(self.entry), typed,
                              (self.baseline["source"], self.baseline["source_de"]))

    def _mark_source_reviewed(self) -> None:
        entry = alt_images.mark_source_reviewed(self.app.project, self.reference)
        if entry is not None:
            self.refresh_entry(entry)
            self.source_reviewed.emit()

    def _show_state(self) -> None:
        """The chip says what is stored, or that this form differs from it."""
        if self.changed:
            self.state_chip.set_text("Changed, unsaved")
            self.state_chip.set_tone("muted")
        else:
            self.state_chip.set_text(STATE_TEXT[self._state])
            self.state_chip.set_tone(STATE_TONES[self._state])

    def set_availability(self, busy: bool, can_translate: bool) -> None:
        """The page runs a job (no second one from here) / has a model to translate with."""
        self.busy, self.can_translate = busy, can_translate
        self._apply_role()

    def refresh_entry(self, entry: alt_images.ImageEntry) -> None:
        """A worker wrote the store: take its entry as what is stored (what "Version on disk" translates)
        without touching the fields or the baseline the next save compares with."""
        self.entry = entry
        self._show_source_state()

    def rebase(self, entry: alt_images.ImageEntry, slide_hash: str) -> None:
        """Show what the store holds now (after a save, or when a worker wrote the image) and take
        it as the values the next save compares with."""
        self.entry = entry
        self.baseline = image_review.form_baseline(entry, self.slide_id)
        self.baseline_en_hash = alt_images.en_text_hash(entry)
        self.provenance = None
        for key, edit in self.fields.items():
            if edit.toPlainText().strip() != self.baseline[key]:
                with QSignalBlocker(edit):
                    edit.setPlainText(self.baseline[key])
        self.roles.set_current(entry.role)
        self._state = alt_images.slide_use_state(entry, self.slide_id, slide_hash)
        self._show_translation_state(alt_images.translation_state(entry))
        self._apply_role()
        self._show_state()
        self._show_source_state()

    def _on_role(self, _role: str) -> None:
        self._apply_role()
        self.edited.emit()

    def _apply_role(self) -> None:
        decorative = self.role == alt_images.ROLE_DECORATIVE
        self.decorative_note.setVisible(decorative)
        for key, edit in self.fields.items():
            if key not in ("source", "source_de"):   # the source is attribution, whatever the role
                edit.setEnabled(not decorative)
        can_translate = not decorative and self.can_translate and not self.busy and not self.translating
        self.translate_button.setEnabled(can_translate)
        self.save_translate_button.setEnabled(can_translate)
        self.tune_button.setEnabled(not self.busy)
        self._refresh_takeaway_state()

    def _show_translation_state(self, state: str) -> None:
        self.translation_state.setText("German: " + TRANSLATION_TEXT[state])

    def _english_edited(self) -> None:
        """The German no longer matches the short and long text typed (until a translation of it comes
        in): the two fields that, with the takeaway default, alt_images.en_text_hash() covers."""
        self._show_translation_state(alt_images.STATE_STALE)

    def _refresh_takeaway_state(self) -> None:
        current, default = self.fields["takeaway"].toPlainText().strip(), self.entry.takeaway_default
        self.default_button.setEnabled(bool(current) and self.role != alt_images.ROLE_DECORATIVE)
        self.takeaway_state.setText(("(using the default)" if default else "(no default set yet)") if current == default
                                    else "(overridden on this slide)")

    def _set_default(self) -> None:
        text = self.fields["takeaway"].toPlainText().strip()
        if not text:        # would clear the default of every slide that follows it
            return
        entry = alt_images.set_takeaway_default(self.app.project, self.reference, self.slide_id, text)
        if entry is None:
            return
        self.entry = entry
        # This acts on the store at once; the other fields' baselines stay as shown, so that what
        # workers wrote meanwhile is not mistaken for a human edit at the next save.
        self.baseline["takeaway"] = entry.takeaway_for(self.slide_id)
        self._refresh_takeaway_state()
        self.edited.emit()

    # -- translating ----------------------------------------------------------------------------

    def begin_translation(self, english: tuple[str, str, str]) -> None:
        """A request for the translation of `english` went out; fields typed from now on are kept."""
        self.provenance = None
        self._asked = ({key: self.fields[key].toPlainText() for key in image_review.GERMAN_FIELDS}, english)
        self.translating = True
        self.translate_button.setText("Translating…")
        self._apply_role()

    def refresh_route(self) -> None:
        """The buttons that send the text to the AI say "· cloud" while the AI switch is on Cloud."""
        project = self.app.project
        if not self.translating:
            self.translate_button.setText(cloud_label(project, "Translate"))
        self.save_translate_button.setText(cloud_label(project, "Save, then translate"))

    def end_translation(self, result) -> None:
        """Put a finished translation (alt_draft.TranslationResult) into the German fields."""
        asked_fields, asked_english = self._asked or ({}, self.english())
        self._asked, self.translating = None, False
        self.refresh_route()
        self._apply_role()
        if not result.ok:
            return
        fields = {key: self.fields[key].toPlainText() for key in image_review.GERMAN_FIELDS}
        applied = image_review.apply_translation(result, asked_fields or fields, asked_english, fields, self.english())
        for key, value in applied.fields.items():
            self.fields[key].setPlainText(value)
        self.provenance = applied.provenance
        self._show_translation_state(alt_images.STATE_REVIEWED if applied.in_sync else alt_images.STATE_STALE)
        self.edited.emit()
