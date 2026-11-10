"""TikZ pictures and rendered PDF pages live in this computer's cache folder, not in the project."""
import ctypes
import os
import shutil
import string
from pathlib import Path

import pytest

from slidemage import project
from slidemage.project import ProjectContext


def make_old_copy(root: Path) -> Path:
    old = root / ".previews"
    for folder, name in (("slide_previews", "a-EN-T-304-171.png"), (project.TIKZ_PREVIEWS, "t-1.png"),
                         (project.PDF_RENDER_CACHE, "m.png")):
        (old / folder).mkdir(parents=True)
        (old / folder / name).write_bytes(b"old " + name.encode())
    (old / "preview-maintenance.lock").write_bytes(b"\0")
    return old


def test_places_are_in_the_cache_folder_under_the_project_id(tmp_path):
    ctx = ProjectContext.at(tmp_path / "Proj")
    base = project.cache_dir() / "previews" / project.project_id(ctx.root)
    assert ctx.previews_dir == base
    assert ctx.tikz_previews_dir == base / "tikz_illustration_previews"
    assert ctx.pdf_render_cache_dir == base / "pdf_render_cache"
    assert not any(p.is_relative_to(ctx.root) for p in (ctx.tikz_previews_dir, ctx.pdf_render_cache_dir))
    assert project.previews_cache_dir(ctx.root) == base
    assert ProjectContext.at(tmp_path / "Other").previews_dir != base       # one folder per project


def test_first_use_moves_an_old_previews_folder(tmp_path):
    root = tmp_path / "Proj"
    old = make_old_copy(root)
    (old / "benchmarks").mkdir()
    (old / "benchmarks" / "evidence.tar.gz").write_bytes(b"keep")
    ctx = ProjectContext.at(root)
    assert (ctx.tikz_previews_dir / "t-1.png").is_file()
    assert (ctx.pdf_render_cache_dir / "m.png").is_file()
    assert not (project.previews_cache_dir(root) / "slide_previews").exists()
    assert [p.name for p in old.iterdir()] == ["benchmarks"]               # the caches and the lock are gone, the rest stays


def test_an_empty_old_folder_is_removed_and_the_new_place_wins(tmp_path):
    root = tmp_path / "Proj"
    old = make_old_copy(root)
    new = project.previews_cache_dir(root) / project.TIKZ_PREVIEWS
    new.mkdir(parents=True)
    (new / "kept.png").write_bytes(b"new")
    project.migrate_previews(root)
    assert not old.exists()
    assert [p.name for p in new.iterdir()] == ["kept.png"]                 # not merged with the old copy
    project.migrate_previews(root)                                           # nothing left to do, nothing raised


def test_migration_runs_once_per_process(tmp_path):
    root = tmp_path / "Proj"
    ctx = ProjectContext.at(root)
    ctx.tikz_previews_dir.mkdir(parents=True)
    make_old_copy(root)                                                      # appears after the first use: not touched again
    assert ctx.tikz_previews_dir.is_dir()
    assert (root / ".previews" / project.TIKZ_PREVIEWS).is_dir()


def other_drive(path: Path):
    """A drive letter other than `path`'s that exists and is writable, else None."""
    if os.name != "nt":
        return None
    mask = ctypes.windll.kernel32.GetLogicalDrives()
    for i, letter in enumerate(string.ascii_uppercase):
        if mask & (1 << i) and letter != os.path.splitdrive(str(path.resolve()))[0][:1].upper():
            return Path(f"{letter}:\\")
    return None


def test_a_project_on_another_drive_than_the_cache(tmp_path):
    drive = other_drive(tmp_path)
    if drive is None:
        pytest.skip("this machine has one drive")
    try:
        root = Path(os.path.join(str(drive), f"slidemage-test-{os.getpid()}"))
        root.mkdir()
    except OSError:
        pytest.skip(f"cannot write to {drive}")
    try:
        make_old_copy(root)
        ctx = ProjectContext.at(root)
        assert os.path.splitdrive(str(ctx.tikz_previews_dir))[0].upper() != os.path.splitdrive(str(root))[0].upper()
        assert (ctx.tikz_previews_dir / "t-1.png").is_file()      # moved across drives
        from slidemage import deck_snapshot
        png = root / ".build" / "appendix-thumbs" / "T" / "x.png"
        png.parent.mkdir(parents=True)
        out = deck_snapshot._JobOutput("j", Path("x.pdf"), [png], "", [], None)
        png.write_bytes(b"png")
        target = tmp_path / "snap"
        assert deck_snapshot.copy_job_previews(out, "t-job", root, target) == 1      # no os.path.relpath across drives
        assert (target / ".build" / "appendix-thumbs" / "t-job" / "T" / "x.png").is_file()
        wrapper = "\\includegraphics{" + png.as_posix() + "}"
        assert deck_snapshot.relative_wrapper(wrapper, root, "t-job") == (
            "\\includegraphics{.build/appendix-thumbs/t-job/T/x.png}")
        assert deck_snapshot.classify_input(ctx.tikz_previews_dir / "t-1.png", project_root=root, framework_dir=None, build_dirs=[], roots=[]) == "build"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_maintenance_lock_is_in_the_cache_folder(tmp_path):
    from slidemage import preview_build
    lock = preview_build.maintenance_lock(tmp_path / "Proj")
    assert lock == ProjectContext.at(tmp_path / "Proj").previews_dir / "preview-maintenance.lock"
