# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Framework discovery after a neighboring checkout is removed."""
from pathlib import Path

from slidemage import compiler, project, slide_templates

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


def test_bundled_framework_is_used_if_available(tmp_path, monkeypatch):
    monkeypatch.delenv(project.LATEX_ENV_VAR, raising=False)
    ctx = _project(tmp_path)
    (tmp_path / "Lectures" / "SlideMage").mkdir()          # the moved checkout left an empty folder behind
    assert project.fallback_framework_dir(ctx.root) == BUNDLED
    assert slide_templates.framework_dirs(ctx.root) == [BUNDLED]
    assert "slidemage" in slide_templates.available_templates(ctx.root)
    assert compiler.build_env(ctx)[project.LATEX_ENV_VAR] == str(BUNDLED)

    monkeypatch.setattr(project, "template_dir", lambda name: None)
    assert project.fallback_framework_dir(ctx.root) is None
    assert slide_templates.framework_dirs(ctx.root) == []
    assert project.LATEX_ENV_VAR not in compiler.build_env(ctx)


def test_local_and_environment_frameworks_take_precedence(tmp_path, monkeypatch):
    monkeypatch.delenv(project.LATEX_ENV_VAR, raising=False)
    ctx = _project(tmp_path)
    own = _framework(tmp_path / "Lectures" / "SlideMage" / "latex")
    assert project.fallback_framework_dir(ctx.root) is None
    assert slide_templates.framework_dirs(ctx.root) == [own]
    assert project.LATEX_ENV_VAR not in compiler.build_env(ctx)

    elsewhere = _framework(tmp_path / "elsewhere" / "latex")
    monkeypatch.setenv(project.LATEX_ENV_VAR, str(elsewhere))
    assert project.fallback_framework_dir(ctx.root) is None
    assert slide_templates.framework_dirs(ctx.root) == [elsewhere, own]
    assert compiler.build_env(ctx)[project.LATEX_ENV_VAR] == str(elsewhere)
