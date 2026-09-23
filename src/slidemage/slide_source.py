"""Encoding/EOL-safe slide-source read/save, with a full timestamped
backup history kept on every save (not a single rolling backup -- an
explicit scope decision, see SESSION_HANDOFF.md).
"""
from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

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
    """
    backup_path = None
    if path.exists():
        if expected_text is not None:
            current_text, _ = read_slide_source(path)
            if current_text != expected_text:
                raise StaleFileError(
                    f"{path.name} changed on disk since it was last loaded -- "
                    "reload this slide's editor tab and retry."
                )
        backup_dir = BACKUPS_DIR / path.name
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_path = _unique_backup_path(backup_dir)
        shutil.copy2(path, backup_path)

    normalized = new_text.replace("\r\n", "\n").replace("\n", eol)
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(normalized)

    return backup_path
