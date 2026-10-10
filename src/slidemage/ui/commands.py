"""The action registry (UI_REDESIGN_PLAN.md, step 8): every thing the user can do from
the window, defined once.

A `Command` says what an action is called, where it belongs, when it is available and
what it does. The top bar's buttons, the Compile and ⋮ menus, the slide list's context
menus and the command palette (⌘K) all build their entries from the registry, so a
label, a shortcut or an enabled rule is written in one place. The commands themselves
are listed in workspace/actions.py.

Labels, metadata and the two predicates may be functions of the *context*, the window
(`ctx.state`, `ctx.compiling`, ...), so the registry stays plain data that is built
once and asked again whenever a menu opens.
"""
from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any, Union

from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QWidget

Context = Any   # the WorkspaceWindow (or a stand-in with the attributes the predicates read)
Text = Union[str, Callable[[Context], str]]


def _always(_ctx: Context) -> bool:
    return True


@dataclass(frozen=True)
class Command:
    id: str
    label: Text
    group: str
    run: Callable[[Context], None]
    icon: str = ""            # a Material icon name, shown in the palette
    shortcut: str = ""        # "Ctrl+K": installed on the window and shown next to the entry
    meta: Text = ""           # a second text: a count, a hint
    tone: str = ""            # "danger" for what destroys something
    enabled: Callable[[Context], bool] = _always   # shown greyed out when False
    visible: Callable[[Context], bool] = _always   # left out when False

    def title(self, ctx: Context) -> str:
        return self.label(ctx) if callable(self.label) else self.label

    def info(self, ctx: Context) -> str:
        """The metadata column: the meta text, else the shortcut as the platform writes it."""
        meta = self.meta(ctx) if callable(self.meta) else self.meta
        return meta or (QKeySequence(self.shortcut).toString(QKeySequence.SequenceFormat.NativeText)
                        if self.shortcut else "")


class CommandRegistry:
    def __init__(self) -> None:
        self._commands: dict[str, Command] = {}

    def add(self, command: Command) -> None:
        if command.id in self._commands:
            raise ValueError(f"command {command.id!r} is registered twice")
        self._commands[command.id] = command

    def __contains__(self, command_id: str) -> bool:
        return command_id in self._commands

    def __getitem__(self, command_id: str) -> Command:
        return self._commands[command_id]

    def __iter__(self) -> Iterator[Command]:
        return iter(self._commands.values())

    def run(self, command_id: str, ctx: Context) -> bool:
        """Run a command if it is visible and enabled now; returns whether it ran."""
        command = self._commands[command_id]
        if not (command.visible(ctx) and command.enabled(ctx)):
            return False
        command.run(ctx)
        return True

    def bind_shortcuts(self, window: QWidget) -> None:
        """A window-wide shortcut for every command that has one."""
        for command in self:
            if command.shortcut:
                QShortcut(QKeySequence(command.shortcut), window).activated.connect(
                    lambda cid=command.id: self.run(cid, window))
