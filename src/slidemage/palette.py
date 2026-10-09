"""Light/dark color data shared by both GUI toolkits during the PySide6
migration (see PYSIDE6_MIGRATION.md) -- deliberately has no Tkinter *or* Qt
import of its own, just plain data, so theme.py (Tk) and ui/kit/theme.py (Qt)
can both read the exact same palette without either one depending on the
other's toolkit. Extracted out of theme.py verbatim (same values, same
keys) rather than duplicated, so the two GUIs can't visually drift apart
while they coexist.
"""
from __future__ import annotations

from typing import Literal

Mode = Literal["light", "dark"]

PALETTES: dict[Mode, dict[str, str]] = {
    "light": {
        "bg": "#f0f0f0",
        "panel_bg": "#e4e4e4",
        "fg": "#000000",
        "entry_bg": "#ffffff",
        "entry_fg": "#000000",
        "select_bg": "#0078d7",
        "select_fg": "#ffffff",
        "border": "#a0a0a0",
        "disabled_fg": "#888888",
        "muted_fg": "gray40",
        "link_fg": "#0066cc",
        "warning_fg": "#cc3300",
        "trough": "#d9d9d9",
        "status_running": "#0066cc",
        "status_moving": "#cc8400",
        "status_pass": "#1a8a1a",
        "status_fail": "#cc0000",
        "syntax_comment": "#008000",
        "syntax_command": "#0033cc",
        "syntax_brace": "#996600",
        "syntax_env": "#a03db0",
        "syntax_math": "#b8860b",
        "syntax_todo": "#cc0000",
        "format_toolbar_button_bg": "#dbe4f5",
    },
    "dark": {
        "bg": "#1e1e1e",
        "panel_bg": "#2d2d2d",
        "fg": "#e0e0e0",
        "entry_bg": "#2d2d2d",
        "entry_fg": "#e0e0e0",
        "select_bg": "#264f78",
        "select_fg": "#ffffff",
        "border": "#3f3f3f",
        "disabled_fg": "#6f6f6f",
        "muted_fg": "#9a9a9a",
        "link_fg": "#4da6ff",
        "warning_fg": "#ff6b4a",
        "trough": "#2d2d2d",
        "status_running": "#4da6ff",
        "status_moving": "#e0a030",
        "status_pass": "#4caf50",
        "status_fail": "#f04848",
        "syntax_comment": "#6a9955",
        "syntax_command": "#569cd6",
        "syntax_brace": "#d7ba7d",
        "syntax_env": "#c586c0",
        "syntax_math": "#dcb67a",
        "syntax_todo": "#f04848",
        "format_toolbar_button_bg": "#39394a",
    },
}
