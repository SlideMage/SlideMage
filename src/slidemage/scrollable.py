"""Reusable canvas-backed scrollable region.

Wraps arbitrary content (built into the returned `.inner` ttk.Frame, exactly
as if it were packed straight into the parent) in a Canvas plus horizontal
and/or vertical Scrollbars that only take up screen space once the content
actually overflows the visible area in that direction -- not a scrollbar
sitting there permanently, uselessly, when there's nothing to scroll.

Used wherever a row of buttons/checkboxes (a deck slide-list editor's own
per-slide row, the main Active/Archived decks table, a slide/deck source
tab's toolbar) can otherwise get silently clipped with no way to reach the
rest of it once the window is narrower than that content's natural width
(see gui.py's own note on the deck editor needing ~1200px by default) --
and, for the deck slide-list editor specifically, also vertically, since its
own row list can run well past 100 entries.

`parent` must be a container ScrollableFrame can freely own the packing of
(it repacks its own canvas/scrollbar(s) from scratch, in the correct order,
every time a bar's visibility needs to change -- see _update_bars below).
Give it a dedicated frame rather than one shared with unrelated siblings
(e.g. a toolbar sitting above some *other* widget that fills the rest of
the tab) -- otherwise that sibling's own packing gets caught up in the
renegotiation. slide_source_tab.py's own toolbar is the worked example: it
wraps its ScrollableFrame in a small dedicated container frame rather than
handing it the tab's whole outer frame (which the ScrolledText editor below
also needs to pack into).
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk


class ScrollableFrame:
    def __init__(
        self,
        parent,
        theme,
        horizontal: bool = True,
        vertical: bool = False,
        canvas_pad: dict | None = None,
    ):
        # canvas_pad: extra padx/pady passed to the canvas's own pack() call
        # (matching whatever spacing the plain frame this replaces used to
        # have); the scrollbar(s) reuse the same pady/padx respectively so
        # a bar doesn't visually hug the tab's edge any tighter than the
        # canvas itself does.
        self._canvas_pad = canvas_pad or {}

        self.canvas = tk.Canvas(parent, highlightthickness=0)
        self.inner = ttk.Frame(self.canvas)
        self._window = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")

        self.hbar = (
            ttk.Scrollbar(parent, orient="horizontal", command=self.canvas.xview)
            if horizontal else None
        )
        self.vbar = (
            ttk.Scrollbar(parent, orient="vertical", command=self.canvas.yview)
            if vertical else None
        )
        if self.hbar is not None:
            self.canvas.configure(xscrollcommand=self.hbar.set)
        if self.vbar is not None:
            self.canvas.configure(yscrollcommand=self.vbar.set)
        self._h_shown = False
        self._v_shown = False

        self.inner.bind("<Configure>", self._on_inner_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self.canvas.pack(side="left", fill="both", expand=True, **self._canvas_pad)
        theme.register_canvas(self.canvas)

        # Only active while the pointer is actually over this canvas --
        # bind_all is otherwise global (would steal every other scrollable
        # widget's wheel events too), the standard Tkinter recipe for this.
        self.canvas.bind("<Enter>", self._bind_mousewheel)
        self.canvas.bind("<Leave>", self._unbind_mousewheel)

    # -- layout -----------------------------------------------------------------

    def _on_inner_configure(self, event=None) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        if self.vbar is None:
            # No vertical scrolling wanted here -- keep the canvas's own
            # height matched to its content's natural height instead, so
            # nothing is ever vertically clipped with no way to reach it;
            # only horizontal overflow is meant to be scrollable in this
            # mode (the main deck table, a toolbar row).
            self.canvas.configure(height=self.inner.winfo_reqheight())
        self._update_bars()

    def _on_canvas_configure(self, event) -> None:
        # Stretch the embedded frame to fill the canvas when its own
        # content is narrower than the canvas (a natural full-width/height
        # fill, matching how a plain packed frame would look) -- but never
        # *shrink* it below its own natural size, or content would get
        # squeezed/wrapped instead of staying reachable by scrolling once
        # it's actually bigger than the canvas.
        width = max(event.width, self.inner.winfo_reqwidth()) if self.hbar is not None else event.width
        height = max(event.height, self.inner.winfo_reqheight()) if self.vbar is not None else event.height
        self.canvas.itemconfigure(self._window, width=width, height=height)
        self._update_bars()

    def _update_bars(self) -> None:
        bbox = self.canvas.bbox("all")
        if bbox is None:
            return
        content_w, content_h = bbox[2], bbox[3]
        canvas_w, canvas_h = self.canvas.winfo_width(), self.canvas.winfo_height()
        want_h = self.hbar is not None and content_w > canvas_w
        want_v = self.vbar is not None and content_h > canvas_h
        if want_h == self._h_shown and want_v == self._v_shown:
            return
        # Full re-pack in the correct order: scrollbar(s) first (each
        # claims its own strip), canvas last (fill=both + expand=True takes
        # whatever's left) -- packing the canvas first would let it claim
        # the entire cavity before a scrollbar ever got a chance to reserve
        # its own strip, the classic Tk pack-manager gotcha for this exact
        # layout, so every visibility change re-does the packing from
        # scratch rather than trying to insert/remove a bar in place.
        self.canvas.pack_forget()
        if self.vbar is not None:
            self.vbar.pack_forget()
        if self.hbar is not None:
            self.hbar.pack_forget()
        if want_v:
            self.vbar.pack(side="right", fill="y", pady=self._canvas_pad.get("pady", 0))
        if want_h:
            self.hbar.pack(side="bottom", fill="x", padx=self._canvas_pad.get("padx", 0))
        self.canvas.pack(side="left", fill="both", expand=True, **self._canvas_pad)
        self._h_shown, self._v_shown = want_h, want_v

    # -- mouse wheel --------------------------------------------------------------

    def _bind_mousewheel(self, event=None) -> None:
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)
        self.canvas.bind_all("<Shift-MouseWheel>", self._on_shift_mousewheel)

    def _unbind_mousewheel(self, event=None) -> None:
        self.canvas.unbind_all("<MouseWheel>")
        self.canvas.unbind_all("<Shift-MouseWheel>")

    def _on_mousewheel(self, event) -> None:
        if self.vbar is not None and self._v_shown:
            self.canvas.yview_scroll(int(-event.delta / 120), "units")
        elif self.hbar is not None and self._h_shown:
            # No vertical scrolling active here -- a plain wheel turn
            # scrolls horizontally instead of requiring Shift, so scrolling
            # does something useful by default (Shift+wheel still works
            # too, see _on_shift_mousewheel).
            self.canvas.xview_scroll(int(-event.delta / 120), "units")

    def _on_shift_mousewheel(self, event) -> None:
        if self.hbar is not None and self._h_shown:
            self.canvas.xview_scroll(int(-event.delta / 120), "units")
