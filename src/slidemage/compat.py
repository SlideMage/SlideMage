# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Project compatibility (v5.29.0): tell the user, when a project is opened,
what a newer SlideMage changed that may affect it -- and, where possible, fix it.

Every non-backwards-compatible change of SlideMage or its LaTeX framework gets
one :class:`Change` in :data:`CHANGES`, added in the same commit as the change
(tests/test_compat.py fails a "BREAKING:" release without one). A change has

- ``since``: the SlideMage version that introduced it; ``"NEXT"`` (change_fragments.NEXT) in a change that is
  not released yet, which packaging/make_release.py replaces with the release's version. Until then it counts as
  the running version, so a build from source applies it;
- ``severity``: BREAKS (a project may stop compiling), LAYOUT (a file layout
  changed) or APPEARANCE (it compiles, but looks different);
- ``detect(root)``: optional, a fast static scan of the project that returns
  the :class:`Finding` s (file, line, message). With a detector the change is
  pending only while it finds something; without one, until it is dealt with;
- ``migrate(root)``: optional, returns ``{file: new bytes}`` for the files to
  rewrite -- pure planning, :func:`run_update` backs every file up first
  (.slidemage/backups/<time>/compat/) and writes it atomically. A file to
  delete maps to ``None``, so a rename is the new name with the bytes plus the
  old name with ``None``. The update is all or nothing: if a file cannot be
  written, everything already written is put back. It must be idempotent.
  decks/#workdeck.tex is not exempt;
- ``fix``: how to fix it by hand (before/after), for the report;
- ``automatic``: SlideMage made the change itself when it opened the project (v0.14.1), so there is nothing to
  update or fix: ``detect`` finds it done, and the user gets a one-time notice that the project was updated and
  that older versions can no longer read it, instead of the dialog below.

State lives in the project's .slidemage/project.json, key "compat":
``checked_version`` (the version whose changes the user has dealt with; starts
at the version the project was last opened with, so a project is never told
about changes from before it was opened with this feature), ``dismissed``
(change ids the user said never to ask about again) and ``ignore_newer`` (a
"project was used by a newer SlideMage" notice already dismissed).

What the user sees: BREAKS/LAYOUT changes open a dialog on start (buttons
Update project / Show report / Not now / Don't ask again -- *Not now* leaves
everything as it is, so it comes back on the next open); APPEARANCE changes
only appear in Info -> Project compatibility and in the report. The report
(.slidemage/compat-report.md and .json) is written for people and AI tools.

Free of Qt. Command line::

    python -m slidemage.compat <project> [--json] [--fix]
"""
from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from . import change_fragments
from . import compat_multilingual, project
from .fileio import atomic_write
from .progress import Progress
from .tex_source import is_commented
from .updater import parse_version

from .compat_types import APPEARANCE, BREAKS, LAYOUT, Change, Finding  # noqa: F401  (re-exported)
SEVERITY_LABELS = {
    BREAKS: "may stop compiling",
    LAYOUT: "file layout changed",
    APPEARANCE: "looks different",
}
LOUD = (BREAKS, LAYOUT)  # these open the dialog; APPEARANCE stays quiet

REPORT_MD = Path(".slidemage") / "compat-report.md"
REPORT_JSON = Path(".slidemage") / "compat-report.json"
BACKUP_DIR = Path(".slidemage") / "backups"


def _decks(root: Path):
    for folder in (root / "decks", root / "decks" / "archive"):
        if folder.is_dir():
            yield from sorted(folder.glob("*.tex"))


def _detect_blocks_and_appendix_views(root: Path) -> list[Finding]:
    """v0.17.20: the decks that use topic blocks (\\slideblock) or name views in \\deckappendixtoc[...], which
    SlideMage v0.16 and older cannot compile."""
    findings = []
    for path in _decks(root):
        text = path.read_text(encoding="utf-8", errors="replace")
        for match in re.finditer(r"\\slideblock\s*\{|\\deckappendixtoc\s*\[", text):
            if not is_commented(text, match.start()):
                what = "a topic block" if "slideblock" in match.group() else "an appendix limited to some views"
                findings.append(Finding(path.relative_to(root).as_posix(), text.count("\n", 0, match.start()) + 1,
                                        f"Uses {what}: SlideMage v0.16 or older cannot compile this deck."))
    return findings


# Newest last. Every breaking change registers itself here. The entries before v0.17 were removed on
# 2026-11-20 (user: nothing older than v0.17 is migrated any more); entries with real work (detect/migrate)
# live in modules of their own.
CHANGES: list[Change] = [Change(
    id="topic-blocks-and-appendix-views",
    since="v0.17.20",
    severity=BREAKS,
    title="Decks with topic blocks or an appendix for some views need SlideMage v0.17",
    description=(
        "Topic blocks (\\slideblock, v0.17.0) and an appendix limited to some views (\\deckappendixtoc[instructor], "
        "v0.17.13) are not known to SlideMage v0.16 or older: a deck that uses them does not compile there. "
        "Nothing changes in this SlideMage."),
    fix="Nothing to change in the project. Update SlideMage on every computer that opens it.",
    detect=_detect_blocks_and_appendix_views,
    automatic=True,
), compat_multilingual.CHANGE]

# Releases from this one on need a registry entry for every "BREAKING:"
# paragraph of their version.py history (tests/test_compat.py).
REGISTRY_FROM = (0, 17, 0, 0)


@dataclass
class Pending:
    change: Change
    findings: list[Finding] = field(default_factory=list)


@dataclass
class Evaluation:
    loud: list[Pending] = field(default_factory=list)      # shown in the dialog
    quiet: list[Pending] = field(default_factory=list)     # appearance only
    applied: list[Pending] = field(default_factory=list)   # Change.automatic, done: a one-time notice
    newer_notice: str = ""     # "vX": the project was used by a newer SlideMage
    environment_notes: list[str] = field(default_factory=list)   # old environment variables still set

    @property
    def everything(self) -> list[Pending]:
        return self.loud + self.applied + self.quiet

    @property
    def readable_from(self) -> str:
        """The oldest SlideMage that still reads the project after the applied changes ("" for none)."""
        versions = [change_fragments.resolve(p.change.since) for p in self.applied]
        versions = [v for v in versions if _tuple(v) is not None]
        return max(versions, key=_tuple, default="")

    @property
    def can_update(self) -> bool:
        return any(p.change.migrate is not None for p in self.loud)


# -- state -------------------------------------------------------------------

def _state(root: Path) -> dict:
    compat = project.read_project_json(root).get("compat")
    return compat if isinstance(compat, dict) else {}


def _save_state(root: Path, compat: dict) -> None:
    data = project.read_project_json(root)
    data["compat"] = compat
    project.write_project_json(root, data)


def checked_version(root: Path) -> str:
    data = project.read_project_json(root)
    state = _state(root)
    return project.stored_version(data, state.get("checked_version")
                                  or project.read_project_info(root)["last_app_version"] or "")


def dismissed_ids(root: Path) -> set[str]:
    ids = _state(root).get("dismissed")
    return {i for i in ids if isinstance(i, str)} if isinstance(ids, list) else set()


def dismiss(root: Path, ids) -> None:
    """Never ask about these changes again (also takes them off the quiet list)."""
    state = _state(root)
    state["dismissed"] = sorted(dismissed_ids(root) | set(ids))
    _save_state(root, state)


def acknowledge(root: Path, app_version: str) -> None:
    """The user dealt with everything up to `app_version` (after an update)."""
    state = _state(root)
    state["checked_version"] = app_version
    _save_state(root, state)


def ignore_newer(root: Path, version: str) -> None:
    state = _state(root)
    state["ignore_newer"] = version
    _save_state(root, state)


# -- evaluating ---------------------------------------------------------------

def _tuple(version: str) -> Optional[tuple[int, ...]]:
    return parse_version(version or "")


def evaluate(root: Path, app_version: str, changes: Optional[list[Change]] = None) -> Evaluation:
    """What is pending for `root` when it is opened with `app_version`."""
    changes = CHANGES if changes is None else changes
    result = Evaluation(environment_notes=project.legacy_env_notes())
    base, current = _tuple(checked_version(root)), _tuple(app_version)
    skipped = dismissed_ids(root)
    for change in changes:
        since = _tuple(change_fragments.resolve(change.since, app_version))
        if change.id in skipped or since is None or current is None:
            continue
        if since > current or (base is not None and since <= base):
            continue
        findings: list[Finding] = []
        if change.detect is not None:
            findings = change.detect(root)
            if not findings:
                continue                       # nothing in this project is affected
        pending = Pending(change, findings)
        if change.automatic:
            result.applied.append(pending)
        else:
            (result.loud if change.severity in LOUD else result.quiet).append(pending)

    data = project.read_project_json(root)
    highest = project.stored_version(data, data.get("highest_app_version", ""))
    top, ignored = _tuple(highest), _tuple(project.stored_version(data, _state(root).get("ignore_newer", "")))
    if top is not None and current is not None and top > current and (ignored is None or top > ignored):
        result.newer_notice = highest
    return result


# -- the update -----------------------------------------------------------------

@dataclass
class UpdateResult:
    changed: list[str] = field(default_factory=list)
    backup: Optional[Path] = None
    errors: list[str] = field(default_factory=list)


def run_update(root: Path, pending: list[Pending], *, dry_run: bool = False, now: Optional[datetime] = None,
               on_progress: Optional[Callable[[Progress], None]] = None) -> UpdateResult:
    """Run the migrations of `pending`. Every file that changes is copied to
    .slidemage/backups/<time>/compat/ first; with dry_run nothing is written.
    `on_progress` gets one step per file backed up and one per file written.
    A deck snapshot (deck_snapshot.py) is never migrated: it stays as it was."""
    result = UpdateResult()
    if project.is_snapshot(root) and not dry_run:
        result.errors.append("This project is a deck snapshot; snapshots are never updated.")
        return result
    plan: dict[Path, Optional[bytes]] = {}
    for item in pending:
        if item.change.migrate is None:
            continue
        try:
            for path, data in item.change.migrate(root).items():
                plan[(root / path) if not Path(path).is_absolute() else Path(path)] = data
        except Exception as exc:  # noqa: BLE001 -- a broken migration must not stop the others
            result.errors.append(f"{item.change.id}: {exc}")
    stamp = (now or datetime.now()).strftime("%Y-%m-%d_%H%M%S")
    backup = root / BACKUP_DIR / stamp / "compat"
    todo: list[tuple[Path, str, Optional[bytes]]] = []
    for path, data in sorted(plan.items()):
        if (data is None and not path.is_file()) or (data is not None and path.is_file() and path.read_bytes() == data):
            continue
        todo.append((path, path.relative_to(root).as_posix(), data))
    result.changed = [rel for _path, rel, _data in todo]
    if dry_run or not todo:
        return result
    # Back everything up before the first change, so a failure leaves the project as it was.
    try:
        for n, (path, rel, _data) in enumerate(todo, 1):
            if on_progress:
                on_progress(Progress.step(n, len(todo), "Backing up"))
            if path.is_file():
                (backup / rel).parent.mkdir(parents=True, exist_ok=True)
                (backup / rel).write_bytes(path.read_bytes())
                result.backup = backup
    except OSError as exc:
        result.errors.append(f"backup failed, nothing was changed: {exc}")
        result.changed = []
        return result
    done: list[tuple[Path, Optional[bytes]]] = []        # (file, what it held before; None = it did not exist)
    try:
        writes_first = sorted(todo, key=lambda item: item[2] is None)    # removals last
        for n, (path, _rel, data) in enumerate(writes_first, 1):
            if on_progress:
                on_progress(Progress.step(n, len(todo), "Updating"))
            before = path.read_bytes() if path.is_file() else None
            if data is None:
                path.unlink()
            else:
                atomic_write(path, data)
            done.append((path, before))
    except OSError as exc:
        result.errors.append(f"{path.relative_to(root).as_posix()}: {exc}; the project was put back as it was")
        for undone, before in reversed(done):
            try:
                if before is None:
                    undone.unlink(missing_ok=True)
                else:
                    atomic_write(undone, before)
            except OSError as undo_exc:
                result.errors.append(f"{undone.relative_to(root).as_posix()}: could not be put back: {undo_exc}")
        result.changed = []
    return result


# -- the report ------------------------------------------------------------------

AI_PROMPT = (
    "This is a SlideMage project (LaTeX/beamer slides). A newer SlideMage changed "
    "things that may affect it; the findings below say where. For each finding, "
    "apply the fix described under its change, edit only the listed files, keep "
    "line endings, and tell me what you changed. Do not touch anything else.")


def report_markdown(root: Path, evaluation: Evaluation, app_version: str) -> str:
    lines = ["# Project compatibility report", "",
             f"Project: `{root}`  ", f"SlideMage: {app_version}  ",
             f"Written: {datetime.now():%Y-%m-%d %H:%M}", ""]
    if evaluation.newer_notice:
        lines += [f"> This project was last used with SlideMage {evaluation.newer_notice}, "
                  f"which is newer than {app_version}; features of that version may not work here.", ""]
    if evaluation.environment_notes:
        lines += ["## Environment variables", "", *[f"- {note}" for note in evaluation.environment_notes], ""]
    if not evaluation.everything:
        lines += ["Nothing to report.", ""]
    else:
        lines += ["## For an AI tool", "", AI_PROMPT, ""]
    for item in evaluation.everything:
        c = item.change
        lines += [f"## {c.title}", "",
                  f"- id: `{c.id}`, since {c.since}, {SEVERITY_LABELS.get(c.severity, c.severity)}",
                  "- automatic update: " + ("done by SlideMage when it opened the project" if c.automatic
                                            else "yes (Update project)" if c.migrate else "no, fix by hand"),
                  "", c.description, ""]
        if c.fix:
            lines += ["**Fix**", "", c.fix, ""]
        if item.findings:
            lines += ["**Where**", ""]
            lines += [f"- `{f.file}{':' + str(f.line) if f.line else ''}`: {f.message}" for f in item.findings]
            lines.append("")
    return "\n".join(lines)


def report_data(evaluation: Evaluation, app_version: str) -> dict:
    return {
        "app_version": app_version,
        "newer_notice": evaluation.newer_notice,
        "environment_notes": evaluation.environment_notes,
        "changes": [{
            "id": p.change.id, "since": p.change.since, "severity": p.change.severity,
            "title": p.change.title, "description": p.change.description, "fix": p.change.fix,
            "automatic_update": p.change.migrate is not None,
            "applied_by_slidemage": p.change.automatic,
            "findings": [{"file": f.file, "line": f.line, "message": f.message} for f in p.findings],
        } for p in evaluation.everything],
    }


def write_report(root: Path, evaluation: Evaluation, app_version: str) -> Path:
    """Write .slidemage/compat-report.md and .json; returns the .md path."""
    md = root / REPORT_MD
    md.parent.mkdir(parents=True, exist_ok=True)
    md.write_text(report_markdown(root, evaluation, app_version), encoding="utf-8", newline="\n")
    data = json.dumps(report_data(evaluation, app_version), indent=2) + "\n"
    (root / REPORT_JSON).write_text(data, encoding="utf-8", newline="\n")
    return md


# -- command line -----------------------------------------------------------------

def main(argv: Optional[list[str]] = None) -> int:
    import argparse

    from .version import VERSION_NUMBER

    parser = argparse.ArgumentParser(prog="slidemage.compat", description=__doc__.split("\n\n")[0])
    parser.add_argument("project", type=Path)
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    parser.add_argument("--fix", action="store_true", help="run the automatic updates (with backups)")
    args = parser.parse_args(argv)
    root = args.project.resolve()
    if not project.is_project(root):
        print(f"{root} has no {project.MARKER}.", file=sys.stderr)
        return 2
    evaluation = evaluate(root, VERSION_NUMBER)
    if args.fix and evaluation.can_update:
        done = run_update(root, evaluation.loud)
        print(f"updated {len(done.changed)} file(s)" + (f", backup {done.backup}" if done.backup else ""))
        for error in done.errors:
            print("error:", error, file=sys.stderr)
        evaluation = evaluate(root, VERSION_NUMBER)
    if evaluation.everything or evaluation.environment_notes:      # files only when there is something to hand on
        write_report(root, evaluation, VERSION_NUMBER)
    if args.json:
        print(json.dumps(report_data(evaluation, VERSION_NUMBER), indent=2))
    else:
        print(report_markdown(root, evaluation, VERSION_NUMBER))
    return 1 if evaluation.loud else 0



if __name__ == "__main__":
    sys.exit(main())
