# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""What the host tells a plugin about a deck's slides. Read-only and free of Qt, so a worker thread may call it;
it reuses SlideMage's own readers and parses nothing itself."""
from __future__ import annotations

from pathlib import Path

from .. import (
    alt_blocks, alt_images, compiler, deck_editor, deck_outline, deck_scan, plugin_api, slide_language,
    slide_versioning,
)
from ..fileio import read_text_exact
from ..project import ProjectContext

LANGUAGES = ("de", "en")


def core_deck(deck: plugin_api.Deck) -> deck_scan.Deck:
    """The deck as SlideMage's readers want it, parsed from the snapshot's text."""
    return deck_scan.deck_from_text(deck.path, deck.text)


def check_view(view: str) -> None:
    if view not in deck_editor.VIEWS:
        raise ValueError(f"unknown view {view!r}: one of {', '.join(deck_editor.VIEWS)}")


def output_folder(ctx: ProjectContext, deck: plugin_api.Deck, view: str) -> Path:
    """Where the PDF of `view` goes (compiler.resolve_output_location, the rule a compile follows)."""
    check_view(view)
    job = compiler.CompileJob(core_deck(deck), view, None)
    return compiler.resolve_output_location(ctx, job)[0]


def deck_slides(ctx: ProjectContext, deck: plugin_api.Deck, view: str, language: str) -> list[plugin_api.SlideRef]:
    check_view(view)
    if language not in LANGUAGES:
        raise ValueError(f"unknown language {language!r}: one of {', '.join(LANGUAGES)}")
    source = core_deck(deck)
    refs = []
    for slot in deck_outline.resolve_slots(ctx, source, view, language.upper()):
        call = slot.slot.call
        path = ctx.slides_dir / call.source_filename
        own = slide_language.own_language(call.id_slug)
        version = call.version
        if version is None:
            try:
                parsed = slide_versioning.parse_version(read_text_exact(path))
            except OSError:
                parsed = None
            version = slide_versioning.format_hyphen(parsed) if parsed is not None else None
        title = deck_outline.slide_file_title(path, call.id_slug)
        chapter = slot.slot.original.chapter
        refs.append(plugin_api.SlideRef(
            id=call.id,
            id_slug=call.id_slug,
            path=path,
            language=own.lower() if own else None,
            version=version,
            pinned=call.version is not None,
            title=title,
            position=slot.position,
            hidden=slot.hidden,
            language_read=language,
            title_text=alt_blocks.plain_title(title),
            section=alt_blocks.plain_title(chapter.title) if chapter else "",
        ))
    return refs


def check_slide_path(ctx: ProjectContext, ref: plugin_api.SlideRef) -> Path:
    """ref.path, if it is a .tex file straight inside the project's slides folder."""
    path = Path(ref.path)
    if path.suffix != ".tex" or path.parent.resolve() != ctx.slides_dir.resolve():
        raise ValueError(f"{path} is not a slide file of this project")
    return path


def slide_source(ctx: ProjectContext, ref: plugin_api.SlideRef) -> plugin_api.SlideSource:
    path = check_slide_path(ctx, ref)
    text = read_text_exact(path)
    entries = alt_images.load_store(ctx)
    language = ref.language_read or ref.language or slide_language.own_language(path.name)
    german = language.lower() == "de" if language else False
    media: list[Path] = []
    descriptions: dict[str, plugin_api.MediaDescription] = {}
    for reference in alt_blocks.referenced_images(text):
        found = alt_blocks.resolve_image(ctx, reference)
        if found is not None and found not in media:
            media.append(found)
        entry = alt_images.lookup(entries, reference)
        if entry is not None and entry.image not in descriptions:
            slide_id = slide_language.bare_id(path.name)
            short, long, takeaway = ((entry.short_de, entry.long_de, entry.takeaway_for_de(slide_id)) if german
                                     else (entry.short, entry.long, entry.takeaway_for(slide_id)))
            descriptions[entry.image] = plugin_api.MediaDescription(entry.image, entry.is_decorative, short, long, takeaway)
    return plugin_api.SlideSource(text, tuple(media), tuple(descriptions.values()))
