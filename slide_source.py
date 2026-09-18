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


def save_slide_source(path: Path, new_text: str, eol: str) -> Path:
    """Back up the file's current on-disk bytes verbatim, then write
    new_text back with every line re-terminated with `eol`. Returns the
    backup file's path (or None if there was nothing on disk yet to back
    up -- a brand-new slide's very first save).

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
        backup_dir = BACKUPS_DIR / path.name
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_path = _unique_backup_path(backup_dir)
        shutil.copy2(path, backup_path)

    normalized = new_text.replace("\r\n", "\n").replace("\n", eol)
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(normalized)

    return backup_path
