"""TikZ pictures and rendered PDF pages live in this computer's cache folder, not in the project."""
import ctypes
import os
import string
from pathlib import Path


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


def other_drive(path: Path):
    """A drive letter other than `path`'s that exists and is writable, else None."""
    if os.name != "nt":
        return None
    mask = ctypes.windll.kernel32.GetLogicalDrives()
    for i, letter in enumerate(string.ascii_uppercase):
        if mask & (1 << i) and letter != os.path.splitdrive(str(path.resolve()))[0][:1].upper():
            return Path(f"{letter}:\\")
    return None


def test_maintenance_lock_is_in_the_cache_folder(tmp_path):
    from slidemage import preview_build
    lock = preview_build.maintenance_lock(tmp_path / "Proj")
    assert lock == ProjectContext.at(tmp_path / "Proj").previews_dir / "preview-maintenance.lock"
