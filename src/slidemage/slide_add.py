"""What the Add slide sheet (ui/dialogs/add_slide.py) does besides drawing itself: the new slide
files, the deck call that adds a slide to a deck, and the list of slides to pick from.

* A new slide starts from one of the FRAMES (the gallery order; the thumbnails are
  assets/frames/<frame>.png). The standard frame is the project's own starter slide
  (slide-template.tex); the others are the skeletons below, which show the frame's arguments.
* A copy is a duplicate in the source's language (nothing links the two) or a translation into
  another language (linked both ways by the "Translation of" / "<LANG> translation" comments).
  The body of a translation can be machine-translated first: translate_body().
* call_spec() turns "load as" and "appears in" into the deck call (deck_editor.format_call).

Ids, files and links come from slide_ids / slide_rename; nothing here touches a deck file.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from . import alt_draft, deck_editor, deck_outline, slide_ids, slide_language, slide_rename
from .ai.providers import ChatProvider
from .slide_import import escape_latex

SLUG_RE = re.compile(r"^[A-Za-z0-9]+(-[A-Za-z0-9]+)*$")
FRAMES_DIR = Path(__file__).resolve().parent / "assets" / "frames"
DEFAULT_TITLE = "Title"

STANDARD_FRAME = "standardframe"
# Frame -> source of a new slide of that frame; "@title@" stands for the (LaTeX-escaped) title.
# Pictures are placeholders to replace. The standard frame is the project's template instead.
_SKELETONS = {
    STANDARD_FRAME: "",
    "figureframe": "\\begin{figureframe}{@title@}\n"
                   "\t%\\includegraphics[height=0.64\\textheight]{media/your-figure.png}\n"
                   "\\end{figureframe}\n",
    "sideimageframe": "\\begin{sideimageframe}{@title@}{media/your-image.pdf}\n"
                      "\t\\begin{itemize}\n\t\t\\item\n\t\\end{itemize}\n"
                      "\\end{sideimageframe}\n",
    "highlightframe": "\\begin{highlightframe}{@title@}\n"
                      "\t\\begin{itemize}\n\t\t\\item\n\t\\end{itemize}\n"
                      "\\end{highlightframe}\n",
    "quoteframe": "\\SMAgendaTitle{@title@}\n"
                  "\\quoteframe{The quote.}\n\t{Author}\n",
    "sectionframe": "\\begin{sectionframe}{@title@}\n\tWhat this part is about.\n\\end{sectionframe}\n",
    "titleframe": "\\titleframe{@title@}{Subtitle}\n",
    "standout": "\\SMAgendaTitle{@title@}\n"
                "\\begin{frame}[standout]\n\tOne slide, one statement\n\\end{frame}\n",
    "fullbleedframe": "\\SMAgendaTitle{@title@}\n\\fullbleedframe{media/your-image.pdf}\n",
}
FRAMES = tuple(_SKELETONS)
# What a frame needs from the user before it compiles.
NEEDS_IMAGE = ("sideimageframe", "fullbleedframe")

# A slide body of a few screens, translated as one block: leave room for the answer.
TRANSLATION_MAX_TOKENS = 4096

def slide_path(id_slug: str) -> Path:
    """The live file of a slide."""
    return slide_ids.SLIDES_DIR / slide_language.current_name(id_slug)


def frame_thumbnail(frame: str) -> Path:
    return FRAMES_DIR / f"{frame}.png"


def frame_body(frame: str, title: str) -> str:
    """The text of a new slide of `frame` called `title` (plain text; "Title" when empty)."""
    shown = escape_latex(title.strip()) or DEFAULT_TITLE
    skeleton = _SKELETONS[frame]
    if not skeleton:
        return slide_ids.read_template().replace("{" + DEFAULT_TITLE + "}", "{" + shown + "}", 1)
    return skeleton.replace("@title@", shown).replace("\n", "\r\n")   # as the template and the header


# -- new files ------------------------------------------------------------------------------

@dataclass(frozen=True)
class CreatedSlide:
    id_slug: str
    path: Path


def create_new(slug: str, language: str, frame: str = STANDARD_FRAME, title: str = "") -> CreatedSlide:
    """A new slide of `frame` in `language` (one of slide_language.LANGUAGES), with a fresh id."""
    return _create(slug, language, frame_body(frame, title))


def create_copy(
    source_id_slug: str, slug: str, language: Optional[str] = None, body: Optional[str] = None,
) -> CreatedSlide:
    """A new slide seeded from `source_id_slug`'s saved content (or from `body`, e.g. its
    translation). Without `language` it is a duplicate in the source's language (EN when the source
    has none), independent of the source; with one, a translation into it, linked with the source."""
    source = slide_path(source_id_slug)
    if body is None:
        body = slide_ids.slide_body(source)
    if language is None:
        return _create(slug, slide_language.own_language(source_id_slug) or "EN", body)
    created = _create(slug, language, body, translation_of=source_id_slug)
    slide_ids.add_translation_backreference(source, language, created.id_slug)
    slide_rename.regenerate_translation_links()
    return created


def _create(slug: str, language: str, body: str, translation_of: Optional[str] = None) -> CreatedSlide:
    new_id = slide_ids.mint_slide_id()
    slide_ids.append_slide_id(new_id)
    path = slide_ids.create_slide_file(new_id, slug, language, translation_of, body)
    return CreatedSlide(f"{new_id}-{language}-{slug}", path)


def source_body(id_slug: str) -> str:
    """What a copy of `id_slug` starts from: the saved text of the slide without its header."""
    return slide_ids.slide_body(slide_path(id_slug))


def slug_of(id_slug: str) -> str:
    """The descriptive part of an id-slug (a copy gets a fresh id and keeps or changes this)."""
    return slide_rename.parse_id_slug(id_slug)[2]


def other_languages(id_slug: str) -> list[str]:
    """The languages a translation of the slide can be written in: all but its own."""
    own = slide_language.own_language(id_slug)
    return [code for code in slide_language.LANGUAGES if code != own]


def can_machine_translate(id_slug: str, target: str) -> bool:
    """Whether a model can translate the slide into `target`. Only English to German is
    configured (translation_prompts.json has no other direction, and even the hardcoded
    last-resort prompt is worded "into German"): offering another would silently produce a
    mistranslation instead of an honest refusal."""
    return slide_language.own_language(id_slug) == "EN" and target == "DE"


def translate_body(provider: ChatProvider, body: str) -> tuple[str, Optional[str]]:
    """(translation, error) of a slide body, sent to the model as one block. Experimental: a
    translation model knows nothing about LaTeX, so a command's argument text can come back
    altered; reviewing the result is the user's job."""
    backend = alt_draft.ModelTranslationBackend(provider, max_tokens=TRANSLATION_MAX_TOKENS)
    translated, error = backend.translate_text(body)
    eol = "\r\n" if "\r\n" in body else "\n"
    return re.sub(r"\r?\n", eol, translated), error


# -- adding to a deck ------------------------------------------------------------------------

@dataclass(frozen=True)
class CallSpec:
    macro: str
    version: Optional[str] = None
    conditions: Optional[list[str]] = None
    steps: Optional[str] = None


def call_spec(load: str, views: list[str], version: Optional[str] = None, steps: str = "") -> CallSpec:
    """The deck call for loading a slide as `load` ("live", "frozen" or "step") in the deck versions `views`
    (deck_editor.DEFAULT_CONDITIONS): \\slide, or \\conditionalslide when it leaves some out;
    \\slideversion of a frozen `version` (which has no per-version form); \\slidestep of `steps`
    (a beamer overlay list, "2" or "1-2,4"). ValueError says what is missing."""
    if load == "frozen":
        if not version:
            raise ValueError("Pick the frozen version to add.")
        return CallSpec("slideversion", version)
    conditions = [v for v in deck_editor.DEFAULT_CONDITIONS if v in views]
    if not conditions:
        raise ValueError("The slide has to appear in at least one deck version.")
    if load == "step":
        return CallSpec("slidestep", conditions=conditions,
                        steps=deck_editor.normalize_steps(steps or deck_editor.DEFAULT_STEPS))
    if conditions == deck_editor.DEFAULT_CONDITIONS:
        return CallSpec("slide")
    return CallSpec("conditionalslide", conditions=conditions)


# -- the slides to pick from -------------------------------------------------------------------

@dataclass(frozen=True)
class ProjectSlide:
    id_slug: str
    title: str
    badge: str      # "[EN]", "[EN + DE]" or ""


def project_slides() -> list[ProjectSlide]:
    """Every slide of the project, sorted by id-slug."""
    slides = []
    links = slide_language.TranslationLinks()
    for id_slug in slide_ids.list_id_slugs():
        path = slide_path(id_slug)
        slides.append(ProjectSlide(id_slug, deck_outline.slide_file_title(path, id_slug),
                                   slide_language.badge_for(id_slug, path, links=links).text()))
    return slides
