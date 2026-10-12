"""The project's snippets/ folder: the small files that \\SMCodeFile{path}
shows on a slide as highlighted LaTeX source, so the slide needs no [fragile]
frame. By convention a slide's snippets are named after it,
`snippets/<slide id>-<n>.tex`; the path in the call is relative to the project
folder, extension included (latex_lint's "code-file" check looks it up there).
"""
from __future__ import annotations

from pathlib import Path
from . import project




def list_snippets() -> list[str]:
    """Every file in snippets/ (subfolders too), as the project-relative paths a
    \\SMCodeFile call takes, sorted."""
    root = project.transitional_context().snippets_dir
    if not root.is_dir():
        return []
    return sorted(f"{root.name}/{p.relative_to(root).as_posix()}" for p in root.rglob("*") if p.is_file())


def next_snippet(slide_id: str) -> str:
    """`snippets/<slide id>-<n>.tex` with the lowest n that is not taken."""
    ctx = project.transitional_context()
    existing = set(list_snippets())
    n = 1
    while f"{ctx.snippets_dir.name}/{slide_id}-{n}.tex" in existing:
        n += 1
    return f"{ctx.snippets_dir.name}/{slide_id}-{n}.tex"


def resolve(path: str) -> Path:
    """The file a project-relative `path` names, which must lie inside snippets/ (not the folder itself)."""
    ctx = project.transitional_context()
    target = (ctx.snippets_dir.parent / path).resolve()
    if target == ctx.snippets_dir.resolve() or target.is_dir() or not target.is_relative_to(ctx.snippets_dir.resolve()):
        raise ValueError(f"{path} is not a file in the {ctx.snippets_dir.name}/ folder.")
    return target


def create(path: str) -> bool:
    """Create the empty snippet `path` (and its folders) unless it exists; whether it was created."""
    target = resolve(path)
    if target.exists():
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("", encoding="utf-8")
    return True
