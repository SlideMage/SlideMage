# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Change a slide's own language segment (<id>-<slug> -> <id>-<LANG>-<slug>,
or <id>-<OLDLANG>-<slug> -> <id>-<LANG>-<slug>), and keep translation
cross-reference header comments honest afterward.

Two entry points:

- set_slide_language(): the actual rename -- renames current.tex plus
  every frozen -vX-Y-Z.tex sibling (git mv when tracked, else a plain
  move, same fallback archive.py already established), rewrites every
  \\slide-family reference to the old id-slug across every deck (including
  #workdeck.tex, unlike deck_headers.py's own header regeneration which
  deliberately excludes it), then re-runs deck_headers.regenerate_headers(ctx)
  and regenerate_translation_links() so both kinds of derived text stay in
  sync with the rename.

- regenerate_translation_links(): mirrors
  deck_headers.regenerate_headers(ctx)'s own "recompute from disk state,
  don't trust old text" approach, but per translation cross-reference
  header line rather than per deck-inclusion header block. Run standalone
  (its own SlideMage toolbar button) or automatically after a rename.

Deliberately does NOT try to reconcile roles across a pair of files (which
side says "Translation of:" vs "<LANG> translation:") -- it only ever
refreshes a comment line that already names a bare ID, resolving that
bare ID's *current* on-disk id-slug/language. It never invents a new line
on a side that never declared the relationship, matching
add_deck_headers.py's own add-only caution.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from .fileio import read_text_exact, write_texts
from . import deck_editor, deck_language, languages, slide_edit, slide_ids, slide_language
from .project import ProjectContext


def compute_new_id_slug(id_slug: str, language: str, codes: tuple[str, ...]) -> str:
    """<id>-<slug> or <id>-<OLDLANG>-<slug> -> <id>-<language>-<slug>; `codes` are the project's languages."""
    allowed = (*codes, slide_language.MULT)
    if language not in allowed:
        raise ValueError(f"language must be one of {allowed}, got {language!r}")
    parts = id_slug.split("-", 2)
    if len(parts) < 2:
        raise ValueError(f"not a valid id-slug (needs at least one hyphen): {id_slug!r}")
    slide_id = parts[0]
    if len(parts) >= 3 and parts[1] in allowed:
        slug = parts[2]
    else:
        slug = "-".join(parts[1:])
    return f"{slide_id}-{language}-{slug}"


def _references(text: str, id_slug: str) -> int:
    """How many \\slide-family calls in `text` load `id_slug`, in every form the deck parser reads
    (deck_editor.calls_in_text), commented-out calls included: the calls a rename rewrites."""
    return sum(call.id_slug == id_slug for call in deck_editor.calls_in_text(text))


def count_references(ctx: ProjectContext, id_slug: str) -> int:
    """How many \\slide-family calls, across every deck (including
    #workdeck.tex), currently reference this id-slug -- for a
    confirmation dialog before set_slide_language() rewrites them."""
    return sum(_references(read_text_exact(deck_path), id_slug) for deck_path in deck_language.call_files(ctx))


def _apply_id_slug_rename(ctx: ProjectContext, id_slug: str, new_id_slug: str,
                          warnings: Optional[list[str]] = None) -> str:
    """Shared machinery behind set_slide_language(), tag_untagged() and rename_slide_slug(): move
    slides/<id_slug>-current.tex (and every frozen -vX-Y-Z.tex sibling) to <new_id_slug>'s own filenames and rewrite
    every slide-family call across every deck, all or nothing (slide_edit), then regenerate both
    derived-text kinds (deck-inclusion headers, translation cross-references). The bare id and its slide_ids.csv
    registration are untouched (rename_slide_id()'s job). Returns new_id_slug. `warnings` collects what could not
    be rebuilt afterwards (the change itself was done)."""
    if new_id_slug == id_slug:
        return id_slug
    result = slide_edit.apply(slide_edit.plan_id_slug_rename(ctx, id_slug, new_id_slug))
    if warnings is not None:
        warnings.extend(result.warnings)
    return new_id_slug


def paths_changed_by_id_slug_rename(ctx: ProjectContext, id_slug: str, new_id_slug: str) -> list[Path]:
    """The files a rename to `new_id_slug` moves or rewrites: the UI refuses while a tab holds unsaved edits of one."""
    return slide_edit.plan_id_slug_rename(ctx, id_slug, new_id_slug).paths()


def paths_changed_by_delete(ctx: ProjectContext, id_slug: str) -> list[Path]:
    """The files delete_slide_id() moves or rewrites."""
    return slide_edit.plan_delete(ctx, id_slug).paths()


def set_slide_language(ctx: ProjectContext, id_slug: str, language: str,
                       warnings: Optional[list[str]] = None) -> str:
    """Renames slides/<id_slug>-current.tex (and every frozen
    -vX-Y-Z.tex sibling) to carry `language`'s segment, rewrites every
    reference across every deck, and regenerates both derived-text kinds
    (deck-inclusion headers, translation cross-references). Returns the
    new id-slug (unchanged from id_slug if it already carried this exact
    language segment)."""
    return _apply_id_slug_rename(ctx, id_slug, compute_new_id_slug(id_slug, language, languages.project_languages(ctx).codes),
                                 warnings)


def untagged_slugs_matching(ctx: ProjectContext, code: str) -> list[str]:
    """The id-slugs of the slides that carry no language, but whose slug starts with `code` as a capital word
    ("x7k-IT-Governance" for "it"): once `code` is one of the project's languages, that word would be read as the
    slide's language. Ask before adding the code to the project; a slide tagged with a language already
    ("x7k-EN-IT-Governance") is never listed."""
    code = code.upper()
    codes = languages.project_languages(ctx).codes
    found = []
    for path in ctx.slides_dir.glob(f"*{slide_language.CURRENT_SUFFIX}"):
        id_slug = path.name[:-len(slide_language.CURRENT_SUFFIX)]
        parts = id_slug.split("-", 2)
        if len(parts) >= 2 and parts[1] == code and slide_language.own_language(id_slug, codes) is None:
            found.append(id_slug)
    return sorted(found)


def tagged_id_slug(id_slug: str, language: str) -> str:
    """"x7k-IT-Governance" + "EN" -> "x7k-EN-IT-Governance"."""
    if not re.fullmatch(r"[A-Z]{2}|mult", language):
        raise ValueError(f"language must be a code like 'EN' or 'mult', got {language!r}")
    bare_id, _, slug = id_slug.partition("-")
    return f"{bare_id}-{language}-{slug}"


def tag_untagged(ctx: ProjectContext, id_slug: str, language: str, warnings: Optional[list[str]] = None) -> str:
    """Give the untagged slide `id_slug` the language segment `language` ("EN"): "x7k-IT-Governance" becomes
    "x7k-EN-IT-Governance". The rename is set_slide_language's: files, deck calls, headers, translation links.
    Returns the new id-slug."""
    return _apply_id_slug_rename(ctx, id_slug, tagged_id_slug(id_slug, language), warnings)


_SLUG_RE = re.compile(r"[0-9A-Za-z]+(?:-[0-9A-Za-z]+)*")


def parse_id_slug(id_slug: str, codes: tuple[str, ...]) -> tuple[str, Optional[str], str]:
    """<id>[-<LANG>]-<slug> -> (bare id, language or None, descriptive
    slug) -- e.g. "hnr-EN-Deception-in-Experimental-Economics" ->
    ("hnr", "EN", "Deception-in-Experimental-Economics"), or a
    not-yet-migrated "abc-Some-Title" -> ("abc", None, "Some-Title"). `codes` are the project's languages."""
    parts = id_slug.split("-", 2)
    if len(parts) < 2:
        raise ValueError(f"not a valid id-slug (needs at least one hyphen): {id_slug!r}")
    bare_id = parts[0]
    if len(parts) >= 3 and slide_language.own_language(id_slug, codes):
        return bare_id, parts[1], parts[2]
    return bare_id, None, "-".join(parts[1:])


def compute_new_slug(id_slug: str, new_slug: str, codes: tuple[str, ...]) -> str:
    """<id>[-<LANG>]-<slug> -> <id>[-<LANG>]-<new_slug> -- same bare id and
    language segment (if any); only the descriptive slug changes."""
    if not _SLUG_RE.fullmatch(new_slug):
        raise ValueError(
            f"{new_slug!r} is not a valid slug: use only letters, digits, "
            "and single hyphens between words (no leading/trailing/doubled "
            "hyphens)"
        )
    bare_id, language, _ = parse_id_slug(id_slug, codes)
    return f"{bare_id}-{language}-{new_slug}" if language else f"{bare_id}-{new_slug}"


def rename_slide_slug(ctx: ProjectContext, id_slug: str, new_slug: str, warnings: Optional[list[str]] = None) -> str:
    """Give a slide a new descriptive slug, keeping its bare id (and
    language segment, if any) unchanged -- for the "Rename slide" button
    (2026-09-23, direct instruction), which only ever changes the
    human-readable part of the id-slug, not the 3-character id itself
    (rename_slide_id()'s job) or its language (set_slide_language()'s
    job). Same move + reference-rewrite + header-regen machinery as both
    of those. Returns the new id-slug (unchanged from id_slug if it
    already had this exact slug)."""
    return _apply_id_slug_rename(ctx, id_slug, compute_new_slug(id_slug, new_slug, languages.project_languages(ctx).codes),
                                 warnings)


def _resolve_reference(ctx: ProjectContext, bare_ref: str) -> Optional[str]:
    return slide_language.current_id_slug_for_bare_id(ctx, slide_language.bare_id(bare_ref))


# A translation line with the bare "%%" that closes its block, as slide_ids.with_translation_backreference writes it.
_LINK_RE = re.compile(r"^%% (?:Translation of: (?P<of>\S+)|(?P<language>[A-Z]{2}|mult) translation: (?P<to>\S+))"
                      r"[^\r\n]*\r?\n(?:%%\r?\n)?", re.MULTILINE)


def _star_text(text: str, members: set[str], original: Optional[str], translations: list[tuple[str, str]]) -> str:
    """`text` of a slide file in a translation group whose members have these bare ids: its header lines
    that name a member are replaced by the star's own ("Translation of: <original>" for a translation, one
    "<LANG> translation:" per (language, id-slug) of `translations` for the original), put where the first of them
    stood. Lines naming anything else stay."""
    wanted = ([f"Translation of: {original}"] if original else []) \
        + [f"{language} translation: {slug}" for language, slug in translations]
    found = [m for m in _LINK_RE.finditer(text) if slide_language.bare_id(m.group("of") or m.group("to")) in members]
    if [m.group(0).splitlines()[0] for m in found] == [f"%% {line}" for line in wanted]:
        return text
    eol = "\r\n" if "\r\n" in text else "\n"
    blocks = "".join(f"%% {line}{eol}%%{eol}" for line in wanted)
    if not found:
        at = slide_ids.header_insert_point(text)
        return text[:at] + blocks + text[at:]
    out, last = [], 0
    for index, m in enumerate(found):
        out.append(text[last:m.start()] + (blocks if index == 0 else ""))
        last = m.end()
    return "".join(out) + text[last:]


def _refresh_links(ctx: ProjectContext, missing: list[str]) -> int:
    """Point every translation line at its target's *current* id-slug/language; `missing` collects a report
    for any whose target no longer has a -current.tex. Returns the number of files changed."""
    changed = 0
    codes = languages.project_languages(ctx).codes
    for path in sorted(ctx.slides_dir.glob("*-current.tex")):
        own_name = path.name[: -len(slide_language.CURRENT_SUFFIX)]
        text = read_text_exact(path)
        new_text = text

        for m in reversed(list(slide_language.TRANSLATION_OF_RE.finditer(new_text))):
            resolved = _resolve_reference(ctx, m.group(1))
            if resolved is None:
                missing.append(
                    f"{own_name}: \"Translation of: {m.group(1)}\" no longer "
                    "resolves to a slides/*-current.tex file -- left as-is, please check."
                )
            elif resolved != m.group(1):
                new_text = new_text[: m.start(1)] + resolved + new_text[m.end(1):]

        def _lang_repl(lm: "re.Match[str]") -> str:
            resolved = _resolve_reference(ctx, lm.group(2))
            if resolved is None:
                missing.append(
                    f"{own_name}: \"{lm.group(1)} translation: {lm.group(2)}\" no "
                    "longer resolves to a slides/*-current.tex file -- left as-is, "
                    "please check."
                )
                return lm.group(0)
            target_lang = slide_language.own_language(resolved, codes) or lm.group(1)
            return f"%% {target_lang} translation: {resolved}"

        new_text = slide_language.LANG_TRANSLATION_RE.sub(_lang_repl, new_text)

        if new_text != text:
            write_texts({path: (text, new_text)})
            changed += 1
    return changed


def regenerate_translation_links(ctx: ProjectContext) -> tuple[int, list[str]]:
    """Rescan every slides/*-current.tex file's own "%% Translation of:
    ..." / "%% <LANG> translation: ..." header lines and refresh each to
    point at its target's *current* id-slug/language, then write every
    translation group as a star: each translation names the original, and
    the original has one "<LANG> translation:" line per translation (a
    chain, where a translation names another translation, is rewritten
    that way). Returns (files changed, [report strings for any link whose
    target no longer has a -current.tex, and for any group whose links
    name no original (a cycle) -- left as they are] -- surfaced in the GUI
    log/a summary dialog rather than silently dropped, same as
    alt_images.SyncReport.missing)."""
    missing: list[str] = []
    changed = _refresh_links(ctx, missing)
    links = slide_language.links_for(ctx)
    done: set[int] = set()
    for slug in sorted(path.name[:-len(slide_language.CURRENT_SUFFIX)] for path in links.paths.values()):
        group = links.group(slug)
        if links.own(slug) in (None, slide_language.MULT) or id(group) in done or len(group.members) < 2:
            continue
        done.add(id(group))
        if group.original is None:
            missing.append(f"{', '.join(sorted(group.members.values()))}: the translation links name no original "
                           "(they refer to each other, or to more than one) -- left as-is, please check.")
            continue
        bare_ids = {slide_language.bare_id(member) for member in group.members.values()}
        translations = [(language, member) for language in links.codes
                        if (member := group.members.get(language)) and member != group.original]
        for member in group.members.values():
            path = links.paths[slide_language.bare_id(member)]
            text = read_text_exact(path)
            if member == group.original:
                new_text = _star_text(text, bare_ids, None, translations)
            else:
                new_text = _star_text(text, bare_ids, group.original, [])
            if new_text != text:
                write_texts({path: (text, new_text)})
                changed += 1
    return changed, missing


def make_original(ctx: ProjectContext, id_slug: str) -> None:
    """Make the translation `id_slug` the original of its translation group, for when the author starts writing
    in another language: its "Translation of:" line goes, every other member's names it (the old original's
    too), and the "<LANG> translation:" lines follow (regenerate_translation_links). All the members' files are
    written, so right afterwards none is outdated. The caller makes sure no member has unsaved edits."""
    links = slide_language.links_for(ctx)
    group = links.group(id_slug)
    own = links.own(id_slug)
    if own in (None, slide_language.MULT) or group.original is None or group.members.get(own) != id_slug:
        raise ValueError(f"{id_slug} is in no translation group with an original")
    members = set(group.members.values())
    bare_ids = {slide_language.bare_id(member) for member in members}
    for member in members:
        path = links.paths[slide_language.bare_id(member)]
        text = read_text_exact(path)
        new_text = _star_text(text, bare_ids, None if member == id_slug else id_slug, [])
        if new_text != text:
            write_texts({path: (text, new_text)})
    regenerate_translation_links(ctx)


def rename_slide_id(ctx: ProjectContext, old_id: str, new_id: str, reserved: bool = False,
                    warnings: Optional[list[str]] = None) -> dict[str, str]:
    """Give a slide a new 3-character id (2026-09-21, direct instruction:
    "838"/"538" are all-digit ids, which slide_ids.illegal_id_reason() now
    rules out for good). Everything that carries the bare id follows:

    - slides/<old>-*.tex (current and every frozen -vX-Y-Z sibling) are
      moved to slides/<new>-*.tex (git mv when tracked);
    - every \\slide-family reference to the old id-slug across every deck
      (including #workdeck.tex, like set_slide_language());
    - bare-id \\hyperlink{<old>}{...} jump targets in every slide file
      (the id is the slide's \\hypertarget, see \\setSlideID);
    - the image manifest's per-slide entries (used_on, notes) in
      media/alt-text.json;
    - slide_ids.csv gets the new id (the old one stays registered, so it is
      never handed out again), then deck-inclusion headers and translation
      cross-references are regenerated;

    `new_id` must start with a letter (slide_ids.regular_id_reason());
    `reserved=True` instead requires the form of the SlideMage manual and
    demo slides (slide_ids.reserved_id_reason()). The collision check
    ignores case, like slide_ids.mint_slide_id().

    All or nothing (slide_edit): a failure puts everything back and raises SlideEditError (an OSError). A failure of
    the review marks, the deck headers or the translation links keeps the rename and is added to `warnings`.

    Returns {old id-slug: new id-slug} for every renamed slide.
    """
    result = slide_edit.apply(slide_edit.plan_id_rename(ctx, old_id, new_id, reserved))
    if warnings is not None:
        warnings.extend(result.warnings)
    return result.mapping


def deck_names_referencing(ctx: ProjectContext, id_slug: str) -> list[str]:
    """Deck names (filename stem, including #workdeck.tex/archived decks)
    that reference id_slug via any \\slide-family call -- for the "Delete
    slide" button's confirmation dialog (2026-09-23, direct instruction:
    "check whether the slide is used in any decks and ask whether the
    user really wants to delete"), so the user sees exactly what's about
    to lose a reference before confirming, not just a bare count."""
    return [deck_path.stem for deck_path in deck_language.call_files(ctx)
            if _references(read_text_exact(deck_path), id_slug)]


def delete_slide_id(ctx: ProjectContext, id_slug: str, remove_deck_references: bool = True,
                    warnings: Optional[list[str]] = None) -> dict[str, int]:
    """Permanently deletes slides/<id_slug>-current.tex and every frozen
    -vX-Y-Z.tex sibling from disk (git rm when tracked, else a plain
    unlink) -- for the "Delete slide" button (2026-09-23, direct
    instruction). Unless remove_deck_references is False, also removes
    every whole \\slide-family call line referencing it from every deck
    (including #workdeck.tex), so no deck is left pointing at a file that
    no longer exists on disk. Also moves this slide's own bare-id data
    from the image store (media/alt-text.json's used_on/notes) into the
    alt-text archive (alt_archive.archive_slides(): nothing is dropped), then
    regenerates deck-inclusion headers and translation cross-references
    (a slide that had a translation link to/from this one gets flagged
    the same "no longer resolves" way a rename target that vanished
    already is, via regenerate_translation_links()'s own missing-target
    reporting).

    The bare id itself is deliberately NOT removed from slide_ids.csv --
    same "never handed out again" reasoning rename_slide_id() above
    already documents, so a future slide can never collide with this
    deleted one's own history.

    The caller is responsible for confirming with the user first (e.g.
    via count_references()/deck_names_referencing() shown in a dialog) --
    this function itself deletes unconditionally, no confirmation of its
    own. Returns {"files_removed": n, "deck_references_removed": n} for
    the caller's own confirmation/log message."""
    result = slide_edit.apply(slide_edit.plan_delete(ctx, id_slug, remove_deck_references))
    if warnings is not None:
        warnings.extend(result.warnings)
    return {"files_removed": result.files, "deck_references_removed": result.references}
