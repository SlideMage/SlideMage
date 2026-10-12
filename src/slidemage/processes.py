"""Small subprocess helpers with no SlideMage dependencies."""

import os
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
