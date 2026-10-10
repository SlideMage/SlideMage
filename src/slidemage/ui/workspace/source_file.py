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

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QHBoxLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout

from ... import (
    bibliography,
    latex_edit,
    latex_lint,
    slide_preview,
    slide_source,
    slide_versioning,
)
from ...deck_scan import PROJECT_ROOT
from ...qt_ai_draft_dialog import AiDraftDialog
from ...slide_language import bare_id
from ..dialogs.slide_usage_dialog import DeckVersions, apply_deck_versions, ask_deck_versions
from ..kit import kit_qss as q
from ..kit.widgets import Button, Chip, PopoverMenu, Surface
from ..text import plural
from .ai_fix import AiFixPanel
from .source_editor import FindBar, LatexPlainTextEdit

LINT_DELAY_MS = 300     # after the last keystroke
LINT_LIST_LIMIT = 25    # issues shown in the status line's list
SAME, RELOADED, CONFLICT = "same", "reloaded", "conflict"    # what disk_changed() found


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
    lint_changed = Signal()

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
        self.ai_dialog: Optional[AiDraftDialog] = None
        self.lint: Optional[latex_lint.CheckResult] = None     # of the buffer; None for a .bib

        self.text, self.eol = slide_source.read_slide_source(path)
        self.editor = LatexPlainTextEdit(app.theme)
        self.editor.set_text(self.text)
        self.editor.modified_changed.connect(self.modified_changed)
        self.editor.escape_pressed.connect(self._abort_ai_fix)
        # A frozen snapshot is a historical record: read-only until unlocked.
        self.editor.set_read_only(self.is_slide and not self.is_current_slide)

        self.find_bar = FindBar(self.editor)
        self.fold_button = Button("", "ghost", compact=True)
        self.fold_button.clicked.connect(self.toggle_header_fold)
        self.fix_panel = AiFixPanel(app, self.editor, path.name)
        self.fix_panel.running_changed.connect(lambda _running: self._update_status())
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._build_status_line())
        layout.addWidget(self._build_conflict_bar())
        layout.addWidget(self.fix_panel)
        layout.addWidget(self.find_bar)
        layout.addWidget(self.fold_button, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self.editor, 1)
        self._update_fold_button()
        # Linted a moment after the last keystroke: a lexical check of the buffer, no LaTeX run.
        self._lint_timer = QTimer(self)
        self._lint_timer.setSingleShot(True)
        self._lint_timer.setInterval(LINT_DELAY_MS)
        self._lint_timer.timeout.connect(self.run_lint)
        self.editor.text_changed.connect(self._lint_timer.start)
        self.run_lint()

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
        return self.dirty or self.fix_panel.running or self.ai_dialog is not None

    # -- the status line: lint of the buffer, Ask AI to fix ------------------------------

    def _build_status_line(self) -> Surface:
        line = Surface()
        row = QHBoxLayout(line)
        row.setContentsMargins(10, 4, 10, 4)
        self.lint_chip = Chip("", "muted")
        self.lint_chip.clicked.connect(self._show_issues)
        row.addWidget(self.lint_chip)
        row.addStretch(1)
        self.ask_ai_button = Button("Ask AI to fix", "ghost", compact=True)
        self.ask_ai_button.setToolTip(
            "Let a language model look for syntax problems in the buffer and propose fixes you can "
            "apply one by one. Not a compile: it can miss problems and flag fine code.")
        self.ask_ai_button.clicked.connect(self.fix_panel.run_check)
        row.addWidget(self.ask_ai_button)
        line.setVisible(not self.is_bib)
        return line

    def _build_conflict_bar(self) -> Surface:
        """The notice for a file that changed on disk while the buffer has unsaved edits."""
        self.conflict_bar = Surface()
        row = QHBoxLayout(self.conflict_bar)
        row.setContentsMargins(10, 4, 10, 4)
        self.conflict_label = QLabel()
        self.conflict_label.setObjectName(q.CHAT_NOTICE)
        self.conflict_label.setProperty("tone", "warning")
        self.conflict_label.setWordWrap(True)
        row.addWidget(self.conflict_label, 1)
        reload_button = Button("Reload from disk", "secondary", compact=True)
        reload_button.setToolTip("Drop your unsaved edits and show the file as it is on disk now.")
        reload_button.clicked.connect(self._reload_conflicting)
        keep_button = Button("Keep my edits", "ghost", compact=True)
        keep_button.setToolTip("Keep what you have in the editor. Saving it replaces the file on disk "
                               "(a backup of that version is kept).")
        keep_button.clicked.connect(self.keep_edits)
        row.addWidget(reload_button)
        row.addWidget(keep_button)
        self.conflict_bar.hide()
        return self.conflict_bar

    def run_lint(self) -> None:
        """Check the buffer now (a .bib is not LaTeX and is not checked)."""
        if self.is_bib:
            return
        self._lint_timer.stop()
        self.lint = latex_lint.check_buffer(self.editor.text(), self.path.name, self.path)
        self._update_status()
        self.lint_changed.emit()

    def _update_status(self) -> None:
        if self.lint is None:
            return
        errors, warnings = len(self.lint.errors), len(self.lint.warnings)
        if errors or warnings:
            parts = ([plural(errors, "error")] if errors else []) + ([plural(warnings, "warning")] if warnings else [])
            self.lint_chip.set_text(" · ".join(parts))
            self.lint_chip.set_tone("error" if errors else "warning")
            self.lint_chip.setToolTip("Click for the list; click an entry to go to its line.")
        else:
            self.lint_chip.set_text("No problems found")
            self.lint_chip.set_tone("muted")
            self.lint_chip.setToolTip("A quick static check of the buffer as you type: it finds what is "
                                      "certainly wrong, not everything that is.")
        self.ask_ai_button.setEnabled(not self.fix_panel.running and not self.editor.is_read_only())

    def _show_issues(self) -> None:
        if self.lint is None or not self.lint.issues:
            return
        issues = sorted(self.lint.issues, key=lambda i: (i.severity != latex_lint.ERROR, i.line))
        menu = PopoverMenu(self, min_width=380)
        for index, issue in enumerate(issues[:LINT_LIST_LIMIT]):
            menu.add_item(str(index), issue.message if len(issue.message) <= 90 else issue.message[:89] + "…",
                          meta=f"line {issue.line}", tone="danger" if issue.severity == latex_lint.ERROR else "")
        if len(issues) > LINT_LIST_LIMIT:
            menu.add_item("more", f"… and {len(issues) - LINT_LIST_LIMIT} more", enabled=False)
        menu.triggered.connect(lambda key: key.isdigit() and self.editor.go_to_line(issues[int(key)].line))
        menu.closed.connect(menu.deleteLater)
        menu.popup_below(self.lint_chip)

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
        self.conflict_bar.hide()

    def sync(self) -> None:
        """Pick up a change of the file on disk made elsewhere in the app (a deck
        edit from the slide list, a replaced image), unless there are unsaved edits."""
        if not self.dirty:
            self.disk_changed()

    def disk_changed(self) -> str:
        """Compare the buffer's saved text with the file on disk: SAME (nothing to do: our own save, or no
        change), RELOADED (the buffer was clean and shows the new text), or CONFLICT (someone else, e.g.
        Claude Code in the terminal, changed a file that has unsaved edits here: the edits stay, and the
        notice offers the choice)."""
        if not self.path.is_file():
            return SAME
        on_disk = slide_source.read_slide_source(self.path)
        if on_disk[0] == self.text:
            self.conflict_bar.hide()
            return SAME
        if not self.dirty:
            self.reload()
            return RELOADED
        self.conflict_label.setText(f"{self.path.name} was changed on disk (by Claude Code or another program) "
                                    "while you have unsaved edits here.")
        self.conflict_bar.show()
        return CONFLICT

    def _reload_conflicting(self) -> None:
        self.reload()
        self.saved.emit()           # the shown file changed: the Preview renders it again

    def keep_edits(self) -> None:
        """Take the file on disk as what the buffer was loaded from, so that saving the edits replaces
        it (save_slide_source keeps a backup of that version) instead of failing as stale."""
        self.text, self.eol = slide_source.read_slide_source(self.path)
        self.conflict_bar.hide()

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
        try:        # before anything is frozen or asked: a stale file loses neither
            slide_source.check_fresh(self.path, previous_text)
        except slide_source.StaleFileError as exc:
            QMessageBox.critical(self.app, "Save failed", str(exc))
            return False
        versions = DeckVersions({}, None)
        frozen_version = None
        if self.is_current_slide:
            old_version = slide_versioning.parse_version(self.text)
            choice = prompt_version_choice(self.app, old_version)
            if choice is None:
                return False
            final_version, freeze_as = slide_versioning.plan_save(old_version, choice)
            if freeze_as is not None:
                # A slide in several decks (or pinned, or translated) asks which
                # version each deck uses from now on.
                frozen_version = freeze_as
                asked = ask_deck_versions(self.app, self.id_slug, self.text, final_version, freeze_as)
                if asked is None:
                    return False
                versions = asked
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
        if frozen_version is not None:
            apply_deck_versions(self.app, self.id_slug, versions.choices, frozen_version)
        if versions.open_translation is not None and self.on_open is not None:
            self.on_open(versions.open_translation)
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
        self._update_status()

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

    def ai_draft(self) -> None:
        if self.ai_dialog is not None:
            self.ai_dialog.raise_()
            self.ai_dialog.activateWindow()
            return
        dialog = AiDraftDialog(self.app, self.editor, self.path.name)
        self.ai_dialog = dialog
        dialog.finished.connect(lambda _result: setattr(self, "ai_dialog", None))
        dialog.show()

    def _abort_ai_fix(self) -> None:
        self.fix_panel.abort()

    def refresh_model_preference(self, models: list[str]) -> None:
        self.fix_panel.refresh_model_preference(models)
        if self.ai_dialog is not None:
            self.ai_dialog.refresh_model_preference(models)
