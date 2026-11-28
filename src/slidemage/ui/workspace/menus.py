# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The window's menu bar, the top bar's menus (deck switcher, Compile caret menu) and the
helper the slide list's context menus use too.

A menu here is only a layout, which commands in which sections; the labels, the
shortcuts and when an entry is available come from the command registry
(actions.py). The item keys are command ids, which `WorkspaceWindow.run_command`
runs. The menu bar (MENU_BAR) lists the commands people reach for; the rest (the other PDF variants,
Pages of the selected slides, ...) stay in the ⌘K palette and the right-click menus.
"""
from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import NamedTuple, Optional

from PySide6.QtCore import Signal
from PySide6.QtGui import QAction, QActionGroup
from PySide6.QtWidgets import QLabel, QMenu, QMenuBar, QWidget, QWidgetAction

from ...ai import routes
from ...deck_groups import DEFAULT_GROUPS, ROLE_PINNED, TAG_MANUAL, DeckGroup, headings, switcher_order
from ...deck_scan import Deck
from ...transcript import STUDENT_VERSIONS
from ..commands import Context
from ..kit import kit_qss as q
from ..kit.widgets import PopoverMenu, set_property

VIEW_LABELS = {
    "instructor": "Instructor",
    "during-course": "During course",
    "after-course": "After course",
}

# The section of the decks whose tags name no group of the project's list (and that has no fallback group).
OTHER_DECKS = "Other decks"
# The heading of a pinned group (the Workdeck group by default) whose own heading is empty.
PINNED_DECKS = "Pinned"


def deck_sections(decks: Iterable[Deck], groups: Sequence[DeckGroup] = DEFAULT_GROUPS) -> list[tuple[str, list[Deck]]]:
    """The deck switcher's sections top to bottom, (heading, decks) per group of the project's list and the
    manual's, empty ones included; a pinned group without a heading of its own is headed "Pinned". A deck in several groups is listed under
    each of them, the same way (2026-10-23). Decks in no group follow in OTHER_DECKS, before the manual and the
    test decks, a section only when there is one."""
    decks = list(decks)
    titles = headings(groups)
    for group in groups:
        if ROLE_PINNED in group.roles and not titles[group.tag]:
            titles[group.tag] = PINNED_DECKS
    sections = [(titles[tag], [d for d in decks if tag in d.groups]) for tag in switcher_order(groups)]
    ungrouped = [d for d in decks if not d.groups]
    if ungrouped:
        order = switcher_order(groups)
        sections.insert(order.index(TAG_MANUAL), (OTHER_DECKS, ungrouped))
    return sections


def deck_key(deck: Deck) -> str:
    return str(deck.path)


def build_deck_menu(parent: QWidget, decks: list[Deck], current: Optional[Deck],
                    groups: Sequence[DeckGroup] = DEFAULT_GROUPS, archived: bool = False) -> PopoverMenu:
    """The active decks by group (`groups`, the project's list); with `archived`, only the archived decks instead
    (Deck ▸ Archived decks…): the regular switcher does not list them."""
    menu = PopoverMenu(parent, min_width=300)
    menu.current_key = deck_key(current) if current is not None else ""
    if archived:
        gone = [d for d in decks if d.archived]
        menu.add_header(f"Archived decks ({len(gone)})")
        for deck in gone:
            _add_deck(menu, deck, current)
        return menu
    for heading, group in deck_sections((d for d in decks if not d.archived), groups):
        if not group:
            continue
        if heading:
            menu.add_header(heading)
        for deck in group:
            _add_deck(menu, deck, current)
    return menu


def _add_deck(menu: PopoverMenu, deck: Deck, current: Optional[Deck]) -> None:
    is_current = current is not None and deck.path == current.path
    menu.add_item(deck_key(deck), deck.name, icon="check" if is_current else "")


class Submenu(NamedTuple):
    """An entry of a menu's command ids that is a row opening a flyout with the commands `ids`."""

    title: str
    ids: tuple[str, ...]


class Item(NamedTuple):
    """A command shown under a shorter title than the registry's (the palette needs the long one, a menu under a
    heading does not repeat it): "Compile PDF · Instructor" is just "Instructor" below the heading "Compile PDF"."""

    id: str
    title: str


def _command_id(entry) -> str:
    return entry.id if isinstance(entry, Item) else entry


def add_commands(menu: PopoverMenu, ctx: Context, ids: Iterable[str | Submenu | Item], header: str = "", *,
                 hints: bool = True) -> None:
    """The visible commands `ids` as items (disabled where they are not available now), under
    `header` if any of them is shown; `hints` False leaves the commands' meta texts out, so only
    the shortcuts show. A Submenu is a flyout row, shown if any of its commands is visible and
    disabled if none is available."""
    entries = [e for e in ids if (_visible(ctx, e.ids) if isinstance(e, Submenu)
                                  else ctx.commands[_command_id(e)].visible(ctx))]
    if entries and header:
        menu.add_header(header)
    for entry in entries:
        if isinstance(entry, Submenu):
            menu.add_submenu(f"submenu:{entry.title.lower()}", entry.title,
                             lambda parent, sub=entry: _flyout(parent, ctx, sub.ids),
                             enabled=any(c.enabled(ctx) for c in _visible(ctx, entry.ids)))
        else:
            command = ctx.commands[_command_id(entry)]
            title = entry.title if isinstance(entry, Item) else command.title(ctx)
            menu.add_item(command.id, title, meta=command.info(ctx) if hints else command.key_text(),
                          tone=command.tone, enabled=command.enabled(ctx), tip=command.tip_text(ctx))


def _visible(ctx: Context, ids: Iterable[str]) -> list:
    return [c for c in (ctx.commands[i] for i in ids) if c.visible(ctx)]


def _flyout(parent: PopoverMenu, ctx: Context, ids: Iterable[str]) -> PopoverMenu:
    flyout = PopoverMenu(parent, min_width=280)
    add_commands(flyout, ctx, ids, hints=False)
    return flyout


def build_compile_menu(parent: QWidget, ctx: Context) -> PopoverMenu:
    """The Compile caret menu: the same PDF and transcript entries as the Build menu (COMPILE_PDF,
    TRANSCRIPTS), Present and Stop. Entries a deck cannot use are disabled instead of hidden."""
    menu = PopoverMenu(parent, min_width=300)
    add_commands(menu, ctx, COMPILE_PDF, "Compile PDF")
    add_commands(menu, ctx, TRANSCRIPTS, "Accessible transcript")
    add_commands(menu, ctx, ["present", "present_here"], "Present")
    menu.add_separator()
    add_commands(menu, ctx, ["stop", "build_options"])
    return menu


# The menu bar: menus of sections. A section is (header, entries); a section without a header is set off by a plain
# separator (none before a menu's first one). An entry is a command id, an id prefix ending in "*" (every command
# registered under it, in the registry's order), a Submenu, or DECKS, the decks as the deck switcher groups them.
# Each menu is filled from the registry whenever it opens: labels, keys, enabled and checked states are those of now.
DECKS = "decks"
# The PDF entries of the Build menu and the Compile caret menu, under the heading "Compile PDF".
COMPILE_PDF = (Item("compile:current", "Current view"), Item("compile:instructor", "Instructor"),
               Item("compile:during-course", "During course"), Item("compile:after-course", "After course"),
               "compile:presenter", Item("compile:all", "All views"), "compile:chapters", "compile:pages",
               "compile:several")
TRANSCRIPTS = (*(f"transcript:{version}" for version in STUDENT_VERSIONS), "transcript:both")
MENU_BAR = (
    ("&File", (("", ("open_project", "new_deck", "import_presentation")), ("", ("save", "autosave")),
               ("", ("settings",)), ("", ("exit",)))),
    ("&Edit", (("", ("palette", "find", "replace")),
               ("", ("selection:rewrite", Submenu("Rewrite selection as", ("selection:rewrite:*",)),
                     "selection:proofread")),
               ("", ("slide:clear",)))),
    ("&View", (("View as", ("view:*",)), ("Language", ("language:*",)), ("Center", ("mode:*",)),
               ("SlideMage layout", ("column:left", "column:right", Submenu("Side panel", ("panel:*",)))),
               ("Tabs", ("tab:*",)))),
    ("&Project", (("", ("images", "library", "log")), ("", ("edit_bib", "edit_test_slides")),
                  ("", ("housekeeping",)))),
    ("&Deck", (("Open", (Item("open_pdf", "Latest PDF"), "deck_source")),
               ("Switch decks", (DECKS, "archived_decks")),
               ("Deck operations", ("update_deck_versions", "duplicate_deck",
                                    Submenu("Export", ("export_pptx", "export_latex")), "create_snapshot",
                                    "archive_deck")),
               ("Maintenance", ("rerender_deck_previews", "deck:readability", "deck:spelling", "refresh_decks")),
               ("", ("deck_settings",)))),
    ("&Slide", (("Views", ("slide:open", "slide:preview", "slide:images")),
                ("Add", ("slide:before", "slide:after", "slide:section_before", "slide:section_after",
                         "slide:duplicate", "slide:translate")),
                ("Visibility", ("slide:visible:*", "slide:update_versions")),
                ("Review", ("slide:reviewed", "slide:review_mark", "slides:unreviewed", "slide:compare")),
                ("", ("slide:readability",)),
                ("", (Submenu("Section", ("section:*",)),)),
                ("", ("slide:rename", "slide:remove", "slide:delete")))),
    ("Prese&nt", (("", ("present", "present_here")),)),
    ("&Build", (("Compile PDF", COMPILE_PDF),
                ("Accessible transcript", TRANSCRIPTS),
                ("Render previews", (Item("render_buffer", "Current view · editor buffer"),
                                     Item("preview:all-buffer", "All views · editor buffer"),
                                     Item("preview:all-saved", "All views · saved file"),
                                     Item("preview:force", "Force rerender current view"))),
                ("", ("stop", "build_options")))),
    ("&AI", (("", ("ai:local", "ai:cloud")),
             ("", (Submenu("This slide", ("slide:readable", "task:slide:*")), Submenu("This deck", ("task:deck:*",)))),
             ("", ("ai:setup",)))),
    ("&Help", (("", ("open_manual", "shortcuts")),
               ("", ("version_history", "check_updates", "plugins", "project_compat")),
               ("", (Submenu("Debug", ("debug_log", "debug_report", "open_logs")),)))),
)
# The commands that are one of a set of states: a radio item, checked where the command's meta says "current".
RADIO_PREFIXES = ("view:", "language:", "mode:", "ai:local", "ai:cloud")
# On a Mac these move to the application menu (Settings… with ⌘,, Quit with ⌘Q, About); elsewhere they stay.
MENU_ROLES = {"settings": QAction.MenuRole.PreferencesRole, "exit": QAction.MenuRole.QuitRole,
              "version_history": QAction.MenuRole.AboutRole}


def expand(ctx: Context, entries: Iterable) -> list:
    """`entries` with each "prefix*" replaced by the ids registered under the prefix."""
    out = []
    for entry in entries:
        if isinstance(entry, str) and entry.endswith("*"):
            out += [c.id for c in ctx.commands if c.id.startswith(entry[:-1])]
        else:
            out.append(entry)
    return out


def menu_bar(ctx: Context) -> tuple:
    """MENU_BAR with the loaded plugins' menu entries added: for each plugin a section headed with its name at the end
    of the menu it asked for. Without plugins this is MENU_BAR itself."""
    from ...plugins import session

    extra: dict[str, list] = {}
    for plugin in session.active():
        for menu in dict.fromkeys(m for m, _cid in plugin.contributions.menu_entries):
            ids = tuple(cid for m, cid in plugin.contributions.menu_entries if m == menu and cid in ctx.commands)
            if ids:
                extra.setdefault(menu, []).append((plugin.manifest.name, ids))
    if not extra:
        return MENU_BAR
    return tuple((title, (*sections, *extra.get(title.replace("&", "").lower(), ()))) for title, sections in MENU_BAR)


def build_menu_bar(window: QWidget, ctx: Context) -> QMenuBar:
    """The window's menu bar; `ctx` runs the commands (the window itself)."""
    bar = QMenuBar(window)
    for title, sections in menu_bar(ctx):
        menu = bar.addMenu(title)
        menu.setObjectName("menu:" + title.replace("&", "").lower())
        if menu.objectName() == "menu:ai":
            menu.menuAction().setVisible(bool(routes.all()))
        menu.aboutToShow.connect(lambda m=menu, s=sections: fill_menu(m, ctx, s))
        fill_menu(menu, ctx, sections)      # filled once now too, so a Mac finds Settings, Quit and About at once
    return bar


def fill_menu(menu: QMenu, ctx: Context, sections) -> None:
    """Fill `menu` again with `sections`' visible commands as they are now."""
    menu.clear()
    menu.setToolTipsVisible(True)       # each command's hover text (Command.tip)
    first = True
    # Items under a heading are set in, as View's are by its radio marks (which reserve that space themselves).
    radios = any(isinstance(e, str) and e.startswith(RADIO_PREFIXES) for _header, entries in sections for e in entries)
    for header, entries in sections:
        entries = [e for e in expand(ctx, entries) if _shown(ctx, e)]
        if not entries:
            continue
        indent = bool(header) and not radios
        if not first:
            menu.addSeparator()
        first = False
        if header:
            _add_header(menu, header)
        group = None
        for entry in entries:
            if entry == DECKS:
                _add_decks(menu, ctx, indent)
            elif isinstance(entry, Submenu):
                sub = menu.addMenu((INDENT_PAD if indent else "") + entry.title)
                sub.setObjectName("submenu:" + entry.title.lower())
                sub.setToolTipsVisible(True)
                commands = _visible(ctx, expand(ctx, entry.ids))
                for command in commands:
                    _add_command(sub, ctx, command)
                sub.menuAction().setEnabled(any(c.enabled(ctx) for c in commands))
            else:
                action = _add_command(menu, ctx, ctx.commands[_command_id(entry)],
                                      entry.title if isinstance(entry, Item) else None, indent)
                if action.isCheckable():
                    group = group or QActionGroup(menu)
                    group.addAction(action)

def _shown(ctx: Context, entry) -> bool:
    if entry == DECKS:
        return bool(getattr(ctx, "decks", None))
    if isinstance(entry, Submenu):
        return bool(_visible(ctx, expand(ctx, entry.ids)))
    return ctx.commands[_command_id(entry)].visible(ctx)


def _add_header(menu: QMenu, text: str) -> None:
    label = QLabel(text)
    label.setObjectName(q.MENU_HEADER)
    header = QWidgetAction(menu)
    header.setDefaultWidget(label)
    header.setEnabled(False)
    menu.addAction(header)


# What goes before the text of an item under a heading to set it in (a QMenu item takes no padding of its own: the
# style sheet pads them all alike), about q.MENU_INDENT px of non-breaking spaces.
INDENT_PAD = "\u00a0" * 3


class _DangerItem(QLabel):
    """A menu-bar item in the error color. A QMenu item cannot be colored by itself (the style sheet draws every
    item alike), so these are widgets that look like items: the hover wash, a click runs the action and closes the
    menus; the arrow keys and Enter reach the action itself."""

    clicked = Signal()

    def __init__(self, text: str, indented: bool = False) -> None:
        super().__init__(text)
        self.setObjectName(q.MENU_DANGER)
        self.setProperty("indented", indented)
        self.setIndent(0)
        self.setMouseTracking(True)

    def _hot(self, on: bool) -> None:
        set_property(self, "hot", on and self.isEnabled())

    def enterEvent(self, event) -> None:
        self._hot(True)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hot(False)
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self.isEnabled() and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)


def _add_danger_command(menu: QMenu, ctx: Context, command, title: str, indent: bool = False) -> QAction:
    item = _DangerItem(title, indent)
    item.setToolTip(command.tip_text(ctx))
    action = QWidgetAction(menu)
    action.setDefaultWidget(item)
    action.setText(title)
    action.setObjectName(command.id)
    enabled = command.enabled(ctx)
    action.setEnabled(enabled)
    item.setEnabled(enabled)
    run = lambda _checked=False, cid=command.id: ctx.commands.run(cid, ctx)    # noqa: E731

    def clicked() -> None:
        top = menu
        while isinstance(top.parent(), QMenu):
            top = top.parent()
        top.close()
        run()

    item.clicked.connect(clicked)
    action.triggered.connect(run)           # Enter on the highlighted action
    menu.addAction(action)
    return action


def _add_command(menu: QMenu, ctx: Context, command, title: Optional[str] = None, indent: bool = False) -> QAction:
    """A command as an item: its title, its key after a tab (shown only; the window binds the shortcuts, a second
    binding on the action would make the key ambiguous), enabled and, for a radio item, checked as now."""
    title = (title if title is not None else command.title(ctx)).replace("&", "&&")
    if command.tone == "danger" and not command.key_text():
        return _add_danger_command(menu, ctx, command, title.replace("&&", "&"), indent)
    key = command.key_text()
    title = (INDENT_PAD + title) if indent else title
    action = menu.addAction(f"{title}\t{key}" if key else title)
    action.setObjectName(command.id)
    action.setToolTip(command.tip_text(ctx))
    action.setMenuRole(MENU_ROLES.get(command.id, QAction.MenuRole.NoRole))
    action.setEnabled(command.enabled(ctx))
    if command.id.startswith(RADIO_PREFIXES):
        action.setCheckable(True)
        action.setChecked(command.info(ctx) == "current")
    action.triggered.connect(lambda _checked=False, cid=command.id: ctx.commands.run(cid, ctx))
    return action


def _add_decks(menu: QMenu, ctx: Context, indent: bool = False) -> None:
    """Switch deck ▸: the active decks by group under the deck switcher's headings (the archived ones are under
    Archived decks…)."""
    sub = menu.addMenu((INDENT_PAD if indent else "") + "Switch deck")
    sub.setObjectName("submenu:switch deck")
    current = ctx.state.deck
    group = QActionGroup(sub)
    groups = getattr(ctx, "deck_groups", DEFAULT_GROUPS)    # a stand-in context may not have the project's list
    sections = deck_sections((d for d in ctx.decks if not d.archived), groups)
    first = True
    for heading, decks in sections:
        if not decks:
            continue
        if not first:
            sub.addSeparator()
        first = False
        if heading:
            _add_header(sub, heading)
        for deck in decks:
            action = sub.addAction(deck.name.replace("&", "&&"))
            action.setObjectName(deck_key(deck))
            action.setCheckable(True)
            action.setChecked(current is not None and deck.path == current.path)
            action.setMenuRole(QAction.MenuRole.NoRole)
            group.addAction(action)
            action.triggered.connect(lambda _checked=False, d=deck: ctx.state.set_deck(d))
