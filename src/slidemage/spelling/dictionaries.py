# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The per-user dictionary folder, and the download into it. No Qt; blocking, so call it from a worker.

A dictionary lives in `<cache>/dictionaries/<key>/` (project.cache_dir(): this computer's folder for what can be
fetched again, not roaming and never synced), once per user, not per project. A file counts as installed only when
its size and SHA-256 are the catalogue's, so a damaged or half-written file is fetched again.

The download keeps to the rules of the plugin installer: http(s) addresses only, the operating system's
certificate store (tls_trust), a size cap, and the hash checked before the file is moved into place. It is
written to a `.part` file next to its target and renamed only when it passes; on any failure the `.part` file is
deleted, so nothing half-done is ever left as a dictionary. A `.part` file a crash left behind is removed the next
time.
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
import threading
import urllib.error
import urllib.request
import uuid
from http.client import HTTPException
from pathlib import Path
from typing import Optional

from .. import fileio, project, tls_trust
from .catalogue import DictFile, Dictionary
from .checker import Report, SpellingUnavailable, sentence_start as _cap

log = logging.getLogger("slidemage.spelling")

USER_AGENT = "SlideMage-spelling"
CHUNK = 256 * 1024
_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def root() -> Path:
    return project.cache_dir() / "dictionaries"


def folder(entry: Dictionary, base: Optional[Path] = None) -> Path:
    return (base or root()) / entry.key


def _lock(key: str) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(key, threading.Lock())


def _intact(path: Path, f: DictFile) -> bool:
    try:
        return path.stat().st_size == f.size and fileio.sha256_file(path) == f.sha256
    except OSError:
        return False


def missing(entry: Dictionary, base: Optional[Path] = None) -> list[DictFile]:
    """The files of `entry` that are not there with the catalogue's size and hash."""
    target = folder(entry, base)
    return [f for f in entry.files if not _intact(target / f.name, f)]


def installed(entry: Dictionary, base: Optional[Path] = None) -> bool:
    return not missing(entry, base)


def _download(f: DictFile, dest: Path, *, timeout: float, report: Optional[Report], done_before: int,
              total: int, label: str) -> None:
    """Fetch `f` into `dest` (a .part file), checking size and hash. Raises SpellingUnavailable; the caller deletes
    `dest` on failure."""
    if not re.match(r"^https?://", f.url):
        raise SpellingUnavailable(f"The address of {label} is not an http(s) address.")
    request = urllib.request.Request(f.url, headers={"User-Agent": USER_AGENT})
    digest = hashlib.sha256()
    done = 0
    message = f"Downloading {label} ({max(1, round(total / 1_000_000))} MB)…"
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response, open(dest, "wb") as out:
            declared = int(response.headers.get("Content-Length") or 0)
            if declared and declared != f.size:
                raise SpellingUnavailable(f"{_cap(label)} on the server is not the file SlideMage expects; "
                                          "a newer SlideMage may be needed.")
            while chunk := response.read(CHUNK):
                done += len(chunk)
                if done > f.size:
                    raise SpellingUnavailable(f"{_cap(label)} on the server is larger than expected; "
                                              "nothing was installed.")
                digest.update(chunk)
                out.write(chunk)
                if report:
                    report(done_before + done, total, message)
    except SpellingUnavailable:
        raise
    except (urllib.error.URLError, HTTPException, OSError, ValueError) as e:
        reason = tls_trust.certificate_message(e, f.url) or str(getattr(e, "reason", None) or e)
        raise SpellingUnavailable(f"{_cap(label)} could not be downloaded: {reason}") from None
    if done != f.size or digest.hexdigest() != f.sha256:
        raise SpellingUnavailable(f"{_cap(label)} that was downloaded is not the file SlideMage expects "
                                  "(size or checksum differs); nothing was installed.")


def ensure(entry: Dictionary, report: Optional[Report] = None, *, base: Optional[Path] = None,
           timeout: float = 30) -> Path:
    """Make every file of `entry` present and intact, downloading what is missing. Returns the folder. Raises
    SpellingUnavailable with a message for the person. Two callers for the same dictionary wait for each other."""
    target = folder(entry, base)
    with _lock(entry.key):
        try:
            target.mkdir(parents=True, exist_ok=True)
            for stale in target.glob("*.part-*"):
                stale.unlink(missing_ok=True)
        except OSError as e:
            raise SpellingUnavailable(f"The dictionary folder {target} cannot be written: {e}") from None
        todo = missing(entry, base)
        total = sum(f.size for f in todo)
        done_before = 0
        for f in todo:
            final = target / f.name
            part = target / f"{f.name}.part-{uuid.uuid4().hex[:8]}"
            try:
                _download(f, part, timeout=timeout, report=report, done_before=done_before, total=total,
                          label=entry.label)
                os.replace(part, final)
            except BaseException:
                part.unlink(missing_ok=True)
                raise
            done_before += f.size
            log.info("spelling: downloaded %s (%d bytes) for %s", f.name, f.size, entry.key)
    return target
