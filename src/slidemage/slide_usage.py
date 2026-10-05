r"""Where a slide is used, and what a new version means for those decks
(v5.23.0, direct instruction).

Saving a new version of a slide freezes the old content as -vX-Y-Z and puts
the new content in -current. A deck that calls \slide{ID} follows -current,
so it moves on to the new version by itself; a deck that calls
\slideversion{ID}{X-Y-Z} stays on its pinned version. When a slide is used
in several decks (or pinned somewhere, or has a translation), the save
dialog (qt_slide_usage_dialog.py) asks for each deck:

- "current" (the default): the deck uses the new version. A pinned call
  (\slideversion, \omitslideversion) becomes \slide / \omitslide; a call
  that follows -current already does.
- "keep": the deck stays on what it uses now. A call that follows -current is
  pinned to the version that was just frozen (\slide -> \slideversion,
  \omitslide -> \omitslideversion); a pinned call is left alone.

\slidefinal, \conditionalslide and \slidestep have no pinned form, so a
deck using only those always follows -current (the dialog says so).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from . import deck_editor, slide_language
from .deck_scan import Deck, scan_decks

PINNED = {"slideversion": "slide", "omitslideversion": "omitslide"}
PINNABLE = {"slide": "slideversion", "omitslide": "omitslideversion"}


@dataclass
class DeckUsage:
    deck: Deck
    calls: list = field(default_factory=list)       # deck_editor.SlideCall

    @property
    def pinned_versions(self) -> list[str]:
        return sorted({c.version for c in self.calls if c.macro in PINNED})

    @property
    def following(self) -> bool:
        """At least one call follows -current and can be pinned."""
        return any(c.macro in PINNABLE for c in self.calls)

    @property
    def only_unpinnable(self) -> bool:
        """Every call is of a kind that always follows -current."""
        return all(c.macro not in PINNED and c.macro not in PINNABLE for c in self.calls)

    def state_text(self) -> str:
        parts = []
        if self.pinned_versions:
            parts.append("pinned to " + ", ".join("v" + v.replace("-", ".") for v in self.pinned_versions))
        if self.following:
            parts.append("follows the current version")
        if self.only_unpinnable:
            macros = sorted({c.macro for c in self.calls})
            parts = ["always the current version (\\" + ", \\".join(macros) + ")"]
        return "; ".join(parts)


@dataclass
class Translation:
    id_slug: str
    language: Optional[str]
    path: Path
    decks: list[str]


def _skipped(deck: Deck) -> bool:
    return deck.name.startswith(("#", "zzz_"))


def find_usage(id_slug: str, decks: Optional[list[Deck]] = None) -> list[DeckUsage]:
    """Every deck (archived ones too) that calls this slide, in scan order."""
    usages = []
    for deck in decks if decks is not None else scan_decks():
        if _skipped(deck):
            continue
        calls = [c for c in deck_editor.parse_slide_calls(deck) if c.id_slug == id_slug]
        if calls:
            usages.append(DeckUsage(deck, calls))
    return usages


def find_translations(id_slug: str, text: str, decks: Optional[list[Deck]] = None) -> list[Translation]:
    """The slide's translation partners, named by its own header comment
    ("%% Translation of:" / "%% <LANG> translation:"), with the decks that use
    each. A partner whose file is gone is left out."""
    partners = []
    m = slide_language.TRANSLATION_OF_RE.search(text)
    if m:
        partners.append(slide_language.bare_id(m.group(1)))
    partners += [slide_language.bare_id(x.group(2))
                 for x in slide_language.LANG_TRANSLATION_RE.finditer(text)]
    out = []
    for bare in dict.fromkeys(partners):
        partner = slide_language.current_id_slug_for_bare_id(bare)
        path = slide_language.current_path_for_bare_id(bare)
        if partner is None or path is None or partner == id_slug:
            continue
        used = [u.deck.name for u in find_usage(partner, decks)]
        out.append(Translation(partner, slide_language.own_language(partner), path, used))
    return out


def needs_dialog(usages: list[DeckUsage], translations: list[Translation]) -> bool:
    """More than one deck, a pinned call anywhere, or a translation."""
    return len(usages) > 1 or any(u.pinned_versions for u in usages) or bool(translations)


def apply_choices(id_slug: str, choices: dict[str, str], frozen_version: Optional[str]) -> list[str]:
    """Rewrite the decks' calls as chosen ({deck name: "current" | "keep"};
    frozen_version is the hyphenated version just frozen, "1-1-0" -- None if
    nothing was frozen, then "keep" can pin nothing). Re-reads every deck, so
    a deck edited since the dialog opened is handled on its current text.
    Returns one log line per deck that changed."""
    log = []
    for usage in find_usage(id_slug):
        choice = choices.get(usage.deck.name)
        if choice not in ("current", "keep"):
            continue
        changes = 0
        text = usage.deck.text
        for call in sorted(usage.calls, key=lambda c: c.call_start, reverse=True):
            if not call.editable:
                continue
            if choice == "current" and call.macro in PINNED:
                text = deck_editor.change_slide_call_variant(
                    usage.deck.path, text, call, PINNED[call.macro])
                changes += 1
            elif choice == "keep" and call.macro in PINNABLE and frozen_version:
                text = deck_editor.change_slide_call_variant(
                    usage.deck.path, text, call, PINNABLE[call.macro], new_version=frozen_version)
                changes += 1
        if changes:
            verb = "now uses the new version" if choice == "current" else f"stays on v{frozen_version.replace('-', '.')}"
            log.append(f"    {usage.deck.name}: {changes} call(s) changed -- {verb}")
    return log
