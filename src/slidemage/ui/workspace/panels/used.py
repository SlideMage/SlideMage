# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Used in decks: every deck that calls the focused slide, how, and where in the deck.

Clicking a row opens that deck at that slide. What a version change means for these decks is
asked at save time (dialogs/slide_usage_dialog.py) and set per deck in the Slide versions panel."""
from __future__ import annotations

from .... import deck_outline
from ....slide_usage import DeckUsage, call_text, find_usage
from ...kit import kit_qss as q
from ..menus import VIEW_LABELS
from ..state import VIEWS
from .base import Row, SidePanel, box, empty_row


class UsedInDecks(SidePanel):
    key = "used"
    title = "Used in decks"

    def build(self, id_slug: str) -> None:
        usages = find_usage(self.app.project, id_slug, self.app.decks, language=self.state.language)
        frame, layout = box()
        if not usages:
            empty_row(layout, "No deck calls this slide.")
        for usage in usages:
            for call, position in zip(usage.calls, usage.positions):
                self._add_call(layout, usage, call, position)
        self.place(frame, "Edits to the current version reach every deck that follows it.")

    def _add_call(self, layout, usage: DeckUsage, call, position: int) -> None:
        row = Row(layout)
        row.make_clickable(lambda: self._open(usage, call, position))
        row.setToolTip("Open this deck at this slide")
        row.add_text(usage.deck.name + (" (archived)" if usage.deck.archived else ""), q.PANEL_MONO)
        how = f"{call_text(call)} · slide {position} of {usage.total}"
        hidden = [VIEW_LABELS[v] for v in VIEWS if not call.included_in(v)]
        if hidden:
            how += " · hidden in " + ", ".join(hidden)
        row.add_text(how, q.PANEL_CAPTION)

    def _open(self, usage: DeckUsage, call, position: int) -> None:
        self.state.set_deck(usage.deck)
        # The occurrence is the slot at that place of the deck: the list selects it, not the slide's first use.
        slot = deck_outline.resolve_slots(self.app.project, usage.deck, self.state.view, self.state.language)[position - 1]
        self.state.set_focused_slide(call.id, occurrence_key=slot.key)
