"""The command palette, Ctrl+K (⌘K on a Mac): one box for everything (UI_REDESIGN_PLAN.md, step 8).

A centred overlay over the window. Typing filters, word by word, the commands of the
registry (actions.py, grouped as there; "Slide 1y8" holds what acts on the focused slide),
the slides of the open deck and the other slides of the project ("Go to slide"), and the
decks ("Go to deck"). From three characters on, the project's source files are searched
for the text too (slide_search.py) on a worker thread, started a moment after the last key
and cancelled when the text changes, so that typing stays fast. "Ask the chat" sends the text
to the chat (about the focused slide).

Keys: ↑ ↓ move, ↵ runs, Esc closes; a click on a row runs it, a click outside closes.

It replaces the Go to slide… box and the slide text search dialog: the first is "Go to
slide", the second "Text in project files", which opens the file at the line of the match.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Optional

import shiboken6
from PySide6.QtCore import QEvent, QObject, QThread, QTimer, Qt, Signal
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QApplication, QFrame, QHBoxLayout, QLabel, QLineEdit, QScrollArea, QVBoxLayout, QWidget

from ... import slide_ids, slide_language, slide_search
from .. import background
from ..kit import kit_qss as q
from ..kit.widgets import Chip, MenuRow, apply_shadow, clear_layout, set_property
from .chat.session import current_route

MIN_TEXT_QUERY = 3    # characters before the files are searched
DEBOUNCE_MS = 200     # a pause after the last key before they are
MAX_SLIDES = 8
MAX_DECKS = 5
MAX_HITS = 10
CARD_WIDTH = 620      # the prototype's
CARD_TOP = 110
LIST_HEIGHT = 440

GROUP_ICONS = {"View & build": "play_arrow", "Slide": "slideshow", "Section": "view_agenda", "Deck": "folder_open",
               "Project": "settings", "Go to slide": "arrow_forward", "Go to deck": "arrow_forward",
               "Text in project files": "description", "Chat": "chat"}
GO_TO_SLIDE, GO_TO_DECK, TEXT_HITS, CHAT = "Go to slide", "Go to deck", "Text in project files", "Chat"


@dataclass
class Entry:
    group: str                  # the heading it is listed under
    label: str
    run: Optional[Callable[[], None]]
    icon: str = ""
    meta: str = ""
    detail: str = ""            # a second, muted line
    tone: str = ""
    enabled: bool = True


def words_of(query: str) -> list[str]:
    return query.lower().split()


def matches(words: list[str], *texts: str) -> bool:
    """Every word is in one of the texts (case-insensitive); no words match everything."""
    haystack = " ".join(texts).lower()
    return all(word in haystack for word in words)


def command_entries(window, words: list[str]) -> list[Entry]:
    """The visible commands of the registry whose label or group matches, in registry order."""
    targets = window.slide_list.targets()
    titles = {
        "Slide": f"Slide {targets[0].call.id}" if len(targets) == 1 else f"{len(targets)} slides",
        "Section": f"Section {section.title}" if (section := window.slide_list.current_section()) else "Section",
    }
    entries = []
    for command in window.commands:
        if not command.visible(window):
            continue
        group = titles.get(command.group, command.group)
        label = command.title(window)
        if matches(words, label, group):
            entries.append(Entry(
                group, label, lambda c=command: window.commands.run(c.id, window), command.icon or
                GROUP_ICONS[command.group], command.info(window), tone=command.tone, enabled=command.enabled(window)))
    return entries


def slide_entries(window, words: list[str], project_slugs: list[str]) -> list[Entry]:
    """The slides of the open deck whose id or title match, then the project's other slides
    whose id-slug does."""
    entries = []
    state = window.state
    in_deck = set()
    for row in window.slide_list.rows():
        call = row.call
        in_deck.add(call.id_slug)
        in_deck.add(row.deck_call.id_slug)
        in_deck.update(c.id_slug for c in row.folded_calls)
        in_deck.update(slug for slide_id in row.related_ids
                       if (slug := slide_language.current_id_slug_for_bare_id(slide_id)))
        if matches(words, call.id_slug, row.deck_call.id_slug, row.title):
            entries.append(Entry(GO_TO_SLIDE, f"{call.id} · {row.title}",
                                 lambda i=call.id: state.set_focused_slide(i), GROUP_ICONS[GO_TO_SLIDE], call.id_slug))
    for id_slug in project_slugs:
        if id_slug not in in_deck and matches(words, id_slug):
            entries.append(Entry(GO_TO_SLIDE, id_slug,
                                 lambda s=id_slug: window.open_slide_editor(window.project.slides_dir / slide_language.current_name(s)),
                                 GROUP_ICONS[GO_TO_SLIDE], "not in this deck"))
    return entries[:MAX_SLIDES]


def deck_entries(window, words: list[str]) -> list[Entry]:
    current = window.state.deck
    decks = [d for d in window.decks if matches(words, d.name) and not (current and d.path == current.path)]
    return [Entry(GO_TO_DECK, d.name, lambda d=d: window.state.set_deck(d), GROUP_ICONS[GO_TO_DECK],
                  "archived" if d.archived else d.group) for d in decks[:MAX_DECKS]]


def hit_entries(window, hits: list[slide_search.SearchHit]) -> list[Entry]:
    group = TEXT_HITS if len(hits) <= MAX_HITS else f"{TEXT_HITS} ({MAX_HITS} of {len(hits)})"
    return [Entry(group, hit.title, lambda h=hit: window.open_slide_editor(h.path, line=h.line),
                  GROUP_ICONS[TEXT_HITS], f"line {hit.line}", detail=hit.snippet) for hit in hits[:MAX_HITS]]


class _SearchWorker(QThread):
    """Searches the project's files for `query`; stopped through requestInterruption()."""

    found = Signal(str, list)

    def __init__(self, query: str) -> None:
        super().__init__()
        self.query = query

    def run(self) -> None:
        hits = slide_search.search_project(self.query, cancelled=self.isInterruptionRequested)
        if not self.isInterruptionRequested():
            self.found.emit(self.query, hits)


class CommandPalette(QWidget):
    def __init__(self, window) -> None:
        """`window` is the command context: it also has `slide_list`, `decks` and `open_slide_editor`."""
        super().__init__(window)
        self._window = window
        self._entries: list[Entry] = []
        self._rows: list[MenuRow] = []
        self._current = -1
        self._project_slugs: list[str] = []
        self._hits: list[slide_search.SearchHit] = []
        self._hits_query = ""
        self._worker: Optional[_SearchWorker] = None
        self._previous_focus: Optional[QWidget] = None   # gets the keyboard back when the palette closes
        self.setObjectName(q.PALETTE)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        self._card = QFrame(self)
        self._card.setObjectName(q.PALETTE_CARD)
        apply_shadow(self._card, "modal")
        outer = QVBoxLayout(self._card)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        head = QFrame()
        head.setObjectName(q.PALETTE_HEAD)
        row = QHBoxLayout(head)
        row.setContentsMargins(18, 12, 18, 12)
        row.setSpacing(10)
        self._chip = Chip("", "neutral")
        row.addWidget(self._chip)
        self.input = QLineEdit()
        self.input.setObjectName(q.PALETTE_INPUT)
        self.input.setPlaceholderText("Type a command, a slide, text in any file, or a question…")
        self.input.textChanged.connect(self._on_text)
        self.input.installEventFilter(self)
        row.addWidget(self.input, 1)
        esc = QLabel("esc")
        esc.setObjectName(q.PALETTE_KEYS)
        row.addWidget(esc)
        outer.addWidget(head)
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list = QWidget()
        self._list_layout = QVBoxLayout(self._list)
        self._list_layout.setContentsMargins(8, 8, 8, 8)
        self._list_layout.setSpacing(0)
        self._scroll.setWidget(self._list)
        outer.addWidget(self._scroll)
        foot = QFrame()
        foot.setObjectName(q.PALETTE_FOOT)
        keys = QHBoxLayout(foot)
        keys.setContentsMargins(18, 10, 18, 10)
        keys.setSpacing(16)
        for hint in ("↑↓ move", "↵ run", "esc close"):
            keys.addWidget(QLabel(hint))
        keys.addStretch(1)
        outer.addWidget(foot)

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(DEBOUNCE_MS)
        self._debounce.timeout.connect(self._start_search)
        window.installEventFilter(self)
        self.hide()

    # -- opening and closing ------------------------------------------------------------

    def toggle(self) -> None:
        if self.isVisible():
            self.hide()
        else:
            self.open()

    def open(self) -> None:
        self._previous_focus = QApplication.focusWidget()
        self._project_slugs = slide_ids.list_id_slugs()
        focused = self._window.state.focused_slide
        self._chip.setVisible(focused is not None)
        self._chip.set_text(focused or "")
        self.input.clear()
        self._place()
        self.show()
        self.raise_()
        self.input.setFocus()
        self._refresh()

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        self.stop_search()
        if self._previous_focus is not None and shiboken6.isValid(self._previous_focus):
            self._previous_focus.setFocus()

    def stop_search(self, wait_ms: int = 0) -> None:
        """Stop the search thread, which is kept until it has ended; typing does not wait for that, the
        window (which calls this on close, too) gives it a moment."""
        self._debounce.stop()
        worker, self._worker = self._worker, None
        if worker is not None:
            background.stop_worker(worker, wait_ms=wait_ms)

    def _place(self) -> None:
        window = self._window
        self.setGeometry(window.rect())
        width = min(CARD_WIDTH, window.width() - 32)
        self._card.setFixedWidth(width)
        self._card.adjustSize()
        self._card.move((window.width() - width) // 2, min(CARD_TOP, max(8, window.height() - self._card.height() - 8)))

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if obj is self._window and event.type() == QEvent.Type.Resize and self.isVisible():
            self._place()
        elif obj is self.input and event.type() == QEvent.Type.KeyPress:
            return self._on_key(event)
        return super().eventFilter(obj, event)

    def _on_key(self, event: QKeyEvent) -> bool:
        key = event.key()
        if key == Qt.Key.Key_Down:
            self._step(1)
        elif key == Qt.Key.Key_Up:
            self._step(-1)
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._run(self._current)
        elif key == Qt.Key.Key_Escape:
            self.hide()
        else:
            return False
        return True

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if not self._card.geometry().contains(event.position().toPoint()):
            self.hide()

    # -- what is listed ----------------------------------------------------------------

    def _query(self) -> str:
        return self.input.text().strip()

    def _on_text(self, _text: str) -> None:
        self.stop_search()
        self._hits, self._hits_query = [], ""
        self._refresh()
        if len(self._query()) >= MIN_TEXT_QUERY:
            self._debounce.start()

    def _refresh(self) -> None:
        """List what matches the text now; the entry that was current stays so if it is still there."""
        query = self._query()
        words = words_of(query)
        before = self._entries[self._current] if 0 <= self._current < len(self._entries) else None
        entries = command_entries(self._window, words)
        if words:
            entries += slide_entries(self._window, words, self._project_slugs)
            entries += deck_entries(self._window, words)
        if self._hits_query == query:
            entries += hit_entries(self._window, self._hits)
        if len(query) >= MIN_TEXT_QUERY:
            entries.append(Entry(CHAT, f"Ask the chat: “{query}”", lambda: self._window.ask_chat(query),
                                 GROUP_ICONS[CHAT], current_route(self._window.project).label))
        self._entries = entries
        self._show_entries()
        kept = next((i for i, e in enumerate(entries) if before and (e.group, e.label) == (before.group, before.label)),
                    None)
        self._set_current(kept if kept is not None else self._first_enabled())

    def _show_entries(self) -> None:
        layout = self._list_layout
        clear_layout(layout)
        self._rows, self._current = [], -1
        group = None
        for index, entry in enumerate(self._entries):
            if entry.group != group:
                group = entry.group
                header = QLabel(group)
                header.setObjectName(q.MENU_HEADER)
                layout.addWidget(header)
                header.show()   # added to a shown parent
            row = MenuRow(str(index), entry.label, entry.meta, entry.icon, entry.tone, True, "", entry.detail)
            row.setEnabled(entry.enabled)
            row.setProperty("off", not entry.enabled)
            row.activated.connect(lambda key: self._run(int(key)))
            row.hovered.connect(lambda r: self._set_current(self._rows.index(r)))
            layout.addWidget(row)
            row.show()
            self._rows.append(row)
        layout.addStretch(1)
        self._scroll.setFixedHeight(min(LIST_HEIGHT, layout.sizeHint().height()))
        self._card.adjustSize()

    # -- moving and running --------------------------------------------------------------

    def _first_enabled(self) -> int:
        return next((i for i, e in enumerate(self._entries) if e.enabled), -1)

    def _set_current(self, index: int) -> None:
        if 0 <= self._current < len(self._rows):
            set_property(self._rows[self._current], "current", False)
        self._current = index
        if 0 <= index < len(self._rows):
            set_property(self._rows[index], "current", True)
            self._scroll.ensureWidgetVisible(self._rows[index])

    def _step(self, delta: int) -> None:
        enabled = [i for i, e in enumerate(self._entries) if e.enabled]
        if not enabled:
            return
        later = [i for i in enabled if (i - self._current) * delta > 0]
        self._set_current((later[0] if delta > 0 else later[-1]) if later else (enabled[0] if delta > 0 else enabled[-1]))

    def _run(self, index: int) -> None:
        if not 0 <= index < len(self._entries):
            return
        entry = self._entries[index]
        if entry.enabled and entry.run is not None:
            self.hide()
            entry.run()

    # -- the text search -----------------------------------------------------------------

    def _start_search(self) -> None:
        query = self._query()
        if len(query) < MIN_TEXT_QUERY:
            return
        self.stop_search()
        self._worker = _SearchWorker(query)
        self._worker.found.connect(self._on_found)
        self._worker.start()

    def _on_found(self, query: str, hits: list) -> None:
        if self.isVisible() and query == self._query():
            self._hits, self._hits_query = hits, query
            self._refresh()
