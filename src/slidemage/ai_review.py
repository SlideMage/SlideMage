"""Claude's slide changes awaiting explicit review, shared with the hook process.

Every read/modify/write holds the existing OS-owned build_lock on a stable
sidecar, then fileio replaces the JSON atomically. No queue or in-memory copy
can lose another process's mark. Buffer writes supply their actual text.

An edit that supplies the text it replaced also keeps that text, one file per slide in
.slidemage/ai-before/ (the last edit only, kept after the slide is marked reviewed): the
earlier side of Compare rendered for the edits that left no diff card, Claude Code's in the terminal.
"""
from __future__ import annotations

from collections import Counter
from types import SimpleNamespace
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

from . import deck_editor, fileio, slide_language
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


def _update(ctx: ProjectContext, mutate) -> None:
    with build_lock(ctx.ai_review_path.with_suffix(".lock")):
        data = fileio.read_json(ctx.ai_review_path)
        before = data.copy()
        mutate(data)
        if data != before:
            fileio.write_json(ctx.ai_review_path, data)


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
                 text_hash=sha256(text.replace("\r\n", "\n").encode("utf-8")).hexdigest())

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
    """Note added live deck calls on their slide's mark, never on the deck itself."""
    if path.suffix != ".tex" or not path.resolve().is_relative_to(ctx.decks_dir.resolve()):
        return
    def calls(text):
        return Counter(call.source_filename for call in deck_editor.parse_slide_calls(
            SimpleNamespace(text=text, chapters=[])))
    for filename in (calls(after) - calls(before)):
        slide = ctx.slides_dir / filename
        entry = unreviewed(ctx).get(_key(ctx, slide), {})
        mark(ctx, slide, entry.get("kind", "edit"), source, deck=path)
