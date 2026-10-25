# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Locate the SlideMage project (the folder holding slide_ids.csv) to operate on.

Deliberately free of side effects and of imports from the rest of the package.
Importing any SlideMage module selects no project: the entry points (cli.py,
the deck_snapshot and preview command lines) create one ProjectContext and
hand it on.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from .fileio import atomic_write, read_json

MARKER = "slide_ids.csv"
ENV_VAR = "SLIDEMAGE_PROJECT"
LATEX_ENV_VAR = "SLIDEMAGE_LATEX"
# The framework's names before it was called SlideMage. They are no longer read; a variable that is
# still set under the old name is reported once (warn_legacy_env_vars) and in the project compatibility sheet.
LEGACY_ENV_VARS = {"SLIDEMASTER_PROJECT": ENV_VAR, "SLIDEMASTER_LATEX": LATEX_ENV_VAR}

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
    blanket "*.pdf" skip: a scheme folder's logo PDF is a real,
    tracked logo asset the preamble \\includegraphics's, needed for the
    copy to actually compile."""
    skip = {".build", ".previews", ".backups", "pdf", "__pycache__"}
    if os.path.basename(directory) == "decks":
        skip |= {n for n in names if n.endswith((".pdf", ".synctex.gz"))}
        skip |= {n for n in names if n.startswith("_") and (Path(directory) / n).is_file()}
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


def project_id(root: Path) -> str:
    """A short, stable name for the project folder `root` on this computer (its normalised path, hashed)."""
    import hashlib
    return hashlib.sha256(os.path.normcase(os.path.normpath(str(Path(root).resolve()))).encode()).hexdigest()[:16]


def preview_cache_dir(root: Path) -> Path:
    """This computer's rebuildable preview caches for the project at `root` (rendered PDFs and their page images):
    outside the project, so a synced project folder never carries them."""
    return cache_dir() / "preview-cache" / project_id(root)


def cache_dir() -> Path:
    """Where this machine keeps what can be rebuilt (not roaming, never synced): the background renders' index."""
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        return base / "SlideMage"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / "SlideMage"
    return Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "slidemage"


def _last_project_file() -> Path:
    return config_dir() / "last_project"


def _exe_sidecar_file() -> Path | None:
    """The exe's own copy of the last-project pointer, next to the exe.
    %APPDATA% belongs to one computer, so on a second PC that runs the same
    (cloud-synced) exe the pointer there is missing and the folder picker
    would ask again; the copy beside the exe travels with the exe.
    Frozen builds only -- a source checkout has no exe to sit next to."""
    if not getattr(sys, "frozen", False):
        return None
    return Path(sys.executable).resolve().parent / "last_project"


def _read_pointer(file: Path | None) -> Path | None:
    if file is None:
        return None
    try:
        text = file.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return Path(text) if text else None


def last_project_hint() -> Path | None:
    """Where the last project was, even if it is gone now: the nearest
    folder that still exists, as the folder picker's starting point."""
    for file in (_last_project_file(), _exe_sidecar_file()):
        path = _read_pointer(file)
        while path is not None and not path.exists():
            parent = path.parent
            path = None if parent == path else parent
        if path is not None:
            return path
    return None


def load_last_project() -> Path | None:
    """The last project opened on this computer, else the one recorded
    beside the exe (see _exe_sidecar_file), if it is a project here."""
    for file in (_last_project_file(), _exe_sidecar_file()):
        path = _read_pointer(file)
        if path is not None and is_project(path):
            return path
    return None


RECENT_LIMIT = 8


def _recent_file() -> Path:
    return config_dir() / "recent_projects.json"


def recent_projects() -> list[Path]:
    """The projects opened last on this computer, newest first. A folder that has
    gone since stays listed (project_status says so)."""
    return [Path(p) for p in read_json(_recent_file(), list) if isinstance(p, str)]


def _remember_recent(path: Path) -> None:
    paths = [str(path)] + [str(p) for p in recent_projects() if p != path]
    text = json.dumps(paths[:RECENT_LIMIT], indent=2) + "\n"
    try:
        if _recent_file().read_text(encoding="utf-8") == text:
            return
    except OSError:
        pass
    try:
        atomic_write(_recent_file(), text)
    except OSError:
        pass


def save_last_project(path: Path) -> None:
    _remember_recent(path)
    for target in (_last_project_file(), _exe_sidecar_file()):
        if target is None:
            continue
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists() and target.read_text(encoding="utf-8").strip() == str(path):
                continue  # unchanged: no needless write into a synced folder
            target.write_text(str(path), encoding="utf-8")
        except OSError:
            pass


def read_project_info(root: Path) -> dict:
    """{"format": int, "last_app_version": str} from the project's
    project.json; a missing or unreadable file reads as format
    PROJECT_FORMAT with no known last version."""
    info = {"format": PROJECT_FORMAT, "last_app_version": ""}
    data = read_project_json(root)
    if isinstance(data.get("format"), int):
        info["format"] = data["format"]
    if isinstance(data.get("last_app_version"), str):
        info["last_app_version"] = data["last_app_version"]
    return info


def read_project_json(root: Path) -> dict:
    """The whole of the project's project.json (every key, also those a
    newer or other part of SlideMage wrote); {} if missing or unreadable."""
    return read_json(root / PROJECT_INFO_PATH)


def write_project_json(root: Path, data: dict) -> None:
    path = root / PROJECT_INFO_PATH
    text = json.dumps(data, indent=2) + "\n"
    try:
        if path.read_text(encoding="utf-8") == text:
            return  # unchanged -- don't touch a cloud-synced file for nothing
    except OSError:
        pass
    atomic_write(path, text)


@dataclass(frozen=True)
class ProjectStatus:
    """What the project picker shows about a folder."""
    path: Path
    name: str
    exists: bool            # a folder with slide_ids.csv
    last_version: str       # the SlideMage that last opened it ("" if none is recorded)
    newer: bool             # its format, or a SlideMage that used it, is newer than the running one


def project_status(root: Path, app_version: str) -> ProjectStatus:
    info = read_project_info(root)
    used_with = read_project_json(root).get("highest_app_version") or info["last_app_version"]
    from .updater import parse_version
    top, current = parse_version(used_with or ""), parse_version(app_version)
    newer = info["format"] > PROJECT_FORMAT or (top is not None and current is not None and top > current)
    return ProjectStatus(root, root.name, is_project(root), info["last_app_version"], newer)


# Deck snapshots (deck_snapshot.py, v5.33.0): a snapshot's project folder is
# an ordinary project whose project.json carries a "snapshot" key; the
# snapshot's own manifest sits one level up, next to the framework copy.
SNAPSHOT_MANIFEST = "snapshot.json"
# Environment variables that could make a compile find files outside the
# snapshot; never passed to a snapshot's compiles.
SNAPSHOT_ISOLATING_ENV_VARS = ("TEXINPUTS", "BIBINPUTS", "LUAINPUTS", "SLIDEMAGE_LATEX")


def snapshot_info(root: Path) -> dict | None:
    """project.json's "snapshot" entry ({"of", "deck_name", "created",
    "read_only"}) when `root` is a deck snapshot's project folder, else None.
    SlideMage never changes a snapshot by itself: no format bookkeeping, no
    compatibility migrations, no framework/manual updates."""
    data = read_project_json(root).get("snapshot")
    return data if isinstance(data, dict) else None


def is_snapshot(root: Path) -> bool:
    return snapshot_info(root) is not None


def snapshot_manifest(root: Path) -> dict:
    """The snapshot.json next to a snapshot's project folder ({} if none)."""
    try:
        data = json.loads((root.parent / SNAPSHOT_MANIFEST).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def snapshot_compile_env(root: Path, env: dict) -> dict:
    """`env` adjusted for compiling inside a snapshot: the snapshot's own
    framework copy, no outside search paths, and the snapshot's fixed
    SOURCE_DATE_EPOCH (PDF dates as when it was taken). Unchanged for an
    ordinary project."""
    if not is_snapshot(root):
        return env
    env = dict(env)
    for name in SNAPSHOT_ISOLATING_ENV_VARS:
        env.pop(name, None)
    manifest = snapshot_manifest(root)
    framework = manifest.get("framework_dir")
    if isinstance(framework, str) and framework:
        env["SLIDEMAGE_LATEX"] = str(root.parent / framework)
    epoch = manifest.get("source_date_epoch")
    if isinstance(epoch, int):
        env["SOURCE_DATE_EPOCH"] = str(epoch)
        env["FORCE_SOURCE_DATE"] = "1"
    return env


def _newer_version(a: str, b: str) -> str:
    """The newer of two "vX.Y.Z" strings (an unparsable one loses)."""
    from .updater import parse_version
    pa, pb = parse_version(a or ""), parse_version(b or "")
    if pa is None:
        return b if pb is not None else (a or b or "")
    if pb is None:
        return a
    return a if pa >= pb else b


def record_project_open(root: Path, app_version: str) -> None:
    """Write project.json after the project was opened with `app_version`.
    A project newer than this app keeps its format and last version, so
    the warning still names the release that changed it. Other keys stay
    (compat.py keeps its state in "compat"), and "highest_app_version"
    never goes down, so opening the project on a PC with an older exe
    doesn't erase that a newer one has used it. "compat.checked_version" --
    the version whose changes the user has dealt with (compat.py) -- starts
    at the version the project was last opened with, so an existing project
    isn't told about changes made before this feature."""
    info = read_project_info(root)
    if info["format"] > PROJECT_FORMAT:
        return
    # Migrations from an older format go here (none exist yet); each
    # must back up what it rewrites first.
    data = read_project_json(root)
    previous = info["last_app_version"]
    data["format"] = PROJECT_FORMAT
    data["last_app_version"] = app_version
    data["highest_app_version"] = _newer_version(
        data.get("highest_app_version", "") or previous, app_version)
    compat = data.get("compat")
    if not isinstance(compat, dict):
        compat = {}
    compat.setdefault("checked_version", previous or app_version)
    data["compat"] = compat
    write_project_json(root, data)


def template_dir(name: str) -> Path | None:
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
    return template_dir("example") is not None and template_dir("latex") is not None


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

    example_dir = template_dir("example") if copy_example else None
    if example_dir is not None:
        conflicts = _template_copy_conflicts(example_dir, path)
        if conflicts:
            raise ProjectCreationError(path, conflicts)
        path.mkdir(parents=True, exist_ok=True)
        shutil.copytree(
            example_dir, path, dirs_exist_ok=True, ignore=_ignore_template_build_output
        )
        latex_dir = template_dir("latex")
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


def legacy_env_notes() -> list[str]:
    """One sentence per old environment variable that is set while its new name is not."""
    return [f"${old} is set but is no longer read. Set ${new} instead."
            for old, new in LEGACY_ENV_VARS.items() if os.environ.get(old) and not os.environ.get(new)]


_legacy_env_warned = False


def warn_legacy_env_vars() -> None:
    """Say on stderr, once per process, which old environment variables are being ignored."""
    global _legacy_env_warned
    if _legacy_env_warned:
        return
    _legacy_env_warned = True
    for note in legacy_env_notes():
        print("SlideMage:", note, file=sys.stderr)


def discover() -> Path | None:
    """$SLIDEMAGE_PROJECT, else upward from the cwd, else the last project opened."""
    env = os.environ.get(ENV_VAR)
    if env and is_project(Path(env)):
        return Path(env).resolve()
    return find_upward(Path.cwd()) or load_last_project()


class _Under:
    """A place inside the project folder, named once: `ctx.slides_dir` is `ctx.root / "slides"`."""

    def __init__(self, *parts: str) -> None:
        self.parts = parts

    def __get__(self, context: "ProjectContext | None", owner: type | None = None):
        return self if context is None else context.root.joinpath(*self.parts)


@dataclass(frozen=True)
class ProjectContext:
    """One project folder and the places inside it. Immutable; created once at the entry point
    (ProjectContext.at) and passed to whatever reads or writes project files. Pure text
    operations take strings, not this."""
    root: Path
    build_dir: Path = None      # type: ignore[assignment]  # latexmk's folder; root/.build unless a benchmark isolates its builds

    slides_dir = _Under("slides")
    slide_backups_dir = _Under("slides", ".backups")
    decks_dir = _Under("decks")
    archive_dir = _Under("decks", "archive")
    media_dir = _Under("media")
    snippets_dir = _Under("snippets")
    sources_dir = _Under("sources")              # papers and figures the user attached to the chat
    pdf_dir = _Under("pdf")
    temp_dir = _Under(".temp")
    previews_dir = _Under(".previews")
    slide_previews_dir = _Under(".previews", "slide_previews")
    tikz_previews_dir = _Under(".previews", "tikz_illustration_previews")
    pdf_render_cache_dir = _Under(".previews", "pdf_render_cache")
    settings_dir = _Under(".slidemage")          # per-project state: app settings, prompts, pass counts, project.json
    ai_review_path = _Under(".slidemage", "ai-review.json")
    ai_before_dir = _Under(".slidemage", "ai-before")   # a slide's text before the last AI edit (ai_review.last_before)
    claude_hook_dir = _Under(".slidemage", "claude-hooks")
    slide_ids_csv = _Under(MARKER)
    bibliography_path = _Under("SlideMage.bib")
    test_slides_path = _Under("decks", "test-slides.tex")
    slide_template_path = _Under(".scripts", "R_Slidemaster", "inst", "templates", "slide-template.tex")

    def __post_init__(self) -> None:
        if self.build_dir is None:
            object.__setattr__(self, "build_dir", self.root / ".build")

    @classmethod
    def at(cls, root: Path) -> "ProjectContext":
        return cls(Path(root))

    @property
    def name(self) -> str:
        return self.root.name

    @property
    def deck_folders(self) -> tuple[Path, Path]:
        """Where decks live: the active ones, then the archived ones."""
        return self.decks_dir, self.archive_dir


def from_environment() -> ProjectContext:
    """The project a command line works on: $SLIDEMAGE_PROJECT, else the one found
    upward from the working directory, else the last opened (else the working directory)."""
    return ProjectContext.at(discover() or Path.cwd())


def relaunch_with_project(root: Path) -> None:
    """Start a fresh SlideMage process pointed at `root` and return --
    never quits the current one itself, since a GUI action needs to
    finish its own event handling first (Qt closes windows/quits the
    QApplication in its caller, after this returns).

    Switching projects restarts instead of changing the running process: windows,
    caches and background jobs all hold the ProjectContext they were built with. A new process
    starts exactly as if the user had launched SlideMage pointed at `root`.

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
