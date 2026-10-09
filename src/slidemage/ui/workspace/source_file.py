"""One file open in the Source view: its editor, find bar and header-fold
button, and what saving, reverting and reloading it mean.

The Source view edits slides (slides/*.tex), a deck's own .tex file and
Slidemaster.bib alike. Only a slide's `-current.tex` gets the version prompt
on save: a frozen `-vX-Y-Z.tex` snapshot has no current version to bump and
saves plainly, like any other file. The saved text is kept (`text`) so that a
save can tell, through slide_source.StaleFileError, when something else in the
app wrote the file meanwhile (an "Add reference" write to the .bib, the header
sync that runs after every deck edit, a rename that rewrites references).
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QDialog, QMessageBox, QPushButton, QVBoxLayout

from ... import bibliography, deck_editor, latex_edit, slide_preview, slide_source, slide_usage, slide_versioning
from ...deck_scan import PROJECT_ROOT
from ...qt_ai_draft_dialog import AiDraftDialog
from ...qt_slide_usage_dialog import SlideUsageDialog
from ...qt_syntax_check_dialog import SyntaxCheckDialog
from ...slide_language import bare_id
from ..kit.widgets import Button, Surface
from .source_editor import FindBar, LatexPlainTextEdit


def prompt_version_choice(parent, old_version: Optional[slide_versioning.Version]) -> Optional[str]:
    """The save-time "how significant is this change?" prompt for a slide's
    current.tex: major/minor/patch freeze the outgoing on-disk content under its
    own tracked version and bump the new content's version accordingly;
    "Overwrite" just saves (a never-tracked slide stays untracked). Returns the
    chosen level, "overwrite", or None if the user cancelled the save."""
    baseline = old_version if old_version is not None else slide_versioning.DEFAULT_BASELINE
    current_label = slide_versioning.format_dot(old_version) if old_version is not None else "untracked"
    box = QMessageBox(parent)
    box.setWindowTitle("Save slide")
    box.setText(f"Current version: {current_label}\n\nHow significant is this change?")
    level_buttons: dict[str, QPushButton] = {}
    for level in ("major", "minor", "patch"):
        target = slide_versioning.format_dot(slide_versioning.bump(baseline, level))
        level_buttons[level] = box.addButton(f"{level.capitalize()} (→ {target})", QMessageBox.ButtonRole.AcceptRole)
    overwrite_label = (
        f"Overwrite (stays {current_label})" if old_version is not None else "Overwrite (no version tracked)")
    overwrite_button = box.addButton(overwrite_label, QMessageBox.ButtonRole.DestructiveRole)
    box.addButton(QMessageBox.StandardButton.Cancel)
    box.setDefaultButton(overwrite_button)
    box.exec()
    clicked = box.clickedButton()
    for level, button in level_buttons.items():
        if clicked is button:
            return level
    return "overwrite" if clicked is overwrite_button else None


class SourceFile(Surface):
    saved = Signal()                  # after a successful save
    modified_changed = Signal(bool)

    def __init__(
        self, app, path: Path, on_saved: Optional[Callable[[str], None]] = None,
        on_open: Optional[Callable[[Path], None]] = None,
    ) -> None:
        """`on_saved(previous_text)` runs after a save (a deck's own source goes
        through the window's after_deck_edit this way); `on_open(path)` opens
        another file (the translation the usage dialog offers)."""
        super().__init__()
        self.app = app
        self.path = path
        self.on_saved = on_saved
        self.on_open = on_open
        try:
            macro, self.id_slug, _version = slide_preview.call_for_slide_path(path)
            self.is_slide = True
            # Only a slide's own current.tex is version-tracked (call_for_slide_path
            # says "slideversion" for a frozen file).
            self.is_current_slide = macro == "slide"
        except ValueError:
            self.is_slide = self.is_current_slide = False
            self.id_slug = ""
        self.bare_id = bare_id(self.id_slug)
        self.is_bib = path == bibliography.DEFAULT_BIB
        self.syntax_dialog: Optional[SyntaxCheckDialog] = None
        self.ai_dialog: Optional[AiDraftDialog] = None

        self.text, self.eol = slide_source.read_slide_source(path)
        self.editor = LatexPlainTextEdit(app.theme)
        self.editor.set_text(self.text)
        self.editor.modified_changed.connect(self.modified_changed)
        self.editor.escape_pressed.connect(self._abort_syntax_check)
        # A frozen snapshot is a historical record: read-only until unlocked.
        self.editor.set_read_only(self.is_slide and not self.is_current_slide)

        self.find_bar = FindBar(self.editor)
        self.fold_button = Button("", "ghost", compact=True)
        self.fold_button.clicked.connect(self.toggle_header_fold)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.find_bar)
        layout.addWidget(self.fold_button, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self.editor, 1)
        self._update_fold_button()

        # Scoped to this file's widgets, so the shortcuts of the files in the
        # same window never clash.
        for sequence, action in ((QKeySequence.StandardKey.Find, self.find_bar.show_find),
                                 (QKeySequence("Ctrl+H"), self.find_bar.show_replace)):
            shortcut = QShortcut(sequence, self)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.activated.connect(action)

    @property
    def dirty(self) -> bool:
        return self.editor.is_modified()

    @property
    def keep_open(self) -> bool:
        """Whether the view must not drop this file when it is shown no more: unsaved
        edits, or a non-modal dialog that works on its editor."""
        return self.dirty or self.syntax_dialog is not None or self.ai_dialog is not None

    # -- header comment ----------------------------------------------------------------

    def toggle_header_fold(self) -> None:
        self.editor.set_header_folded(not self.editor.is_header_folded())
        self._update_fold_button()

    def _update_fold_button(self) -> None:
        count = self.editor.header_line_count()
        self.fold_button.setVisible(count > 0)
        arrow = "▸ Show" if self.editor.is_header_folded() else "▾ Hide"
        self.fold_button.setText(f"{arrow} {count}-line header comment")

    # -- reading and writing -----------------------------------------------------------

    def reload(self) -> None:
        """Replace the buffer with what is on disk now, dropping unsaved edits (the
        caller asked the user): Revert, and a .bib that "Add reference" just changed."""
        self.text, self.eol = slide_source.read_slide_source(self.path)
        self.editor.set_text(self.text)
        self._update_fold_button()

    def sync(self) -> None:
        """Pick up a change of the file on disk made elsewhere in the app (a deck
        edit from the slide list, a replaced image), unless there are unsaved edits."""
        if not self.dirty and self.path.is_file() and slide_source.read_slide_source(self.path)[0] != self.text:
            self.reload()

    def revert(self) -> None:
        if not self.dirty:
            return
        reply = QMessageBox.question(
            self.app, "Revert", f"Discard unsaved changes to {self.path.name} and reload the saved version?")
        if reply == QMessageBox.StandardButton.Yes:
            self.reload()
            self.app.log(f"Reverted {self.path.name} to the saved version")

    def save(self) -> bool:
        """Returns whether the file was saved: False when the version prompt or the
        usage dialog was cancelled, or the file changed on disk meanwhile."""
        raw_text = self.editor.text()
        new_text = raw_text
        previous_text = self.text
        usage_choices: dict[str, str] = {}
        open_translation = None
        frozen_hyphen = None
        if self.is_current_slide:
            old_version = slide_versioning.parse_version(self.text)
            choice = prompt_version_choice(self.app, old_version)
            if choice is None:
                return False
            final_version, freeze_as = slide_versioning.plan_save(old_version, choice)
            if freeze_as is not None:
                # A slide in several decks (or pinned, or translated) asks which
                # version each deck uses from now on.
                frozen_hyphen = slide_versioning.format_hyphen(freeze_as)
                usages = slide_usage.find_usage(self.id_slug)
                translations = slide_usage.find_translations(self.id_slug, self.text)
                if slide_usage.needs_dialog(usages, translations):
                    dialog = SlideUsageDialog(
                        self.app, self.id_slug, slide_versioning.format_dot(final_version),
                        slide_versioning.format_dot(freeze_as), usages, translations)
                    if dialog.exec() != QDialog.DialogCode.Accepted:
                        return False
                    usage_choices = dialog.choices()
                    if dialog.open_translation() and translations:
                        open_translation = translations[0].path
                frozen = slide_versioning.freeze_slide(self.path, self.id_slug, freeze_as)
                if frozen is not None:
                    self.app.log(f"    (froze outgoing v{slide_versioning.format_dot(freeze_as)} -> {frozen.name})")
                else:
                    self.app.log(f"    (v{slide_versioning.format_dot(freeze_as)} was already frozen -- left it alone)")
            new_text = (slide_versioning.set_marker(new_text, final_version) if final_version is not None
                        else slide_versioning.strip_marker(new_text))

        try:
            # expected_text: without it a save would silently overwrite (backup
            # aside) whatever else in the app wrote this file since it was loaded.
            backup_path = slide_source.save_slide_source(self.path, new_text, self.eol, expected_text=previous_text)
        except slide_source.StaleFileError as exc:
            QMessageBox.critical(self.app, "Save failed", str(exc))
            return False
        self.text = new_text
        if new_text != raw_text:
            # The version bump rewrote the \setSlideVersion{} line in what went to
            # disk but not in the buffer, which would keep showing the old one.
            self.editor.patch_text(new_text)
        self.editor.mark_saved()
        if usage_choices:
            try:
                for line in slide_usage.apply_choices(self.id_slug, usage_choices, frozen_hyphen):
                    self.app.log(line)
                self.app.refresh_open_deck_editors()
            except (deck_editor.StaleFileError, ValueError) as exc:
                QMessageBox.warning(
                    self.app, "Decks not updated", f"The slide is saved, but a deck could not be changed: {exc}")
        if open_translation is not None and self.on_open is not None:
            self.on_open(open_translation)
        if backup_path is not None:
            self.app.log(f"Saved {self.path.name} (backup: {backup_path.relative_to(PROJECT_ROOT)})")
        else:
            self.app.log(f"Saved {self.path.name} (new file, no prior content to back up)")
        if self.on_saved is not None:
            self.on_saved(previous_text)
        self.saved.emit()
        return True

    # -- helpers the toolbar calls ------------------------------------------------------

    def unlock(self) -> None:
        self.editor.set_read_only(False)

    def show_bib_key(self, key: str) -> None:
        """Put the cursor on the entry `key` (`@type{key,`), after one was added."""
        offset = self.editor.text().find(f"{{{key},")
        if offset >= 0:
            self.editor.go_to_offset(offset)

    def jump_to_bib_letter(self, letter: str) -> bool:
        offset = latex_edit.bib_entry_start(self.editor.text(), letter)
        if offset is None:
            return False
        self.editor.go_to_offset(offset)
        return True

    def check_syntax(self) -> None:
        """Non-modal and reused rather than reopened: a second dialog over the same
        buffer would only confuse."""
        if self.syntax_dialog is not None:
            self.syntax_dialog.raise_()
            self.syntax_dialog.activateWindow()
            return
        dialog = SyntaxCheckDialog(self.app, self.editor, self.path.name)
        self.syntax_dialog = dialog
        dialog.finished.connect(lambda _result: setattr(self, "syntax_dialog", None))
        dialog.show()

    def ai_draft(self) -> None:
        if self.ai_dialog is not None:
            self.ai_dialog.raise_()
            self.ai_dialog.activateWindow()
            return
        dialog = AiDraftDialog(self.app, self.editor, self.path.name)
        self.ai_dialog = dialog
        dialog.finished.connect(lambda _result: setattr(self, "ai_dialog", None))
        dialog.show()

    def _abort_syntax_check(self) -> None:
        if self.syntax_dialog is not None:
            self.syntax_dialog.abort_check()

    def refresh_model_preference(self, models: list[str]) -> None:
        for dialog in (self.syntax_dialog, self.ai_dialog):
            if dialog is not None:
                dialog.refresh_model_preference(models)
