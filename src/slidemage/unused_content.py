# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Find and archive media/ and slides/ files nothing references anymore.

Two independent scans (find_unused_media(), find_unused_slides()), archived by archive_files():

- media/: a file is "in use" if any slides/*.tex file that is itself in
  use (see below) actually \\includegraphics{}s it (or similar -- \\chapterlogo{}, \\fullbleedframe{},
  \\begin{sideimageframe}{}{}, etc. all just take a bare "media/<name>"
  argument, so this looks for that literal substring rather than
  enumerating every macro that can carry one). A reference can omit the
  extension (LaTeX's own default-extension search, e.g.
  \\includegraphics{media/foo} with no extension) -- confirmed directly:
  slides/vpk-Collateralized-Debt-Obligations-current.tex does exactly this
  for media/midjourney-bankers-slicing-bonds.jpeg. Every media/ file is
  also grouped with every other file sharing its filename stem (e.g.
  chart-portfolio-frontier.svg and chart-portfolio-frontier.pdf); if any
  member of a stem group is used, the whole group counts as used, even
  though nothing ever references the .svg/.eps source directly --
  LaTeX/lualatex can only \\includegraphics the derived PDF, so a vector
  source would otherwise always look unused despite being exactly the
  thing worth keeping.

- slides/: a slides/<id>-current.tex or slides/<id>-vX-Y-Z.tex file is "in
  use" if actually \\slide{}/\\conditionalslide{}/\\omitslide{}/
  \\slidestep{}/\\slideversion{}/\\omitslideversion{}-ed from any *.tex file
  directly inside decks/, decks/archive/, or blocks/ -- deliberately every *.tex file
  there,
  not just ones with \\documentclass (i.e. not deck_scan.scan_decks()):
  decks/test-slides.tex is a shared \\input{}-ed fragment with real
  \\slide{}/\\omitslide{} calls of its own (test.tex/test-student.tex and the other test decks all \\input{} it rather than listing slides
  directly), so it has to be scanned too or its slides would look unused.

A 2026-09-27 direct report found two real false positives from this batch
run, both fixed here:

- \\slidestep{id-slug}[versions]{steps} (added to the project 2026-09-20)
  was never added to the slides/ scan's own macro list, so a slide
  referenced *only* via \\slidestep (e.g. IA2's 8gc, the Masterdeck's egk,
  test-slides.tex's own ZZH demo) looked completely unreferenced and got
  archived, even though a real deck compile still needs it.
- media/alt-text.json/.csv (the accessibility image-description store --
  see README.md's "Screen-reader accessibility"/"Describing images") sit
  directly inside media/, but are never \\includegraphics{}d -- they're
  read directly by SlideMage/SlideMage_alt.lua, not referenced as a
  literal "media/<name>" string in any slide, so the media/ scan always
  treated them as unused. MEDIA_NEVER_UNUSED below is the fix: filenames
  excluded from the media/ scan outright, regardless of whether anything
  references them by name.

Both scans strip LaTeX comments first (2026-08-25, direct instruction --
previously a commented-out reference kept a file "in use" indefinitely,
silently masking otherwise-genuinely-unused content; now a reference only
counts if it's live). Neither scan looks inside slides/archive/ or
media/archive/ themselves (once archived, a file is out of scope until
moved back by hand).
"""
from __future__ import annotations

import os
import re
import shutil
from pathlib import Path
from typing import Callable, Iterable

from . import ai_review, alt_archive, alt_images, deck_language, languages, library_data, sm_rename
from .progress import Progress
from .project import ProjectContext
from .slide_language import CURRENT_SUFFIX, bare_id, current_name, current_path_for_bare_id
from .tex_source import COMMENT_RE


# Never candidates for archiving, regardless of whether any slide's own
# text mentions them by name -- see the module docstring's 2026-09-27 entry.
MEDIA_NEVER_UNUSED = {"alt-text.json", "alt-text.csv"}

MEDIA_REF_RE = re.compile(r"media/([\w][\w.-]*)")
# These files belong to SlideMage's accessibility editor, not to a deck's
# media collection. In particular alt-text.json contains authored
# descriptions and must remain at its canonical path for the editor to use.
MEDIA_METADATA_FILENAMES = {"alt-text.json", "alt-text.csv"}


def _is_media_metadata_filename(name: str) -> bool:
    return (
        name in MEDIA_METADATA_FILENAMES
        or (name.startswith(".alt-text.json.") and name.endswith(".tmp"))
    )


def _strip_comments(text: str) -> str:
    """Text with every unescaped '%...' comment tail removed, so a
    reference that only exists inside a commented-out line no longer
    counts as "in use" -- see module docstring."""
    return COMMENT_RE.sub("", text)

LogCallback = Callable[[str], None]


def _deck_texts(ctx: ProjectContext) -> list[str]:
    """Text of decks and blocks, with comments and generated wrappers excluded."""
    return [_strip_comments(path.read_text(encoding="utf-8", errors="replace"))
            for path in (*(p for p in deck_language.deck_files(ctx) if not p.name.startswith("_")),
                         *deck_language.block_files(ctx))]


def slide_filenames_in(ctx: ProjectContext, text: str) -> set[str]:
    """Every slides/*.tex filename the \\slide{}-family calls of this deck text load, the
    translation partners (any language) of each included. The text is read as it is: a deck's
    commented-out calls count unless the comments were stripped first."""
    from . import deck_language
    used: set[str] = set()
    calls = deck_language.calls_in(text, [], comments=True)
    # Keep explicit pins even when a translation call is folded into another slot.
    used.update(call.source_filename for call in calls)
    for language in languages.project_languages(ctx).codes:
        for slot in deck_language.slots(ctx, calls, language):
            used.add(slot.call.source_filename)
            if slot.related_ids:
                # Current headers identify the partner even when the call pins a version.
                used.add(current_name(slot.original.id_slug))
    return used


def find_used_slide_filenames(ctx: ProjectContext) -> set[str]:
    """Every slides/*.tex filename referenced by a deck or kept in the library pool."""
    used: set[str] = set()
    for text in _deck_texts(ctx):
        used |= slide_filenames_in(ctx, text)
    pool = library_data.read(ctx).pool
    if pool:
        ids = library_data.group_ids(ctx)
        used.update(path.name for path in ctx.slides_dir.glob("*-current.tex")
                    if ids.get(path.name.split("-", 1)[0]) in pool)
    return used


def find_unused_slides(ctx: ProjectContext) -> list[Path]:
    """slides/*.tex files not referenced by a deck or kept in the library pool."""
    if not ctx.slides_dir.is_dir():
        return []
    used = find_used_slide_filenames(ctx)
    return sorted(p for p in ctx.slides_dir.glob("*.tex") if p.name not in used)


def media_references(ctx: ProjectContext, texts: Iterable[str]) -> tuple[set[str], set[str]]:
    """(the media/ filenames these texts use, the "media/<name>" references that match no file).
    Used means referenced directly, via a bare stem, or by sharing a stem with a file that is --
    see module docstring."""
    media_files = [p for p in ctx.media_dir.iterdir() if p.is_file()] if ctx.media_dir.is_dir() else []
    by_name = {p.name: p for p in media_files}
    by_stem: dict[str, list[Path]] = {}
    for p in media_files:
        by_stem.setdefault(p.stem, []).append(p)

    directly_used: set[str] = set()
    missing: set[str] = set()
    for text in texts:
        for token in MEDIA_REF_RE.findall(_strip_comments(text)):
            if token in by_name:
                directly_used.add(token)
            elif token in by_stem:
                # No extension in the reference -- any file with this stem
                # could be the one LaTeX's default-extension search picks,
                # so treat them all as used rather than guessing which.
                directly_used.update(p.name for p in by_stem[token])
            else:
                missing.add(f"media/{token}")

    used: set[str] = set()
    for siblings in by_stem.values():
        if any(p.name in directly_used for p in siblings):
            used.update(p.name for p in siblings)
    return used, missing


def find_used_media_filenames(ctx: ProjectContext) -> set[str]:
    """Every media/ filename actually referenced by a slide that is itself in
    use. A slide that is about to be archived does not keep its images
    (v5.14.2, direct report: one click archived the unused slides, and the
    next click found an image only one of those slides had used -- the media
    scan read every slide file, the ones being archived in the same run
    included)."""
    if not ctx.slides_dir.is_dir():
        return set()
    used_slides = find_used_slide_filenames(ctx)
    return media_references(ctx, (
        path.read_text(encoding="utf-8", errors="replace")
        for path in ctx.slides_dir.glob("*.tex") if path.name in used_slides))[0]


def find_unused_media(ctx: ProjectContext) -> list[Path]:
    """media/ files not referenced by any slide, directly or via a
    same-stem sibling that is."""
    if not ctx.media_dir.is_dir():
        return []
    used = find_used_media_filenames(ctx)
    return sorted(
        p for p in ctx.media_dir.iterdir()
        if p.is_file()
        and p.name not in used
        and p.name not in MEDIA_NEVER_UNUSED
        and not _is_media_metadata_filename(p.name)
    )


COPY_SAME = "same"          # archive/ already holds a byte-identical file of that name
COPY_OLDER = "older"        # the archived one differs only in the SM names (sm_rename) and in comments
COPY_DIFFERS = "differs"    # archive/ holds a file of that name with other differences: never overwritten


def _code_lines(text: str) -> list[str]:
    """The lines of a .tex text without comments and without the lines that held nothing else."""
    lines = (COMMENT_RE.sub("", line).rstrip() for line in text.splitlines())
    return [line for line in lines if line.strip()]


def archive_copy_state(path: Path, archive_dir: Path) -> str | None:
    """How the file of the same name in `archive_dir` relates to `path`: None when there is none, else COPY_SAME,
    COPY_OLDER (a .tex file whose archived text only lacks what the file has gained since: the SlideMage names
    sm_rename would give it, and comments such as the generated list of the decks that include the slide; its
    code is the same, so only comments of the archived copy are lost by replacing it) or COPY_DIFFERS."""
    dest = archive_dir / path.name
    if not dest.is_file():
        return None
    old, new = dest.read_bytes(), path.read_bytes()
    if old == new:
        return COPY_SAME
    if path.suffix == ".tex":
        try:
            migrated = sm_rename.rename_identifiers(sm_rename.rename_text(old.decode("utf-8")))
            if _code_lines(migrated) == _code_lines(new.decode("utf-8")):
                return COPY_OLDER
        except UnicodeDecodeError:
            pass
    return COPY_DIFFERS


def _archive_files(
    files: list[Path], archive_dir: Path, kind: str, log: LogCallback, step: Callable[[], None]
) -> int:
    """kind: singular noun for one file, e.g. "media file" or "slide". `step()` follows each file. A file whose
    name is in archive/ already is not skipped without a word, as it used to be (it stayed in its folder and was
    listed again and again): an identical one is removed from its folder, an older archived text is replaced by
    this file, and one that differs otherwise is left where it is and said so."""
    if not files:
        log(f"No unused {kind}s found.")
        return 0
    archive_dir.mkdir(parents=True, exist_ok=True)
    moved = 0
    for path in files:
        dest = archive_dir / path.name
        state = archive_copy_state(path, archive_dir)
        if state == COPY_SAME:
            path.unlink()
            log(f"Archived {kind}: {path.name} (an identical copy was in {archive_dir.name}/ already)")
            moved += 1
        elif state == COPY_OLDER:
            os.replace(path, dest)
            log(f"Archived {kind}: {path.name} (replaced the older copy in {archive_dir.name}/, which differed only "
                "in SM names and comments)")
            moved += 1
        elif state == COPY_DIFFERS:
            log(f"Left {path.name} where it is -- {archive_dir.name}/ holds a different file of that name")
        else:
            shutil.move(str(path), str(dest))
            log(f"Archived {kind}: {path.name}")
            moved += 1
        step()
    return moved


def _archive_alt_text(ctx: ProjectContext, media: list[Path], slides: list[Path], log: LogCallback) -> None:
    """What the image store holds for the files just moved goes to the alt-text archive: a slide that has no current
    file any more (a moved frozen version of a live slide changes nothing) with its own takeaways, reviewed stamps
    and summary, then the entry of each moved media file. Not a reason to fail the move: it has happened."""
    gone = {bare_id(p.name): p.name[: -len(CURRENT_SUFFIX)] for p in slides
            if p.name.endswith(CURRENT_SUFFIX) and current_path_for_bare_id(ctx, bare_id(p.name)) is None}
    try:
        result = alt_archive.archive_slides(ctx, sorted(gone.items()), alt_archive.REASON_SLIDE_ARCHIVED)
        images = [path.relative_to(ctx.root).as_posix() for path in media]
        archived = alt_archive.archive_images(ctx, images, alt_archive.REASON_IMAGE_ARCHIVED)
    except alt_images.NewerStoreError as exc:     # also UnreadableStoreError: a damaged store or archive
        log(f"Image descriptions were not moved to the alt-text archive: {exc}")
        return
    except OSError as exc:
        log(f"Image descriptions were not moved to the alt-text archive: {exc}")
        return
    if result.slides or result.images or archived:
        log(f"Moved to the alt-text archive: data of {len(result.slides)} slide(s), "
            f"{len(result.images) + len(archived)} image description(s)")


def _after_archiving(ctx: ProjectContext, media: list[Path], slides: list[Path], log: LogCallback) -> None:
    """What follows the files of these lists that have left their folder: their slides count as reviewed, their
    image descriptions go to the alt-text archive."""
    ai_review.mark_reviewed(ctx, [p for p in slides if not p.exists()])
    _archive_alt_text(ctx, [p for p in media if not p.exists()], [p for p in slides if not p.exists()], log)


KEEP_ARCHIVED = "archived"     # settle_archived_copy(): the copy in archive/ stays, the file goes
KEEP_FILE = "file"             # the file replaces the copy in archive/


def settle_archived_copy(ctx: ProjectContext, path: Path, keep: str, log: LogCallback,
                         trash: Callable[[Path], bool] | None = None) -> str | None:
    """For a file whose name archive/ holds with other content (COPY_DIFFERS): keep one of the two in archive/. The
    other goes to the Recycle Bin (`trash`, default deck_snapshot.move_to_trash), never deleted for good; when it
    can't, nothing changes. KEEP_FILE then archives the file as usual; KEEP_ARCHIVED leaves the archived copy, and
    the file counts as archived (review marks, image descriptions). Returns the problem, or None when it is done."""
    if trash is None:
        from .deck_snapshot import move_to_trash as trash
    archive_dir = path.parent / "archive"
    archived = archive_dir / path.name
    if not path.is_file() or not archived.is_file():
        return f"{path.name} or its copy in {path.parent.name}/archive/ is gone"
    loser = archived if keep == KEEP_FILE else path
    if not trash(loser):
        return f"Couldn't move {loser.relative_to(ctx.root).as_posix()} to the Recycle Bin; nothing was changed"
    media, slides = ([path], []) if path.parent == ctx.media_dir else ([], [path])
    if keep == KEEP_FILE:
        log(f"Moved the archived copy of {path.name} to the Recycle Bin")
        archive_files(ctx, media, slides, log)
    else:
        log(f"Kept the archived copy of {path.name}; moved {path.relative_to(ctx.root).as_posix()} "
            "to the Recycle Bin")
        _after_archiving(ctx, media, slides, log)
    return None


def archive_files(ctx: ProjectContext, media: list[Path], slides: list[Path], log: LogCallback,
                  on_progress: Callable[[Progress], None] | None = None) -> tuple[int, int]:
    """Move these media/ files into media/archive/ and these slides/ files into slides/archive/.
    Returns (media moved, slides moved). `on_progress` gets one step per file."""
    total, seen = len(media) + len(slides), 0

    def step() -> None:
        nonlocal seen
        seen += 1
        if on_progress:
            on_progress(Progress.step(seen, total, "Moving"))

    media_moved = _archive_files(media, ctx.media_dir / "archive", "media file", log, step)
    slides_moved = _archive_files(slides, ctx.slides_dir / "archive", "slide", log, step)
    _after_archiving(ctx, media, slides, log)
    log(
        f"==== Archive unused content done: {media_moved} media file(s), "
        f"{slides_moved} slide(s) moved ===="
    )
    return media_moved, slides_moved
