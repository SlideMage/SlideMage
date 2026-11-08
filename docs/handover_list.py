"""Build the "pick the next tasks" page from the task block in handover.md.

Usage:  python docs/handover_list.py OUT.html [--all] [--handover PATH]

Reads the JSON lines between <!-- TASKS:BEGIN --> and <!-- TASKS:END --> in handover.md (same folder, or PATH: the file
is not in git, so a worktree does not have it), keeps the tasks
whose status is "open" (all with --all), and writes OUT.html from handover_list.template.html. Publish OUT.html with the
Artifact tool; the page republishes itself with the user's picks and notes when they click "Start tasks".
Each task's "Details" text is whatever stands between `<!-- task:ID -->` and `<!-- /task:ID -->` lines in handover.md; a
task's optional "notes" field preloads its text field. A task's optional "run" ({"mode": "session"|"agent"|"", "model", "effort"}) preselects the page's Subsession/Subagent boxes and
model and effort lists as a recommendation (defaults: no mode, sonnet, medium). A task with `"needs_items": true` is left out unless its marked text has a
bullet item (a line starting with "* " or "- "), so an empty standing section does not clutter the page. Prints the number of tasks and the ids, one line (and the ids that
have no details). Standard library only.
"""
import json
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
BEGIN, END = "<!-- TASKS:BEGIN -->", "<!-- TASKS:END -->"


def read_tasks(text):
    if BEGIN not in text or END not in text:
        raise SystemExit("handover.md has no TASKS block")
    block = text.split(BEGIN, 1)[1].split(END, 1)[0]
    tasks, seen = [], set()
    for n, line in enumerate(block.splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            t = json.loads(line)
        except ValueError as e:
            raise SystemExit(f"TASKS block, line {n}: not valid JSON ({e})")
        for key in ("id", "status", "grp", "title", "desc", "src"):
            if key not in t:
                raise SystemExit(f"TASKS block, line {n}: missing '{key}'")
        if t["id"] in seen:
            raise SystemExit(f"TASKS block: duplicate id {t['id']}")
        seen.add(t["id"])
        tasks.append(t)
    return tasks


def read_details(text):
    """Text between <!-- task:ID --> and <!-- /task:ID --> lines, by id."""
    out = {}
    for m in re.finditer(r"^<!-- task:([a-z0-9-]+) -->[ \t]*\r?\n(.*?)^<!-- /task:\1 -->", text, re.S | re.M):
        if m.group(1) in out:
            raise SystemExit(f"handover.md: task markers for {m.group(1)} appear twice")
        out[m.group(1)] = m.group(2).strip()
    return out


def main(argv):
    argv = list(argv)
    handover = HERE / "handover.md"
    if "--handover" in argv:
        i = argv.index("--handover")
        handover = pathlib.Path(argv[i + 1])
        del argv[i:i + 2]
    args = [a for a in argv if not a.startswith("--")]
    if len(args) != 1:
        raise SystemExit(__doc__)
    text = handover.read_text(encoding="utf-8")
    tasks = read_tasks(text)
    if "--all" not in argv:
        tasks = [t for t in tasks if t["status"] == "open"]
    details = read_details(text)
    missing = []
    for t in tasks:
        t["detail"] = details.get(t["id"], "")
        if not t["detail"]:
            missing.append(t["id"])
    tasks = [t for t in tasks if not t.get("needs_items") or re.search(r"^[*-] ", details.get(t["id"], ""), re.M)]
    missing = [i for i in missing if any(t["id"] == i for t in tasks)]
    notes = {t["id"]: t["notes"] for t in tasks if t.get("notes")}
    run = {}
    for t in tasks:
        r = t.get("run") or {}
        run[t["id"]] = {"mode": r.get("mode", ""), "model": r.get("model", "sonnet"), "effort": r.get("effort", "medium")}
    state = {"tasks": tasks, "sel": {}, "notes": dict(notes), "savedNotes": dict(notes), "run": run, "sent": None, "updated": None}
    blob = json.dumps(state, ensure_ascii=False).replace("</", "<\\/")
    html = (HERE / "handover_list.template.html").read_text(encoding="utf-8").replace("__STATE__", blob)
    pathlib.Path(args[0]).write_text(html, encoding="utf-8")
    print(len(tasks), "tasks:", " ".join(t["id"] for t in tasks))
    if missing:
        print("no details (add task markers):", " ".join(missing))


if __name__ == "__main__":
    main(sys.argv[1:])
