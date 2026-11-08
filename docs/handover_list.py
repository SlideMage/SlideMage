"""Build the "pick the next tasks" page from the task block in handover.md.

Usage:  python docs/handover_list.py OUT.html [--all] [--handover PATH]

Reads the JSON lines between <!-- TASKS:BEGIN --> and <!-- TASKS:END --> in handover.md (same folder, or PATH: the file
is not in git, so a worktree does not have it), keeps the tasks
whose status is "open" (all with --all), and writes OUT.html from handover_list.template.html. Publish OUT.html with the
Artifact tool; the page republishes itself with the user's picks and notes when they click "Start tasks".
Prints the number of tasks and the ids, one line. Standard library only.
"""
import json
import pathlib
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
    tasks = read_tasks(handover.read_text(encoding="utf-8"))
    if "--all" not in argv:
        tasks = [t for t in tasks if t["status"] == "open"]
    state = {"tasks": tasks, "sel": {}, "notes": {}, "sent": None}
    blob = json.dumps(state, ensure_ascii=False).replace("</", "<\\/")
    html = (HERE / "handover_list.template.html").read_text(encoding="utf-8").replace("__STATE__", blob)
    pathlib.Path(args[0]).write_text(html, encoding="utf-8")
    print(len(tasks), "tasks:", " ".join(t["id"] for t in tasks))


if __name__ == "__main__":
    main(sys.argv[1:])
