"""Encoding/EOL-safe slide-source read/save, with a full timestamped
backup history kept on every save (not a single rolling backup -- an
explicit scope decision, see SESSION_HANDOFF.md).
"""
from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from . import alt_blocks
from .tex_source import masked_same_length
from .deck_scan import PROJECT_ROOT

SLIDES_DIR = PROJECT_ROOT / "slides"
BACKUPS_DIR = SLIDES_DIR / ".backups"


class StaleFileError(RuntimeError):
    """The slide file on disk no longer matches the text the editor tab
    last loaded -- something else in the app wrote to it in the meantime
    (bibliography.add_entry() from an "Add citation" dialog on this same
    slide, deck_headers.regenerate_headers() running in the background
    after any deck edit, a translation back-reference, a rename/replace-
    image rewrite, ...). Same concept, same name, as deck_editor.py's own
    StaleFileError for deck files -- kept as a separate class here rather
    than imported, since the two check different files for different
    reasons and a caller should never need to catch "either kind" at
    once."""


def read_slide_source(path: Path) -> tuple[str, str]:
    """Read a slide's own .tex file, returning (text, eol).

    text always uses bare \\n internally (collapsed from the file's own
    CRLF, if any) -- matching what a Tk Text widget itself stores/renders,
    and avoiding a literal embedded \\r mis-rendering inside it. eol is
    the file's own dominant line ending ("\\r\\n" if present, else "\\n"),
    detected per-file rather than assumed, for save_slide_source() to
    restore later.
    """
    with open(path, encoding="utf-8", newline="") as f:
        raw = f.read()
    eol = "\r\n" if "\r\n" in raw else "\n"
    text = raw.replace("\r\n", "\n")
    return text, eol


def _unique_backup_path(backup_dir: Path) -> Path:
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    candidate = backup_dir / f"{ts}.tex"
    n = 2
    while candidate.exists():
        candidate = backup_dir / f"{ts}-{n}.tex"
        n += 1
    return candidate


def check_fresh(path: Path, expected_text: str) -> None:
    """Raise StaleFileError unless the file is as `expected_text` says (or does not exist yet)."""
    if path.exists() and read_slide_source(path)[0] != expected_text:
        raise StaleFileError(
            f"{path.name} changed on disk since it was last loaded -- reload the slide and retry."
        )


def save_slide_source(
    path: Path, new_text: str, eol: str, expected_text: str | None = None
) -> Path:
    """Back up the file's current on-disk bytes verbatim, then write
    new_text back with every line re-terminated with `eol`. Returns the
    backup file's path (or None if there was nothing on disk yet to back
    up -- a brand-new slide's very first save).

    If `expected_text` is given and the file exists, it's compared (same
    bare-"\\n" normalization read_slide_source() itself returns) against
    what's actually on disk right now; a mismatch raises StaleFileError
    and writes nothing, backup included, rather than silently backing up
    and overwriting a write this editor tab doesn't know about. Callers
    that don't pass it (or pass None) keep the old unconditional-overwrite
    behavior -- this is the tab's own last-loaded copy, and only the tab
    has one to check against.

    The backup is a raw byte copy (shutil.copy2, not re-encoded) into
    slides/.backups/<original filename>/<timestamp>.tex -- invisible to
    every existing glob-based scan (deck_scan.py/unused_content.py/
    deck_headers.py all use non-recursive, exact-suffix globs at the top
    level of slides/ only).

    Documented, accepted limitation: this normalizes the *whole* file to
    one consistent eol rather than preserving per-line mixed endings --
    never touches content, always visible in git diff, backstopped by
    both this backup and git itself (slides/ is already tracked).

    If `expected_text` is given and the file already exists, its current
    on-disk text (read the same way read_slide_source() normalizes it --
    bare \\n) must match `expected_text` exactly, or this raises
    StaleFileError without touching the file or writing a backup at all.
    Left as None (the default) for a caller that hasn't been ported to the
    stale-check yet, which always saves last-write-wins as before.
    """
    if expected_text is not None:
        check_fresh(path, expected_text)
    backup_path = None
    if path.exists():
        backup_dir = BACKUPS_DIR / path.name
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_path = _unique_backup_path(backup_dir)
        shutil.copy2(path, backup_path)

    normalized = new_text.replace("\r\n", "\n").replace("\n", eol)
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(normalized)

    return backup_path


def last_saved(path: Path) -> datetime | None:
    """When the slide was last saved through save_slide_source(): the newest backup of
    slides/.backups/<filename>/, whose name is the time of the save. None for a file never saved
    that way. (A file's mtime would also move when the header sync or a rename rewrites it.)"""
    stamps = []
    for backup in (BACKUPS_DIR / path.name).glob("*.tex"):
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
        content, after = alt_blocks.braced_argument(text, cursor)
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
    _, after = alt_blocks.braced_argument(masked, match.end() - 1)
    return (match.end(), after - 1) if after > match.end() - 1 else None


def set_title(text: str, title: str) -> str:
    """`text` with the frame's title text replaced by `title`."""
    span = title_span(text)
    if span is None:
        raise ValueError("the slide has no frame title")
    return text[:span[0]] + title + text[span[1]:]
