# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Prompt-to-preview timing in the debug log (area `timing`), from the app, the AI tools and the Claude Code hooks,
each process in its own debug file. `python tools/debug_log.py --timeline` merges them and prints the latest
request's timeline. SLIDEMAGE_TIMING=1 still turns the debug log on (diagnostics.forced). Until v0.13.6 the
events went to <project>/.slidemage/timing.jsonl, read by tools/timing_summary.py."""
from __future__ import annotations

import logging
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
