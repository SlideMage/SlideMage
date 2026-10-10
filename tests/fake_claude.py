"""A stand-in for the `claude` program, for the tests of the Claude Code view: a script that logs what it
was started with (argv, cwd, selected environment) to $FAKE_CLAUDE_LOG, prints a banner, echoes what is typed
(raw terminal) and ends at "/exit". It never talks to a model or the network."""
from __future__ import annotations

import stat
import sys
from pathlib import Path

SCRIPT = '''#!{python}
import json, os, sys, tty
log = os.environ.get("FAKE_CLAUDE_LOG")
if log:
    with open(log, "w") as f:
        json.dump({{"argv": sys.argv[1:], "cwd": os.getcwd(), "token": os.environ.get("SLIDEMAGE_MCP_TOKEN"),
                   "term": os.environ.get("TERM"), "project": os.environ.get("SLIDEMASTER_PROJECT")}}, f)
sys.stdout.write("Fake Claude Code\\r\\n> ")
sys.stdout.flush()
tty.setraw(0)
typed = ""
while True:
    data = os.read(0, 1024).decode("utf-8", "replace")
    if not data:
        break
    for ch in data:
        if ch in "\\r\\n":
            if typed.strip() == "/exit":
                sys.stdout.write("\\r\\nbye\\r\\n"); sys.stdout.flush(); sys.exit(3)
            sys.stdout.write("\\r\\necho: " + typed + "\\r\\n> "); typed = ""
        else:
            typed += ch; sys.stdout.write(ch)
    sys.stdout.flush()
'''


def make_fake_claude(folder: Path) -> Path:
    path = folder / "claude"
    path.write_text(SCRIPT.format(python=sys.executable))
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path
