# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Bundled framework and manual updates preserve project edits and back up replacements."""
from __future__ import annotations

import json
import shutil
import threading
from datetime import datetime
from functools import partial
from pathlib import Path

import pytest

from conftest import wait_until
from conftest import write_test_file as write

from slidemage import alt_images, bundled_copies, project
from slidemage.bundled_copies import FRAMEWORK, MANUAL
from slidemage.project import ProjectContext

NOW = datetime(2026, 10, 5, 12, 0, 0)
write = partial(write, newline=None)


@pytest.fixture
def bundle(tmp_path):
    latex = tmp_path / "bundle" / "latex"
    write(latex / "SlideMage_base.tex", "base v1\n")
    write(latex / "SlideMage_template_slidemage.tex", "template v1\n")
    example = tmp_path / "bundle" / "example"
    write(example / "decks" / "slidemage-manual.tex", "manual deck v1\n")
    write(example / "slides" / "1aa-EN-One-current.tex", "slide one v1\n")
    write(example / "slides" / "1bb-EN-Two-current.tex", "slide two v1\n")
    write(example / "snippets" / "1aa-1.tex", "code v1\n")
    write(example / "media" / "shot.png", "png v1")
    write(example / "media" / "alt-text.json", json.dumps({"version": 1, "images": {
        "media/shot.png": {"role": "informative", "status": "auto", "short": "shot v1"}}}))
    write(example / "slide_ids.csv", '"id"\r\n"1aa"\r\n"1bb"\r\n')
    write(example / "SlideMage_template_acme.tex", "graz\n")
    return latex, example


def make_project(tmp_path, bundle):
    latex, example = bundle
    root = tmp_path / "work" / "project"
    shutil.copytree(example, root)
    shutil.copytree(latex, root.parent / "latex")
    bundled_copies.record_copies(root, "v0.5.19.0", framework_dir=root.parent / "latex",
                                 framework_source=latex, example_source=example)
    return root


def plan(root, bundle):
    latex, example = bundle
    return {p.name: p for p in bundled_copies.plan_updates(
        root, latex_source=latex, example_source=example)}


def test_updates_back_up_replaced_files_and_keep_user_edits(tmp_path, bundle):
    latex, example = bundle
    # v10.1.0: bundled Gotham files were removed. Preserve the user's edited copy.
    obsolete, edited = "gotham.dtx", "beamerouterthemegotham.sty"
    for name in (obsolete, edited):
        write(latex / name, "gotham v1")
    root = make_project(tmp_path, bundle)
    assert plan(root, bundle) == {}
    for name in (obsolete, edited):
        (latex / name).unlink()
    write(latex / "beamerthemeSlideMage.sty", "theme")
    framework_copy = root.parent / "latex"
    write(framework_copy / edited, "my edit")
    one, two, three = (f"slides/1{id}-EN-{title}-current.tex"
                       for id, title in (("aa", "One"), ("bb", "Two"), ("cc", "Three")))
    snippet = "snippets/1aa-1.tex"
    write(example / one, "slide one v2\n")
    write(example / three, "slide three v2\n")
    (example / two).unlink()
    write(example / "slides" / ".backups" / "history.tex", "history")
    write(example / ".build" / "x.aux", "aux")
    write(latex / "SlideMage_base.tex", "base v2\n")
    write(root / snippet, "my own code\n")
    write(example / snippet, "code v2\n")

    parts = plan(root, bundle)
    manual, framework = parts[MANUAL], parts[FRAMEWORK]
    assert (manual.update, manual.add, manual.remove, manual.kept) == ([one], [three], [two], [snippet])
    assert framework.update == ["SlideMage_base.tex"] and not framework.adopted
    assert (framework.add, framework.remove, framework.kept) == (["beamerthemeSlideMage.sty"], [obsolete], [edited])

    ctx, steps = ProjectContext.at(root), []
    backup = bundled_copies.apply_update(ctx, manual, "v0.5.20.0", now=NOW, on_progress=steps.append)
    framework_backup = bundled_copies.apply_update(ctx, framework, "v0.5.20.0", now=NOW)
    assert len(steps) == 5 and steps[-1].fraction == 1
    assert (root / one).read_text() == "slide one v2\n" and (root / three).is_file()
    assert not (root / two).exists() and (root / snippet).read_text() == "my own code\n"
    assert (backup / one).read_text() == "slide one v1\n" and (backup / two).is_file()
    assert (framework_copy / "SlideMage_base.tex").read_text() == "base v2\n"
    assert (framework_copy / "beamerthemeSlideMage.sty").read_text() == "theme"
    assert not (framework_copy / obsolete).exists() and (framework_backup / obsolete).is_file()
    assert (framework_copy / edited).read_text() == "my edit"
    assert "media/alt-text.json" not in bundled_copies.read_manifest(root)[MANUAL]["files"]
    assert plan(root, bundle) == {}


def test_header_regeneration_allows_updates_and_preserves_user_edits(tmp_path, bundle):
    # v5.27.0: generated headers blocked updates of 38 manual slides.
    _, example = bundle
    one, two = "slides/1aa-EN-One-current.tex", "slides/1bb-EN-Two-current.tex"
    bundled_header = "%% Included in decks: slidemage-manual\n%%\n\n"
    local_header = bundled_header.replace("slidemage-manual", "slidemage-manual, my-course-deck")
    for name in (one, two):
        write(example / name, bundled_header + "original\n")
    root = make_project(tmp_path, bundle)
    write(root / one, local_header + "original\n")
    assert plan(root, bundle) == {}
    write(root / two, local_header + "my own wording\n")
    for name in (one, two):
        write(example / name, bundled_header + "upstream\n")
    manual = plan(root, bundle)[MANUAL]
    assert manual.update == [one] and manual.kept == [two]
    bundled_copies.apply_update(ProjectContext.at(root), manual, "v0.5.26.1", now=NOW)
    assert (root / one).read_text() == local_header + "upstream\n"
    assert (root / two).read_text() == local_header + "my own wording\n"
    assert plan(root, bundle) == {}


def test_a_file_the_user_deleted_stays_deleted(tmp_path, bundle):
    _, example = bundle
    root = make_project(tmp_path, bundle)
    (root / "slides" / "1bb-EN-Two-current.tex").unlink()
    write(example / "slides" / "1bb-EN-Two-current.tex", "slide two v2\n")
    assert plan(root, bundle) == {}


def test_framework_adoption_and_git_checkouts(tmp_path, bundle, monkeypatch):
    # Only this test's checkout counts, even when a runner puts tmp_path in a checkout.
    exists = Path.exists

    def isolated_exists(path):
        if path.name == ".git" and not path.is_relative_to(tmp_path):
            return False
        return exists(path)

    monkeypatch.setattr(Path, "exists", isolated_exists)
    root = tmp_path / "old" / "project"
    write(root / "slide_ids.csv", '"id"\r\n')
    write(root.parent / "latex" / "SlideMage_base.tex", "base v0\n")
    parts = plan(root, bundle)
    framework = parts[FRAMEWORK]
    assert framework.adopted
    assert framework.update == ["SlideMage_base.tex"]
    assert framework.add == ["SlideMage_template_slidemage.tex"]
    # a framework folder inside a git checkout is never touched
    (root.parent / ".git").mkdir()
    assert FRAMEWORK not in plan(root, bundle)


def test_manual_dialog_adds_the_manual_without_overwriting_project_files(tmp_path, bundle, monkeypatch, qapp):
    root = tmp_path / "mine" / "project"
    write(root / "slide_ids.csv", '"id"\r\n"abc"\r\n')
    write(root / "media" / "shot.png", "my own png")            # same name, own content
    manual = plan(root, bundle)[MANUAL]
    assert manual.new_install and manual.adopted
    assert "media/shot.png" in manual.kept and "media/shot.png" not in manual.add
    window = _run_dialog(monkeypatch, root, bundle, "Add the manual")
    wait_until(lambda: window.reloaded)
    assert window.reloaded == 1
    assert (root / "decks" / "slidemage-manual.tex").is_file()
    assert (root / "media" / "shot.png").read_text() == "my own png"   # never overwritten
    ids = (root / "slide_ids.csv").read_text().split()
    assert ids == ['"id"', '"abc"', '"1aa"', '"1bb"']
    store = json.loads((root / "media" / "alt-text.json").read_text(encoding="utf-8"))
    assert store["images"]["media/shot.png"]["text"]["en"]["short"] == "shot v1"


def test_image_descriptions_follow_unless_reviewed(tmp_path, bundle):
    _, example = bundle
    root = make_project(tmp_path, bundle)
    ctx = ProjectContext.at(root)

    def update_shot(version):
        write(example / "media" / "shot.png", f"png v{version}")
        write(example / "media" / "alt-text.json", json.dumps({"version": 1, "images": {
            "media/shot.png": {"role": "informative", "status": "auto", "short": f"shot v{version}"}}}))
        bundled_copies.apply_update(ctx, plan(root, bundle)[MANUAL], f"v5.20.{version}", now=NOW)
        return alt_images.load_store(ctx)["media/shot.png"].short

    assert update_shot(2) == "shot v2"

    def review(entries):
        entries["media/shot.png"].status = alt_images.STATUS_REVIEWED
        entries["media/shot.png"].short = "mine"
        return True
    alt_images.update_store(ctx, review)
    assert update_shot(3) == "mine"


def test_never_plans_against_the_bundle_itself(bundle):
    latex, example = bundle
    assert bundled_copies.plan_updates(example, latex_source=latex, example_source=example) == []


@pytest.mark.parametrize("existing_latex", [False, True])
def test_init_project_seeds_example_and_records_baseline(tmp_path, existing_latex):
    # 2026-09-23: the first-run picker could not create a compilable project.
    target = tmp_path / "new_project"
    if existing_latex:
        (tmp_path / "latex").mkdir()
        (tmp_path / "latex" / "sentinel.txt").write_text("do not touch")
    assert project.has_example_template()
    project.init_project(target, copy_example=True)
    assert project.is_project(target)
    assert (target / "decks" / "slidemage-manual.tex").is_file()
    assert not (target / "decks" / "slidemage-manual.pdf").exists() and not (target / ".build").exists()
    assert (target / "media" / "alt-text.json").is_file()
    manifest = bundled_copies.read_manifest(target)
    assert "decks/slidemage-manual.tex" in manifest[MANUAL]["files"]
    if existing_latex:
        assert (tmp_path / "latex" / "sentinel.txt").read_text() == "do not touch"
    else:
        assert manifest[FRAMEWORK]["dir"] == "../latex"
    assert bundled_copies.plan_updates(
        target, latex_source=project.template_dir("latex"),
        example_source=project.template_dir("example")) == []


def _run_dialog(monkeypatch, root, bundle, choose: str):
    from PySide6.QtWidgets import QMessageBox, QWidget

    from slidemage.ui.workspace import maintenance

    latex, example = bundle
    monkeypatch.setattr(project, "template_dir", lambda name: {"latex": latex, "example": example}[name])
    seen, threads = [], []
    compare = maintenance.bundled_parts

    def compare_on_worker(window):
        threads.append(threading.current_thread())
        return compare(window)

    monkeypatch.setattr(maintenance, "bundled_parts", compare_on_worker)

    def fake_exec(box):
        seen.append(next(b for b in box.buttons() if b.text() == choose))
        return 0
    monkeypatch.setattr(QMessageBox, "exec", fake_exec)
    monkeypatch.setattr(QMessageBox, "clickedButton", lambda box: seen[0])

    class Window(QWidget):
        project = ProjectContext.at(root)
        reloaded = 0

        def log(self, line):
            pass

        def reload_decks(self):
            self.reloaded += 1

    window = Window()
    maintenance.check_bundled_copies(window)
    wait_until(lambda: seen)
    assert len(threads) == 1 and threads[0] is not threading.main_thread()
    return window


def test_dialog_dont_ask_again(tmp_path, bundle, monkeypatch, qapp):
    from slidemage import version

    monkeypatch.setattr(version, "VERSION_NUMBER", "v0.5.20.0")
    root = make_project(tmp_path, bundle)
    write(bundle[1] / "slides" / "1aa-EN-One-current.tex", "slide one v2\n")
    window = _run_dialog(monkeypatch, root, bundle, "Don't ask again for this version")
    assert window.reloaded == 0
    assert (root / "slides" / "1aa-EN-One-current.tex").read_text() == "slide one v1\n"
    assert bundled_copies.is_dismissed(root, "v0.5.20.0")
    assert not bundled_copies.is_dismissed(root, "v0.5.21.0")


def test_the_shipped_framework_has_the_theme_and_no_gotham_file():
    names = bundled_copies.framework_files(Path(__file__).resolve().parents[1] / "latex")
    assert "beamerthemeSlideMage.sty" in names and "SlideMage_setup.tex" in names
    assert {"SlideMage_layout_fira.tex", "SlideMage_layout_lmsans.tex", "SlideMage_bibliography_default.tex"} <= set(names)
    assert not [n for n in names if "gotham" in n.lower()]
