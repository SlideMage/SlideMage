"""Modal "Add slide" dialog for the deck slide-list editor: pick an
existing slide or scaffold a brand-new one, then insert the chosen
\\slide{}-family call into the deck at the position the caller requested
(see deck_editor_tab.py's own "+ before"/"+ after" row buttons).
"""
from __future__ import annotations

import re
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Optional

from . import deck_editor, slide_ids
from .deck_scan import Deck

SLUG_RE = re.compile(r"^[A-Za-z0-9]+(-[A-Za-z0-9]+)*$")


class AddSlideDialog(tk.Toplevel):
    def __init__(self, app, deck: Deck, insert_at: int, indent: str):
        super().__init__(app.root)
        self.app = app
        self.deck = deck
        self.insert_at = insert_at
        self.indent = indent
        self._selected_id_slug: Optional[str] = None
        self._listbox_items: list[str] = []
        self._all_slides = slide_ids.list_id_slugs()

        # Deferred import -- see deck_editor_tab.py's own __init__ comment;
        # gui.py imports this module at its own module level to construct
        # AddSlideDialog, so this can't be a module-top import.
        from .gui import VERSIONS, VERSION_LABELS
        self._VERSIONS = VERSIONS
        self._VERSION_LABELS = VERSION_LABELS

        self.title("Add slide")
        self.transient(app.root)
        self.resizable(False, False)
        self.app.theme.register_toplevel(self)

        self.mode_var = tk.StringVar(value="existing")
        self._build()
        self.grab_set()

    # -- widgets ----------------------------------------------------------------

    def _build(self) -> None:
        pad = {"padx": 8, "pady": 4}

        mode_frame = ttk.Frame(self)
        mode_frame.pack(fill="x", **pad)
        ttk.Radiobutton(
            mode_frame, text="Use existing slide", variable=self.mode_var,
            value="existing", command=self._on_mode_change,
        ).pack(side="left")
        ttk.Radiobutton(
            mode_frame, text="Create new slide", variable=self.mode_var,
            value="new", command=self._on_mode_change,
        ).pack(side="left", padx=(12, 0))

        self.existing_frame = ttk.Frame(self)
        ttk.Label(self.existing_frame, text="Search:").pack(anchor="w")
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *a: self._refresh_listbox())
        self.search_entry = ttk.Entry(self.existing_frame, textvariable=self.search_var)
        self.search_entry.pack(fill="x")
        self.listbox = tk.Listbox(self.existing_frame, height=10, exportselection=False)
        self.listbox.pack(fill="both", expand=True, pady=(4, 0))
        self.listbox.bind("<<ListboxSelect>>", lambda e: self._on_existing_selected())
        self.app.theme.register_listbox(self.listbox)

        self.new_frame = ttk.Frame(self)
        ttk.Label(self.new_frame, text="Slug (e.g. MM-Theorem):").pack(anchor="w")
        self.slug_var = tk.StringVar()
        self.slug_entry = ttk.Entry(self.new_frame, textvariable=self.slug_var)
        self.slug_entry.pack(fill="x")

        variant_frame = ttk.Frame(self)
        variant_frame.pack(fill="x", **pad)
        ttk.Label(variant_frame, text="Load as:").pack(side="left")
        self.variant_var = tk.StringVar()
        self.variant_combo = ttk.Combobox(
            variant_frame, textvariable=self.variant_var, state="readonly", width=26
        )
        self.variant_combo.pack(side="left", padx=(8, 0))
        self.variant_combo.bind("<<ComboboxSelected>>", lambda e: self._sync_condition_state())
        self.no_versions_label = ttk.Label(variant_frame, text="", style="Muted.TLabel")
        self.no_versions_label.pack(side="left", padx=(8, 0))

        self.condition_frame = ttk.Frame(self)
        self.condition_frame.pack(fill="x", **pad)
        ttk.Label(self.condition_frame, text="Included in:").pack(side="left")
        self.condition_vars: dict[str, tk.BooleanVar] = {}
        self.condition_checks: dict[str, ttk.Checkbutton] = {}
        for version in self._VERSIONS:
            var = tk.BooleanVar(value=True)
            self.condition_vars[version] = var
            cb = ttk.Checkbutton(
                self.condition_frame, text=self._VERSION_LABELS[version], variable=var
            )
            cb.pack(side="left", padx=(8, 0))
            self.condition_checks[version] = cb

        button_row = ttk.Frame(self)
        button_row.pack(fill="x", **pad)
        ttk.Button(button_row, text="Add", command=self._on_add).pack(side="right")
        ttk.Button(button_row, text="Cancel", command=self.destroy).pack(side="right", padx=(0, 8))

        self._on_mode_change()

    # -- mode/list handling -----------------------------------------------------

    def _on_mode_change(self) -> None:
        if self.mode_var.get() == "existing":
            self.new_frame.pack_forget()
            self.existing_frame.pack(fill="both", expand=True, padx=8, pady=4, before=self.condition_frame)
            self._refresh_listbox()
            self._on_existing_selected()
            # So the user can start typing a search term immediately,
            # without an extra click -- both on first open (this mode is
            # the default) and when switching back to it from "new".
            self.search_entry.focus_set()
        else:
            self.existing_frame.pack_forget()
            self.new_frame.pack(fill="x", padx=8, pady=4, before=self.condition_frame)
            self._selected_id_slug = None
            self._refresh_variant_options([])
            self.slug_entry.focus_set()

    def _refresh_listbox(self) -> None:
        query = self.search_var.get().strip().lower()
        self.listbox.delete(0, "end")
        self._listbox_items = [s for s in self._all_slides if query in s.lower()]
        for item in self._listbox_items:
            self.listbox.insert("end", item)

    def _on_existing_selected(self) -> None:
        selection = self.listbox.curselection()
        if not selection:
            self._selected_id_slug = None
            self._refresh_variant_options([])
            return
        self._selected_id_slug = self._listbox_items[selection[0]]
        self._refresh_variant_options(deck_editor.available_versions(self._selected_id_slug))

    # -- variant handling ---------------------------------------------------------

    def _refresh_variant_options(self, versions: list[str]) -> None:
        options = [f"\\{m} (current)" for m in deck_editor.BASE_MACROS]
        for v in versions:
            options.append(f"\\slideversion (v{v})")
            options.append(f"\\omitslideversion (v{v})")
        self.variant_combo["values"] = options
        if options:
            self.variant_combo.current(0)
        self.no_versions_label.configure(
            text="" if (versions or self.mode_var.get() == "new") else "(no frozen versions available)"
        )
        self._sync_condition_state()

    def _current_macro_version(self) -> tuple[str, Optional[str]]:
        label = self.variant_var.get()
        if not label:
            return "slide", None
        macro = label.split(" ", 1)[0][1:]
        if "(v" in label:
            return macro, label.split("(v", 1)[1].rstrip(")")
        return macro, None

    def _sync_condition_state(self) -> None:
        macro, _ = self._current_macro_version()
        state = "normal" if macro == "conditionalslide" else "disabled"
        for cb in self.condition_checks.values():
            cb.configure(state=state)

    # -- submit -------------------------------------------------------------------

    def _on_add(self) -> None:
        macro, version = self._current_macro_version()
        conditions = None
        if macro == "conditionalslide":
            conditions = [v for v in self._VERSIONS if self.condition_vars[v].get()]
            if not conditions:
                messagebox.showerror(
                    "Add slide", "Pick at least one deck version for \\conditionalslide."
                )
                return

        if self.mode_var.get() == "existing":
            if self._selected_id_slug is None:
                messagebox.showerror("Add slide", "Pick an existing slide from the list.")
                return
            id_slug = self._selected_id_slug
        else:
            slug = self.slug_var.get().strip()
            if not SLUG_RE.match(slug):
                messagebox.showerror(
                    "Add slide",
                    "Slug must be non-empty and hyphen-separated alphanumeric "
                    "words, e.g. MM-Theorem.",
                )
                return
            new_id = slide_ids.mint_slide_id()
            slide_ids.append_slide_id(new_id)
            try:
                slide_ids.create_slide_file(new_id, slug)
            except FileExistsError as exc:
                messagebox.showerror("Add slide", str(exc))
                return
            id_slug = f"{new_id}-{slug}"

        previous_text = self.deck.text
        try:
            deck_editor.insert_slide_call(
                self.deck.path, self.deck.text, self.insert_at, self.indent,
                macro, id_slug, version, conditions,
            )
        except (deck_editor.StaleFileError, ValueError) as exc:
            messagebox.showerror("Add slide failed", str(exc))
            return

        self.destroy()
        self.app.after_deck_edit(
            self.deck.path, f"Added \\{macro}{{{id_slug}}} to {self.deck.name}",
            previous_text=previous_text,
        )
