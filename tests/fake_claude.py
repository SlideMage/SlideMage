"""A stand-in for the `claude` program, for the tests of the Claude Code view: a script that logs what it
was started with (argv, cwd, selected environment) to $FAKE_CLAUDE_LOG, prints a banner, echoes what is typed
(raw terminal) and ends at "/exit". With `-p` it is a one-shot task: it logs the call and the request it read
from stdin (one JSON line per call; with `--input-format stream-json` the text of the user message as "request"
and its image blocks as "images", each the block's source), then answers with stream-json events as
$FAKE_CLAUDE_REPLIES says, a JSON list with one entry per call (the last one repeats): {"answer": {...}} is the structured result, {"error":
"text"} an error result, {"exit": code} no result at all; "delay" waits that many seconds before the result, and
"marker" is a file touched after the delay (a process that was killed never gets there). It never talks to a
model or the network."""
from __future__ import annotations

import stat
import sys
from pathlib import Path

SCRIPT = '''#!{python}
import json, os, sys, tty
log = os.environ.get("FAKE_CLAUDE_LOG")
if "-p" in sys.argv:
    import time
    request, images = sys.stdin.read(), []
    if "--input-format" in sys.argv:
        content = json.loads(request.splitlines()[0])["message"]["content"]
        images = [block["source"] for block in content if block["type"] == "image"]
        request = "".join(block["text"] for block in content if block["type"] == "text")
    calls = len(open(log).readlines()) if os.path.exists(log) else 0
    with open(log, "a") as f:
        f.write(json.dumps({{"argv": sys.argv[1:], "cwd": os.getcwd(), "request": request, "images": images,
                            "env": sorted(os.environ)}}) + "\\n")
    replies = json.loads(os.environ["FAKE_CLAUDE_REPLIES"])
    reply = replies[min(calls, len(replies) - 1)]
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
