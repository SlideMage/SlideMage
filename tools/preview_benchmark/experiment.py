# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Immutable experiment identities, atomic records, and small-run validation."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import tempfile

SCHEMA = 2
EDIT_VERSION = "visible-title-and-body-v2"
CONFIGS = ("saved", "buffer", "overlay", "buffer-overlay")


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".record-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def bind(path, identity):
    path = Path(path)
    if path.exists():
        if json.loads(path.read_text()) != identity:
            raise ValueError(f"Incompatible experiment resume: {path}")
    else:
        atomic_json(path, identity)


def tree_hashes(root, *, python_only=False):
    """Hash inputs, excluding generated state; normalize Python line endings."""
    root = Path(root)
    result = {}
    for path in sorted(root.rglob("*.py" if python_only else "*")):
        relative = path.relative_to(root)
        if any(part in {".git", ".build", ".previews", ".temp", "__pycache__"}
               for part in relative.parts):
            continue
        if path.name.startswith(("_slidemage_", "_snapshot_")) or not path.is_file():
            continue
        data = path.read_bytes()
        if python_only:
            data = data.replace(b"\r\n", b"\n")
        result[relative.as_posix()] = hashlib.sha256(data).hexdigest()
    return result


def command_output(command, cwd=None):
    try:
        result = subprocess.run(command, cwd=cwd, capture_output=True, timeout=5)
        return result.stdout.decode(errors="replace").strip() if result.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def implementation_identity(package, options, environment):
    checkout = Path(__file__).resolve().parents[2]
    source = tree_hashes(package, python_only=True)
    rc_paths = [Path(environment.get("HOME") or Path.home()) / ".latexmkrc",
                Path(environment.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "latexmk/latexmkrc",
                Path(environment.get("LATEXMKRCSYS") or "/etc/LatexMk")]
    return dict(
        schema=SCHEMA, source=source, source_sha256=digest(source),
        benchmark_tools=tree_hashes(Path(__file__).parent, python_only=True),
        checkout_head=command_output(["git", "rev-parse", "HEAD"], checkout),
        checkout_dirty_patch_sha256=hashlib.sha256((command_output(
            ["git", "diff", "--binary", "HEAD", "--", "src", "tools/preview_benchmark"], checkout
        ) or "").encode()).hexdigest(),
        python=sys.version, executable=sys.executable, platform=platform.platform(),
        tools={tool: command_output([tool, "--version"]) for tool in ("latexmk", "lualatex", "biber")},
        search={name: value for name, value in environment.items()
                if name.startswith(("TEX", "LUA", "BIB", "FONTCONFIG", "LATEXMK", "MIKTEX"))
                or name in {"PATH", "SLIDEMAGE_LATEX", "SOURCE_DATE_EPOCH", "OSFONTDIR", "VARTEXFONTS"}},
        rc={str(path): hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
            for path in rc_paths},
        options=options, edit_version=EDIT_VERSION,
    )


def phases(repeats):
    return ["cold"] + [f"edit-{i}" for i in range(1, repeats + 1)] + ["unchanged"]


def validate_record(record, experiment_id, expected_phases):
    if record.get("experiment_id") != experiment_id:
        raise ValueError("Record implementation/options identity changed")
    samples = record.get("samples", [])
    if [sample.get("phase") for sample in samples] != expected_phases:
        raise ValueError("Record has missing, duplicated, or reordered phases")


def subset_indices(manifest):
    return manifest.get("selected_indices", list(range(1, len(manifest["calls"]) + 1)))


def observations():
    state = {"load_average": list(os.getloadavg()) if hasattr(os, "getloadavg") else None}
    frequency = Path("/sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq")
    try:
        state["cpu0_frequency_khz"] = frequency.read_text().strip()
    except OSError:
        state["cpu0_frequency_khz"] = None
    return state


def observed_rules(events, end):
    """Observe old and new backends through their common logging callback."""
    rules, active = [], None
    for timestamp, line in events:
        match = re.search(r"Run number (\d+) of rule '([^']+)'", line)
        if match:
            if active is not None:
                active["seconds"] = timestamp - active.pop("start")
            active = dict(rule=match[2], run=int(match[1]), start=timestamp)
            rules.append(active)
        elif "Latexmk: Getting log file" in line and active is not None:
            active["seconds"] = timestamp - active.pop("start")
            active = None
    if active is not None:
        active["seconds"] = end - active.pop("start")
    return rules
