# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Add three typical editing examples to the existing one-bullet comparison."""

import argparse
import json
from pathlib import Path
from statistics import mean
import subprocess
import sys
import time

from experiment import atomic_json


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("--before-source", type=Path)
    parser.add_argument("--after-source", type=Path, default=Path("src"))
    parser.add_argument("--project", type=Path, default=Path("example"))
    parser.add_argument("--framework", type=Path, default=Path("latex"))
    parser.add_argument("--bullet-report", type=Path, default=Path("docs/preview-bullet-edit-2026-10-11.json"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--archive-dir", type=Path)
    parser.add_argument("--summarize-only", action="store_true")
    parser.add_argument("--time-budget", type=float, default=180)
    args = parser.parse_args()
    if args.time_budget <= 0:
        parser.error("Use a positive budget")
    base = args.output.resolve()
    if not base.is_relative_to(Path("/tmp")):
        parser.error("Use a scratch directory under /tmp")
    if not args.summarize_only:
        if base.exists() or not args.before_source or not args.archive_dir:
            parser.error("Provide original source, archive directory and a new scratch output")
        base.mkdir(parents=True)
    records = {"bullet": json.loads(args.bullet_report.read_text())}
    assert records["bullet"]["complete"]
    if args.summarize_only:
        for case in ("title", "formula", "figure"):
            records[case] = json.loads((base / f"{case}.json").read_text())
        seconds = json.loads((base / "run.json").read_text())["added_wall_seconds"]
        write_report(records, args.report, seconds)
        return
    started = time.time()
    deadline = started + args.time_budget
    for position, case in enumerate(("title", "formula", "figure")):
        order = "original-first" if position % 2 == 0 else "optimized-first"
        command = [sys.executable, str(Path(__file__).with_name("bullet_edit.py")),
            "--before-source", str(args.before_source), "--after-source", str(args.after_source),
            "--project", str(args.project), "--framework", str(args.framework),
            "--output", str(base / case), "--case", case, "--order", order,
            "--report", str(base / f"{case}.md"), "--archive",
            str(args.archive_dir / f"{case}.tar.gz"),
            "--time-budget", str(args.time_budget), "--deadline", str(deadline)]
        print(f"Measuring {case}, {order}; elapsed {time.time()-started:.1f}s", flush=True)
        subprocess.check_call(command)
        records[case] = json.loads((base / f"{case}.json").read_text())
    seconds = time.time()-started
    atomic_json(base / "run.json", dict(added_wall_seconds=seconds))
    write_report(records, args.report, seconds)


def write_report(records, destination, seconds):
    assert list(records) == ["bullet", "title", "formula", "figure"], "Missing or reordered examples"
    for record in records.values():
        for samples in record["records"].values():
            assert [s["phase"] for s in samples] == ["cold", "edit-1", "edit-2", "unchanged"]
            assert all(s["ok"] for s in samples)
            for position in (1, 2):
                assert samples[position]["visible_edit"]
                assert samples[position]["signature"] != samples[position - 1]["signature"], "Invisible edit"
        for before, after in zip(record["records"]["original-fresh"], record["records"]["optimized"], strict=True):
            assert before["signature"] == after["signature"], "PDF mismatch"
            assert before["display_signature"] == after["display_signature"], "Display mismatch"
    names = dict(bullet="Edit one bullet", title="Change the slide title",
                 formula="Edit a formula", figure="Resize a figure")
    lines = ["# Typical preview editing gains — 11 October 2026", "",
        "Comparison against the original fresh-job behavior, before build reuse. Each row averages "
        "two actual successive edits after an initial preview, using the same input in both saved-file paths. "
        "The bullet measurement is the earlier 44.3-second probe; the three added examples "
        "are measured sequentially in this run, alternating original/optimized order by case.", "",
        "| Typical action | Original fresh job, s | Optimized preview, s | Seconds saved | Speedup | Less time |",
        "| --- | ---: | ---: | ---: | ---: | ---: |"]
    summaries = []
    for case, record in records.items():
        assert record["complete"] and record["pdf_matches"] == 4 and record["display_matches"] == 4
        assert record["visible_edits"] == 4
        before, after = (mean(s["seconds"] for s in record["records"][label]
                             if s["phase"].startswith("edit-")) for label in ("original-fresh", "optimized"))
        summary = dict(case=case, name=names[case], before=before, after=after,
                       saved=before-after, speedup=before/after, reduction=1-after/before)
        summaries.append(summary)
        lines.append(f"| {names[case]} | {before:.3f} | {after:.3f} | {before-after:.3f} | "
                     f"{before/after:.2f}× | {1-after/before:.1%} |")
    lines += ["", "The title test leaves body content unchanged. The formula test changes only the "
        "denominator; the figure test changes only image height; their titles remain unchanged. "
        "The main saving comes from retaining latexmk auxiliary state and resolved bibliography data. "
        "Required passes are still chosen by latexmk; no pass cap or draft output is used.", "",
        "These timings include backend compilation, GUI image preparation and permitted snapshot writes, "
        "with the TeX font cache warm. Lint, the automatic-save debounce and Qt painting are excluded. "
        "Original and optimized output matched for every phase at 72 dpi and 1920-pixel display width. "
        "These are representative examples from two slides, not a corpus-wide average or a universal "
        "speed guarantee. Initial previews still take about 7–8 seconds; the known spacing fallback "
        "case remains slower.", "",
        "This baseline is the original fresh-build behavior. The separate BIG CHANGE 2 comparison "
        "starts from an already cached implementation and measures its additional effect."]
    data = dict(complete=True, summary=summaries, examples=records,
                added_wall_seconds=seconds, added_requests=24,
                pdf_matches=16, display_matches=16, visible_edits=16)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(("\n".join(lines)+"\n").replace("\n", "\r\n").encode())
    atomic_json(destination.with_suffix(".json"), data)
    print(json.dumps(dict(complete=True, examples=4, added_seconds=data["added_wall_seconds"])), flush=True)


if __name__ == "__main__":
    main()
