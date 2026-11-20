# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The displayed app version computes its Git suffix only on first access."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from slidemage import processes, version


@pytest.mark.parametrize("git_out, unreleased, expected", [
    (None, False, ""),
    ("3e7142f9 2026-10-11 12:34", False, " (2026-10-11 12:34)"),
    ("3e7142f9 2026-10-11 12:34", True, "+dev (3e7142f9, 2026-10-11 12:34)"),
])
def test_version_is_lazy_cached_and_importable(monkeypatch, git_out, unreleased, expected):
    def unexpected_git(*args, **kwargs):
        raise AssertionError("Git ran while importing version.py")

    monkeypatch.setattr(processes.subprocess, "run", unexpected_git)
    name = "slidemage._test_version"
    spec = importlib.util.spec_from_file_location(name, version.__file__)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    assert "VERSION" not in vars(module)

    calls = []

    def run_git(*args):
        calls.append(args)
        return git_out

    monkeypatch.setattr(module, "run_git", run_git)
    monkeypatch.setattr(module, "unreleased_fragments", lambda: [Path("changes/x.md")] if unreleased else [])
    expected = module.VERSION_NUMBER + expected
    assert module.VERSION == expected
    assert module.VERSION == expected
    imported = {}
    exec(f"from {name} import VERSION", imported)
    assert imported["VERSION"] == expected
    assert len(calls) == 1
