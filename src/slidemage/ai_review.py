# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Claude's slide changes awaiting explicit review, shared with the hook process.

Every read/modify/write holds the existing OS-owned build_lock on a stable
sidecar, then fileio replaces the JSON atomically. No queue or in-memory copy
can lose another process's mark. Buffer writes supply their actual text.

An edit that supplies the text it replaced also keeps that text, one file per slide in
.slidemage/ai-before/ (the last edit only, kept after the slide is marked reviewed): the
earlier side of Compare rendered for the edits that left no diff card, Claude Code's in the terminal.
"""
from __future__ import annotations

import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from . import alt_blocks, alt_images, deck_language, fileio, slide_language
from .filelock import build_lock
from .project import ProjectContext


def _key(ctx: ProjectContext, path: Path | str) -> str | None:
    path = Path(path)
    path = (path if path.is_absolute() else ctx.root / path).resolve()
    if path.parent != ctx.slides_dir.resolve():
        return None
    try:
        macro, _, _ = slide_language.call_for_slide_path(path)
    except ValueError:
        return None
    return path.relative_to(ctx.root.resolve()).as_posix() if macro == "slide" else None


def check_writable(ctx: ProjectContext) -> None:
    """Raise UnreadableFileError if an update would refuse ai-review.json: for an edit that has to ask first."""
    fileio.read_json_strict(ctx.ai_review_path)


def _update(ctx: ProjectContext, mutate) -> None:
    def change(data: dict):
        before = data.copy()
        mutate(data)
        return data != before
    # Tolerant (a damaged file is replaced), as before: the plan checks writability first (check_writable).
    fileio.JsonStore(ctx.ai_review_path, lock=lambda: build_lock(ctx.ai_review_path.with_suffix(".lock"))
                     ).update(change, strict=False)


def mark(ctx: ProjectContext, path: Path | str, kind: str, source: str, *,
         text: str | None = None, deck: Path | None = None, before: str | None = None) -> None:
    """Mark a live slide; non-slides, frozen files and missing files are ignored. `before` is the text an
    "edit" replaced: it is kept as the slide's last_before() unless it is the text the slide has now."""
    if kind not in ("draft", "translation", "edit"):
        raise ValueError(f"Unknown Claude change kind: {kind}")
    key = _key(ctx, path)
    if key is None or not (ctx.root / key).is_file():
        return
    text = fileio.read_text_exact(ctx.root / key) if text is None else text
    if kind == "edit" and before is not None and before.replace("\r\n", "\n") != text.replace("\r\n", "\n"):
        fileio.atomic_write(ctx.ai_before_dir / Path(key).name, before.replace("\r\n", "\n"))
    entry = dict(by="claude", kind=kind, source=source,
                 since=datetime.now(timezone.utc).isoformat(),
                 text_hash=fileio.text_sha256(text.replace("\r\n", "\n")))

    def mutate(data):
        # Preserve insertion provenance when the slide body is edited later.
        old = data.get(key, {})
        decks = old.get("decks", []) if isinstance(old, dict) else []
        if deck is not None:
            decks = sorted(set(decks) | {deck.resolve().relative_to(ctx.root.resolve()).as_posix()})
        if decks:
            entry["decks"] = decks
        data[key] = entry

    _update(ctx, mutate)


def media_snapshot(ctx: ProjectContext) -> dict[str, list[int]]:
    """The project's image files as {project-relative path: [mtime ns, size]}, JSON-ready for a hook's snapshot.
    Dot-folders and the top-level pdf/ folder (built decks, not images) are skipped, like the files Claude sees."""
    found: dict[str, list[int]] = {}
    pending = [ctx.root]
    while pending:
        folder = pending.pop()
        try:
            entries = list(os.scandir(folder))
        except OSError:
            continue
        for entry in entries:
            try:
                if entry.is_dir(follow_symlinks=False):
                    if not entry.name.startswith(".") and not (folder == ctx.root and entry.name == "pdf"):
                        pending.append(Path(entry.path))
                elif entry.name.lower().endswith(alt_images.IMAGE_SUFFIXES):
                    info = entry.stat()
                    found[Path(entry.path).relative_to(ctx.root).as_posix()] = [info.st_mtime_ns, info.st_size]
            except OSError:
                continue            # gone while scanning
    return found


def _written_names(reference: str) -> set[str]:
    """The files a slide's image reference can mean, in lower case: as written, or with an image suffix added."""
    name = Path(reference).as_posix().casefold()
    return {name, *(name + suffix for suffix in alt_images.IMAGE_SUFFIXES)}


def mark_media_changes(ctx: ProjectContext, before: dict[str, list[int]], source: str) -> list[Path]:
    """Mark the live slides that include an image added, replaced or removed since `before` (media_snapshot).
    A slide already marked keeps its kind; the marked slides' paths are returned."""
    now = media_snapshot(ctx)
    changed = {name.casefold(): name for name in before.keys() | now.keys() if before.get(name) != now.get(name)}
    if not changed:
        return []
    kinds = {key: entry.get("kind", "edit") for key, entry in unreviewed(ctx).items()}
    marked = []
    for slide in sorted(ctx.slides_dir.glob("*.tex")):
        key = _key(ctx, slide)
        if key is None:
            continue
        try:
            references = alt_blocks.referenced_images(fileio.read_text_exact(slide))
        except (OSError, UnicodeDecodeError):
            continue
        used = sorted({changed[name] for reference in references for name in _written_names(reference) & changed.keys()})
        if used:
            mark(ctx, slide, kinds.get(key, "edit"),
                 f"{source}: {', '.join(used[:3])}{', …' if len(used) > 3 else ''}")
            marked.append(slide)
    return marked


def unreviewed(ctx: ProjectContext) -> dict[str, dict]:
    """Project-relative live slide paths and their provenance (always read afresh)."""
    return {key: entry for key, entry in fileio.read_json(ctx.ai_review_path).items()
            if isinstance(entry, dict) and entry.get("by") == "claude"
            and _key(ctx, key) == key and (ctx.root / key).is_file()}


def is_unreviewed(ctx: ProjectContext, path: Path | str) -> bool:
    return _key(ctx, path) in unreviewed(ctx)


def last_before(ctx: ProjectContext, path: Path | str) -> str | None:
    """The text the live slide `path` had before the last AI edit that was recorded with it, else None."""
    key = _key(ctx, path)
    try:
        return fileio.read_text_exact(ctx.ai_before_dir / Path(key).name) if key else None
    except (OSError, UnicodeDecodeError):
        return None


def mark_reviewed(ctx: ProjectContext, paths) -> None:
    keys = {_key(ctx, path) for path in paths}
    _update(ctx, lambda data: [data.pop(key, None) for key in keys])


def rename(ctx: ProjectContext, old: Path, new: Path) -> None:
    old_key, new_key = _key(ctx, old), _key(ctx, new)
    if old_key and new_key and (kept := ctx.ai_before_dir / Path(old_key).name).is_file():
        kept.replace(ctx.ai_before_dir / Path(new_key).name)

    def mutate(data):
        entry = data.pop(old_key, None)
        if entry is not None and new_key is not None:
            data[new_key] = entry

    _update(ctx, mutate)


def inserted_slides(ctx: ProjectContext, path: Path, before: str, after: str, source: str) -> None:
    """Note added calls in decks or blocks on their slide's mark, never on the caller."""
    # A block's first call may still be in an unsaved buffer.
    if path.suffix != ".tex" or (path.resolve() not in {p.resolve() for p in deck_language.call_files(ctx)}
                                 and path.resolve().parent != ctx.blocks_dir.resolve()):
        return
    def calls(text):
        return Counter(call.source_filename for call in deck_language.calls_in(text, [], comments=True))
    for filename in (calls(after) - calls(before)):
        slide = ctx.slides_dir / filename
        entry = unreviewed(ctx).get(_key(ctx, slide), {})
        mark(ctx, slide, entry.get("kind", "edit"), source, deck=path)
