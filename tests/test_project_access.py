# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""project_access: which of the project's folders refuse new files, and the window's notice about it."""
from __future__ import annotations

import tempfile
from types import SimpleNamespace

from slidemage import project_access
from slidemage.project import ProjectContext


def _refusing(monkeypatch, *folders):
    real = tempfile.mkstemp

    def mkstemp(*args, dir=None, **kwargs):
        if dir in folders:
            raise OSError(22, "Invalid argument")
        return real(*args, dir=dir, **kwargs)

    monkeypatch.setattr(project_access.tempfile, "mkstemp", mkstemp)


def test_folders_that_take_a_file_are_no_problem_and_the_probe_leaves_nothing(tmp_path):
    ctx = ProjectContext.at(tmp_path)
    for folder in project_access.folders(ctx):
        folder.mkdir(parents=True)
    assert project_access.problems(ctx) == []
    assert not any(path.name.startswith(project_access.PROBE_PREFIX) for path in tmp_path.rglob("*"))


def test_a_folder_not_made_yet_is_no_problem_but_a_project_folder_that_has_gone_is(tmp_path):
    assert project_access.problems(ProjectContext.at(tmp_path)) == []
    gone = ProjectContext.at(tmp_path / "gone")
    assert [folder for folder, _ in project_access.problems(gone)] == [gone.root]


def test_a_refusing_folder_is_named_with_the_sync_client_hint(tmp_path, monkeypatch):
    ctx = ProjectContext.at(tmp_path)
    for folder in project_access.folders(ctx):
        folder.mkdir(parents=True)
    _refusing(monkeypatch, ctx.settings_dir, ctx.build_dir)
    found = project_access.problems(ctx)
    assert [folder for folder, _ in found] == [ctx.settings_dir, ctx.build_dir]
    text = project_access.message(ctx, found)
    assert ".slidemage/, .build/" in text and "Invalid argument" in text and "sync client" in text


def test_the_window_says_so_once_per_outage(tmp_path):
    from slidemage.ui.workspace import maintenance

    ctx = ProjectContext.at(tmp_path)
    toasts, lines = [], []
    window = SimpleNamespace(project=ctx, project_access_problems=[], log=lines.append,
                             toast=SimpleNamespace(show_message=lambda text, **kw: toasts.append((text, kw))))
    refused = [(ctx.settings_dir, "Invalid argument")]
    maintenance.on_access_checked(window, refused)
    maintenance.on_access_checked(window, refused)                     # still refused: nothing new to say
    assert len(toasts) == 1 and toasts[0][1].get("error") and ".slidemage/" in toasts[0][0]
    maintenance.on_access_checked(window, [])
    assert len(toasts) == 2 and "again" in toasts[1][0]
    maintenance.on_access_checked(window, [])
    assert len(toasts) == 2 and len(lines) == 2
