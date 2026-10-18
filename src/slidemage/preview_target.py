"""What the Preview shows: one slide as its deck typesets it, in the view and
language being edited, and how to render it.

A target is the \\slide{}-family call plus the deck context the render needs
(the deck's preamble, so theme and footer match, and the slide's frame number).
A slide that is not in the open deck, or a frozen version opened by itself,
renders alone under the default template. Rendering goes through
slide_preview (reusable latexmk builds, see preview_build.py); a render
of the instructor view also refreshes the slide's cached snapshot, which is
what the Preview shows without compiling anything.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
import hashlib
from pathlib import Path
from typing import Optional

from . import deck_context, project, slide_language, slide_preview, slide_snapshot
from .deck_editor import VIEW_INSTRUCTOR, SlideCall
from .deck_scan import Deck


@dataclass(frozen=True)
class PreviewTarget:
    context: project.ProjectContext
    macro: str
    id_slug: str
    version: Optional[str]
    conditions: Optional[list]
    steps: Optional[str]
    frame_number: Optional[int]
    preamble_text: Optional[str]    # the deck's; None: the default template's
    # The open deck and, for a slide that only makes sense inside it (a contents slide, a chapter agenda, ...: see
    # deck_context), why; `deck_hash` then keeps a render apart from one made for another state of the deck.
    deck: Optional[Deck] = field(default=None, compare=False, repr=False)
    needs_context: tuple = ()
    deck_hash: str = ""

    @property
    def bare_id(self) -> str:
        return slide_language.bare_id(self.id_slug)

    @property
    def source_path(self) -> Path:
        """The slide file this call loads."""
        name = slide_language.frozen_name(self.id_slug, self.version) if self.version else slide_language.current_name(self.id_slug)
        return self.context.slides_dir / name

    @property
    def template(self) -> str:
        if self.preamble_text is None:
            return slide_snapshot.render_template(self.context)
        return slide_snapshot.detect_template(self.preamble_text)

    @property
    def is_frozen_alone(self) -> bool:
        """A frozen version shown on its own, not as a deck pins it: it is not what the
        slide's cached snapshot (the current version, or what the decks typeset) shows."""
        return self.version is not None and self.preamble_text is None

    @property
    def key(self) -> tuple:
        """What a render depends on besides the view and the language."""
        return (self.macro, self.id_slug, self.version, tuple(self.conditions or ()), self.steps,
                self.frame_number, self.template,
                hashlib.sha256((self.preamble_text or '').encode()).hexdigest(),
                self.deck_hash if self.needs_context else "")


def for_call(ctx: project.ProjectContext, deck: Deck, call: SlideCall, position: int, language: Optional[str] = None) -> PreviewTarget:
    """`call`, the `position`-th slide call of `deck`, as the deck typesets it."""
    if language is not None:
        from .deck_language import resolve_call
        call = resolve_call(call, language, slide_language.TranslationLinks(ctx.slides_dir))
    target = PreviewTarget(ctx, call.macro, call.id_slug, call.version, call.conditions, call.steps,
                           position, deck.preamble_text)
    found = deck_context.reasons_for_file(target.source_path)
    if not found:
        return target
    return replace(target, deck=deck, needs_context=found,
                   deck_hash=hashlib.sha256(deck.text.encode()).hexdigest())


def for_path(ctx: project.ProjectContext, path: Path) -> Optional[PreviewTarget]:
    """The slide file `path` rendered alone; None if it is not a slides/ current
    or version file."""
    try:
        macro, id_slug, version = slide_language.call_for_slide_path(path)
    except ValueError:
        return None
    return PreviewTarget(ctx, macro, id_slug, version, None, None, None, None)


def cached_image(target: PreviewTarget) -> Optional[tuple[Path, bool]]:
    """The slide's cached snapshot (strictly in the target's template) and
    whether it is at least as new as the slide's source; None if none was
    captured yet. Only the instructor view is cached, and not for a frozen version
    shown on its own."""
    if target.is_frozen_alone:
        return None
    png = slide_snapshot.snapshot_path(target.context, target.bare_id, target.template, slide_snapshot.FULL_SIZE)
    if not png.is_file():
        return None
    return png, slide_snapshot.is_fresh(target.context, target.bare_id, target.source_path, target.template)


def render(target: PreviewTarget, view: str, language: str, *, footer_timestamp: bool, log,
           capture_snapshot: bool = True, cancel=None, all_steps: bool = False) -> Path:
    """Compile the saved slide in `view` and `language` ("EN"/"DE") to a PDF.
    `all_steps` keeps every reveal step (page k = step k) whatever the call or the slide restricts.
    A slide that needs its deck (target.needs_context) is typeset in the deck's last compile when there is one, else
    with the deck's sections and agenda records around it (deck_context).
    Raises RuntimeError with the compile log's tail on failure."""
    context = {}
    if target.needs_context and target.deck is not None:
        deck, position = target.deck, target.frame_number
        in_deck = deck_context.render_in_deck(
            target.context, deck, view, target.bare_id, target.id_slug, log, cancel,
            footer_timestamp=footer_timestamp, all_steps=all_steps, language=language)
        if in_deck is not None:
            return in_deck
        around = None if position is None else deck_context.skeleton(
            target.context, deck, position, target.id_slug, view, language,
            deck_context.aux_titles_for(target.context, deck, view, language))
        if around is not None:
            context = dict(context_before=around.before, context_after=around.after)
    return slide_preview.render_slide_to_pdf(
        target.context, target.macro, target.id_slug, target.version, target.conditions,
        deck_version=view, deck_language=language.lower(), footer_timestamp=footer_timestamp,
        preamble_text=target.preamble_text, frame_number=target.frame_number,
        log=log, steps=target.steps, capture_snapshot=capture_snapshot and not target.is_frozen_alone, cancel=cancel,
        all_steps=all_steps, **context)


def render_text(
    target: PreviewTarget, text: str, view: str, language: str, *, footer_timestamp: bool, log,
    presenter: bool = False, mode: str = "slide", overlay: Optional[int] = None,
    capture_snapshot: bool = True, cancel=None, all_steps: bool = False,
) -> Path:
    """Compile `text` (the editor's buffer, saved or not) in place of the slide's
    file. `mode` is "slide", "region" (the text as a frame) or "element" (the
    text cropped); `overlay` shows only that reveal step of each frame.
    A presenter render is the instructor version with beamer's second screen. A whole slide that needs its deck gets
    the deck's sections and agenda records around it (deck_context.skeleton)."""
    context = {}
    if (target.deck is not None and mode == "slide" and not presenter and target.frame_number is not None
            and deck_context.reasons(text)):
        around = deck_context.skeleton(target.context, target.deck, target.frame_number, target.id_slug, view,
                                       language, deck_context.aux_titles_for(target.context, target.deck, view, language))
        if around is not None:
            context = dict(context_before=around.before, context_after=around.after)
    return slide_preview.render_slide_text_to_pdf(
        target.context, target.id_slug, text,
        deck_version=VIEW_INSTRUCTOR if presenter else view, deck_language=language.lower(),
        footer_timestamp=footer_timestamp, presenter=presenter, preamble_text=target.preamble_text,
        frame_number=target.frame_number, log=log, preview_mode=mode, overlay=overlay,
        capture_snapshot=capture_snapshot and not target.is_frozen_alone, cancel=cancel, all_steps=all_steps,
        **context)
