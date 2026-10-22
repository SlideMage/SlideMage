# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""One file open in the Source view: its editor, find bar and header-fold
button, and what saving, reverting and reloading it mean.

The Source view edits slides (slides/*.tex), a deck's own .tex file and
Slidemaster.bib alike, and saves as you type (AUTOSAVE_DELAY_MS after the last
keystroke; write_now()). A slide's `-current.tex` gets the "+" on its version
line as it is written (slide_versioning.prepare_autosave()); a version is made
on purpose, with Update Version. A frozen `-vX-Y-Z.tex` snapshot is read-only
until unlocked, then saves plainly, like any other file. The saved text is
kept (`text`) so that a save can tell, through slide_source.StaleFileError,
when something else wrote the file meanwhile (Claude Code in the terminal, an
"Add reference" write to the .bib, the header sync that runs after every deck
edit, a rename that rewrites references): autosave then stops, and the
conflict bar asks.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QHBoxLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout

from ... import app_settings
from ... import (
    latex_edit,
    latex_lint,
    slide_language,
    slide_source,
    slide_versioning,
)
from ...slide_language import bare_id
from ..kit import kit_qss as q
from ..kit.widgets import Button, Chip, PopoverMenu, Surface
from ..text import plural
from .ai_fix import AiFixPanel
from .source_editor import FindBar, LatexPlainTextEdit

LINT_DELAY_MS = 300     # after the last keystroke
AUTOSAVE_DELAY_MS = 1500    # after the last keystroke
LINT_LIST_LIMIT = 25    # issues shown in the status line's list
SAME, RELOADED, CONFLICT = "same", "reloaded", "conflict"    # what disk_changed() found

# Replace in the file shown: Ctrl+H, but ⌥⌘F on a Mac, where ⌘H (what Qt makes of Ctrl+H) hides the app.
REPLACE_KEY = "Ctrl+Alt+F" if sys.platform == "darwin" else "Ctrl+H"


def prompt_version_level(parent, base: slide_versioning.Version) -> Optional[str]:
    """Update Version's "how significant is the change since `base`?" prompt.
    Returns "major", "minor", "patch", or None if the user cancelled."""
    box = QMessageBox(parent)
    box.setWindowTitle("Update version")
    box.setText(f"Changed since v{slide_versioning.format_dot(base)}.\n\nHow significant is the change?")
    level_buttons: dict[str, QPushButton] = {}
    for level in ("major", "minor", "patch"):
        target = slide_versioning.format_dot(slide_versioning.bump(base, level))
        level_buttons[level] = box.addButton(f"{level.capitalize()} (→ {target})", QMessageBox.ButtonRole.AcceptRole)
    box.addButton(QMessageBox.StandardButton.Cancel)
    box.setDefaultButton(level_buttons["minor"])
    box.exec()
    clicked = box.clickedButton()
    return next((level for level, button in level_buttons.items() if clicked is button), None)


class SourceFile(Surface):
    saved = Signal()                  # after Ctrl+S (the Preview renders it again), not after an autosave
    written = Signal()                # after every write, autosave included
    modified_changed = Signal(bool)
    conflict_changed = Signal()       # the conflict bar was shown or hidden
    lint_changed = Signal()

    def __init__(
        self, app, path: Path, on_saved: Optional[Callable[[str], None]] = None,
        on_open: Optional[Callable[[Path], None]] = None,
    ) -> None:
        """`on_saved(previous_text)` runs after each write (a deck's own source goes
        through the window's after_deck_edit this way); `on_open(path)` opens
        another file (the translation the usage dialog offers)."""
        super().__init__()
        self.app = app
        self.path = path
        self.on_saved = on_saved
        self.on_open = on_open
        try:
            macro, self.id_slug, _version = slide_language.call_for_slide_path(path)
            self.is_slide = True
            # Only a slide's own current.tex is version-tracked (call_for_slide_path
            # says "slideversion" for a frozen file).
            self.is_current_slide = macro == "slide"
        except ValueError:
            self.is_slide = self.is_current_slide = False
            self.id_slug = ""
        self.bare_id = bare_id(self.id_slug)
        self.is_bib = path == self.app.project.bibliography_path
        self.lint: Optional[latex_lint.CheckResult] = None     # of the buffer; None for a .bib

        self.text, self.eol = slide_source.read_slide_source(path)
        tab_width = app_settings.get(app.project, latex_edit.TAB_WIDTH_SETTING_KEY, latex_edit.DEFAULT_TAB_WIDTH_CHARS)
        self.editor = LatexPlainTextEdit(app.theme, tab_width)
        self.editor.set_text(self.text)
        self.editor.modified_changed.connect(self.modified_changed)
        self.editor.escape_pressed.connect(self._abort_ai_fix)
        # A frozen snapshot is a historical record: read-only until unlocked.
        self.editor.set_read_only(self.is_slide and not self.is_current_slide)

        self.find_bar = FindBar(self.editor)
        self.fold_button = Button("", "ghost", compact=True)
        self.fold_button.clicked.connect(self.toggle_header_fold)
        self.fix_panel = AiFixPanel(app, self.editor, path)
        self.fix_panel.running_changed.connect(self._on_fix_running)
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
        # Saved a moment after the last keystroke; backed up once per editing session.
        self._backed_up = False
        self._autosave_timer = QTimer(self)
        self._autosave_timer.setSingleShot(True)
        self._autosave_timer.setInterval(AUTOSAVE_DELAY_MS)
        self._autosave_timer.timeout.connect(self.write_now)
        self.editor.text_changed.connect(self._schedule_autosave)

        # Scoped to this file's widgets, so the shortcuts of the files in the
        # same window never clash.
        for sequence, action in ((QKeySequence.StandardKey.Find, self.find_bar.show_find),
                                 (QKeySequence(REPLACE_KEY), self.find_bar.show_replace)):
            shortcut = QShortcut(sequence, self)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.activated.connect(action)

    @property
    def dirty(self) -> bool:
        return self.editor.is_modified()

    @property
    def conflicted(self) -> bool:
        """The file changed on disk while the buffer has edits: nothing is written until the user chooses."""
        return not self.conflict_bar.isHidden()

    @property
    def blocked(self) -> bool:
        """The buffer has edits that are not written and will not be until something changes: a read-only
        buffer, the conflict bar up, or an AI fix running. (Plain `dirty` is also true between a keystroke
        and its autosave.)"""
        return self.dirty and (self.editor.is_read_only() or self.conflicted or self.fix_panel.running)

    @property
    def keep_open(self) -> bool:
        """Whether the view must not drop this file when it is shown no more: unsaved
        edits or a running "Ask AI to fix"."""
        return self.dirty or self.fix_panel.running

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
        if self.is_bib:
            line.hide()     # never setVisible(True) here: the line has no parent yet, so it would open as a window
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
        keep_button.setToolTip("Keep what you have in the editor. It is saved over the file on disk "
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
        self.lint = latex_lint.check_buffer(self.app.project, self.editor.text(), self.path.name, self.path)
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
        self._autosave_timer.stop()
        self._backed_up = False
        self._set_conflict(None)

    def adopt_disk(self) -> None:
        """Take the file on disk into the clean buffer as one edit, keeping cursor, scroll position and
        undo history: Update Version rewrote its version line."""
        self.text, self.eol = slide_source.read_slide_source(self.path)
        self.editor.patch_text(self.text)
        self.editor.mark_saved()

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
            self._set_conflict(None)
            return SAME
        if not self.dirty:
            try:        # an edit made outside the app gets the "+" an in-app edit would have
                slide_versioning.mark_external_edit(self.app.project, self.path)
            except (OSError, ValueError, slide_source.StaleFileError):
                pass
            self.reload()
            return RELOADED
        self._autosave_timer.stop()
        self._set_conflict(f"{self.path.name} was changed on disk (by Claude Code or another program) "
                           "while you have edits here that are not saved yet.")
        return CONFLICT

    def _set_conflict(self, message: Optional[str]) -> None:
        """Show the conflict bar with `message`, or hide it (None)."""
        if message is not None:
            self.conflict_label.setText(message)
        if (message is None) != self.conflict_bar.isHidden():
            self.conflict_bar.setVisible(message is not None)
            self.conflict_changed.emit()

    def _reload_conflicting(self) -> None:
        self.reload()
        self.saved.emit()           # the shown file changed: the Preview renders it again

    def keep_edits(self) -> None:
        """Take the file on disk as what the buffer was loaded from, so that saving the edits replaces
        it (save_slide_source keeps a backup of that version) instead of failing as stale."""
        self.text, self.eol = slide_source.read_slide_source(self.path)
        self._backed_up = False     # the file on disk is someone else's: back it up before it is replaced
        self._set_conflict(None)
        self._schedule_autosave()

    def _schedule_autosave(self) -> None:
        if self.dirty and not self.editor.is_read_only():
            self._autosave_timer.start()

    def _on_fix_running(self, running: bool) -> None:
        self._update_status()
        if not running:
            self._schedule_autosave()   # what the fix applied meanwhile

    def write_now(self, explicit: bool = False) -> bool:
        """Write the buffer's edits to the file now: the autosave, a flush before another file is
        shown or a run starts, and Ctrl+S (`explicit`, which also emits `saved`, so the Preview
        renders it). Returns whether the file holds the buffer: False while saving is paused (a
        read-only buffer, the conflict bar up, an AI fix running), when the file changed on disk
        meanwhile (the conflict bar then shows) or the write failed."""
        self._autosave_timer.stop()
        if not self.dirty:
            if explicit:
                self.saved.emit()
            return True
        if self.blocked:
            return False
        raw_text = self.editor.text()
        previous_text = self.text
        try:
            # A slide's current file gets the "+", after its version is frozen if it is not yet.
            new_text, backup_path, frozen = slide_versioning.save_slide(
                self.app.project, self.path, raw_text, self.eol, previous_text, backup=not self._backed_up)
        except slide_source.StaleFileError:
            self.disk_changed()
            return False
        except OSError as exc:
            self.app.log(f"*** Could not save {self.path.name}: {exc} ***")
            if explicit:
                QMessageBox.critical(self.app, "Save failed", f"Could not save {self.path.name}: {exc}")
            return False
        self._backed_up = True
        if frozen is not None:
            self.app.log(f"Froze {frozen.name}: the version {self.path.name} had before this change")
        self.text = new_text
        if new_text != raw_text:
            # The "+" went onto the version line in what went to disk, not yet in the buffer.
            self.editor.patch_text(new_text)
        self.editor.mark_saved()
        if backup_path is not None:
            self.app.log(f"Saving {self.path.name} as you type (backup: {backup_path.relative_to(self.app.project.root)})")
        if self.on_saved is not None:
            self.on_saved(previous_text)
        self.written.emit()
        if explicit:
            self.saved.emit()
        return True

    # -- helpers the toolbar calls ------------------------------------------------------

    def unlock(self) -> None:
        self.editor.set_read_only(False)
        self._update_status()
        self._schedule_autosave()

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

    def _abort_ai_fix(self) -> None:
        self.fix_panel.abort()

    def refresh_model_preference(self, models: list[str]) -> None:
        self.fix_panel.refresh_model_preference(models)
