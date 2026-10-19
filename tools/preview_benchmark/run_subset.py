# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Freeze inputs and compare four manual calls in adjacent before/after order."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import time

from experiment import atomic_json, bind, tree_hashes

INDICES = [54, 58, 70, 80]
IGNORE = shutil.ignore_patterns(".git", ".build", ".previews", ".temp", "__pycache__", "_slidemage_*", "_snapshot_*")


def freeze(origin, destination):
    if destination.exists():
        if tree_hashes(origin) != tree_hashes(destination):
            raise ValueError(f"Frozen inputs changed: {origin}")
    else:
        shutil.copytree(origin, destination, ignore=IGNORE)


def archive(base, destination):
    """Durable local evidence; omit project settings and credential storage."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    checksums = {}
    with tarfile.open(destination, "w:gz") as bundle:
        for folder in ("results", "sources", "project", "framework", "tools"):
            root = base / folder
            for path in sorted(root.rglob("*")):
                relative = path.relative_to(base)
                if not path.is_file() or any(part in {".build", ".previews", "__pycache__", ".git", ".temp"}
                                              for part in relative.parts):
                    continue
                if folder == "project" and path.suffix.lower() not in {
                    ".tex", ".bib", ".sty", ".pdf", ".png", ".jpg", ".jpeg", ".eps", ".ttf", ".otf", ".csv",
                } and path.name != ".latexmkrc":
                    continue
                if path.name.startswith(("_slidemage_", "_snapshot_")):
                    continue
                checksums[relative.as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
                bundle.add(path, arcname=relative.as_posix(), recursive=False)
        atomic_json(base / "artifact-checksums.json", checksums)
        bundle.add(base / "artifact-checksums.json", arcname="artifact-checksums.json")
    return dict(path=str(destination.resolve()), sha256=hashlib.sha256(destination.read_bytes()).hexdigest(),
                files=len(checksums))


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("--before-source", type=Path, required=True)
    parser.add_argument("--after-source", type=Path, default=Path("src"))
    parser.add_argument("--project", type=Path, default=Path("example"))
    parser.add_argument("--framework", type=Path, default=Path("latex"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--time-budget", type=float, default=600)
    parser.add_argument("--order-seed", type=int, default=0)
    args = parser.parse_args()
    base = args.output.resolve()
    if not base.is_relative_to(Path("/tmp")) or args.time_budget <= 0:
        parser.error("Use a scratch output under /tmp and a positive time budget")
    base.mkdir(parents=True, exist_ok=True)
    sources = {"before": args.before_source.resolve(), "after": args.after_source.resolve()}
    scripts = Path(__file__).parent
    selection = dict(indices=INDICES, source={label: tree_hashes(path, python_only=True) for label, path in sources.items()},
                     project=tree_hashes(args.project), framework=tree_hashes(args.framework),
                     benchmark_tools=tree_hashes(scripts, python_only=True), order_seed=args.order_seed)
    bind(base / "selection.json", selection)
    for label, path in sources.items():
        freeze(path, base / "sources" / label)
    freeze(args.project, base / "project")
    freeze(args.framework, base / "framework")
    freeze(scripts, base / "tools")
    results = base / "results"
    results.mkdir(exist_ok=True)
    started = time.time()
    deadline = started + args.time_budget
    order_path = results / "orchestration.json"
    order = json.loads(order_path.read_text()) if order_path.exists() else []
    stopped = False
    for position, index in enumerate(INDICES):
        labels = ("before", "after") if (position + args.order_seed) % 2 == 0 else ("after", "before")
        for label in labels:
            if time.time() >= deadline or (results / "STOP").exists():
                stopped = True
                break
            env = dict(os.environ, PYTHONPATH=str(base / "sources" / label),
                       SLIDEMASTER_PROJECT=str(base / "project"), SLIDEMASTER_LATEX=str(base / "framework"))
            command = [sys.executable, str(scripts / "compare.py"), "--output", str(results),
                       "--label", label, "--indices", str(index), "--subset-indices", *map(str, INDICES),
                       "--repeats", "2", "--deadline", str(deadline), "--time-budget", str(args.time_budget),
                       "--order-seed", str(args.order_seed)]
            if label == "before":
                command += ["--configs", "saved"]
            else:
                command += ["--defer-images"]
            print(f"Call {index}, {label}; elapsed {time.time()-started:.1f}s", flush=True)
            step = dict(index=index, label=label, started=time.time(), command=command)
            order.append(step)
            atomic_json(order_path, order)
            with (results / f"orchestrator-{len(order):03}-{label}-{index}.log").open("w") as log:
                returncode = subprocess.call(command, env=env, stdout=log, stderr=subprocess.STDOUT)
            step.update(returncode=returncode, seconds=time.time()-step["started"])
            atomic_json(order_path, order)
            if returncode:
                stopped = True
                break
        if stopped:
            break
    # The summarizer performs identity, subset, failure and output gates.
    command = [sys.executable, str(scripts / "summarize.py"), str(results), str(args.report)]
    returncode = subprocess.call(command)
    if returncode:
        subprocess.check_call(command + ["--allow-incomplete"])
    shutil.copy2(args.report, results / "summary.md")
    shutil.copy2(args.report.with_suffix(".json"), results / "summary.json")
    artifact = archive(base, args.archive)
    report_json = args.report.with_suffix(".json")
    data = json.loads(report_json.read_text())
    data["artifact"] = artifact
    data["wall_seconds"] = time.time()-started
    atomic_json(report_json, data)
    with args.report.open("a") as report:
        report.write(f"\nEvidence archive: `{artifact['path']}`; SHA-256 `{artifact['sha256']}`. "
                     f"Completed {len(data['records'])} records in {data['wall_seconds']:.1f} s.\n")
    print(json.dumps(dict(complete=data["complete"], records=len(data["records"]),
                          seconds=data["wall_seconds"], artifact=artifact)), flush=True)
    return 0 if data["complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
