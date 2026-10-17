"""Small subprocess helpers with no SlideMage dependencies."""

import os
import shutil
import subprocess
from pathlib import Path


def no_console_kwargs() -> dict:
    """Suppress a subprocess console window on Windows."""
    return {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}


def is_git_repo(project_root: Path) -> bool:
    return (project_root / ".git").exists()


def is_git_tracked(path: Path, project_root: Path) -> bool:
    result = subprocess.run(
        ["git", "ls-files", "--error-unmatch", str(path.relative_to(project_root))],
        cwd=project_root,
        capture_output=True,
        **no_console_kwargs(),
    )
    return result.returncode == 0


def command_output(cmd: list[str], *, cwd: Path | None = None, timeout: float = 30,
                   any_exit_code: bool = False) -> str | None:
    """A command's stdout, or None if it can't run, times out, or exits with an error (unless
    `any_exit_code`) -- for version strings, kpsewhich lookups and git queries."""
    try:
        result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, errors="replace",
                                timeout=timeout, **no_console_kwargs())
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout if result.returncode == 0 or any_exit_code else None


def move_file(src: Path, dest: Path, project_root: Path) -> None:
    """Move a file inside the project. `git mv` for a tracked one, so history follows; it refuses a file
    that was never committed, and a project outside git has no history, so those get a plain move."""
    if is_git_repo(project_root) and is_git_tracked(src, project_root):
        subprocess.run(["git", "mv", str(src.relative_to(project_root)), str(dest.relative_to(project_root))],
                       cwd=project_root, check=True, **no_console_kwargs())
    else:
        shutil.move(str(src), str(dest))


def delete_file(path: Path, project_root: Path) -> None:
    """Delete a file inside the project: `git rm` for a tracked one, else a plain unlink."""
    if is_git_repo(project_root) and is_git_tracked(path, project_root):
        subprocess.run(["git", "rm", "-q", str(path.relative_to(project_root))],
                       cwd=project_root, check=True, **no_console_kwargs())
    else:
        path.unlink()
