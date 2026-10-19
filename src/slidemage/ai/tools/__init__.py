# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The agent's tools (2026-10-10, UI redesign step 10a): `build_toolbox()` gives a run its
ToolBox. Generic file tools: files.py; changing files and the rules for it: edits.py; the
SlideMage tools: slidemage.py; the cached-preview refreshes: previews.py; the readability check: readability.py;
the shape of a tool: base.py."""
from __future__ import annotations

from collections.abc import Callable

from ... import compiler
from ..agent_types import EDIT_ASK, AgentEvent
from ..workspace import Workspace
from . import edits, files, focus, previews, readability, slidemage
from .base import Tool, ToolBox, ToolContext, ToolError
from .edits import undo_edit

TOOLS = [files.read_file, files.find_files, files.search, edits.edit_file, edits.write_file,
         slidemage.list_slides, slidemage.lint, slidemage.render_preview, slidemage.add_slide, slidemage.create_slide,
         slidemage.modify_slide, slidemage.add_bib_entry, slidemage.compile_deck, slidemage.read_guide,
         previews.refresh_preview, previews.refresh_deck_previews, readability.check_readability]

# What the embedded Claude Code is offered over MCP (ai/mcp_server.py): the focus and the buffer, the
# read-only tools and composite slide creation/modification. Native Edit/Write handles other files.
CLAUDE_CODE_READ_ONLY = [focus.get_focus, focus.show_slide, focus.read_buffer, focus.read_selection, slidemage.list_slides, slidemage.lint,
                         slidemage.render_preview, previews.refresh_preview, readability.check_readability,
                         slidemage.read_guide]
CLAUDE_CODE_TOOLS = [*CLAUDE_CODE_READ_ONLY, slidemage.add_slide, slidemage.create_slide, slidemage.modify_slide, focus.translate_slide,
                     focus.switch_to_deck_mode, previews.refresh_deck_previews]

__all__ = ["CLAUDE_CODE_READ_ONLY", "CLAUDE_CODE_TOOLS", "TOOLS", "Tool", "ToolBox", "ToolContext", "ToolError", "build_toolbox", "undo_edit"]


def build_toolbox(
    workspace: Workspace, emit: Callable[[AgentEvent], None], cancel: compiler.CancelToken,
    mode: str = EDIT_ASK, tools: list[Tool] | None = None,
) -> ToolBox:
    return ToolBox(tools or TOOLS, ToolContext(workspace.project, workspace, emit, cancel, mode))
