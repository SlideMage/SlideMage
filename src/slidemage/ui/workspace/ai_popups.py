# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The popovers that answer a move of the AI switch (workspace v6 handoff, section 2, "Popups"): busy, busy after
the work ended, Claude Code session, project setting Local, first use of Cloud.

One component, `DecisionPopover`: 360 px wide, under the switch, with an icon and a title, a text, an optional
list box, and buttons with the secondary one first and the primary one last. A click outside does not dismiss it;
Esc is the secondary button. For the keyboard the popover is a small modal group: it opens on the secondary button (the
safe answer: nothing is sent, nothing is stopped), Tab goes secondary, primary, link and round again, and a button or Esc
gives the focus back to where it was. The texts are here, as data (`PopupSpec`); which one shows when is ai_route.py's.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ...ai import routes
from ..kit import kit_qss as q
from ..kit.widgets import Button, IconLabel, Popover, apply_shadow, clear_layout
from .ai_work import RunningWork

WIDTH = 360


def connection_text(conn: str) -> str:
    """The cloud route as the warnings name it: "Claude Code", "the Anthropic API"."""
    route = routes.get(conn)
    service = route.service if route is not None else conn
    return f"the {service}" if service.endswith("API") else service


BUSY_TEXT = ("Switching changes the route for every AI task. Running work would have to stop first. "
             "A file write that has started finishes before the switch.")
FINISHED_TEXT = "Nothing is running now, so you can switch without stopping anything."
SESSION_TEXT = ("The Claude Code terminal is still running. Switching away ends it. SlideMage cannot tell "
                "whether it is idle, and the session may not be resumable later.")


@dataclass(frozen=True)
class PopupSpec:
    kind: str                       # "busy", "finished", "session", "policy" or "first"
    icon: str                       # Material icon name
    tone: str                       # of the icon: "strong", "ok" or "warning"
    title: str
    text: str
    actions: tuple[tuple[str, str, Callable[[], None]], ...]    # (label, button kind, callback): the secondary first
    lines: tuple[str, ...] = ()     # the grey list box
    link: tuple[str, Callable[[], None]] | None = None


def busy_spec(work: list[RunningWork], keep: Callable[[], None], stop: Callable[[], None]) -> PopupSpec:
    return PopupSpec("busy", "pending", "strong", "AI work is running", BUSY_TEXT,
                     (("Keep running", "secondary", keep), ("Stop and switch", "primary", stop)),
                     lines=tuple(w.line for w in work))


def finished_spec(cancel: Callable[[], None], switch: Callable[[], None]) -> PopupSpec:
    return PopupSpec("finished", "check_circle", "ok", "The running work has finished", FINISHED_TEXT,
                     (("Cancel", "secondary", cancel), ("Switch now", "primary", switch)))


def session_spec(stay: Callable[[], None], end: Callable[[], None], service: str = "Claude Code") -> PopupSpec:
    text = SESSION_TEXT if service == "Claude Code" else (
        f"The {service} session is still running. Switching away ends it. "
        "The session may not be resumable later.")
    return PopupSpec("session", "terminal", "strong", f"End the {service} session?", text,
                     (("Stay", "secondary", stay), ("End session and switch", "primary", end)))


def policy_spec(conn: str, cancel: Callable[[], None], switch: Callable[[], None],
                change_setting: Callable[[], None]) -> PopupSpec:
    text = ("In Cloud mode every AI task (chat, image descriptions, translations, fixes) sends slide source, images "
            f"and notes to {connection_text(conn)}. The project setting stays Local, and the switch starts on Local "
            "again next time.")
    return PopupSpec("policy", "warning", "warning", "This project is set to Local", text,
                     (("Cancel", "secondary", cancel), ("Switch to Cloud for this session", "cloud", switch)),
                     link=("Change the project setting…", change_setting))


def first_use_spec(conn: str, cancel: Callable[[], None], use: Callable[[], None]) -> PopupSpec:
    text = (f"Requests will send slide source, images and notes from this project to {connection_text(conn)}. "
            "Switching itself sends nothing. This is asked once for this project.")
    return PopupSpec("first", "cloud", "warning", "Use Cloud for all AI tasks?", text,
                     (("Cancel", "secondary", cancel), ("Use Cloud", "cloud", use)))


class DecisionPopover(Popover):
    """The popover of one PopupSpec. `show_spec` replaces what it says (busy -> finished) without moving it."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent, min_width=WIDTH, inline=True, dismiss_outside=False)
        self.setFixedWidth(WIDTH)
        self.body.setContentsMargins(16, 16, 16, 16)
        self.body.setSpacing(10)
        apply_shadow(self, "raised")
        self.spec: PopupSpec | None = None
        self.buttons: list[Button] = []        # of the spec on show, the secondary first

    def show_spec(self, spec: PopupSpec) -> None:
        """Show `spec`; one that replaces another keeps the focus on the same button."""
        keep = next((i for i, button in enumerate(self.buttons) if button.hasFocus()), 0)
        self.spec = spec
        self.buttons = []
        clear_layout(self.body)
        self.setAccessibleName(spec.title)
        head = QHBoxLayout()
        head.setSpacing(8)
        icon = IconLabel(spec.icon, 20)
        icon.set_tone(spec.tone)
        head.addWidget(icon)
        title = QLabel(spec.title)
        title.setObjectName(q.AI_POPUP_TITLE)
        head.addWidget(title, 1)
        self.body.addLayout(head)
        text = QLabel(spec.text)
        text.setObjectName(q.AI_POPUP_TEXT)
        text.setWordWrap(True)
        self.body.addWidget(text)
        if spec.lines:
            box = QFrame()
            box.setObjectName(q.LIST_BOX)
            rows = QVBoxLayout(box)
            rows.setContentsMargins(10, 8, 10, 8)
            rows.setSpacing(4)
            for line in spec.lines:
                label = QLabel(line)
                label.setWordWrap(True)
                rows.addWidget(label)
            self.body.addWidget(box)
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        buttons.addStretch(1)
        for label, kind, callback in spec.actions:
            button = Button(label, kind)
            button.clicked.connect(lambda _checked=False, c=callback: self._run(c))
            buttons.addWidget(button)
            self.buttons.append(button)
        self.body.addLayout(buttons)
        if spec.link is not None:
            self.body.addWidget(link(spec.link[0], lambda: self._run(spec.link[1])), 0, Qt.AlignmentFlag.AlignRight)
        self.adjustSize()
        self.focus_target = self.buttons[keep]
        if self.isVisible():
            self.focus_target.show()            # the layout shows its new widgets a turn later; the focus cannot wait
            self.focus_target.setFocus(Qt.FocusReason.OtherFocusReason)

    def _run(self, callback: Callable[[], None]) -> None:
        self.close_and_return()
        callback()

    def escape(self) -> None:
        """Esc is the secondary button."""
        self._run(self.spec.actions[0][2])


def link(text: str, on_click: Callable[[], None]) -> Button:
    """An underlined text button (it is in the Tab order; Enter and Space press it)."""
    button = Button(text, "ghost")
    button.setObjectName(q.AI_POPUP_LINK)
    button.clicked.connect(lambda _checked=False: on_click())
    return button
