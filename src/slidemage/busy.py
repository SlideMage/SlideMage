"""What keeps the machine busy for background rendering: a deck compile, an AI job, an export, a dialog.

Code that starts such work holds `working("reason")` while it runs; the idle gate (idle_gate.py) and the
reveal slider's timer ask `is_busy()`. Thread-safe, free of Qt.
"""
from __future__ import annotations

import threading
from contextlib import contextmanager

_lock = threading.Lock()
_reasons: dict[str, int] = {}


def acquire(reason: str) -> None:
    with _lock:
        _reasons[reason] = _reasons.get(reason, 0) + 1


def release(reason: str) -> None:
    with _lock:
        count = _reasons.get(reason, 0) - 1
        if count > 0:
            _reasons[reason] = count
        else:
            _reasons.pop(reason, None)


@contextmanager
def working(reason: str):
    acquire(reason)
    try:
        yield
    finally:
        release(reason)


def reasons() -> list[str]:
    with _lock:
        return sorted(_reasons)


def is_busy() -> bool:
    with _lock:
        return bool(_reasons)
