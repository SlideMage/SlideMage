# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Saves a deck's source in a window over a COPY of a project and prints what the save triggered, with the debug
log's timing lines (spans, rebuild callers, header sync, thumbnail pass, stalls of the GUI thread) in time order.

    python tools/freeze_probe.py D:/uniCLOUD/Slidemaster --deck "#workdeck" --scenario edit
    python tools/freeze_probe.py D:/uniCLOUD/Slidemaster --scenario edit --burners 6      # with the CPUs busy
    python tools/freeze_probe.py D:/uniCLOUD/Slidemaster --scenario remove --seconds 12

Scenarios: `noop` (save with no change to the text), `edit` (a comment line is added), `remove` (the first
\slide line goes). The project is copied to a temporary folder first (the header sync rewrites slide files);
`--burners N` starts N processes that use a CPU each, to see how the same save behaves on a loaded machine;
`--background-previews` lets the idle-time preview renderer run, as in the app (off by default, as in the tests).
Needs a display unless QT_QPA_PLATFORM=offscreen (the default here)."""
from __future__ import annotations

import argparse
import logging
import multiprocessing
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


def _burn() -> None:
    while True:
        sum(i * i for i in range(10_000))


class Collector(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.DEBUG)
        self.lines: list[tuple[float, str, str, str]] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append((record.created, record.name.removeprefix("slidemage."), record.threadName,
                           record.getMessage()))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("project", type=Path)
    parser.add_argument("--deck", help="deck name (default: the first active deck)")
    parser.add_argument("--scenario", choices=("noop", "edit", "remove"), default="edit")
    parser.add_argument("--seconds", type=float, default=10.0, help="how long to watch after the save")
    parser.add_argument("--burners", type=int, default=0)
    parser.add_argument("--background-previews", action="store_true")
    parser.add_argument("--runs", type=int, default=1, help="saves in a row, 3 s apart (an edit each)")
    args = parser.parse_args()

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ.pop("SLIDEMAGE_NO_STALL_MONITOR", None)
    if not args.background_previews:
        os.environ["SLIDEMAGE_NO_BACKGROUND_PREVIEWS"] = "1"
    work = Path(tempfile.mkdtemp(prefix="freeze-probe-"))
    root = work / args.project.name
    print(f"copying {args.project} -> {root} ...", flush=True)
    shutil.copytree(args.project, root, ignore=shutil.ignore_patterns(".git", "__pycache__", ".slidemage"))

    from PySide6.QtCore import QCoreApplication, QElapsedTimer
    from PySide6.QtWidgets import QApplication

    from slidemage.project import ProjectContext
    from slidemage.ui.kit.fonts import load_fonts
    from slidemage.ui.kit.theme import ThemeManager
    from slidemage.ui.workspace.window import WorkspaceWindow

    collector = Collector()
    logger = logging.getLogger("slidemage")
    logger.setLevel(logging.DEBUG)
    logger.addHandler(collector)
    app = QApplication.instance() or QApplication([])
    load_fonts()
    context = ProjectContext.at(root)
    window = WorkspaceWindow(ThemeManager(project=context), context)
    window.resize(1500, 900)
    window.show()
    deck = next((d for d in window.decks if d.name == args.deck), None) if args.deck else \
        next((d for d in window.decks if not d.archived), None)
    if deck is None:
        print("no such deck; decks:", ", ".join(d.name for d in window.decks))
        return 1
    window.state.set_deck(deck)
    window.reload_decks()
    window.state.set_mode("source")

    def pump(seconds: float) -> None:
        clock = QElapsedTimer()
        clock.start()
        while clock.elapsed() < seconds * 1000:
            app.processEvents()
            time.sleep(0.005)

    pump(3)                                                    # the window settles: first thumbnails, timers
    window.open_deck_source_editor(window.state.deck)
    pump(1)
    burners = [multiprocessing.Process(target=_burn, daemon=True) for _ in range(args.burners)]
    for burner in burners:
        burner.start()
    source = window.centre.source.current
    marks = []
    for run in range(args.runs):
        text = source.editor.text()
        if args.scenario == "edit":
            source.editor.replace_all_text(text + f"\n% probe {run}\n")
        elif args.scenario == "remove":
            lines = text.split("\n")
            index = next((i for i, line in enumerate(lines) if line.strip().startswith("\slide{")), None)
            if index is None:
                print("no \slide line in the deck source")
                break
            source.editor.replace_all_text("\n".join(lines[:index] + lines[index + 1:]))
        marks.append(time.time())
        began = time.perf_counter()
        source.write_now()
        print(f"run {run}: write_now() blocked the GUI thread for {time.perf_counter() - began:.3f} s", flush=True)
        pump(args.seconds if run == args.runs - 1 else 3)
    for burner in burners:
        burner.terminate()

    start = marks[0] if marks else collector.lines[0][0]
    print(f"\n--- timeline (s after the first save; scenario={args.scenario} burners={args.burners}) ---")
    for created, area, thread, message in collector.lines:
        if created < start - 0.001 or area not in ("timing",):
            continue
        short = message if len(message) < 600 else message[:600] + " ..."
        print(f"{created - start:7.3f}  {thread[:22]:22}  {short}")
    stalls = [m for _t, a, _th, m in collector.lines if a == "timing" and m.startswith("stall")]
    print(f"\n{len(stalls)} stall(s) of the GUI thread (> 0.15 s late)")
    window.hide()
    window.deleteLater()
    QCoreApplication.sendPostedEvents(None, 0)
    shutil.rmtree(work, ignore_errors=True)
    sys.stdout.flush()
    os._exit(0)             # worker threads and the debug machinery need no orderly shutdown here


if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(main())
