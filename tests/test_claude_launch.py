# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""How the embedded Claude Code is found and started (ai/claude_launch.py): where `claude` is looked for, the
exact flags and JSON, the environment of the child, and that nothing is written into the user's Claude
configuration or the project (only flags and environment variables carry the setup)."""
from __future__ import annotations

import json
import os
import shlex
import stat
import sys
from pathlib import Path

import pytest

from slidemage import cli
from slidemage.ai import claude_launch, claude_scope
from slidemage.ai.tools import CLAUDE_CODE_READ_ONLY

URL = "http://127.0.0.1:4711/mcp"


def test_orientation_and_prompt_scope_agree_on_focus_and_keep_editor_guards():
    orientation = claude_launch.ORIENTATION
    scope = claude_scope.prompt_context({"scope": "slide", "slide": "slides/abc-EN-Hello-current.tex", "dirty": True})
    for text in (orientation, scope):
        assert "call get_focus only if the focus is missing or stale" in text
        assert "read_buffer" in text and "call get_focus first" not in text
    assert "Batch independent reads in one turn" in orientation
    assert "native Edit/Write for other files" in orientation
    assert "modify_slide" in orientation and "create_slide" in orientation
    assert all(guard in orientation for guard in ("frozen", "leading '%%'", "\\setSlideVersion", "\\vbox to 0pt", "hook"))
    assert "do not explore" in scope and "switch_to_deck_mode" in scope


def make_executable(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\n")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


@pytest.mark.parametrize("location", ["path", "installer", "not-executable"])
def test_claude_discovery(tmp_path, monkeypatch, location):
    """Find an executable on PATH or in the installer folder used by desktop launches."""
    home = tmp_path / "home"
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    monkeypatch.setattr(claude_launch.Path, "home", lambda: home)
    monkeypatch.setattr(sys, "platform", "linux")
    assert claude_launch.find_claude() is None
    candidate = tmp_path / "bin" / "claude" if location == "path" else home / ".local" / "bin" / "claude"
    if location == "not-executable":
        if os.name == "nt":
            pytest.skip("Windows has no executable bit: os.access(X_OK) is true for every file")
        candidate.parent.mkdir(parents=True)
        candidate.write_text("not a program")
        assert claude_launch.find_claude() is None
    else:
        make_executable(candidate)
        if location == "path":
            monkeypatch.setenv("PATH", str(candidate.parent))
        assert claude_launch.find_claude() == candidate


def test_the_command_line_leaves_the_model_and_effort_to_claude_code(tmp_path):
    # the tab's picker is gone: tasks follow the active route (ai_profile), the terminal its own defaults
    command = claude_launch.build_command(tmp_path / "claude", URL)
    assert "--model" not in command and "--effort" not in command


def test_the_command_line_carries_the_mcp_server_the_hook_and_the_orientation(tmp_path):
    claude = tmp_path / "claude"
    command = claude_launch.build_command(claude, URL, hook="HOOK COMMAND")
    assert command[0] == str(claude)
    flags = dict(zip(command[1::2], command[2::2], strict=True))
    assert json.loads(flags["--mcp-config"]) == {"mcpServers": {"slidemage": {
        "type": "http", "url": URL, "headers": {"Authorization": "Bearer ${SLIDEMAGE_MCP_TOKEN}"}}}}
    settings = json.loads(flags["--settings"])
    assert settings["hooks"] == {"PreToolUse": [{"matcher": "Edit|Write|MultiEdit", "hooks": [
        {"type": "command", "command": "HOOK COMMAND"}]}],
        "PostToolUse": [{"matcher": "Edit|Write|MultiEdit", "hooks": [
            {"type": "command", "command": "HOOK COMMAND"}]}],
        "UserPromptSubmit": [{"hooks": [{"type": "command", "command": "HOOK COMMAND"}]}]}
    assert settings["permissions"]["allow"] == [f"mcp__slidemage__{t.spec.name}" for t in CLAUDE_CODE_READ_ONLY]
    assert "add_slide" not in " ".join(settings["permissions"]["allow"])        # it changes files: Claude asks
    assert "insert_slide" not in " ".join(settings["permissions"]["allow"])
    assert "create_slide" not in " ".join(settings["permissions"]["allow"])
    assert "modify_slide" not in " ".join(settings["permissions"]["allow"])
    assert "get_focus" in flags["--append-system-prompt"] and "hook" in flags["--append-system-prompt"]
    # no bearer token on the command line (visible in `ps`)
    assert "Bearer ${" in command[2] and "--strict-mcp-config" not in command


def test_the_token_goes_to_the_child_by_environment_only(tmp_path):
    claude = tmp_path / "bin" / "claude"
    env = claude_launch.environment("s3cret", tmp_path / "proj", claude, base={"PATH": "/usr/bin", "HOME": "/h"})
    assert env["SLIDEMAGE_MCP_TOKEN"] == "s3cret" and env["SLIDEMASTER_PROJECT"] == str(tmp_path / "proj")
    assert env["TERM"] == "xterm-256color" and env["COLORTERM"] == "truecolor" and env["HOME"] == "/h"
    assert env["PATH"].split(os.pathsep) == [str(claude.parent), "/usr/bin"]
    assert "s3cret" not in " ".join(claude_launch.build_command(claude, URL))


def test_the_hook_finds_this_slidemage_even_when_it_is_not_installed(tmp_path):
    here = str(Path(claude_launch.__file__).resolve().parents[2])
    env = claude_launch.environment("t", tmp_path, tmp_path / "claude", {"PATH": "/usr/bin", "PYTHONPATH": "/mine"})
    assert env["PYTHONPATH"].split(os.pathsep) == [here, "/mine"] and (Path(here) / "slidemage").is_dir()
    assert claude_launch.environment("t", tmp_path, tmp_path / "claude", {})["PYTHONPATH"] == here


def test_the_child_uses_the_users_own_login_not_keys_or_inherited_sessions(tmp_path):
    base = {"PATH": "/usr/bin", "HOME": "/h", "ANTHROPIC_API_KEY": "sk-x", "ANTHROPIC_AUTH_TOKEN": "t",
            "CLAUDECODE": "1", "CLAUDE_CODE_CHILD_SESSION": "1", "CLAUDE_CODE_SESSION_ID": "s",
            "CLAUDE_CODE_ENTRYPOINT": "cli", "CLAUDE_CODE_USE_BEDROCK": "1", "CLAUDE_PID": "7",
            "CLAUDE_CODE_OAUTH_TOKEN": "oauth", "CLAUDE_CODE_MAX_OUTPUT_TOKENS": "9000", "ANTHROPIC_BASE_URL": "u"}
    env = claude_launch.environment("t0k", tmp_path, tmp_path / "claude", base)
    assert not {"ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDECODE", "CLAUDE_CODE_CHILD_SESSION",
                "CLAUDE_CODE_SESSION_ID", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_PID"} & set(env)
    assert env["CLAUDE_CODE_OAUTH_TOKEN"] == "oauth" and env["CLAUDE_CODE_MAX_OUTPUT_TOKENS"] == "9000"
    assert env["ANTHROPIC_BASE_URL"] == "u" and env["HOME"] == "/h"          # other settings stay the user's


def test_the_hook_command_runs_this_python_unfrozen_and_this_program_frozen(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    plain = shlex.split(claude_launch.hook_command())
    assert plain == [sys.executable, "-m", "slidemage.ai.claude_hook"]
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", "/opt/Slide Mage/SlideMage")
    assert shlex.split(claude_launch.hook_command()) == ["/opt/Slide Mage/SlideMage", cli.CLAUDE_HOOK_FLAG]
    monkeypatch.setattr(sys, "platform", "win32")
    assert claude_launch.hook_command() == '"/opt/Slide Mage/SlideMage" --claude-hook'


def test_the_frozen_program_runs_the_hook_when_given_the_flag(monkeypatch):
    called = []
    monkeypatch.setattr("slidemage.ai.claude_hook.main", lambda: called.append(1) or 7)
    try:
        cli.main([cli.CLAUDE_HOOK_FLAG])
    except SystemExit as exit_:
        assert exit_.code == 7
    assert called == [1]


def test_building_the_launch_writes_nothing_anywhere(tmp_path, monkeypatch):
    """Not into ~/.claude, a project's .claude/ or a .mcp.json: the setup is flags and environment."""
    home = tmp_path / "home"
    project = tmp_path / "project"
    home.mkdir()
    project.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.chdir(project)
    claude = make_executable(home / ".local" / "bin" / "claude")
    monkeypatch.setenv("PATH", str(claude.parent))
    found = claude_launch.find_claude()
    claude_launch.build_command(found, URL)
    claude_launch.environment("t", project, found)
    assert sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*")) == [
        "home", "home/.local", "home/.local/bin", "home/.local/bin/claude", "project"]


def test_saved_chat_model_and_effort_are_passed_as_launch_flags(ctx, tmp_path):
    from slidemage.ai import ai_profile

    ai_profile.set_model_choice(ctx, ai_profile.CLAUDE_CODE, ai_profile.CHAT, "opus:high")
    route = ai_profile.route_for(ctx, ai_profile.CLAUDE_CODE, ai_profile.CHAT)
    command = claude_launch.build_command(tmp_path / "claude", URL, model=route.model, effort=route.effort)
    assert command[1:5] == ["--model", "opus", "--effort", "high"]


def test_image_description_language_instructions_reach_both_chats_and_guide():
    from slidemage.ai import agent_context, guides

    for prompt in (claude_launch.ORIENTATION, agent_context.SYSTEM_PROMPT, guides.GUIDES["images_and_text"][1]):
        assert "media/alt-text.json" in prompt
        assert "short_de and long_de" in prompt and "in German" in prompt
        assert "EN/DE segment" in prompt and "deck's editing language" in prompt
        assert "Preserve existing descriptions in the other language" in prompt


def test_a_session_id_names_the_conversation_or_resumes_it(tmp_path):
    command = claude_launch.build_command(tmp_path / "claude", URL, model="opus", session_id="abc")
    assert command[1:5] == ["--session-id", "abc", "--model", "opus"]
    command = claude_launch.build_command(tmp_path / "claude", URL, model="opus", session_id="abc", resume=True)
    assert command[1:5] == ["--resume", "abc", "--model", "opus"]
    assert "--resume" not in claude_launch.build_command(tmp_path / "claude", URL, resume=True)     # no id, no flag


def test_a_transcript_is_found_in_any_project_folder_of_the_config_dir(tmp_path):
    env = {"CLAUDE_CONFIG_DIR": str(tmp_path)}
    assert not claude_launch.has_transcript("abc", env)
    (tmp_path / "projects" / "D--some-project").mkdir(parents=True)
    (tmp_path / "projects" / "D--some-project" / "abc.jsonl").write_text("{}\n", encoding="utf-8")
    assert claude_launch.has_transcript("abc", env) and not claude_launch.has_transcript("abd", env)
    assert not claude_launch.has_transcript("", env)
