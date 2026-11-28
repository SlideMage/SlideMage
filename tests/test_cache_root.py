"""One cache folder per project (`project_cache_dir`), and the move of the three folders of earlier versions."""
import os
import time

import pytest

from slidemage import housekeeping, preview_build, project, render_store
from slidemage.project import ProjectContext


def old_layout(root):
    pages, previews, store = project.legacy_cache_roots(root)
    for folder, name in ((pages / "page-images", "p.json"), (pages / "render-results", "r.pdf"),
                         (previews / "tikz_illustration_previews", "t.png"), (store / "objects", "o.bin")):
        folder.mkdir(parents=True)
        (folder / name).write_text(name, encoding="utf-8")
    (previews / "preview-maintenance.lock").write_text("l", encoding="utf-8")
    (store / "index.sqlite").write_text("db", encoding="utf-8")
    return pages, previews, store


def fresh(root):
    project._migrated.clear()
    return project.project_cache_dir(root)


def test_old_folders_move_into_the_one_root_intact(tmp_path):
    root = tmp_path / "Proj"
    pages, previews, store = old_layout(root)
    base = fresh(root)
    assert base == project.cache_dir() / "projects" / project.project_id(root)
    assert (base / "page-images" / "p.json").read_text() == "p.json"
    assert (base / "previews" / "tikz_illustration_previews" / "t.png").read_text() == "t.png"
    assert (base / "previews" / "preview-maintenance.lock").read_text() == "l"
    assert (base / "render-store" / "objects" / "o.bin").read_text() == "o.bin"
    assert (base / "render-store" / "index.sqlite").read_text() == "db"
    assert not pages.exists() and not previews.exists() and not store.exists()    # render-results went with its folder


def test_an_old_folder_beside_a_new_one_in_use_is_removed(tmp_path):
    """The leftover of a move that failed before the old folder stayed in use: the app had started an empty folder
    in the new place and filled it, so the new one is current and the old one unused (2026-11-28, 5.4 GB)."""
    root = tmp_path / "Proj"
    pages, previews, store = old_layout(root)
    new = project.cache_dir() / "projects" / project.project_id(root) / "render-store"
    new.mkdir(parents=True)
    (new / "mine").write_text("new", encoding="utf-8")
    base = fresh(root)
    assert [p.name for p in new.iterdir()] == ["mine"] and not store.exists()
    assert (base / "previews" / "preview-maintenance.lock").is_file() and not previews.exists()
    assert (base / ".cache-root-migrated").exists()
    assert project.render_store_cache_dir(root) == new


def test_a_failed_move_does_not_raise_and_keeps_the_old_folder(tmp_path, monkeypatch):
    root = tmp_path / "Proj"
    pages, previews, store = old_layout(root)

    def locked(source, target, *args, **kwargs):
        raise PermissionError("in use")
    monkeypatch.setattr("slidemage.fileio.replace_with_retry", locked)
    base = fresh(root)
    assert (store / "index.sqlite").is_file() and (previews / "preview-maintenance.lock").is_file()
    assert not (base / ".cache-root-migrated").exists()


def test_after_a_failed_move_the_old_folders_stay_in_use_until_a_later_start_moves_them(tmp_path, monkeypatch):
    """No empty folder in the new place, so nothing renders again (2026-11-28: "Access denied" on the render store
    made the app render the whole project again)."""
    root = tmp_path / "Proj"
    pages, previews, store = old_layout(root)
    from slidemage import fileio
    real = fileio.replace_with_retry

    def locked(source, target, *args, **kwargs):
        raise PermissionError("in use")
    monkeypatch.setattr(fileio, "replace_with_retry", locked)
    fresh(root)
    assert project.render_store_cache_dir(root) == store
    assert project.previews_cache_dir(root) == previews
    assert project.preview_cache_dir(root) == pages / "page-images"
    assert ProjectContext.at(root).previews_dir == previews
    monkeypatch.setattr(fileio, "replace_with_retry", real)       # the lock is gone at the next start
    base = fresh(root)
    assert project.render_store_cache_dir(root) == base / "render-store"
    assert (base / "render-store" / "index.sqlite").read_text() == "db" and not store.exists()
    assert (base / ".cache-root-migrated").exists()


def test_a_second_start_does_nothing(tmp_path, monkeypatch):
    root = tmp_path / "Proj"
    old_layout(root)
    base = fresh(root)
    assert (base / ".cache-root-migrated").is_file()
    project.legacy_cache_roots(root)[2].mkdir(parents=True)       # appears later: the marker means no second look
    (project.legacy_cache_roots(root)[2] / "x").write_text("x")
    assert fresh(root) == base and not (base / "render-store" / "x").exists()


def test_every_user_resolves_to_the_one_root(tmp_path):
    root = tmp_path / "Proj"
    ctx = ProjectContext.at(root)
    base = project.cache_dir() / "projects" / project.project_id(root)
    store = render_store.RenderStore(ctx)
    try:
        assert store.root == base / "render-store"
    finally:
        store.close()
    assert project.preview_cache_dir(root) == base / "page-images"
    assert project.previews_cache_dir(root) == ctx.previews_dir == base / "previews"
    assert ctx.tikz_previews_dir.parent == ctx.pdf_render_cache_dir.parent == base / "previews"
    assert preview_build.maintenance_lock(root) == base / "previews" / "preview-maintenance.lock"


def test_housekeeping_prunes_a_forgotten_project_root_and_a_leftover_old_store(tmp_path):
    ctx = ProjectContext.at(tmp_path / "Proj")
    store = render_store.RenderStore(ctx)
    store.close()
    old = time.time() - 31 * 86400
    gone = project.cache_dir() / "projects" / "gone"
    (gone / "render-store").mkdir(parents=True)
    (gone / "page-images").mkdir()
    (gone / "render-store" / "index.sqlite").touch()
    leftover = project.cache_dir() / "render-store" / "leftover"
    leftover.mkdir(parents=True)
    (leftover / "index.sqlite").touch()
    for path in (gone / "render-store" / "index.sqlite", leftover / "index.sqlite"):
        os.utime(path, (old, old))
    housekeeping.prune_render_stores(ctx)
    assert not gone.exists() and not leftover.exists() and store.root.is_dir()
