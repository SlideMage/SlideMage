"""Keep a project's copies of the framework and of the SlideMage manual up to
date with the ones this SlideMage carries (2026-10-05, direct instruction: "can
SlideMage be made to show the user an info dialog when the manual has changed,
offering to update it? ... Do both framework and manual").

A new project gets copies of two bundled templates (project.init_project()):
the LaTeX framework (the sibling ``latex/`` folder) and the example project,
whose content is the SlideMage manual. App updates never touched those
copies, so a project kept an old framework and an old manual forever. Now:

- When the copies are made, ``.slidemage/bundled_copies.json`` records a
  SHA-256 per copied file -- the *baseline*.
- On every start, :func:`plan_updates` compares, file by file, the bundled
  version (what this app carries), the baseline and the file on disk:

  ============================  ==============================================
  on disk == baseline != bundle  ``update``: changed upstream only -> replaced
  not in baseline, in bundle     ``add``: new upstream -> added
  in baseline, not in bundle     ``remove``: dropped upstream -> removed (only
                                 if unchanged on disk)
  on disk != baseline != bundle  ``kept``: changed by the user -> left alone
  in baseline, missing on disk   deleted by the user -> stays deleted
  ============================  ==============================================

- :func:`apply_update` backs up every file it replaces or removes under
  ``.slidemage/backups/<time>/<part>/`` first, then copies, and moves the
  baseline to the bundled version.

Projects without a baseline (made before v5.19.0, or never made by SlideMage):

- *Framework*: a sibling ``latex/`` folder that is not part of a git checkout
  is adopted -- its current files count as the baseline, so every file that
  differs from the bundle is replaced (after the backup). A git checkout (a
  developer's ``SlideMage/latex``) is never touched: git updates it.
- *Manual*: offered as an addition -- only files the project doesn't have are
  added; an existing file is never overwritten. This is also how a project of
  one's own gets the manual.

The manual's files are the example project's ``decks/slidemage-manual.tex``,
``slides/``, ``snippets/`` and ``media/`` (without the image-description store,
which is merged instead: descriptions of images the project doesn't describe
yet are added, unreviewed ones of updated images are replaced). New slide ids
are appended to the project's ``slide_ids.csv``.

Free of Qt; ui/workspace/maintenance.py shows the dialog.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from .fileio import read_json, write_json
from .project import ProjectContext

MANIFEST_PATH = Path(".slidemage") / "bundled_copies.json"
BACKUP_DIR = Path(".slidemage") / "backups"

FRAMEWORK = "framework"
MANUAL = "manual"
PART_LABELS = {FRAMEWORK: "LaTeX framework", MANUAL: "SlideMage manual"}

MANUAL_DECK = Path("decks") / "slidemage-manual.tex"
MANUAL_DIRS = ("slides", "snippets", "media")
ALT_TEXT_FILES = {"media/alt-text.json", "media/alt-text.csv"}
# Never part of a copy: build output, caches, and hidden folders such as
# slides/.backups (the slide editor's own undo history of a project).
_SKIP_DIRS = {"__pycache__", "pdf"}


def _skipped(rel: Path) -> bool:
    return any(part in _SKIP_DIRS or part.startswith(".") for part in rel.parts)


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# SlideMage itself keeps the "%% Included in decks: ..." line of every slide
# file (deck_headers.py), so it differs from project to project -- a project
# with a deck of its own that uses the manual's slides lists that deck too.
# That line is not the user's edit; ignoring it is what lets an untouched
# manual slide be updated (v5.26.1: 38 of 56 slides of a real project were
# "kept" only because of it).
_HEADER_RE = re.compile(rb"^%% Included in decks:[^\r\n]*", re.MULTILINE)


def _is_slide_file(rel: str) -> bool:
    return rel.startswith("slides/") and rel.endswith(".tex")


def _hash_with_header_of(path: Path, source: Path) -> str:
    """The hash `path` would have if its "Included in decks" line were the one
    of `source` (the bundled file)."""
    data = path.read_bytes()
    header = _HEADER_RE.search(source.read_bytes())
    if header:
        data = _HEADER_RE.sub(lambda _m: header.group(0), data, count=1)
    return hashlib.sha256(data).hexdigest()


def _hashes(root: Path, relpaths: list[str]) -> dict[str, str]:
    return {rel: file_hash(root / rel) for rel in relpaths}


def framework_files(latex_dir: Path) -> list[str]:
    """Every file of a framework folder, as forward-slash relative paths."""
    out = []
    for path in sorted(latex_dir.rglob("*")):
        rel = path.relative_to(latex_dir)
        if path.is_file() and not _skipped(rel):
            out.append(rel.as_posix())
    return out


def manual_files(example_dir: Path) -> list[str]:
    """The SlideMage manual's files in the (bundled) example project."""
    out = [MANUAL_DECK.as_posix()] if (example_dir / MANUAL_DECK).is_file() else []
    for sub in MANUAL_DIRS:
        folder = example_dir / sub
        if not folder.is_dir():
            continue
        for path in sorted(folder.rglob("*")):
            rel = path.relative_to(example_dir)
            if (path.is_file() and not _skipped(rel)
                    and rel.as_posix() not in ALT_TEXT_FILES):
                out.append(rel.as_posix())
    return out


# -- the manifest ------------------------------------------------------------

def read_manifest(project_root: Path) -> dict:
    return read_json(project_root / MANIFEST_PATH)


def write_manifest(project_root: Path, data: dict) -> None:
    write_json(project_root / MANIFEST_PATH, data, ensure_ascii=True)


def record_copies(project_root: Path, app_version: str, *, framework_dir: Optional[Path],
                  framework_source: Optional[Path], example_source: Optional[Path]) -> None:
    """Called right after project.init_project() copied the templates: the
    baseline is what was just copied (the bundled files' hashes)."""
    data = read_manifest(project_root)
    if framework_dir is not None and framework_source is not None:
        data[FRAMEWORK] = {
            "dir": _relative_dir(project_root, framework_dir),
            "app_version": app_version,
            "files": _hashes(framework_source, framework_files(framework_source)),
        }
    if example_source is not None:
        data[MANUAL] = {
            "app_version": app_version,
            "files": _hashes(example_source, manual_files(example_source)),
        }
    write_manifest(project_root, data)


def _relative_dir(project_root: Path, folder: Path) -> str:
    try:
        return Path("..", folder.resolve().relative_to(project_root.resolve().parent)).as_posix()
    except ValueError:
        return folder.resolve().as_posix()


# -- planning ----------------------------------------------------------------

@dataclass
class Part:
    """One bundled copy (framework or manual) and what an update would do."""
    name: str
    source: Path            # the bundled folder (what this app carries)
    target: Path            # the project's copy
    adopted: bool           # no baseline: adopted (framework) / new install (manual)
    add: list[str] = field(default_factory=list)
    update: list[str] = field(default_factory=list)
    remove: list[str] = field(default_factory=list)
    kept: list[str] = field(default_factory=list)
    bundle_hashes: dict[str, str] = field(default_factory=dict)

    @property
    def label(self) -> str:
        return PART_LABELS[self.name]

    @property
    def pending(self) -> bool:
        return bool(self.add or self.update or self.remove)

    @property
    def new_install(self) -> bool:
        """The manual isn't in the project at all yet."""
        return self.name == MANUAL and self.adopted and MANUAL_DECK.as_posix() in self.add


def _in_git_checkout(folder: Path) -> bool:
    folder = folder.resolve()
    return any((p / ".git").exists() for p in (folder, *folder.parents))


def _same_folder(a: Path, b: Path) -> bool:
    try:
        return a.resolve() == b.resolve()
    except OSError:
        return False


def _plan_part(name: str, source: Path, target: Path, files: list[str],
               baseline: Optional[dict[str, str]]) -> Part:
    adopted = baseline is None
    part = Part(name, source, target, adopted, bundle_hashes=_hashes(source, files))
    if adopted and name == FRAMEWORK:
        # the files as they are count as the baseline: whatever differs is replaced
        baseline = {rel: file_hash(target / rel) for rel in files if (target / rel).is_file()}
    for rel, bundled in part.bundle_hashes.items():
        on_disk = target / rel
        known = (baseline or {}).get(rel)
        if not on_disk.is_file():
            if known is None:
                part.add.append(rel)            # new upstream (or a new install)
            continue                            # else deleted by the user: stays deleted
        current = file_hash(on_disk)
        if current == bundled:
            continue
        as_bundled = _hash_with_header_of(on_disk, source / rel) if _is_slide_file(rel) else None
        if as_bundled == bundled:
            continue                            # only SlideMage's own header line differs
        if known is not None and (current == known or as_bundled == known):
            part.update.append(rel)             # changed upstream only
        else:
            part.kept.append(rel)               # changed by the user (or unknown)
    if baseline:
        for rel, known in baseline.items():
            if rel not in part.bundle_hashes and (target / rel).is_file():
                if file_hash(target / rel) == known:
                    part.remove.append(rel)     # dropped upstream, unchanged here
    return part


def plan_updates(project_root: Path, *, latex_source: Optional[Path],
                 example_source: Optional[Path]) -> list[Part]:
    """The parts with something to do for `project_root`, given the bundled
    framework and example folders (project.template_dir()). Never plans
    against the bundle itself (a developer running on the repo's example/),
    and never against a deck snapshot, which keeps the framework and manual it
    was made with (v5.33.0)."""
    from .project import is_snapshot
    if is_snapshot(project_root):
        return []
    manifest = read_manifest(project_root)
    parts: list[Part] = []

    if latex_source is not None and latex_source.is_dir():
        entry = manifest.get(FRAMEWORK)
        if entry:
            target = (project_root / entry["dir"]).resolve()
            baseline = entry.get("files", {})
        else:
            target = (project_root.parent / "latex").resolve()
            baseline = None
            if (not (target / "Slidemaster_preamble_base.tex").is_file()
                    or _in_git_checkout(target)):
                target = None
        if target is not None and target.is_dir() and not _same_folder(target, latex_source):
            parts.append(_plan_part(FRAMEWORK, latex_source, target,
                                    framework_files(latex_source), baseline))

    if (example_source is not None and example_source.is_dir()
            and not _same_folder(project_root, example_source)):
        entry = manifest.get(MANUAL)
        parts.append(_plan_part(MANUAL, example_source, project_root,
                                manual_files(example_source),
                                entry.get("files", {}) if entry else None))

    return [p for p in parts if p.pending]


def is_dismissed(project_root: Path, app_version: str) -> bool:
    return read_manifest(project_root).get("dismissed_app_version") == app_version


def dismiss(project_root: Path, app_version: str) -> None:
    data = read_manifest(project_root)
    data["dismissed_app_version"] = app_version
    write_manifest(project_root, data)


# -- applying ----------------------------------------------------------------

def apply_update(ctx: ProjectContext, part: Part, app_version: str,
                 now: Optional[datetime] = None) -> Path:
    """Carry out `part`; returns the backup folder (created only if anything
    was replaced or removed)."""
    stamp = (now or datetime.now()).strftime("%Y-%m-%d_%H%M%S")
    backup = ctx.root / BACKUP_DIR / stamp / part.name
    for rel in part.update + part.remove:
        dest = backup / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(part.target / rel, dest)
    for rel in part.add + part.update:
        dest = part.target / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        own_header = None
        if rel in part.update and _is_slide_file(rel):
            own_header = _HEADER_RE.search(dest.read_bytes())
        shutil.copy2(part.source / rel, dest)
        if own_header:
            # keep the project's own "Included in decks" line; SlideMage keeps it
            dest.write_bytes(_HEADER_RE.sub(
                lambda _m: own_header.group(0), dest.read_bytes(), count=1))
    for rel in part.remove:
        (part.target / rel).unlink()

    data = read_manifest(ctx.root)
    entry = {"app_version": app_version, "files": dict(part.bundle_hashes)}
    if part.name == FRAMEWORK:
        entry["dir"] = _relative_dir(ctx.root, part.target)
    data[part.name] = entry
    data.pop("dismissed_app_version", None)
    write_manifest(ctx.root, data)

    if part.name == MANUAL:
        _merge_slide_ids(ctx.root, part)
        _merge_image_descriptions(ctx, part)
    return backup


def _read_ids(csv_path: Path) -> list[str]:
    try:
        lines = csv_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    return [line.strip().strip('"') for line in lines[1:] if line.strip()]


def _merge_slide_ids(project_root: Path, part: Part) -> None:
    """Append the manual's slide ids the project's slide_ids.csv lacks, in
    slide_ids.append_slide_id()'s format (quoted, CRLF)."""
    csv_path = project_root / "slide_ids.csv"
    have = {i.lower() for i in _read_ids(csv_path)}
    manual_ids = {Path(rel).name.split("-", 1)[0] for rel in part.bundle_hashes
                  if rel.startswith("slides/")}
    missing = [i for i in _read_ids(part.source / "slide_ids.csv")
               if i in manual_ids and i.lower() not in have]
    if not missing:
        return
    if not csv_path.exists():
        csv_path.write_text('"id"\r\n', encoding="utf-8", newline="")
    with open(csv_path, "a", encoding="utf-8", newline="") as f:
        for slide_id in missing:
            f.write(f'"{slide_id}"\r\n')


def _merge_image_descriptions(ctx: ProjectContext, part: Part) -> None:
    """Add the manual's image descriptions the project lacks; replace the
    unreviewed descriptions of images this update replaced. Goes through
    alt_images (the running app's project store, which regenerates the CSV)."""
    from . import alt_images

    try:
        raw = json.loads((part.source / "media" / "alt-text.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    bundled = {image: alt_images.entry_from_dict(image, d)
               for image, d in raw.get("images", raw).items()}
    replaced = set(part.update) | set(part.add)

    def mutate(entries) -> bool:
        changed = False
        for image, entry in bundled.items():
            current = entries.get(image)
            if current is None or (image in replaced
                                   and current.status != alt_images.STATUS_REVIEWED):
                entries[image] = entry
                changed = True
        return changed

    alt_images.update_store(ctx, mutate)


def summary_lines(part: Part) -> list[str]:
    """Human-readable lines for the dialog and the log."""
    if part.new_install:
        lines = [f"{part.label}: not in this project yet -- adds "
                 f"{len(part.add)} files (the deck decks/slidemage-manual.tex, its "
                 "slides, code snippets and images); existing files are never overwritten."]
    else:
        counts = []
        if part.update:
            counts.append(f"{len(part.update)} changed")
        if part.add:
            counts.append(f"{len(part.add)} new")
        if part.remove:
            counts.append(f"{len(part.remove)} no longer used")
        where = f" ({part.target})" if part.name == FRAMEWORK else ""
        lines = [f"{part.label}{where}: {', '.join(counts)} file(s)."]
        if part.adopted and part.name == FRAMEWORK and part.update:
            lines.append("  (made before SlideMage tracked its copies: every file that "
                         "differs from this version is replaced)")
    if part.kept:
        shown = ", ".join(part.kept[:4]) + (" ..." if len(part.kept) > 4 else "")
        lines.append(f"  Kept as they are ({len(part.kept)}, changed in this project): {shown}")
    return lines
