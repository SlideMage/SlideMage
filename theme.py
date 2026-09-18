"""Central color palette + ttk style wiring for SlideManager's light/dark
themes.

Windows' default ttk theme ("vista") ignores style-level color overrides on
most widgets -- it draws the native OS look regardless of what you configure
(see gui.py's own long-standing note on why "Compile selected" is a plain
tk.Button rather than a ttk.Button, for exactly this reason). So dark mode
switches the whole app to ttk's "clam" theme instead -- the one theme bundled
with Tk on Windows that actually honors palette overrides.

Live toggling (the "Dark mode" checkbox in gui.py's toolbar) works two ways:

- Every reusable ttk look is a *named style* (e.g. "Link.TLabel") configured
  here, rather than a per-widget `foreground=`/`background=` option passed at
  construction time. A ttk widget re-reads its named style live, so
  reconfiguring that name once (in _configure_styles below) recolors every
  existing widget using it, with no need to touch the widgets themselves.
- Plain tk widgets (Text/Canvas/Listbox/Button -- no ttk equivalent, or one
  that can't be recolored the way clam's other widgets can) have no such
  style layer, so they register themselves with a ThemeManager instance
  (register_text/register_canvas/register_listbox/register_toplevel) and are
  explicitly reconfigured, by weak reference, on every theme change.
"""
from __future__ import annotations

import tkinter as tk
import weakref
from tkinter import ttk
from typing import Callable

from .palette import PALETTES, Mode  # noqa: F401 -- Mode re-exported for callers' type hints

__all__ = ["PALETTES", "Mode", "ThemeManager"]


class ThemeManager:
    """Owns the current light/dark palette, the shared ttk.Style, and the
    registry of plain tk widgets (Text/Canvas/Listbox/Toplevel) that have no
    style layer of their own and so need to be recolored by hand on every
    toggle."""

    def __init__(self, root: tk.Tk):
        self.root = root
        self.dark = True
        self.style = ttk.Style(root)
        self.style.theme_use("clam")
        self._texts: list[weakref.ref] = []
        self._syntax_texts: list[weakref.ref] = []
        self._canvases: list[weakref.ref] = []
        self._listboxes: list[weakref.ref] = []
        self._toplevels: list[weakref.ref] = []

    @property
    def colors(self) -> dict[str, str]:
        return PALETTES["dark" if self.dark else "light"]

    def status_color(self, status: str) -> str:
        return self.colors[f"status_{status}"]

    # -- registration for plain tk widgets (no ttk style layer) ---------------

    def register_text(self, widget: tk.Text) -> None:
        self._texts.append(weakref.ref(widget))
        self._style_text(widget)

    def register_syntax_text(self, widget: tk.Text) -> None:
        """Like register_text, but also recolors slide_source_tab.py's
        LaTeX syntax-highlighting tags (latex_comment/latex_command/
        latex_brace) on every toggle -- those live on the Text widget's tag
        table, not as widget-level options, so they need their own
        re-application separate from _style_text's bg/fg/selection colors."""
        self._syntax_texts.append(weakref.ref(widget))
        self._style_text(widget)
        self._style_syntax_tags(widget)

    def register_canvas(self, widget: tk.Canvas) -> None:
        self._canvases.append(weakref.ref(widget))
        self._style_canvas(widget)

    def register_listbox(self, widget: tk.Listbox) -> None:
        self._listboxes.append(weakref.ref(widget))
        self._style_listbox(widget)

    def register_toplevel(self, widget: tk.Toplevel) -> None:
        self._toplevels.append(weakref.ref(widget))
        self._style_toplevel(widget)

    # -- applying ---------------------------------------------------------------

    def toggle(self) -> None:
        self.dark = not self.dark
        self.apply()

    def apply(self) -> None:
        c = self.colors
        self.root.configure(background=c["bg"])
        self._configure_styles(c)

        registries: list[tuple[list[weakref.ref], Callable[[object], None]]] = [
            (self._texts, self._style_text),
            (self._syntax_texts, self._style_syntax_text_and_tags),
            (self._canvases, self._style_canvas),
            (self._listboxes, self._style_listbox),
            (self._toplevels, self._style_toplevel),
        ]
        for registry, styler in registries:
            alive = []
            for ref in registry:
                widget = ref()
                # winfo_exists() also catches a destroyed-but-not-yet-
                # garbage-collected widget (e.g. a closed slide-source tab
                # whose Text still has a live Python reference somewhere) --
                # a dead weakref alone wouldn't be enough to prune those.
                if widget is not None and widget.winfo_exists():
                    styler(widget)
                    alive.append(ref)
            registry[:] = alive

    def _style_syntax_text_and_tags(self, widget: tk.Text) -> None:
        self._style_text(widget)
        self._style_syntax_tags(widget)

    def _configure_styles(self, c: dict[str, str]) -> None:
        s = self.style
        s.configure(".", background=c["bg"], foreground=c["fg"], fieldbackground=c["entry_bg"])
        s.configure("TFrame", background=c["bg"])
        s.configure("TLabel", background=c["bg"], foreground=c["fg"])
        s.configure(
            "TCheckbutton", background=c["bg"], foreground=c["fg"],
            indicatorbackground=c["entry_bg"], indicatorforeground=c["fg"],
        )
        s.map(
            "TCheckbutton",
            background=[("active", c["bg"])],
            foreground=[("disabled", c["disabled_fg"])],
            indicatorbackground=[
                ("disabled", c["panel_bg"]), ("selected", c["select_bg"])
            ],
        )
        s.configure(
            "TRadiobutton", background=c["bg"], foreground=c["fg"],
            indicatorbackground=c["entry_bg"], indicatorforeground=c["fg"],
        )
        s.map(
            "TRadiobutton",
            background=[("active", c["bg"])],
            indicatorbackground=[
                ("disabled", c["panel_bg"]), ("selected", c["select_bg"])
            ],
        )
        s.configure(
            "TButton", background=c["panel_bg"], foreground=c["fg"],
            bordercolor=c["border"], lightcolor=c["panel_bg"], darkcolor=c["panel_bg"],
        )
        s.map(
            "TButton",
            background=[("active", c["select_bg"]), ("disabled", c["panel_bg"])],
            foreground=[("disabled", c["disabled_fg"])],
        )
        s.configure(
            "TEntry", fieldbackground=c["entry_bg"], foreground=c["entry_fg"],
            insertcolor=c["fg"], bordercolor=c["border"],
        )
        s.configure(
            "TCombobox", fieldbackground=c["entry_bg"], foreground=c["entry_fg"],
            background=c["panel_bg"], arrowcolor=c["fg"], bordercolor=c["border"],
        )
        s.map(
            "TCombobox",
            fieldbackground=[("readonly", c["entry_bg"])],
            foreground=[("readonly", c["entry_fg"])],
        )
        # A Combobox's own dropdown list is a plain Tk Listbox Tk builds
        # internally, not reachable through the Combobox's own widget/style
        # options -- only through this option-database route.
        self.root.option_add("*TCombobox*Listbox.background", c["entry_bg"])
        self.root.option_add("*TCombobox*Listbox.foreground", c["entry_fg"])
        self.root.option_add("*TCombobox*Listbox.selectBackground", c["select_bg"])
        self.root.option_add("*TCombobox*Listbox.selectForeground", c["select_fg"])
        s.configure("TNotebook", background=c["bg"], bordercolor=c["border"])
        s.configure(
            "TNotebook.Tab", background=c["panel_bg"], foreground=c["fg"], padding=(8, 4)
        )
        s.map(
            "TNotebook.Tab",
            background=[("selected", c["bg"])],
            foreground=[("selected", c["fg"])],
        )
        s.configure(
            "TScrollbar", background=c["panel_bg"], troughcolor=c["trough"],
            bordercolor=c["border"], arrowcolor=c["fg"],
        )
        s.configure("TSeparator", background=c["border"])

        # Named looks used in place of a per-widget hardcoded foreground=
        # elsewhere in this package, so toggling the theme recolors every
        # instance automatically (see module docstring).
        s.configure("Link.TLabel", background=c["bg"], foreground=c["link_fg"])
        s.configure("Muted.TLabel", background=c["bg"], foreground=c["muted_fg"])
        s.configure("Warning.TLabel", background=c["bg"], foreground=c["warning_fg"])

    def _style_text(self, widget: tk.Text) -> None:
        c = self.colors
        widget.configure(
            background=c["entry_bg"], foreground=c["entry_fg"],
            insertbackground=c["fg"], selectbackground=c["select_bg"],
            selectforeground=c["select_fg"], highlightbackground=c["border"],
            highlightcolor=c["border"],
        )
        vbar = getattr(widget, "vbar", None)  # scrolledtext.ScrolledText's own classic Scrollbar
        if vbar is not None:
            vbar.configure(background=c["panel_bg"], troughcolor=c["trough"])

    def _style_syntax_tags(self, widget: tk.Text) -> None:
        c = self.colors
        widget.tag_configure("latex_comment", foreground=c["syntax_comment"])
        widget.tag_configure("latex_command", foreground=c["syntax_command"])
        widget.tag_configure("latex_brace", foreground=c["syntax_brace"])

    def _style_canvas(self, widget: tk.Canvas) -> None:
        widget.configure(background=self.colors["bg"], highlightthickness=0)

    def _style_listbox(self, widget: tk.Listbox) -> None:
        c = self.colors
        widget.configure(
            background=c["entry_bg"], foreground=c["entry_fg"],
            selectbackground=c["select_bg"], selectforeground=c["select_fg"],
            highlightbackground=c["border"], highlightcolor=c["border"],
        )

    def _style_toplevel(self, widget: tk.Toplevel) -> None:
        widget.configure(background=self.colors["bg"])
