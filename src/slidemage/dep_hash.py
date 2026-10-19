# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""SHA-256 of files with a (size, mtime) shortcut, for telling what a render depends on has changed.

The mtime is only a shortcut: a file whose size and modification time are as they were when it was last
hashed keeps its hash without being read; anything else is read again. A file modified within the last
RACY_SECONDS is never trusted by the shortcut and its hash is not kept (a sync client may still be
writing it; the same "racy" rule as git's index), so its hash is looked at again next time. After reading,
the file is stat-ed once more: one that moved while it was read has no hash yet (None).

Cloud-synced folders make this matter: the sync client may restore another machine's modification time
(a changed file with an old mtime has another size or is caught by the periodic audit, see
HashCache.audit) and may touch a file without changing it (a rehash gives the same hash again).
Free of Qt.
"""
from __future__ import annotations

import hashlib
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Callable, Optional

RACY_SECONDS = 3.0

SCHEMA = """
CREATE TABLE IF NOT EXISTS filehash (
    path TEXT PRIMARY KEY, size INTEGER NOT NULL, mtime_ns INTEGER NOT NULL, sha256 TEXT NOT NULL)
"""


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def norm(path: Path | str) -> str:
    return os.path.normcase(os.path.normpath(str(path)))


class HashCache:
    """File hashes kept in the `filehash` table of a SQLite connection (the render store's local index)."""

    def __init__(self, connection: sqlite3.Connection, lock: Optional[threading.RLock] = None, *,
                 clock: Callable[[], float] = time.time, hasher: Callable[[Path], str] = file_sha256) -> None:
        self._db = connection
        self._lock = lock or threading.RLock()
        self._clock = clock
        self._hasher = hasher
        self.reads = 0              # files actually read (for tests and the status log)
        with self._lock:
            self._db.execute(SCHEMA)

    def hash(self, path: Path | str, *, verify: bool = False) -> Optional[str]:
        """The SHA-256 of `path`, or None when the file is missing, unreadable or changed while read.
        `verify` ignores the shortcut (the idle audit)."""
        key = norm(path)
        try:
            before = os.stat(path)
        except OSError:
            return None
        racy = self._clock() - before.st_mtime < RACY_SECONDS
        if not verify and not racy:
            with self._lock:
                row = self._db.execute("SELECT size, mtime_ns, sha256 FROM filehash WHERE path=?", (key,)).fetchone()
            if row and row[0] == before.st_size and row[1] == before.st_mtime_ns:
                return row[2]
        try:
            digest = self._hasher(Path(path))
            after = os.stat(path)
        except OSError:
            return None
        self.reads += 1
        if (after.st_size, after.st_mtime_ns) != (before.st_size, before.st_mtime_ns):
            return None
        if not racy:
            with self._lock:
                self._db.execute("INSERT OR REPLACE INTO filehash VALUES (?,?,?,?)",
                                 (key, before.st_size, before.st_mtime_ns, digest))
                self._db.commit()
        return digest

    def is_racy(self, path: Path | str) -> bool:
        """The file was modified so recently that its hash cannot be trusted yet."""
        try:
            return self._clock() - os.stat(path).st_mtime < RACY_SECONDS
        except OSError:
            return False

    def audit(self, limit: int = 20) -> list[str]:
        """Re-read up to `limit` of the oldest-checked files ignoring the shortcut; the paths whose content
        had changed under an unchanged size and mtime (what only a sync client can produce)."""
        with self._lock:
            rows = self._db.execute("SELECT path, sha256 FROM filehash ORDER BY RANDOM() LIMIT ?", (limit,)).fetchall()
        changed = []
        for path, old in rows:
            if self.hash(path, verify=True) not in (old, None):
                changed.append(path)
        return changed
