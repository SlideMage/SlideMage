# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The generic file tools -- read, find, search -- and the one place that decides
which paths the agent may touch at all (2026-10-10, UI redesign step 10a).

Everything is confined to the project folder: a path is resolved (symlinks
included) before it is judged, so neither `..` nor a link that leads out gets
through. Hidden folders (`.build/`, `.slidemage/` -- which holds the settings
file and possibly the API key --, `.previews/`, `.git/` ...) and `pdf/` do not
exist as far as the model can tell. Text, PDFs (text by page, or the pages as images) and images are read; "\n" is the line end the
model sees whatever the file uses (edits.py writes the file's own back).
"""
from __future__ import annotations

import os
import posixpath
from fnmatch import fnmatch
from pathlib import Path

from ... import preview_raster_client, slide_search
from ..workspace import Workspace
from .base import ToolContext, ToolError, ToolOutput, tool

HIDDEN_FOLDERS = ("pdf",)        # besides everything whose name starts with "."
MAX_FILE_BYTES = 2_000_000
READ_LINES = 400                 # lines read_file returns unless asked for fewer
READ_CHARS = 30_000
MAX_BINARY_BYTES = 50_000_000    # a paper as PDF
MAX_IMAGE_BYTES = 5_000_000      # what the model accepts per image
PDF_PAGES = 10                   # pages of text read_file returns unless asked for fewer
PAGE_IMAGES = 4                  # rendered pages per call, at PAGE_DPI
PAGE_DPI = 110
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".webp")
DRAWING_SUFFIXES = (".svg", ".eps")     # rasterised by PyMuPDF
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


def _binary_file(path: Path, limit: int) -> Path:
    if not path.is_file():
        raise ToolError(f"{path.name} does not exist.")
    if path.stat().st_size > limit:
        raise ToolError(f"{path.name} is too large to read ({path.stat().st_size // 1_000_000} MB).")
    return path


def _read_pdf(ctx: ToolContext, path: Path, args: dict) -> ToolOutput:
    """The text of PDF pages "--- page N ---" (like the line paging), or, with pages_as_images, the pages as PNGs.
    MuPDF runs in the raster child process, never in this (worker) thread."""
    _binary_file(path, MAX_BINARY_BYTES)
    name = relative(ctx.root, path)
    start = max(1, args.get("start_page", 1))
    images = args.get("pages_as_images", False)
    count = min(max(1, args.get("max_pages", PAGE_IMAGES if images else PDF_PAGES)), PAGE_IMAGES if images else 50)
    try:
        if images:
            from ... import preview_pages
            got = preview_pages.read_document(path, project_root=ctx.root, start=start, count=count, dpi=PAGE_DPI)
        else:
            got = preview_raster_client.read_document(path, "pdf", start, count, PAGE_DPI)
    except RuntimeError as exc:
        raise ToolError(f"{path.name} is not a readable PDF: {exc}") from None
    total = got["count"]
    last = start + len(got.get("texts") or got["images"]) - 1
    if last < start:
        return f"{name} ({total} pages)\nThere is no page {start}."
    if images:
        return f"{name} ({total} pages): pages {start}-{last} as images.", got["images"]
    shown, size = [], 0
    for number, body in enumerate(got["texts"], start):
        page = f"--- page {number} ---\n{body.strip()}"
        size += len(page) + 1
        if size > READ_CHARS and shown:
            break
        shown.append(page)
    last = start + len(shown) - 1
    text = f"{name} ({total} pages)\n" + "\n".join(shown)
    if not any(body.strip() for body in got["texts"]):
        text += "\n[No text layer found (a scan or a drawing): read it with pages_as_images.]"
    if last < total:
        text += f"\n[Pages {start}-{last} of {total}; read on with start_page={last + 1}.]"
    return text


def _read_image(ctx: ToolContext, path: Path, suffix: str) -> ToolOutput:
    """An image file for the model to look at; an SVG or EPS drawing is rasterised first (in the child)."""
    _binary_file(path, MAX_BINARY_BYTES)
    if suffix in DRAWING_SUFFIXES:
        try:
            data = preview_raster_client.read_document(path, "drawing", dpi=PAGE_DPI * 2)["images"][0]
        except RuntimeError as exc:
            raise ToolError(f"{path.name} cannot be rasterised: {exc}") from None
    else:
        data = path.read_bytes()
    if len(data) > MAX_IMAGE_BYTES:
        raise ToolError(f"{path.name} is too large to look at ({len(data) // 1_000_000} MB; the limit is 5 MB).")
    return f"{relative(ctx.root, path)}:", [data]


@tool("read_file",
      "Read a file of the project. Text (a slide, a deck, SlideMage.bib ...) comes numbered "
      "(\"12<tab>text\"); the numbers are not part of the file, leave them out of old_text. If a file "
      "is open in the editor you get its current text, unsaved edits included. A PDF (an attached paper) "
      "comes as text per page; set pages_as_images to see the pages themselves (figures, formulas, "
      "tables). An image (png, jpg, gif, webp, svg, eps) is shown to you.",
      {"path": {"type": "string", "description": "Project-relative path, e.g. slides/1y8-EN-Title-current.tex"},
       "start_line": {"type": "integer", "description": "First line to read (default 1)."},
       "max_lines": {"type": "integer", "description": f"How many lines at most (default and cap {READ_LINES})."},
       "start_page": {"type": "integer", "description": "PDF: first page to read (default 1)."},
       "max_pages": {"type": "integer",
                     "description": f"PDF: pages to read (text: default {PDF_PAGES}, cap 50; images: default and cap {PAGE_IMAGES})."},
       "pages_as_images": {"type": "boolean", "description": "PDF: look at the pages as images instead of reading their text."}},
      ("path",))
def read_file(ctx: ToolContext, args: dict) -> ToolOutput:
    path = project_path(ctx.root, args["path"])
    suffix = path.suffix.casefold()
    if suffix == ".pdf":
        return _read_pdf(ctx, path, args)
    if suffix in IMAGE_SUFFIXES + DRAWING_SUFFIXES:
        return _read_image(ctx, path, suffix)
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
      "Find text in the project's slides, decks and SlideMage.bib (case-insensitive, a plain "
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
