# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Prompt-to-preview timing in the debug log (area `timing`), from the app, the AI tools and the Claude Code hooks,
each process in its own debug file. `python tools/debug_log.py --timeline` merges them and prints the latest
request's timeline. SLIDEMAGE_TIMING=1 still turns the debug log on (diagnostics.forced). Until v0.13.7 the
events went to <project>/.slidemage/timing.jsonl, read by tools/timing_summary.py."""
from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from pathlib import Path

ENV = "SLIDEMAGE_TIMING"
log = logging.getLogger("slidemage.timing")


def enabled() -> bool:
    return log.isEnabledFor(logging.DEBUG)


def event(root: Path, name: str, **fields) -> None:
    """Record `name` now as `name key=value ...`; a no-op while the debug log is off. `root` (the project) stays in
    the signature for the callers and the plugin API's HookContext.timing_event."""
    if enabled():
        log.debug("%s%s", name, "".join(f" {key}={value}" for key, value in fields.items()))


@contextmanager
def span(name: str, **fields):
    """Log `name seconds=… key=value …` when the block ends, so that a stall shows in the debug log with the
    step that took it (area `timing`); a no-op while the debug log is off."""
    if not enabled():
        yield
        return
    start = time.perf_counter()
    try:
        yield
    finally:
        seconds = time.perf_counter() - start
        log.debug("%s seconds=%.3f%s", name, seconds, "".join(f" {key}={value}" for key, value in fields.items()))


def stack_summary(skip: int = 2, depth: int = 6) -> str:
    """The callers of the function that asks, innermost first, as `module.function:line > ...` (for `caller`)."""
    import sys
    frames = []
    frame = sys._getframe(skip)
    while frame is not None and len(frames) < depth:
        module = frame.f_globals.get("__name__", "?").removeprefix("slidemage.").removeprefix("ui.workspace.")
        frames.append(f"{module}.{frame.f_code.co_name}:{frame.f_lineno}")
        frame = frame.f_back
    return " > ".join(frames)


def caller(name: str, **fields) -> None:
    """`name` with the call stack that led here, to find out what triggers a rebuild or a refresh; a no-op while the
    debug log is off."""
    if enabled():
        log.debug("%s%s stack=%s", name, "".join(f" {key}={value}" for key, value in fields.items()), stack_summary(3))
