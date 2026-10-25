# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""A stand-in for the `claude` program, for the tests of the Claude Code view: a script that logs what it
was started with (argv, cwd, selected environment) to $FAKE_CLAUDE_LOG, prints a banner, echoes what is typed
(raw terminal) and ends at "/exit". With `-p` it is a one-shot task: it logs the call and the request it read
from stdin (one JSON line per call; with `--input-format stream-json` the text of the user message as "request"
and its image blocks as "images", each the block's source), then answers with stream-json events as
$FAKE_CLAUDE_REPLIES says, a JSON list with one entry per call (the last one repeats): {"answer": {...}} is the structured result, {"error":
"text"} an error result, {"exit": code} no result at all; "delay" waits that many seconds before the result, and
"marker" is a file touched after the delay (a process that was killed never gets there); "when" makes it the
reply to the first request that contains that text (processes started together cannot count their calls). Each
call logs its start "time". It never talks to a model or the network."""
from __future__ import annotations

import io
import stat
import sys
import zipfile
from pathlib import Path

SCRIPT = '''#!{python}
import json, os, sys
log = os.environ.get("FAKE_CLAUDE_LOG")
if "-p" in sys.argv:
    import time
    request, images = sys.stdin.read(), []
    if "--input-format" in sys.argv:
        content = json.loads(request.splitlines()[0])["message"]["content"]
        images = [block["source"] for block in content if block["type"] == "image"]
        request = "".join(block["text"] for block in content if block["type"] == "text")
    earlier = [json.loads(line).get("request", "") for line in open(log)] if os.path.exists(log) else []
    calls = len(earlier)
    with open(log, "a") as f:
        f.write(json.dumps({{"argv": sys.argv[1:], "cwd": os.getcwd(), "request": request, "images": images,
                            "env": sorted(os.environ), "time": time.time()}}) + "\\n")
    replies = json.loads(os.environ["FAKE_CLAUDE_REPLIES"])
    reply = next((r for r in replies if r.get("when") and r["when"] in request
                  and not any(r["when"] in e for e in earlier)), None) or replies[min(calls, len(replies) - 1)]
    def emit(event):
        sys.stdout.write(json.dumps(event) + "\\n"); sys.stdout.flush()
    emit({{"type": "system", "subtype": "init"}})
    if "exit" in reply:
        print("boom", file=sys.stderr); sys.exit(reply["exit"])
    emit({{"type": "assistant", "message": {{}}}})
    time.sleep(reply.get("delay", 0))
    if reply.get("marker"):
        open(reply["marker"], "w").close()
    usage = {{"input_tokens": 3, "cache_read_input_tokens": 100, "output_tokens": 7}}
    emit({{"type": "result", "subtype": "success", "is_error": "error" in reply, "num_turns": 2, "usage": usage,
          "result": reply.get("error", ""), "structured_output": reply.get("answer")}})
    sys.exit(0)
if log:
    with open(log, "w") as f:
        json.dump({{"argv": sys.argv[1:], "cwd": os.getcwd(), "token": os.environ.get("SLIDEMAGE_MCP_TOKEN"),
                   "term": os.environ.get("TERM"), "project": os.environ.get("SLIDEMAGE_PROJECT")}}, f)
sys.stdout.write("Fake Claude Code\\r\\n> ")
sys.stdout.flush()
import tty
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
    script = SCRIPT.format(python=sys.executable)
    if sys.platform == "win32":
        return _windows_exe(folder / "claude.exe", script)
    path = folder / "claude"
    path.write_text(script)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def _windows_exe(path: Path, script: str) -> Path:
    """Windows runs no shebang script, so the fake is a claude.exe the way pip makes a console script: the
    distlib launcher, then the line naming the Python to run, then a zip holding the script as __main__.py.
    The launcher hands the arguments over unchanged (a .cmd wrapper would let cmd.exe reinterpret the JSON
    and prompt text the runner passes). Only the one-shot (-p) part works there: the interactive part needs
    a POSIX terminal, and the tests of it are POSIX-only."""
    try:
        from pip._vendor import distlib
    except ImportError:
        import pytest
        pytest.skip("the fake claude.exe needs pip's script launcher (pip._vendor.distlib)")
    launcher = (Path(distlib.__file__).parent / "t64.exe").read_bytes()
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr("__main__.py", script)
    path.write_bytes(launcher + f'#!"{sys.executable}"\r\n'.encode() + archive.getvalue())
    return path
