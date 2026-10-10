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

from slidemage import cli
from slidemage.ai import claude_launch
from slidemage.ai.tools import CLAUDE_CODE_READ_ONLY

URL = "http://127.0.0.1:4711/mcp"


def make_executable(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\n")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def test_claude_is_found_on_the_path(tmp_path, monkeypatch):
    found = make_executable(tmp_path / "bin" / "claude")
    monkeypatch.setenv("PATH", str(found.parent))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    assert claude_launch.find_claude() == found


def test_claude_is_found_in_the_places_its_installers_use(tmp_path, monkeypatch):
    """A desktop launcher often has a shorter PATH than a terminal."""
    home = tmp_path / "home"
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    monkeypatch.setattr(claude_launch.Path, "home", lambda: home)
    monkeypatch.setattr(sys, "platform", "linux")
    assert claude_launch.find_claude() is None
    installed = make_executable(home / ".local" / "bin" / "claude")
    assert claude_launch.find_claude() == installed


def test_a_file_that_is_not_executable_does_not_count(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    monkeypatch.setattr(claude_launch.Path, "home", lambda: home)
    (home / ".local" / "bin").mkdir(parents=True)
    (home / ".local" / "bin" / "claude").write_text("not a program")
    assert claude_launch.find_claude() is None


def test_the_command_line_carries_the_mcp_server_the_hook_and_the_orientation(tmp_path):
    claude = tmp_path / "claude"
    command = claude_launch.build_command(claude, URL, hook="HOOK COMMAND")
    assert command[0] == str(claude)
    flags = dict(zip(command[1::2], command[2::2], strict=True))
    assert list(flags) == ["--mcp-config", "--settings", "--append-system-prompt"]
    assert json.loads(flags["--mcp-config"]) == {"mcpServers": {"slidemage": {
        "type": "http", "url": URL, "headers": {"Authorization": "Bearer ${SLIDEMAGE_MCP_TOKEN}"}}}}
    settings = json.loads(flags["--settings"])
    assert settings["hooks"] == {"PreToolUse": [{"matcher": "Edit|Write|MultiEdit", "hooks": [
        {"type": "command", "command": "HOOK COMMAND"}]}]}
    assert settings["permissions"]["allow"] == [f"mcp__slidemage__{t.spec.name}" for t in CLAUDE_CODE_READ_ONLY]
    assert "add_slide" not in " ".join(settings["permissions"]["allow"])        # it changes files: Claude asks
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
