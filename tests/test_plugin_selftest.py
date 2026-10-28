# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""`slidemage --self-test --plugins`: the bundled standard library and a plugin loaded through the loader."""
from __future__ import annotations

import pytest

from slidemage import cli
from slidemage.plugins import selftest


def test_run_passes_in_the_venv(capsys):
    assert selftest.run() == 0   # its plugin's config is a temporary folder, not the user's
    assert "SlideMage plugin self-test: ok" in capsys.readouterr().out


def test_bundled_list_excludes_the_listed_names():
    names = set(selftest.bundled_stdlib_modules())
    for excluded in ("tkinter", "turtle", "turtledemo", "idlelib", "test", "ensurepip", "lib2to3",
                     "pydoc_data", "this", "antigravity"):
        assert excluded not in names
    assert not [n for n in names if n.startswith("_") and n != "_thread"]


def test_bundled_list_includes_what_plugins_use():
    names = set(selftest.bundled_stdlib_modules())
    for wanted in ("json", "csv", "http", "urllib", "ssl", "smtplib", "_thread"):
        assert wanted in names


def test_cli_dispatches_plugins_flag_to_the_selftest(monkeypatch):
    calls = []
    monkeypatch.setattr(selftest, "run", lambda: calls.append(True) or 7)
    monkeypatch.setattr(cli.splash, "close", lambda: None)
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["--self-test", "--plugins"])
    assert calls == [True]
    assert exit_info.value.code == 7
