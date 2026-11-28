# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Read SlideMage's debug log (slidemage/diagnostics.py): filter it, or print the timeline of the latest request.

    python tools/debug_log.py [files or folders] [--area AREA] [--level LEVEL] [--grep TEXT] [--timeline] [--stalls]

Without files it reads every file in logs/debug of SlideMage's cache folder (SLIDEMAGE_LOG_DIR names another
log folder). Records of all files are merged by time; a record's indented lines (a traceback, a header) stay
with it. --area takes a prefix (`plugins` matches `plugins.hello`). --timeline replaces tools/timing_summary.py:
the `timing` records since the last `prompt`, as seconds after it, with the process that wrote each. --stalls
ranks, over the `stall` records of stall_monitor.py, the GUI frames and the busy worker frames of each stall."""
from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

LINE = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\.\d{3}) \+(\S+)s (\w+)\s+(\S+)\s+(\S+):(\d+) (.+?)  (.*)$")
LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
STALL_LATE = re.compile(r"stall late=([\d.]+)")
GUI_IDLE_FRAME = "app.py main"          # ui/app.py: sys.exit(app.exec()), so the Qt event loop is innermost
GUI_IDLE = "GUI idle, worker busy"
MONITOR_FRAMES = ("stall_monitor.py ", "timing.py ")
# Parked in a blocking call, which releases the GIL; stall_monitor prints their callers, as for any other worker.
BLOCKED_FRAMES = {"selectors.py select", "ptyprocess.py read", "socket.py readinto", "subprocess.py _communicate"}


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


def frame_key(frame: str) -> str:
    """`file:line function` as `file function`: without the line, the counts of one function merge."""
    where, _, func = frame.rpartition(" ")              # `<frozen x>` has a space: the function is after the last one
    return f"{where.rsplit(':', 1)[0]} {func}"


def stall_report(records) -> list[str]:
    """The GUI frames and the busy worker frames during each stall, most frequent first. A stall counts once per
    frame, however many samples of it show that frame; a worker with one frame, or in a
    blocking call (BLOCKED_FRAMES), is parked, not busy."""
    gui, workers = defaultdict(lambda: [0, 0.0]), defaultdict(lambda: [0, 0.0])
    stalls, idle, late_total = 0, 0, 0.0
    for r in records:
        if r.area != "timing" or r.event != "stall":
            continue
        late = float(STALL_LATE.match(r.message).group(1))
        stalls += 1
        late_total += late
        seen_gui, seen_workers = set(), set()
        for sample in r.message.partition("threads=[")[2][:-1].split(" || "):
            for part in sample.split("; "):
                name, at, chain = part.partition("@")
                if not at:
                    continue                                    # "(none taken)"
                frames = [frame_key(f) for f in chain.split(" < ")]
                if name == "GUI":
                    own = [f for f in frames if not f.startswith(MONITOR_FRAMES)] or frames
                    seen_gui.add(GUI_IDLE if own[0] == GUI_IDLE_FRAME else own[0])
                elif len(frames) > 1 and frames[0] not in BLOCKED_FRAMES:
                    seen_workers.add((re.sub(r"\d+", "", name), frames[0]))
        idle += GUI_IDLE in seen_gui
        for key in seen_gui or {"(no sample)"}:
            gui[key][0] += 1
            gui[key][1] += late
        for key in seen_workers:
            workers[key][0] += 1
            workers[key][1] += late
    if not stalls:
        return ["no stall records"]

    def ranked(table):
        return sorted(table.items(), key=lambda item: (-item[1][0], -item[1][1]))

    lines = ["GUI thread:", f"{'count':>6} {'late s':>8}  frame"]
    lines += [f"{n:>6} {s:>8.2f}  {key}" for key, (n, s) in ranked(gui)]
    lines += ["", "busy workers during stalls:", f"{'count':>6} {'late s':>8}  thread  frame"]
    lines += [f"{n:>6} {s:>8.2f}  {name}  {key}" for (name, key), (n, s) in ranked(workers)]
    lines.append(f"{stalls} stalls, {late_total:.2f} s late, GUI idle in {idle}")
    return lines


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
    parser.add_argument("--stalls", action="store_true", help="what the GUI and busy workers did during stalls")
    args = parser.parse_args(argv)
    records = read(args.paths or [default_folder()])
    if args.timeline:
        lines = timeline(records)
        print("\n".join(lines) if lines else "no timing events")
        return 0
    if args.stalls:
        print("\n".join(stall_report(select(records, args.area, args.level, args.grep))))
        return 0
    for record in select(records, args.area, args.level, args.grep):
        print(record.text)
        for line in record.more:
            print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
