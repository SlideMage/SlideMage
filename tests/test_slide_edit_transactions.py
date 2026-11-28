# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Slide rename and delete transactions preserve project data on failure."""
from __future__ import annotations

import json
import shutil
import subprocess

import pytest

from slidemage import ai_review, alt_archive, alt_images, deck_headers, fileio, library_data, processes
from slidemage import slide_edit, slide_rename
from slidemage.alt_images import ImageEntry, ImageText, SlideNotes, SlideUse
from slidemage.project import ProjectContext
from slidemage.slide_edit import SlideEditError

IMAGE = "media/a.png"


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="")


def snapshot(root) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*"))
            if p.is_file() and p.suffix != ".lock" and ".git" not in p.relative_to(root).parts}


@pytest.fixture
def ctx(tmp_path, monkeypatch):
    ctx = ProjectContext.at(tmp_path)
    monkeypatch.setattr(processes, "is_git_repo", lambda _root: False)
    monkeypatch.setattr(deck_headers, "regenerate_headers", lambda _ctx: None)
    monkeypatch.setattr(slide_rename, "regenerate_translation_links", lambda _ctx: None)
    write(tmp_path / "slide_ids.csv", '"id"\r\n"2du"\r\n"k9z"\r\n')
    for stem in ("2du-EN-Old", "k9z-Plain"):
        write(ctx.slides_dir / f"{stem}-current.tex", f"%% {stem}\n\\hyperlink{{2du}}{{back}}\n")
        write(ctx.slides_dir / f"{stem}-v1-0-0.tex", f"%% {stem} v1\n")
    write(ctx.slides_dir / "2du-EN-Old-v1-1-0.tex", "%% v1.1\n")
    write(ctx.slides_dir / "other-EN-Z-current.tex", "\\hyperlink{2du}{go}\n")
    for name in ("d1", "d2", "d3"):
        write(ctx.decks_dir / f"{name}.tex", "\\slide{other-EN-Z}\n\\slide{2du-EN-Old}\n\\slide{k9z-Plain}\n")
    alt_images.save_store(ctx, {IMAGE: ImageEntry(image=IMAGE, texts={"en": ImageText(short="a", long="b")},
                                                  used_on={"2du": SlideUse(takeaway="why")})})
    alt_images.update_slide_notes(ctx, lambda notes: notes.update({"2du": SlideNotes(summary="sum")}) or True)
    library_data.update(ctx, lambda data: (data.pool.add("2du"), data.topics.update({"2du": {"T"}})))
    write(ctx.ai_review_path, json.dumps({"slides/2du-EN-Old-current.tex": {"by": "claude", "kind": "draft"}}))
    return ctx


def fail_nth(monkeypatch, owner, name, n, exc=PermissionError("locked")):
    original, remaining = getattr(owner, name), iter(range(1, n + 1))

    def wrapper(*args, **kwargs):
        if next(remaining, None) == n:
            raise exc
        return original(*args, **kwargs)
    monkeypatch.setattr(owner, name, wrapper)


def assert_unchanged(ctx, before, allow=("slide_ids.csv",)):
    after = snapshot(ctx.root)
    assert {k: v for k, v in after.items() if k not in allow} == {k: v for k, v in before.items() if k not in allow}
    assert not any(k.startswith(".slidemage/trash/") for k in after)


def rename_id(ctx):
    return slide_rename.rename_slide_id(ctx, "2du", "k7m")


def delete(ctx):
    return slide_rename.delete_slide_id(ctx, "2du-EN-Old")


def test_a_rename_updates_files_references_and_the_alt_text_store_once(ctx, monkeypatch):
    write_store, writes = fileio.JsonStore.write, []

    def track_write(store, *args, **kwargs):
        if alt_images.is_store(ctx, store.path):
            writes.append(store.path)
        return write_store(store, *args, **kwargs)

    monkeypatch.setattr(fileio.JsonStore, "write", track_write)
    mapping = rename_id(ctx)
    assert len(writes) == 1
    assert mapping == {"2du-EN-Old": "k7m-EN-Old"}
    assert sorted(p.name for p in ctx.slides_dir.glob("k7m-*")) == [
        "k7m-EN-Old-current.tex", "k7m-EN-Old-v1-0-0.tex", "k7m-EN-Old-v1-1-0.tex"]
    assert not list(ctx.slides_dir.glob("2du-*"))
    assert "\\slide{k7m-EN-Old}" in (ctx.decks_dir / "d3.tex").read_text(encoding="utf-8")
    assert "\\hyperlink{k7m}" in (ctx.slides_dir / "other-EN-Z-current.tex").read_text(encoding="utf-8")
    assert '"k7m"' in ctx.slide_ids_csv.read_text(encoding="utf-8")
    assert "k7m" in alt_images.load_store(ctx)[IMAGE].used_on and "k7m" in alt_images.load_slide_notes(ctx)
    assert library_data.read(ctx).pool == {"k7m"}


@pytest.mark.parametrize("operation, owner, method, nth", [
    pytest.param(rename_id, slide_edit, "move_file", 3, id="rename-move"),
    pytest.param(rename_id, fileio, "write_text_exact", 2, id="rename-deck"),
    pytest.param(rename_id, alt_images, "update_both", 1, id="rename-alt-text"),
    pytest.param(rename_id, library_data, "update", 1, id="rename-library"),
    pytest.param(delete, slide_edit, "move_to_trash", 3, id="delete-move"),
    pytest.param(delete, fileio, "write_text_exact", 2, id="delete-deck"),
    pytest.param(delete, alt_archive, "archive_slides", 1, id="delete-archive"),
    pytest.param(delete, library_data, "update", 1, id="delete-library"),
])
def test_failed_slide_edit_restores_files_and_stores(ctx, monkeypatch, operation, owner, method, nth):
    before = snapshot(ctx.root)
    fail_nth(monkeypatch, owner, method, nth)
    with pytest.raises(SlideEditError, match="Nothing was changed") as error:
        operation(ctx)
    assert error.value.clean and isinstance(error.value, OSError)
    assert_unchanged(ctx, before)
    if method == "move_file":
        assert '"k7m"' in ctx.slide_ids_csv.read_text(encoding="utf-8")


def test_a_deck_that_changed_after_the_plan_stops_the_rename(ctx):
    plan = slide_edit.plan_id_rename(ctx, "2du", "k7m")
    write(ctx.decks_dir / "d2.tex", "\\slide{2du-EN-Old}\n% edited meanwhile\n")
    before = snapshot(ctx.root)
    with pytest.raises(SlideEditError, match="changed on disk"):
        slide_edit.apply(plan)
    assert_unchanged(ctx, before)


def test_review_and_derived_data_failures_warn_without_rolling_back(ctx, monkeypatch):
    monkeypatch.setattr(ai_review, "rename", lambda *_a: (_ for _ in ()).throw(OSError("locked")))
    monkeypatch.setattr(deck_headers, "regenerate_headers", lambda _ctx: (_ for _ in ()).throw(OSError("busy")))
    warnings: list[str] = []
    assert slide_rename.rename_slide_id(ctx, "2du", "k7m", warnings=warnings) == {"2du-EN-Old": "k7m-EN-Old"}
    assert (ctx.slides_dir / "k7m-EN-Old-current.tex").is_file()
    assert any("review marks" in w for w in warnings)
    assert library_data.read(ctx).pool == {"k7m"}
    assert any("deck headers" in w and "rebuilt" in w for w in warnings)


def test_an_undo_that_fails_says_what_is_left(ctx, monkeypatch):
    original, calls = slide_edit.move_file, []

    def flaky(src, dest, root):
        calls.append(src.name)
        if len(calls) > 1:                      # the first move works; the second fails, and so does every move back
            raise PermissionError("locked")
        return original(src, dest, root)
    monkeypatch.setattr(slide_edit, "move_file", flaky)
    with pytest.raises(SlideEditError, match="could not be fully undone") as error:
        rename_id(ctx)
    assert not error.value.clean and "k7m-EN-Old" in str(error.value)


@pytest.mark.parametrize("call, owner, method, nth", [
    pytest.param(lambda ctx: slide_rename.rename_slide_slug(ctx, "2du-EN-Old", "New"),
                 slide_edit, "move_file", 2, id="slug"),
    pytest.param(lambda ctx: slide_rename.set_slide_language(ctx, "2du-EN-Old", "mult"),
                 slide_edit, "move_file", 1, id="language"),
    pytest.param(lambda ctx: slide_rename.tag_untagged(ctx, "k9z-Plain", "EN"),
                 fileio, "write_text_exact", 2, id="tag"),
])
def test_the_id_slug_renames_are_all_or_nothing(ctx, monkeypatch, call, owner, method, nth):
    before = snapshot(ctx.root)
    fail_nth(monkeypatch, owner, method, nth)
    with pytest.raises(SlideEditError, match="Nothing was changed"):
        call(ctx)
    assert_unchanged(ctx, before)


def test_the_plan_names_every_file_an_editor_tab_may_hold(ctx):
    plan = slide_edit.plan_id_slug_rename(ctx, "2du-EN-Old", "2du-EN-New")
    names = {p.name for p in plan.paths()}
    assert {"d1.tex", "d2.tex", "d3.tex", "2du-EN-Old-current.tex", "2du-EN-New-current.tex",
            "2du-EN-Old-v1-0-0.tex"} <= names
    delete_plan = slide_edit.plan_delete(ctx, "2du-EN-Old")
    assert {"d1.tex", "2du-EN-Old-current.tex"} <= {p.name for p in delete_plan.paths()}
    assert not any("trash" in str(p) for p in delete_plan.paths())
    assert {"other-EN-Z-current.tex"} <= {p.name for p in slide_edit.plan_id_rename(ctx, "2du", "k7m").paths()}


def test_a_damaged_review_file_stops_the_rename_before_anything_changes(ctx):
    write(ctx.ai_review_path, "{not json")
    before = snapshot(ctx.root)
    with pytest.raises(ValueError, match="cannot be read"):
        rename_id(ctx)
    assert snapshot(ctx.root) == before


def test_a_delete_that_works_leaves_no_trash(ctx):
    assert delete(ctx) == {"files_removed": 3, "deck_references_removed": 3}
    assert not list(ctx.slides_dir.glob("2du-*"))
    assert "2du-EN-Old" not in (ctx.decks_dir / "d1.tex").read_text(encoding="utf-8")
    assert not list((ctx.settings_dir / "trash").glob("*"))
    assert alt_archive.archive_path(ctx).is_file()
    assert "2du" not in library_data.read(ctx).pool


def test_a_delete_with_a_trash_folder_that_will_not_go_still_succeeds_with_a_warning(ctx, monkeypatch):
    monkeypatch.setattr(slide_edit.shutil, "rmtree", lambda _p: (_ for _ in ()).throw(PermissionError("locked")))
    warnings: list[str] = []
    slide_rename.delete_slide_id(ctx, "2du-EN-Old", warnings=warnings)
    assert any("trash" in w for w in warnings) and not list(ctx.slides_dir.glob("2du-*"))


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
@pytest.mark.parametrize("failure", ["library", "move"])
def test_tracked_files_follow_a_rename_and_a_failed_delete_preserves_the_index(ctx, monkeypatch, failure):
    monkeypatch.undo()                      # the real is_git_repo; the derived-data steps are not needed here
    monkeypatch.setattr(deck_headers, "regenerate_headers", lambda _ctx: None)
    monkeypatch.setattr(slide_rename, "regenerate_translation_links", lambda _ctx: None)

    def git(*args):
        return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=ctx.root, check=True,
                              capture_output=True, text=True).stdout
    git("init", "-q")
    git("add", "-A")
    git("commit", "-qm", "start")
    slide_rename.rename_slide_slug(ctx, "2du-EN-Old", "New")
    assert "2du-EN-New-current.tex" in git("ls-files")
    assert "2du-EN-Old" not in git("ls-files", "slides")
    git("add", "-A")
    git("commit", "-qm", "renamed")

    current = ctx.slides_dir / "2du-EN-New-current.tex"
    write(current, "% staged revision\n")
    git("add", "--", str(current.relative_to(ctx.root)))
    write(current, "% unstaged revision\n")
    write(ctx.slides_dir / "2du-EN-New-v1-0-0.tex", "% unstaged version\n")
    git("rm", "--cached", "--", "slides/2du-EN-New-v1-1-0.tex")
    paths = sorted(ctx.slides_dir.glob("2du-EN-New-*.tex"))
    index_before = {p: git("ls-files", "--stage", "--", str(p.relative_to(ctx.root))) for p in paths}
    bytes_before = {p: p.read_bytes() for p in paths}
    status_before = git("status", "--porcelain", "slides")

    if failure == "library":
        fail_nth(monkeypatch, library_data, "update", 1, OSError("disk full"))
    else:
        fail_nth(monkeypatch, slide_edit.shutil, "move", 1, OSError("locked"))
    with pytest.raises(SlideEditError, match="Nothing was changed") as error:
        slide_rename.delete_slide_id(ctx, "2du-EN-New")
    assert error.value.clean
    assert {p: git("ls-files", "--stage", "--", str(p.relative_to(ctx.root))) for p in paths} == index_before
    assert {p: p.read_bytes() for p in paths} == bytes_before
    assert git("status", "--porcelain", "slides") == status_before
    monkeypatch.undo()
    monkeypatch.setattr(deck_headers, "regenerate_headers", lambda _ctx: None)
    monkeypatch.setattr(slide_rename, "regenerate_translation_links", lambda _ctx: None)

    slide_rename.delete_slide_id(ctx, "2du-EN-New")
    assert "2du-EN-New" not in git("ls-files", "slides")
    assert not list(ctx.slides_dir.glob("2du-*")) and not list((ctx.settings_dir / "trash").glob("*"))


# -- the message of a failed step (2026-11-28: a locked file showed the raw git command) ------------------------

def test_a_locked_file_reads_as_in_use_not_as_a_command_line():
    import subprocess as sp
    from slidemage.slide_edit import describe_failure

    locked = sp.CalledProcessError(128, ["git", "mv", "a", "b"],
                                   stderr=b"fatal: renaming 'slides/a.tex' failed: Permission denied\n")
    text = describe_failure(locked)
    assert "open in another program" in text and "Permission denied" in text
    assert "git', 'mv'" not in text and "exit status" not in text
    assert "open in another program" in describe_failure(sp.CalledProcessError(128, ["git", "mv"], stderr=b""))
    assert describe_failure(sp.CalledProcessError(128, ["git", "mv"], stderr=b"fatal: bad source\n")) \
        == "Git refused it (bad source)."
    assert "open in another program" in describe_failure(PermissionError(13, "Permission denied"))
