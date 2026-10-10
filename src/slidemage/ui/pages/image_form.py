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
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPlainTextEdit, QVBoxLayout

from ... import alt_images, image_review
from ..kit import kit_qss as q
from ..kit.widgets import Button, Chip, Field, SegmentedControl, Surface, caption
from .image_preview import ImagePreview

ROLES = ((alt_images.ROLE_INFORMATIVE, "Informative"), (alt_images.ROLE_DECORATIVE, "Decorative"))
# Chip tone of an alt_images state.
STATE_TONES = {alt_images.STATE_NONE: "error", alt_images.STATE_DRAFT: "info",
               alt_images.STATE_STALE: "warning", alt_images.STATE_REVIEWED: "ok"}
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

# (key, label, tooltip, height, placeholder) of the fields of each language, in the order they are shown.
ENGLISH = (
    ("short", "Short description (alt text)", "One locating sentence; goes into the PDF. Shared by every slide "
     "using this image.", 64, "What a sighted reader takes from the image, in one or two sentences"),
    ("long", "Long description", "Structured; goes into the transcript. Shared by every slide using this image.",
     190, "Values, axes, structure"),
    ("takeaway", "Takeaway (why this image is on this slide)", "", 64, "What the slide wants the reader to conclude"),
    ("source", "Source (citation or attribution)", "", 48, "e.g. Own illustration, data from …"),
)
GERMAN = (
    ("short_de", "Kurzbeschreibung", "", 64, "Not translated yet"),
    ("long_de", "Langbeschreibung", "", 190, "Not translated yet"),
    ("takeaway_de", "Erkenntnis (takeaway_de)", "", 64, "Not translated yet"),
    ("source_de", "Quelle (source_de; leave blank to use the English source)", "", 48, ""),
)


class ImageForm(Surface):
    edited = Signal()
    replace_clicked = Signal(object)         # this form
    tune_clicked = Signal(object)
    translate_clicked = Signal(object, bool)  # this form, whether to save the slide first

    def __init__(self, app, reference: str, entry: alt_images.ImageEntry, slide_id: str, slide_hash: str) -> None:
        super().__init__()
        self.setObjectName(q.PANEL_ROW)   # a hairline under the form
        self.reference, self.slide_id = reference, slide_id
        self.entry = entry
        # Values as the form was first shown. `entry` itself is refreshed by "Set as default", so it
        # cannot serve as the conflict baseline of the other fields at the next save.
        self.baseline = image_review.form_baseline(entry, slide_id)
        self.baseline_en_hash = alt_images.en_text_hash(entry)
        self.provenance: Optional[dict] = None   # of a translation applied to the form
        self.translating = False   # a translation of this form is under way
        self.busy = False          # the page runs a job: no second one is started from here
        self._asked: Optional[tuple[dict[str, str], tuple[str, str, str]]] = None   # what a request was sent from
        self.fields: dict[str, QPlainTextEdit] = {}
        self._groups: dict[str, Surface] = {}

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
        self.set_state(alt_images.slide_use_state(entry, slide_id, slide_hash))
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
        layout.addWidget(ImagePreview(reference, app.log))

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
        self._refresh_takeaway_state()
        self._apply_role()
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
        for key, label, tip, height, placeholder in specs:
            edit = QPlainTextEdit(self.baseline[key])
            edit.setObjectName(q.INPUT)
            edit.setFixedHeight(height)
            edit.setPlaceholderText(placeholder)
            edit.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)   # the text wraps
            edit.textChanged.connect(self.edited)   # connected after the text is set: showing is no edit
            field = Field(label, edit)
            field.setToolTip(tip)
            column.addWidget(field)
            self.fields[key] = edit
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

    def set_state(self, state: str) -> None:
        self.state_chip.set_text(STATE_TEXT[state])
        self.state_chip.set_tone(STATE_TONES[state])

    def set_busy(self, busy: bool) -> None:
        self.busy = busy
        self._apply_role()

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
        self.set_state(alt_images.slide_use_state(entry, self.slide_id, slide_hash))
        self._show_translation_state(alt_images.translation_state(entry))
        self._refresh_takeaway_state()
        self._apply_role()

    def _on_role(self, _role: str) -> None:
        self.state_chip.set_text("Changed, unsaved")
        self.state_chip.set_tone("muted")
        self._apply_role()
        self.edited.emit()

    def _apply_role(self) -> None:
        decorative = self.role == alt_images.ROLE_DECORATIVE
        self.decorative_note.setVisible(decorative)
        for key, edit in self.fields.items():
            if key not in ("source", "source_de"):   # the source is attribution, whatever the role
                edit.setEnabled(not decorative)
        can_translate = not decorative and not self.busy and not self.translating
        self.translate_button.setEnabled(can_translate)
        self.save_translate_button.setEnabled(can_translate)
        self.tune_button.setEnabled(not self.busy)

    def _show_translation_state(self, state: str) -> None:
        self.translation_state.setText("German: " + TRANSLATION_TEXT[state])

    def _english_edited(self) -> None:
        """The German no longer matches the short and long text typed (until a translation of it comes
        in): the two fields that, with the takeaway default, alt_images.en_text_hash() covers."""
        self._show_translation_state(alt_images.STATE_STALE)

    def _refresh_takeaway_state(self) -> None:
        current, default = self.fields["takeaway"].toPlainText().strip(), self.entry.takeaway_default
        self.takeaway_state.setText(("(using the default)" if default else "(no default set yet)") if current == default
                                    else "(overridden on this slide)")

    def _set_default(self) -> None:
        text = self.fields["takeaway"].toPlainText().strip()
        entry = alt_images.set_takeaway_default(self.reference, self.slide_id, text)
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

    def end_translation(self, result) -> None:
        """Put a finished translation (alt_draft.TranslationResult) into the German fields."""
        asked_fields, asked_english = self._asked or ({}, self.english())
        self._asked, self.translating = None, False
        self.translate_button.setText("Translate")
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
