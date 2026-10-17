"""Putting a file the user brings (paperclip, drop, pasted image) into the project, for the Chat and the
Claude Code terminal alike: a file inside the project stays where it is, any other is copied into sources/."""
from __future__ import annotations

import shutil
from pathlib import Path

from PySide6.QtGui import QImage

from ...ai.tools.files import may_touch


def unique_path(folder: Path, name: str) -> Path:
    """`folder/name`, or with -2, -3 ... before the suffix when that exists already: nothing is overwritten."""
    path, number = folder / name, 1
    while path.exists():
        number += 1
        path = folder / f"{Path(name).stem}-{number}{Path(name).suffix}"
    return path


def place_file(project, source: str | Path, dash_spaces: bool = False) -> str | None:
    """The project-relative POSIX path of `source` after placing it; None when it is no file. Raises OSError
    when the copy fails. `dash_spaces` writes a copy's name with '-' for spaces."""
    root = project.root.resolve()
    path = Path(source).resolve()
    if not path.is_file():
        return None
    if not may_touch(root, path):
        folder = project.sources_dir
        folder.mkdir(exist_ok=True)
        target = unique_path(folder, path.name.replace(" ", "-") if dash_spaces else path.name)
        shutil.copyfile(path, target)
        path = target.resolve()
    return path.relative_to(root).as_posix()


def save_image(project, image: QImage) -> str | None:
    """A pasted image saved into sources/ as a PNG: its project-relative path, or None when that failed."""
    folder = project.sources_dir
    folder.mkdir(exist_ok=True)
    target = unique_path(folder, "pasted-image.png")
    if image.isNull() or not image.save(str(target), "PNG"):
        return None
    return target.relative_to(project.root).as_posix()
