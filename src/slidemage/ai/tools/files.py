"""The generic file tools -- read, find, search -- and the one place that decides
which paths the agent may touch at all (2026-10-10, UI redesign step 10a).

Everything is confined to the project folder: a path is resolved (symlinks
included) before it is judged, so neither `..` nor a link that leads out gets
through. Hidden folders (`.build/`, `.slidemage/` -- which holds the settings
file and possibly the API key --, `.previews/`, `.git/` ...) and `pdf/` do not
exist as far as the model can tell. Only text is read; "\n" is the line end the
model sees whatever the file uses (edits.py writes the file's own back).
"""
from __future__ import annotations

import os
import posixpath
from fnmatch import fnmatch
from pathlib import Path

from ... import slide_search
from ..workspace import Workspace
from .base import ToolContext, ToolError, tool

HIDDEN_FOLDERS = ("pdf",)        # besides everything whose name starts with "."
MAX_FILE_BYTES = 2_000_000
READ_LINES = 400                 # lines read_file returns unless asked for fewer
READ_CHARS = 30_000
FIND_LIMIT = 200
SEARCH_LIMIT = 40


def is_hidden(rel: Path) -> bool:
    return any(part.startswith(".") for part in rel.parts) or bool(rel.parts and rel.parts[0].casefold() in HIDDEN_FOLDERS)


def project_path(root: Path, arg: str) -> Path:
    """The resolved path `arg` (relative to the project, or absolute) names, if the agent may
    touch it; ToolError otherwise."""
    if not arg.strip():
        raise ToolError("The path is empty.")
    raw = Path(arg)
    try:
        resolved = (raw if raw.is_absolute() else root / raw).resolve()
        rel = resolved.relative_to(root)
    except ValueError:
        raise ToolError(f"'{arg}' is outside the project folder.") from None
    except (OSError, RuntimeError) as exc:
        raise ToolError(f"'{arg}' cannot be resolved: {exc}") from None
    if is_hidden(rel):
        raise ToolError(f"'{arg}' is not available: SlideMage's own folders (.build, .slidemage, pdf ...) are off limits.")
    return resolved


def may_touch(root: Path, path: Path) -> bool:
    """Whether `path` passes project_path's gate (links resolved, dot-files and hidden folders out)."""
    try:
        project_path(root, str(path))
    except ToolError:
        return False
    return True


def relative(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def read_disk_text(path: Path) -> str:
    """The text of a file on disk with "\\n" line ends; ToolError for a folder, a missing, huge or
    binary file."""
    if path.is_dir():
        raise ToolError(f"{path.name} is a folder. find_files lists what is in it.")
    if not path.is_file():
        raise ToolError(f"{path.name} does not exist.")
    if path.stat().st_size > MAX_FILE_BYTES:
        raise ToolError(f"{path.name} is too large to read ({path.stat().st_size // 1000} kB).")
    data = path.read_bytes()
    if b"\0" in data[:8192]:
        raise ToolError(f"{path.name} is not a text file.")
    try:
        return data.decode("utf-8").replace("\r\n", "\n")
    except UnicodeDecodeError:
        raise ToolError(f"{path.name} is not UTF-8 text.") from None


def current_text(workspace: Workspace, path: Path) -> str:
    """Fresh file text, with unsaved editor edits taking priority."""
    return current_revision(workspace, path)[0]


def current_revision(workspace: Workspace, path: Path) -> tuple[str, str]:
    """The text and the version checked; GUI buffers sync and snapshot on the GUI thread."""
    if workspace.is_open(path):
        text, dirty = workspace.buffer_snapshot(path)
        return text, "editor (unsaved)" if dirty else "file"
    return read_disk_text(path), "file"


@tool("read_file",
      "Read a text file of the project (a slide, a deck, Slidemaster.bib ...). Lines come numbered "
      "(\"12<tab>text\"); the numbers are not part of the file, leave them out of old_text. If a file "
      "is open in the editor you get its current text, unsaved edits included.",
      {"path": {"type": "string", "description": "Project-relative path, e.g. slides/1y8-EN-Title-current.tex"},
       "start_line": {"type": "integer", "description": "First line to read (default 1)."},
       "max_lines": {"type": "integer", "description": f"How many lines at most (default and cap {READ_LINES})."}},
      ("path",))
def read_file(ctx: ToolContext, args: dict) -> str:
    path = project_path(ctx.root, args["path"])
    text, source = current_revision(ctx.workspace, path)
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()                      # the line end of the last line, not a line of its own
    start = max(1, args.get("start_line", 1))
    count = min(max(1, args.get("max_lines", READ_LINES)), READ_LINES)
    shown, size = [], 0
    for number in range(start, min(start + count, len(lines) + 1)):
        line = f"{number}\t{lines[number - 1]}"
        size += len(line) + 1
        if size > READ_CHARS and shown:
            break
        shown.append(line)
    header = f"{relative(ctx.root, path)} ({len(lines)} lines; {source})"
    if not shown:
        return f"{header}\nThere is no line {start}."
    last = start + len(shown) - 1
    more = f"\n[Lines {start}-{last} of {len(lines)}; read on with start_line={last + 1}.]" if last < len(lines) else ""
    return header + "\n" + "\n".join(shown) + more


def _matches(rel: str, pattern: str) -> bool:
    if fnmatch(rel, pattern):
        return True
    if pattern.startswith("**/") and fnmatch(rel, pattern[3:]):
        return True
    return "/" not in pattern and fnmatch(posixpath.basename(rel), pattern)


@tool("find_files",
      f"List project files whose path matches a glob pattern: 'slides/*.tex', '**/*.bib', '*.png' (a "
      f"pattern without a slash matches file names anywhere). At most {FIND_LIMIT} are listed.",
      {"pattern": {"type": "string", "description": "Glob pattern, relative to the project folder."}},
      ("pattern",))
def find_files(ctx: ToolContext, args: dict) -> str:
    pattern = args["pattern"].strip().replace("\\", "/")
    if not pattern or pattern.startswith("/") or ".." in pattern.split("/"):
        raise ToolError("The pattern must be relative to the project folder and may not contain '..'.")
    found: list[str] = []
    for folder, subfolders, names in os.walk(ctx.root):
        rel_folder = Path(folder).relative_to(ctx.root)
        subfolders[:] = sorted(d for d in subfolders if not is_hidden(rel_folder / d))
        for name in sorted(names):
            rel = (rel_folder / name).as_posix()
            if _matches(rel, pattern) and may_touch(ctx.root, ctx.root / rel):
                found.append(rel)
    found.sort()
    if not found:
        return f"No file matches '{pattern}'."
    shown = found[:FIND_LIMIT]
    more = f"\n[{len(found) - FIND_LIMIT} more; narrow the pattern.]" if len(found) > FIND_LIMIT else ""
    return "\n".join(shown) + more


@tool("search",
      "Find text in the project's slides, decks and Slidemaster.bib (case-insensitive, a plain "
      "substring -- also finds citation keys and macro names). One hit per file, with the first "
      "matching line. Searches the saved files, not unsaved editor edits.",
      {"query": {"type": "string", "description": "The text to look for (at least 2 characters)."}},
      ("query",))
def search(ctx: ToolContext, args: dict) -> str:
    query = args["query"].strip()
    if len(query) < 2:
        raise ToolError("Give at least 2 characters to search for.")
    hits = slide_search.search_project(
        query, ctx.root, cancelled=ctx.cancel.is_set, allow=lambda path: may_touch(ctx.root, path))
    if not hits:
        return f"Nothing found for '{query}'."
    lines = [f"{relative(ctx.root, hit.path)}:{hit.line}: {hit.snippet}" for hit in hits[:SEARCH_LIMIT]]
    more = f"\n[{len(hits) - SEARCH_LIMIT} more files; use a longer query.]" if len(hits) > SEARCH_LIMIT else ""
    return "\n".join(lines) + more
