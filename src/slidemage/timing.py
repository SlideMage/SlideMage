# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Optional prompt-to-preview timing, off unless SLIDEMAGE_TIMING=1 is in the environment (the embedded Claude Code
and its hooks inherit it). `event` appends one JSON line {"t": epoch seconds, "event": name, ...} to
<project>/.slidemage/timing.jsonl; `python tools/timing_summary.py <project>` prints the latest request's timeline."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

ENV = "SLIDEMAGE_TIMING"
LOG_NAME = "timing.jsonl"


def enabled() -> bool:
    return os.environ.get(ENV) == "1"


def event(root: Path, name: str, **fields) -> None:
    """Record `name` now; a no-op when timing is off and never an error when the log cannot be written."""
    if not enabled():
        return
    line = json.dumps({"t": round(time.time(), 3), "event": name, **fields}) + "\n"
    try:
        log = Path(root) / ".slidemage" / LOG_NAME
        log.parent.mkdir(parents=True, exist_ok=True)
        with open(log, "a", encoding="utf-8") as stream:
            stream.write(line)          # one short append: lines from the hook and the app do not interleave
    except OSError:
        pass
