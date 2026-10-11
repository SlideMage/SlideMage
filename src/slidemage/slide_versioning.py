"""Automatic per-slide version tracking on save (SlideMage's own
freeze-then-bump workflow, 2026-08-20 direct instruction).

Before this, freezing a slide's outgoing content as a numbered version was
a manual step (R_Slidemaster's slide.archive() / slide.new()'s "before
making a significant revision" convention -- see README.md's "Naming and
versioning convention"). This module automates it: SlideMage's own
Save button, for a slide's own current.tex, asks how significant the
change is (major/minor/patch/overwrite) and does the freeze + version-bump
bookkeeping itself. The frozen "-vX-Y-Z.tex" file is always a byte-exact
copy of whatever was on disk immediately before the save (shutil.copy2,
same as deck_duplicate.py) -- never rewritten, never re-encoded.

The tracked version itself lives inside current.tex as a
\\setSlideVersion{X-Y-Z} line (Slidemaster_preamble_base.tex), the same
"tool-managed header line" pattern as the "%% Included in decks: ..."
line add_deck_headers.py maintains -- never hand-edited, always the
first thing this module's own set_marker()/strip_marker() touch on save.
A slide with no such line has simply never been through this workflow
yet; its footer omits the version segment entirely rather than showing
something wrong (\\ifSMSlideVersionSet, reset per-frame -- see that
file's own comments).
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Literal, Optional

from .deck_scan import is_commented

Version = tuple[int, int, int]
BumpLevel = Literal["major", "minor", "patch"]

# The one baseline this module ever assumes on a slide's *first* tracked
# save: untracked content is treated as "already 1.0.0" -- the freeze
# captures it as exactly that, and the bump moves on from there (e.g. a
# first-ever "Minor" save freezes v1-0-0 and leaves current.tex at
# 1.1.0), matching how a slide.new()-minted slide's initial content has
# always informally been "version 1" even when nothing wrote that down.
DEFAULT_BASELINE: Version = (1, 0, 0)

_EMBEDDED_VERSION_RE = re.compile(r"\\setSlideVersion\{(\d+)-(\d+)-(\d+)\}")
# Matches the whole tool-managed line, trailing newline included, so
# strip_marker() removes it cleanly rather than leaving a blank line
# behind. `%?` tolerates a trailing comment-continuation `%` some other
# tool-managed lines in this project use, even though set_marker() itself
# never writes one.
_MARKER_LINE_RE = re.compile(r"^\\setSlideVersion\{\d+-\d+-\d+\}%?[ \t]*\r?\n?", re.MULTILINE)


def parse_version(text: str) -> Optional[Version]:
    """The version embedded in a slide's own current text, or None if it
    was never tracked (no \\setSlideVersion{} line yet)."""
    for match in _EMBEDDED_VERSION_RE.finditer(text):
        if not is_commented(text, match.start()):
            return (int(match.group(1)), int(match.group(2)), int(match.group(3)))
    return None


def format_hyphen(version: Version) -> str:
    """Filename-safe form, matching a version file's own "-vX-Y-Z.tex"
    suffix and \\slideversion{}'s own second argument."""
    return "-".join(str(part) for part in version)


def format_dot(version: Version) -> str:
    """Display form ("1.0.0") -- conventional semver, and what the
    compiled footer shows (Slidemaster_preamble_base.tex's own
    \\setSlideVersion does this same hyphen-to-dot conversion at compile
    time; this is the Python-side equivalent for the save dialog)."""
    return ".".join(str(part) for part in version)


def version_label(version: str) -> str:
    """"v1.2.3" for a version in its file-name form ("1-2-3")."""
    return "v" + version.replace("-", ".")


def bump(version: Version, level: BumpLevel) -> Version:
    major, minor, patch = version
    if level == "major":
        return (major + 1, 0, 0)
    if level == "minor":
        return (major, minor + 1, 0)
    if level == "patch":
        return (major, minor, patch + 1)
    raise ValueError(f"unknown bump level: {level!r}")


def strip_marker(text: str) -> str:
    """Remove any existing \\setSlideVersion{} line -- called before
    re-inserting one (set_marker()) or when a save leaves the slide
    untracked, so a stray/stale marker from a previous save or a
    copy-pasted block never survives into the new content."""
    return _MARKER_LINE_RE.sub("", text)


def set_marker(text: str, version: Version) -> str:
    """Insert \\setSlideVersion{X-Y-Z} as its own line, right after
    whatever leading header-comment block the slide has (if any) and
    right before its first real content line -- the same "top of file"
    placement the "%% Included in decks: ..." header already uses.
    Always strips any existing marker first, so a re-save never
    accumulates duplicates regardless of where a previous one landed.
    """
    text = strip_marker(text)
    lines = text.splitlines(keepends=True)
    insert_at = 0
    for line in lines:
        if line.strip() == "" or line.lstrip().startswith("%"):
            insert_at += 1
        else:
            break
    lines.insert(insert_at, f"\\setSlideVersion{{{format_hyphen(version)}}}\n")
    return "".join(lines)


def plan_save(
    old_version: Optional[Version], choice: Literal["major", "minor", "patch", "overwrite"]
) -> tuple[Optional[Version], Optional[Version]]:
    """Decide what this save should do, given the version current.tex was
    already tracking (None if it never was) and the user's own dialog
    choice. Returns (final_version, freeze_as):

    - final_version: the version the *new* content should be marked with
      (None means "leave it untracked" -- either it always was, or...
      this module never un-tracks an already-tracked slide, so that only
      happens when old_version was already None and the choice was
      "overwrite").
    - freeze_as: the version the *old* on-disk content should be frozen
      as before it's overwritten (None means "don't freeze anything" --
      "overwrite" never freezes, by definition).
    """
    if choice == "overwrite":
        return old_version, None
    baseline = old_version if old_version is not None else DEFAULT_BASELINE
    return bump(baseline, choice), baseline


def freeze_slide(current_path: Path, id_slug: str, version: Version) -> Optional[Path]:
    """Copy current_path's own on-disk bytes, verbatim, to
    slides/<id_slug>-v<version>.tex, right before it gets overwritten by
    a new save. Returns the frozen file's path, or None if either nothing
    was on disk yet to freeze (a brand new slide's very first save) or a
    file already exists there -- shouldn't happen in normal use (a given
    (slide, version) pair is only ever frozen once, exactly when
    current.tex is about to move past it), but silently clobbering real
    history would be a far worse failure mode than just leaving it alone
    and letting the caller decide how to report it.
    """
    if not current_path.exists():
        return None
    dest = current_path.parent / f"{id_slug}-v{format_hyphen(version)}.tex"
    if dest.exists():
        return None
    shutil.copy2(str(current_path), str(dest))
    return dest


def freeze_current(current_path: Path, id_slug: str, level: BumpLevel) -> tuple[Path, Version]:
    """Freeze the slide's current content under its own tracked version and move
    the slide on to the next one (`level`), as a Save does -- but with no change
    to the content. Returns (the frozen file, the new version). Raises ValueError
    when that version is frozen already."""
    from . import slide_source

    text, eol = slide_source.read_slide_source(current_path)
    final, freeze_as = plan_save(parse_version(text), level)
    frozen = freeze_slide(current_path, id_slug, freeze_as)
    if frozen is None:
        raise ValueError(f"v{format_dot(freeze_as)} of {id_slug} is already frozen, so the current content cannot be.")
    slide_source.save_slide_source(current_path, set_marker(text, final), eol, expected_text=text)
    return frozen, final


_FROZEN_RE = re.compile(r"-v(\d+)-(\d+)-(\d+)\.tex$")


class RestoreError(ValueError):
    """restore_version() cannot do it; the message says why."""


def restore_version(current_path: Path, id_slug: str, version_path: Path) -> tuple[Optional[Path], Version]:
    """Make a frozen version's content the slide's current content (v5.22.0,
    direct instruction), archiving what is current now.

    1. The outgoing current.tex is frozen under its own tracked version
       (1.0.0 if it was never tracked), exactly as a Save would -- nothing is
       lost, and a deck can still pin it. Skipped (returns None) when that
       version file already holds the same content.
    2. current.tex gets the frozen file's content, keeping its own
       "%% Included in decks" header, and a new version: the highest version
       known (current or frozen) with the minor number bumped -- a version
       number is never reused, so the restored 1.0.0 content becomes e.g.
       1.2.0 while 1.1.0 stays archived.
    Returns (archived file or None, the new version). Raises RestoreError if
    the slide already has that content or the archive name is taken by
    different content."""
    from . import slide_source
    from .deck_headers import HEADER_RE

    cur_text, eol = slide_source.read_slide_source(current_path)
    old_text, _ = slide_source.read_slide_source(version_path)
    if strip_marker(cur_text).strip() == strip_marker(old_text).strip():
        raise RestoreError(f"{current_path.name} already has the content of {version_path.name}.")
    cur_version = parse_version(cur_text) or DEFAULT_BASELINE
    known = [cur_version]
    for path in current_path.parent.glob(f"{id_slug}-v*.tex"):
        m = _FROZEN_RE.search(path.name)
        if m:
            known.append((int(m.group(1)), int(m.group(2)), int(m.group(3))))
    new_version = bump(max(known), "minor")

    archive = current_path.parent / f"{id_slug}-v{format_hyphen(cur_version)}.tex"
    archived: Optional[Path] = None
    if archive.exists():
        frozen_text, _ = slide_source.read_slide_source(archive)
        if strip_marker(frozen_text).strip() != strip_marker(cur_text).strip():
            raise RestoreError(
                f"{archive.name} already exists with different content, so the current "
                f"version cannot be archived under that name.")
    else:
        archived = freeze_slide(current_path, id_slug, cur_version)

    new_text = strip_marker(old_text)
    header = HEADER_RE.search(cur_text)
    if header:
        new_text = HEADER_RE.sub(lambda _m: header.group(0), new_text, count=1) \
            if HEADER_RE.search(new_text) else header.group(0) + new_text
    new_text = set_marker(new_text, new_version)
    slide_source.save_slide_source(current_path, new_text, eol, expected_text=cur_text)
    return archived, new_version
