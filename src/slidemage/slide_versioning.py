"""Per-slide version tracking (SlideMage's own freeze-then-bump workflow,
2026-08-20 direct instruction; since v8.18.0 with continuous saving).

Since v8.18.0 the Source view saves a slide as you type, and versions are
made on purpose, with "Update Version" (update_version()). The version line
then says what the content is: \\setSlideVersion{1-2-0} is version 1.2.0
itself, \\setSlideVersion{1-2-0+} (footer "v1.2.0+") has changed since
1.2.0. The first autosave after a version freezes it, if it is not frozen
yet (prepare_autosave()), so a version's content is always kept. What
follows describes the earlier Save-time workflow this grew from.

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

from .project import ProjectContext
from .slide_language import FROZEN_RE, frozen_name
from .tex_source import is_commented

Version = tuple[int, int, int]
BumpLevel = Literal["major", "minor", "patch"]

# The one baseline this module ever assumes on a slide's *first* tracked
# save: untracked content is treated as "already 1.0.0" -- the freeze
# captures it as exactly that, and the bump moves on from there (e.g. a
# first-ever "Minor" save freezes v1-0-0 and leaves current.tex at
# 1.1.0), matching how a slide.new()-minted slide's initial content has
# always informally been "version 1" even when nothing wrote that down.
DEFAULT_BASELINE: Version = (1, 0, 0)

# app_settings key (Settings -> General, off by default): leaving a slide that was edited and carries a
# "+" asks whether to make it a version now (CentreColumn._offer_version).
ASK_ON_LEAVE_SETTING_KEY = "ask_update_version_on_leave"

_EMBEDDED_VERSION_RE = re.compile(r"\\setSlideVersion\{(\d+)-(\d+)-(\d+)(\+?)\}")
# Matches the whole tool-managed line, trailing newline included, so
# strip_marker() removes it cleanly rather than leaving a blank line
# behind. `%?` tolerates a trailing comment-continuation `%` some other
# tool-managed lines in this project use, even though set_marker() itself
# never writes one.
_MARKER_LINE_RE = re.compile(r"^\\setSlideVersion\{\d+-\d+-\d+\+?\}%?[ \t]*\r?\n?", re.MULTILINE)


def parse_marker(text: str) -> Optional[tuple[Version, bool]]:
    """(the version on the slide's version line, whether the content has
    changed since: a "+"), or None if it was never tracked (no
    \\setSlideVersion{} line yet)."""
    for match in _EMBEDDED_VERSION_RE.finditer(text):
        if not is_commented(text, match.start()):
            return (int(match.group(1)), int(match.group(2)), int(match.group(3))), bool(match.group(4))
    return None


def parse_version(text: str) -> Optional[Version]:
    """The version embedded in a slide's own current text, or None if it
    was never tracked (no \\setSlideVersion{} line yet)."""
    marker = parse_marker(text)
    return marker[0] if marker is not None else None


def version_text(text: str) -> Optional[str]:
    """The slide's version for display: "1.2.0", "1.2.0+" when it has changed
    since, None when untracked."""
    marker = parse_marker(text)
    return format_dot(marker[0]) + ("+" if marker[1] else "") if marker is not None else None


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


def set_marker(text: str, version: Version, changed: bool = False) -> str:
    """Insert \\setSlideVersion{X-Y-Z} as its own line, right after
    whatever leading header-comment block the slide has (if any) and
    right before its first real content line -- the same "top of file"
    placement the "%% Included in decks: ..." header already uses.
    Always strips any existing marker first, so a re-save never
    accumulates duplicates regardless of where a previous one landed.
    `changed` writes the "+" (changed since `version`).
    """
    text = strip_marker(text)
    lines = text.splitlines(keepends=True)
    insert_at = 0
    for line in lines:
        if line.strip() == "" or line.lstrip().startswith("%"):
            insert_at += 1
        else:
            break
    lines.insert(insert_at, f"\\setSlideVersion{{{format_hyphen(version)}{'+' if changed else ''}}}\n")
    return "".join(lines)


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
    dest = current_path.parent / frozen_name(id_slug, format_hyphen(version))
    if dest.exists():
        return None
    shutil.copy2(str(current_path), str(dest))
    return dest


def frozen_path(current_path: Path, id_slug: str, version: Version) -> Path:
    return current_path.parent / frozen_name(id_slug, format_hyphen(version))


def prepare_autosave(current_path: Path, id_slug: str, disk_text: str, new_text: str) -> tuple[str, Optional[Version]]:
    """What an autosave of a slide's current file writes (`new_text` with the
    version line marked "+": changed since), and the version the file on disk
    must be frozen as first, or None. That is the version on its line when it
    has no "+" and is not frozen yet: a slide saved before continuous saving,
    a restored one, or one never tracked (as 1.0.0)."""
    marker = parse_marker(disk_text)
    version = marker[0] if marker is not None else DEFAULT_BASELINE
    changed = marker is not None and marker[1]
    freeze_as = None if changed or frozen_path(current_path, id_slug, version).exists() else version
    return set_marker(new_text, version, changed=True), freeze_as


def without_plus(text: str) -> str:
    """`text` with its version line's "+" taken off: for comparing a text an edit expects with
    the slide's, which may have got the "+" since (an autosave, an earlier edit)."""
    marker = parse_marker(text)
    return set_marker(text, marker[0]) if marker is not None and marker[1] else text


def carry_plus(current: str, new_text: str) -> str:
    """`new_text` with the "+" of `current`'s version line, if it has one and `new_text` names the
    same version: a write never takes the "+" off; only Update Version does."""
    marker, new_marker = parse_marker(current), parse_marker(new_text)
    if marker is not None and marker[1] and new_marker is not None and new_marker[0] == marker[0]:
        return set_marker(new_text, marker[0], changed=True)
    return new_text


def is_current_slide(path: Path) -> bool:
    from .slide_language import call_for_slide_path
    try:
        return call_for_slide_path(path)[0] == "slide"
    except ValueError:
        return False


def save_slide(ctx: ProjectContext, path: Path, new_text: str, eol: str, expected_text: str, *,
               backup: bool = True, mark: bool = True) -> tuple[str, Optional[Path], Optional[Path]]:
    """Write `new_text` to `path` through slide_source.save_slide_source(), refusing a stale file
    (`expected_text`, compared without the "+"). A slide's current file gets the "+" and, first,
    the freeze prepare_autosave() asks for. Every in-app write of a slide's text goes this way;
    update_version() and restore_version() set the version line themselves; `mark=False` (an undo,
    a rollback: an earlier text put back exactly) writes `new_text` as it is. Returns (the text
    written, the backup or None, the file frozen first or None). Raises StaleFileError."""
    from . import slide_source

    disk_text = slide_source.read_slide_source(path)[0] if path.exists() else expected_text
    if without_plus(disk_text) != without_plus(expected_text):
        slide_source.check_fresh(path, expected_text)     # raises StaleFileError, with its message
    frozen = None
    if mark and is_current_slide(path):
        from .slide_language import call_for_slide_path
        id_slug = call_for_slide_path(path)[1]
        new_text, freeze_as = prepare_autosave(path, id_slug, disk_text, new_text)
        if freeze_as is not None:
            frozen = freeze_slide(path, id_slug, freeze_as)
    backup_path = slide_source.save_slide_source(ctx, path, new_text, eol, expected_text=disk_text, backup=backup)
    return new_text, backup_path, frozen


def mark_external_edit(ctx: ProjectContext, path: Path) -> bool:
    """A slide's current file that was changed outside the app (Claude Code in the terminal, another
    editor) has no "+": its content differs from its frozen version, and nothing here wrote it. Put the
    "+" on its version line now, so the footer and Update Version see it like an in-app edit. False when
    nothing was done (not a current slide, already marked, never frozen so nothing to compare with, or
    unchanged since its frozen version)."""
    from . import slide_source
    from .slide_language import call_for_slide_path

    if not is_current_slide(path) or not path.is_file():
        return False
    text, eol = slide_source.read_slide_source(path)
    marker = parse_marker(text)
    if marker is not None and marker[1]:
        return False
    version = marker[0] if marker is not None else DEFAULT_BASELINE
    id_slug = call_for_slide_path(path)[1]
    frozen = frozen_path(path, id_slug, version)
    if not frozen.exists() or not _changed_since(slide_source.read_slide_source(frozen)[0], text):
        return False
    slide_source.save_slide_source(ctx, path, set_marker(text, version, changed=True), eol,
                                   expected_text=text, backup=False)
    return True


def changed_slides(ctx: ProjectContext, deck, language: str) -> list[str]:
    """The id-slugs of the slides `deck` calls from their current file (not a pinned version) that
    carry a "+": changed since their last version, so what the deck compiles to is not a version
    any frozen file records. In the deck's order, each once."""
    from . import deck_language, slide_language, slide_source

    found: dict[str, None] = {}
    for slot in deck_language.deck_slots(ctx, deck, language):
        call = slot.call
        if call.version is not None or call.id_slug in found:
            continue
        path = ctx.slides_dir / slide_language.current_name(call.id_slug)
        if not path.is_file():
            continue
        marker = parse_marker(slide_source.read_slide_source(path)[0])
        if marker is not None and marker[1]:
            found[call.id_slug] = None
    return list(found)


def _content(text: str) -> str:
    """What a version is: the text without its header comments and version line."""
    from .slide_ids import body_of
    return strip_marker(body_of(text.replace("\r\n", "\n"))).strip()


def _changed_since(frozen_text: str, text: str) -> bool:
    """Whether the current `text` has content its frozen version does not. Taking out the
    \\SMFinalStateForStudents line that no deck needs any longer (reveal_steps.drop_dead_final_flag) is no
    change: the slide typesets as before. Adding the flag is one: students would see something else."""
    from .reveal_steps import remove_final_flag

    if _content(frozen_text) == _content(text):
        return False
    stripped = remove_final_flag(frozen_text)
    return not (stripped is not None and remove_final_flag(text) is None and _content(stripped) == _content(text))


def plan_update(current_path: Path, id_slug: str, text: str, level: BumpLevel) -> tuple[Version, Version]:
    """(the version Update Version makes of `text`, the version it moves on
    from). With no "+" and that version not frozen yet, it is frozen as it
    is: both are the same. A text without "+" that differs from its frozen
    version (an edit made outside the app: Claude Code in the terminal) has
    changed too. Raises ValueError when there is nothing to make a version
    of, or the new version is frozen already (a number is never reused)."""
    from . import slide_source

    marker = parse_marker(text)
    base = marker[0] if marker is not None else DEFAULT_BASELINE
    base_path = frozen_path(current_path, id_slug, base)
    changed = marker is not None and marker[1] or (
        base_path.exists() and _changed_since(slide_source.read_slide_source(base_path)[0], text))
    if changed:
        new = bump(base, level)
    elif not base_path.exists():
        new = base
    else:
        raise ValueError(f"{id_slug} has not changed since v{format_dot(base)}.")
    if frozen_path(current_path, id_slug, new).exists():
        raise ValueError(f"v{format_dot(new)} of {id_slug} is frozen already, so the current content cannot be.")
    return new, base


def update_version(ctx: ProjectContext, current_path: Path, id_slug: str, level: BumpLevel) -> tuple[Path, Version, Version]:
    """"Update Version": the slide's current content becomes version
    plan_update() says, written without "+" and frozen as that version.
    Returns (the frozen file, the new version, the version moved on from:
    what decks that keep the old content pin)."""
    from . import slide_source

    text, eol = slide_source.read_slide_source(current_path)
    new, base = plan_update(current_path, id_slug, text, level)
    new_text = set_marker(text, new)
    if new_text != text:
        slide_source.save_slide_source(ctx, current_path, new_text, eol, expected_text=text)
    frozen = freeze_slide(current_path, id_slug, new)
    if frozen is None:
        raise ValueError(f"v{format_dot(new)} of {id_slug} could not be frozen.")
    return frozen, new, base


class RestoreError(ValueError):
    """restore_version() cannot do it; the message says why."""


def restore_version(ctx: ProjectContext, current_path: Path, id_slug: str, version_path: Path) -> tuple[Optional[Path], Version]:
    """Make a frozen version's content the slide's current content (v5.22.0,
    direct instruction), archiving what is current now.

    1. The outgoing current.tex is frozen under its own tracked version
       (1.0.0 if it was never tracked), exactly as a Save would -- nothing is
       lost, and a deck can still pin it. Skipped (returns None) when that
       version file already holds the same content. Content that has
       changed since its version (a "+") is archived as the next patch
       version above every known one.
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
    marker = parse_marker(cur_text)
    cur_version = marker[0] if marker is not None else DEFAULT_BASELINE
    known = [cur_version]
    for path in current_path.parent.glob(f"{id_slug}-v*.tex"):
        m = FROZEN_RE.search(path.name)
        if m:
            known.append(tuple(int(part) for part in m.group(1).split("-")))
    if marker is not None and marker[1]:
        # Changed since its version: archived as a version of its own, the next patch above every known one.
        cur_version = bump(max(known), "patch")
        marked = set_marker(cur_text, cur_version)
        slide_source.save_slide_source(ctx, current_path, marked, eol, expected_text=cur_text)
        cur_text = marked
        known.append(cur_version)
    new_version = bump(max(known), "minor")

    archive = current_path.parent / frozen_name(id_slug, format_hyphen(cur_version))
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
    slide_source.save_slide_source(ctx, current_path, new_text, eol, expected_text=cur_text)
    return archived, new_version
