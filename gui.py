"""SlideManager's Tkinter GUI: pick decks/versions/level from a table, or
archive a deck out of decks/ into decks/archive/."""
from __future__ import annotations

import os
import queue
import re
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, scrolledtext, ttk
from typing import Callable, Optional

from . import archive as archive_mod
from . import deck_headers
from . import theme as theme_mod
from . import version as version_mod
from .add_slide_dialog import AddSlideDialog
from .compiler import BUILD_DIR, PDF_DIR, CancelToken, CompileJob, run_jobs
from .deck_editor_tab import DeckEditorTab
from .deck_scan import DECKS_DIR, Deck, scan_decks
from .scrollable import ScrollableFrame
from .slide_ids import SLIDES_DIR, list_id_slugs
from .slide_source_tab import SlideSourceTab
from .unused_content import archive_unused_content

VERSIONS = ["instructor", "during-course", "after-course"]
VERSION_LABELS = {
    "instructor": "Instructor",
    "during-course": "During-course",
    "after-course": "After-course",
}

RUNNING_LOG_RE = re.compile(r"^==== Compiling \S+ -> (\S+) ====")
MOVING_LOG_RE = re.compile(r"^==== MOVING: (\S+) ->")
PASS_LOG_RE = re.compile(r"^==== PASS: (\S+) ->")
FAIL_LOG_RE = re.compile(r"^\*\*\* FAIL: (\S+) --")
DONE_LOG_RE = re.compile(r"^==== Done: (.+) ====$")
# slide_preview.py's own render_slide_to_pdf() logging -- distinct wording
# ("Rendering"/"render of") from the compile-job lines above on purpose,
# so the two never collide despite sharing the same "==== ... ====" style.
RENDER_START_RE = re.compile(r"^==== Rendering (\S+) -> \S+ ====")
RENDER_PASS_RE = re.compile(r"^==== PASS: render of (\S+) ->")
RENDER_FAIL_RE = re.compile(r"^\*\*\* FAIL: render of (\S+) --")
# latexmk's own "Run number 3 of rule 'lualatex'"/"...'biber /path/jobname'"
# lines -- raw latexmk output, not one of compiler.py's synthetic ====
# lines, so it carries no jobname to look up in _job_status_map. Since jobs
# run strictly sequentially (run_jobs() processes them one at a time on the
# single background thread), the currently-tracked "running" progress text
# is unambiguous -- see _current_progress_base in SlideManagerApp.
RUN_NUMBER_RE = re.compile(r"^Run number (\d+) of rule '([^']+)'")

SPINNER_INTERVAL_MS = 400


def _job_column_key(job: CompileJob) -> str:
    """Which status indicator a job belongs to: one of the three version
    keys, or "chapter" for every per-chapter job (they all share the single
    "After-course, per chapter" checkbox, so they share its status dot)."""
    if job.chapter is not None:
        return "chapter"
    return job.version or "instructor"


def _build_progress_texts(jobs: list[CompileJob]) -> dict[str, str]:
    """One human-readable "what job is this" line per job, keyed by
    jobname, for the status bar -- SlideManagerApp appends the right
    suffix for whatever's actually happening right now. Per-chapter jobs
    are counted against that *one deck's* own chapter count ("Chapter
    5/12"), a real, fixed total known up front. Whole-deck jobs get no
    batch-position counter of their own (there's no meaningful fixed total
    to put on the other side of a slash -- latexmk decides how many
    lualatex/biber passes a compile actually needs as it goes, it isn't
    known in advance); the deck name alone identifies which job this is,
    and _log()'s "Compile N..." suffix (built from latexmk's own "Run
    number N of rule '...'" lines) reports live progress instead. When the
    batch spans more than one distinct deck, every line is prefaced with
    "Deck I/N | " (I = this job's deck's 1-based position among the
    batch's distinct decks in job order, N = how many distinct decks total)
    -- omitted entirely for a single-deck batch, where it would just be a
    constant "Deck 1/1" adding noise, not information."""
    deck_order: list[str] = []
    for job in jobs:
        if job.deck.name not in deck_order:
            deck_order.append(job.deck.name)
    deck_position = {name: i + 1 for i, name in enumerate(deck_order)}
    total_decks = len(deck_order)

    texts: dict[str, str] = {}
    for job in jobs:
        prefix = (
            f"Deck {deck_position[job.deck.name]}/{total_decks} | "
            if total_decks > 1
            else ""
        )
        if job.chapter is None:
            texts[job.jobname] = f"{prefix}Compiling {job.deck.name}"
        else:
            total_chapters = len(job.deck.chapters)
            texts[job.jobname] = (
                f"{prefix}Compiling {job.deck.name}: Chapter {job.chapter.order}/"
                f"{total_chapters}"
            )
    return texts


class DeckRow:
    """One row of checkboxes (plus an optional Archive button) for one deck."""

    def __init__(
        self,
        parent: ttk.Frame,
        deck: Deck,
        row_index: int,
        theme: theme_mod.ThemeManager,
        on_archive: Optional[Callable[[Deck], None]] = None,
        on_open: Optional[Callable[[Deck], None]] = None,
        on_quick_compile: Optional[Callable[["DeckRow"], None]] = None,
    ):
        self.deck = deck
        self.theme = theme
        self.vars: dict[str, tk.BooleanVar] = {}
        self.status_labels: dict[str, ttk.Label] = {}
        self._running_keys: set[str] = set()

        # Link-styled and clickable -- opens the deck slide-list editor tab
        # (see SlideManagerApp.open_deck_editor) for this deck, on both the
        # Active and Archived tabs.
        name_label = ttk.Label(parent, text=deck.name, style="Link.TLabel", cursor="hand2")
        name_label.grid(row=row_index, column=0, sticky="w", padx=(4, 12), pady=2)
        if on_open is not None:
            name_label.bind("<Button-1>", lambda e, d=deck: on_open(d))

        col = 1
        for version in VERSIONS:
            cell = ttk.Frame(parent)
            cell.grid(row=row_index, column=col, padx=8)
            var = tk.BooleanVar(value=False)
            self.vars[version] = var
            # Instructor is always selectable -- for a deck with no
            # \deckversionoverride support at all, checking it just means
            # "compile with whatever's hardcoded in the file" (see
            # selected_versions() below). Only During-course/After-course
            # actually depend on \deckversionoverride existing.
            state = "normal" if (version == "instructor" or deck.supports_version) else "disabled"
            ttk.Checkbutton(cell, variable=var, state=state).pack(side="left")
            status = ttk.Label(cell, text="", width=2)
            status.pack(side="left")
            self.status_labels[version] = status
            col += 1

        chapter_cell = ttk.Frame(parent)
        chapter_cell.grid(row=row_index, column=col, padx=8)
        self.chapter_var = tk.BooleanVar(value=False)
        chapter_state = "normal" if deck.has_chapters else "disabled"
        ttk.Checkbutton(chapter_cell, variable=self.chapter_var, state=chapter_state).pack(
            side="left"
        )
        chapter_status = ttk.Label(chapter_cell, text="", width=2)
        chapter_status.pack(side="left")
        self.status_labels["chapter"] = chapter_status
        col += 1

        if on_archive is not None:
            ttk.Button(
                parent, text="Archive", command=lambda: on_archive(deck)
            ).grid(row=row_index, column=col, padx=(12, 4))
            col += 1

        if on_quick_compile is not None:
            # Ignores this row's own version/chapter checkboxes entirely --
            # always instructor, whole deck -- so it stays useful as a fast
            # "does this deck still compile" check regardless of whatever's
            # currently ticked for a real batch run.
            ttk.Button(
                parent, text="Quick compile", command=lambda: on_quick_compile(self)
            ).grid(row=row_index, column=col, padx=(4, 4))

    def selected_versions(self) -> list[Optional[str]]:
        if not self.deck.supports_version:
            # Only the "Instructor" box is enabled for such a deck; checking
            # it means "compile with whatever version is hardcoded in the
            # file" (usually instructor) -- no \deckversionoverride needed.
            return [None] if self.vars["instructor"].get() else []
        return [v for v in VERSIONS if self.vars[v].get()]

    def build_jobs(self) -> list[CompileJob]:
        """The three version checkboxes and the per-chapter checkbox are
        independent actions, not a 2D grid: each checked version box always
        produces one *whole-deck* compile of that version, and the
        per-chapter box (always the after-course version -- that's the one
        given to students for post-course review, split up for easier
        navigation) independently produces one compile per chapter. Both
        can be requested in the same run."""
        jobs: list[CompileJob] = [
            CompileJob(self.deck, version, None) for version in self.selected_versions()
        ]

        if self.chapter_var.get() and self.deck.has_chapters:
            chapter_version = "after-course" if self.deck.supports_version else None
            for chapter in self.deck.chapters:
                jobs.append(CompileJob(self.deck, chapter_version, chapter))

        return jobs

    def reset_status(self) -> None:
        """Clear every status dot back to blank -- called right before a new
        compile run starts, so a stale PASS/FAIL from a previous run doesn't
        linger next to a box that isn't even part of this run."""
        self._running_keys.clear()
        for label in self.status_labels.values():
            label.configure(text="", foreground=self.theme.colors["fg"])

    def set_status(self, key: str, status: str) -> None:
        """Update one status dot through its lifecycle: "running" (animated
        dots -- the job is actively compiling), "moving" (a static orange
        arrow -- the PDF itself compiled fine and it's now trying to
        relocate it into pdf/, which can take a while if that's retrying
        against a sync-client lock), "pass" (green check), or "fail" (red
        X). The "chapter" key is shared by every per-chapter job for this
        deck (there's only one checkbox for all of them) -- once any of
        them has failed, a later chapter starting/moving/passing shouldn't
        paint over that and hide the failure, so a FAIL is sticky until the
        next reset_status()."""
        label = self.status_labels.get(key)
        if label is None:
            return
        if status == "fail":
            self._running_keys.discard(key)
            label.configure(text="✗", foreground=self.theme.status_color("fail"))
            return
        if label.cget("text") == "✗":
            return  # sticky fail (see above) -- ignore further updates
        if status == "running":
            self._running_keys.add(key)
            label.configure(text=".", foreground=self.theme.status_color("running"))
        elif status == "moving":
            self._running_keys.discard(key)
            label.configure(text="→", foreground=self.theme.status_color("moving"))
        elif status == "pass":
            self._running_keys.discard(key)
            label.configure(text="✓", foreground=self.theme.status_color("pass"))

    def tick_spinner(self, frame: int) -> None:
        """Advance the animated "..." for every status dot currently in the
        "running" state -- called on a shared timer from SlideManagerApp
        rather than each row running its own, so all dots animate in
        lockstep and there's only ever one after()-chain to worry about."""
        if not self._running_keys:
            return
        dots = "." * (frame % 3 + 1)
        for key in self._running_keys:
            self.status_labels[key].configure(text=dots)


class SlideManagerApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("SlideManager")
        # Height is 1.5x the old 650 default (975); width was widened from
        # 900 to 1200 so the deck slide-list editor's own row of buttons
        # (position, id-slug link, variant combo, conditions, Apply/+before/
        # +after/Render/Remove) fits without clipping by default -- measured
        # directly against this project's own two largest real decks
        # (t-Uni-FM2-2027s/t-Uni-IA2-2026w, ~1000px of row content each,
        # including their longest id-slug link text) rather than guessed.
        # Reduced back down by 16% (direct instruction, 2026-07-28, after the
        # toolbar's settings cluster was tightened up) to 1008 -- close
        # enough to that ~1000px figure that the deck editor's own row may
        # clip again for those two decks' longest id-slug text; widen this
        # back toward 1200 if that's ever actually seen rather than assumed.
        root.geometry("1008x975")

        self.theme = theme_mod.ThemeManager(root)
        self.theme.apply()

        self.log_queue: "queue.Queue[str]" = queue.Queue()
        self.compiling = False
        self.cancel_token: Optional[CancelToken] = None
        self._stop_buttons: list[tk.Button] = []
        self._tk_buttons: list[tk.Button] = []
        self._job_status_map: dict[str, tuple[DeckRow, str]] = {}
        self._job_progress_texts: dict[str, str] = {}
        self._current_progress_base = ""
        self._spinner_frame = 0
        # Keyed by path, deduping already-open tabs -- reselecting an
        # already-open deck editor/slide source instead of reopening it.
        self._deck_editor_tabs: dict[Path, DeckEditorTab] = {}
        self._slide_source_tabs: dict[Path, SlideSourceTab] = {}

        self.notebook = ttk.Notebook(root)
        self.notebook.pack(fill="both", expand=True, padx=8, pady=8)

        self.active_tab = ttk.Frame(self.notebook)
        self.archived_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.active_tab, text="Active decks")
        self.notebook.add(self.archived_tab, text="Archived decks")

        # Overlaid on the notebook's own tab-strip row via place() -- a
        # child of self.notebook itself, not root, so it's positioned
        # relative to the notebook's own top-right corner rather than
        # needing to duplicate root's own padx/pady by hand. There's
        # normally blank space to the right of the "Active decks"/"Archived
        # decks" tabs themselves (rarely more than a couple of tabs open at
        # once), and floating the search bar there keeps the tab strip
        # pinned to the very top of the window instead of pushing it down
        # to make room for a whole extra row above it. Unlike self.toolbar
        # below (hidden while a deck/slide editor tab is showing, see
        # _on_tab_changed), "find a slide" is useful from *any* tab,
        # including while already editing a different slide, so it's never
        # hidden -- place()'d directly on the notebook, it stays visible
        # (and stays pinned to the tab row) no matter which tab is selected.
        self.search_bar = ttk.Frame(self.notebook)
        self.search_bar.place(relx=1.0, x=-8, y=4, anchor="ne")
        self.slide_search_var = tk.StringVar()
        self.slide_search_entry = ttk.Entry(
            self.search_bar, textvariable=self.slide_search_var, width=28
        )
        self.slide_search_entry.pack(side="right")
        ttk.Label(self.search_bar, text="Find slide:").pack(side="right", padx=(4, 6))
        self.slide_search_var.trace_add("write", lambda *a: self._on_slide_search_changed())
        self.slide_search_entry.bind("<Down>", self._on_slide_search_down)
        self.slide_search_entry.bind("<Up>", self._on_slide_search_up)
        self.slide_search_entry.bind("<Return>", self._on_slide_search_enter)
        self.slide_search_entry.bind("<Escape>", self._on_slide_search_escape)
        self.slide_search_entry.bind("<FocusOut>", self._on_slide_search_focus_out)
        self._slide_search_popup: Optional[tk.Toplevel] = None
        self._slide_search_listbox: Optional[tk.Listbox] = None
        self._slide_search_matches: list[str] = []
        self._slide_search_selected = 0

        self.toolbar = ttk.Frame(root)
        self.toolbar.pack(fill="x", padx=8, pady=(0, 4))
        ttk.Button(
            self.toolbar, text="Empty pdf/ folder", command=self._empty_pdf_folder
        ).pack(side="left")
        ttk.Button(
            self.toolbar, text="Remove temp files", command=self._remove_temp_files
        ).pack(side="left", padx=(8, 0))
        ttk.Button(
            self.toolbar,
            text="Archive unused content",
            command=self._archive_unused_content,
        ).pack(side="left", padx=(8, 0))
        # Grouped together on the right, apart from the action buttons to
        # their left -- all three are display/behavior toggles rather than
        # one-shot batch actions, so they read as their own settings
        # cluster: a row of three checkboxes, with the version string
        # right-aligned underneath.
        #
        # The version label is a sibling of checkbox_row within
        # settings_frame -- deliberately *not* nested inside its own little
        # frame together with just the "Dark mode" checkbox (an earlier
        # attempt at this). That nesting always left a blank strip
        # somewhere, whichever side the pair was anchored to: the version
        # string is wider than "Dark mode" alone, so anchoring the pair
        # right left a gap *before* the checkbox (reading as its own,
        # disconnected group -- the very first version of this layout);
        # anchoring left instead left the same gap *after* it, pushing the
        # window's usable right edge out further than the actual content
        # needed (confirmed directly against both). Checkbox_row's own
        # width (three checkboxes + their 16px inter-gaps) is wider than
        # the version string alone, so making it settings_frame's *other*
        # child -- rather than boxing the label together with just one
        # checkbox -- lets settings_frame's natural width follow the row,
        # with the label simply right-anchored (anchor="e") to whatever
        # that width turns out to be: flush under "Dark mode" with no
        # leftover blank space on either side, and nothing forcing the
        # window wider than the row itself needs.
        settings_frame = ttk.Frame(self.toolbar)
        settings_frame.pack(side="right")

        checkbox_row = ttk.Frame(settings_frame)
        checkbox_row.pack(side="top")

        self.footer_timestamp_var = tk.BooleanVar(value=True)
        # Default on -- matches Slidemaster_preamble_base.tex's own default
        # (\gothamShowCompileTimestamptrue). Unticking sets
        # CompileJob.footer_timestamp=False for every job in the next batch
        # (see _compile_rows/_quick_compile below), which compiler.py's
        # wrapper turns into \def\gothamFooterTimestampOverride{0} -- drops
        # \gothamCompileTimestamp from every footer for that compile. Added
        # 2026-07-28 for the IA2 deck's front-to-back render/diff final
        # check, where a fresh compile timestamp on every page would
        # otherwise make every page look "changed" against the saved
        # baseline even with no real edit.
        ttk.Checkbutton(
            checkbox_row, text="Include footer timestamp", variable=self.footer_timestamp_var,
        ).pack(side="left")

        self.auto_open_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            checkbox_row, text="Auto-open generated PDFs", variable=self.auto_open_var,
        ).pack(side="left", padx=(16, 0))

        self.dark_mode_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            checkbox_row, text="Dark mode", variable=self.dark_mode_var,
            command=self._on_toggle_dark_mode,
        ).pack(side="left", padx=(16, 0))

        # A git-derived version string, not a hand-maintained one -- see
        # version.py's own docstring for why (a launched process never
        # re-reads its source, so this is the one place a user can tell
        # which commit a running window is actually executing).
        ttk.Label(
            settings_frame, text=version_mod.VERSION, style="Muted.TLabel"
        ).pack(side="top", anchor="e")

        self.log_frame = ttk.Frame(root)
        self.log_frame.pack(fill="both", expand=False, padx=8, pady=(0, 8))
        log_header = ttk.Frame(self.log_frame)
        log_header.pack(fill="x")
        ttk.Label(log_header, text="Log:").pack(side="left")
        # Status bar shares this line with "Log:" rather than its own row
        # -- reflects both the main compile-batch status (unchanged) and,
        # via _log()'s RENDER_*_RE matching below, a slide render started
        # from the deck or slide-source editor, which previously had no
        # status-bar feedback at all.
        self.status_var = tk.StringVar(value="")
        ttk.Label(
            log_header, textvariable=self.status_var, style="Warning.TLabel"
        ).pack(side="left", padx=(12, 0))
        self.log_text = scrolledtext.ScrolledText(self.log_frame, height=12, state="disabled")
        self.log_text.pack(fill="both", expand=True)
        self.theme.register_text(self.log_text)

        self.active_rows: list[DeckRow] = []
        self.archived_rows: list[DeckRow] = []
        self._toolbar_visible = True

        # The compile-batch toolbar (Empty pdf/, Remove temp files, Archive
        # unused content, Auto-open) only applies to the Active/Archived
        # decks tables -- hidden while a deck slide-list editor or
        # slide-source tab is showing, since those are unrelated actions
        # that just clutter the view while editing.
        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)

        self.reload_decks()
        self.root.after(100, self._drain_log_queue)
        self.root.after(SPINNER_INTERVAL_MS, self._tick_spinner)

    # -- table (re)construction ------------------------------------------------

    def reload_decks(self) -> None:
        for tab in (self.active_tab, self.archived_tab):
            for child in tab.winfo_children():
                child.destroy()
        # _build_table appends its own Stop/Compile buttons here -- clear the
        # stale references to widgets just destroyed above before rebuilding.
        self._stop_buttons = []
        self._tk_buttons = []

        decks = scan_decks()
        active_decks = [d for d in decks if not d.archived]
        archived_decks = [d for d in decks if d.archived]

        self.active_rows = self._build_table(self.active_tab, active_decks, archivable=True)
        self.archived_rows = self._build_table(self.archived_tab, archived_decks, archivable=False)

    def _build_table(self, parent: ttk.Frame, decks: list[Deck], archivable: bool) -> list[DeckRow]:
        # Horizontal only -- this table doesn't scroll vertically (see the
        # note label built below), but its own row of checkboxes/buttons
        # per deck (plus the Compile selected/Stop compilation/Refresh
        # decks row) can still get clipped with no way to reach the rest
        # once the window's narrower than their combined natural width.
        scrollable = ScrollableFrame(
            parent, self.theme, horizontal=True, vertical=False,
            canvas_pad={"padx": 4, "pady": 4},
        )
        container = scrollable.inner

        header = [
            "Deck", "Instructor", "During-course", "After-course",
            "After-course, per chapter",
        ]
        if archivable:
            header.append("")  # Archive
            header.append("")  # Quick compile
        for col, text in enumerate(header):
            ttk.Label(container, text=text, font=("", 9, "bold")).grid(
                row=0, column=col, padx=8, pady=(0, 6)
            )

        rows: list[DeckRow] = []
        for i, deck in enumerate(decks, start=1):
            on_archive = self._archive_deck if archivable else None
            rows.append(
                DeckRow(
                    container, deck, i, self.theme,
                    on_archive=on_archive, on_open=self.open_deck_editor,
                    on_quick_compile=self._quick_compile if archivable else None,
                )
            )

        note = (
            "Instructor/During-course/After-course each compile the whole deck "
            "as one PDF -- independent of \"After-course, per chapter\", which "
            "always compiles the after-course version split into one PDF per "
            "chapter (both can be checked together in the same run). "
            "Instructor-only decks have no \\deckversion override, so only "
            "\"Instructor\" is selectable there. \"After-course, per chapter\" "
            "is disabled for decks with no \\section{} chapters."
        )
        ttk.Label(container, text=note, style="Muted.TLabel", wraplength=760).grid(
            row=len(decks) + 1, column=0, columnspan=len(header), sticky="w", pady=(10, 4)
        )

        button_row = ttk.Frame(container)
        # On the archivable (Active decks) table, "Refresh decks" is gridded
        # into the Archive column itself below (one column left of the
        # trailing Quick compile column), rather than packed into this
        # frame -- so it lines up with the "Archive" buttons above it
        # exactly, via the same grid column, instead of merely eyeballing
        # matching padx values against a separately packed frame.
        button_row_span = len(header) - 2 if archivable else len(header)
        button_row.grid(
            row=len(decks) + 2, column=0, columnspan=button_row_span, sticky="ew", pady=(4, 0)
        )
        # Plain tk.Button here, not ttk.Button like everything else in this
        # file -- ttk's "vista" theme (the Windows default) ignores
        # background/foreground style overrides on TButton, drawing the
        # native visual style regardless, so a ttk widget can't actually be
        # recolored this way; tk.Button's own bg/fg options aren't
        # theme-drawn and do take effect. This is the primary action on the
        # row, so it's the one button worth making visually stand out.
        compile_button = tk.Button(
            button_row,
            text="Compile selected",
            command=lambda: self._compile_rows(rows),
            font=("", 9, "bold"),
            background="#0066cc",
            foreground="white",
            activebackground="#0052a3",
            activeforeground="white",
            relief="raised",
            padx=10,
        )
        compile_button.pack(side="left")
        self._tk_buttons.append(compile_button)
        stop_button = tk.Button(
            button_row,
            text="Stop compilation",
            command=self._stop_compilation,
            font=("", 9, "bold"),
            activeforeground="white",
            relief="raised",
            padx=10,
        )
        self._tk_buttons.append(stop_button)
        # Classic tk (unlike ttk) never changes a button's own bg/fg between
        # normal/disabled on its own -- disabledforeground alone reads as
        # barely-different white-on-red rather than a clearly greyed-out
        # button, so _style_stop_button swaps the whole palette explicitly.
        # Reflects whatever's already running -- e.g. "Refresh decks" clicked
        # mid-compile rebuilds this button too, and it should come back
        # enabled rather than stranding an in-progress run with no way to
        # stop it.
        self._style_stop_button(stop_button, enabled=self.compiling)
        stop_button.pack(side="left", padx=(8, 0))
        self._stop_buttons.append(stop_button)
        self._apply_tk_button_borders()
        if archivable:
            # Same column, same padx, as the per-row "Archive" button
            # (DeckRow.__init__ below) -- guarantees the two line up rather
            # than relying on independently-tuned padding to coincide.
            ttk.Button(
                container, text="Refresh decks", command=self.reload_decks
            ).grid(row=len(decks) + 2, column=len(header) - 2, padx=(12, 4), pady=(4, 0))
        else:
            ttk.Button(
                button_row, text="Refresh decks", command=self.reload_decks
            ).pack(side="right")

        return rows

    def _apply_tk_button_borders(self) -> None:
        """Classic tk.Button draws a focus-ring border in the platform's own
        default color (not theme-drawn), unlike everything else in this
        window -- left alone, it shows up as a pale halo around "Compile
        selected"/"Stop compilation" against a dark background. Matches it
        to the current theme's own window background instead."""
        bg = self.theme.colors["bg"]
        for button in self._tk_buttons:
            button.configure(highlightbackground=bg, highlightcolor=bg)

    @staticmethod
    def _style_stop_button(button: tk.Button, enabled: bool) -> None:
        if enabled:
            button.configure(
                state="normal",
                background="#cc3300",
                activebackground="#a32900",
                foreground="white",
            )
        else:
            button.configure(
                state="disabled",
                background="#d9d9d9",
                activebackground="#d9d9d9",
                foreground="#888888",
            )

    def _on_toggle_dark_mode(self) -> None:
        self.theme.dark = self.dark_mode_var.get()
        self.theme.apply()
        self._apply_tk_button_borders()

    def _on_tab_changed(self, event=None) -> None:
        # Tracked explicitly rather than queried via winfo_ismapped() --
        # that reflects whether the *window* is actually mapped on screen
        # (false for e.g. a withdrawn/minimized root, regardless of this
        # frame's own pack state), not just whether this frame is
        # currently pack()ed; an explicit flag is unambiguous either way.
        on_main_tab = self.notebook.select() in (str(self.active_tab), str(self.archived_tab))
        if on_main_tab and not self._toolbar_visible:
            self.toolbar.pack(fill="x", padx=8, pady=(0, 4), before=self.log_frame)
            self._toolbar_visible = True
        elif not on_main_tab and self._toolbar_visible:
            self.toolbar.pack_forget()
            self._toolbar_visible = False

    # -- slide search (top-right of the window) ------------------------------

    def _on_slide_search_changed(self) -> None:
        query = self.slide_search_var.get().strip().lower()
        if not query:
            self._hide_slide_search_popup()
            return
        # Earliest match position first (e.g. "capm" as a prefix outranks
        # "capm" buried deep in a long slug), alphabetical as a tiebreak
        # among equal positions -- rather than list_id_slugs()'s own plain
        # alphabetical order, which would bury an early-position match
        # under an alphabetically-earlier slide whose own match sits deep
        # in its slug.
        scored = sorted(
            ((s.lower().find(query), s) for s in list_id_slugs() if query in s.lower()),
            key=lambda pair: pair[0],
        )
        matches = [s for _, s in scored][:15]
        if not matches:
            self._hide_slide_search_popup()
            return
        self._slide_search_matches = matches
        self._slide_search_selected = 0
        self._show_slide_search_popup(matches)

    def _show_slide_search_popup(self, matches: list[str]) -> None:
        if self._slide_search_popup is None:
            popup = tk.Toplevel(self.root)
            popup.withdraw()
            # No title bar/border -- reads as a dropdown attached to the
            # entry above it, not a separate window of its own.
            popup.overrideredirect(True)
            popup.attributes("-topmost", True)
            listbox = tk.Listbox(popup, exportselection=False, width=40)
            listbox.pack(fill="both", expand=True)
            # ButtonRelease, not <<ListboxSelect>> -- the latter only fires
            # for a selection change, so clicking the row already selected
            # by keyboard navigation would otherwise do nothing.
            listbox.bind(
                "<ButtonRelease-1>", lambda e: self._open_slide_search_index(listbox.nearest(e.y))
            )
            self.theme.register_toplevel(popup)
            self.theme.register_listbox(listbox)
            self._slide_search_popup = popup
            self._slide_search_listbox = listbox
        listbox = self._slide_search_listbox
        listbox.delete(0, "end")
        for m in matches:
            listbox.insert("end", m)
        listbox.configure(height=min(len(matches), 10))
        self._update_slide_search_highlight()
        self._position_slide_search_popup()
        self._slide_search_popup.deiconify()

    def _position_slide_search_popup(self) -> None:
        # Right-edge-anchored under the entry (which itself sits flush
        # against the window's own right edge) -- the popup is usually
        # wider than the entry (id-slugs run longer than 28 characters), so
        # anchoring by the *left* edge instead would routinely push it past
        # the window's, or even the screen's, right edge.
        entry = self.slide_search_entry
        popup = self._slide_search_popup
        popup.update_idletasks()
        popup_width = popup.winfo_reqwidth()
        entry_right = entry.winfo_rootx() + entry.winfo_width()
        x = entry_right - popup_width
        y = entry.winfo_rooty() + entry.winfo_height()
        popup.geometry(f"+{x}+{y}")

    def _hide_slide_search_popup(self) -> None:
        if self._slide_search_popup is not None:
            self._slide_search_popup.withdraw()
        self._slide_search_matches = []
        self._slide_search_selected = 0

    def _update_slide_search_highlight(self) -> None:
        listbox = self._slide_search_listbox
        if listbox is None:
            return
        listbox.selection_clear(0, "end")
        if self._slide_search_matches:
            listbox.selection_set(self._slide_search_selected)
            listbox.see(self._slide_search_selected)

    def _on_slide_search_down(self, event=None) -> None:
        if not self._slide_search_matches:
            return
        self._slide_search_selected = min(
            self._slide_search_selected + 1, len(self._slide_search_matches) - 1
        )
        self._update_slide_search_highlight()
        return "break"

    def _on_slide_search_up(self, event=None) -> None:
        if not self._slide_search_matches:
            return
        self._slide_search_selected = max(self._slide_search_selected - 1, 0)
        self._update_slide_search_highlight()
        return "break"

    def _on_slide_search_enter(self, event=None) -> None:
        if not self._slide_search_matches:
            return
        self._open_slide_search_index(self._slide_search_selected)

    def _on_slide_search_escape(self, event=None) -> None:
        self._hide_slide_search_popup()

    def _on_slide_search_focus_out(self, event=None) -> None:
        # Delayed so a click landing on the popup listbox (which momentarily
        # shifts focus away from the entry) gets a chance to register as a
        # selection before this decides whether to hide the popup out from
        # under it.
        self.root.after(150, self._hide_slide_search_popup_if_unfocused)

    def _hide_slide_search_popup_if_unfocused(self) -> None:
        focused = self.root.focus_get()
        if focused is self.slide_search_entry or focused is self._slide_search_listbox:
            return
        self._hide_slide_search_popup()

    def _open_slide_search_index(self, index: int) -> None:
        if index < 0 or index >= len(self._slide_search_matches):
            return
        id_slug = self._slide_search_matches[index]
        return_to = self.notebook.nametowidget(self.notebook.select())
        self.open_slide_editor(SLIDES_DIR / f"{id_slug}-current.tex", return_to=return_to)
        self._hide_slide_search_popup()
        self.slide_search_var.set("")

    # -- deck slide-list / slide-source editor ------------------------------

    def open_deck_editor(self, deck: Deck) -> None:
        existing = self._deck_editor_tabs.get(deck.path)
        if existing is not None:
            existing.reload(deck)
            existing.select()
            return
        tab = DeckEditorTab(self, deck)
        self._deck_editor_tabs[deck.path] = tab
        tab.select()

    def open_slide_editor(
        self,
        path: Path,
        on_saved: Optional[Callable[[str], None]] = None,
        return_to: Optional[ttk.Frame] = None,
    ) -> None:
        existing = self._slide_source_tabs.get(path)
        if existing is not None:
            if return_to is not None:
                # Update, not just leave as whatever it was set to on the
                # first open -- closing should return to wherever the user
                # most recently navigated here from, not a stale earlier tab.
                existing.return_to = return_to
            existing.select()
            return
        tab = SlideSourceTab(self, path, on_saved=on_saved, return_to=return_to)
        self._slide_source_tabs[path] = tab
        tab.select()

    def open_deck_source_editor(self, deck: Deck, return_to: Optional[ttk.Frame] = None) -> None:
        """The deck slide-list editor's own "Source" button -- opens the
        deck's raw .tex file in the same editor used for a slide's own
        source (SlideSourceTab already builds a plain Save/Revert/Close
        editor with no Render controls for a non-slides/ path, see that
        module's docstring). A save is routed through the same
        after_deck_edit() pipeline every row action already uses, so a
        hand-edit gets header-sync, the open deck-editor tab refreshed, and
        an Undo-stack entry exactly like any other deck edit."""
        self.open_slide_editor(
            deck.path,
            on_saved=lambda previous_text: self.after_deck_edit(
                deck.path, f"Edited {deck.name}'s source directly", previous_text=previous_text
            ),
            return_to=return_to,
        )

    def open_add_slide_dialog(self, deck: Deck, insert_at: int, indent: str) -> None:
        AddSlideDialog(self, deck, insert_at, indent)

    def close_slide_editor(self, path: Path) -> None:
        self._slide_source_tabs.pop(path, None)

    def close_deck_editor(self, deck_path: Path) -> None:
        self._deck_editor_tabs.pop(deck_path, None)

    def resync_deck(self, deck_path: Path) -> Optional[Deck]:
        """Re-scans every deck (like Refresh decks) and returns this one's
        fresh Deck snapshot -- called after any edit made through the deck
        slide-list editor, so the main table's own DeckRow (which reads
        deck.chapters/deck.text at compile time) never goes stale."""
        self.reload_decks()
        for row in self.active_rows + self.archived_rows:
            if row.deck.path == deck_path:
                return row.deck
        return None

    def after_deck_edit(
        self, deck_path: Path, summary: str, previous_text: Optional[str] = None
    ) -> None:
        """Shared post-edit sequence for every deck slide-list editor
        action (remove/change-variant/insert, from either
        deck_editor_tab.py or add_slide_dialog.py): header-sync in the
        background (it rereads every slides/*-current.tex file, and this
        project has a documented history of cloud-sync file-op stalls --
        the single-deck edit itself already happened inline, same as
        _archive_deck() above), then resync + rebuild the open tab, then
        log a summary line.

        `previous_text`, when given, is the deck's whole-file text from
        just before this edit -- recorded onto the open tab's own undo
        stack so its Undo button can restore it. Left as None for the
        undo action itself, so undoing doesn't push its own redo entry
        (there's no redo feature -- see deck_editor_tab.py)."""
        threading.Thread(target=self._regenerate_headers_bg, daemon=True).start()
        fresh_deck = self.resync_deck(deck_path)
        tab = self._deck_editor_tabs.get(deck_path)
        if tab is not None:
            if previous_text is not None:
                tab.record_undo_snapshot(previous_text)
            if fresh_deck is not None:
                tab.reload(fresh_deck)
        self._log(summary)

    def _regenerate_headers_bg(self) -> None:
        changed, n_decks = deck_headers.regenerate_headers()
        self.log_queue.put(
            f"==== Header sync: {changed} slide file(s) updated across {n_decks} deck(s) ===="
        )

    def log(self, line: str) -> None:
        """Public entry point for the deck editor/slide source tab modules
        to append to the log pane -- always called from the main thread
        (a button/dialog action), unlike _run_jobs_thread's own
        log_queue.put() from a background thread."""
        self._log(line)

    # -- actions -----------------------------------------------------------

    def _archive_deck(self, deck: Deck) -> None:
        if not messagebox.askyesno(
            "Archive deck", f"Move {deck.name}.tex to decks/archive/?"
        ):
            return
        try:
            archive_mod.archive_deck(deck)
        except Exception as exc:  # noqa: BLE001 -- surface any failure to the user
            messagebox.showerror("Archive failed", str(exc))
            return
        self._log(f"Archived {deck.name}.tex -> decks/archive/{deck.name}.tex")
        self.reload_decks()

    def _compile_rows(self, rows: list[DeckRow]) -> None:
        if self.compiling:
            messagebox.showinfo("Busy", "A compile run is already in progress.")
            return
        jobs: list[CompileJob] = []
        job_status_map: dict[str, tuple[DeckRow, str]] = {}
        footer_timestamp = self.footer_timestamp_var.get()
        for row in rows:
            row.reset_status()
            for job in row.build_jobs():
                job.footer_timestamp = footer_timestamp
                job_status_map[job.jobname] = (row, _job_column_key(job))
                jobs.append(job)
        if not jobs:
            messagebox.showinfo(
                "Nothing selected", "Check at least one version per deck to compile."
            )
            return
        self._start_jobs(jobs, job_status_map)

    def _quick_compile(self, row: DeckRow) -> None:
        """The per-row "Quick compile" button: always the instructor
        version, whole deck, regardless of whatever this row's own
        version/chapter checkboxes currently say -- a fast "does this deck
        still compile" check independent of setting up a real batch run."""
        if self.compiling:
            messagebox.showinfo("Busy", "A compile run is already in progress.")
            return
        version = "instructor" if row.deck.supports_version else None
        job = CompileJob(row.deck, version, None, footer_timestamp=self.footer_timestamp_var.get())
        row.reset_status()
        self._start_jobs([job], {job.jobname: (row, _job_column_key(job))})

    def _start_jobs(
        self, jobs: list[CompileJob], job_status_map: dict[str, tuple[DeckRow, str]]
    ) -> None:
        self._job_status_map = job_status_map
        self._job_progress_texts = _build_progress_texts(jobs)
        self.compiling = True
        self.cancel_token = CancelToken()
        for button in self._stop_buttons:
            self._style_stop_button(button, enabled=True)
        threading.Thread(target=self._run_jobs_thread, args=(jobs,), daemon=True).start()

    def _stop_compilation(self) -> None:
        if self.cancel_token is None or not self.compiling:
            return
        if not messagebox.askyesno(
            "Stop compilation",
            "Stop the compile run? The job currently compiling will be "
            "killed immediately (including latexmk's own lualatex/biber "
            "children); anything still queued after it will be skipped.",
        ):
            return
        self._log("==== Stop requested -- killing current job and skipping the rest ====")
        self.cancel_token.request_stop()
        for button in self._stop_buttons:
            self._style_stop_button(button, enabled=False)

    def _tick_spinner(self) -> None:
        self._spinner_frame += 1
        for row in self.active_rows + self.archived_rows:
            row.tick_spinner(self._spinner_frame)
        self.root.after(SPINNER_INTERVAL_MS, self._tick_spinner)

    def _empty_pdf_folder(self) -> None:
        self._empty_folder(PDF_DIR, "pdf/")

    def _remove_temp_files(self) -> None:
        """Clears .build/'s own contents *and* any leftover
        `_slidemanager_*.tex` wrapper files under decks/ (including
        decks/archive/) -- compiler.py normally deletes its own wrapper file
        right after each job finishes (pass or fail), but one can be left
        behind if the app is closed or killed mid-compile."""
        if self.compiling:
            messagebox.showinfo(
                "Busy", "Can't remove temp files while a compile run is in progress."
            )
            return
        build_files = [p for p in BUILD_DIR.iterdir() if p.is_file()] if BUILD_DIR.exists() else []
        wrapper_files = list(DECKS_DIR.rglob("_slidemanager_*.tex"))
        all_files = build_files + wrapper_files
        if not all_files:
            messagebox.showinfo("Nothing to do", "No temp files to remove.")
            return
        if not messagebox.askyesno(
            "Remove temp files",
            f"Delete {len(build_files)} file(s) in .build/ and "
            f"{len(wrapper_files)} leftover wrapper file(s) in decks/?",
        ):
            return
        for p in all_files:
            p.unlink(missing_ok=True)
        self._log(
            f"Removed {len(all_files)} temp file(s) "
            f"({len(build_files)} in .build/, {len(wrapper_files)} wrapper file(s) in decks/)"
        )

    def _archive_unused_content(self) -> None:
        if self.compiling:
            messagebox.showinfo(
                "Busy",
                "Can't archive unused content while a compile run is in "
                "progress -- a running compile could still need a file this "
                "would move.",
            )
            return
        if not messagebox.askyesno(
            "Archive unused content",
            "Scan media/ and slides/ for files no longer referenced by any "
            "slide or deck (including archived decks) and move them into "
            "media/archive/ and slides/archive/? Files can be moved back by "
            "hand afterwards if needed.",
        ):
            return
        threading.Thread(
            target=self._run_archive_unused_content, daemon=True
        ).start()

    def _run_archive_unused_content(self) -> None:
        def log(line: str) -> None:
            self.log_queue.put(line)

        archive_unused_content(log)

    def _open_pdf(self, jobname: str) -> None:
        """Opens a just-finished job's PDF in the OS's default viewer, when
        "Auto-open generated PDFs" is checked -- called right as _log() sees
        that job's own "==== PASS: ... ====" line, so it fires once per job
        (whole-deck or per-chapter) rather than once per batch."""
        pdf_path = PDF_DIR / f"{jobname}.pdf"
        if not pdf_path.exists():
            return
        try:
            os.startfile(pdf_path)  # Windows-only project, same as elsewhere in this file
        except OSError as exc:
            self._log(f"*** couldn't auto-open {pdf_path.name}: {exc} ***")

    def _empty_folder(self, folder, label: str) -> None:
        if not folder.exists():
            messagebox.showinfo("Nothing to do", f"{label} doesn't exist yet.")
            return
        files = [p for p in folder.iterdir() if p.is_file()]
        if not files:
            messagebox.showinfo("Nothing to do", f"{label} is already empty.")
            return
        if not messagebox.askyesno(
            "Empty folder", f"Delete all {len(files)} file(s) in {label}?"
        ):
            return
        for p in files:
            p.unlink(missing_ok=True)
        self._log(f"Emptied {label} ({len(files)} file(s) deleted)")

    def _run_jobs_thread(self, jobs: list[CompileJob]) -> None:
        def log(line: str) -> None:
            self.log_queue.put(line)

        cancel = self.cancel_token
        results = run_jobs(jobs, log, cancel=cancel)
        passed = sum(1 for ok in results.values() if ok)
        failed = len(results) - passed
        log(f"==== Done: {passed} passed, {failed} failed ====")
        self.compiling = False
        self.cancel_token = None
        self.root.after(0, self._disable_stop_buttons)

    def _disable_stop_buttons(self) -> None:
        """Runs on the main thread (via root.after -- Tk widgets aren't
        thread-safe) once a batch finishes on its own, so a Stop button left
        enabled from that run doesn't linger for the next, unrelated one."""
        for button in self._stop_buttons:
            self._style_stop_button(button, enabled=False)

    # -- log pane (main-thread only) -----------------------------------------

    def _drain_log_queue(self) -> None:
        try:
            while True:
                self._log(self.log_queue.get_nowait())
        except queue.Empty:
            pass
        self.root.after(100, self._drain_log_queue)

    def _log(self, line: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", line + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

        # A slide render (deck or slide-source editor's own "Render"/
        # "Render to PDF" button) has no row/checkbox of its own to flash
        # a status dot on, so it drives the shared status bar directly
        # instead -- reusing _current_progress_base/RUN_NUMBER_RE below so
        # a render's own latexmk "Run number N..." lines live-update it
        # exactly like a real compile job's do.
        render_start = RENDER_START_RE.match(line)
        if render_start:
            self._current_progress_base = f"Rendering {render_start.group(1)}"
            self.status_var.set(f"{self._current_progress_base}: starting...")
            return
        render_pass = RENDER_PASS_RE.match(line)
        if render_pass:
            self.status_var.set(f"Done: rendered {render_pass.group(1)}")
            self._current_progress_base = ""
            return
        render_fail = RENDER_FAIL_RE.match(line)
        if render_fail:
            self.status_var.set(f"Render failed: {render_fail.group(1)}")
            self._current_progress_base = ""
            return

        # Piggyback on the same Compiling/MOVING/PASS/FAIL lines compiler.py
        # already logs, so a checkbox's status dot (and the status bar)
        # update live as soon as its own job reaches that point -- rather
        # than only once the whole batch (which may cover several
        # decks/versions/chapters) is done.
        for pattern, status in (
            (RUNNING_LOG_RE, "running"),
            (MOVING_LOG_RE, "moving"),
            (PASS_LOG_RE, "pass"),
            (FAIL_LOG_RE, "fail"),
        ):
            match = pattern.match(line)
            if match:
                jobname = match.group(1)
                entry = self._job_status_map.get(jobname)
                if entry is not None:
                    row, key = entry
                    row.set_status(key, status)
                if status == "pass" and self.auto_open_var.get():
                    self._open_pdf(jobname)
                if status in ("running", "moving"):
                    base = self._job_progress_texts.get(jobname, "")
                    if status == "running":
                        # Tracked so a later, job-anonymous "Run number..."
                        # line (see below) knows what it's a run *of*.
                        self._current_progress_base = base
                        if base:
                            self.status_var.set(f"{base}: starting...")
                    elif base:
                        self.status_var.set(
                            f"{base}: compiled, relocating PDF into pdf/..."
                        )
                break
        else:
            done_match = DONE_LOG_RE.match(line)
            if done_match:
                self.status_var.set(f"Done: {done_match.group(1)}")
                return
            # latexmk's own progress, not one of compiler.py's synthetic
            # ==== lines -- e.g. "Run number 3 of rule 'lualatex'" for a
            # deck needing several reruns to settle references/citations,
            # or "...'biber /path/jobname'" for the bibliography step.
            # Confirmed directly: without this, the status bar sat frozen
            # the whole compile even as the log showed several separate
            # lualatex/biber runs going by underneath it. No fixed "N/M"
            # here (per explicit user preference) -- latexmk decides how
            # many passes a compile actually needs as it goes, so there's
            # no honest total to put on the other side of the slash; just
            # the live count of whichever pass is running right now,
            # whether that's lualatex or biber.
            run_match = RUN_NUMBER_RE.match(line)
            if run_match and self._current_progress_base:
                run_number = run_match.group(1)
                self.status_var.set(
                    f"{self._current_progress_base}: Compile {run_number}..."
                )


def main() -> None:
    root = tk.Tk()
    SlideManagerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
