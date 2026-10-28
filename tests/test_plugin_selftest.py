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


def test_imports_all_five_promised_qt_modules(monkeypatch):
    imported = []
    real = selftest.importlib.import_module

    def record(name):
        imported.append(name)
        return real(name)

    monkeypatch.setattr(selftest.importlib, "import_module", record)
    assert selftest._check_qt_imports() == []
    assert imported == [f"PySide6.{name}" for name in ("QtCore", "QtGui", "QtWidgets", "QtNetwork", "QtSvg")]


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


def test_loaded_plugin_builds_its_widget(qapp, monkeypatch):
    built = []
    real = selftest._check_widget

    def check(build):
        def record():
            widget = build()
            built.append(widget.text())
            return widget
        return real(record)

    monkeypatch.setattr(selftest, "_check_widget", check)
    assert selftest._check_plugin() == []
    assert built == ["Self-test widget"]


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

