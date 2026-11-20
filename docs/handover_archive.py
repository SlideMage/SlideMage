"""Move what is done out of handover.md into handover-archive.md.

Usage:  python docs/handover_archive.py [--dry-run] [--handover PATH]

handover.md is not in git, so a worktree does not have it: without --handover the script uses the one next to it, else
the main checkout's. The archive is the file handover-archive.md beside the handover. /finish runs this after updating the
handover, and handover_list.py (the /handover picker) runs it first, so finished work does not pile up in handover.md.

What moves (nothing is edited, only moved):
* every TASKS line with "status": "done" (or "archived") goes to the end of the archive, under "# Archived task lines" (ids are never
  reused, so the lines stay findable there);
* every section (a "# Title" heading between two "---" rules) whose Status line starts "done", "finished", "answered"
  or "task deleted", unless a task naming it in its "src" (by its title, or "§N" for the N-th item of the numbered
  contents list) is open or blocked. A section whose Status still says open stays even if its tasks are done.
  "# Cleanup" never moves. The contents item of a moved section gets "[archived: see handover-archive.md]".

Prints what it moved. Standard library only.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TASKS_BEGIN, TASKS_END = "<!-- TASKS:BEGIN -->", "<!-- TASKS:END -->"
NEVER = {"Cleanup"}
FINISHED_STATUSES = ("done", "archived")      # "archived": the picker page's Archive button
ARCHIVED_NOTE = "[archived: see handover-archive.md]"
TASK_LINES_TITLE = "# Archived task lines"
_HEADING = re.compile(r"^---[ \t]*\r?\n\r?\n# (.+?)[ \t]*\r?$", re.MULTILINE)
_FINISHED = re.compile(r"Status:\s*\*\*(done|finished|answered|task deleted)", re.IGNORECASE)


def default_handover() -> Path:
    """handover.md next to this file, else the main checkout's (this file in .claude/worktrees/<name>/docs/)."""
    for folder in (HERE, *(p / "docs" for p in HERE.parents[:4])):
        if (folder / "handover.md").is_file():
            return folder / "handover.md"
    return HERE / "handover.md"


def _eol(text: str) -> str:
    return "\r\n" if "\r\n" in text else "\n"


def split_sections(text: str) -> list[tuple[str, int, int]]:
    """(title, start, end) of each section: start is its leading "---" rule, end the next section's start."""
    found = list(_HEADING.finditer(text))
    return [(m.group(1), m.start(), found[i + 1].start() if i + 1 < len(found) else len(text))
            for i, m in enumerate(found)]


def contents_items(text: str) -> dict[int, str]:
    """The numbered contents list ("1. Title (note)") as {number: line text}, above the first section."""
    first = _HEADING.search(text)
    head = text[:first.start()] if first else text
    return {int(m.group(1)): m.group(2) for m in re.finditer(r"^(\d{1,3})\. (.+?)\r?$", head, re.MULTILINE)}


def task_lines(text: str) -> list[tuple[str, dict]]:
    """[(line, task)] for the JSON lines between the TASKS markers."""
    block = text[text.index(TASKS_BEGIN) + len(TASKS_BEGIN):text.index(TASKS_END)]
    found = []
    for line in block.splitlines():
        if line.startswith("{"):
            try:
                found.append((line, json.loads(line)))
            except ValueError:
                pass
    return found


def _title_of_item(item: str) -> str:
    return re.sub(r"\s*\([^()]*\)\s*(\[archived:[^\]]*\])?\s*$", "", item.replace("**", "")).strip()


def _same(title: str, item: str) -> bool:
    wanted = _title_of_item(item)
    return bool(wanted) and (title == wanted or title.startswith(wanted) or wanted.startswith(title))


def plan(text: str) -> tuple[list[str], list[str], list[str]]:
    """(task lines to move, titles of the sections to move, titles held back by an open task)."""
    tasks = task_lines(text)
    items = contents_items(text)
    sections = split_sections(text)
    statuses: dict[str, list[str]] = {}
    for _, task in tasks:
        src = str(task.get("src", "")).strip()
        number = re.match(r"^\W*(\d{1,3})\b", src) if src[:1] in ("\u00a7",) else None
        for title, _, _ in sections:
            if (number and int(number.group(1)) in items and _same(title, items[int(number.group(1))])) or title == src:
                statuses.setdefault(title, []).append(task.get("status", ""))
    move, held = [], []
    for title, start, end in sections:
        if title in NEVER:
            continue
        found = statuses.get(title, [])
        if any(s not in FINISHED_STATUSES for s in found):
            held.append(title)
        elif _FINISHED.search(text[start:end][:1500]):
            move.append(title)
    return [line for line, task in tasks if task.get("status") in FINISHED_STATUSES], move, held


def archive(handover: Path, dry_run: bool = False) -> str:
    archive_path = handover.with_name("handover-archive.md")
    text = handover.read_bytes().decode("utf-8")
    eol = _eol(text)
    move_tasks, move_titles, _held = plan(text)
    if not move_tasks and not move_titles:
        return "nothing to archive"
    spans = {title: (start, end) for title, start, end in split_sections(text)}
    chunks = [text[spans[t][0]:spans[t][1]] for t in move_titles]
    for title in sorted(move_titles, key=lambda t: -spans[t][0]):       # from the end: offsets stay valid
        text = text[:spans[title][0]] + text[spans[title][1]:]
    for line in move_tasks:
        text = text.replace(line + eol, "", 1) if (line + eol) in text else text.replace(line, "", 1)
    for number, item in contents_items(text).items():
        if ARCHIVED_NOTE not in item and any(_same(t, item) for t in move_titles):
            text = re.sub(r"^(" + str(number) + r"\. .+?)(\r?)$", lambda m: f"{m.group(1)} {ARCHIVED_NOTE}{m.group(2)}",
                          text, count=1, flags=re.MULTILINE)
    archived = archive_path.read_bytes().decode("utf-8")
    aeol = _eol(archived)
    if not archived.endswith(aeol):
        archived += aeol
    for chunk in chunks:
        archived += aeol + chunk.replace(eol, aeol).rstrip() + aeol
    if move_tasks:
        fence = "```" + aeol
        if TASK_LINES_TITLE not in archived:
            archived += (aeol + "---" + aeol + aeol + TASK_LINES_TITLE + aeol + aeol + "TASKS lines of finished tasks, moved "
                         "out of `handover.md` by `docs/handover_archive.py`." + aeol + aeol + fence + fence)
        # Before the closing fence of the task-lines block, which already holds the lines of earlier runs and may be
        # followed by sections archived since.
        opening = archived.index(fence, archived.index(TASK_LINES_TITLE)) + len(fence)
        at = archived.index(fence, opening)
        archived = archived[:at] + aeol.join(move_tasks) + aeol + archived[at:]
    summary = f"{len(move_tasks)} task lines, {len(move_titles)} sections" + "".join(f"\n  - {t}" for t in move_titles)
    if not dry_run:
        handover.write_bytes(text.encode("utf-8"))
        archive_path.write_bytes(archived.encode("utf-8"))
    return ("would move " if dry_run else "moved ") + summary


def main(argv: list[str]) -> None:
    argv = list(argv)
    handover = default_handover()
    if "--handover" in argv:
        i = argv.index("--handover")
        handover = Path(argv[i + 1])
        del argv[i:i + 2]
    print(archive(handover, dry_run="--dry-run" in argv))


if __name__ == "__main__":
    main(sys.argv[1:])
