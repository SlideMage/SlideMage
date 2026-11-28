# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Per-slide version tracking (SlideMage's own freeze-then-bump workflow,
2026-08-20 direct instruction; since v8.18.0 with continuous saving).

Since v8.18.0 the Source view saves a slide as you type, and versions are
made on purpose, with "Update Version". The version line
then says what the content is: \\setSlideVersion{1-2-0} is version 1.2.0
itself, \\setSlideVersion{1-2-0+} (footer "v1.2.0+") has changed since
1.2.0. The first autosave after a version freezes it, if it is not frozen
yet (prepare_autosave()), so a version's content is always kept.

The tracked version itself lives inside current.tex as a
\\setSlideVersion{X-Y-Z} line (SlideMage_base.tex), the same
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
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Optional

from .fileio import Edits, read_text_exact
from . import slide_source
from .project import ProjectContext
from .slide_language import FROZEN_RE, frozen_name
from .tex_source import is_commented

if TYPE_CHECKING:
    from .deck_language import ExpandedCall
    from .slide_add import CreatedSlide
    from .slide_usage import DeckUsage, Translation

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
# app_settings key (Settings -> General, off by default): a deck compile typesets a slide that carries a "+" as it
# is now. Off, it typesets the slide's last version, the frozen file of the version on its "+" line
# (saved_version_lines).
RENDER_CHANGES_SETTING_KEY = "render_slide_changes_in_decks"
# app_settings key (Settings -> General, on by default): with RENDER_CHANGES_SETTING_KEY off, a deck compile that
# typesets some slides from their last version asks first (compile_actions._confirm_saved_versions, issue #97).
ASK_SAVED_VERSIONS_SETTING_KEY = "ask_before_compiling_last_versions"

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
    compiled footer shows (SlideMage_base.tex's own
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


def frozen_path(current_path: Path, id_slug: str, version: Version) -> Path:
    return current_path.parent / frozen_name(id_slug, format_hyphen(version))


def _base_file(current_path: Path, id_slug: str, text: str) -> tuple[Path, str | None]:
    base = parse_version(text) or DEFAULT_BASELINE
    path = frozen_path(current_path, id_slug, base)
    try:
        return path, read_text_exact(path)
    except FileNotFoundError:
        return path, None


def prepare_autosave(disk_text: str, new_text: str, frozen_text: str | None) -> tuple[str, bool]:
    """Return the editor text to save and whether the captured original needs a first freeze."""
    marker = parse_marker(disk_text)
    version = marker[0] if marker else DEFAULT_BASELINE
    freeze = frozen_text is None and (marker is None or not marker[1])
    changed = frozen_text is None or _changed_since(frozen_text, new_text)
    return set_marker(new_text, version, changed=changed), freeze


def autosave_text(path: Path, id_slug: str, disk_text: str, new_text: str) -> str:
    """The marked text a preview of the current editor buffer will render."""
    _, frozen = _base_file(path, id_slug, disk_text)
    return prepare_autosave(disk_text, new_text, frozen)[0]


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
    """Save from an exact disk snapshot. Return editor text, backup path and first freeze."""
    new_text = new_text.replace("\r\n", "\n")
    edits: Edits = {}
    frozen = None
    if mark and is_current_slide(path):
        from .slide_language import call_for_slide_path
        base, base_text = _base_file(path, call_for_slide_path(path)[1], expected_text)
        new_text, freeze = prepare_autosave(expected_text, new_text, base_text)
        if freeze:
            frozen = base
            edits[base] = (None, expected_text)
        elif base_text is not None:
            edits[base] = (base_text, base_text)
    edits[path] = (expected_text, new_text.replace("\n", eol))
    backup_path = slide_source.commit_slide(ctx, path, edits, backup=backup)
    return new_text, backup_path, frozen


def mark_external_edit(ctx: ProjectContext, path: Path) -> bool:
    """A slide's current file that was changed outside the app (Claude Code in the terminal, another
    editor) has no "+": its content differs from its frozen version, and nothing here wrote it. Put the
    "+" on its version line now, so the footer and Update Version see it like an in-app edit. False when
    nothing was done (not a current slide, already marked, never frozen so nothing to compare with, or
    unchanged since its frozen version)."""
    from .slide_language import call_for_slide_path

    if not is_current_slide(path) or not path.is_file():
        return False
    raw = read_text_exact(path)
    text, eol = slide_source.editor_text(raw)
    marker = parse_marker(text)
    if marker is not None and marker[1]:
        return False
    version = marker[0] if marker is not None else DEFAULT_BASELINE
    id_slug = call_for_slide_path(path)[1]
    frozen, before = _base_file(path, id_slug, raw)
    if before is None or not _changed_since(before, text):
        return False
    after = set_marker(text, version, changed=True).replace("\n", eol)
    slide_source.commit_slide(ctx, path, {frozen: (before, before), path: (raw, after)}, backup=False)
    return True


def _live_slides(ctx: ProjectContext, deck, language: str):
    from . import deck_language, slide_language

    slugs = dict.fromkeys(slot.call.id_slug for slot in deck_language.deck_slots(ctx, deck, language)
                          if slot.call.version is None)
    for slug in slugs:
        path = ctx.slides_dir / slide_language.current_name(slug)
        if path.is_file():
            yield slug, path


def changed_slides(ctx: ProjectContext, deck, language: str) -> list[str]:
    """The live slides with a '+', in deck order."""
    return [slug for slug, path in _live_slides(ctx, deck, language)
            if (marker := parse_marker(read_text_exact(path))) and marker[1]]


def saved_versions(ctx: ProjectContext, deck, language: str, *, pending=None) -> dict[str, str]:
    """Frozen substitutions for a compile. Its prompt can project pending autosaves without writing them."""
    found = {}
    for slug, path in _live_slides(ctx, deck, language):
        raw = read_text_exact(path)
        freeze = False
        if pending and path in pending:
            _, base = _base_file(path, slug, raw)
            raw, freeze = prepare_autosave(raw, pending[path], base)
        marker = parse_marker(raw)
        if marker and marker[1]:
            frozen = frozen_path(path, slug, marker[0])
            if freeze or frozen.is_file():
                found[slug] = frozen.name
    return found


def saved_version_lines(ctx: ProjectContext, deck, language: str) -> list[str]:
    """The lines a deck compile's wrapper starts with so that each slide of saved_versions() is typeset from its
    last version's frozen file instead of its current file: LaTeX's file substitution
    (\\declare@file@substitution, LaTeX 2020-10), which \\slide{} and the other calls' \\input{slides/<id>-current.tex}
    then follow. Nothing in the framework or the deck changes. No lines when no slide qualifies."""
    from . import slide_language

    substitutions = [f"\\declare@file@substitution{{slides/{slide_language.current_name(slug)}}}{{slides/{frozen}}}"
                     for slug, frozen in saved_versions(ctx, deck, language).items()]
    return ["\\makeatletter", *substitutions, "\\makeatother"] if substitutions else []


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


def _updated_version(id_slug: str, raw: str, base_text: str | None, level: BumpLevel) -> tuple[Version, Version]:
    marker = parse_marker(raw)
    base = marker[0] if marker else DEFAULT_BASELINE
    if (marker and marker[1]) or (base_text is not None and _changed_since(base_text, raw)):
        return bump(base, level), base
    if base_text is None:
        return base, base
    raise ValueError(f"{id_slug} has not changed since v{format_dot(base)}.")


def plan_update(current: Path, raw: str, base_text: str | None, frozen: frozenset[Path],
                level: BumpLevel) -> tuple[Version, Version]:
    slug = current.name.removesuffix("-current.tex")
    new, base = _updated_version(slug, raw, base_text, level)
    if frozen_path(current, slug, new) in frozen:
        raise ValueError(f"v{format_dot(new)} of {slug} is frozen already, so the current content cannot be.")
    return new, base


def update_hint(current: Path, id_slug: str, text: str, level: BumpLevel) -> tuple[Version, Version]:
    _, base_text = _base_file(current, id_slug, text)
    return plan_update(current, text, base_text, frozenset(current.parent.glob(f"{id_slug}-v*.tex")), level)


def _marked_raw(raw: str, version: Version) -> str:
    text, eol = slide_source.editor_text(raw)
    marked = set_marker(text, version)
    return raw if marked == text else marked.replace("\n", eol)


def version_edits(current: Path, raw: str, frozen: Path, frozen_before: str | None, version: Version) -> Edits:
    """Patch and Overwrite publish identical frozen and current content."""
    after = _marked_raw(raw, version)
    return {frozen: (frozen_before, after), current: (raw, after)}


def reverted_text(current_raw: str, frozen_raw: str) -> str:
    """Restore the frozen body under the live slide's inclusion and translation headers."""
    current, eol = slide_source.editor_text(current_raw)
    old, _ = slide_source.editor_text(frozen_raw)
    metadata = re.compile(r"^%% (?:Included in decks|Translation of|(?:[A-Z]{2}|mult) translation): "
                          r"[^\n]*(?:\n|$)(?:%%(?:\n|$))?", re.MULTILINE)
    header = "".join(metadata.findall(current)).rstrip("\n")
    body = metadata.sub("", old).lstrip("\n")
    restored = header + "\n\n" + body if header else body
    return set_marker(restored, parse_version(current) or DEFAULT_BASELINE).replace("\n", eol)


def _restore_content(current: str, old: str, version: Version) -> str:
    """Use the selected version's body and keep the current slide's deck header."""
    from .deck_headers import HEADER_RE

    restored = strip_marker(old)
    header = HEADER_RE.search(current)
    if header:
        restored = (HEADER_RE.sub(lambda _m: header.group(0), restored, count=1)
                    if HEADER_RE.search(restored) else header.group(0) + restored)
    return set_marker(restored, version)


class RestoreError(ValueError):
    """The selected content cannot replace the current slide."""


def restore_edits(current: Path, raw: str, selected: Path, old_raw: str, archive: Path,
                  existing: str | None, archive_version: Version, new: Version) -> Edits:
    cur_text, eol = slide_source.editor_text(raw)
    old_text, _ = slide_source.editor_text(old_raw)
    if strip_marker(cur_text).strip() == strip_marker(old_text).strip():
        raise RestoreError(f"{current.name} already has the content of {selected.name}.")
    if existing is not None and strip_marker(slide_source.editor_text(existing)[0]).strip() != strip_marker(cur_text).strip():
        raise RestoreError(f"{archive.name} already exists with different content, so the current "
                           "version cannot be archived under that name.")
    marker = parse_marker(raw)
    archived = _marked_raw(raw, archive_version) if marker and marker[1] else raw
    restored = _restore_content(cur_text, old_text, new).replace("\n", eol)
    return {archive: (existing, archived if existing is None else existing),
            selected: (old_raw, old_raw),
            current: (raw, restored)}


@dataclass(frozen=True)
class Proposal:
    edits: Edits
    inputs: dict[Path, str | None]
    occurrences: tuple[tuple[Path, ExpandedCall], ...]
    frozen: frozenset[Path]
    created: CreatedSlide | None = None
    usages: list[DeckUsage] = field(default_factory=list)
    translations: list[Translation] = field(default_factory=list)
    has_translation: bool = False
    changed: tuple[Path, ...] = ()     # live, changed slides resolved for the originating jobs
    codes: tuple[str, ...] = ()
    backups: dict[Path, Path] = field(default_factory=dict)

    def with_edits(self, edits: Edits) -> Proposal:
        """Keep each changed current slide's session backup in the same publication."""
        backups = {self.backups[path]: (None, before) for path, (before, after) in edits.items()
                   if path in self.backups and before != after}
        ordered = {}
        for path, pair in edits.items():
            if backups and path in self.backups:
                ordered.update(backups)
                backups.clear()
            ordered[path] = pair
        return replace(self, edits=ordered)

    def base_file(self, current: Path) -> Path:
        version = parse_version(self.inputs[current]) or DEFAULT_BASELINE
        return frozen_path(current, current.name.removesuffix("-current.tex"), version)

    def update(self, current: Path, level: BumpLevel) -> tuple[Version, Version]:
        return plan_update(current, self.inputs[current], self.inputs.get(self.base_file(current)), self.frozen, level)

    def same_inputs(self, other: Proposal) -> bool:
        def calls(proposal):
            return [(deck, c.source, c.source_start, c.macro, c.id_slug, c.version, c.conditions, c.steps)
                    for deck, c in proposal.occurrences]
        return (self.inputs == other.inputs and self.frozen == other.frozen and self.changed == other.changed
                and self.codes == other.codes and self.translations == other.translations and calls(self) == calls(other))


def _revision_decks(ctx, read, jobs):
    from . import deck_language, deck_scan

    paths = (dict.fromkeys(job.deck.path for job in jobs) if jobs else
             (p for p in deck_language.deck_files(ctx)
              if not deck_scan.is_generated_wrapper(p.name) and not p.name.startswith(("#", "zzz_"))))
    scanned = []
    for path in paths:
        raw = read(path)
        if jobs or deck_scan.DOCUMENTCLASS_RE.search(raw):
            deck = deck_scan.deck_from_text(path, raw, archived=path.parent == ctx.archive_dir)
            scanned.append((deck, deck_language.resolve(deck, reader=read, strict_includes=True).calls))
    return scanned


def _job_slides(ctx, jobs, scanned, read, codes, *, compiling):
    """Check every job's live, pinned and translated inputs. Keep requested updates in job order."""
    from . import deck_language, slide_language

    by_path = {deck.path: (deck.text, calls) for deck, calls in scanned}
    links = slide_language.TranslationLinks(ctx.slides_dir, codes, reader=read)
    changed = {}
    for job in jobs:
        raw, calls = by_path[job.deck.path]
        if job.deck.text != raw:
            raise ValueError(f"{job.deck.path.name} changed. Refresh the deck and try again.")
        language = deck_language.language_for_job(job)
        if job.resolve_translations:
            calls = [slot.call for slot in deck_language.slots(ctx, calls, language, links=links)]
        for call in calls:
            if call.version:
                read(ctx.slides_dir / frozen_name(call.id_slug, call.version))
                continue
            current = ctx.slides_dir / slide_language.current_name(call.id_slug)
            marker = parse_marker(read(current))
            if marker and marker[1] and not (compiling and job.current_edits):
                changed[current] = None
    return tuple(changed)


def capture(ctx: ProjectContext, action: str, paths, *, jobs=(), approved: Proposal | None = None) -> Proposal:
    """Capture exact file contents, occurrences and the names reserved for this edit."""
    from . import languages, slide_language, slide_usage

    inputs: dict[Path, str | None] = {}

    def optional(path: Path) -> str | None:
        if path not in inputs:
            try:
                inputs[path] = read_text_exact(path)
            except FileNotFoundError:
                inputs[path] = None
            except UnicodeDecodeError as exc:
                raise ValueError(f"{path} is not valid UTF-8.") from exc
        return inputs[path]

    def read(path: Path) -> str:
        raw = optional(path)
        if raw is None:
            raise FileNotFoundError(f"{path} was not found.")
        return raw

    for path in paths:
        read(path)
    scanned = _revision_decks(ctx, read, jobs)
    occurrences = tuple((deck.path, call) for deck, calls in scanned for call in calls)
    # "overwrite" too: whether other decks (or pinned calls, or translations) are affected decides if it asks
    choose_calls = action in ("patch", "minor", "major", "update", "new_slide", "overwrite")
    codes = languages.project_languages(ctx, reader=read).codes if choose_calls or jobs else ()
    changed = _job_slides(ctx, jobs, scanned, read, codes, compiling=action == "compile") if jobs else ()

    frozen = set()
    backups = {}
    for current in dict.fromkeys((*paths, *changed)):
        if not slide_language.is_current_file(current):
            continue
        slug = current.name.removesuffix(slide_language.CURRENT_SUFFIX)
        for path in current.parent.glob(f"{slug}-v*.tex"):
            if FROZEN_RE.search(path.name):
                read(path)
                frozen.add(path)
        if action != "revert":
            backup = (approved.backups[current] if approved and current in approved.backups
                      else slide_source.backup_path(ctx, current))
            optional(backup)
            backups[current] = backup

    usages, translations = [], []
    has_translation = False
    if choose_calls or action in ("overwrite", "restore", "revert"):
        slug = paths[0].name.removesuffix(slide_language.CURRENT_SUFFIX)
        has_translation = bool(slide_language.translated_languages(ctx, slug))
    if choose_calls:
        usages = slide_usage.revision_usages(scanned, slug)
        files = [(deck, calls, None, []) for deck, calls in scanned]
        translations = slide_usage.find_translations(ctx, slug, inputs[paths[0]], files=files, codes=codes)
        for partner in translations:
            read(partner.path)
    cap = Proposal({}, inputs, occurrences, frozenset(frozen), usages=usages, translations=translations,
                   has_translation=has_translation, changed=changed, backups=backups, codes=codes)
    if action == "new_slide" or (approved and approved.created):
        from .slide_branch import capture_identity
        return capture_identity(ctx, cap, paths[0], approved.created if approved else None)
    return cap


def patch_edits(cap: Proposal, current: Path, level: BumpLevel, choices) -> Edits:
    from .slide_usage import choice_edits
    new, base = cap.update(current, level)
    frozen = frozen_path(current, current.name.removesuffix("-current.tex"), new)
    edits = version_edits(current, cap.inputs[current], frozen, None, new)
    previous = format_hyphen(base) if cap.base_file(current) in cap.frozen else None
    edits.update(choice_edits(cap.usages, choices, previous))
    return edits


def batch_edits(cap: Proposal, paths, level: BumpLevel | str) -> Edits:
    """Leave all calls as written. Publish all freezes before updating any live slide. Level "overwrite": each slide
    replaces the frozen version it is based on instead of becoming a new one."""
    edits = {}
    for path in paths:
        edits.update(overwrite_edits(cap, path) if level == "overwrite" else patch_edits(cap, path, level, {}))
    for path in paths:
        edits[path] = edits.pop(path)
    return edits


def overwrite_edits(cap: Proposal, current: Path) -> Edits:
    raw = cap.inputs[current]
    frozen = cap.base_file(current)
    before = cap.inputs.get(frozen)
    slug = current.name.removesuffix("-current.tex")
    new, base = _updated_version(slug, raw, before, "patch")
    if new == base:
        raise ValueError(f"{slug} has not changed since v{format_dot(base)}.")
    return version_edits(current, raw, frozen, before, base)


def restore(cap: Proposal, current: Path, selected: Path) -> Edits:
    raw = cap.inputs[current]
    marker = parse_marker(raw)
    base = marker[0] if marker else DEFAULT_BASELINE
    known = [tuple(map(int, FROZEN_RE.search(p.name).group(1).split("-"))) for p in cap.frozen]
    highest = max([base, *known])
    archive_version = bump(highest, "patch") if marker and marker[1] else base
    archive = frozen_path(current, current.name.removesuffix("-current.tex"), archive_version)
    return restore_edits(current, raw, selected, cap.inputs[selected], archive, cap.inputs.get(archive),
                         archive_version, bump(max(highest, archive_version), "minor"))


def revert_edits(cap: Proposal, current: Path) -> Edits:
    frozen = cap.base_file(current)
    if frozen not in cap.frozen:
        raise ValueError(f"{current.name} has no frozen {frozen.name} to go back to.")
    raw = cap.inputs[current]
    return {current: (raw, reverted_text(raw, cap.inputs[frozen]))}
