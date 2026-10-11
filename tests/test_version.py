"""The displayed app version computes its Git suffix only on first access."""
from __future__ import annotations

import importlib.util
import sys

import pytest

from slidemage import version


@pytest.mark.parametrize("commit_dt", [None, "2026-10-11 12:34"])
def test_version_is_lazy_cached_and_importable(monkeypatch, commit_dt):
    def unexpected_git(*args, **kwargs):
        raise AssertionError("Git ran while importing version.py")

    monkeypatch.setattr(version.subprocess, "run", unexpected_git)
    name = "slidemage._test_version"
    spec = importlib.util.spec_from_file_location(name, version.__file__)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    assert "VERSION" not in vars(module)

    calls = []

    def run_git(*args):
        calls.append(args)
        return commit_dt

    monkeypatch.setattr(module, "run_git", run_git)
    expected = (f"{module.VERSION_NUMBER} ({commit_dt})"
                if commit_dt is not None else module.VERSION_NUMBER)
    assert module.VERSION == expected
    assert module.VERSION == expected
    imported = {}
    exec(f"from {name} import VERSION", imported)
    assert imported["VERSION"] == expected
    assert len(calls) == 1
