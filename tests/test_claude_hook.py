"""The PreToolUse hook of the embedded Claude Code (ai/claude_hook.py) with hook JSON as Claude Code sends it:
protected parts and frozen versions are blocked (exit code 2, the reason on stderr), everything else is
allowed, and so is anything the hook cannot work out."""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys

import pytest
from conftest import SLIDE_TEXT, make_project

from slidemage.ai import claude_hook
from slidemage.ai.tools.edits import PROTECTED_MESSAGE

CURRENT = "abc-EN-Hello-current.tex"
FROZEN = "abc-EN-Hello-v1-0-0.tex"


@pytest.fixture
def root(tmp_path, monkeypatch):
    return make_project(monkeypatch, tmp_path / "project")


def event(root, tool, name=CURRENT, **tool_input):
    path = str(root / "slides" / name)
    return {"session_id": "s", "cwd": str(root), "hook_event_name": "PreToolUse", "tool_name": tool,
            "tool_input": {"file_path": path, **tool_input}}


def edit(root, old, new, name=CURRENT, **more):
    return event(root, "Edit", name, old_string=old, new_string=new, **more)


def test_an_edit_of_the_body_is_allowed(root):
    assert claude_hook.blocked_reason(edit(root, "First point", "1st point")) is None
    assert claude_hook.blocked_reason(edit(root, "\\item First point", "\\item First\n\t\t\\item inserted")) is None


@pytest.mark.parametrize("old, new", [
    ("%% Included in decks: test", "%% Included in decks: test, other"),         # the header comment
    ("\\setSlideVersion{1-0-0}", "\\setSlideVersion{2-0-0}"),
    ("\\hbox{overlay}", "\\hbox{changed}"),                                       # inside \vbox to 0pt{...}
    ("\\setSlideVersion{1-0-0}\r\n", ""),                                         # deleting a protected line
])
def test_an_edit_of_a_protected_part_is_blocked(root, old, new):
    assert claude_hook.blocked_reason(edit(root, old, new)) == PROTECTED_MESSAGE


def test_crlf_in_the_file_or_the_tool_input_makes_no_difference(root):
    assert SLIDE_TEXT.count("\r\n") > 3
    assert claude_hook.blocked_reason(edit(root, "First point\r\n\t\t\\item Second point", "x")) is None
    assert claude_hook.blocked_reason(edit(root, "\\setSlideVersion{1-0-0}\r\n\\begin", "\\begin")) == PROTECTED_MESSAGE


def test_replace_all_counts_every_occurrence(root):
    assert claude_hook.blocked_reason(edit(root, "point", "idea", replace_all=True)) is None
    assert claude_hook.blocked_reason(edit(root, "1-0-0", "2-0-0", replace_all=True)) == PROTECTED_MESSAGE


def test_write_compares_the_whole_new_text(root):
    keep = SLIDE_TEXT.replace("First point", "1st")
    assert claude_hook.blocked_reason(event(root, "Write", content=keep)) is None
    assert claude_hook.blocked_reason(event(root, "Write", content="\\begin{standardframe}{x}\\end{standardframe}")) \
        == PROTECTED_MESSAGE


def test_multiedit_applies_the_edits_in_order(root):
    fine = [{"old_string": "First", "new_string": "1st"}, {"old_string": "Second", "new_string": "2nd"}]
    assert claude_hook.blocked_reason(event(root, "MultiEdit", edits=fine)) is None
    bad = [*fine, {"old_string": "overlay", "new_string": "gone"}]
    assert claude_hook.blocked_reason(event(root, "MultiEdit", edits=bad)) == PROTECTED_MESSAGE
    # the second edit works on the result of the first
    chained = [{"old_string": "First", "new_string": "1st"},
               {"old_string": "1st point", "new_string": "\\vbox to 0pt{\\vss\\hbox{new}}"}]
    assert claude_hook.blocked_reason(event(root, "MultiEdit", edits=chained)) == PROTECTED_MESSAGE


@pytest.mark.parametrize("tool", ["Edit", "Write"])
def test_a_frozen_version_is_read_only(root, tool):
    event_ = edit(root, "First", "1st", FROZEN) if tool == "Edit" else event(root, "Write", FROZEN, content="x")
    reason = claude_hook.blocked_reason(event_)
    assert reason and FROZEN in reason and "frozen version" in reason and "-current.tex" in reason


def test_what_is_not_a_slide_or_cannot_be_judged_is_allowed(root):
    deck = event(root, "Edit", old_string="\\section{Intro}", new_string="\\section{Start}")
    deck["tool_input"]["file_path"] = str(root / "decks" / "test.tex")
    assert claude_hook.blocked_reason(deck) is None
    bib = event(root, "Write", content="@book{x}")
    bib["tool_input"]["file_path"] = str(root / "Slidemaster.bib")
    assert claude_hook.blocked_reason(bib) is None
    assert claude_hook.blocked_reason(edit(root, "not in the file at all", "x")) is None      # Edit fails on its own
    assert claude_hook.blocked_reason(edit(root, "", "x")) is None
    assert claude_hook.blocked_reason(event(root, "Write", "zzz-EN-New-current.tex", content="x")) is None   # new file
    assert claude_hook.blocked_reason(event(root, "Read")) is None
    assert claude_hook.blocked_reason(event(root, "Bash")) is None
    assert claude_hook.blocked_reason({"tool_name": "Edit", "tool_input": "garbage"}) is None
    assert claude_hook.blocked_reason({}) is None


def test_an_ambiguous_edit_is_left_to_claude_code_to_reject(root):
    assert claude_hook.blocked_reason(edit(root, "point", "idea")) is None     # twice in the file, no replace_all


def test_a_relative_path_is_taken_from_the_session_folder(root):
    relative = edit(root, "\\setSlideVersion{1-0-0}", "")
    relative["tool_input"]["file_path"] = f"slides/{CURRENT}"
    assert claude_hook.blocked_reason(relative) == PROTECTED_MESSAGE


# -- the command ---------------------------------------------------------------------------------------------

def run_main(monkeypatch, capsys, payload: str):
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(payload.encode())))
    code = claude_hook.main()
    return code, capsys.readouterr().err


def test_main_exits_2_with_the_reason_on_stderr_to_block(root, monkeypatch, capsys):
    code, err = run_main(monkeypatch, capsys, json.dumps(edit(root, "\\setSlideVersion{1-0-0}", "")))
    assert code == 2 and err.strip() == PROTECTED_MESSAGE
    code, err = run_main(monkeypatch, capsys, json.dumps(edit(root, "First point", "1st point")))
    assert code == 0 and err == ""


def test_main_never_blocks_because_of_its_own_trouble(monkeypatch, capsys):
    code, err = run_main(monkeypatch, capsys, "this is not json")
    assert code == 1 and "SlideMage hook" in err        # a non-blocking error: Claude Code goes on
    assert run_main(monkeypatch, capsys, "[]")[0] == 0


def test_the_command_as_claude_code_runs_it(tmp_path):
    """The hook as a real process, the way the settings JSON starts it, in a project with a slide."""
    project = make_project_in(tmp_path)
    payload = json.dumps({"cwd": str(project), "tool_name": "Edit", "tool_input": {
        "file_path": str(project / "slides" / CURRENT), "old_string": "\\setSlideVersion{1-0-0}", "new_string": ""}})
    env = {**os.environ, "SLIDEMASTER_PROJECT": str(project)}
    done = subprocess.run([sys.executable, "-m", "slidemage.ai.claude_hook"], input=payload.encode(), env=env,
                          capture_output=True, timeout=60)
    assert done.returncode == 2 and b"protected part" in done.stderr


def test_the_program_runs_the_hook_with_the_flag_as_the_frozen_build_does(tmp_path):
    """`SlideMage --claude-hook` (the frozen executable has no `-m`): same answer, and no window."""
    project = make_project_in(tmp_path)
    payload = json.dumps({"cwd": str(project), "tool_name": "Write", "tool_input": {
        "file_path": str(project / "slides" / FROZEN), "content": "x"}})
    done = subprocess.run([sys.executable, "-m", "slidemage", "--claude-hook"], input=payload.encode(), capture_output=True,
                          env={**os.environ, "SLIDEMASTER_PROJECT": str(project), "QT_QPA_PLATFORM": "offscreen"}, timeout=60)
    assert done.returncode == 2 and b"frozen version" in done.stderr


def make_project_in(tmp_path):
    """A real project folder (the subprocess reads it by SLIDEMASTER_PROJECT, so it needs the marker file)."""
    from slidemage import project

    root = tmp_path / "proj"
    (root / "slides").mkdir(parents=True)
    (root / project.MARKER).write_text("")
    (root / "slides" / CURRENT).write_bytes(SLIDE_TEXT.encode())
    return root.resolve()


def test_a_slide_that_cannot_be_read_is_refused_not_waved_through(root):
    (root / "slides" / CURRENT).write_bytes(b"\xff\xfe not utf-8 \x00")
    for call in (edit(root, "not utf-8", "x"), event(root, "Write", content="\\begin{x}")):
        reason = claude_hook.blocked_reason(call)
        assert reason and CURRENT in reason and "UTF-8" in reason
