# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Host.add_entry_point and `SlideMage --plugin <id>:<name>`: a plugin's code run as a program, with no window."""
from __future__ import annotations

import sys

import pytest

from slidemage import cli, project
from slidemage.ai import claude_hook
from slidemage.plugins import loader
from slidemage.plugins.manifest import Manifest, read_manifest
from slidemage.plugins.registry import Registrar

TOML = """\
id = "entryfix"
name = "Entry fixture"
version = "0.1.0"
api_version = 1
requires_slidemage = ">=8.0"
summary = "Fixture plugin with entry points."
author = "Test"
homepage = "https://example.org/entryfix"
license = "GPL-3.0-or-later"
"""
INIT = '''\
import sys

def activate(host):
    def hook(args):
        print("args=" + ",".join(args))
        print("command=" + " ".join(host.entry_point_command("hook")))
        return 3
    host.add_entry_point("hook", hook)
    host.add_entry_point("quiet", lambda args: None)
    host.add_entry_point("boom", lambda args: sys.exit(5))
'''


@pytest.fixture
def plugin_path(tmp_path, monkeypatch):
    folder = tmp_path / "dev" / "entryfix"
    (folder / "entryfix").mkdir(parents=True)
    (folder / "plugin.toml").write_text(TOML, encoding="utf-8")
    (folder / "entryfix" / "__init__.py").write_text(INIT, encoding="utf-8")
    monkeypatch.setattr(project, "config_dir", lambda: tmp_path / "config")
    monkeypatch.setenv(loader.PATH_ENV, str(folder))
    monkeypatch.setenv(project.ENV_VAR, str(tmp_path))      # no project to look for
    yield folder
    loader._discard_module("entryfix")


def run(argv):
    try:
        with pytest.raises(SystemExit) as stop:
            cli.main(argv)
    finally:
        loader._discard_module("entryfix")      # a real run is one process per entry point; the tests share one
    return stop.value.code


def test_the_entry_point_runs_with_its_arguments_and_returns_its_code(plugin_path, capsys):
    assert run(["--plugin", "entryfix:hook", "--flag", "x"]) == 3
    out = capsys.readouterr().out
    assert "args=--flag,x" in out
    assert out.rstrip().endswith("--plugin entryfix:hook")


def test_none_is_exit_code_zero_and_a_systemexit_passes_through(plugin_path):
    assert run(["--plugin", "entryfix:quiet"]) == 0
    assert run(["--plugin", "entryfix:boom"]) == 5


@pytest.mark.parametrize("spec, words", [
    ("entryfix:nothing", "no entry point 'nothing'"),
    ("nobody:hook", "no plugin 'nobody'"),
    ("entryfix", "<plugin id>:<entry point>"),
    ("", "<plugin id>:<entry point>"),
])
def test_unknown_plugin_or_entry_point_is_exit_2_with_a_message(plugin_path, capsys, spec, words):
    assert run(["--plugin", spec]) == 2
    assert words in capsys.readouterr().err


def test_no_argument_is_exit_2(plugin_path, capsys):
    assert run(["--plugin"]) == 2
    assert "--plugin wants" in capsys.readouterr().err


def test_a_disabled_plugin_is_not_run(plugin_path, capsys):
    loader.set_enabled("entryfix", False)
    assert run(["--plugin", "entryfix:hook"]) == 2
    assert "disabled" in capsys.readouterr().err


def test_claude_hook_flag_is_unchanged(monkeypatch):
    monkeypatch.setattr(claude_hook, "main", lambda: 7)
    assert run([cli.CLAUDE_HOOK_FLAG]) == 7


def registrar():
    manifest = read_manifest_from(TOML)
    return Registrar(manifest)


def read_manifest_from(text):
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "plugin.toml").write_text(text, encoding="utf-8")
        return read_manifest(Path(tmp))


def test_registration_rules():
    reg = registrar()
    with pytest.raises(RuntimeError):
        reg.add_entry_point("hook", lambda args: 0)         # only while activate() runs
    with reg.activation():
        reg.add_entry_point("hook", lambda args: 0)
        with pytest.raises(ValueError):
            reg.add_entry_point("hook", lambda args: 0)
        for bad in ("", "Hook", "a b", "1x", "a:b"):
            with pytest.raises(ValueError):
                reg.add_entry_point(bad, lambda args: 0)
    assert list(reg.contributions.entry_points) == ["hook"]


def test_entry_point_command_from_source_and_frozen(monkeypatch):
    reg = registrar()
    assert reg.entry_point_command("hook") == [sys.executable, "-m", "slidemage", "--plugin", "entryfix:hook"]
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert reg.entry_point_command("hook") == [sys.executable, "--plugin", "entryfix:hook"]
    assert isinstance(reg.manifest, Manifest)
