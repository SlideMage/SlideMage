# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Safe file writes and tolerant JSON reads with no SlideMage dependencies: every store and record SlideMage
keeps is written complete beside its target and renamed into place, so a crash or a second process never
sees half a file."""

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any


class StaleFileError(RuntimeError):
    """The file on disk no longer matches the text an edit was based on."""


def replace_with_retry(source: Path, target: Path, attempts: int = 40, delay: float = 0.25,
                       *, expected_text: str | None = None) -> None:
    """os.replace(), retried for a while: on Windows a virus scanner or the
    search indexer often holds a just-written file open for a moment, and the
    rename of a freshly written file or snapshot folder then fails with "access
    denied" although nothing is wrong."""
    for attempt in range(attempts):
        if expected_text is not None and read_text_exact(target) != expected_text:
            raise StaleFileError(f"{target.name} changed on disk -- reload and retry.")
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(delay)


def atomic_write(path: Path, data: str | bytes, *, expected_text: str | None = None, mode: int | None = None) -> None:
    """Write `data` (text as UTF-8 with plain "\\n" line ends) to a temporary file beside `path`, flush it to
    disk, then replace `path` with it. Missing folders are created. An expected_text mismatch
    immediately before replacement raises StaleFileError and leaves the current file untouched. `mode` sets the
    new file's permission bits (default: the private ones of a temporary file)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data.encode("utf-8") if isinstance(data, str) else data)
            handle.flush()
            os.fsync(handle.fileno())
        if mode is not None:
            os.chmod(temporary, mode)
        replace_with_retry(temporary, path, attempts=8, expected_text=expected_text)
    finally:
        temporary.unlink(missing_ok=True)


def read_text_exact(path: Path) -> str:
    """The file's text with its line endings untouched ("\\r\\n" stays), so edits and regexes see what is on disk."""
    with open(path, encoding="utf-8", newline="") as f:
        return f.read()


def write_text_exact(path: Path, text: str, *, expected_text: str | None = None) -> None:
    """Write `text` as it is: UTF-8, no line-ending translation. The file is replaced, never truncated in
    place: the text goes to a temporary file beside it, which then takes its place (atomic_write), so a failure
    midway leaves the old file complete. An existing file keeps its permission bits, and a symbolic link keeps
    pointing at its target. expected_text, if given, is checked against the file immediately before the
    replacement (StaleFileError on a mismatch)."""
    if path.is_symlink():
        path = path.resolve()
    mode = path.stat().st_mode & 0o7777 if path.exists() else None
    atomic_write(path, text, expected_text=expected_text, mode=mode)


def read_json(path: Path, kind: type = dict) -> Any:
    """The JSON in `path`; an empty `kind()` (a dict unless asked otherwise) when the file is missing,
    unreadable, not JSON, or not a `kind`."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):  # ValueError covers bad JSON and bytes that are not UTF-8
        return kind()
    return data if isinstance(data, kind) else kind()


def write_json(path: Path, data: Any, *, indent: int | None = 2, sort_keys: bool = True,
               ensure_ascii: bool = False) -> None:
    """`data` as JSON with a final newline, written with atomic_write()."""
    atomic_write(path, json.dumps(data, indent=indent, sort_keys=sort_keys, ensure_ascii=ensure_ascii) + "\n")
