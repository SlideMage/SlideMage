# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The tools an outside agent (the embedded Claude Code, a plugin's own MCP server) is offered: the one place
that assembles them, so the Claude Code session and Host.ai_tools() give the same box. No Qt."""
from __future__ import annotations

from pathlib import Path

from .. import compiler
from . import claude_scope
from .agent_types import EDIT_AUTO
from .tools import CLAUDE_CODE_TOOLS, ToolBox, build_toolbox
from .workspace import Workspace


def agent_toolbox(
    workspace: Workspace, scope: str, focus_path: Path | None, cancel: compiler.CancelToken | None = None,
    mode: str = EDIT_AUTO,
) -> ToolBox:
    """The Claude Code tool set on `workspace`, limited to `scope` ("slide": the focused slide, "deck"). `focus_path`
    is the file the editor shows; it counts as the focus only if it is a slide."""
    box = build_toolbox(workspace, lambda _event: None, cancel or compiler.CancelToken(), mode, tools=CLAUDE_CODE_TOOLS)
    box.ctx.scope = scope
    box.ctx.focus_slide = claude_scope.slide_focus(box.ctx.root, focus_path)
    return box
