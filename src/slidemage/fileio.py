# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Safe file writes and tolerant JSON reads: every store and record SlideMage
keeps is written complete beside its target and renamed into place, so a crash or a second process never
sees half a file."""

import copy
import errno
import hashlib
import json
import logging
import os
import tempfile
import threading
import time
from collections.abc import Callable
from contextlib import nullcontext
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)


def text_sha256(text: str) -> str:
    """Hash UTF-8 text; source files are read with universal newlines before hashing."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    """Hash a file in 1 MiB chunks so large PDFs and archives need no full copy in memory."""
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


class StaleFileError(RuntimeError):
    """The file on disk no longer matches the text an edit was based on."""


Edits = dict[Path, tuple[str | None, str]]
_write_lock = threading.Lock()
_write_stamp = 0


def writer_stamp() -> int:
    """The generation of the last guarded publication, including writes later rolled back. Read without the write
    lock: a write holds it while it touches the disk (seconds on a network or Dropbox drive), and a caller on the GUI
    thread must not wait for that. A plain int read is atomic; write_texts(expected_stamp=...) compares again under
    the lock, so a stamp read just before a publication is refused there, not trusted."""
    return _write_stamp


class PartialWriteError(OSError):
    """A write failed after publishing files. Restored paths are in rollback order."""

    def __init__(self, cause: Exception, written: list[Path], restored: list[Path]) -> None:
        self.written = tuple(written)
        self.restored = tuple(restored)
        kept = [str(path) for path in written if path not in restored]
        detail = "Kept: " + ", ".join(kept) if kept else "Restored all files already written."
        super().__init__(f"Write failed: {cause}. {detail}")


def _require_text(path: Path, expected: str) -> None:
    try:
        if read_text_exact(path) == expected:
            return
    except (FileNotFoundError, UnicodeDecodeError):
        pass
    raise StaleFileError(f"{path.name} changed on disk -- reload and retry.")


def replace_with_retry(source: Path, target: Path, attempts: int = 40, delay: float = 0.25,
                       *, expected_text: str | None = None) -> None:
    """os.replace(), retried for a while: on Windows a virus scanner or the
    search indexer often holds a just-written file open for a moment, and the
    rename of a freshly written file or snapshot folder then fails with "access
    denied" although nothing is wrong."""
    for attempt in range(attempts):
        if expected_text is not None:
            _require_text(target, expected_text)
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(delay)


def swap_into_place(staging: Path, final: Path, old_dir: Path) -> None:
    """Publish a checked folder (or file) at `final`, restoring the old one if publication fails. `old_dir` is a
    unique backup path; the caller owns staging/backup cleanup and translates OSError into its own user-facing
    message. Both renames use replace_with_retry(): a folder that was just written is held open for a moment on
    Windows."""
    old = None
    try:
        if final.exists():
            old = old_dir
            old.parent.mkdir(parents=True, exist_ok=True)
            replace_with_retry(final, old)
        replace_with_retry(staging, final)
    except OSError:
        if old is not None and old.exists() and not final.exists():
            try:
                replace_with_retry(old, final)
            except OSError:
                _log.exception("Could not restore %s", final)
        raise


# os.link failing for these reasons means the volume has no hard links (FAT, exFAT, some network shares).
_NO_HARD_LINKS = {errno.EPERM, errno.ENOTSUP, errno.EMLINK}
_NO_HARD_LINKS_WINERROR = {1, 50}      # ERROR_INVALID_FUNCTION, ERROR_NOT_SUPPORTED


def _create_exclusive(path: Path, payload: bytes) -> None:
    """Create `path` with `payload`; an existing file raises FileExistsError and is never touched."""
    with open(path, "xb") as handle:
        try:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        except BaseException:
            path.unlink(missing_ok=True)
            raise


def atomic_write(path: Path, data: str | bytes, *, expected_text: str | None = None, mode: int | None = None,
                 exclusive: bool = False) -> None:
    """Write `data` (text is encoded as UTF-8; its line endings are kept as given, nothing is converted) to a
    temporary file beside `path`, flush it to disk, then replace `path` with it. Missing folders are created. An expected_text mismatch
    immediately before replacement raises StaleFileError and leaves the current file untouched. `mode` sets the
    new file's permission bits (default: the private ones of a temporary file). With exclusive=True,
    publish with a hard link that requires an absent target (an exclusive create where hard links are unsupported)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = data.encode("utf-8") if isinstance(data, str) else data
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        if mode is not None:
            os.chmod(temporary, mode)
        if exclusive:
            try:
                os.link(temporary, path)
            except OSError as error:
                if error.errno not in _NO_HARD_LINKS and getattr(error, "winerror", 0) not in _NO_HARD_LINKS_WINERROR:
                    raise
                _create_exclusive(path, payload)
        else:
            replace_with_retry(temporary, path, attempts=8, expected_text=expected_text)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            # A published hard link is already committed even if the staging name cannot be removed.
            _log.warning("Could not remove staging file %s", temporary, exc_info=True)


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


def write_texts(edits: Edits, *, expected_stamp: int | None = None,
                unused_slide_ids: tuple[Path, set[str]] | None = None) -> None:
    """Check every snapshot, then publish in order. None requires a new file.

    If given, the case-folded unused slide IDs must also be absent from the slide filenames.
    """
    global _write_stamp
    with _write_lock:
        if expected_stamp is not None and expected_stamp != _write_stamp:
            raise StaleFileError("Files changed since the project was checked.")
        if unused_slide_ids is not None:
            from .slide_ids import ids_on_disk

            directory, ids = unused_slide_ids
            collisions = ids & {i.casefold() for i in ids_on_disk(directory)}
            if collisions:
                raise StaleFileError(f"Slide ID already in use: {', '.join(sorted(collisions))} -- reload and retry.")
        for path, (before, _) in edits.items():
            if before is None:
                if os.path.lexists(path):
                    raise StaleFileError(f"{path.name} already exists -- reload and retry.")
            else:
                _require_text(path, before)
        written = []
        try:
            for path, (before, after) in edits.items():
                if before == after:
                    continue
                if before is None:
                    atomic_write(path, after, exclusive=True)
                else:
                    write_text_exact(path, after, expected_text=before)
                written.append(path)
        except (OSError, UnicodeEncodeError, StaleFileError) as cause:
            if not written:
                raise
            restored = []
            for path in reversed(written):
                before, after = edits[path]
                try:
                    if before is None:
                        _require_text(path, after)
                        path.unlink()
                    else:
                        write_text_exact(path, before, expected_text=after)
                except (OSError, StaleFileError):
                    break
                restored.append(path)
            error = PartialWriteError(cause, written, restored)
            _log.error("%s Written: %s. Restored: %s", error, written, restored)
            raise error from cause
        finally:
            if written:
                _write_stamp += 1


def read_json(path: Path, kind: type = dict) -> Any:
    """The JSON in `path`; an empty `kind()` (a dict unless asked otherwise) when the file is missing,
    unreadable, not JSON, or not a `kind`. For showing what is stored: a read that an update writes back
    uses read_json_strict(), or a damaged file would be replaced by the part being saved."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):  # ValueError covers bad JSON and bytes that are not UTF-8
        return kind()
    return data if isinstance(data, kind) else kind()


class UnreadableFileError(ValueError):
    """A file exists but is not the JSON it should be (a merge conflict, an interrupted sync, a truncated
    write). An update refuses to write it: what it writes would replace everything it could not read."""

    def __init__(self, path: Path, detail: str) -> None:
        super().__init__(f"{path.name} cannot be read ({detail}), so it was not changed. Repair it or restore an "
                         f"earlier copy (from git or your sync service's history), then try again.")
        self.path = path


def parse_json_strict(path: Path, text: str | None, kind: type = dict) -> Any:
    """What read_json_strict() makes of a file's `text` (None: the file does not exist, so an empty `kind()`)."""
    if text is None:
        return kind()
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise UnreadableFileError(path, f"not valid JSON: {exc}") from None
    if not isinstance(data, kind):
        raise UnreadableFileError(path, f"not a JSON {'object' if kind is dict else kind.__name__}")
    return data


def read_json_strict(path: Path, kind: type = dict) -> Any:
    """The JSON in `path` for a read-modify-write: an empty `kind()` only when the file does not exist.
    Raises UnreadableFileError when it is not valid UTF-8 JSON or not a `kind`, and OSError when it cannot be
    read."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return kind()
    except UnicodeDecodeError:
        raise UnreadableFileError(path, "not UTF-8 text") from None
    return parse_json_strict(path, text, kind)


def write_json(path: Path, data: Any, *, indent: int | None = 2, sort_keys: bool = True,
               ensure_ascii: bool = False) -> None:
    """`data` as JSON with a final newline, written with atomic_write()."""
    atomic_write(path, json.dumps(data, indent=indent, sort_keys=sort_keys, ensure_ascii=ensure_ascii) + "\n")


class NewerFormatError(Exception):
    """A store was written by a newer SlideMage: an older one may read it but never write it."""

    def __init__(self, path: Path) -> None:
        super().__init__(f"{path.name} was saved by a newer SlideMage. Update SlideMage to change it.")
        self.path = path


# The parsed files of every cached JsonStore, with their (mtime, size). A file changed in the last 2 s is read again
# every time (a second write inside Windows' 15 ms mtime step can keep the stamp), and a write forgets its file.
_cache_lock = threading.Lock()
_parsed: dict[Path, tuple[tuple[int, int], dict]] = {}
_RACY_NS = 2_000_000_000


def clear_json_cache() -> None:
    with _cache_lock:
        _parsed.clear()


class JsonStore:
    """One JSON object file that SlideMage keeps. read() is for showing it and never fails; update() is for changing
    it and refuses to build on what it cannot read.

    - `version`: the format version of the file's "version" field. A file with a larger one was written by a newer
      SlideMage: a strict update() raises `newer()` (default NewerFormatError) and writes nothing.
    - `lock`: a context manager (a threading.Lock, or a cross-process build_lock) or a function returning one, held
      around every update().
    - `unreadable`: turns the UnreadableFileError of a damaged file into the store's own error type.
    - `cache`: read() is served from memory while the file's stamp is unchanged (a copy the caller may change).
    - `indent`, `sort_keys`, `ensure_ascii`: how the file is written.

    update() reads the exact text, checks it again right before the atomic replacement (expected_text: another process
    may have written since) and, on a mismatch, runs the change again on the new text (up to `attempts` times)."""

    def __init__(self, path: Path, *, version: int | None = None, lock: Any = None, cache: bool = False,
                 newer: Callable[[], Exception] | None = None,
                 unreadable: Callable[[UnreadableFileError], Exception] | None = None,
                 indent: int | None = 2, sort_keys: bool = True, ensure_ascii: bool = False) -> None:
        self.path, self.version, self.lock, self.cache = path, version, lock, cache
        self._newer, self._unreadable = newer, unreadable
        self._format = {"indent": indent, "sort_keys": sort_keys, "ensure_ascii": ensure_ascii}

    def read(self) -> dict:
        """The file's object, {} when it is missing or damaged."""
        if not self.cache:
            return read_json(self.path)
        try:
            stat = os.stat(self.path)
        except OSError:
            with _cache_lock:
                _parsed.pop(self.path, None)
            return {}
        stamp = (stat.st_mtime_ns, stat.st_size)
        with _cache_lock:
            cached = _parsed.get(self.path)
        if cached is not None and cached[0] == stamp:
            return copy.deepcopy(cached[1])
        data = read_json(self.path)
        if stamp[0] < time.time_ns() - _RACY_NS:
            with _cache_lock:
                _parsed[self.path] = (stamp, copy.deepcopy(data))
        return data

    def read_strict(self) -> dict:
        """The object for a change that writes it back: {} only when the file does not exist. UnreadableFileError
        (or the store's own error) when it cannot be parsed, the `newer` error for a newer format."""
        return self._load(True)[1]

    def _load(self, strict: bool) -> tuple[str | None, dict]:
        """(the file's exact text or None, its object). Not strict: a damaged file is {} and its version unchecked."""
        try:
            text = read_text_exact(self.path)
        except FileNotFoundError:
            return None, {}
        except OSError:
            if strict:
                raise
            return None, {}
        except UnicodeDecodeError:
            text, problem = None, "not UTF-8 text"
        else:
            problem = None
        try:
            if problem:
                raise UnreadableFileError(self.path, problem)
            data = parse_json_strict(self.path, text)
        except UnreadableFileError as exc:
            if not strict:
                return text, {}
            raise (self._unreadable(exc) if self._unreadable else exc) from None
        version = data.get("version", 0)
        if strict and self.version is not None and isinstance(version, int) and version > self.version:
            raise self._newer() if self._newer else NewerFormatError(self.path)
        return text, data

    def write(self, data: dict, *, expected_text: str | None = None) -> None:
        """`data` written atomically (StaleFileError when the file no longer holds `expected_text`)."""
        with _cache_lock:
            _parsed.pop(self.path, None)
        atomic_write(self.path, json.dumps(data, **self._format) + "\n", expected_text=expected_text)

    def update(self, change: Callable[[dict], Any], *, strict: bool = True, attempts: int = 3,
               after: Callable[[dict], Any] | None = None) -> bool:
        """Read the file, let `change(data)` change that dict in place, and write it back unless `change` returned
        False. Returns whether it wrote. `strict=False` reads a damaged file as empty (preferences, where the new value
        matters more than the rest). `after(data)` runs once the file is written, still under the lock."""
        lock = self.lock
        with nullcontext() if lock is None else lock if hasattr(lock, "__enter__") else lock():
            for attempt in range(attempts):
                text, data = self._load(strict)
                if change(data) is False:
                    return False
                try:
                    self.write(data, expected_text=text)
                except StaleFileError:
                    if attempt == attempts - 1:
                        raise
                    continue
                if after is not None:
                    after(data)
                return True
        return False
