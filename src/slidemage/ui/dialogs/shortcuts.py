# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Help → Keyboard shortcuts…: every key of the window, for the system SlideMage runs on.

The keys of the commands come from the registry (a command's shortcut, else the key it only shows,
`Command.key_text()`), grouped by the palette's headings, so the sheet lists what the menus show. The keys
that the Source view and the slide list bind for themselves, and that are no command, are listed below them.
"""
from __future__ import annotations

import html as _html

from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QTextBrowser

from ..commands import CommandRegistry
from ..kit.widgets import ModalSheet

# The keys of the editor and the slide list that are not commands: (heading, ((what, key), ...)).
OWN_KEYS = (
    ("Source view", (("Bold", "Ctrl+B"), ("Italic", "Ctrl+I"), ("Underline", "Ctrl+U"),
                     ("Comment or uncomment the lines", "Ctrl+/"), ("Render the buffer", "Ctrl+R"))),
    ("Slide list", (("Move the slide up", "Alt+Up"), ("Move the slide down", "Alt+Down"))),
)


def native(key: str) -> str:
    return QKeySequence(key).toString(QKeySequence.SequenceFormat.NativeText)


def shortcut_rows(registry: CommandRegistry, ctx=None) -> list[tuple[str, list[tuple[str, str]]]]:
    """(heading, [(title, key), ...]) for every group of the registry with keys, then OWN_KEYS. A title that
    depends on the window ("Hide slide list") is asked of `ctx`, else it is the command id."""
    groups: dict[str, list[tuple[str, str]]] = {}
    for command in registry:
        key = command.key_text()
        if not key:
            continue
        if callable(command.label):
            title = command.label(ctx) if ctx is not None else command.id
        else:
            title = command.label
        groups.setdefault(command.group, []).append((title, key))
    rows = list(groups.items())
    rows += [(heading, [(what, native(key)) for what, key in keys]) for heading, keys in OWN_KEYS]
    return rows


class ShortcutsSheet(ModalSheet):
    def __init__(self, registry: CommandRegistry, parent=None) -> None:
        super().__init__("Keyboard shortcuts", parent, width=560)
        self.setMinimumHeight(560)
        self.browser = QTextBrowser()
        parts = []
        for heading, keys in shortcut_rows(registry, parent):
            parts.append(f"<h3>{_html.escape(heading)}</h3><table cellspacing='0' cellpadding='3' width='100%'>")
            parts += [f"<tr><td>{_html.escape(title)}</td><td align='right'><code>{_html.escape(key)}</code></td></tr>"
                      for title, key in keys]
            parts.append("</table>")
        self.browser.setHtml("".join(parts))
        self.add_tab("Shortcuts", self.browser)
        self.add_button("Close", kind="primary", role="accept")
