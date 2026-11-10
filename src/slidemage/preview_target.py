# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""What the Preview shows: one slide as its deck typesets it, in the view and
language being edited, and how to render it.

A target is the \\slide{}-family call plus the deck context the render needs
(the deck's preamble, so theme and footer match, and the slide's frame number).
A slide that is not in the open deck, or a frozen version opened by itself,
renders alone under the default template. Rendering goes through
slide_preview (reusable latexmk builds, see preview_build.py).
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Optional

from . import deck_context, project, slide_language, slide_preview, slide_templates
from .deck_editor import VIEW_INSTRUCTOR, VIEWS, SlideCall
from .deck_scan import DECKTAGS_RE, OPEN_PDF_RE, OUTPUT_FOLDER_RE, Deck
from .fileio import text_sha256


def preamble_sha(text: Optional[str]) -> str:
    """The hash of a deck's preamble as TeX typesets it: without the lines only SlideMage reads (the inert
    \\deckoutputfolder and \\decktags, the "%% SlideMage open PDF:" comment), so a deck's PDF output or tags
    settings leave its slides' renders current."""
    kept = []
    for line in (text or '').splitlines(keepends=True):
        bare = OPEN_PDF_RE.sub('', DECKTAGS_RE.sub('', OUTPUT_FOLDER_RE.sub('', line)))
        if bare == line or bare.strip():
            kept.append(line)
    return text_sha256(''.join(kept))


@dataclass(frozen=True)
class PreviewTarget:
    context: project.ProjectContext
    macro: str
    id_slug: str
    version: Optional[str]
    conditions: Optional[tuple[str, ...]]
    steps: Optional[str]
    frame_number: Optional[int]
    preamble_text: Optional[str]    # the deck's; None: the default template's
    occurrence_key: tuple = ()
    hidden: bool = False
    presenter_frame_number: Optional[int] = None
    # The open deck and, for a slide that only makes sense inside it (a contents slide, a chapter agenda, ...: see
    # deck_context), why; `deck_hash` then keeps a render apart from one made for another state of the deck.
    deck: Optional[Deck] = field(default=None, compare=False, repr=False)
    needs_context: tuple = ()
    deck_hash: str = ""
    # The call's 1-based position among the deck's slide calls (deck_context.skeleton): frame_number may be the
    # real frame number instead, which differs once a call before it typesets several frames or none.
    position: Optional[int] = None

    def __post_init__(self):
        if self.conditions is not None:
            object.__setattr__(self, 'conditions', tuple(self.conditions))

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
            return slide_templates.render_template(self.context)
        return slide_templates.detect_template(self.preamble_text)

    @property
    def is_frozen_alone(self) -> bool:
        """A frozen version shown on its own, not as a deck pins it: it is not what the
        slide's cached preview (the current version, or what the decks typeset) shows."""
        return self.version is not None and self.preamble_text is None

    @property
    def key(self) -> tuple:
        """What a render depends on besides the view and the language."""
        return (self.macro, self.id_slug, self.version, tuple(self.conditions or ()), self.steps,
                self.frame_number, self.template,
                preamble_sha(self.preamble_text),
                self.deck_hash if self.needs_context else "") + ((self.occurrence_key,) if self.occurrence_key else ()) + (
                    (self.presenter_frame_number,) if self.presenter_frame_number is not None else ())


def for_call(ctx: project.ProjectContext, deck: Deck, call: SlideCall, position: int, language: Optional[str] = None, *, frame_number: Optional[int] = None,
             occurrence_key: tuple = (), hidden: bool = False, outline=None) -> PreviewTarget:
    """`call`, the `position`-th slide call of `deck`, as the deck typesets it. `outline` (deck_outline.Outline), when it
    describes `deck` in `language`, supplies the translation links and the Instructor frame numbers instead of
    another scan of the slides folder and a resolution of every slot."""
    shared = outline if outline is not None and outline.matches(ctx, deck, language or "EN") else None
    if language is not None:
        from .deck_language import resolve_call
        call = resolve_call(call, language, shared.links if shared else slide_language.links_for(ctx))
    presenter_frame = None
    if occurrence_key:
        if shared:
            presenter_frame = shared.instructor_frames.get(occurrence_key)
        else:
            from .deck_outline import resolve_slots
            presenter_frame = next((r.frame_number for r in resolve_slots(ctx, deck, VIEW_INSTRUCTOR, language or "EN")
                                    if r.key == occurrence_key), None)
    target = PreviewTarget(ctx, call.macro, call.id_slug, call.version, call.conditions, call.steps,
                           position if frame_number is None else frame_number, deck.preamble_text,
                           occurrence_key=occurrence_key, hidden=hidden, presenter_frame_number=presenter_frame,
                           position=position, deck=deck)
    found = deck_context.reasons_for_file(target.source_path)
    if not found:
        return target
    return replace(target, needs_context=found,
                   deck_hash=text_sha256(deck.text))


def requested_views(view: str | None, selected_view: str = VIEW_INSTRUCTOR) -> tuple[str, ...]:
    requested = selected_view if view is None else view
    if requested == "all":
        return VIEWS
    if requested not in VIEWS:
        raise ValueError(f"Invalid preview view: {requested!r}; expected {', '.join((*VIEWS, 'all'))}")
    return (requested,)


def for_path(ctx: project.ProjectContext, path: Path) -> Optional[PreviewTarget]:
    """The slide file `path` rendered alone; None if it is not a slides/ current
    or version file."""
    try:
        macro, id_slug, version = slide_language.call_for_slide_path(path)
    except ValueError:
        return None
    return PreviewTarget(ctx, macro, id_slug, version, None, None, None, None)


def render(target: PreviewTarget, view: str, language: str, *, log,
           cancel=None, all_steps: bool = False, force_build=False) -> Path:
    """Compile the saved slide in `view` and `language` ("EN"/"DE") to a PDF.
    `all_steps` keeps every reveal step (page k = step k) whatever the call or the slide restricts.
    A slide that needs its deck (target.needs_context) is typeset in the deck's last compile when there is one, else
    with the deck's sections and agenda records around it (deck_context).
    Raises RuntimeError with the compile log's tail on failure."""
    if target.hidden:
        raise ValueError(f"Slide {target.id_slug} is hidden in {view}")
    context = {}
    if target.needs_context and target.deck is not None:
        deck, position = target.deck, target.position
        in_deck = deck_context.render_in_deck(
            target.context, deck, view, target.bare_id, target.id_slug, log, cancel,
            all_steps=all_steps, language=language)
        if in_deck is not None:
            return in_deck
        around = None if position is None else deck_context.skeleton(
            target.context, deck, position, target.id_slug, view, language,
            deck_context.aux_titles_for(target.context, deck, view, language))
        if around is not None:
            context = dict(context_before=around.before, context_after=around.after)
    return slide_preview.render_slide_to_pdf(
        target.context, target.macro, target.id_slug, target.version, target.conditions,
        deck_version=view, deck_language=language.lower(),
        preamble_text=target.preamble_text, frame_number=target.frame_number,
        log=log, steps=target.steps, cancel=cancel,
        all_steps=all_steps, **context,
        **({'force_build': True} if force_build else {}))


def render_text(
    target: PreviewTarget, text: str, view: str, language: str, *, log,
    presenter: bool = False, mode: str = "slide", overlay: Optional[int] = None,
    cancel=None, all_steps: bool = False, force_build=False, workspace=None,
) -> Path:
    """Compile `text` (the editor's buffer, saved or not) in place of the slide's
    file. `mode` is "slide", "region" (the text as a frame) or "element" (the
    text cropped); `overlay` shows only that reveal step of each frame.
    A presenter render is the instructor version with beamer's second screen. A whole slide that needs its deck gets
    the deck's sections and agenda records around it (deck_context.skeleton)."""
    if target.hidden and not presenter:
        raise ValueError(f"Slide {target.id_slug} is hidden in {view}")
    context = {}
    if (target.deck is not None and mode == "slide" and not presenter and target.position is not None
            and deck_context.reasons(text)):
        around = deck_context.skeleton(target.context, target.deck, target.position, target.id_slug, view,
                                       language, deck_context.aux_titles_for(target.context, target.deck, view, language))
        if around is not None:
            context = dict(context_before=around.before, context_after=around.after)
    return slide_preview.render_slide_text_to_pdf(
        target.context, target.id_slug, text,
        deck_version=VIEW_INSTRUCTOR if presenter else view, deck_language=language.lower(),
        presenter=presenter, preamble_text=target.preamble_text,
        frame_number=(target.presenter_frame_number if presenter and target.presenter_frame_number is not None
                      else target.frame_number), log=log, preview_mode=mode, overlay=overlay,
        steps=target.steps if mode == "slide" else None,
        final=target.macro == "slidefinal" and mode == "slide",
        slide_version=target.version if mode == "slide" else None,
        omitted=target.macro in ("omitslide", "omitslideversion") and mode == "slide",
        cancel=cancel, all_steps=all_steps,
        workspace=workspace,
        **context,
        **({'force_build': True} if force_build else {}))
