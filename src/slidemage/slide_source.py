# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Encoding/EOL-safe slide-source read/save, with a full timestamped
backup history kept on every save (not a single rolling backup -- an
explicit scope decision, see SESSION_HANDOFF.md).
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .fileio import Edits, StaleFileError as StaleFileError, read_text_exact, write_texts
from . import alt_blocks
from .project import ProjectContext
from .tex_source import braced_argument, masked_same_length



def read_slide_source(path: Path) -> tuple[str, str]:
    """The editor text and preferred line ending of a UTF-8 file."""
    return editor_text(read_text_exact(path))


def editor_text(raw: str) -> tuple[str, str]:
    eol = "\r\n" if "\r\n" in raw else "\n"
    text = raw.replace("\r\n", "\n")
    return text, eol


def backup_path(ctx: ProjectContext, path: Path) -> Path:
    backup_dir = ctx.slide_backups_dir / path.name
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    candidate = backup_dir / f"{ts}.tex"
    n = 2
    while candidate.exists():
        candidate = backup_dir / f"{ts}-{n}.tex"
        n += 1
    return candidate


def save_slide_source(
    ctx: ProjectContext, path: Path, new_text: str, eol: str, expected_text: str | None = None,
    backup: bool = True,
) -> Path | None:
    """Save the source with a backup, guarded by the exact expected text."""
    if expected_text is None:
        try:
            expected_text = read_text_exact(path)
        except FileNotFoundError:
            pass
    after = new_text.replace("\r\n", "\n").replace("\n", eol)
    return commit_slide(ctx, path, {path: (expected_text, after)}, backup=backup)


def commit_slide(ctx: ProjectContext, path: Path, edits: Edits, *, backup: bool = True) -> Path | None:
    """Publish the captured backup with the edits, before replacing the current file."""
    expected_text, after = edits[path]
    edits = edits.copy()
    del edits[path]
    backup_dir = ctx.slide_backups_dir / path.name
    backup_file = None
    if backup and expected_text is not None:
        backup_file = backup_path(ctx, path)
        edits[backup_file] = (None, expected_text)
    edits[path] = (expected_text, after)
    write_texts(edits)
    if not backup and expected_text is not None and expected_text != after:
        try:
            backup_dir.mkdir(parents=True, exist_ok=True)
            (backup_dir / SAVED_STAMP).touch()
        except OSError:
            logging.getLogger(__name__).warning("Saved %s but could not update its last-save time", path, exc_info=True)
    return backup_file


SAVED_STAMP = ".last-save"     # in a file's backup folder: touched by a save that keeps no backup


def last_saved(ctx: ProjectContext, path: Path) -> datetime | None:
    """When the slide was last saved through save_slide_source(): the newest backup of
    slides/.backups/<filename>/, whose name is the time of the save, or the time of its SAVED_STAMP
    (a save without a backup), whichever is later. None for a file never saved that way. (A file's
    mtime would also move when the header sync or a rename rewrites it.)"""
    stamps = []
    stamp = ctx.slide_backups_dir / path.name / SAVED_STAMP
    if stamp.is_file():
        stamps.append(datetime.fromtimestamp(stamp.stat().st_mtime).replace(microsecond=0))
    for backup in (ctx.slide_backups_dir / path.name).glob("*.tex"):
        try:
            stamps.append(datetime.strptime(backup.stem[:15], "%Y%m%d-%H%M%S"))
        except ValueError:
            continue
    return max(stamps, default=None)


# -- speaker notes: \note{...} --------------------------------------------------------------------

@dataclass(frozen=True)
class NoteCall:
    start: int       # the backslash of \note
    end: int         # after the closing brace
    overlay: str     # what stands between \note and the brace, e.g. "<2>" or "<2>[item]"; may be empty
    content: str     # the braced argument, as written

    @property
    def text(self) -> str:
        return f"\\note{self.overlay}{{{self.content}}}"


def note_calls(text: str) -> list[NoteCall]:
    r"""Every \note call of a slide's text, in order: Beamer's \note{...}, \note<2>{...} and
    \note<2>[item]{...} (the same forms alt_blocks.extract_note_calls() removes for a transcript)."""
    calls = []
    last_end = 0
    for name, found, command_end in alt_blocks.iter_tex_commands(text):
        if name != "note" or found < last_end:
            continue
        cursor = command_end
        while cursor < len(text) and text[cursor].isspace():
            cursor += 1
        seen: set[str] = set()
        while cursor < len(text) and text[cursor] in "<[" and text[cursor] not in seen:
            seen.add(text[cursor])
            after = alt_blocks.delimited_group_end(text, cursor, text[cursor], ">" if text[cursor] == "<" else "]")
            if after is None:
                break
            cursor = after
            while cursor < len(text) and text[cursor].isspace():
                cursor += 1
        content, after = braced_argument(text, cursor)
        if after == cursor:
            continue
        overlay = text[command_end:cursor].strip()
        calls.append(NoteCall(found, after, overlay, content))
        last_end = after
    return calls


def replace_note(text: str, index: int, content: str) -> str:
    """`text` with the argument of its `index`-th note replaced (its overlay stays)."""
    call = note_calls(text)[index]
    return text[:call.start] + NoteCall(call.start, call.end, call.overlay, content).text + text[call.end:]


def remove_note(text: str, index: int) -> str:
    """`text` without its `index`-th note and the line it stood alone on."""
    call = note_calls(text)[index]
    line_start = text.rfind("\n", 0, call.start) + 1
    line_end = text.find("\n", call.end)
    line_end = len(text) if line_end == -1 else line_end + 1
    if text[line_start:call.start].strip() == "" and text[call.end:line_end].strip() == "":
        return text[:line_start] + text[line_end:]
    return text[:call.start] + text[call.end:]


_FRAME_END_RE = re.compile(r"^([ \t]*)\\end\{\w*frame\}", re.MULTILINE)


def add_note(text: str, content: str) -> str:
    """`text` with a new \\note{content} on its own line before the closing \\end{...frame} (one
    indent deeper than it), or at the end when the slide has no frame."""
    ends = list(_FRAME_END_RE.finditer(text))
    if not ends:
        return text.rstrip("\n") + f"\n\\note{{{content}}}\n"
    end = ends[-1]
    return text[:end.start()] + f"{end.group(1)}\t\\note{{{content}}}\n" + text[end.start():]


# -- the frame title ---------------------------------------------------------------------------------

def title_span(text: str) -> tuple[int, int] | None:
    r"""Where the title text of a slide's frame stands in `text` (start, end): the first argument of
    \begin{standardframe}[options]{Title} (and the other frame environments) or of
    \titleframe{Title}{Subtitle}; None for a slide without either. Comments are skipped."""
    masked = masked_same_length(text)
    match = alt_blocks.FRAME_OPEN_RE.search(masked) or alt_blocks.TITLEFRAME_RE.search(masked)
    if match is None:
        return None
    _, after = braced_argument(masked, match.end() - 1)
    return (match.end(), after - 1) if after > match.end() - 1 else None


def set_title(text: str, title: str) -> str:
    """`text` with the frame's title text replaced by `title`."""
    span = title_span(text)
    if span is None:
        raise ValueError("the slide has no frame title")
    return text[:span[0]] + title + text[span[1]:]
