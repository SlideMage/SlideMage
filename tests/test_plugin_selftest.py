# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""`slidemage --self-test --plugins`: the bundled standard library and a plugin loaded through the loader."""
from __future__ import annotations

from pathlib import Path
import re

import pytest

from slidemage import cli, plugin_api
from slidemage.plugins import selftest


def test_run_passes_in_the_venv(capsys):
    assert selftest.run() == 0   # its plugin's config is a temporary folder, not the user's
    assert "SlideMage plugin self-test: ok" in capsys.readouterr().out


def test_bundled_list_excludes_the_listed_names():
    names = set(selftest.bundled_stdlib_modules())
    assert names.isdisjoint({"tkinter", "turtle", "turtledemo", "idlelib", "test", "ensurepip",
                             "lib2to3", "pydoc_data", "this", "antigravity"})
    assert {"json", "csv", "http", "urllib", "ssl", "smtplib", "_thread"} <= names
    assert not [n for n in names if n.startswith("_") and n != "_thread"]


def test_cli_dispatches_plugins_flag_to_the_selftest(monkeypatch):
    calls = []
    monkeypatch.setattr(selftest, "run", lambda: calls.append(True) or 7)
    monkeypatch.setattr(cli.splash, "close", lambda: None)
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["--self-test", "--plugins"])
    assert calls == [True]
    assert exit_info.value.code == 7


@pytest.mark.parametrize("module", selftest.PYSIDE_MODULES)
def test_missing_promised_qt_module_fails_selftest(monkeypatch, module, capsys):
    real = selftest.importlib.import_module

    def missing(name):
        if name == f"PySide6.{module}":
            raise ImportError("not bundled")
        return real(name)

    monkeypatch.setattr(selftest.importlib, "import_module", missing)
    monkeypatch.setattr(selftest, "_check_imports", lambda: [])
    assert selftest.run() == 1
    assert f"PySide6 module {module} does not import" in capsys.readouterr().out


def test_plugin_widget_failure_fails_selftest(qapp, monkeypatch, capsys):
    monkeypatch.setattr(selftest, "PLUGIN_INIT", selftest.PLUGIN_INIT.replace(
        'return QLabel("Self-test widget")', 'raise RuntimeError("widget failed")'))
    monkeypatch.setattr(selftest, "_check_imports", lambda: [])
    assert selftest.run() == 1
    assert "the self-test plugin UI failed" in capsys.readouterr().out

def test_every_module_plugin_api_loads_by_name_is_bundled_and_checked():
    source = (Path(plugin_api.__file__)).read_text(encoding="utf-8")
    named = set(re.findall(r'import_module\("(slidemage[.\w]*)"\)', source)) | set(plugin_api._LAZY.values())
    assert named and named <= set(plugin_api._RUNTIME_MODULES)


def test_missing_plugin_api_module_fails_selftest(monkeypatch, capsys):
    monkeypatch.setattr(plugin_api, "_RUNTIME_MODULES", ("slidemage.no_such_module",))
    assert selftest.run() == 1
    assert "plugin_api's module slidemage.no_such_module does not import" in capsys.readouterr().out



def test_modules_that_refuse_windows_are_not_listed_there(monkeypatch):
    """Windows release self-tests must exclude modules present but unimportable there."""
    import importlib.util
    import sys

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys, "stdlib_module_names", frozenset({"crypt", "curses", "json", "pty", "tty"}))
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: object())      # as if each were there
    assert selftest.bundled_stdlib_modules() == ["json"]
