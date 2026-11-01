# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""packaging/presenter_paths.txt lists what SlideMage Presenter is built from; release.yml attaches the Presenter's
zips only when one of those files changed (docs/plans/presenter-app.md, step 4). This keeps the list complete."""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import slidemage
from test_presenter_imports import PRESENTER_MODULES

ROOT = Path(slidemage.__file__).resolve().parents[2]
PATHS_FILE = ROOT / "packaging" / "presenter_paths.txt"
# version.py changes with every release and is deliberately not a reason for a new Presenter.
EXEMPT = {"src/slidemage/version.py"}
# The program also runs these, though no start-up import reaches them: the update notice and the updater.
ALSO_IMPORTED = ("slidemage.presentation.presenter_update", "slidemage.updater")


def _load_script(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "packaging" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


changed = _load_script("presenter_changed")


def _matches(spec: str, path: str) -> bool:
    return path.startswith(spec) if spec.endswith("/") else path == spec


def _loaded_files() -> list[str]:
    script = ("import json, sys\n"
              f"for name in {PRESENTER_MODULES + ALSO_IMPORTED!r}:\n"
              "    __import__(name)\n"
              "print(json.dumps([m.__file__ for n, m in sorted(sys.modules.items())\n"
              "                  if (n == 'slidemage' or n.startswith('slidemage.')) and getattr(m, '__file__', None)]))\n")
    env = {**os.environ, "PYTHONPATH": str(Path(slidemage.__file__).resolve().parents[1]),
           "QT_QPA_PLATFORM": "offscreen"}
    done = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=120, env=env)
    assert done.returncode == 0, done.stderr[-2000:]
    return json.loads(done.stdout.strip().splitlines()[-1])


def test_every_module_the_presenter_loads_is_listed():
    specs = changed.pathspecs(PATHS_FILE.read_text(encoding="utf-8"))
    files = [Path(name).resolve().relative_to(ROOT).as_posix() for name in _loaded_files()]
    assert files, "no slidemage module was loaded"
    missing = [f for f in files if f not in EXEMPT and not any(_matches(spec, f) for spec in specs)]
    assert not missing, f"add to packaging/presenter_paths.txt: {missing}"


def test_every_listed_path_exists():
    for spec in changed.pathspecs(PATHS_FILE.read_text(encoding="utf-8")):
        assert (ROOT / spec.rstrip("/")).exists(), f"{spec} in packaging/presenter_paths.txt does not exist"


def test_what_changes_with_every_release_is_not_listed():
    specs = changed.pathspecs(PATHS_FILE.read_text(encoding="utf-8"))
    for name in ("src/slidemage/version.py", "src/slidemage/CHANGELOG.md"):
        assert not any(_matches(spec, name) for spec in specs), name


def test_pathspecs_skip_comments_and_blank_lines():
    assert changed.pathspecs("# a\n\n  src/x.py \n#b\ndir/\n") == ["src/x.py", "dir/"]


@pytest.mark.skipif(shutil.which("git") is None, reason="needs git")
def test_changed_since_the_previous_tag(tmp_path, monkeypatch):
    def git(*args):
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.org", "-c", "commit.gpgsign=false",
                        *args], cwd=tmp_path, check=True, capture_output=True)

    def commit(name, text, message):
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        git("add", "-A")
        git("commit", "-m", message)

    git("init", "-q")
    monkeypatch.chdir(tmp_path)
    specs = ["src/presenter/", "pyproject.toml"]
    commit("src/presenter/a.py", "1", "first")
    assert changed.previous_tag() is None and changed.changed_since(None, specs)      # no previous tag: attach
    git("tag", "v1")
    commit("src/other.py", "1", "unrelated")
    commit("notes/CHANGELOG.md", "1", "unrelated too")
    assert changed.previous_tag("HEAD") == "v1"
    assert not changed.changed_since("v1", specs)
    commit("src/presenter/b.py", "1", "a new presenter module")
    assert changed.changed_since("v1", specs)
    git("tag", "v2")
    commit("pyproject.toml", "x", "dependencies")
    assert changed.previous_tag() == "v2" and changed.changed_since("v2", specs)
    assert changed.changed_since("no-such-tag", specs)                            # git cannot tell: attach
