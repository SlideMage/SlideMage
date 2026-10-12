"""The Source view: a compact toolbar over the editor of the file being edited.

It edits slides, a deck's own .tex file and Slidemaster.bib alike, one
`SourceFile` (source_file.py) per file. A file with unsaved edits stays open
when another is shown, so that switching slides never loses an edit; a clean
one is dropped and read from disk again when it comes back, so it is never
stale. The view reports "dirty" and "saved" and asks the window, through the
signals, for what is not its own: rendering the buffer, restoring a frozen
version, showing another file.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import Qt, Signal
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

from ... import latex_edit
from ...latex_edit import ASKS, INSERT_BLOCK_COMMANDS, INSERT_COMMANDS, INSERT_LIST_COMMANDS, Insert
from ..dialogs.citation import CitationDialog
from ..kit import kit_qss as q
from ..kit.widgets import Button, Chip, IconButton, Popover, PopoverMenu, Surface
from .insert_popovers import CitationPopover, CodeFilePopover, LinkPopover
from .source_file import SourceFile

LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


class SourcePane(Surface):
    dirty_changed = Signal(bool)         # some file has unsaved edits
    buffer_changed = Signal(object)      # Path; every text edit, even while already dirty
    file_closed = Signal(object)         # the Path of a file the view no longer holds
    lint_errors_changed = Signal(int)    # errors the static check finds in the file shown
    saved = Signal(object)               # the Path that was saved
    render_requested = Signal()          # Ctrl+R: render the buffer
    restore_requested = Signal(object)   # Path of a frozen version to make current
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

        # Scoped to this view's widgets. Ctrl+S is the window's (window.py): it saves the file shown here
        # from every view.
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
        self._unsaved_chip = Chip("Unsaved changes", "warning")
        top.addWidget(self._unsaved_chip)
        top.addStretch(1)
        self._elsewhere_chip = Chip("", "warning")
        self._elsewhere_chip.clicked.connect(self._show_other_dirty)
        top.addWidget(self._elsewhere_chip)
        self._find_button = IconButton("search", "Find and replace (Ctrl+F, Ctrl+H)")
        self._find_button.clicked.connect(lambda: self._with_file(lambda f: f.find_bar.show_find()))
        top.addWidget(self._find_button)
        self._revert_button = Button("Revert", "ghost", compact=True)
        self._revert_button.setToolTip("Discard the unsaved changes and reload the saved file.")
        self._revert_button.clicked.connect(lambda: self._with_file(SourceFile.revert))
        top.addWidget(self._revert_button)
        self._save_button = Button("Save", "primary", compact=True)
        self._save_button.setToolTip("Save (Ctrl+S). A slide asks how significant the change is.")
        self._save_button.clicked.connect(self.save)
        top.addWidget(self._save_button)
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
        return sorted((f for f in self._files.values() if f.dirty), key=lambda f: str(f.path))

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
                file.editor.text_changed.connect(lambda p=path: self.buffer_changed.emit(p))
                file.lint_changed.connect(self._emit_lint_errors)
                file.saved.connect(lambda p=path: self.saved.emit(p))
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
        dirty = any(f.dirty for f in self._files.values())
        self._update_toolbar()
        if dirty != self._dirty:
            self._dirty = dirty
            self.dirty_changed.emit(dirty)

    def buffer(self) -> Optional[tuple[str, str]]:
        """(the whole text, the selected text) of the file shown, if it is a slide."""
        file = self._current
        return (file.editor.text(), file.editor.selected_text()) if file is not None and file.is_slide else None

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
        others = [f for f in self.dirty_files() if f is not file]
        self._elsewhere_chip.setVisible(bool(others))
        self._elsewhere_chip.set_text(f"{len(others)} more unsaved" if len(others) > 1 else "1 more unsaved")
        self._elsewhere_chip.setToolTip("Click to show the next file with unsaved changes.")
        self._find_button.setEnabled(has)
        self._revert_button.setEnabled(has and file.dirty)
        self._save_button.setEnabled(has and not read_only)
        self._format_row.setEnabled(has and not read_only)
        self._tools_button.setEnabled(has)
        frozen = has and file.is_slide and not file.is_current_slide
        self._frozen_bar.setVisible(frozen)
        self._unlock_button.setEnabled(read_only)
        self._jump_bar.setVisible(has and file.is_bib)

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
        others = [f for f in self.dirty_files() if f is not self._current]
        if others:
            self.file_requested.emit(others[0].path)

    def _jump_to_letter(self, letter: str) -> None:
        if self._current is not None and not self._current.jump_to_bib_letter(letter):
            self.app.log(f"No .bib entry with a citation key starting with '{letter}'")

    def save(self) -> bool:
        file = self._current
        return file is not None and not file.editor.is_read_only() and file.save()

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
            self._ask(CodeFilePopover(self._current.bare_id), self._insert_button)

    def _open_citation_popover(self) -> None:
        if self._current is not None and not self._current.editor.is_read_only():
            popover = CitationPopover()
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

    # -- references --------------------------------------------------------------------

    def add_reference(self, key: str = "") -> None:
        """Add an entry to Slidemaster.bib (with the citation key `key`, if one is missing).
        The dialog writes the file on disk, not a buffer: unsaved edits of the .bib are saved
        first, or the two would overwrite each other, and an open buffer is reloaded afterwards."""
        bib = self._files.get(self.app.project.bibliography_path)
        if bib is not None and bib.dirty:
            reply = QMessageBox.question(
                self, "Add reference",
                "Slidemaster.bib has unsaved changes. Save them first, so the new reference "
                "and your edits can't overwrite each other?")
            if reply != QMessageBox.StandardButton.Yes or not bib.save():
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
