"""Starting the user's own Claude Code inside SlideMage (UI redesign step 10c): where `claude` is, and the
command line and environment that connect it to SlideMage's MCP server and protected-region hook.

Everything goes through command-line flags and the child's environment (`--mcp-config`, `--settings`,
`--append-system-prompt`): nothing is written to ~/.claude, to the project's .claude/ or to a .mcp.json.
The MCP bearer token is not on the command line (visible in `ps`): the config names the environment
variable it is read from, and only the child process gets it. No Qt.
"""
from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

from ..cli import CLAUDE_HOOK_FLAG
from .claude_scope import FOCUS_ENV
from .tools import CLAUDE_CODE_READ_ONLY

SERVER_NAME = "slidemage"
TOKEN_ENV = "SLIDEMAGE_MCP_TOKEN"
HOOK_MATCHER = "Edit|Write|MultiEdit"
INSTALL_URL = "https://docs.claude.com/en/docs/claude-code/setup"

ORIENTATION = (
    "You are running inside SlideMage, a desktop app for writing LaTeX (beamer) slide decks; the project is the "
    "current folder and the user sees SlideMage's editor beside this terminal. The MCP server 'slidemage' tells "
    "you what they are looking at: call get_focus first when they say 'this slide' or 'here' (each prompt opens "
    "with a [SlideMage scope: ...] line that already names the slide and how far you may go: follow it). "
    "read_buffer shows "
    "an open file with its unsaved edits (your Read shows the older file on disk); lint checks a slide; "
    "render_preview typesets it and shows you the image (look at it after a layout change); list_slides lists "
    "a deck; read_guide explains the conventions (slides, frames, layout, reveals, citations, "
    "images_and_text): read it before writing something you are unsure of; add_slide creates a slide with a "
    "fresh id (never invent a slide file by hand). Slides are slides/<id>-<LANG>-<Slug>-current.tex, decks "
    "decks/<name>.tex. Never edit a frozen slides/*-vX-Y-Z.tex, a slide's leading '%%' comment block, its "
    "\\setSlideVersion line or a \\vbox to 0pt{...} block: a hook refuses those edits. SlideMage reloads files "
    "you change; if the user has unsaved edits in the same file it asks them first. After creating a slide, or "
    "changing one the user is not looking at, call show_slide so they see it. To translate a slide, call "
    "translate_slide and then only say that SlideMage is translating it. Answers are short: one or two "
    "sentences on what you did, no recap of the slide's content, no list of things to check; end with at most "
    "one question offering a concrete next step (e.g. 'Create the German version?').")


def _extra_dirs() -> list[Path]:
    home = Path.home()
    dirs = [home / ".local" / "bin", home / ".claude" / "local", home / ".npm-global" / "bin",
            Path("/usr/local/bin"), Path("/opt/homebrew/bin")]
    if sys.platform == "win32":
        dirs += [Path(os.environ.get("APPDATA", home / "AppData" / "Roaming")) / "npm",
                 Path(os.environ.get("LOCALAPPDATA", home / "AppData" / "Local")) / "Programs" / "claude"]
    return dirs


def find_claude() -> Path | None:
    """The user's `claude`: on PATH, else in the places its installers use (a desktop launcher often has a
    shorter PATH than a terminal)."""
    found = shutil.which("claude")
    if found:
        return Path(found)
    names = ("claude.exe", "claude.cmd", "claude") if sys.platform == "win32" else ("claude",)
    for folder in _extra_dirs():
        for name in names:
            candidate = folder / name
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return candidate
    return None


def hook_command() -> str:
    """The shell command Claude Code runs for the hook: this very program, so that it finds the same
    SlideMage (the frozen build has no `python -m`, its executable takes CLAUDE_HOOK_FLAG)."""
    if getattr(sys, "frozen", False):
        argv = [sys.executable, CLAUDE_HOOK_FLAG]
    else:
        argv = [sys.executable, "-m", "slidemage.ai.claude_hook"]
    return subprocess.list2cmdline(argv) if sys.platform == "win32" else shlex.join(argv)


def mcp_config(url: str) -> dict:
    return {"mcpServers": {SERVER_NAME: {
        "type": "http", "url": url, "headers": {"Authorization": f"Bearer ${{{TOKEN_ENV}}}"}}}}


def settings(hook: str) -> dict:
    """Extra settings for this session only: the protected-region hook, and the read-only tools allowed
    without asking (add_slide asks, like any tool that changes files)."""
    return {
        "hooks": {"PreToolUse": [{"matcher": HOOK_MATCHER, "hooks": [{"type": "command", "command": hook}]}],
                  "UserPromptSubmit": [{"hooks": [{"type": "command", "command": hook}]}]},
        "permissions": {"allow": [f"mcp__{SERVER_NAME}__{t.spec.name}" for t in CLAUDE_CODE_READ_ONLY]}}


def build_command(claude: Path, url: str, hook: str | None = None) -> list[str]:
    return [str(claude),
            "--mcp-config", json.dumps(mcp_config(url)),
            "--settings", json.dumps(settings(hook or hook_command())),
            "--append-system-prompt", ORIENTATION]


# Claude Code settings of the user that survive the clean-up of `environment`: a subscription token from
# `claude setup-token`, and plain tuning. Everything else named CLAUDE_CODE_* is dropped: session markers of a
# Claude Code that started SlideMage, and CLAUDE_CODE_USE_BEDROCK / _VERTEX / _FOUNDRY, which would replace the login.
KEEP_CLAUDE_CODE = ("CLAUDE_CODE_OAUTH_TOKEN", "CLAUDE_CODE_MAX_OUTPUT_TOKENS", "CLAUDE_CODE_GIT_BASH_PATH",
                    "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC")
DROP = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDECODE", "CLAUDE_AGENT_SDK_VERSION", "CLAUDE_PID",
        "CLAUDE_EFFORT")


def _inherited(name: str) -> bool:
    if name in KEEP_CLAUDE_CODE:
        return True
    return not (name in DROP or name.startswith("CLAUDE_CODE_"))


def clean_environment(claude: Path, base: dict[str, str] | None = None) -> dict[str, str]:
    """The app's environment, without what would stop Claude Code using the user's own login (an API key or auth
    token in the environment, markers of a Claude Code session SlideMage was started from), and with `claude`'s
    own folder on PATH (an npm install runs through `node` found there)."""
    env = {name: value for name, value in (os.environ if base is None else base).items() if _inherited(name)}
    env["PATH"] = os.pathsep.join([str(claude.parent), env.get("PATH", "")]) if env.get("PATH") else str(claude.parent)
    return env


def environment(token: str, project: Path, claude: Path, base: dict[str, str] | None = None,
                focus_file: Path | None = None) -> dict[str, str]:
    """The terminal's environment: `clean_environment`, a terminal that does colour, the token, the project for
    the hook, and this SlideMage on PYTHONPATH for the hook."""
    env = clean_environment(claude, base)
    env.update({"TERM": "xterm-256color", "COLORTERM": "truecolor", TOKEN_ENV: token,
                "SLIDEMASTER_PROJECT": str(project)})
    if focus_file is not None:
        env[FOCUS_ENV] = str(focus_file)
    if not getattr(sys, "frozen", False):
        # `python -m slidemage.ai.claude_hook` must import this very SlideMage, also when it runs from a source
        # tree that is not installed (a hook that fails to start is a warning, so it would let every edit through).
        env["PYTHONPATH"] = os.pathsep.join(filter(None, [str(Path(__file__).resolve().parents[2]), env.get("PYTHONPATH")]))
    return env
