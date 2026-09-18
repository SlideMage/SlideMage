"""Tk tab for editing one slide's own .tex source file directly inside
SlideManager, instead of switching out to TeXstudio/Notepad++. Encoding/
EOL safety and the backup history are entirely slide_source.py's job; this
module is just the Text widget plus dirty-tracking/save/close/highlighting
wiring around it.

Also reused, unmodified, by the deck slide-list editor's own "Source"
button (see gui.py's open_deck_source_editor) to edit a deck's raw .tex
file the same way -- `path` need not live under slides/ at all. The
Render-to-PDF controls only make sense for an actual slides/*.tex file
(they need a single \\slide{}-family call to preview), so they're built
only when slide_preview.call_for_slide_path(path) actually resolves;
editing a deck's source just gets the plain Save/Revert/Close editor.
"""
from __future__ import annotations

import re
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, scrolledtext, ttk
from typing import Callable, Optional

from . import slide_preview, slide_source
from .deck_scan import PROJECT_ROOT
from .scrollable import ScrollableFrame

# Deliberately basic, regex-based LaTeX highlighting -- not a real
# tokenizer/parser (no brace-nesting or math-mode awareness), just enough
# to make comments and command names visually distinct while editing.
# Comments: an unescaped "%" through end of line -- "unescaped" is
# approximated as "not immediately preceded by a single backslash" (the
# classic even/odd-backslash-count edge case, e.g. "\\%", is not handled;
# vanishingly rare in this project's actual slide sources, and not worth
# the extra complexity for what's meant to be "a form of" highlighting,
# not a full LaTeX parser).
COMMENT_RE = re.compile(r"(?<!\\)%.*")
# Commands: a control word (\foo, optionally starred: \item*) or a control
# symbol (\%, \{, \\, ...) -- the latter matched *before* BRACE_RE gets a
# chance to see a bare "{"/"}" inside one, so e.g. \{ highlights as one
# command token rather than a command-colored "\" next to a
# brace-colored "{".
COMMAND_RE = re.compile(r"\\[a-zA-Z]+\*?|\\.")
# Braces: only counted when NOT part of a \{ / \} escape (see COMMAND_RE
# above) -- same even/odd-backslash caveat as COMMENT_RE.
BRACE_RE = re.compile(r"(?<!\\)[{}]")

# Monospace, not this app's usual proportional Tk default -- brace/indent
# alignment in source text is unreadable otherwise. Consolas has shipped
# with Windows since Vista, so it's safe to assume here the same way this
# project already assumes MiKTeX/Git for Windows elsewhere (Windows-only
# project throughout, see compiler.py's own comments).
SOURCE_FONT = ("Consolas", 10)

# The project's own \textcolor{}-able palette -- these names aren't defined
# anywhere in Python; they're \definecolor{}'d once per institution in
# Slidemaster_preamble_{uni-graz,mci,uni-ibk}.tex (identical names, only the
# hex values differ per institution) and demonstrated together on
# slides/ZZM-Slidemaster-colors-current.tex, in the order README.md
# documents as "sorted by relevance" (primary, then secondary/tertiary hue
# pairs, then custom last). This dropdown deliberately uses a *different*
# order (direct instruction) -- category first (custom, primary, secondary,
# tertiary), alphabetical within each category -- since picking a color by
# name benefits more from a predictable, scannable order than from that
# relevance grouping.
_TEXTCOLOR_CATEGORY_ORDER = {"custom": 0, "primary": 1, "secondary": 2, "tertiary": 3}


def _textcolor_sort_key(name: str) -> tuple[int, str]:
    # "c_primary_dark" -> "primary" -- every name follows this exact
    # c_<category>_<hue> shape (see README.md's own naming-scheme note).
    category = name.split("_")[1]
    return (_TEXTCOLOR_CATEGORY_ORDER[category], name)


TEXTCOLOR_PALETTE = sorted(
    [
        "c_primary_dark", "c_primary_highlight", "c_primary_gray", "c_primary_white",
        "c_secondary_violet", "c_tertiary_violet", "c_secondary_blue", "c_tertiary_blue",
        "c_secondary_green", "c_tertiary_green", "c_secondary_red", "c_tertiary_red",
        "c_secondary_orange", "c_tertiary_orange", "c_secondary_yellow", "c_tertiary_yellow",
        "c_tertiary_gray", "c_custom_gray", "c_custom_red", "c_custom_green",
    ],
    key=_textcolor_sort_key,
)
COLOR_COMBO_PLACEHOLDER = "Text color..."

# This project's reveal-step-aware macros (Slidemaster_preamble_base.tex) --
# just the two the user actually wants a shortcut for, not the full
# deckonly/deckuncover/deckvisible/deckreveal family. Each entry is
# (dropdown display text, macro prefix for _wrap_or_insert -- or None if
# the command takes no braced content of its own, in which case the
# display text itself IS the literal token to insert/replace-selection-with).
REVEAL_COMMANDS = [
    ("\\conditionalpause[instructor]", None),
    ("\\only<2->{...}", "only<2->"),
]
REVEAL_COMBO_PLACEHOLDER = "Insert reveal command..."


class SlideSourceTab:
    def __init__(
        self,
        app,
        path: Path,
        on_saved: Optional[Callable[[str], None]] = None,
        return_to: Optional[ttk.Frame] = None,
    ):
        self.app = app
        self.notebook = app.notebook
        self.path = path
        # Called after a successful save with the *previous* (pre-save)
        # text -- lets a caller that cares about this particular file
        # react to it changing (currently: the deck slide-list editor's
        # "Source" button routes this straight into the same
        # after_deck_edit() pipeline every row action already uses, so a
        # hand-edit to the deck's raw source gets header-sync + tab-refresh
        # + an Undo-stack entry exactly like any other deck edit).
        self.on_saved = on_saved
        # The deck-editor tab (its own ttk.Frame) this slide was opened
        # from, if any -- reselected on close instead of leaving
        # ttk.Notebook's own post-forget() default (whatever tab now sits
        # at this index) to land on some unrelated tab, e.g. a second deck
        # tab open further right. Kept up to date by
        # SlideManagerApp.open_slide_editor on every (re)open, not just the
        # first, so returning to the *most recently* navigated-from tab
        # always wins over a stale one from an earlier visit.
        self.return_to = return_to
        try:
            slide_preview.call_for_slide_path(path)
            self._is_slide = True
        except ValueError:
            self._is_slide = False

        # Deferred import -- see deck_editor_tab.py's own __init__ comment;
        # gui.py imports this module at its own module level to construct
        # SlideSourceTab, so this can't be a module-top import.
        from .gui import VERSIONS, VERSION_LABELS
        self._LABEL_TO_VERSION = {label: version for version, label in VERSION_LABELS.items()}

        self.frame = ttk.Frame(self.notebook)
        self.notebook.add(self.frame, text=path.name)

        self.text, self.eol = slide_source.read_slide_source(path)

        # A dedicated container for the toolbar's own ScrollableFrame --
        # ScrollableFrame needs to freely pack/unpack its horizontal
        # scrollbar within its parent as content overflows, which would
        # otherwise conflict with the ScrolledText widget packed below (a
        # shared parent's packing order/cavity negotiation gets confused if
        # two unrelated things repack themselves in the same frame -- see
        # that module's own docstring). This container holds nothing else.
        toolbar_container = ttk.Frame(self.frame)
        toolbar_container.pack(fill="x")
        self._toolbar_scrollable = ScrollableFrame(
            toolbar_container, self.app.theme, horizontal=True, vertical=False,
            canvas_pad={"padx": 4, "pady": 4},
        )
        toolbar = self._toolbar_scrollable.inner
        ttk.Button(toolbar, text="Save", command=self._on_save).pack(side="left")
        self.revert_button = ttk.Button(
            toolbar, text="Revert", command=self._on_revert, state="disabled"
        )
        self.revert_button.pack(side="left", padx=(8, 0))
        if self._is_slide:
            self.render_button = ttk.Button(toolbar, text="Render to PDF", command=self._on_render)
            self.render_button.pack(side="left", padx=(8, 0))
            # Defaults to Instructor -- render_slide_text_to_pdf always passes
            # this explicitly rather than leaving it unset, since an unset
            # \deckversion[] leaves Slidemaster_preamble_base.tex's own
            # \ifgothamInstructorVersion-family booleans false even though
            # \gothamDeckVersion (the plain string) itself defaults to
            # "instructor" -- confirmed directly: a slide whose own content
            # branches on \ifgothamInstructorVersion (not just the string)
            # rendered incorrectly with no \deckversion[] call at all, not just
            # ambiguously.
            self.version_var = tk.StringVar(value=VERSION_LABELS["instructor"])
            self.version_combo = ttk.Combobox(
                toolbar, textvariable=self.version_var, state="readonly", width=14,
                values=[VERSION_LABELS[v] for v in VERSIONS],
            )
            self.version_combo.pack(side="left", padx=(8, 0))
        ttk.Button(toolbar, text="Close", command=self._on_close).pack(side="left", padx=(8, 0))
        ttk.Button(
            toolbar, text="Close and save", command=self._on_close_and_save
        ).pack(side="left", padx=(8, 0))
        self.dirty_label = ttk.Label(toolbar, text="", style="Warning.TLabel")
        self.dirty_label.pack(side="left", padx=(8, 0))

        # A second, separate toolbar row for text-formatting actions --
        # its own dedicated container/ScrollableFrame, same reasoning as
        # toolbar_container above (a ScrollableFrame needs to own its
        # parent's packing outright). Buttons that wrap the current
        # selection in a single-argument macro (Italic/Bold/Typewriter/
        # Source/Footnote -- the ones actually used most often in this
        # project's own slides, by grep count) are grouped on the left;
        # the two dropdowns (color palette, reveal-logic commands) follow.
        format_toolbar_container = ttk.Frame(self.frame)
        format_toolbar_container.pack(fill="x")
        self._format_toolbar_scrollable = ScrollableFrame(
            format_toolbar_container, self.app.theme, horizontal=True, vertical=False,
            canvas_pad={"padx": 4, "pady": (0, 4)},
        )
        format_toolbar = self._format_toolbar_scrollable.inner
        ttk.Button(
            format_toolbar, text="I", width=3, command=lambda: self._wrap_or_insert("textit")
        ).pack(side="left")
        ttk.Button(
            format_toolbar, text="B", width=3, command=lambda: self._wrap_or_insert("textbf")
        ).pack(side="left", padx=(4, 0))
        ttk.Button(
            format_toolbar, text="Tt", width=3, command=lambda: self._wrap_or_insert("texttt")
        ).pack(side="left", padx=(4, 0))
        ttk.Button(
            format_toolbar, text="Source", command=lambda: self._wrap_or_insert("source")
        ).pack(side="left", padx=(8, 0))
        ttk.Button(
            format_toolbar, text="Footnote", command=lambda: self._wrap_or_insert("footnote")
        ).pack(side="left", padx=(4, 0))

        self.color_var = tk.StringVar(value=COLOR_COMBO_PLACEHOLDER)
        self.color_combo = ttk.Combobox(
            format_toolbar, textvariable=self.color_var, state="readonly", width=20,
            values=TEXTCOLOR_PALETTE,
        )
        self.color_combo.pack(side="left", padx=(12, 0))
        self.color_combo.bind("<<ComboboxSelected>>", lambda e: self._on_color_selected())

        self.reveal_var = tk.StringVar(value=REVEAL_COMBO_PLACEHOLDER)
        self.reveal_combo = ttk.Combobox(
            format_toolbar, textvariable=self.reveal_var, state="readonly", width=22,
            values=[label for label, _ in REVEAL_COMMANDS],
        )
        self.reveal_combo.pack(side="left", padx=(8, 0))
        self.reveal_combo.bind("<<ComboboxSelected>>", lambda e: self._on_reveal_selected())

        self.widget = scrolledtext.ScrolledText(self.frame, undo=True, font=SOURCE_FONT)
        self.widget.pack(fill="both", expand=True, padx=4, pady=(0, 4))
        self.app.theme.register_syntax_text(self.widget)
        self.widget.insert("1.0", self.text)
        self._highlight()
        self.widget.edit_modified(False)
        self._dirty = False
        self.widget.bind("<<Modified>>", self._on_modified)

    # -- public API used by gui.py -----------------------------------------------

    def select(self) -> None:
        self.notebook.select(self.frame)

    # -- syntax highlighting --------------------------------------------------------

    def _highlight(self) -> None:
        """Re-tag the whole buffer -- cheap enough at slide-file sizes
        (tens to a couple hundred lines) to just do on every keystroke
        rather than debounce or highlight incrementally."""
        widget = self.widget
        content = widget.get("1.0", "end-1c")
        for tag in ("latex_comment", "latex_command", "latex_brace"):
            widget.tag_remove(tag, "1.0", "end")

        comment_spans = [m.span() for m in COMMENT_RE.finditer(content)]

        def in_comment(pos: int) -> bool:
            return any(start <= pos < end for start, end in comment_spans)

        for start, end in comment_spans:
            widget.tag_add("latex_comment", f"1.0+{start}c", f"1.0+{end}c")
        for m in COMMAND_RE.finditer(content):
            if not in_comment(m.start()):
                widget.tag_add("latex_command", f"1.0+{m.start()}c", f"1.0+{m.end()}c")
        for m in BRACE_RE.finditer(content):
            if not in_comment(m.start()):
                widget.tag_add("latex_brace", f"1.0+{m.start()}c", f"1.0+{m.end()}c")

    # -- dirty tracking -----------------------------------------------------------

    def _on_modified(self, event=None) -> None:
        if self.widget.edit_modified():
            self._set_dirty(True)
            self._highlight()
            # Tk's modified flag is edge-triggered, not level-triggered --
            # clear it now so the *next* keystroke fires <<Modified>> again.
            self.widget.edit_modified(False)

    def _set_dirty(self, dirty: bool) -> None:
        self._dirty = dirty
        self.dirty_label.configure(text="(unsaved changes)" if dirty else "")
        self.revert_button.configure(state="normal" if dirty else "disabled")

    # -- actions --------------------------------------------------------------------

    def _wrap_or_insert(self, prefix: str) -> None:
        """Shared by every single-argument-macro toolbar button/dropdown
        entry (Italic/Bold/Typewriter/Source/Footnote, the color combo --
        `prefix` already includes the color's own leading brace group, e.g.
        "textcolor{c_secondary_blue}" -- and \\only<2->{...}): if text is
        currently selected, wrap it in \\{prefix}{...}; otherwise insert
        \\{prefix}{} with the cursor placed between the braces, ready to
        type straight into.

        .replace()/.insert() (not delete()+insert()) go through the
        widget's normal edit API and produce a single atomic undo-stack
        entry each, so one Ctrl+Z fully reverts the action -- and
        <<Modified>> fires exactly as it would for typed input, so
        dirty-tracking/re-highlighting (see _on_modified above) need no
        special-casing for any of these call sites.

        Ends with focus_set() either way -- moving the "insert" mark alone
        only changes *where* a keystroke would land once the widget has
        focus, not which widget has it; without this, focus is left on
        whichever toolbar button/dropdown triggered the call (that's what
        the user just clicked/picked from), so typing right after picking
        a color with nothing selected would go nowhere near the new {}."""
        ranges = self.widget.tag_ranges("sel")
        if not ranges:
            insert_point = self.widget.index("insert")
            token = f"\\{prefix}{{}}"
            self.widget.insert(insert_point, token)
            self.widget.mark_set("insert", f"{insert_point}+{len(token) - 1}c")
        else:
            start, end = ranges
            selected = self.widget.get(start, end)
            self.widget.replace(start, end, f"\\{prefix}{{{selected}}}")
        self.widget.focus_set()

    def _replace_selection_or_insert(self, literal: str) -> None:
        """For a reveal command with no braced content of its own (e.g.
        \\conditionalpause[instructor]) -- acts like typing the literal text
        over the current selection, or at the cursor if nothing's
        selected. See _wrap_or_insert's own docstring for why this ends
        with focus_set() too."""
        ranges = self.widget.tag_ranges("sel")
        if ranges:
            start, end = ranges
            self.widget.replace(start, end, literal)
        else:
            self.widget.insert("insert", literal)
        self.widget.focus_set()

    def _on_color_selected(self) -> None:
        color = self.color_var.get()
        # Reset to the placeholder immediately, before _wrap_or_insert runs
        # -- <<ComboboxSelected>> only fires on a value *change*, so leaving
        # the just-picked name showing would silently do nothing if the
        # user picks that same color again on a later selection.
        self.color_var.set(COLOR_COMBO_PLACEHOLDER)
        self._wrap_or_insert(f"textcolor{{{color}}}")

    def _on_reveal_selected(self) -> None:
        label = self.reveal_var.get()
        self.reveal_var.set(REVEAL_COMBO_PLACEHOLDER)
        # dict.get()'s own default distinguishes "not found" from a found
        # entry whose prefix is legitimately None (the no-braces case) --
        # unlike a truthiness check, which would conflate the two.
        lookup = dict(REVEAL_COMMANDS)
        if label not in lookup:
            return
        prefix = lookup[label]
        if prefix is None:
            self._replace_selection_or_insert(label)
        else:
            self._wrap_or_insert(prefix)

    def _on_save(self) -> None:
        new_text = self.widget.get("1.0", "end-1c")
        previous_text = self.text
        backup_path = slide_source.save_slide_source(self.path, new_text, self.eol)
        self.text = new_text
        self._set_dirty(False)
        if backup_path is not None:
            self.app.log(f"Saved {self.path.name} (backup: {backup_path.relative_to(PROJECT_ROOT)})")
        else:
            self.app.log(f"Saved {self.path.name} (new file, no prior content to back up)")
        if self.on_saved is not None:
            self.on_saved(previous_text)

    def _on_revert(self) -> None:
        if not self._dirty:
            return
        if not messagebox.askyesno(
            "Revert", f"Discard unsaved changes to {self.path.name} and reload the saved version?"
        ):
            return
        self.text, self.eol = slide_source.read_slide_source(self.path)
        self.widget.delete("1.0", "end")
        self.widget.insert("1.0", self.text)
        self._highlight()
        self.widget.edit_modified(False)
        self._set_dirty(False)
        self.app.log(f"Reverted {self.path.name} to the saved version")

    def _on_render(self) -> None:
        # Always renders the current in-editor buffer directly (never
        # saves first, never touches the file on disk) -- so an unsaved
        # edit previews immediately, and the dirty flag / Revert button
        # stay exactly as they were before rendering. See
        # slide_preview.render_slide_text_to_pdf's own docstring for how.
        try:
            _, id_slug, _ = slide_preview.call_for_slide_path(self.path)
        except ValueError as exc:
            messagebox.showerror("Render failed", str(exc))
            return

        slide_body = self.widget.get("1.0", "end-1c")
        deck_version = self._LABEL_TO_VERSION[self.version_var.get()]

        self.render_button.configure(state="disabled")
        threading.Thread(
            target=self._render_bg, args=(id_slug, slide_body, deck_version), daemon=True
        ).start()

    def _render_bg(self, id_slug: str, slide_body: str, deck_version: str) -> None:
        log = self.app.log_queue.put
        try:
            pdf_path = slide_preview.render_slide_text_to_pdf(
                id_slug, slide_body, deck_version=deck_version, log=log
            )
        except RuntimeError as exc:
            log(f"*** Render failed: {exc} ***")
        else:
            slide_preview.open_pdf(pdf_path)
        finally:
            self.app.root.after(0, lambda: self.render_button.configure(state="normal"))

    def _on_close(self) -> None:
        if self._dirty:
            # Yes -> save then close; No -> close without saving;
            # Cancel (None) -> stay open, same as the old plain
            # confirm/deny dialog's "no" used to, just with a real third
            # option instead of that doing double duty for both "cancel"
            # and "discard".
            choice = messagebox.askyesnocancel(
                "Close slide source",
                f"Save changes to {self.path.name} before closing?",
            )
            if choice is None:
                return
            if choice:
                self._on_save()
        self._close_tab()

    def _on_close_and_save(self) -> None:
        # No prompt -- "Close and save" is itself the explicit choice the
        # dialog above would otherwise be asking about.
        if self._dirty:
            self._on_save()
        self._close_tab()

    def _close_tab(self) -> None:
        self.notebook.forget(self.frame)
        # Return to whichever deck tab this slide was (most recently)
        # opened from, if it's still open -- see self.return_to above.
        # Guarded with a TclError catch, not a tabs()-membership check,
        # since the originating deck tab may itself have been closed while
        # this one was open, in which case its underlying Tk widget is
        # already destroyed and .select() on it would raise.
        if self.return_to is not None:
            try:
                self.notebook.select(self.return_to)
            except tk.TclError:
                pass
        self.app.close_slide_editor(self.path)
