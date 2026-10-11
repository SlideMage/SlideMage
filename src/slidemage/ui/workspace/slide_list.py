"""The slide list, the workspace's left column (UI_REDESIGN_PLAN.md, step 4).

It replaces the old deck editor tab: sections that collapse and rename inline,
a row per slide with its status, and every edit of the deck file -- adding,
removing, moving, changing how a slide is called -- as a click, a key, a drop or
an entry of the right-click menu. All of them go through `deck_editor`; this
widget only decides which function to call, and the window's
`after_deck_edit()` rescans the decks, after which `rebuild()` redraws the
list. The rows come from `deck_outline` (what is shown), the painting and the
drag and drop from `slide_tree`.

Edits can be undone (Ctrl+Z, or the toast's Undo): each keeps the deck text
from before it, a few of them per deck.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import QItemSelectionModel, QPoint, Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ... import deck_editor, deck_outline
from ...deck_editor import BASE_MACROS, StaleFileError, VERSIONED_MACROS
from ...deck_outline import SectionRow, SlideRow
from ...deck_scan import Chapter, Deck
from ...slide_ids import SLIDES_DIR
from ..kit import kit_qss as q
from ..kit.theme import ThemeManager
from ..kit.widgets import Button, IconButton, PopoverMenu, Toast
from .menus import VIEW_LABELS, add_commands
from .slide_tree import SlideTree
from .state import VIEWS, WorkspaceState

UNDO_LIMIT = 20
WIDTH = 280   # the prototype's fixed width of the column
# QAbstractItemView.DropIndicatorPosition: where in a row a drop landed.
ON_ITEM, ABOVE_ITEM, BELOW_ITEM = 0, 1, 2

VARIANT_TITLES = {
    "slide": "Live (follows the current version)",
    "slidefinal": "Final overlay state",
    "omitslide": "Instructor only",
    "conditionalslide": "Only in some views",
    "slidestep": "Reveal steps…",
}


class SlideList(QWidget):
    def __init__(self, app, state: WorkspaceState, theme: ThemeManager, toast: Toast) -> None:
        """`app` is the window: it rescans after an edit (`after_deck_edit`), opens the
        add-slide dialog, the source editor, the preview and the image descriptions, and
        owns the command registry that the context menus show (actions.py)."""
        super().__init__()
        self.app = app
        self.state = state
        self.toast = toast
        self._outline: list[SectionRow] = []
        self._deck_path: Optional[Path] = None
        self._undo: dict[Path, list[str]] = {}
        self.setFixedWidth(WIDTH)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.find = QLineEdit()
        self.find.setObjectName(q.SLIDES_FIND)
        self.find.setPlaceholderText("Find slide by id or title")
        self.find.textChanged.connect(self._apply_filter)
        self.find.returnPressed.connect(self._go_to_first_match)
        escape = QShortcut(QKeySequence(Qt.Key.Key_Escape), self.find)
        escape.setContext(Qt.ShortcutContext.WidgetShortcut)
        escape.activated.connect(self.find.clear)
        layout.addWidget(self.find)

        self.tree = SlideTree(theme, state)
        self.tree.currentItemChanged.connect(self._on_current_changed)
        self.tree.itemSelectionChanged.connect(self._on_selection_changed)
        self.tree.itemDoubleClicked.connect(lambda item, _col: self._open_item(item))
        self.tree.customContextMenuRequested.connect(self._on_context_menu)
        self.tree.command.connect(self._on_command)
        self.tree.moved.connect(self._on_moved, Qt.ConnectionType.QueuedConnection)
        self.tree.delegate.renamed.connect(self._rename_section)
        layout.addWidget(self.tree, 1)

        self.note = QLabel()
        self.note.setObjectName(q.SLIDES_NOTE)
        self.note.setWordWrap(True)
        layout.addWidget(self.note)

        self.bulk_bar = self._build_bulk_bar()
        layout.addWidget(self.bulk_bar)
        self.add_bar = QWidget()
        add_row = QHBoxLayout(self.add_bar)
        add_row.setContentsMargins(0, 4, 0, 0)
        self.add_slide_button = Button("+ Slide", "primary")
        self.add_slide_button.clicked.connect(self._add_slide)
        self.add_section_button = Button("+ Section", "secondary")
        self.add_section_button.clicked.connect(lambda: self._add_section(self._end_point()))
        add_row.addWidget(self.add_slide_button, 1)
        add_row.addWidget(self.add_section_button, 1)
        layout.addWidget(self.add_bar)

        undo = QShortcut(QKeySequence.StandardKey.Undo, self)
        undo.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        undo.activated.connect(self.undo)
        toast.action_triggered.connect(lambda key: self.undo() if key == "undo" else None)

        state.deck_changed.connect(lambda _deck: self.rebuild())
        state.view_changed.connect(lambda _view: self.rebuild())
        state.language_changed.connect(lambda _language: self.rebuild())
        state.focused_slide_changed.connect(self._on_state_focus)
        self.rebuild()

    def _build_bulk_bar(self) -> QWidget:
        bar = QWidget()
        outer = QVBoxLayout(bar)
        outer.setContentsMargins(0, 4, 0, 0)
        outer.setSpacing(6)
        top = QHBoxLayout()
        self.bulk_label = QLabel()
        self.bulk_label.setObjectName(q.SLIDES_BULK_LABEL)
        select_all = Button("Select all", "ghost")
        select_all.clicked.connect(self._select_all)
        clear = IconButton("close", "Clear the selection")
        clear.clicked.connect(self.tree.clearSelection)
        top.addWidget(self.bulk_label, 1)
        top.addWidget(select_all)
        top.addWidget(clear)
        outer.addLayout(top)
        buttons = QHBoxLayout()
        self.bulk_visibility_button = Button("", "primary")
        self.bulk_visibility_button.clicked.connect(self._bulk_toggle_visibility)
        more = Button("More ▾", "secondary")
        more.clicked.connect(lambda: self._popup(self._bulk_menu(), more))
        remove = IconButton("delete_outline", "Remove from the deck")
        remove.clicked.connect(lambda: self._remove(self.tree.selected_rows()))
        buttons.addWidget(self.bulk_visibility_button, 1)
        buttons.addWidget(more)
        buttons.addWidget(remove)
        outer.addLayout(buttons)
        bar.hide()
        return bar

    # -- content -----------------------------------------------------------------

    @property
    def deck(self) -> Optional[Deck]:
        """The deck whose slides are listed (a test deck has none of its own)."""
        deck = self.state.deck
        return None if deck is None or deck.is_test_deck else deck

    def rebuild(self) -> None:
        """Redraw from the deck as it is now; keeps the selection and the focus
        (by what a call is, so an edit elsewhere leaves them), and the scroll position."""
        deck = self.deck
        path = deck.path if deck else None
        same_deck = path == self._deck_path
        selected = {r.key for r in self.tree.selected_rows()} if same_deck else set()
        current = self.tree.data_of(self.tree.currentItem())
        current_key = current.key if same_deck and isinstance(current, SlideRow) else None
        current_index = next((i for i, item in enumerate(self.tree.slide_items())
                              if item is self.tree.currentItem()), 0)
        scroll = self.tree.verticalScrollBar().value()
        if not same_deck:
            self.tree.collapsed.clear()
        self._deck_path = path
        self._outline = (deck_outline.build_outline(deck, self.state.view, self.state.language)
                         if deck else [])
        self.tree.blockSignals(True)
        self.tree.populate(self._outline, VIEW_LABELS[self.state.view], self.state.language)
        items = self.tree.slide_items()
        for item in items:
            item.setSelected(self.tree.data_of(item).key in selected)
        # the focused slide stays; when it is gone (removed, or called differently now)
        # the focus moves to the slide that took its place
        focus = next((i for i in items if self.tree.data_of(i).key == current_key), None)
        if focus is None and current_key is not None and items:
            focus = items[min(current_index, len(items) - 1)]
        if focus is not None:
            self.tree.setCurrentItem(focus, 0, QItemSelectionModel.SelectionFlag.NoUpdate)
        self.tree.blockSignals(False)
        self.tree.verticalScrollBar().setValue(scroll)
        self._apply_filter()
        self.tree.itemSelectionChanged.emit()   # it was blocked while rebuilding
        self._on_current_changed(self.tree.currentItem(), None)
        self.add_bar.setEnabled(deck is not None)

    def _apply_filter(self) -> None:
        words = self.find.text().lower().split()
        matches = 0
        for head in self.tree.section_items():
            shown = 0
            for i in range(head.childCount()):
                row = self.tree.data_of(head.child(i))
                hit = all(w in f"{row.call.id_slug} {row.deck_call.id_slug} {row.title}".lower() for w in words)
                head.child(i).setHidden(not hit)
                shown += hit
            head.setHidden(bool(words) and not shown)
            matches += shown
        self.tree.show_sections(all_open=bool(words))
        if not self.deck:
            self.note.setText("")
        elif not self.tree.slide_items() and not words:
            self.note.setText("This deck has no slides yet.")
        elif not matches:
            self.note.setText("No slide matches. Search all files with Ctrl+K.")
        else:
            self.note.setText("")
        self.note.setVisible(bool(self.note.text()))

    def _go_to_first_match(self) -> None:
        first = next((i for i in self.tree.slide_items() if not i.isHidden()), None)
        if first is not None:
            self.find.clear()
            self.tree.setCurrentItem(first, 0, QItemSelectionModel.SelectionFlag.ClearAndSelect)
            self.tree.scrollToItem(first)
            self.tree.setFocus()

    # -- state <-> tree ------------------------------------------------------------

    def _on_current_changed(self, item: Optional[QTreeWidgetItem], _previous) -> None:
        row = self.tree.data_of(item)
        if isinstance(row, SlideRow):
            self.state.set_focused_slide(row.call.id)

    def _on_state_focus(self, slide_id: Optional[str]) -> None:
        """Another part of the window focused a slide (the source editor, the palette's Go to
        slide): it is shown even if the Find box hides it or its section is closed."""
        item = next((i for i in self.tree.slide_items() if self.tree.data_of(i).matches(slide_id)), None)
        if item is None:
            return
        head = item.parent()
        self.tree.collapsed.discard(self.tree.data_of(head).title)
        if item.isHidden():
            self.find.clear()   # shows every slide again, the sections open as the user left them
        head.setExpanded(True)
        current = self.tree.data_of(self.tree.currentItem())
        if not (isinstance(current, SlideRow) and current.matches(slide_id)):
            self.tree.setCurrentItem(item, 0, QItemSelectionModel.SelectionFlag.ClearAndSelect)
        self.tree.scrollToItem(item)

    def _on_selection_changed(self) -> None:
        rows = self.tree.selected_rows()
        self.state.set_selection(tuple(r.call.id for r in rows))
        self.bulk_bar.setVisible(len(rows) >= 2)
        self.add_bar.setVisible(len(rows) < 2)
        self.bulk_label.setText(f"{len(rows)} slides selected")
        view = self.state.view
        hide = all(r.call.included_in(view) for r in rows)
        self.bulk_visibility_button.setText(f"{'Hide' if hide else 'Show'} in {VIEW_LABELS[view]}")

    def _select_all(self) -> None:
        for item in self.tree.slide_items():
            item.setSelected(not item.isHidden())

    def _current_row(self) -> Optional[SlideRow]:
        row = self.tree.data_of(self.tree.currentItem())
        return row if isinstance(row, SlideRow) else None

    def rows(self) -> list[SlideRow]:
        """Every slide of the deck, in order."""
        return [row for section in self._outline for row in section.rows]

    def targets(self) -> list[SlideRow]:
        """The slides the slide commands act on: the selected ones, else the focused one."""
        return self.tree.selected_rows() or ([self._current_row()] if self._current_row() else [])

    def current_section(self) -> Optional[SectionRow]:
        """The section the section commands act on: the one chosen in the list."""
        section = self.tree.data_of(self.tree.currentItem())
        return section if isinstance(section, SectionRow) else None

    # -- keys and double click -------------------------------------------------------

    def _on_command(self, command: str) -> None:
        current = self.tree.data_of(self.tree.currentItem())
        if command == "open":
            self._open_item(self.tree.currentItem())
        elif command == "remove":
            self._remove(self.tree.selected_rows() or ([current] if isinstance(current, SlideRow) else []))
        elif command == "rename" and isinstance(current, SectionRow) and current.editable:
            self.tree.rename(self.tree.currentItem())
        elif command in ("move_up", "move_down"):
            self._step(-1 if command == "move_up" else 1)

    def _open_item(self, item: Optional[QTreeWidgetItem]) -> None:
        row = self.tree.data_of(item)
        if isinstance(row, SlideRow):
            self._open_source(row)
        elif isinstance(row, SectionRow):
            self.tree.toggle_section(item)

    def _open_source(self, row: SlideRow) -> None:
        self.app.open_slide_editor(SLIDES_DIR / row.call.source_filename)

    def _step(self, delta: int) -> None:
        """Alt+Up/Down: the focused slide passes the item above or below it, a
        section marker included (which puts it into the neighbouring section);
        a focused section passes the section above or below."""
        deck = self.deck
        current = self.tree.data_of(self.tree.currentItem())
        if deck is None:
            return
        if isinstance(current, SectionRow):
            self._step_section(current, delta)
            return
        items = deck_outline.ordered_items(self._outline)
        position = next((i for i, item in enumerate(items) if item is current), None)
        if position is None or not 0 <= position + delta < len(items):
            return
        neighbor = items[position + delta]
        call = current.deck_call
        direction = "up" if delta < 0 else "down"
        if isinstance(neighbor, Chapter):
            move = lambda path, text: deck_editor.move_slide_past_section(path, text, call, neighbor)  # noqa: E731
        else:
            move = lambda path, text: deck_editor.move_slide_call(path, text, call, neighbor.deck_call)  # noqa: E731
        self.edit("Move failed", f"Moved {call.id_slug} {direction} in {deck.name}", move)

    # -- menus --------------------------------------------------------------------

    def _on_context_menu(self, pos: QPoint) -> None:
        item = self.tree.itemAt(pos)
        data = self.tree.data_of(item)
        if isinstance(data, SlideRow):
            if not item.isSelected():
                self.tree.setCurrentItem(item, 0, QItemSelectionModel.SelectionFlag.ClearAndSelect)
            menu = self._bulk_menu() if len(self.tree.selected_rows()) > 1 else self._slide_menu()
        elif isinstance(data, SectionRow):
            self.tree.setCurrentItem(item, 0, QItemSelectionModel.SelectionFlag.NoUpdate)
            menu = self._section_menu()
        else:
            return
        self._popup(menu, self.tree.viewport(), pos)

    def _popup(self, menu: PopoverMenu, anchor: QWidget, pos: Optional[QPoint] = None) -> None:
        menu.closed.connect(menu.deleteLater)
        if pos is None:
            menu.popup_below(anchor)
        else:
            menu.popup_at(anchor.mapToGlobal(pos))

    def _new_menu(self, min_width: int) -> PopoverMenu:
        menu = PopoverMenu(self, min_width=min_width)
        menu.triggered.connect(self._on_menu_chosen)
        return menu

    def _on_menu_chosen(self, key: str) -> None:
        """A registry command, or one of the entries only this list knows (a way to call the
        slide, a section to move to)."""
        if key in self.app.commands:
            self.app.commands.run(key, self.app)
        else:
            self._run(key, self.targets())

    def _slide_menu(self) -> PopoverMenu:
        row = self.targets()[0]
        call = row.deck_call
        menu = self._new_menu(280)
        menu.add_header(f"{row.call.id} · {row.title}")
        add_commands(menu, self.app, ["slide:open", "slide:preview", "slide:images"])
        if not call.editable:
            menu.add_header(f"Read-only here: {call.readonly_reason}")
        menu.add_separator()
        menu.add_header("Call as")
        editable = call.editable
        for macro in BASE_MACROS:
            menu.add_item(f"variant:{macro}", VARIANT_TITLES[macro], meta=f"\\{macro}", enabled=editable,
                          icon="check" if call.macro == macro else "")
        versions = deck_editor.available_versions(row.deck_call.id_slug)
        if row.deck_call.macro in VERSIONED_MACROS and row.deck_call.version not in versions:
            versions.append(row.deck_call.version)
        for version in versions:
            for macro, title in (("slideversion", "Pinned to"), ("omitslideversion", "Instructor only, pinned to")):
                menu.add_item(f"variant:{macro}:{version}", f"{title} v{version}", meta=f"\\{macro}",
                              enabled=editable, icon="check" if (call.macro, call.version) == (macro, version) else "")
        menu.add_separator()
        add_commands(menu, self.app, [f"slide:visible:{view}" for view in VIEWS])
        menu.add_separator()
        add_commands(menu, self.app, ["slide:before", "slide:after", "slide:duplicate", "slide:translate",
                                  "slide:section_before"])
        self._add_move_items(menu, editable)
        menu.add_separator()
        add_commands(menu, self.app, ["slide:remove"])
        return menu

    def _bulk_menu(self) -> PopoverMenu:
        rows = self.targets()
        menu = self._new_menu(260)
        menu.add_header(f"{len(rows)} slides selected")
        add_commands(menu, self.app, [f"slide:visible:{view}" for view in VIEWS])
        self._add_move_items(menu, all(r.call.editable for r in rows))
        menu.add_separator()
        add_commands(menu, self.app, ["compile:slides", "slide:clear", "slide:remove"])
        return menu

    def _add_move_items(self, menu: PopoverMenu, enabled: bool) -> None:
        menu.add_separator()
        menu.add_header("Move to section")
        for index, section in enumerate(self._outline):
            menu.add_item(f"move:{index}", section.title, enabled=enabled)

    def _section_menu(self) -> PopoverMenu:
        menu = self._new_menu(240)
        add_commands(menu, self.app, ["section:rename", "section:add_slide", "section:section_before"])
        menu.add_separator()
        add_commands(menu, self.app, ["section:section_up", "section:section_down"])
        menu.add_separator()
        add_commands(menu, self.app, ["section:remove_section"])
        return menu

    def section_enabled(self, name: str) -> bool:
        """Whether the section command `name` can change the chosen section."""
        section = self.current_section()
        if section is None or self.deck is None:
            return False
        marker = section.chapter is not None
        editable = marker and section.editable
        if name == "section_before":
            return marker
        if name in ("rename", "remove_section"):
            return editable
        if name in ("section_up", "section_down"):
            chapters = self.deck.chapters
            index = chapters.index(section.chapter) if marker and section.chapter in chapters else -1
            target = index + (-1 if name == "section_up" else 1)
            return editable and index >= 0 and 0 <= target < len(chapters) and self._chapter_editable(chapters[target])
        return True

    def _chapter_editable(self, chapter: Chapter) -> bool:
        return deck_editor.section_editable(self.deck.text, chapter)

    def run(self, name: str) -> None:
        """A slide command of the registry: it acts on `targets()`."""
        targets = self.targets()
        if targets:
            self._run(name, targets)

    def run_section(self, name: str) -> None:
        """A section command of the registry: it acts on the chosen section."""
        section = self.current_section()
        if section is not None:
            self._run_section(name, section)

    def _run(self, key: str, targets: list[SlideRow]) -> None:
        """A slide command, `name` or `name:argument`, on the slides `targets`."""
        name, _, arg = key.partition(":")
        target = targets[0]
        if name == "open":
            self._open_source(target)
        elif name == "preview":
            self.state.set_focused_slide(target.call.id)
            self.state.set_mode("preview")
        elif name == "images":
            self.app.open_images_for_slide(target.call.id_slug)
        elif name == "variant":
            macro, _, version = arg.partition(":")
            self._change_variant(target, macro, version or None)
        elif name == "visible":
            self._set_visibility(targets, arg, not all(r.call.included_in(arg) for r in targets))
        elif name == "before":
            self._open_add(target.call.line_start, target.call.indent, f"before {target.call.id_slug}",
                           target.call.id_slug)
        elif name == "after":
            self._open_add(target.call.line_end, target.call.indent, f"after {target.call.id_slug}",
                           target.call.id_slug)
        elif name in ("duplicate", "translate"):
            self.add_slide(name, target.call.id_slug, arg or None)
        elif name == "section_before":
            self._add_section(target.call.line_start)
        elif name == "move":
            self._move_to_section(targets, self._outline[int(arg)])
        elif name == "remove":
            self._remove(targets)
        elif name == "clear":
            self.tree.clearSelection()

    def _run_section(self, name: str, section: SectionRow) -> None:
        deck = self.deck
        if name == "rename":
            self.tree.rename(next(h for h in self.tree.section_items() if self.tree.data_of(h) is section))
        elif name == "add_slide":
            self._add_slide_to(section)
        elif name == "section_before":
            self._add_section(deck_editor.section_line_span(deck.text, section.chapter)[0])
        elif name in ("section_up", "section_down"):
            self._step_section(section, -1 if name == "section_up" else 1)
        elif name == "remove_section":
            self.edit("Remove section failed", f"Removed section {section.title} from {deck.name}",
                       lambda path, text: deck_editor.remove_section(path, text, section.chapter))

    def _step_section(self, section: SectionRow, delta: int) -> None:
        chapters = self.deck.chapters
        index = chapters.index(section.chapter) + delta if section.chapter in chapters else -1
        if 0 <= index < len(chapters):
            self.edit(
                "Move section failed",
                f"Moved section {section.title} {'up' if delta < 0 else 'down'} in {self.deck.name}",
                lambda path, text: deck_editor.move_section(path, text, section.chapter, chapters[index]))

    # -- edits ---------------------------------------------------------------------

    def edit(self, failed: str, summary: str, change: Callable[[Path, str], str]) -> bool:
        """Run `change(deck path, deck text)` (a deck_editor function); on success the
        window rescans and calls deck_edited(). False when it was refused or changed nothing."""
        deck = self.deck
        previous = deck.text
        try:
            new = change(deck.path, previous)
        except (StaleFileError, ValueError) as exc:
            QMessageBox.critical(self, failed, str(exc))
            return False
        if new == previous:
            return False
        self.app.after_deck_edit(deck.path, summary, previous_text=previous)
        return True

    def deck_edited(self, deck_path: Path, summary: str, previous_text: Optional[str]) -> None:
        """The window's after_deck_edit() calls this once the deck is rescanned: remember
        the text from before, so that the edit can be undone, and say what happened."""
        if previous_text is None:
            self.toast.show_message(summary)
            return
        stack = self._undo.setdefault(deck_path, [])
        stack.append(previous_text)
        del stack[:-UNDO_LIMIT]
        self.toast.show_message(summary, [("undo", "Undo")])

    def undo(self) -> None:
        deck = self.deck
        stack = self._undo.get(deck.path) if deck else None
        if not stack:
            return
        previous = stack.pop()
        try:
            deck_editor.restore_deck_text(deck.path, deck.text, previous)
        except StaleFileError as exc:
            stack.append(previous)
            QMessageBox.critical(self, "Undo failed", str(exc))
            return
        self.app.after_deck_edit(deck.path, f"Undid last change to {deck.name}")

    def _change_variant(self, row: SlideRow, macro: str, version: Optional[str]) -> None:
        call = row.deck_call
        steps = None
        if macro == "slidestep":
            steps, accepted = QInputDialog.getText(
                self, "Reveal steps",
                "Steps typeset for this call (beamer overlay list, e.g. 1,2 or 2- or 1-2,4):",
                text=call.steps or deck_editor.DEFAULT_STEPS)
            if not accepted:
                return
        conditions = call.conditions if macro in deck_editor.CONDITIONAL_MACROS else None
        self.edit(
            "Change variant failed",
            f"Changed {call.id_slug} in {self.deck.name}: \\{call.macro} -> \\{macro}",
            lambda path, text: deck_editor.change_slide_call_variant(
                path, text, call, macro, version, conditions, steps))

    def _set_visibility(self, rows: list[SlideRow], view: str, visible: bool) -> None:
        calls = [r.deck_call for r in rows]
        what = ", ".join(c.id_slug for c in calls)
        self.edit(
            "Change failed",
            f"{'Showed' if visible else 'Hid'} {what} in {VIEW_LABELS[view]} of {self.deck.name}",
            lambda path, text: deck_editor.set_calls_visibility(path, text, calls, view, visible))

    def _bulk_toggle_visibility(self) -> None:
        rows = self.tree.selected_rows()
        view = self.state.view
        self._set_visibility(rows, view, not all(r.call.included_in(view) for r in rows))

    def _remove(self, rows: list[SlideRow]) -> None:
        if not rows:
            return
        calls = list({c.call_start: c for r in rows for c in (r.deck_call, *r.folded_calls)}.values())
        what = calls[0].id_slug if len(calls) == 1 else f"{len(calls)} slides ({', '.join(c.id_slug for c in calls)})"
        self.edit("Remove failed", f"Removed {what} from {self.deck.name}",
                   lambda path, text: deck_editor.remove_slide_calls(path, text, calls))

    def _end_point(self) -> int:
        return deck_editor.end_insert_point(self.deck.text)

    def _add_slide(self) -> None:
        self.add_slide()

    def add_slide(self, source: str = "new", id_slug: Optional[str] = None, target: Optional[str] = None) -> None:
        """Open the Add slide sheet on `source`, for a place after the slide `id_slug` (the
        focused one by default), else at the end of the deck. Duplicate and Translate start from
        that slide, a translation on the language `target`."""
        deck = self.deck
        row = (next((r for r in self.rows() if r.call.id_slug == id_slug), None) if id_slug
               else self._current_row())
        if row is not None:
            self._open_add(row.call.line_end, row.call.indent, f"after {row.call.id_slug}",
                           row.call.id_slug, source, target)
            return
        try:
            insert_at, indent = (deck_editor.append_position(deck) if self.tree.slide_items()
                                 else deck_editor.empty_deck_insert_point(deck.text))
        except ValueError as exc:
            QMessageBox.critical(self, "Add slide", str(exc))
            return
        self._open_add(insert_at, indent, "at the end of the deck", id_slug, source, target)

    def _add_slide_to(self, section: SectionRow) -> None:
        deck = self.deck
        calls = [r.deck_call for r in section.rows]
        indent = calls[-1].indent if calls else "\t"
        try:
            insert_at = deck_editor.section_append_point(deck, section.chapter)
        except ValueError as exc:
            QMessageBox.critical(self, "Add slide", str(exc))
            return
        self._open_add(insert_at, indent, f"at the end of {section.title}", None)

    def _open_add(self, insert_at: int, indent: str, where: str, slide: Optional[str], source: str = "new",
                  target: Optional[str] = None) -> None:
        self.app.open_add_slide_dialog(self.deck, insert_at, indent, where=where, source=source, slide=slide,
                                       target=target)

    def _add_section(self, insert_at: int) -> None:
        title, accepted = QInputDialog.getText(self, "Add section", "Section title:")
        if accepted:
            self.edit("Add section failed", f"Added section {title.strip()} in {self.deck.name}",
                       lambda path, text: deck_editor.add_section(path, text, title, insert_at))

    def _rename_section(self, section: SectionRow, title: str) -> None:
        if title.strip() and title.strip() != section.title:
            collapsed = self.tree.collapsed
            was_closed = section.title in collapsed
            if was_closed:          # the rebuild after the edit must find the new title closed
                collapsed.discard(section.title)
                collapsed.add(title.strip())
            if not self.edit("Rename section failed", f"Renamed section {section.title} in {self.deck.name}",
                              lambda path, text: deck_editor.rename_section(path, text, section.chapter, title)) \
                    and was_closed:
                collapsed.discard(title.strip())
                collapsed.add(section.title)

    def _move_to_section(self, rows: list[SlideRow], section: SectionRow) -> None:
        try:
            insert_at = deck_editor.section_append_point(self.deck, section.chapter)
        except ValueError as exc:
            QMessageBox.critical(self, "Move failed", str(exc))
            return
        self._move_slides(rows, insert_at, f"to {section.title}")

    def _move_slides(self, rows: list[SlideRow], insert_at: int, where: str) -> None:
        calls = [r.deck_call for r in rows]
        self.edit("Move failed", f"Moved {', '.join(c.id_slug for c in calls)} {where}",
                   lambda path, text: deck_editor.move_slide_calls(path, text, calls, insert_at))

    # -- drag and drop ---------------------------------------------------------------

    def _on_moved(self, sources: list, target, position: int) -> None:
        """Slides (or a section) were dropped on `target`, a slide row or a section
        heading, at `position` (ON_ITEM, ABOVE_ITEM, BELOW_ITEM)."""
        deck = self.deck
        if deck is None:
            return
        if isinstance(sources[0], SectionRow):
            self._move_section_to(sources[0], target)
            return
        if isinstance(target, SlideRow):
            insert_at = target.call.line_start if position == ABOVE_ITEM else target.call.line_end
        elif target.chapter is None or position == ON_ITEM:
            insert_at = deck_editor.section_append_point(deck, target.chapter)
        else:
            start, end = deck_editor.section_line_span(deck.text, target.chapter)
            insert_at = start if position == ABOVE_ITEM else end
        self._move_slides(sources, insert_at,
                          f"to {target.title}" if isinstance(target, SectionRow) else f"next to {target.call.id}")

    def _move_section_to(self, section: SectionRow, target) -> None:
        """A section dropped on another one (or on one of its slides) takes its place."""
        owner = target if isinstance(target, SectionRow) else next(
            (s for s in self._outline if any(r is target for r in s.rows)), None)
        chapters = self.deck.chapters
        if owner is None or owner.chapter is None or owner is section or section.chapter is None:
            return
        index = chapters.index(owner.chapter)
        self.edit("Move section failed", f"Moved section {section.title} in {self.deck.name}",
                   lambda path, text: deck_editor.move_section_to(path, text, section.chapter, index))
