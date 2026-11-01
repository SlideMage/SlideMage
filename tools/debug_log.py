# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Read SlideMage's debug log (slidemage/diagnostics.py): filter it, or print the timeline of the latest request.

    python tools/debug_log.py [files or folders] [--area AREA] [--level LEVEL] [--grep TEXT] [--timeline]

Without files it reads every file in logs/debug of SlideMage's cache folder (SLIDEMAGE_LOG_DIR names another
log folder). Records of all files are merged by time; a record's indented lines (a traceback, a header) stay
with it. --area takes a prefix (`plugins` matches `plugins.hello`). --timeline replaces tools/timing_summary.py:
the `timing` records since the last `prompt`, as seconds after it, with the process that wrote each."""
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

LINE = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\.\d{3}) \+(\S+)s (\w+)\s+(\S+)\s+(\S+):(\d+) (\S+)  (.*)$")
LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


@dataclass
class Record:
    time: datetime
    level: str
    area: str
    role: str
    pid: int
    thread: str
    message: str
    more: list[str] = field(default_factory=list)
    text: str = ""

    @property
    def event(self) -> str:
        return self.message.split(" ", 1)[0]


def parse(lines) -> list[Record]:
    records: list[Record] = []
    for line in lines:
        line = line.rstrip("\r\n")
        match = LINE.match(line)
        if match:
            stamp, _elapsed, level, area, role, pid, thread, message = match.groups()
            records.append(Record(datetime.strptime(stamp, "%Y-%m-%d %H:%M:%S.%f"), level, area, role, int(pid),
                                  thread, message, text=line))
        elif records and line.startswith("    "):
            records[-1].more.append(line)
    return records


def read(paths: list[Path]) -> list[Record]:
    files = []
    for path in paths:
        files += sorted(p for p in path.iterdir() if p.is_file()) if path.is_dir() else [path]
    records = []
    for path in files:
        try:
            records += parse(path.read_text(encoding="utf-8", errors="replace").splitlines())
        except OSError as exc:
            print(f"cannot read {path}: {exc}", file=sys.stderr)
    return sorted(records, key=lambda r: r.time)       # sorted() is stable: a process's own order stays


def select(records, area=None, level=None, grep=None) -> list[Record]:
    floor = LEVELS.index(level.upper()) if level else 0

    def wanted(r: Record) -> bool:
        if area is not None and r.area != area and not r.area.startswith(area + "."):
            return False
        if r.level in LEVELS and LEVELS.index(r.level) < floor:
            return False
        return grep is None or grep in r.text or any(grep in line for line in r.more)

    return [r for r in records if wanted(r)]


def timeline(records) -> list[str]:
    events = [r for r in records if r.area == "timing"]
    start = max((i for i, r in enumerate(events) if r.event == "prompt"), default=0)
    events = events[start:]
    if not events:
        return []
    t0 = events[0].time
    return [f"+{(r.time - t0).total_seconds():7.3f} s  {r.message}  [{r.role}:{r.pid}]" for r in events]


def default_folder() -> Path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from slidemage import diagnostics

    return diagnostics.log_dir() / diagnostics.DEBUG_DIR


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("paths", nargs="*", type=Path, help="log files or folders (default: logs/debug)")
    parser.add_argument("--area", help="only this area and its sub-areas")
    parser.add_argument("--level", choices=[level.lower() for level in LEVELS], help="only this level and higher")
    parser.add_argument("--grep", help="only records containing this text")
    parser.add_argument("--timeline", action="store_true", help="the latest request's timing events")
    args = parser.parse_args(argv)
    records = read(args.paths or [default_folder()])
    if args.timeline:
        lines = timeline(records)
        print("\n".join(lines) if lines else "no timing events")
        return 0
    for record in select(records, args.area, args.level, args.grep):
        print(record.text)
        for line in record.more:
            print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
