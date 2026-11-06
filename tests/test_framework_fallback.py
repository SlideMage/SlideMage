# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""v0.14.19: a project with no framework of its own to find compiles against the one SlideMage bundles.

The case that prompted it: a project set up next to a SlideMage checkout (../SlideMage/latex) whose checkout moved
away. The background previews said "Template slidemage not found" and the compiles had no framework.
"""
from pathlib import Path

from slidemage import compiler, project, slide_snapshot

BUNDLED = Path(__file__).resolve().parents[1] / "latex"


def _project(tmp_path: Path) -> project.ProjectContext:
    root = tmp_path / "Lectures" / "Slidemaster"
    project.init_project(root, copy_example=False)
    return project.ProjectContext(root)


def _framework(folder: Path) -> Path:
    folder.mkdir(parents=True)
    (folder / "SlideMage_base.tex").write_text("% a framework\n", encoding="utf-8")
    (folder / "SlideMage_template_slidemage.tex").write_text("% the template\n", encoding="utf-8")
    return folder


def test_with_no_framework_beside_the_project_the_bundled_one_is_used(tmp_path, monkeypatch):
    monkeypatch.delenv(project.LATEX_ENV_VAR, raising=False)
    ctx = _project(tmp_path)
    (tmp_path / "Lectures" / "SlideMage").mkdir()          # the moved checkout left an empty folder behind
    assert project.fallback_framework_dir(ctx.root) == BUNDLED
    assert slide_snapshot.framework_dirs(ctx.root) == [BUNDLED]
    assert "slidemage" in slide_snapshot.available_templates(ctx.root)
    assert compiler.build_env(ctx)[project.LATEX_ENV_VAR] == str(BUNDLED)


def test_a_framework_beside_the_project_still_wins(tmp_path, monkeypatch):
    monkeypatch.delenv(project.LATEX_ENV_VAR, raising=False)
    ctx = _project(tmp_path)
    own = _framework(tmp_path / "Lectures" / "SlideMage" / "latex")
    assert project.fallback_framework_dir(ctx.root) is None
    assert slide_snapshot.framework_dirs(ctx.root) == [own]
    assert project.LATEX_ENV_VAR not in compiler.build_env(ctx)


def test_the_environment_variable_still_wins(tmp_path, monkeypatch):
    ctx = _project(tmp_path)
    elsewhere = _framework(tmp_path / "elsewhere" / "latex")
    monkeypatch.setenv(project.LATEX_ENV_VAR, str(elsewhere))
    assert project.fallback_framework_dir(ctx.root) is None
    assert slide_snapshot.framework_dirs(ctx.root) == [elsewhere]
    assert compiler.build_env(ctx)[project.LATEX_ENV_VAR] == str(elsewhere)


def test_without_a_bundled_framework_nothing_is_invented(tmp_path, monkeypatch):
    monkeypatch.delenv(project.LATEX_ENV_VAR, raising=False)
    monkeypatch.setattr(project, "template_dir", lambda name: None)
    ctx = _project(tmp_path)
    assert project.fallback_framework_dir(ctx.root) is None
    assert slide_snapshot.framework_dirs(ctx.root) == []
    assert project.LATEX_ENV_VAR not in compiler.build_env(ctx)
