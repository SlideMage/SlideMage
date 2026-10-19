# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The Source view: a compact toolbar over the editor of the file being edited.

It edits slides, a deck's own .tex file and Slidemaster.bib alike, one
`SourceFile` (source_file.py) per file, saved as you type. A file is written
before another is shown; one that cannot be (a conflict with a change on disk)
stays open, so that switching slides never loses an edit; a clean one is
dropped and read from disk again when it comes back, so it is never stale.
The view reports edits that could not be saved ("dirty") and Ctrl+S ("saved"), and asks the window, through the
signals, for what is not its own: rendering the buffer, restoring a frozen
version, making a version (Update Version), showing another file.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ... import latex_edit, slide_versioning
from ...latex_edit import ASKS, INSERT_BLOCK_COMMANDS, INSERT_COMMANDS, INSERT_LIST_COMMANDS, Insert
from ...selection import NO_SELECTION, Selection, SelectionError, capture
from ..dialogs.citation import CitationDialog
from ..kit import kit_qss as q
from ..kit.widgets import Button, Chip, IconButton, Popover, PopoverMenu, Surface
from .insert_popovers import CitationPopover, CodeFilePopover, LinkPopover
from .selection_tasks import PROOFREAD, REWRITE, add_menu_items
from .source_file import SourceFile

LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


VERSION_TIP = ("Make the slide as it is now a version: it is frozen, and decks can keep using it. "
               "Asks how significant the change is. (Edits are saved as you type.)")


class SourcePane(Surface):
    dirty_changed = Signal(bool)         # some file has edits that cannot be saved (a conflict, read-only, an AI fix running)
    written = Signal(object)             # Path; after every write, autosave included
    buffer_changed = Signal(object)      # Path; every text edit, even while already dirty
    file_closed = Signal(object)         # the Path of a file the view no longer holds
    lint_errors_changed = Signal(int)    # errors the static check finds in the file shown
    saved = Signal(object)               # the Path that was saved
    render_requested = Signal()          # Ctrl+R: render the buffer
    restore_requested = Signal(object)   # Path of a frozen version to make current
    version_requested = Signal(str)      # id_slug: Update Version of that slide
    file_requested = Signal(object)      # Path of another file to show
    reference_added = Signal()           # an entry was added to Slidemaster.bib

    def __init__(self, app) -> None:
        super().__init__()
        self.app = app
        self._files: dict[Path, SourceFile] = {}
        self._current: Optional[SourceFile] = None
        self._dirty = False
        self._lint_errors = 0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._build_toolbar())
        self._jump_bar = self._build_jump_bar()
        layout.addWidget(self._jump_bar)
        self._frozen_bar = self._build_frozen_bar()
        layout.addWidget(self._frozen_bar)
        self._stack = QStackedWidget()
        self._stack.setObjectName(q.SURFACE)
        self._empty = QLabel()
        self._empty.setWordWrap(True)
        self._empty.setObjectName(q.SOURCE_NOTE)
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._stack.addWidget(self._empty)
        layout.addWidget(self._stack, 1)

        # Scoped to this view's widgets. Ctrl+S is the window's (window.py): it writes the file shown here
        # now and renders it, from every view.
        shortcuts = [
            ("Ctrl+/", lambda: self._edit(lambda e: e.toggle_comment())),
            ("Ctrl+I", lambda: self._wrap("textit")), ("Ctrl+B", lambda: self._wrap("textbf")),
            ("Ctrl+U", lambda: self._wrap("underline")), ("Ctrl+R", self.render_requested.emit),
        ]
        for sequence, action in shortcuts:
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.activated.connect(action)
        self._update_toolbar()

    # -- building ----------------------------------------------------------------------

    def _build_toolbar(self) -> QWidget:
        bar = Surface()
        bar.setObjectName(q.SOURCE_BAR)
        outer = QVBoxLayout(bar)
        outer.setContentsMargins(10, 8, 10, 6)
        outer.setSpacing(4)

        top = QHBoxLayout()
        top.setSpacing(6)
        self._name = QLabel()
        self._name.setObjectName(q.SOURCE_FILE_NAME)
        top.addWidget(self._name)
        self._unsaved_chip = Chip("", "muted")
        top.addWidget(self._unsaved_chip)
        top.addStretch(1)
        self._elsewhere_chip = Chip("", "warning")
        self._elsewhere_chip.clicked.connect(self._show_other_dirty)
        top.addWidget(self._elsewhere_chip)
        self._find_button = IconButton("search", "Find and replace (Ctrl+F, Ctrl+H)")
        self._find_button.clicked.connect(lambda: self._with_file(lambda f: f.find_bar.show_find()))
        top.addWidget(self._find_button)
        self._version_button = Button("Update version", "primary", compact=True)
        self._version_button.clicked.connect(self.update_version)
        self.written.connect(lambda _path: self._update_toolbar())     # an autosave may add the "+"
        top.addWidget(self._version_button)
        outer.addLayout(top)

        self._format_row = Surface()
        row = QHBoxLayout(self._format_row)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(2)
        for label, macro in latex_edit.FORMAT_MACROS:
            button = Button(label, "ghost", compact=True)
            # Each label is drawn in the style it applies: the row is its own legend.
            style = {"I": "font-style: italic;", "B": "font-weight: 700;", "U": "text-decoration: underline;"}
            button.setStyleSheet(style.get(label, ""))
            button.clicked.connect(lambda _=False, m=macro: self._wrap(m))
            row.addWidget(button)
        comment = Button("%", "ghost", compact=True)
        comment.setToolTip("Comment or uncomment the selected lines (Ctrl+/)")
        comment.clicked.connect(lambda: self._edit(lambda e: e.toggle_comment()))
        row.addWidget(comment)
        for label, macro in latex_edit.WORD_MACROS:
            button = Button(label, "ghost", compact=True)
            button.clicked.connect(lambda _=False, m=macro: self._wrap(m))
            row.addWidget(button)
        self._color_button = Button("Color ▾", "ghost", compact=True)
        self._color_button.clicked.connect(self._open_color_menu)
        row.addWidget(self._color_button)
        self._insert_button = Button("Insert ▾", "ghost", compact=True)
        self._insert_button.clicked.connect(self._open_insert_menu)
        row.addWidget(self._insert_button)
        self._cite_button = Button("Cite ▾", "ghost", compact=True)
        self._cite_button.setToolTip("Insert a citation of an entry of Slidemaster.bib")
        self._cite_button.clicked.connect(self._open_citation_popover)
        row.addWidget(self._cite_button)
        row.addStretch(1)
        self._tools_button = Button("Tools ▾", "ghost", compact=True)
        self._tools_button.clicked.connect(self._open_tools_menu)
        row.addWidget(self._tools_button)
        outer.addWidget(self._format_row)
        return bar

    def _build_jump_bar(self) -> QWidget:
        """Slidemaster.bib only: one button per letter jumps to the first entry whose key starts with it."""
        bar = Surface()
        grid = QGridLayout(bar)
        grid.setContentsMargins(10, 4, 10, 4)
        grid.setSpacing(2)
        half = len(LETTERS) // 2
        for i, letter in enumerate(LETTERS):
            button = Button(letter, "ghost", compact=True)
            button.setFixedWidth(32)
            button.clicked.connect(lambda _=False, ltr=letter: self._jump_to_letter(ltr))
            grid.addWidget(button, i // half, i % half)
        grid.setColumnStretch(half, 1)
        bar.setVisible(False)
        return bar

    def _build_frozen_bar(self) -> QWidget:
        bar = Surface()
        row = QHBoxLayout(bar)
        row.setContentsMargins(10, 4, 10, 4)
        label = QLabel("Frozen version, read-only.")
        label.setObjectName(q.SOURCE_NOTE)
        row.addWidget(label)
        row.addStretch(1)
        self._unlock_button = Button("Unlock editing", "ghost", compact=True)
        self._unlock_button.setToolTip(
            "Allow editing this frozen snapshot directly. Normally a past version is never "
            "changed: edit the current slide instead.")
        self._unlock_button.clicked.connect(self._unlock)
        row.addWidget(self._unlock_button)
        restore = Button("Make this the current version", "secondary", compact=True)
        restore.setToolTip("Replace the slide's current content with this version. The current content "
                           "is archived first, as a version of its own.")
        restore.clicked.connect(lambda: self._with_file(lambda f: self.restore_requested.emit(f.path)))
        row.addWidget(restore)
        bar.setVisible(False)
        return bar

    # -- the files ---------------------------------------------------------------------

    @property
    def current(self) -> Optional[SourceFile]:
        return self._current

    def file_for(self, path: Path) -> Optional[SourceFile]:
        return self._files.get(path)

    def dirty_files(self) -> list[SourceFile]:
        """Files whose buffer differs from the file: between a keystroke and its autosave, or for good
        when it cannot be written (see `blocked_files`). Flush first to be left with the latter."""
        return sorted((f for f in self._files.values() if f.dirty), key=lambda f: str(f.path))

    def blocked_files(self) -> list[SourceFile]:
        return [f for f in self.dirty_files() if f.blocked]

    def show_path(self, path: Optional[Path], on_saved: Optional[Callable[[str], None]] = None) -> None:
        """Show `path` (None: nothing). An `on_saved` given for a file that is open
        replaces the one it has."""
        if path is None:
            self._current = None
        else:
            file = self._files.get(path)
            if file is None:
                file = SourceFile(self.app, path, on_saved, on_open=self.app.open_slide_editor)
                file.modified_changed.connect(self._on_modified)
                file.conflict_changed.connect(self._on_modified)
                file.editor.text_changed.connect(lambda p=path: self.buffer_changed.emit(p))
                file.lint_changed.connect(self._emit_lint_errors)
                file.editor.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
                file.editor.customContextMenuRequested.connect(self._on_context_menu)
                file.fix_panel.running_changed.connect(self._on_modified)
                file.saved.connect(lambda p=path: self.saved.emit(p))
                file.written.connect(lambda p=path: self.written.emit(p))
                self._files[path] = file
                self._stack.addWidget(file)
            else:
                file.sync()
                if on_saved is not None:
                    file.on_saved = on_saved
            self._current = file
            self._stack.setCurrentWidget(file)
        if self._current is None:
            self._stack.setCurrentWidget(self._empty)
        for other in self._files.values():
            if other is not self._current:
                other.write_now()       # written before it goes out of view
        for stale in [f for f in self._files.values() if f is not self._current and not f.keep_open]:
            self._drop(stale)
        self._update_toolbar()
        self._emit_lint_errors()

    def _emit_lint_errors(self) -> None:
        lint = self._current.lint if self._current is not None else None
        errors = len(lint.errors) if lint is not None else 0
        if errors != self._lint_errors:
            self._lint_errors = errors
            self.lint_errors_changed.emit(errors)

    def set_message(self, message: str) -> None:
        """What to say when no file is shown."""
        self._empty.setText(message)

    def _drop(self, file: SourceFile) -> None:
        del self._files[file.path]
        self._stack.removeWidget(file)
        file.deleteLater()
        self.file_closed.emit(file.path)

    def _on_modified(self, _modified: bool = False) -> None:
        dirty = any(f.blocked for f in self._files.values())
        self._update_toolbar()
        if dirty != self._dirty:
            self._dirty = dirty
            self.dirty_changed.emit(dirty)

    def buffer(self, path: Optional[Path] = None) -> Optional[tuple[str, str]]:
        """(the whole text, the selected text) of the file shown, if it is a slide. With `path`: of
        that file if it is open here (the current file is not necessarily the previewed slide: the
        Source view is not updated while the centre is in Preview mode)."""
        file = self._current if path is None else self._files.get(path)
        return (file.editor.text(), file.editor.selected_text()) if file is not None and file.is_slide else None

    def selection(self) -> Selection:
        """The text selected in the slide shown, captured now, for an AI task on it. SelectionError says why there is
        none: no slide in view, nothing selected, a frozen (read-only) version, a protected part in the selection."""
        file = self._current
        if file is None or not file.is_slide or not self.isVisibleTo(self.window()):
            raise SelectionError("Open a slide in the Source view and select some of its text.")
        start, end = file.editor.selection_range()
        if start == end:
            raise SelectionError(NO_SELECTION)
        if not file.is_current_slide or file.editor.is_read_only():
            raise SelectionError("This is a frozen version of the slide, which is read-only. Select text in its "
                                 "current version.")
        return capture(file.path, file.editor.text(), start, end)

    def stop_ai_checks(self) -> None:
        """Abort and join every running "Ask AI to fix" check, whichever file it belongs to."""
        for file in self._files.values():
            file.fix_panel.stop()

    def refresh_colors(self) -> None:
        for file in self._files.values():
            file.editor.refresh_colors()

    def set_tab_width(self, chars: int) -> None:
        for file in self._files.values():
            file.editor.set_tab_width(chars)

    def refresh_model_preferences(self, models: list[str]) -> None:
        for file in self._files.values():
            file.refresh_model_preference(models)

    # -- the toolbar -------------------------------------------------------------------

    def _update_toolbar(self) -> None:
        file = self._current
        has = file is not None
        read_only = has and file.editor.is_read_only()
        self._name.setText(file.path.name if has else "")
        self._unsaved_chip.setVisible(has and file.dirty)
        if has and file.conflicted:
            self._unsaved_chip.set_text("Not saved: changed on disk")
            self._unsaved_chip.set_tone("warning")
        elif has and (file.editor.is_read_only() or file.fix_panel.running):
            self._unsaved_chip.set_text("Not saved")
            self._unsaved_chip.set_tone("warning")
        else:
            self._unsaved_chip.set_text("Saving…")
            self._unsaved_chip.set_tone("muted")
        others = [f for f in self.dirty_files() if f is not file and f.blocked]
        self._elsewhere_chip.setVisible(bool(others))
        self._elsewhere_chip.set_text(f"{len(others)} more not saved" if len(others) > 1 else "1 more not saved")
        self._elsewhere_chip.setToolTip("Click to show the next file whose edits could not be saved.")
        self._find_button.setEnabled(has)
        self._version_button.setVisible(has and file.is_current_slide)
        changes, why_not = self._changes_since_version(file) if has and file.is_current_slide else (False, "")
        self._version_button.setEnabled(changes and not read_only)
        self._version_button.setToolTip(VERSION_TIP if changes else why_not)
        self._format_row.setEnabled(has and not read_only)
        self._tools_button.setEnabled(has)
        frozen = has and file.is_slide and not file.is_current_slide
        self._frozen_bar.setVisible(frozen)
        self._unlock_button.setEnabled(read_only)
        self._jump_bar.setVisible(has and file.is_bib)

    @staticmethod
    def _changes_since_version(file: SourceFile) -> tuple[bool, str]:
        """(whether Update version has something to make a version of -- edits waiting for their autosave,
        a "+", or content that differs from the frozen version --, and if not, why not for the tooltip)."""
        if file.dirty:
            return True, ""
        try:
            new, base = slide_versioning.plan_update(file.path, file.id_slug, file.editor.text(), "patch")
        except ValueError as exc:
            return False, str(exc)
        if new == base:     # not frozen yet, but unchanged: the first edit freezes it by itself
            return False, f"No changes since v{slide_versioning.format_dot(base)}."
        return True, ""

    def _with_file(self, action: Callable[[SourceFile], None]) -> None:
        if self._current is not None:
            action(self._current)

    def _edit(self, action: Callable) -> None:
        if self._current is not None and not self._current.editor.is_read_only():
            action(self._current.editor)

    def _wrap(self, macro: str) -> None:
        self._edit(lambda editor: editor.wrap_macro(macro))

    def _unlock(self) -> None:
        self._with_file(SourceFile.unlock)
        self._update_toolbar()

    def _show_other_dirty(self) -> None:
        others = [f for f in self.blocked_files() if f is not self._current]
        if others:
            self.file_requested.emit(others[0].path)

    def _jump_to_letter(self, letter: str) -> None:
        if self._current is not None and not self._current.jump_to_bib_letter(letter):
            self.app.log(f"No .bib entry with a citation key starting with '{letter}'")

    def save(self) -> bool:
        """Ctrl+S: write the file shown now and render it. Whether it is saved."""
        file = self._current
        return file is not None and file.write_now(explicit=True)

    def flush_all(self) -> bool:
        """Write every file's edits now (before a run reads the files, or the window closes).
        Whether all are saved; one in conflict with a change on disk is not."""
        return all([file.write_now() for file in list(self._files.values())])

    def update_version(self) -> None:
        file = self._current
        if file is not None and file.is_current_slide:
            self.version_requested.emit(file.id_slug)

    # -- menus -------------------------------------------------------------------------

    def _popup(self, menu: PopoverMenu, anchor: QWidget) -> None:
        menu.closed.connect(menu.deleteLater)
        menu.popup_below(anchor)

    def _open_color_menu(self) -> None:
        menu = PopoverMenu(self, min_width=220)
        for name in latex_edit.TEXTCOLOR_PALETTE:
            menu.add_item(name, name, swatch=latex_edit.TEXTCOLOR_SWATCHES[name])
        menu.triggered.connect(lambda name: self._wrap(f"textcolor{{{name}}}"))
        self._popup(menu, self._color_button)

    def _open_insert_menu(self) -> None:
        menu = PopoverMenu(self, min_width=340)
        # The two that ask first lead; then the lists, the blocks and the plain commands.
        commands = list(enumerate(INSERT_COMMANDS))
        groups = (("", "cmd", [c for c in commands if c[1].kind in ASKS]),
                  ("Lists", "list", list(enumerate(INSERT_LIST_COMMANDS))),
                  ("Blocks", "block", list(enumerate(INSERT_BLOCK_COMMANDS))),
                  ("Commands", "cmd", [c for c in commands if c[1].kind not in ASKS]))
        for title, prefix, inserts in groups:
            if title:
                menu.add_header(title)
            for i, insert in inserts:
                menu.add_item(f"{prefix}:{i}", insert.label, meta=insert.hint)
        menu.triggered.connect(self._on_insert_chosen)
        self._popup(menu, self._insert_button)

    def _on_insert_chosen(self, key: str) -> None:
        prefix, _, index = key.partition(":")
        inserts = {"list": INSERT_LIST_COMMANDS, "block": INSERT_BLOCK_COMMANDS, "cmd": INSERT_COMMANDS}[prefix]
        self.insert(inserts[int(index)])

    def insert(self, insert: Insert) -> None:
        """Insert at the cursor; hyperlink and code file ask in a popover under the Insert button first."""
        if self._current is None or self._current.editor.is_read_only():
            return
        editor = self._current.editor
        if insert.kind not in ASKS:
            editor.apply_insert(insert)
        elif insert.kind == "hyperlink":
            self._ask(LinkPopover(editor.selected_text()), self._insert_button)
        else:
            self._ask(CodeFilePopover(self.app.project, self._current.bare_id), self._insert_button)

    def _open_citation_popover(self) -> None:
        if self._current is not None and not self._current.editor.is_read_only():
            popover = CitationPopover(self.app.project)
            popover.add_reference_requested.connect(self.add_reference)
            self._ask(popover, self._cite_button)

    def _ask(self, popover: Popover, anchor: QWidget) -> None:
        """Show `popover` under `anchor`; what it chooses replaces the selection."""
        popover.setParent(self, popover.windowFlags())     # owned by the view, not garbage collected
        popover.chosen.connect(self._current.editor.replace_selection)
        popover.closed.connect(popover.deleteLater)
        popover.popup_below(anchor)

    def _open_tools_menu(self) -> None:
        file = self._current
        menu = PopoverMenu(self, min_width=240)
        menu.add_item("reindent", "Reindent", meta="one tab per \\begin level",
                      enabled=file.is_slide and not file.editor.is_read_only())
        menu.add_item("chat", "Ask the chat…", meta="about this slide", enabled=file.is_slide)
        menu.triggered.connect(self._on_tool_chosen)
        self._popup(menu, self._tools_button)

    def _on_tool_chosen(self, key: str) -> None:
        if key == "reindent":
            self.reindent()
        elif key == "chat":
            self.app.focus_chat()

    def reindent(self) -> None:
        file = self._current
        self.app.log(f"Reindented {file.path.name}" if file.editor.reindent()
                     else f"{file.path.name}: indentation already correct")

    def _on_context_menu(self, pos: QPoint) -> None:
        """Right-click in the editor: the edit commands and, in a slide, Rewrite selection and Proofread selection
        (enabled when the selection can be worked on)."""
        editor = self._current.editor
        selected, writable = editor.textCursor().hasSelection(), not editor.is_read_only()
        menu = PopoverMenu(self, min_width=240)
        menu.add_item("undo", "Undo", meta="Ctrl+Z", enabled=writable)
        menu.add_item("redo", "Redo", meta="Ctrl+Y", enabled=writable)
        menu.add_separator()
        menu.add_item("cut", "Cut", meta="Ctrl+X", enabled=selected and writable)
        menu.add_item("copy", "Copy", meta="Ctrl+C", enabled=selected)
        menu.add_item("paste", "Paste", meta="Ctrl+V", enabled=writable)
        menu.add_item("selectAll", "Select all", meta="Ctrl+A")
        if self._current.is_slide:
            menu.add_separator()
            try:
                self.selection()
                usable = True
            except SelectionError:
                usable = False
            add_menu_items(menu, usable)
        menu.triggered.connect(self._on_context_chosen)
        self._popup_at(menu, editor.mapToGlobal(pos))

    def _on_context_chosen(self, key: str) -> None:
        if key == PROOFREAD:
            self.app.assistant.proofread_selection()
        elif key.startswith(REWRITE):
            self.app.assistant.rewrite_selection(key.removeprefix(REWRITE))
        else:
            getattr(self._current.editor, key)()

    def popup_at_selection(self, popup: Popover) -> None:
        """Show `popup` under the cursor, which is at one end of the selection."""
        editor = self._current.editor
        popup.setParent(self, popup.windowFlags())     # owned by the view, not garbage collected
        self._popup_at(popup, editor.viewport().mapToGlobal(editor.cursorRect().bottomLeft()))

    @staticmethod
    def _popup_at(popup: Popover, point: QPoint) -> None:
        popup.closed.connect(popup.deleteLater)
        popup.popup_at(point)

    # -- references --------------------------------------------------------------------

    def add_reference(self, key: str = "") -> None:
        """Add an entry to Slidemaster.bib (with the citation key `key`, if one is missing).
        The dialog writes the file on disk, not a buffer: edits of the .bib are written first,
        or the two would overwrite each other, and an open buffer is reloaded afterwards."""
        bib = self._files.get(self.app.project.bibliography_path)
        if bib is not None and not bib.write_now():
            QMessageBox.warning(self, "Add reference",
                                "Slidemaster.bib has edits that could not be saved (it changed on disk). "
                                "Resolve that first, so the new reference and your edits can't overwrite each other.")
            return
        dialog = CitationDialog(self.app, key)
        if dialog.exec() != CitationDialog.DialogCode.Accepted:
            return
        self.reference_added.emit()
        if bib is None:
            return
        bib.reload()
        if dialog.new_key:
            bib.show_bib_key(dialog.new_key)
