"""The readability check as an agent tool: can an audience read a slide or a deck? Deterministic, no model, nothing
written (v8.14.0). The rules and the thresholds are readability.py's; readability_check.py renders a slide as a
draft, or reads the deck's compiled PDF when it is current. A deck whose PDF is out of date is not compiled here:
the answer says so, and compile_deck (or the user's Compile) comes first.
"""
from __future__ import annotations

from ... import readability_check, slide_language
from ...readability_check import StalePdf
from .base import ToolContext, ToolError, tool
from .files import current_revision
from .previews import first_error_line
from .slidemage import open_deck, slide_or_file, slide_target

DECK_SLIDE_LIMIT = 40      # slides with findings named in a deck's answer before "and N more"


@tool("check_readability",
      "Check whether the text and images of a slide, or of a whole deck, are big and clear enough to be read by an "
      "audience: text size relative to the slide height (body, headings, sources and footnotes, text in figures), "
      "images shown too small, contrast, clipped or overlapping text, too much text, line spacing. Deterministic, "
      "measured on the rendered pages, and it changes nothing. A slide is rendered as a draft (the unsaved buffer "
      "included) in the user's view and language; a deck uses its compiled PDF and says so if that is out of date "
      "(compile it first; this tool does not). Every finding gives the measured value, the threshold and a "
      "suggestion.",
      {"slide": {"type": "string", "description": "A slide id (1y8) or a path; default the slide in focus."},
       "deck": {"type": "string",
                "description": "Check this deck's compiled PDF instead of one slide: a deck name, or 'open' for the "
                               "open deck."}})
def check_readability(ctx: ToolContext, args: dict) -> str:
    if args.get("slide") and args.get("deck"):
        raise ToolError("Give a slide or a deck, not both.")
    context = ctx.workspace.context()
    if args.get("deck"):
        deck = open_deck(ctx, None if args["deck"].strip().lower() == "open" else args["deck"])
        try:
            report = readability_check.check_deck(ctx.project, deck, context.view, context.language)
        except StalePdf as exc:
            return (f"The compiled PDF of {deck.name} ({context.view}, {context.language}) is not current: {exc}. "
                    "Compile the deck first (compile_deck, or the user's Compile PDF), then check again.")
        except RuntimeError as exc:
            raise ToolError(f"The PDF of {deck.name} could not be read: {exc}") from None
        return f"{deck.name} as {context.view}, {context.language}: " + report.to_text(DECK_SLIDE_LIMIT)
    path = slide_or_file(ctx, args.get("slide"))
    own = slide_language.own_language(path.name)
    language = own if own in slide_language.TRANSLATION_LANGUAGES else context.language
    target = slide_target(ctx.project, open_deck(ctx) if context.deck is not None else None, path, context.view,
                          language)
    if target is None:
        raise ToolError(f"{path.name} is not a slide file, so it has no rendered page to check.")
    text, source = current_revision(ctx.workspace, path)
    try:
        report = readability_check.check_slide(ctx.project, target, text, context.view, language,
                                               context.footer_timestamp, ctx.cancel)
    except RuntimeError as exc:
        raise ToolError(f"{target.bare_id}: the slide ({source}) did not compile, so it was not checked. "
                        f"{first_error_line(str(exc))}") from None
    return f"{path.name} ({source}) as {context.view}, {language}: " + report.to_text()
