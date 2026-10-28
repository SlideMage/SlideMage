# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The plugin host's part of `slidemage --self-test --plugins`, run on every build before it is published.

Two checks. First, every standard-library module a plugin may import is importable: PyInstaller bundles only what
SlideMage itself imports, so a plugin using csv or smtplib would fail only in the installed app. Second, a
minimal plugin is written to a temporary folder and loaded through the real loader, which must end "loaded"
with its one command.

This file imports only the standard library at module level: packaging/slidemage.spec loads it by path, to get
bundled_stdlib_modules() at build time, so the spec and this check use the same list.
"""
from __future__ import annotations

import importlib
import importlib.util
import os
import sys
import tempfile
from pathlib import Path

# Standard-library modules that are not hidden imports: GUI toolkits and developer tools a plugin has no use for,
# modules that do something when imported, and the ones an installed app must not carry.
EXCLUDED = frozenset({
    "tkinter", "turtle", "turtledemo", "idlelib", "test", "ensurepip", "lib2to3", "pydoc_data", "this", "antigravity",
})
# The list the spec writes beside the build (slidemage/plugins/), for the frozen self-test: find_spec in a frozen
# app finds only what was bundled, so a module PyInstaller missed would silently drop out of the check.
STDLIB_LIST_NAME = "stdlib_modules.txt"

PLUGIN_ID = "selftest"
PLUGIN_TOML = """\
id = "selftest"
name = "Self-test"
version = "1.0.0"
api_version = 1
requires_slidemage = ">=1.0"
summary = "Loaded by slidemage --self-test --plugins."
author = "SlideMage"
homepage = "https://example.invalid/selftest"
license = "GPL-3.0-or-later"
"""
PLUGIN_INIT = '''\
def activate(host):
    host.add_command("selftest.ok", "Self-test", lambda deck: None)
'''


def bundled_stdlib_modules() -> list[str]:
    """The top-level standard-library modules a plugin may import, on this platform: sys.stdlib_module_names
    without EXCLUDED and without private names (except _thread), and without those find_spec cannot find here
    (msvcrt on Linux, say). Packages are listed by name; the spec adds their submodules."""
    names = []
    for name in sorted(sys.stdlib_module_names):
        if name in EXCLUDED or (name.startswith("_") and name != "_thread"):
            continue
        try:
            found = importlib.util.find_spec(name) is not None
        except Exception:
            found = False
        if found:
            names.append(name)
    return names


def _expected_modules() -> list[str]:
    if getattr(sys, "frozen", False):
        path = Path(getattr(sys, "_MEIPASS", "")) / "slidemage" / "plugins" / STDLIB_LIST_NAME
        return path.read_text(encoding="utf-8").split()
    return bundled_stdlib_modules()


def _check_imports() -> list[str]:
    try:
        names = _expected_modules()
    except OSError as e:
        return [f"the list of bundled standard-library modules cannot be read: {e}"]
    if not names:
        return ["the list of bundled standard-library modules is empty"]
    problems = []
    for name in names:
        try:
            importlib.import_module(name)
        except Exception as e:
            problems.append(f"standard-library module {name} does not import: {e!r}")
    return problems


def _check_plugin() -> list[str]:
    from .. import project
    from . import loader
    from .registry import Registrar

    problems: list[str] = []
    old_config_dir = project.config_dir
    old_path = os.environ.get(loader.PATH_ENV)
    with tempfile.TemporaryDirectory(prefix="slidemage-selftest-") as tmp:
        root = Path(tmp)
        folder = root / "plugin"
        (folder / PLUGIN_ID).mkdir(parents=True)
        (folder / "plugin.toml").write_text(PLUGIN_TOML, encoding="utf-8")
        (folder / PLUGIN_ID / "__init__.py").write_text(PLUGIN_INIT, encoding="utf-8")
        project.config_dir = lambda: root / "config"
        os.environ[loader.PATH_ENV] = str(folder)
        try:
            loaded = loader.load_all(lambda manifest: Registrar(manifest))
        finally:
            project.config_dir = old_config_dir
            if old_path is None:
                os.environ.pop(loader.PATH_ENV, None)
            else:
                os.environ[loader.PATH_ENV] = old_path
            loader._discard_module(PLUGIN_ID)   # the test plugin's package must not stay importable
    mine = [p for p in loaded if p.id == PLUGIN_ID]
    if len(mine) != 1:
        return [f"the self-test plugin was not found (plugins found: {[p.id for p in loaded]})"]
    plugin = mine[0]
    if plugin.state != "loaded":
        return [f"the self-test plugin is {plugin.state}: {plugin.reason}"]
    commands = [c.id for c in plugin.contributions.commands]
    if commands != ["selftest.ok"]:
        problems.append(f"the self-test plugin registered commands {commands}, expected ['selftest.ok']")
    return problems


def run() -> int:
    problems = _check_imports() + _check_plugin()
    if problems:
        print("SlideMage plugin self-test: failed")
        for problem in problems:
            print(f"  {problem}")
        return 1
    print("SlideMage plugin self-test: ok")
    return 0
