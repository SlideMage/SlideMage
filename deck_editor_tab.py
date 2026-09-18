"""Tk tab listing one deck's own \\slide{}-family call list -- the deck
slide-list editor opened by clicking a deck's name in the main table (see
gui.py's SlideManagerApp.open_deck_editor). Scrollable (canvas + scrollbar,
unlike the main table) since a deck's slide list can run well past 100
rows.

Every row-level action (remove, change variant, insert) delegates the
actual file edit to deck_editor.py, then runs the same after-edit sequence
via SlideManagerApp.after_deck_edit: background header resync, resync the
main table's own Deck snapshot, rebuild this tab, log a summary line.

Undo: rather than a confirmation dialog before a destructive action (the
original "Remove slide call" behavior), each mutating action hands its
pre-edit whole-file text to after_deck_edit, which pushes it onto this
tab's own `_undo_stack`. The Undo button pops the most recent snapshot and
writes it straight back via deck_editor.restore_deck_text -- undo is
itself just another edit, so it goes through the same stale-file check as
everything else, but deliberately does *not* push its own undo entry (no
redo feature, per explicit user request: "It's enough ... if it undoes the
latest action only"). Multiple undo steps fell out for free from the same
mechanism, capped at `_UNDO_LIMIT` purely so a very long editing session
doesn't accumulate an unbounded list of whole-file strings. A manual
Refresh clears the stack -- it re-reads the file from disk (e.g. to pick up
an outside edit made in TeXstudio), and undoing back past that point would
mean discarding whatever the refresh just picked up.
"""
from __future__ import annotations

import threading
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Optional

from . import deck_editor, slide_preview
from .deck_editor import SlideCall
from .deck_scan import Deck
from .scrollable import ScrollableFrame
from .slide_ids import SLIDES_DIR


class DeckEditorTab:
    # Whole-file text snapshots kept per undo step -- deck files are at
    # most a few hundred lines, so even this many strings is negligible
    # memory; the cap just exists so a long session doesn't grow it
    # forever, not because it's expensive.
    _UNDO_LIMIT = 20

    def __init__(self, app, deck: Deck):
        self.app = app
        self.notebook = app.notebook
        self.deck = deck
        self._undo_stack: list[str] = []

        # Deferred import -- gui.py imports this module at its own module
        # level to construct DeckEditorTab, so importing gui.py back at
        # this module's top level would be circular. By the time a tab is
        # actually opened (this __init__ runs), gui.py has long since
        # finished loading.
        from .gui import VERSIONS, VERSION_LABELS
        self._VERSIONS = VERSIONS
        self._VERSION_LABELS = VERSION_LABELS

        self.frame = ttk.Frame(self.notebook)
        self.notebook.add(self.frame, text=f"{deck.name} (slides)")

        toolbar = ttk.Frame(self.frame)
        toolbar.pack(fill="x", padx=4, pady=4)
        ttk.Button(toolbar, text="Refresh", command=self._on_refresh).pack(side="left")
        ttk.Button(toolbar, text="Source", command=self._on_source).pack(side="left", padx=(8, 0))
        self.undo_button = ttk.Button(
            toolbar, text="Undo", command=self._on_undo, state="disabled"
        )
        self.undo_button.pack(side="left", padx=(8, 0))
        ttk.Button(toolbar, text="Close", command=self._on_close).pack(side="left", padx=(8, 0))

        # Both directions: vertical since a deck's slide list can run well
        # past 100 rows, horizontal since one row's own content (position,
        # id-slug link, variant combo, conditions, Apply/+before/+after/
        # Render/Remove) needs ~1200px by default (see gui.py's own note)
        # and would otherwise just get clipped with no way to reach it once
        # the window's narrower than that.
        self._scrollable = ScrollableFrame(
            self.frame, self.app.theme, horizontal=True, vertical=True,
            canvas_pad={"padx": (4, 0), "pady": 4},
        )
        self.inner = self._scrollable.inner

        self._build_rows()

    # -- public API used by gui.py -------------------------------------------

    def select(self) -> None:
        self.notebook.select(self.frame)

    def reload(self, deck: Deck) -> None:
        self.deck = deck
        self._build_rows()

    # -- toolbar actions --------------------------------------------------------

    def _on_refresh(self) -> None:
        """Re-reads this deck from disk -- every row action here already
        rebuilds the tab on its own (see after_deck_edit), so this is only
        for picking up a change made outside the app (e.g. hand-editing the
        deck's own .tex file in TeXstudio) without closing and reopening
        the tab."""
        fresh_deck = self.app.resync_deck(self.deck.path)
        if fresh_deck is None:
            messagebox.showerror(
                "Refresh failed",
                f"{self.deck.name} could not be found -- it may have been "
                "archived or removed since this tab was opened.",
            )
            return
        self.reload(fresh_deck)
        self._undo_stack.clear()
        self._update_undo_button_state()
        self.app.log(f"Refreshed {self.deck.name} (slides)")

    def _on_source(self) -> None:
        """Opens this deck's own raw .tex file in the same editor used for
        a slide's source (see SlideManagerApp.open_deck_source_editor) --
        saving there re-parses and rebuilds this tab automatically via the
        usual after_deck_edit() pipeline, so there's nothing to wire up
        here beyond opening it."""
        self.app.open_deck_source_editor(self.deck, return_to=self.frame)

    def record_undo_snapshot(self, previous_text: str) -> None:
        """Called by SlideManagerApp.after_deck_edit right before it
        applies an edit's own post-edit reload -- `previous_text` is the
        deck's whole-file text from just before that edit."""
        self._undo_stack.append(previous_text)
        del self._undo_stack[: -self._UNDO_LIMIT]
        self._update_undo_button_state()

    def _update_undo_button_state(self) -> None:
        self.undo_button.configure(state="normal" if self._undo_stack else "disabled")

    def _on_undo(self) -> None:
        if not self._undo_stack:
            return
        previous_text = self._undo_stack.pop()
        try:
            deck_editor.restore_deck_text(self.deck.path, self.deck.text, previous_text)
        except deck_editor.StaleFileError as exc:
            # Nothing was written -- put the snapshot back so a retry (e.g.
            # after a Refresh) can still use it.
            self._undo_stack.append(previous_text)
            messagebox.showerror("Undo failed", str(exc))
            return
        self._update_undo_button_state()
        # No previous_text here -- undoing isn't itself undoable (no redo
        # stack), see the module docstring.
        self.app.after_deck_edit(self.deck.path, f"Undid last change to {self.deck.name}")

    def _on_close(self) -> None:
        self.notebook.forget(self.frame)
        # ttk.Notebook's own post-forget() default is whatever tab now sits
        # at this index -- which lands on "Archived decks" whenever a deck
        # editor tab is closed right after "Active decks" in the tab order,
        # rather than back on the main table the user actually came from.
        self.notebook.select(self.app.active_tab)
        self.app.close_deck_editor(self.deck.path)

    # -- row construction -----------------------------------------------------

    def _build_rows(self) -> None:
        for child in self.inner.winfo_children():
            child.destroy()

        calls = deck_editor.parse_slide_calls(self.deck)
        if not calls:
            ttk.Label(
                self.inner,
                text="This deck has no \\slide{}-family calls of its own "
                     "(e.g. a wrapper deck that \\input{}s a shared slide list).",
                style="Muted.TLabel",
            ).grid(row=0, column=0, sticky="w", padx=8, pady=8)
            return

        row_index = 0
        last_chapter_title = object()  # sentinel, never equal to a real title or None
        for position, call in enumerate(calls, start=1):
            title = call.chapter.title if call.chapter is not None else None
            if title != last_chapter_title:
                last_chapter_title = title
                header_text = title if title is not None else "(before first chapter)"
                ttk.Label(
                    self.inner, text=header_text, font=("", 9, "bold")
                ).grid(row=row_index, column=0, columnspan=8, sticky="w", padx=4, pady=(10, 2))
                row_index += 1
            self._build_row(row_index, position, call)
            row_index += 1

    def _build_row(self, row_index: int, position: int, call: SlideCall) -> None:
        ttk.Label(self.inner, text=str(position), width=3).grid(row=row_index, column=0, padx=4)

        link = ttk.Label(self.inner, text=call.id_slug, style="Link.TLabel", cursor="hand2")
        link.grid(row=row_index, column=1, sticky="w", padx=4)
        link.bind(
            "<Button-1>",
            lambda e, c=call: self.app.open_slide_editor(
                SLIDES_DIR / c.source_filename, return_to=self.frame
            ),
        )

        ttk.Button(
            self.inner, text="+ before", width=8,
            command=lambda: self._on_insert(call, before=True),
        ).grid(row=row_index, column=5, padx=2)
        ttk.Button(
            self.inner, text="+ after", width=7,
            command=lambda: self._on_insert(call, before=False),
        ).grid(row=row_index, column=6, padx=2)
        render_button = ttk.Button(
            self.inner, text="Render", width=7,
            command=lambda: self._on_render(call, render_button),
        )
        render_button.grid(row=row_index, column=8, padx=2)

        if not call.editable:
            ttk.Label(
                self.inner, text=f"read-only: {call.readonly_reason}", style="Warning.TLabel"
            ).grid(row=row_index, column=2, columnspan=3, sticky="w", padx=4)
            return

        versions = deck_editor.available_versions(call.id_slug)
        options, current_index = self._variant_options(call, versions)
        initial_label = options[current_index]
        variant_var = tk.StringVar(value=initial_label)
        combo = ttk.Combobox(
            self.inner, textvariable=variant_var, state="readonly", width=26, values=options
        )
        combo.grid(row=row_index, column=2, padx=4)

        cond_vars = {
            v: tk.BooleanVar(value=(call.conditions is not None and v in call.conditions))
            for v in self._VERSIONS
        }
        initial_cond_values = {v: cond_vars[v].get() for v in self._VERSIONS}
        cond_frame = ttk.Frame(self.inner)
        cond_frame.grid(row=row_index, column=3, padx=4)
        cond_checks = {}
        for v in self._VERSIONS:
            cb = ttk.Checkbutton(cond_frame, text=self._VERSION_LABELS[v][:1], variable=cond_vars[v])
            cb.pack(side="left")
            cond_checks[v] = cb

        apply_button = ttk.Button(
            self.inner, text="Apply", width=6,
            command=lambda: self._on_apply(call, variant_var, cond_vars),
        )
        apply_button.grid(row=row_index, column=4, padx=2)

        def sync_row_state(*_args) -> None:
            # The I/D/A condition checkboxes only mean anything for
            # \conditionalslide -- shown (not just enabled) only once the
            # dropdown actually selects it, hidden otherwise rather than
            # left visible-but-grayed-out.
            macro, _ = self._parse_option(variant_var.get())
            conditional = macro == "conditionalslide"
            if conditional:
                cond_frame.grid()
            else:
                cond_frame.grid_remove()

            # Apply only matters once there's something pending to apply --
            # hidden while the row still matches its on-disk state, shown
            # as soon as either the variant dropdown or (for
            # \conditionalslide) a condition checkbox diverges from it.
            dirty = variant_var.get() != initial_label
            if conditional:
                dirty = dirty or any(
                    cond_vars[v].get() != initial_cond_values[v] for v in self._VERSIONS
                )
            if dirty:
                apply_button.grid()
            else:
                apply_button.grid_remove()

        combo.bind("<<ComboboxSelected>>", sync_row_state)
        for cb in cond_checks.values():
            cb.configure(command=sync_row_state)
        sync_row_state()
        ttk.Button(
            self.inner, text="Remove", width=7,
            command=lambda: self._on_remove(call),
        ).grid(row=row_index, column=7, padx=(2, 4))

    # -- variant option formatting --------------------------------------------

    def _variant_options(self, call: SlideCall, versions: list[str]) -> tuple[list[str], int]:
        options = [self._format_option(m, None) for m in deck_editor.BASE_MACROS]
        for v in versions:
            options.append(self._format_option("slideversion", v))
            options.append(self._format_option("omitslideversion", v))
        current_label = self._format_option(call.macro, call.version)
        try:
            idx = options.index(current_label)
        except ValueError:
            # e.g. this call pins a version that's since been removed from
            # disk -- keep it selectable/visible rather than silently
            # swapping the row to something else.
            options.insert(0, current_label)
            idx = 0
        return options, idx

    @staticmethod
    def _format_option(macro: str, version: Optional[str]) -> str:
        return f"\\{macro} (v{version})" if version is not None else f"\\{macro} (current)"

    @staticmethod
    def _parse_option(label: str) -> tuple[str, Optional[str]]:
        macro = label.split(" ", 1)[0][1:]
        if "(v" in label:
            return macro, label.split("(v", 1)[1].rstrip(")")
        return macro, None

    # -- actions --------------------------------------------------------------

    def _on_apply(self, call: SlideCall, variant_var: tk.StringVar, cond_vars: dict) -> None:
        macro, version = self._parse_option(variant_var.get())
        conditions = None
        if macro == "conditionalslide":
            conditions = [v for v in self._VERSIONS if cond_vars[v].get()]
            if not conditions:
                messagebox.showerror(
                    "Change variant", "Pick at least one deck version for \\conditionalslide."
                )
                return
        previous_text = self.deck.text
        try:
            deck_editor.change_slide_call_variant(
                self.deck.path, self.deck.text, call, macro, version, conditions
            )
        except (deck_editor.StaleFileError, ValueError) as exc:
            messagebox.showerror("Change variant failed", str(exc))
            return
        self.app.after_deck_edit(
            self.deck.path,
            f"Changed {call.id_slug} in {self.deck.name}: \\{call.macro} -> \\{macro}",
            previous_text=previous_text,
        )

    def _on_remove(self, call: SlideCall) -> None:
        # No confirmation dialog -- the toolbar's Undo button (see the
        # module docstring) covers this instead.
        previous_text = self.deck.text
        try:
            deck_editor.remove_slide_call(self.deck.path, self.deck.text, call)
        except (deck_editor.StaleFileError, ValueError) as exc:
            messagebox.showerror("Remove failed", str(exc))
            return
        self.app.after_deck_edit(
            self.deck.path,
            f"Removed \\{call.macro}{{{call.id_slug}}} from {self.deck.name}",
            previous_text=previous_text,
        )

    def _on_insert(self, call: SlideCall, before: bool) -> None:
        insert_at = call.line_start if before else call.line_end
        self.app.open_add_slide_dialog(self.deck, insert_at, call.indent)

    def _on_render(self, call: SlideCall, button: ttk.Button) -> None:
        # Uses this deck's own preamble (theme/colors/footer), so the
        # preview matches how the slide actually looks inside this deck --
        # unlike the slide-source editor's own "Render to PDF", which has
        # no deck context and falls back to a generic preamble.
        button.configure(state="disabled")
        threading.Thread(target=self._render_bg, args=(call, button), daemon=True).start()

    def _render_bg(self, call: SlideCall, button: ttk.Button) -> None:
        log = self.app.log_queue.put
        try:
            pdf_path = slide_preview.render_slide_to_pdf(
                call.macro, call.id_slug, call.version, call.conditions,
                preamble_text=self.deck.preamble_text, log=log,
            )
        except RuntimeError as exc:
            log(f"*** Render failed: {exc} ***")
        else:
            slide_preview.open_pdf(pdf_path)
        finally:
            self.app.root.after(0, lambda: button.configure(state="normal"))
