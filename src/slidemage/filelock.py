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
                import msvcrt
                if not path.stat().st_size:
                    stream.write(b'\0')
                    stream.flush()
                while True:
                    check_cancel(cancel)
                    try:
                        stream.seek(0)
                        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                        acquired = True
                        break
                    except OSError as exc:
                        if exc.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                            raise
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
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


def check_cancel(cancel):
    if cancel is not None and cancel.is_set():
        raise RuntimeError('Preview cancelled')
