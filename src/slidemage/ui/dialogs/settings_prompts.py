"""The Prompts tab of the Settings sheet: the system prompts the AI tasks send, one page each --
image descriptions (alt_draft), slide rewrite (ai_draft) and translation (translation_prompts.py).
They are kept with the project (.slidemage/), not per deck.

Unlike the rest of Settings a prompt is saved by its own Save button, because a half-edited prompt
must not take effect (a model told to drop the required JSON or the protected-placeholder rule
misbehaves). Unsaved text is shown, and closing the sheet asks about it (`confirm_close`). A prompt
saved as it is by default is not stored (draft_prompts.set_custom_prompt), so a later change of the
default still reaches it.
"""
from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QLabel, QMessageBox, QPlainTextEdit, QSpinBox, QStackedWidget

from ... import ai_draft, alt_draft, draft_prompts
from ... import translation_prompts as tp
from ..kit.widgets import Button, Field, Page, SegmentedControl, caption, columns, row, set_property

IMAGE_NOTE = (
    "Sent as the system prompt of every Draft and Draft all. A model told to drop the required JSON "
    "output format stops working: try a change on one image with \"Tune prompt\" first.")
REWRITE_NOTE = (
    "Sent as the system prompt of \"AI draft\" slide rewrites. It must keep the instruction to reproduce "
    "every \"%%%PROTECTED_N%%%\" placeholder line verbatim: without it the model can edit what the "
    "feature protects (the slide's header comment, its \\setSlideVersion{} line and \\vbox to 0pt{...} "
    "overlays).")
TRANSLATION_NOTE = (
    "Used for the Images page's \"Translate\" and \"Translate all\" and for translating a slide. The "
    "prompt and the blank lines after it are sent as one message, followed by the text to translate. A "
    "model with an override of its own for the language pair uses that; any other uses the default.")
DEFAULT_CHOICE, NEW_CHOICE = "default", "new"


class _Editor(Page):
    """A note, a prompt's text, its state ("Unsaved changes") and the Reset and Save buttons."""

    def __init__(self, note: str, *, height: int) -> None:
        super().__init__()
        self.edit = QPlainTextEdit()
        self.edit.setMinimumHeight(height)
        self.status = caption("")
        self.reset_button = Button("Reset to default", compact=True)
        self.save_button = Button("Save", "primary", compact=True)
        self.save_button.setEnabled(False)
        self.body.addWidget(caption(note))
        self.body.addWidget(self.edit)
        self.buttons = row(self.status, self.reset_button, self.save_button)
        self.body.addWidget(self.buttons)

    def show_state(self, dirty: bool, error: str = "") -> None:
        self.status.setText(error or ("Unsaved changes" if dirty else ""))
        set_property(self.status, "tone", "error" if error else "")
        self.save_button.setEnabled(dirty)


class PromptPage(Page):
    """One prompt of draft_prompts: `default` is the program's own, which Reset restores (it is
    saved only with Save)."""

    def __init__(self, app, kind: str, default: str, note: str, what: str) -> None:
        super().__init__()
        self.app = app
        self.kind = kind
        self.default = default
        self.what = what
        self.editor = _Editor(note, height=200)
        self.body.addWidget(self.editor)
        self.body.addStretch(1)
        text = draft_prompts.get_custom_prompt(kind) or default
        self.editor.edit.setPlainText(text)
        self._saved = text.strip()
        self.editor.edit.textChanged.connect(lambda: self.editor.show_state(self.dirty()))
        self.editor.reset_button.clicked.connect(lambda: self.editor.edit.setPlainText(default))
        self.editor.save_button.clicked.connect(self.save)

    def dirty(self) -> bool:
        return self.editor.edit.toPlainText().strip() != self._saved

    def save(self) -> bool:
        prompt = self.editor.edit.toPlainText().strip()
        if not prompt:
            self.editor.show_state(True, "The prompt text is required.")
            return False
        draft_prompts.set_custom_prompt(self.kind, prompt, self.default)
        self.app.log(f"Saved {self.what}")
        self._saved = prompt
        self.editor.show_state(False)
        return True


class TranslationPage(Page):
    """The default translation prompt and the overrides for one (model, from, to) -- one form, for
    whichever the chooser names. A new override names its model and languages; an existing one is
    changed or deleted, not renamed."""

    def __init__(self, app) -> None:
        super().__init__()
        self.app = app
        self._snapshot: tuple = ()
        self.chooser = QComboBox()
        self._choices: list = []            # what each chooser entry stands for
        self.body.addWidget(Field("Prompt for", self.chooser))
        self.model_combo = QComboBox()
        self.model_combo.setEditable(True)
        self.model_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.model_combo.setMinimumContentsLength(16)
        self.source_combo, self.target_combo = QComboBox(), QComboBox()
        for combo, codes in ((self.source_combo, ("en", "de")), (self.target_combo, ("de", "en"))):
            combo.setEditable(True)
            combo.addItems(codes)
            combo.setMinimumWidth(80)       # an editable combo sizes itself to its two letters otherwise
        self.keys = columns(Field("Model", self.model_combo), Field("From", self.source_combo),
                        Field("To", self.target_combo))
        self.body.addWidget(self.keys)
        self.editor = _Editor(TRANSLATION_NOTE, height=130)
        self.blank_spin = QSpinBox()
        self.blank_spin.setRange(0, 10)
        self.body.addWidget(self.editor)
        self.delete_button = Button("Delete override…", compact=True)
        buttons = self.editor.buttons.layout()
        for index, widget in enumerate((QLabel("Blank lines before the text"), self.blank_spin, self.delete_button), 1):
            buttons.insertWidget(index, widget)
        self.body.addStretch(1)

        self.chooser.currentIndexChanged.connect(self._on_choice)
        for signal in (self.editor.edit.textChanged, self.blank_spin.valueChanged,
                       self.model_combo.currentTextChanged, self.source_combo.currentTextChanged,
                       self.target_combo.currentTextChanged):
            signal.connect(self._refresh_state)
        self.editor.reset_button.hide()
        self.editor.save_button.clicked.connect(self.save)
        self.delete_button.clicked.connect(self._on_delete)
        self.reload()

    def set_models(self, names: list[str]) -> None:
        text = self.model_combo.currentText()
        self.model_combo.blockSignals(True)
        self.model_combo.clear()
        self.model_combo.addItems(names)
        self.model_combo.setCurrentText(text)
        self.model_combo.blockSignals(False)

    def reload(self, select: tuple | str = DEFAULT_CHOICE) -> None:
        """Fill the chooser from the stored prompts and show `select` (DEFAULT_CHOICE, NEW_CHOICE or
        a (model, from, to))."""
        self.chooser.blockSignals(True)
        self.chooser.clear()
        self._choices = [DEFAULT_CHOICE]
        self.chooser.addItem("Default (models with no override)")
        for model, source, target, _config in tp.list_configs():
            self.chooser.addItem(f"{model}: {source} → {target}")
            self._choices.append((model, source, target))
        self.chooser.addItem("New override…")
        self._choices.append(NEW_CHOICE)
        self.chooser.blockSignals(False)
        self.chooser.setCurrentIndex(self._choices.index(select) if select in self._choices else 0)
        self._on_choice(self.chooser.currentIndex())

    def _values(self) -> tuple:
        return (self.model_combo.currentText().strip(), self.source_combo.currentText().strip(),
                self.target_combo.currentText().strip(), self.editor.edit.toPlainText().strip(),
                self.blank_spin.value())

    def choice(self):
        """DEFAULT_CHOICE, NEW_CHOICE or the (model, from, to) of the override on show."""
        return self._choices[self.chooser.currentIndex()]

    def _on_choice(self, index: int) -> None:
        choice = self._choices[index]
        if choice == DEFAULT_CHOICE:
            config, key = tp.effective_default_prompt(), ("", "en", "de")
        elif choice == NEW_CHOICE:
            config, key = tp.PromptConfig(prompt=""), ("", "en", "de")
        else:
            config, key = tp.get_prompt(*choice) or tp.PromptConfig(prompt=""), choice
        for edit, value in zip((self.model_combo, self.source_combo, self.target_combo), key):
            edit.blockSignals(True)
            edit.setCurrentText(value)
            edit.blockSignals(False)
        self.editor.edit.blockSignals(True)
        self.editor.edit.setPlainText(config.prompt)
        self.editor.edit.blockSignals(False)
        self.blank_spin.blockSignals(True)
        self.blank_spin.setValue(config.blank_lines)
        self.blank_spin.blockSignals(False)
        self.keys.setVisible(choice == NEW_CHOICE)
        self.delete_button.setVisible(choice not in (DEFAULT_CHOICE, NEW_CHOICE))
        self._snapshot = self._values()
        self._refresh_state()

    def dirty(self) -> bool:
        return self._values() != self._snapshot

    def description(self) -> str:
        return ("the default translation prompt" if self.choice() == DEFAULT_CHOICE
                else "the per-model translation prompt")

    def _refresh_state(self) -> None:
        self.editor.show_state(self.dirty())

    def save(self) -> bool:
        model, source, target, prompt, blank_lines = self._values()
        config = tp.PromptConfig(prompt=prompt, blank_lines=blank_lines)
        if self.choice() == DEFAULT_CHOICE:
            if not prompt:
                self.editor.show_state(True, "The prompt text is required.")
                return False
            tp.set_default_prompt(config)
            self.app.log("Saved default translation prompt")
            self._snapshot = self._values()
            self._refresh_state()
            return True
        if not (model and source and target and prompt):
            self.editor.show_state(True, "Model, From, To and the prompt text are all required.")
            return False
        tp.set_prompt(model, source, target, config)
        self.app.log(f"Saved translation prompt for {model} ({source} → {target})")
        self.reload(select=(model, source, target))
        return True

    def _on_delete(self) -> None:
        choice = self.choice()
        if choice in (DEFAULT_CHOICE, NEW_CHOICE):
            return
        model, source, target = choice
        confirm = QMessageBox.question(
            self, "Delete prompt",
            f"Delete the translation prompt for {model} ({source} → {target})? Translation falls back to the "
            "default prompt for this model and pair afterward.")
        if confirm != QMessageBox.StandardButton.Yes:
            return
        tp.delete_prompt(model, source, target)
        self.app.log(f"Deleted translation prompt for {model} ({source} → {target})")
        self.reload()


class PromptsTab(Page):
    def __init__(self, app) -> None:
        super().__init__()
        self.image = PromptPage(app, draft_prompts.KIND_IMAGE_DRAFT, alt_draft.SYSTEM_PROMPT, IMAGE_NOTE,
                                "image description prompt")
        self.rewrite = PromptPage(app, draft_prompts.KIND_SLIDE_REWRITE, ai_draft.SYSTEM_PROMPT, REWRITE_NOTE,
                                  "slide rewrite prompt")
        self.translation = TranslationPage(app)
        self.pages = {"image": self.image, "rewrite": self.rewrite, "translation": self.translation}
        self.chooser = SegmentedControl(
            (("image", "Image descriptions"), ("rewrite", "Slide rewrite"), ("translation", "Translation")))
        self.stack = QStackedWidget()
        for page in self.pages.values():
            self.stack.addWidget(page)
        self.chooser.changed.connect(self.show_page)
        self.body.addWidget(self.chooser)
        self.body.addWidget(self.stack)
        self.body.addStretch(1)

    def show_page(self, key: str) -> None:
        self.chooser.set_current(key)
        self.stack.setCurrentWidget(self.pages[key])

    def dirty_descriptions(self) -> list[str]:
        out = []
        if self.image.dirty():
            out.append("the image description prompt")
        if self.rewrite.dirty():
            out.append("the slide rewrite prompt")
        if self.translation.dirty():
            out.append(self.translation.description())
        return out

    def save_dirty(self) -> bool:
        """Save every page with unsaved text; False if one was refused (its page, shown, says why)."""
        ok = True
        for key, page in self.pages.items():
            if page.dirty() and not page.save():
                self.show_page(key)
                ok = False
        return ok

    def confirm_close(self) -> bool:
        """True when the sheet may close: nothing is unsaved, or the user saved or discarded it."""
        dirty = self.dirty_descriptions()
        if not dirty:
            return True
        box = QMessageBox(self)
        box.setWindowTitle("Unsaved changes")
        box.setText(f"You have unsaved changes to {' and '.join(dirty)}. Save before closing?")
        save = box.addButton("Save", QMessageBox.ButtonRole.AcceptRole)
        discard = box.addButton("Discard", QMessageBox.ButtonRole.DestructiveRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(save)
        box.exec()
        if box.clickedButton() is save:
            return self.save_dirty()
        return box.clickedButton() is discard
