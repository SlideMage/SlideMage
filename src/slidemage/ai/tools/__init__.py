"""The agent's tools (2026-10-10, UI redesign step 10a): `build_toolbox()` gives a run its
ToolBox. Generic file tools: files.py; changing files and the rules for it: edits.py; the
SlideMage tools: slidemage.py; the shape of a tool: base.py."""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from ... import compiler
from ..agent_types import EDIT_ASK, AgentEvent
from ..workspace import Workspace
from . import edits, files, slidemage
from .base import Tool, ToolBox, ToolContext, ToolError
from .edits import undo_edit

TOOLS = [files.read_file, files.find_files, files.search, edits.edit_file, edits.write_file,
         slidemage.list_slides, slidemage.lint, slidemage.render_preview, slidemage.add_slide,
         slidemage.add_bib_entry, slidemage.compile_deck, slidemage.read_guide]

__all__ = ["TOOLS", "Tool", "ToolBox", "ToolContext", "ToolError", "build_toolbox", "undo_edit"]


def build_toolbox(
    workspace: Workspace, emit: Callable[[AgentEvent], None], cancel: compiler.CancelToken,
    mode: str = EDIT_ASK, root: Path | None = None, tools: list[Tool] | None = None,
) -> ToolBox:
    return ToolBox(tools or TOOLS, ToolContext((root or workspace.root).resolve(), workspace, emit, cancel, mode))
