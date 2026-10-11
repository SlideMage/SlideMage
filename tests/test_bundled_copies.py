"""bundled_copies: a project's copies of the framework and the manual follow
the versions this SlideMage carries -- updated where unchanged in the project,
kept where the user changed them, with a backup of everything replaced."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from slidemage import alt_images, bundled_copies, project
from slidemage.bundled_copies import FRAMEWORK, MANUAL

NOW = datetime(2026, 10, 5, 12, 0, 0)


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


@pytest.fixture
def bundle(tmp_path):
    """A bundled framework and example project (manual), like the exe's."""
    latex = tmp_path / "bundle" / "latex"
    write(latex / "Slidemaster_preamble_base.tex", "base v1\n")
    write(latex / "Slidemaster_preamble_slidemage.tex", "template v1\n")
    example = tmp_path / "bundle" / "example"
    write(example / "decks" / "slidemage-manual.tex", "manual deck v1\n")
    write(example / "slides" / "1aa-EN-One-current.tex", "slide one v1\n")
    write(example / "slides" / "1bb-EN-Two-current.tex", "slide two v1\n")
    write(example / "snippets" / "1aa-1.tex", "code v1\n")
    write(example / "media" / "shot.png", "png v1")
    write(example / "media" / "alt-text.json", json.dumps({"version": 1, "images": {
        "media/shot.png": {"role": "informative", "status": "auto", "short": "shot v1"}}}))
    write(example / "slide_ids.csv", '"id"\r\n"1aa"\r\n"1bb"\r\n')
    write(example / "Slidemaster_preamble_uni-graz.tex", "graz\n")
    return latex, example


def make_project(tmp_path, bundle):
    """A project created from the bundle, with its baseline recorded."""
    latex, example = bundle
    root = tmp_path / "work" / "project"
    import shutil
    shutil.copytree(example, root)
    shutil.copytree(latex, root.parent / "latex")
    bundled_copies.record_copies(root, "v5.19.0", framework_dir=root.parent / "latex",
                                 framework_source=latex, example_source=example)
    return root


def plan(root, bundle):
    latex, example = bundle
    return {p.name: p for p in bundled_copies.plan_updates(
        root, latex_source=latex, example_source=example)}


def use_store(monkeypatch, root: Path) -> None:
    """Point the image-description store -- the JSON and the compile-time CSV
    it regenerates -- at `root`'s media folder, never the real project's."""
    monkeypatch.setattr(alt_images, "STORE_PATH", root / "media" / "alt-text.json")
    monkeypatch.setattr(alt_images, "_COMPILE_CSV_PATH", root / "media" / "alt-text.csv")


@pytest.fixture(autouse=True)
def isolated_alt_store(tmp_path, monkeypatch):
    use_store(monkeypatch, tmp_path / "work" / "project")


def test_nothing_to_do_right_after_the_copy(tmp_path, bundle):
    root = make_project(tmp_path, bundle)
    assert plan(root, bundle) == {}
    manifest = bundled_copies.read_manifest(root)
    assert manifest[FRAMEWORK]["dir"] == "../latex"
    assert "decks/slidemage-manual.tex" in manifest[MANUAL]["files"]
    assert "media/alt-text.json" not in manifest[MANUAL]["files"]


def test_update_add_remove_and_keep(tmp_path, bundle):
    latex, example = bundle
    root = make_project(tmp_path, bundle)
    # upstream: one slide changed, one new, one dropped; framework changed
    write(example / "slides" / "1aa-EN-One-current.tex", "slide one v2\n")
    write(example / "slides" / "1cc-EN-Three-current.tex", "slide three v2\n")
    (example / "slides" / "1bb-EN-Two-current.tex").unlink()
    write(latex / "Slidemaster_preamble_base.tex", "base v2\n")
    # the user changed the snippet, which also changed upstream
    write(root / "snippets" / "1aa-1.tex", "my own code\n")
    write(example / "snippets" / "1aa-1.tex", "code v2\n")

    parts = plan(root, bundle)
    manual, framework = parts[MANUAL], parts[FRAMEWORK]
    assert manual.update == ["slides/1aa-EN-One-current.tex"]
    assert manual.add == ["slides/1cc-EN-Three-current.tex"]
    assert manual.remove == ["slides/1bb-EN-Two-current.tex"]
    assert manual.kept == ["snippets/1aa-1.tex"]
    assert framework.update == ["Slidemaster_preamble_base.tex"] and not framework.adopted

    backup = bundled_copies.apply_update(root, manual, "v5.20.0", now=NOW)
    bundled_copies.apply_update(root, framework, "v5.20.0", now=NOW)
    assert (root / "slides" / "1aa-EN-One-current.tex").read_text() == "slide one v2\n"
    assert (root / "slides" / "1cc-EN-Three-current.tex").is_file()
    assert not (root / "slides" / "1bb-EN-Two-current.tex").exists()
    assert (root / "snippets" / "1aa-1.tex").read_text() == "my own code\n"     # kept
    assert (backup / "slides" / "1aa-EN-One-current.tex").read_text() == "slide one v1\n"
    assert (backup / "slides" / "1bb-EN-Two-current.tex").is_file()
    assert (root.parent / "latex" / "Slidemaster_preamble_base.tex").read_text() == "base v2\n"
    # afterwards nothing is pending; the user's snippet stays theirs
    assert plan(root, bundle) == {}


def test_only_the_included_in_decks_line_is_not_a_user_edit(tmp_path, bundle):
    """SlideMage itself rewrites each slide's '%% Included in decks:' line (a
    project with its own deck lists it too); that must not make an otherwise
    untouched slide count as changed by the user."""
    latex, example = bundle
    one = "1aa-EN-One-current.tex"
    write(example / "slides" / one, "%% Included in decks: slidemage-manual\n%%\n\nslide one v1\n")
    root = make_project(tmp_path, bundle)
    write(root / "slides" / one,
          "%% Included in decks: slidemage-manual, my-course-deck\n%%\n\nslide one v1\n")
    assert plan(root, bundle) == {}                       # nothing differs but the header

    write(example / "slides" / one, "%% Included in decks: slidemage-manual\n%%\n\nslide one v2\n")
    manual = plan(root, bundle)[MANUAL]
    assert manual.update == [f"slides/{one}"] and manual.kept == []

    bundled_copies.apply_update(root, manual, "v5.26.1", now=NOW)
    text = (root / "slides" / one).read_text()
    assert "slide one v2" in text
    assert text.startswith("%% Included in decks: slidemage-manual, my-course-deck\n")  # own line kept
    assert plan(root, bundle) == {}


def test_a_real_edit_next_to_a_header_change_is_still_kept(tmp_path, bundle):
    latex, example = bundle
    one = "1aa-EN-One-current.tex"
    write(example / "slides" / one, "%% Included in decks: slidemage-manual\n%%\n\nslide one v1\n")
    root = make_project(tmp_path, bundle)
    write(root / "slides" / one,
          "%% Included in decks: slidemage-manual, my-course-deck\n%%\n\nmy own wording\n")
    write(example / "slides" / one, "%% Included in decks: slidemage-manual\n%%\n\nslide one v2\n")
    write(example / "slides" / "1bb-EN-Two-current.tex", "slide two v2\n")  # keeps the part pending
    manual = plan(root, bundle)[MANUAL]
    assert manual.kept == [f"slides/{one}"] and manual.update == ["slides/1bb-EN-Two-current.tex"]


def test_a_file_the_user_deleted_stays_deleted(tmp_path, bundle):
    _, example = bundle
    root = make_project(tmp_path, bundle)
    (root / "slides" / "1bb-EN-Two-current.tex").unlink()
    write(example / "slides" / "1bb-EN-Two-current.tex", "slide two v2\n")
    assert plan(root, bundle) == {}


def test_framework_adoption_and_git_checkouts(tmp_path, bundle):
    latex, example = bundle
    root = tmp_path / "old" / "project"
    write(root / "slide_ids.csv", '"id"\r\n')
    write(root.parent / "latex" / "Slidemaster_preamble_base.tex", "base v0\n")
    parts = plan(root, bundle)
    framework = parts[FRAMEWORK]
    assert framework.adopted
    assert framework.update == ["Slidemaster_preamble_base.tex"]
    assert framework.add == ["Slidemaster_preamble_slidemage.tex"]
    # a framework folder inside a git checkout is never touched
    (root.parent / ".git").mkdir()
    assert FRAMEWORK not in plan(root, bundle)


def test_manual_offered_to_a_project_without_it(tmp_path, bundle, monkeypatch):
    _, example = bundle
    root = tmp_path / "mine" / "project"
    use_store(monkeypatch, root)
    write(root / "slide_ids.csv", '"id"\r\n"abc"\r\n')
    write(root / "media" / "shot.png", "my own png")            # same name, own content
    manual = plan(root, bundle)[MANUAL]
    assert manual.new_install and manual.adopted
    assert "media/shot.png" in manual.kept and "media/shot.png" not in manual.add
    bundled_copies.apply_update(root, manual, "v5.19.0", now=NOW)
    assert (root / "decks" / "slidemage-manual.tex").is_file()
    assert (root / "media" / "shot.png").read_text() == "my own png"   # never overwritten
    ids = (root / "slide_ids.csv").read_text().split()
    assert ids == ['"id"', '"abc"', '"1aa"', '"1bb"']
    store = json.loads((root / "media" / "alt-text.json").read_text(encoding="utf-8"))
    assert store["images"]["media/shot.png"]["short"] == "shot v1"


def test_image_descriptions_follow_unless_reviewed(tmp_path, bundle):
    _, example = bundle
    root = make_project(tmp_path, bundle)
    write(example / "media" / "shot.png", "png v2")
    write(example / "media" / "alt-text.json", json.dumps({"version": 1, "images": {
        "media/shot.png": {"role": "informative", "status": "auto", "short": "shot v2"}}}))
    bundled_copies.apply_update(root, plan(root, bundle)[MANUAL], "v5.20.0", now=NOW)
    assert alt_images.load_store()["media/shot.png"].short == "shot v2"
    # a reviewed description is the user's: kept
    def review(entries):
        entries["media/shot.png"].status = alt_images.STATUS_REVIEWED
        entries["media/shot.png"].short = "mine"
        return True
    alt_images.update_store(review)
    write(example / "media" / "shot.png", "png v3")
    write(example / "media" / "alt-text.json", json.dumps({"version": 1, "images": {
        "media/shot.png": {"role": "informative", "status": "auto", "short": "shot v3"}}}))
    bundled_copies.apply_update(root, plan(root, bundle)[MANUAL], "v5.21.0", now=NOW)
    assert alt_images.load_store()["media/shot.png"].short == "mine"


def test_dismissed_for_one_version(tmp_path, bundle):
    root = make_project(tmp_path, bundle)
    bundled_copies.dismiss(root, "v5.20.0")
    assert bundled_copies.is_dismissed(root, "v5.20.0")
    assert not bundled_copies.is_dismissed(root, "v5.21.0")


def test_never_plans_against_the_bundle_itself(tmp_path, bundle):
    latex, example = bundle
    assert bundled_copies.plan_updates(example, latex_source=latex, example_source=example) == []


def test_init_project_records_the_baseline(tmp_path):
    target = tmp_path / "new" / "project"
    project.init_project(target, copy_example=True)
    manifest = bundled_copies.read_manifest(target)
    assert manifest[FRAMEWORK]["dir"] == "../latex"
    assert "decks/slidemage-manual.tex" in manifest[MANUAL]["files"]
    assert bundled_copies.plan_updates(
        target, latex_source=project.template_dir("latex"),
        example_source=project.template_dir("example")) == []


# -- the dialog (MaintenanceMixin.check_bundled_copies) ----------------

def _run_dialog(monkeypatch, root, bundle, choose: str):
    from PySide6.QtWidgets import QApplication, QMessageBox, QWidget

    from slidemage.ui.workspace import maintenance

    QApplication.instance() or QApplication([])
    latex, example = bundle
    monkeypatch.setattr(maintenance, "PROJECT_ROOT", root)
    monkeypatch.setattr(project, "template_dir", lambda name: {"latex": latex, "example": example}[name])
    seen = {}

    def fake_exec(box):
        seen["text"] = box.text() + "\n" + box.informativeText()
        seen["buttons"] = [b.text() for b in box.buttons()]
        seen["chosen"] = next(b for b in box.buttons() if b.text() == choose)
        return 0
    monkeypatch.setattr(QMessageBox, "exec", fake_exec)
    monkeypatch.setattr(QMessageBox, "clickedButton", lambda box: seen["chosen"])

    class Window(maintenance.MaintenanceMixin, QWidget):
        logged: list = []
        reloaded = 0

        def log(self, line):
            self.logged.append(line)

        def reload_decks(self):
            Window.reloaded += 1

    window = Window()
    window.check_bundled_copies()
    return seen, window


def test_dialog_adds_the_manual(tmp_path, bundle, monkeypatch):
    root = tmp_path / "mine" / "project"
    write(root / "slide_ids.csv", '"id"\r\n')
    use_store(monkeypatch, root)
    seen, window = _run_dialog(monkeypatch, root, bundle, "Add the manual")
    assert "Add it to this project?" in seen["text"]
    assert (root / "decks" / "slidemage-manual.tex").is_file()
    assert window.reloaded == 1


def test_dialog_dont_ask_again(tmp_path, bundle, monkeypatch):
    root = make_project(tmp_path, bundle)
    write(bundle[1] / "slides" / "1aa-EN-One-current.tex", "slide one v2\n")
    seen, _ = _run_dialog(monkeypatch, root, bundle, "Don't ask again for this version")
    assert "1 changed" in seen["text"]
    assert (root / "slides" / "1aa-EN-One-current.tex").read_text() == "slide one v1\n"
    from slidemage import version
    assert bundled_copies.is_dismissed(root, version.VERSION_NUMBER)


def test_hidden_folders_are_never_part_of_a_copy(tmp_path, bundle):
    _, example = bundle
    write(example / "slides" / ".backups" / "abc-EN-Test-current.tex" / "20261005-0800.tex", "history")
    write(example / ".build" / "x.aux", "aux")
    files = bundled_copies.manual_files(example)
    assert not any(part.startswith(".") for f in files for part in Path(f).parts)
