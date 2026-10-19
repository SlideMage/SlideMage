# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Print the timeline of the latest request in a project's .slidemage/timing.jsonl (see slidemage/timing.py):
every event since the last "prompt", as seconds after it.   python tools/timing_summary.py <project folder>"""
import json
import sys
from pathlib import Path


def summarize(lines: list[str]) -> list[str]:
    events = [json.loads(line) for line in lines if line.strip()]
    start = max((i for i, e in enumerate(events) if e["event"] == "prompt"), default=0)
    events = events[start:]
    if not events:
        return []
    t0 = events[0]["t"]
    return [f"+{e['t'] - t0:7.3f} s  {e['event']}" + "".join(f"  {k}={v}" for k, v in e.items() if k not in ("t", "event"))
            for e in events]


if __name__ == "__main__":
    log = Path(sys.argv[1]) / ".slidemage" / "timing.jsonl"
    print("\n".join(summarize(log.read_text(encoding="utf-8").splitlines())) if log.is_file() else f"no {log}")
