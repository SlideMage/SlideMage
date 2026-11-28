# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""tex_paths: TeX and Perl folders missing from PATH are appended, existing ones never reordered."""
import os
import sys

import pytest

from slidemage import tex_paths


@pytest.fixture
def folders(tmp_path):
    made = {name: tmp_path / name for name in ("miktex", "perl", "registry", "already")}
    for folder in made.values():
        folder.mkdir()
    return made


def _candidates(monkeypatch, registry, known):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(tex_paths, "_windows_registry_path", lambda: [str(p) for p in registry])
    monkeypatch.setattr(tex_paths, "_windows_known_dirs", lambda: list(known))


def test_missing_folders_are_appended_after_the_current_path(monkeypatch, folders):
    _candidates(monkeypatch, [folders["registry"], folders["already"]], [folders["miktex"], folders["perl"]])
    monkeypatch.setenv("PATH", str(folders["already"]))
    added = tex_paths.extend_path()
    assert added == [str(folders["registry"]), str(folders["miktex"]), str(folders["perl"])]
    assert os.environ["PATH"].split(os.pathsep) == [str(folders["already"]), *added]


def test_folders_that_do_not_exist_or_repeat_are_left_out(monkeypatch, folders, tmp_path):
    gone = tmp_path / "gone"
    _candidates(monkeypatch, [folders["miktex"], gone], [folders["miktex"], gone])
    assert tex_paths.missing_dirs("") == [str(folders["miktex"])]


def test_nothing_to_add_leaves_path_unchanged(monkeypatch, folders):
    _candidates(monkeypatch, [], [folders["already"]])
    monkeypatch.setenv("PATH", str(folders["already"]))
    assert tex_paths.extend_path() == []
    assert os.environ["PATH"] == str(folders["already"])


def test_newest_texlive_year_first(tmp_path):
    for name in ("2024", "2026", "2025", "tlpkg"):
        (tmp_path / name).mkdir()
    assert [p.name for p in tex_paths._newest_first(tmp_path)] == ["2026", "2025", "2024"]


def test_linux_upstream_texlive_only_without_lualatex(monkeypatch, tmp_path):
    bin_dir = tmp_path / "2026" / "bin" / "x86_64-linux"
    bin_dir.mkdir(parents=True)
    monkeypatch.setattr(tex_paths, "_newest_first", lambda base: [tmp_path / "2026"])
    monkeypatch.setattr(tex_paths.shutil, "which", lambda name: None)
    assert tex_paths._linux_known_dirs() == [bin_dir]
    monkeypatch.setattr(tex_paths.shutil, "which", lambda name: "/usr/bin/lualatex")
    assert tex_paths._linux_known_dirs() == []
