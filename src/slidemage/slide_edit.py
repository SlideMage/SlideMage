# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Slide rename and delete that complete or change nothing (A4, docs/plans/rename-delete-transactions.md).

A change is first planned from reads alone (a SlideEdit: the files to move, the exact text of every deck and slide
that changes, the stores to update, each with the change that undoes it), then applied in an order that can be
undone: the id is registered, the texts are written (fileio.write_texts restores what it wrote on failure), the
files are moved, the stores are updated. When a step fails, everything done before it is put back and the error
(SlideEditError) says so; when the undo fails too it says which files are in which state. Derived text (the deck
headers, the translation links) is rebuilt at the end and a failure there is only a warning.

A delete moves the files to .slidemage/trash/<time>-<id>/ first and removes that folder after everything else
worked, because deleting a file cannot be undone.
"""
from __future__ import annotations

import contextlib
import logging
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from . import ai_review, alt_archive, alt_images, deck_editor, deck_headers, deck_language, fileio, library_data
from . import processes, slide_ids, slide_language
from .fileio import read_text_exact
from .processes import move_file
from .project import ProjectContext

log = logging.getLogger(__name__)


class SlideEditError(OSError):
    """A rename or delete that did not complete. `clean` is True when everything was put back (nothing changed)."""

    def __init__(self, message: str, clean: bool = True) -> None:
        super().__init__(message)
        self.clean = clean


@dataclass
class StoreChange:
    """One store update. `undo` is the inverse (new -> old) and must do no harm when applied to a store that
    was not changed. `fatal`: its failure rolls everything back (alt-text and library hold authored data); a
    failure of the others (ai_review marks) keeps the change and is shown as a warning."""
    name: str
    apply: Callable[[], None]
    undo: Callable[[], None]
    fatal: bool = True


@dataclass
class SlideEditResult:
    mapping: dict[str, str] = field(default_factory=dict)
    files: int = 0
    references: int = 0
    warnings: list[str] = field(default_factory=list)


@dataclass
class SlideEdit:
    ctx: ProjectContext
    what: str
    moves: list[tuple[Path, Path]] = field(default_factory=list)
    texts: dict[Path, tuple[str, str]] = field(default_factory=dict)
    stores: list[StoreChange] = field(default_factory=list)
    register: Optional[str] = None
    trash: Optional[Path] = None              # delete: the folder the files are moved into
    mapping: dict[str, str] = field(default_factory=dict)
    references: int = 0

    def paths(self) -> list[Path]:
        """Every file this edit changes or moves: an open editor tab holding unsaved edits of one of them would
        go stale (the UI refuses first, SAVE_FIRST)."""
        found = dict.fromkeys([*self.texts, *(src for src, _dest in self.moves),
                               *(dest for _src, dest in self.moves if self.trash is None)])
        return list(found)


# -- plans (reads only) ----------------------------------------------------------------------------------------

def _check_stores(ctx: ProjectContext) -> bool:
    """Raise (UnreadableStoreError / UnreadableFileError, both ValueErrors) before anything changes when a store
    is damaged. Returns whether the image store may be written: False when a newer SlideMage wrote it (it is left
    as it is, like before)."""
    alt_ok = True
    try:
        alt_images.check_writable(ctx)
    except alt_images.UnreadableStoreError:
        raise
    except alt_images.NewerStoreError:
        alt_ok = False
    library_data.check_writable(ctx)
    ai_review.check_writable(ctx)
    return alt_ok


def plan_id_slug_rename(ctx: ProjectContext, id_slug: str, new_id_slug: str) -> SlideEdit:
    """<id-slug> -> <new id-slug>: language, slug or untagging (the bare id stays)."""
    plan = SlideEdit(ctx, f"The rename of {id_slug}")
    current_src = ctx.slides_dir / slide_language.current_name(id_slug)
    if not current_src.exists():
        raise FileNotFoundError(f"{current_src} does not exist")
    current_dest = ctx.slides_dir / slide_language.current_name(new_id_slug)
    if current_dest.exists():
        raise FileExistsError(f"{current_dest} already exists")
    plan.moves.append((current_src, current_dest))
    for version_src in ctx.slides_dir.glob(f"{id_slug}-v*.tex"):
        version_dest = ctx.slides_dir / f"{new_id_slug}{version_src.name[len(id_slug):]}"
        if version_dest.exists():
            raise FileExistsError(f"{version_dest} already exists")
        plan.moves.append((version_src, version_dest))
    ai_review.check_writable(ctx)
    plan.mapping = {id_slug: new_id_slug}
    _plan_call_rewrites(plan)
    plan.stores.append(_review_rename(ctx, plan.moves))
    return plan


def plan_id_rename(ctx: ProjectContext, old_id: str, new_id: str, reserved: bool = False) -> SlideEdit:
    """<old id> -> <new id> for every slide file, deck call, \\hyperlink, store entry and slide_ids.csv."""
    check = slide_ids.reserved_id_reason if reserved else slide_ids.regular_id_reason
    reason = check(new_id)
    if reason:
        raise ValueError(f"{new_id!r} is not a legal slide id: {reason}")
    first_ok = new_id[:1] in (slide_ids.RESERVED_FIRST_DIGITS if reserved else slide_ids.ID_ALPHABET)
    if len(new_id) != slide_ids.ID_LENGTH or not first_ok or not all(c in slide_ids.ID_ALPHABET for c in new_id[1:]):
        raise ValueError(f"{new_id!r} must be {slide_ids.ID_LENGTH} characters from {slide_ids.ID_ALPHABET!r}")
    taken = slide_ids.existing_ids_from_csv(ctx) | slide_ids.existing_ids_from_disk(ctx)
    if new_id.lower() in {i.lower() for i in taken}:
        raise FileExistsError(f"slide id {new_id!r} is already in use")
    old_files = sorted(ctx.slides_dir.glob(f"{old_id}-*.tex"))
    if not old_files:
        raise FileNotFoundError(f"no slides/{old_id}-*.tex")
    alt_ok = _check_stores(ctx)       # before anything changes: a damaged store stops the rename here

    plan = SlideEdit(ctx, f"The rename of {old_id}", register=new_id)
    for src in old_files:
        dest = ctx.slides_dir / (new_id + src.name[len(old_id):])
        if dest.exists():
            raise FileExistsError(f"{dest} already exists")
        plan.moves.append((src, dest))
        if src.name.endswith(slide_language.CURRENT_SUFFIX):
            old_slug = src.name[: -len(slide_language.CURRENT_SUFFIX)]
            plan.mapping[old_slug] = new_id + old_slug[len(old_id):]
    _plan_call_rewrites(plan)

    link = re.compile(r"(\\hyperlink\{)" + re.escape(old_id) + r"(\})")
    for path in sorted(ctx.slides_dir.glob("*.tex")):
        text = read_text_exact(path)
        new_text = link.sub(r"\g<1>" + new_id + r"\g<2>", text)
        if new_text != text:
            plan.texts[path] = (text, new_text)

    if alt_ok:
        plan.stores.append(_alt_move(ctx, old_id, new_id))
    plan.stores.append(_library_move(ctx, old_id, new_id))
    plan.stores.append(_review_rename(ctx, plan.moves))
    return plan


def plan_delete(ctx: ProjectContext, id_slug: str, remove_deck_references: bool = True) -> SlideEdit:
    """Delete every file of the slide, its deck calls and its store entries (moved to the archive)."""
    current = ctx.slides_dir / slide_language.current_name(id_slug)
    if not current.exists():
        raise FileNotFoundError(f"{current} does not exist")
    alt_ok = _check_stores(ctx)       # before anything is deleted
    plan = SlideEdit(ctx, f"The deletion of {id_slug}")
    stamp = time.strftime("%Y%m%d-%H%M%S")
    plan.trash = ctx.settings_dir / "trash" / f"{stamp}-{id_slug}"
    n = 1
    while plan.trash.exists():
        n += 1
        plan.trash = ctx.settings_dir / "trash" / f"{stamp}-{id_slug}-{n}"
    plan.moves = [(path, plan.trash / path.name) for path in sorted(ctx.slides_dir.glob(f"{id_slug}-*.tex"))]
    if remove_deck_references:
        for deck_path in deck_language.call_files(ctx):
            text = read_text_exact(deck_path)
            new_text, count = deck_editor.remove_call_references(text, id_slug)
            if count:
                plan.texts[deck_path] = (text, new_text)
                plan.references += count
    bare_id = id_slug.split("-", 1)[0]
    if alt_ok:
        plan.stores.append(_snapshot_store(
            "alt-text archive",
            [alt_archive.archive_path(ctx), ctx.media_dir / "alt-text.json", ctx.media_dir / "alt-text.csv"],
            lambda: alt_archive.archive_slides(ctx, [(bare_id, id_slug)], alt_archive.REASON_SLIDE_DELETED)))
    plan.stores.append(_snapshot_store("library", [ctx.settings_dir / "library.json"],
                                       lambda: library_data.update(ctx, lambda _data: None)))
    plan.stores.append(StoreChange("review marks", lambda: ai_review.mark_reviewed(ctx, [p for p, _ in plan.moves]),
                                   lambda: None, fatal=False))
    return plan


def _plan_call_rewrites(plan: SlideEdit) -> None:
    for deck_path in deck_language.call_files(plan.ctx):
        text = read_text_exact(deck_path)
        new_text, count = deck_editor.rewrite_call_references(text, plan.mapping)
        if count:
            plan.texts[deck_path] = (text, new_text)
            plan.references += count


# -- store changes ---------------------------------------------------------------------------------------------

def _review_rename(ctx: ProjectContext, moves: list[tuple[Path, Path]]) -> StoreChange:
    def apply() -> None:
        for src, dest in moves:
            ai_review.rename(ctx, src, dest)

    def undo() -> None:
        for src, dest in reversed(moves):
            ai_review.rename(ctx, dest, src)
    return StoreChange("review marks", apply, undo, fatal=False)


def _alt_move(ctx: ProjectContext, old_id: str, new_id: str) -> StoreChange:
    def move(a: str, b: str) -> Callable[[], None]:
        def uses(entries) -> bool:
            changed = False
            for entry in entries.values():
                if a in entry.used_on:
                    entry.used_on[b] = entry.used_on.pop(a)
                    changed = True
            return changed

        def notes(current) -> bool:
            if a in current:
                current[b] = current.pop(a)
                return True
            return False
        return lambda: alt_images.update_both(ctx, uses, notes)
    return StoreChange("image descriptions", move(old_id, new_id), move(new_id, old_id))


def _library_move(ctx: ProjectContext, old_id: str, new_id: str) -> StoreChange:
    def move(a: str, b: str) -> Callable[[], None]:
        def change(library) -> None:
            for members in (library.pool, library.not_reusable):
                if a in members:
                    members.remove(a)
                    members.add(b)
            if a in library.topics:
                library.topics[b] = library.topics.pop(a)
            library.different_on_purpose = {
                (frozenset(b if i == a else i for i in ids), fingerprint)
                for ids, fingerprint in library.different_on_purpose}
        return lambda: library_data.update(ctx, change)
    return StoreChange("library", move(old_id, new_id), move(new_id, old_id))


def _snapshot_store(name: str, paths: list[Path], run: Callable[[], object]) -> StoreChange:
    """A store whose change has no simple inverse (the archive move, the library prune): undone by putting the
    bytes of its files back."""
    saved: dict[Path, Optional[bytes]] = {}

    def apply() -> None:
        for path in paths:
            saved[path] = path.read_bytes() if path.is_file() else None
        with contextlib.suppress(alt_images.NewerStoreError):   # a newer SlideMage's store is left as it is
            run()

    def undo() -> None:
        for path, data in saved.items():
            if data is None:
                path.unlink(missing_ok=True)
            else:
                fileio.atomic_write(path, data)
    return StoreChange(name, apply, undo)


# -- moves -----------------------------------------------------------------------------------------------------

def _tracked(ctx: ProjectContext, path: Path) -> bool:
    return processes.is_git_repo(ctx.root) and processes.is_git_tracked(path, ctx.root)


def _git(ctx: ProjectContext, *args: str, input: bytes | None = None) -> bytes:
    return subprocess.run(["git", *args], cwd=ctx.root, stdin=subprocess.DEVNULL if input is None else None,
                          input=input, stdout=subprocess.PIPE, check=True,
                          timeout=processes.GIT_TIMEOUT_S, **processes.no_console_kwargs()).stdout


def move_to_trash(ctx: ProjectContext, src: Path, dest: Path, index_entry: bytes) -> None:
    """Take `src` out of the project into the trash folder; a tracked file leaves git's index too (as git rm)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if index_entry:
        _git(ctx, "rm", "-q", "--cached", "-f", "--", str(src.relative_to(ctx.root)))
    try:
        shutil.move(str(src), str(dest))
    except Exception:
        if index_entry:
            with contextlib.suppress(Exception):
                _git(ctx, "update-index", "-z", "--index-info", input=index_entry)
        raise


def move_from_trash(ctx: ProjectContext, src: Path, dest: Path, index_entry: bytes) -> None:
    """Restore the file at `src` and its original Git index records, without staging working edits."""
    shutil.move(str(dest), str(src))
    if index_entry:
        _git(ctx, "update-index", "-z", "--index-info", input=index_entry)


# -- apply -----------------------------------------------------------------------------------------------------

# Windows errors of a file another program holds open (sharing violation) or one the user may not change.
_IN_USE_WINERRORS = (5, 32, 33)
_IN_USE_WORDS = ("permission denied", "access is denied", "zugriff verweigert", "being used by another process",
                 "invalid argument", "resource busy")


def describe_failure(exc: BaseException) -> str:
    """Why a step of a slide edit failed, in words a user can act on: never the raw command line of a git call
    (2026-11-28, a locked file gave "Command ['git', 'mv', ...] returned non-zero exit status 128")."""
    if isinstance(exc, subprocess.CalledProcessError):
        lines = (exc.stderr or b"")
        lines = (lines.decode("utf-8", "replace") if isinstance(lines, bytes) else str(lines)).strip().splitlines()
        detail = lines[-1].removeprefix("fatal: ").strip() if lines else ""
        if not detail or any(word in detail.lower() for word in _IN_USE_WORDS):
            return ("the file is open in another program, or Windows did not allow the change"
                    + (f" (Git: {detail})." if detail else "."))
        return f"Git refused it ({detail})."
    if isinstance(exc, PermissionError) or getattr(exc, "winerror", None) in _IN_USE_WINERRORS:
        reason = getattr(exc, "strerror", None) or str(exc)
        return f"the file is open in another program, or you may not change it ({reason})."
    return f"{exc}"


def apply(plan: SlideEdit) -> SlideEditResult:
    """Carry out `plan`: all of it, or none of it (SlideEditError says which)."""
    ctx = plan.ctx
    result = SlideEditResult(mapping=dict(plan.mapping), files=len(plan.moves), references=plan.references)
    texts_written = False
    moved: list[tuple[Path, Path, bytes]] = []         # (src, dest, original index records)
    index_entries: dict[Path, bytes] = {}
    tried: list[StoreChange] = []

    def fail(step: str, exc: BaseException) -> SlideEditError:
        problems = _undo(plan, moved, tried, texts_written)
        if not problems and plan.trash is not None:
            for folder in (plan.trash, plan.trash.parent):       # empty again: nothing is left behind
                with contextlib.suppress(OSError):
                    folder.rmdir()
        if not problems:
            return SlideEditError(f"{plan.what} failed at {step}: {describe_failure(exc)} Nothing was changed.",
                                  clean=True)
        return SlideEditError(
            f"{plan.what} failed at {step}: {describe_failure(exc)} It could not be fully undone: "
            + "; ".join(problems)
            + ". Move the files back by hand and restore the deck text from git or your sync service's history.",
            clean=False)

    if plan.trash is not None:
        try:
            for src, _dest in plan.moves:
                if _tracked(ctx, src):
                    index_entries[src] = _git(ctx, "--literal-pathspecs", "ls-files", "--stage", "-z", "--",
                                              str(src.relative_to(ctx.root)))
        except Exception as exc:
            raise fail("reading Git's index", exc) from exc

    if plan.register:
        try:
            slide_ids.append_slide_id(ctx, plan.register)    # never undone: a registered id nobody uses is harmless
        except Exception as exc:
            raise fail("registering the new id", exc) from exc
    if plan.texts:
        try:
            fileio.write_texts(plan.texts)
            texts_written = True
        except Exception as exc:
            if isinstance(exc, fileio.PartialWriteError) and len(exc.restored) < len(exc.written):
                raise SlideEditError(f"{plan.what} failed while writing the decks: {exc}", clean=False) from exc
            raise fail("writing the decks", exc) from exc
    for src, dest in plan.moves:
        index_entry = index_entries.get(src, b"")
        try:
            if plan.trash is not None:
                move_to_trash(ctx, src, dest, index_entry)
            else:
                move_file(src, dest, ctx.root)
        except Exception as exc:
            raise fail(f"moving {src.name}", exc) from exc
        moved.append((src, dest, index_entry))
    for change in plan.stores:
        tried.append(change)
        try:
            change.apply()
        except Exception as exc:
            if change.fatal:
                raise fail(f"updating the {change.name}", exc) from exc
            log.exception("%s: the %s could not be updated", plan.what, change.name)
            result.warnings.append(f"The {change.name} could not be updated: {exc}")
    if plan.trash is not None:
        try:
            shutil.rmtree(plan.trash)
        except OSError as exc:
            log.exception("could not remove %s", plan.trash)
            result.warnings.append(f"The deleted files are still in {plan.trash}: {exc}")
    _rebuild_derived(ctx, result)
    return result


def _undo(plan: SlideEdit, moved: list[tuple[Path, Path, bytes]], tried: list[StoreChange],
          texts_written: bool) -> list[str]:
    """Put back what apply() did; the problems that remain, as sentences. The files and decks go back first, then
    the stores, newest first: the library update drops ids that have no slide file, so the old id's file must
    exist again when its entry is moved back."""
    ctx, problems = plan.ctx, []
    for src, dest, index_entry in reversed(moved):
        try:
            if plan.trash is not None:
                move_from_trash(ctx, src, dest, index_entry)
            else:
                move_file(dest, src, ctx.root)
        except Exception as exc:
            problems.append(f"{dest} was moved from {src} and could not be moved back ({exc})")
    if texts_written:
        try:
            fileio.write_texts({path: (after, before) for path, (before, after) in plan.texts.items()})
        except Exception as exc:
            problems.append(f"{', '.join(p.name for p in plan.texts)} keep the new text ({exc})")
    for change in reversed(tried):
        try:
            change.undo()
        except Exception as exc:
            problems.append(f"the {change.name} still holds the new state ({exc})")
    return problems


def _rebuild_derived(ctx: ProjectContext, result: SlideEditResult) -> None:
    """The deck headers and translation links are recomputed from the sources: a failure is a warning only."""
    from . import slide_rename           # imported here: slide_rename wraps this module

    for name, rebuild in (("deck headers", deck_headers.regenerate_headers),
                          ("translation links", slide_rename.regenerate_translation_links)):
        try:
            rebuild(ctx)
        except Exception as exc:
            log.exception("could not update the %s", name)
            result.warnings.append(f"The {name} could not be updated: {exc} They are rebuilt the next time a deck "
                                   "is saved.")
