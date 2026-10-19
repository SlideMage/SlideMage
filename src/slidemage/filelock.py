# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The cross-process file lock (`build_lock`) shared by preview builds and the review store; light enough for the
Claude Code hook process to import (no Qt, compiler or PDF libraries)."""
from __future__ import annotations

import errno
import os
import time
from contextlib import contextmanager
from pathlib import Path

from .preview_metrics import stage


@contextmanager
def build_lock(path: Path, *, blocking=True, shared=False, cancel=None):
    """OS-owned lock, released on crashes as well as normal returns."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b') as stream:
        acquired = False
        with stage('lock_wait'):
            if os.name == 'nt':
                if not path.stat().st_size:
                    stream.write(b'\0')
                    stream.flush()
                while True:
                    check_cancel(cancel)
                    if _windows_lock(stream, shared):
                        acquired = True
                        break
                    if not blocking:
                        break
                    time.sleep(.1)
            else:
                import fcntl
                mode = fcntl.LOCK_SH if shared else fcntl.LOCK_EX
                while True:
                    check_cancel(cancel)
                    try:
                        fcntl.flock(stream, mode | fcntl.LOCK_NB)
                        acquired = True
                        break
                    except BlockingIOError:
                        if not blocking:
                            break
                        time.sleep(.05)
        try:
            yield acquired
        finally:
            if not acquired:
                pass
            elif os.name == 'nt':
                _windows_unlock(stream)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


# Windows: LockFileEx, which (unlike msvcrt.locking) has shared locks. With msvcrt every "shared" holder excluded
# every other, so the preview compiles of a project, which all hold the maintenance lock shared, ran one at a time.
_LOCKFILE_FAIL_IMMEDIATELY, _LOCKFILE_EXCLUSIVE_LOCK = 0x1, 0x2
_ERROR_LOCK_VIOLATION = 33


def _overlapped():
    import ctypes
    from ctypes import wintypes

    class OVERLAPPED(ctypes.Structure):
        _fields_ = [("Internal", ctypes.c_void_p), ("InternalHigh", ctypes.c_void_p), ("Offset", wintypes.DWORD),
                    ("OffsetHigh", wintypes.DWORD), ("hEvent", wintypes.HANDLE)]
    return OVERLAPPED()


def _windows_lock(stream, shared: bool) -> bool:
    """Take the lock on the file's first byte without waiting: True if it was granted."""
    import ctypes
    import msvcrt

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = msvcrt.get_osfhandle(stream.fileno())
    flags = _LOCKFILE_FAIL_IMMEDIATELY | (0 if shared else _LOCKFILE_EXCLUSIVE_LOCK)
    overlapped = _overlapped()
    if kernel32.LockFileEx(ctypes.c_void_p(handle), flags, 0, 1, 0, ctypes.byref(overlapped)):
        return True
    error = ctypes.get_last_error()
    if error == _ERROR_LOCK_VIOLATION:
        return False
    raise OSError(errno.EACCES, f"LockFileEx failed with Windows error {error}", str(getattr(stream, "name", "")))


def _windows_unlock(stream) -> None:
    import ctypes
    import msvcrt

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    overlapped = _overlapped()
    kernel32.UnlockFileEx(ctypes.c_void_p(msvcrt.get_osfhandle(stream.fileno())), 0, 1, 0, ctypes.byref(overlapped))


def check_cancel(cancel):
    if cancel is not None and cancel.is_set():
        raise RuntimeError('Preview cancelled')
