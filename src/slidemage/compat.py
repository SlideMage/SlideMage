"""Project compatibility (v5.29.0): tell the user, when a project is opened,
what a newer SlideMage changed that may affect it -- and, where possible, fix it.

Every non-backwards-compatible change of SlideMage or its LaTeX framework gets
one :class:`Change` in :data:`CHANGES`, added in the same commit as the change
(tests/test_compat.py fails a "BREAKING:" release without one). A change has

- ``since``: the SlideMage version that introduced it;
- ``severity``: BREAKS (a project may stop compiling), LAYOUT (a file layout
  changed) or APPEARANCE (it compiles, but looks different);
- ``detect(root)``: optional, a fast static scan of the project that returns
  the :class:`Finding` s (file, line, message). With a detector the change is
  pending only while it finds something; without one, until it is dealt with;
- ``migrate(root)``: optional, returns ``{file: new bytes}`` for the files to
  rewrite -- pure planning, :func:`run_update` backs every file up first
  (.slidemage/backups/<time>/compat/) and writes it atomically. It must be
  idempotent. decks/#workdeck.tex is not exempt;
- ``fix``: how to fix it by hand (before/after), for the report.

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
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from . import compat_bibliography, project
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


def _detect_omitslide(root: Path) -> list[Finding]:
    findings = []
    for path in compat_bibliography._decks(root):
        text = path.read_text(encoding="utf-8", errors="replace")
        for match in re.finditer(r"\\omitslide(?:version)?\s*\{", text):
            if not is_commented(text, match.start()):
                findings.append(Finding(path.relative_to(root).as_posix(),
                                        text.count("\n", 0, match.start()) + 1,
                                        "Instructor-only slide is skipped in student deck versions."))
    return findings


# Newest last. Entries start with v5.29.0's rule that every breaking change
# registers itself here (the changes before that were announced in
# version.py's BREAKING paragraphs and are not retrofitted). Entries with real
# work (detect/migrate) live in modules of their own, e.g. compat_bibliography.
CHANGES: list[Change] = [compat_bibliography.CHANGE, Change(
    id="workspace-redesign",
    since="v6.0.0",
    severity=APPEARANCE,
    title="SlideMage's window was rebuilt as one workspace per deck",
    description=(
        "Version 6.0 replaced the window of tabs, the deck table and the deck editor by a "
        "workspace (slide list, Preview / Source / Split / Details, side panels, an AI "
        "assistant, a command palette). Projects, decks, slides and settings files are "
        "unchanged and compile as before; what changed is how you work with them."),
    fix=(
        "Nothing to do in the project. Compile the other versions from the arrow of Compile PDF "
        "(they were the deck table's checkboxes), and use the chat instead of AI drafting."),
), Change(
    id="language-switch-translations",
    since="v7.0.0",
    severity=APPEARANCE,
    title="EN / DE follows linked translations",
    description=(
        "The language switch now selects the linked slide file for editing, previewing and "
        "compiling the open deck. Linked EN / DE calls are one logical slot, including old "
        "decks that list both. The original call keeps visibility and reveal steps; a "
        "translation uses its own current version, independently of an English pin."),
    fix=(
        "No project migration is needed. Select EN or DE to edit that language's slide; "
        "missing partners fall back to the called file. To include both languages as "
        "separate slides, use independent copies without translation links. Raw LaTeX "
        "compiles outside SlideMage keep the literal deck calls."),
), Change(
    id="omitslide-instructor-only",
    since="v8.0.0",
    severity=APPEARANCE,
    title="Omitted slides are instructor-only",
    description=(
        "\\omitslide and \\omitslideversion now skip slides in during-course and after-course "
        "decks, keeping frame numbers aligned. Instructor and presenter compiles, and decks "
        "without \\deckversion, still include them unless \\studentversion is set."),
    fix=(
        "Use \\slide or \\slideversion for slides students should receive; keep omission "
        "calls for instructor-only content."),
    detect=_detect_omitslide,
)]

# Releases from this one on need a registry entry for every "BREAKING:"
# paragraph of their version.py history (tests/test_compat.py).
REGISTRY_FROM = (5, 29, 0)


@dataclass
class Pending:
    change: Change
    findings: list[Finding] = field(default_factory=list)


@dataclass
class Evaluation:
    loud: list[Pending] = field(default_factory=list)      # shown in the dialog
    quiet: list[Pending] = field(default_factory=list)     # appearance only
    newer_notice: str = ""     # "vX": the project was used by a newer SlideMage

    @property
    def everything(self) -> list[Pending]:
        return self.loud + self.quiet

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
    state = _state(root)
    return (state.get("checked_version")
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
    result = Evaluation()
    base, current = _tuple(checked_version(root)), _tuple(app_version)
    skipped = dismissed_ids(root)
    for change in changes:
        since = _tuple(change.since)
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
        (result.loud if change.severity in LOUD else result.quiet).append(pending)

    highest = project.read_project_json(root).get("highest_app_version", "")
    top, ignored = _tuple(highest), _tuple(_state(root).get("ignore_newer", ""))
    if top is not None and current is not None and top > current and (ignored is None or top > ignored):
        result.newer_notice = highest
    return result


# -- the update -----------------------------------------------------------------

@dataclass
class UpdateResult:
    changed: list[str] = field(default_factory=list)
    backup: Optional[Path] = None
    errors: list[str] = field(default_factory=list)


def _atomic_write(path: Path, data: bytes) -> None:
    tmp = path.with_name(path.name + ".slidemage-tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def run_update(root: Path, pending: list[Pending], *, dry_run: bool = False,
               now: Optional[datetime] = None) -> UpdateResult:
    """Run the migrations of `pending`. Every file that changes is copied to
    .slidemage/backups/<time>/compat/ first; with dry_run nothing is written.
    A deck snapshot (deck_snapshot.py) is never migrated: it stays as it was."""
    result = UpdateResult()
    if project.is_snapshot(root) and not dry_run:
        result.errors.append("This project is a deck snapshot; snapshots are never updated.")
        return result
    plan: dict[Path, bytes] = {}
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
    for path, data in sorted(plan.items()):
        rel = path.relative_to(root).as_posix()
        if path.is_file() and path.read_bytes() == data:
            continue
        result.changed.append(rel)
        if dry_run:
            continue
        try:
            if path.is_file():
                (backup / rel).parent.mkdir(parents=True, exist_ok=True)
                (backup / rel).write_bytes(path.read_bytes())
                result.backup = backup
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
            _atomic_write(path, data)
        except OSError as exc:
            result.errors.append(f"{rel}: {exc}")
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
    if not evaluation.everything:
        lines += ["Nothing to report.", ""]
    else:
        lines += ["## For an AI tool", "", AI_PROMPT, ""]
    for item in evaluation.everything:
        c = item.change
        lines += [f"## {c.title}", "",
                  f"- id: `{c.id}`, since {c.since}, {SEVERITY_LABELS.get(c.severity, c.severity)}",
                  f"- automatic update: {'yes (Update project)' if c.migrate else 'no, fix by hand'}",
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
        "changes": [{
            "id": p.change.id, "since": p.change.since, "severity": p.change.severity,
            "title": p.change.title, "description": p.change.description, "fix": p.change.fix,
            "automatic_update": p.change.migrate is not None,
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
    if evaluation.everything:      # files only when there is something to hand on
        write_report(root, evaluation, VERSION_NUMBER)
    if args.json:
        print(json.dumps(report_data(evaluation, VERSION_NUMBER), indent=2))
    else:
        print(report_markdown(root, evaluation, VERSION_NUMBER))
    return 1 if evaluation.loud else 0



if __name__ == "__main__":
    sys.exit(main())
