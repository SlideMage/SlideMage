# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The archive of image descriptions and slide data nothing in the project uses any more:
`media/archive/alt-text-archive.json`.

The live store (`media/alt-text.json`, alt_images.py) holds what the slides in `slides/` need. When a slide is
deleted or archived, or an image is archived or replaced, what the store held for it is moved here instead of being
dropped or left to go stale, so every description a person or a model wrote stays retrievable and the live store
stays lean. `media/archive/` is already outside every scan, travels with the archived images and is in git.

Two kinds of record, each a list of snapshots per key (oldest first, newest last):

    {
      "version": 1,
      "images": {
        "media/chart-x.png": [
          {"archived": "2026-11-21", "reason": "slide deleted", "slides": ["3px"], "entry": {<as in alt-text.json>}}
        ]
      },
      "slides": {
        "3px": [
          {"archived": "2026-11-21", "reason": "slide deleted", "name": "3px-EN-Demo",
           "summary": "...", "uses": {"media/chart-x.png": {"takeaway": {"en": "..."}, "reviewed": "...", "hash": "..."}}}
        ]
      }
    }

`images` snapshots whole entries (every language, role, source, who drafted it, the slides it was used on);
`slides` snapshots what belongs to one slide alone: its takeaway overrides and reviewed stamps per image and its
summary. A second archiving of the same key adds a snapshot only if its content differs from the newest one, so
nothing is lost when a slide is archived, restored, edited and archived again, and nothing is duplicated.

Nothing here ever deletes without being asked: purge_*() is the only thing that removes a snapshot, and only a
person calls it. The archive is written *before* the live store is changed, so an interruption can leave a
duplicate but never a loss. An archive written by a newer SlideMage is never written (NewerStoreError).
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import date
from typing import Iterable

from . import alt_blocks, alt_images
from .alt_images import ImageEntry, NewerStoreError
from .fileio import read_json, write_json
from .project import ProjectContext

ARCHIVE_VERSION = 1
FILE_NAME = "alt-text-archive.json"

REASON_SLIDE_DELETED = "slide deleted"
REASON_SLIDE_ARCHIVED = "slide archived"
REASON_IMAGE_ARCHIVED = "image archived"
REASON_IMAGE_REPLACED = "image replaced"
REASON_UNUSED = "unused description"

# Written only while holding this one; always taken inside the live store's lock, never the other way round.
_archive_lock = threading.Lock()


def archive_path(ctx: ProjectContext):
    return ctx.media_dir / "archive" / FILE_NAME


def _read(ctx: ProjectContext) -> dict:
    raw = read_json(archive_path(ctx))
    version = raw.get("version", 0)
    if isinstance(version, int) and version > ARCHIVE_VERSION:
        raise NewerStoreError
    return {kind: {key: [s for s in snaps if isinstance(s, dict)] for key, snaps in (raw.get(kind) or {}).items()
                   if isinstance(snaps, list)} for kind in ("images", "slides")}


def _write(ctx: ProjectContext, data: dict) -> None:
    path = archive_path(ctx)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"version": ARCHIVE_VERSION}
    for kind in ("images", "slides"):
        payload[kind] = {key: data[kind][key] for key in sorted(data[kind]) if data[kind][key]}
    write_json(path, payload, sort_keys=False)


def load(ctx: ProjectContext) -> dict:
    """{"images": {image: [snapshot, ...]}, "slides": {bare slide id: [snapshot, ...]}}, empty if there is no archive."""
    return _read(ctx)


def image_snapshots(ctx: ProjectContext, image: str) -> list[dict]:
    return _read(ctx)["images"].get(image, [])


def slide_snapshots(ctx: ProjectContext, bare_id: str) -> list[dict]:
    return _read(ctx)["slides"].get(bare_id, [])


def _same(a: dict, b: dict) -> bool:
    ignore = ("archived", "reason")
    return {k: v for k, v in a.items() if k not in ignore} == {k: v for k, v in b.items() if k not in ignore}


def _add(snapshots: dict[str, list[dict]], key: str, snapshot: dict) -> bool:
    """Append `snapshot` unless it only repeats the newest one. Whether the archive changed."""
    current = snapshots.setdefault(key, [])
    if current and _same(current[-1], snapshot):
        return False
    current.append(snapshot)
    return True


def _worth_keeping(entry: ImageEntry) -> bool:
    """Whether an entry holds anything a person or a model wrote: a bare row made by a scan is not archived."""
    return bool(entry.hint) or any(not text.is_blank for text in entry.texts.values())


def _image_snapshot(entry: ImageEntry, reason: str, today: str) -> dict:
    return {"archived": today, "reason": reason, "slides": sorted(entry.used_on),
            "entry": alt_images.entry_to_dict(entry)}


def referenced_images(ctx: ProjectContext) -> set[str]:
    """The store keys of the images the slides in slides/ reference right now (the archived slides are not read)."""
    entries = alt_images.load_store(ctx)
    found: set[str] = set()
    for row in alt_blocks.scan_slides_raw(ctx):
        for reference in row.images:
            entry = alt_images.lookup(entries, reference)
            if entry is not None:
                found.add(entry.image)
    return found


@dataclass
class ArchiveResult:
    slides: list[str] = field(default_factory=list)        # bare ids whose own data was archived
    images: list[str] = field(default_factory=list)        # whole entries archived because nothing uses them now
    dropped: list[str] = field(default_factory=list)       # empty entries removed without a snapshot

    @property
    def changed(self) -> bool:
        return bool(self.slides or self.images or self.dropped)


def archive_slides(ctx: ProjectContext, slides: Iterable[tuple[str, str]], reason: str = REASON_SLIDE_DELETED, *,
                   referenced: set[str] | None = None, today: str | None = None) -> ArchiveResult:
    """Move what the store holds for these slides -- `(bare id, name)` pairs, the name (its id-slug) for a reader of
    the archive -- into the archive: the slide's takeaway overrides and reviewed stamps per image and its summary.
    An image left with no slide use that no slide in slides/ references either (`referenced`, read when not given)
    is archived whole. Call it after the slide's files are gone from slides/. Raises NewerStoreError for either file
    written by a newer SlideMage."""
    slides = list(slides)
    alt_images.check_writable(ctx)
    today = today or date.today().isoformat()
    notes = alt_images.load_slide_notes(ctx)
    result = ArchiveResult()
    if not slides:
        return result
    live = referenced if referenced is not None else referenced_images(ctx)

    batch = {bare_id for bare_id, _name in slides}

    def mutate(entries: dict[str, ImageEntry]) -> bool:
        with _archive_lock:
            data = _read(ctx)
            touched: set[str] = set()
            changed = False
            for bare_id, name in slides:
                uses = {image: alt_images.use_to_dict(entry.used_on[bare_id]) for image, entry in entries.items()
                        if bare_id in entry.used_on}
                touched.update(uses)
                authored = {image: use for image, use in uses.items() if use}
                summary = notes[bare_id].summary if bare_id in notes else ""
                if authored or summary:
                    changed |= _add(data["slides"], bare_id, {"archived": today, "reason": reason, "name": name,
                                                              "summary": summary, "uses": authored})
                    result.slides.append(bare_id)
            # An image whose every use was by these slides, and which no slide in slides/ references either.
            gone = [image for image in sorted(touched) if set(entries[image].used_on) <= batch and image not in live]
            for image in gone:
                if _worth_keeping(entries[image]):
                    changed |= _add(data["images"], image, _image_snapshot(entries[image], reason, today))
                    result.images.append(image)
                else:
                    result.dropped.append(image)
            if changed:
                _write(ctx, data)   # before the store changes: an interruption leaves a duplicate, never a loss
            for entry in entries.values():
                for bare_id in batch:
                    entry.used_on.pop(bare_id, None)
            for image in gone:
                del entries[image]
        return bool(touched)

    alt_images.update_store(ctx, mutate)
    drop = {bare_id for bare_id, _name in slides if bare_id in notes}
    if drop:
        def drop_notes(current) -> bool:
            gone = [bare_id for bare_id in drop if bare_id in current]
            for bare_id in gone:
                del current[bare_id]
            return bool(gone)
        alt_images.update_slide_notes(ctx, drop_notes)
    return result


def archive_images(ctx: ProjectContext, images: Iterable[str], reason: str = REASON_UNUSED, *,
                   today: str | None = None) -> list[str]:
    """Move these whole entries into the archive (the image was archived or replaced, or a person chose them in the
    review of unused descriptions). An entry without any text goes without a snapshot. Returns the images that got
    a snapshot."""
    wanted = list(dict.fromkeys(images))
    alt_images.check_writable(ctx)
    today = today or date.today().isoformat()
    archived: list[str] = []

    def mutate(entries: dict[str, ImageEntry]) -> bool:
        present = [image for image in wanted if image in entries]
        if not present:
            return False
        with _archive_lock:
            data = _read(ctx)
            for image in present:
                if _worth_keeping(entries[image]):
                    _add(data["images"], image, _image_snapshot(entries[image], reason, today))
                    archived.append(image)
            _write(ctx, data)
        for image in present:
            del entries[image]
        return True

    alt_images.update_store(ctx, mutate)
    return archived


def unreferenced_entries(ctx: ProjectContext) -> list[str]:
    """The entries no slide in slides/ references: the ones for a person to review before they are archived (a new
    image not yet placed on a slide is among them, so nothing archives these on its own)."""
    live = referenced_images(ctx)
    return sorted(image for image in alt_images.load_store(ctx) if image not in live)


# --------------------------------------------------------------------------
# Restore and purge
# --------------------------------------------------------------------------

def _blank(entry: ImageEntry) -> bool:
    return not _worth_keeping(entry)


def restore_image(ctx: ProjectContext, image: str, index: int = -1, *, overwrite: bool = False) -> str:
    """Put an archived entry (the newest snapshot, or snapshot `index`) back into the store. Text that is there now
    is kept unless `overwrite`: the result is "restored", "kept" (the entry has text and overwrite was not asked)
    or "none" (no such snapshot). The slide uses in the store now win over the archived ones. The snapshot stays in
    the archive."""
    snapshots = image_snapshots(ctx, image)
    if not snapshots or not -len(snapshots) <= index < len(snapshots):
        return "none"
    archived = alt_images.entry_from_dict(image, snapshots[index]["entry"])
    outcome = "restored"

    def mutate(entries: dict[str, ImageEntry]) -> bool:
        nonlocal outcome
        current = entries.get(image)
        if current is not None and not _blank(current) and not overwrite:
            outcome = "kept"
            return False
        if current is not None:
            archived.used_on = {**archived.used_on, **current.used_on}
        entries[image] = archived
        return True

    alt_images.update_store(ctx, mutate)
    return outcome


@dataclass
class RestoreResult:
    uses: list[str] = field(default_factory=list)       # images whose slide use came back
    missing: list[str] = field(default_factory=list)    # images with no entry in the store (restore those first)
    summary: bool = False

    @property
    def found(self) -> bool:
        return bool(self.uses or self.summary or self.missing)


def restore_slide(ctx: ProjectContext, bare_id: str, index: int = -1) -> RestoreResult:
    """Put an archived slide's own data back: its takeaway overrides and reviewed stamps on the images it used (those
    with an entry in the store) and its summary. Whatever the slide has now is kept."""
    result = RestoreResult()
    snapshots = slide_snapshots(ctx, bare_id)
    if not snapshots or not -len(snapshots) <= index < len(snapshots):
        return result
    snapshot = snapshots[index]

    def mutate(entries: dict[str, ImageEntry]) -> bool:
        changed = False
        for image, use in (snapshot.get("uses") or {}).items():
            entry = entries.get(image)
            if entry is None:
                result.missing.append(image)
                continue
            have = entry.used_on.get(bare_id)
            if have is None or not alt_images.use_to_dict(have):
                entry.used_on[bare_id] = alt_images.use_from_dict(use)
                result.uses.append(image)
                changed = True
        return changed

    alt_images.update_store(ctx, mutate)
    summary = snapshot.get("summary") or ""
    if summary:
        def add_summary(notes) -> bool:
            if bare_id in notes and notes[bare_id].summary:
                return False
            notes[bare_id] = alt_images.SlideNotes(summary=summary)
            result.summary = True
            return True
        alt_images.update_slide_notes(ctx, add_summary)
    return result


def _purge(ctx: ProjectContext, kind: str, key: str, index: int | None) -> int:
    with _archive_lock:
        data = _read(ctx)
        snapshots = data[kind].get(key, [])
        if not snapshots:
            return 0
        if index is None:
            removed = len(snapshots)
            data[kind][key] = []
        elif -len(snapshots) <= index < len(snapshots):
            del snapshots[index]
            removed = 1
        else:
            return 0
        _write(ctx, data)
        return removed


def purge_image(ctx: ProjectContext, image: str, index: int | None = None) -> int:
    """Delete snapshot `index` of an archived image (all of them when None) for good. Only a person's choice calls
    this. Returns how many snapshots went."""
    return _purge(ctx, "images", image, index)


def purge_slide(ctx: ProjectContext, bare_id: str, index: int | None = None) -> int:
    """The same for an archived slide's data."""
    return _purge(ctx, "slides", bare_id, index)
