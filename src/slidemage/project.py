"""Locate the Slidemaster project (the folder holding slide_ids.csv) to operate on.

Deliberately free of side effects and of imports from the rest of the package:
cli.py must settle the project before deck_scan computes PROJECT_ROOT at import.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

MARKER = "slide_ids.csv"
ENV_VAR = "SLIDEMASTER_PROJECT"

# Project format guard (v4.1.0). <project>/.slidemage/project.json records
# {"format": N, "last_app_version": "vX.Y.Z"} and is tracked with the
# project, unlike app_settings.json. PROJECT_FORMAT goes up only when a
# SlideMage release changes what it writes into a project in a way older
# releases can't read -- always a breaking release (major bump + BREAKING:
# paragraph, see version.py). A project with a higher format than this
# app's gets a warning before opening (cli.py); one with a lower format is
# where a migration would go -- none exist yet. A migration MUST back up
# every file it rewrites before touching it.
PROJECT_FORMAT = 1
PROJECT_INFO_PATH = Path(".slidemage") / "project.json"

def _ignore_template_build_output(directory: str, names: list[str]) -> set[str]:
    """shutil.copytree() ignore callback for init_project()'s template
    copy: skips compiled-deck build output (a *.pdf/*.synctex.gz sitting
    directly in decks/, or the whole pdf/.build/.previews folders) --
    real, current for the repo's own example/ demo copy since it's
    actually been compiled, but nothing a *brand-new* project should
    start out with; a new project compiles its own from scratch. NOT a
    blanket "*.pdf" skip: schemes/scheme_uni_graz/*.pdf is a real,
    tracked logo asset the preamble \\includegraphics's, needed for the
    copy to actually compile."""
    skip = {".build", ".previews", ".backups", "pdf", "__pycache__"}
    if os.path.basename(directory) == "decks":
        skip |= {n for n in names if n.endswith((".pdf", ".synctex.gz"))}
    return {n for n in names if n in skip}


class ProjectCreationError(ValueError):
    """A project template would collide with content already in the folder."""

    def __init__(self, path: Path, conflicts: list[Path]):
        self.path = path
        self.conflicts = tuple(conflicts)
        shown = ", ".join(str(item) for item in self.conflicts[:5])
        if len(self.conflicts) > 5:
            shown += f", and {len(self.conflicts) - 5} more"
        super().__init__(
            f"Cannot create a project in {path}: existing content would be "
            f"overwritten or replaced ({shown}). Choose an empty folder or "
            "move the listed content first."
        )


def _template_copy_conflicts(source: Path, destination: Path) -> list[Path]:
    """Existing paths that copytree() would replace or follow through."""
    conflicts: list[Path] = []
    for root, dirs, files in os.walk(source):
        ignored = _ignore_template_build_output(root, [*dirs, *files])
        dirs[:] = [name for name in dirs if name not in ignored]
        relative = Path(root).relative_to(source)
        for name in dirs:
            target = destination / relative / name
            if os.path.lexists(target) and (target.is_symlink() or not target.is_dir()):
                conflicts.append(target)
        for name in files:
            if name in ignored:
                continue
            target = destination / relative / name
            if os.path.lexists(target):
                conflicts.append(target)
    return sorted(set(conflicts))


def _scaffold_conflicts(path: Path) -> list[Path]:
    """Existing paths that the empty-project scaffold needs to create."""
    conflicts: list[Path] = []
    marker = path / MARKER
    if os.path.lexists(marker):
        conflicts.append(marker)
    for name in ("slides", "decks", "media"):
        target = path / name
        if os.path.lexists(target) and (target.is_symlink() or not target.is_dir()):
            conflicts.append(target)
    return sorted(set(conflicts))


def is_project(path: Path) -> bool:
    return (path / MARKER).is_file()


def find_upward(start: Path) -> Path | None:
    start = start.resolve()
    for candidate in (start, *start.parents):
        if is_project(candidate):
            return candidate
    return None


def config_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
        return base / "SlideMage"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "SlideMage"
    base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "slidemage"


def _last_project_file() -> Path:
    return config_dir() / "last_project"


def load_last_project() -> Path | None:
    try:
        path = Path(_last_project_file().read_text(encoding="utf-8").strip())
    except OSError:
        return None
    return path if is_project(path) else None


def save_last_project(path: Path) -> None:
    target = _last_project_file()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(str(path), encoding="utf-8")
    except OSError:
        pass


def read_project_info(root: Path) -> dict:
    """{"format": int, "last_app_version": str} from the project's
    project.json; a missing or unreadable file reads as format
    PROJECT_FORMAT with no known last version."""
    info = {"format": PROJECT_FORMAT, "last_app_version": ""}
    try:
        data = json.loads((root / PROJECT_INFO_PATH).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return info
    if isinstance(data, dict):
        if isinstance(data.get("format"), int):
            info["format"] = data["format"]
        if isinstance(data.get("last_app_version"), str):
            info["last_app_version"] = data["last_app_version"]
    return info


def record_project_open(root: Path, app_version: str) -> None:
    """Write project.json after the project was opened with `app_version`.
    A project newer than this app keeps its format and last version, so
    the warning still names the release that changed it."""
    info = read_project_info(root)
    if info["format"] <= PROJECT_FORMAT:
        # Migrations from an older format go here (none exist yet); each
        # must back up what it rewrites first.
        info = {"format": PROJECT_FORMAT, "last_app_version": app_version}
    path = root / PROJECT_INFO_PATH
    text = json.dumps(info, indent=2) + "\n"
    try:
        if path.read_text(encoding="utf-8") == text:
            return  # unchanged -- don't touch a cloud-synced file for nothing
    except OSError:
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def _template_dir(name: str) -> Path | None:
    """Where the bundled `name` template ("example" or "latex") lives
    right now, or None if this run has neither -- shouldn't happen for
    either supported way of running SlideMage, but a missing template is
    a reason for init_project() to fall back to an empty scaffold, not to
    raise.

    Frozen (PyInstaller): packaging/slidemage.spec bundles both folders
    as datas under "slidemage_template/", extracted at startup into
    sys._MEIPASS (a onefile build's per-run temp extraction dir) same as
    every other bundled data file. Unfrozen: this file's own location is
    src/slidemage/project.py, so two parents up is the repo root, where
    example/ and latex/ are real, live directories -- not a copy, so an
    edit to the repo's own example/ is what a dev-checkout run of this
    picks up, same as it always would."""
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", "")) / "slidemage_template"
    else:
        base = Path(__file__).resolve().parents[2]
    candidate = base / name
    return candidate if candidate.is_dir() else None


def has_example_template() -> bool:
    """Whether init_project(..., copy_example=True) actually has
    something to copy -- both the example project and the LaTeX
    framework it depends on need to be found, or a copy without one of
    them would leave a project that looks complete but can't compile."""
    return _template_dir("example") is not None and _template_dir("latex") is not None


def init_project(path: Path, copy_example: bool = True) -> None:
    """Turn an ordinary folder into a minimal, valid project.

    copy_example=True seeds it with the bundled demo project, then copies
    the sibling LaTeX framework only when one is not already there. An
    empty scaffold is created when copy_example is False or the template is
    unavailable. Existing unrelated files are preserved; any path the
    operation would overwrite or replace raises ProjectCreationError before
    any project files are written.
    """
    path = Path(path)
    if os.path.lexists(path) and (path.is_symlink() or not path.is_dir()):
        raise ProjectCreationError(path, [path])

    example_dir = _template_dir("example") if copy_example else None
    if example_dir is not None:
        conflicts = _template_copy_conflicts(example_dir, path)
        if conflicts:
            raise ProjectCreationError(path, conflicts)
        path.mkdir(parents=True, exist_ok=True)
        shutil.copytree(
            example_dir, path, dirs_exist_ok=True, ignore=_ignore_template_build_output
        )
        latex_dir = _template_dir("latex")
        sibling_latex = path.parent / "latex"
        copied_latex = latex_dir is not None and not os.path.lexists(sibling_latex)
        if copied_latex:
            shutil.copytree(latex_dir, sibling_latex)
        # The baseline for later updates of these copies (bundled_copies.py):
        # the manual always, the framework only if this call copied it.
        from . import bundled_copies
        from .version import VERSION_NUMBER
        bundled_copies.record_copies(
            path, VERSION_NUMBER,
            framework_dir=sibling_latex if copied_latex else None,
            framework_source=latex_dir if copied_latex else None,
            example_source=example_dir)
        return

    conflicts = _scaffold_conflicts(path)
    if conflicts:
        raise ProjectCreationError(path, conflicts)
    path.mkdir(parents=True, exist_ok=True)
    csv_path = path / MARKER
    if not csv_path.exists():
        # Byte-for-byte the same header-only shape
        # slide_ids.append_slide_id() itself writes for a brand-new file.
        csv_path.write_text('"id"\r\n', encoding="utf-8", newline="")
    for sub in ("slides", "decks", "media"):
        (path / sub).mkdir(exist_ok=True)


def discover() -> Path | None:
    """$SLIDEMASTER_PROJECT, else upward from the cwd, else the last project opened."""
    env = os.environ.get(ENV_VAR)
    if env and is_project(Path(env)):
        return Path(env).resolve()
    return find_upward(Path.cwd()) or load_last_project()


def relaunch_with_project(root: Path) -> None:
    """Start a fresh SlideMage process pointed at `root` and return --
    never quits the current one itself, since a GUI action needs to
    finish its own event handling first (Qt closes windows/quits the
    QApplication in its caller, after this returns).

    Switching projects can't just mutate the running process's own state:
    deck_scan.PROJECT_ROOT and every directory constant derived from it at
    import time across this whole package (compiler.BUILD_DIR/PDF_DIR,
    slide_source.SLIDES_DIR, alt_images.STORE_PATH, app_settings.STORE_PATH,
    ...) are fixed once, at the first `from . import deck_scan` anywhere
    in the process -- there is no single place left to change them all
    after the fact. A new process re-derives every one of them fresh from
    this one new root, the same as if the user had launched SlideMage
    pointed at `root` from the start.

    Frozen (PyInstaller): sys.executable *is* the SlideMage binary itself,
    so it's relaunched directly. Unfrozen: sys.executable is the Python
    interpreter that's currently running this file as an installed
    package, not as a standalone script, so it needs `-m slidemage` to
    find its way back to the same entry point cli.py's own console-script
    hook (`slidemage = slidemage.cli:main`) uses."""
    save_last_project(root)
    env = os.environ.copy()
    env[ENV_VAR] = str(root)
    frozen = getattr(sys, "frozen", False)
    if frozen:
        # Without this, the one-file bootloader treats the new process as
        # part of this one and runs it from this process's _MEI temp dir,
        # which is deleted when we exit -- the relaunch dies at startup.
        env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    argv = (
        [sys.executable, "--project", str(root)]
        if frozen
        else [sys.executable, "-m", "slidemage", "--project", str(root)]
    )
    subprocess.Popen(argv, env=env)


def pick_or_create_project(parent, start_dir: Path) -> Path | None:
    """Shared folder-picker loop for cli.py's first-run fallback (no
    window exists yet, parent=None) and qt_gui.py's "Open Project…"
    (parent=the main window) -- one implementation so the two don't drift
    apart, and so the "not a project yet" case offers to create one
    (init_project() above) instead of only ever rejecting the folder and
    making the user pick a different, already-existing project."""
    from PySide6.QtWidgets import QFileDialog, QMessageBox

    start = str(start_dir)
    while True:
        chosen = QFileDialog.getExistingDirectory(
            parent, f"Open a Slidemaster project (folder containing {MARKER})", start
        )
        if not chosen:
            return None
        path = Path(chosen)
        if is_project(path):
            return path.resolve()
        with_example = has_example_template()
        detail = (
            "Create a new project here, seeded with the demo content "
            "(Gotham theme, sample slides, a deck-version example) so "
            "there's something to compile and learn from right away?"
            if with_example else
            "Create a new, empty project here?"
        )
        box = QMessageBox(parent)
        box.setWindowTitle("Not a Slidemaster project")
        box.setText(f"{path} has no {MARKER} yet.")
        box.setInformativeText(detail)
        create_button = box.addButton("Create", QMessageBox.ButtonRole.AcceptRole)
        pick_again_button = box.addButton(
            "Pick a different folder", QMessageBox.ButtonRole.RejectRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(pick_again_button)
        box.exec()
        clicked = box.clickedButton()
        if clicked is create_button:
            try:
                init_project(path, copy_example=with_example)
            except ProjectCreationError as exc:
                QMessageBox.warning(parent, "Cannot create project", str(exc))
                start = chosen
                continue
            return path.resolve()
        if clicked is not pick_again_button:
            return None  # Cancel
        start = chosen
