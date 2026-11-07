# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Design tokens taken from the Prototype v3 (2026-10-09), as plain data.

The prototype defines light colors only: its "dark mode" is a CSS
`invert(1) hue-rotate(180deg)` filter over the whole page, which Qt has no
equivalent for. The dark values below are therefore our own (2026-10-09):
backgrounds and text retain the original dark palette, and the
accents are the lighter "400" shades of the light ones.

No Qt import here, so both theme.py (which turns tokens into QSS) and the
kit widgets can read them without a cycle.
"""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType

# Font families bundled in assets/fonts/ and loaded by fonts.py.
FONT_SANS = "Roboto"
FONT_MONO = "Roboto Mono"
FONT_ICONS = "Material Icons"

# Corner radii in px. Use pill(height) for height-constrained round shapes.
RADIUS_XS = 3
RADIUS_SM = 4
RADIUS_MD = 8
RADIUS_LG = 12
RADIUS_PILL = 999


@dataclass(frozen=True)
class TypeScale:
    micro: int = 11
    small: int = 12
    body: int = 13
    control: int = 14
    heading: int = 15
    title: int = 18
    display: int = 20


TYPE = TypeScale()


@dataclass(frozen=True)
class SpaceScale:
    """Spacing steps in px; zero stays literal. Numeric names use s_2xs/s_2xl."""

    s_2xs: int = 2
    xs: int = 4
    sm: int = 6
    md: int = 8
    lg: int = 10
    xl: int = 12
    s_2xl: int = 16


SPACE = SpaceScale()


def pill(height: int) -> float:
    """Half the widget height; larger radii can produce square corners in Qt."""
    return height / 2


@dataclass(frozen=True)
class Shadow:
    """One Qt drop shadow (QGraphicsDropShadowEffect takes a single layer).

    The prototype stacks several CSS layers per elevation; `blur` and `alpha`
    here approximate the sum.
    """

    dy: int
    blur: int
    alpha: int  # 0-255


SHADOWS: dict[str, Shadow] = {
    # Cards, menus and chips (Material elevation 2).
    "raised": Shadow(2, 8, 50),
    # Toast.
    "toast": Shadow(12, 32, 51),
    # Modal sheets and dialogs (Material elevation 24).
    "modal": Shadow(16, 44, 70),
}


@dataclass(frozen=True)
class Tokens:
    # Neutrals. `bg` is the page behind the cards, `surface` the cards.
    bg: str
    surface: str
    text: str
    text_2: str  # secondary text (prototype #4b5563)
    text_3: str  # tertiary (#6b7280)
    text_4: str  # placeholders, disabled (#9ca3af)
    line: str  # hairlines (#e5e7eb)
    hover: str  # translucent hover wash, also the segmented-control track
    # Strong fill for primary buttons, the split button and toasts.
    inverse: str
    on_inverse: str
    # "View as" colors: solid for the active segment, tint for backgrounds.
    view_instructor: str
    view_during: str
    view_after: str
    view_instructor_tint: str
    view_during_tint: str
    view_after_tint: str
    # Reveal-step colors (STEPC), cycled by step index.
    steps: tuple[str, ...]
    # Status colors: strong, background tint, text on the tint.
    error: str
    error_bg: str
    error_fg: str
    error_solid: str   # fill behind on_solid text (error toast, badges): the same in both themes
    warning_solid: str  # fixed fill behind on_solid text
    warning: str
    warning_bg: str
    warning_fg: str
    ok: str
    ok_bg: str
    ok_fg: str
    info: str
    info_bg: str
    info_fg: str
    # The Cloud route (workspace v6): the AI switch's wrapper and its popups. `cloud_solid` fills the selected Cloud
    # segment and the primary Cloud buttons (white text); `cloud_text` is the route text in dark amber.
    cloud_bg: str
    cloud_border: str
    cloud_fg: str
    cloud_solid: str
    cloud_text: str
    # The Local route: its icon and route text. `focus` is the keyboard focus ring.
    local_icon: str
    local_fg: str
    focus: str
    # Text on a solid color fill (error badges, the active "View as" segment, the toast): white in both themes.
    on_solid: str
    # A slide's page and the picture on it: white in both themes, with dark text and an outline that
    # shows where the picture ends.
    paper: str
    paper_text: str
    paper_outline: str
    # The Log drawer is dark in both themes (prototype: #1d1d1d, #e8e6e1).
    log_bg: str
    log_text: str

    # Source editor syntax, selection highlight and document links.
    syntax_comment: str
    syntax_command: str
    syntax_brace: str
    syntax_env: str
    syntax_math: str
    syntax_todo: str
    selection: str
    link: str
    scrim: str

    def view_color(self, view: str) -> str:
        """`view` is "instructor", "during" or "after"."""
        return getattr(self, f"view_{view}")

    def view_tint(self, view: str) -> str:
        return getattr(self, f"view_{view}_tint")


VIEWS = ("instructor", "during", "after")

# Values that are identical across themes, including the overlay's base colour.
_WARNING_SOLID = "#b45309"
FIXED = MappingProxyType({
    "on_solid": "#ffffff",
    "error_solid": "#b91c1c",
    "warning_solid": _WARNING_SOLID,
    "cloud_solid": _WARNING_SOLID,
    "paper": "#ffffff",
    "paper_text": "#4b5563",
    "paper_outline": "#ff00ff",
    "log_text": "#e8e6e1",
    "scrim": "#000000",
})

# Shared roles within each theme; semantic fields remain available to callers.
_L_TEXT, _D_TEXT = "#1d1d1d", "#e0e0e0"
_L_INFO, _D_INFO = "#2563eb", "#60a5fa"
_L_OK, _D_OK = "#15803d", "#4ade80"
_L_OK_FG, _D_OK_FG = "#065f46", "#a7f3d0"
_L_WARNING_BG, _D_WARNING_BG = "#fef3c7", "#422006"
_L_WARNING_FG, _D_WARNING_FG = "#78350f", "#fde68a"

# Categorical colours shared by status, reveal steps and terminal base hues.
ACCENTS = MappingProxyType({
    "light": MappingProxyType({
        "neutral": _L_TEXT, "slate": "#475569", "blue": _L_INFO,
        "teal": "#0f766e", "green": _L_OK, "violet": "#9333ea", "pink": "#be185d",
    }),
    "dark": MappingProxyType({
        "neutral": _D_TEXT, "slate": "#94a3b8", "blue": _D_INFO,
        "teal": "#2dd4bf", "green": _D_OK, "violet": "#c084fc", "pink": "#f472b6",
    }),
})


_STEP_ACCENTS = ("neutral", "blue", "teal", "green", "violet", "pink")

LIGHT = Tokens(
    bg="#f3f4f6", surface="#ffffff", text=_L_TEXT, text_2="#4b5563",
    text_3="#6b7280", text_4="#9ca3af", line="#e5e7eb",
    hover="rgba(0,0,0,0.05)", inverse=_L_TEXT, on_inverse="#ffffff",
    # oklch(0.55 0.14 255/155/45) and oklch(0.96 0.025-0.03 ...), converted.
    view_instructor="#3072c1", view_during="#00884b", view_after="#b2511e",
    view_instructor_tint="#e7f3ff", view_during_tint="#e3f8e9", view_after_tint="#ffece2",
    steps=tuple(ACCENTS["light"][name] for name in _STEP_ACCENTS),
    error=FIXED["error_solid"], error_bg="#fef2f2", error_fg="#7f1d1d",
    warning=FIXED["warning_solid"], warning_bg=_L_WARNING_BG, warning_fg=_L_WARNING_FG,
    # Success keeps its existing tinted background/text pair.
    ok=_L_OK, ok_bg="#d1fae5", ok_fg=_L_OK_FG,
    info=_L_INFO, info_bg="#dbeafe", info_fg="#1e40af",
    cloud_bg=_L_WARNING_BG, cloud_border="#f59e0b", cloud_fg=_L_WARNING_FG, cloud_text="#92400e",
    local_icon=_L_OK, local_fg=_L_OK_FG, focus=_L_INFO,
    log_bg="#1d1d1d",
    syntax_comment="#008000",
    syntax_command="#0033cc",
    syntax_brace="#996600",
    syntax_env="#a03db0",
    syntax_math="#b8860b",
    syntax_todo="#cc0000",
    selection="#0078d7",
    link="#0066cc",
    **FIXED,
)

DARK = Tokens(
    bg="#1e1e1e", surface="#2d2d2d", text=_D_TEXT, text_2="#b0b0b0",
    text_3="#9a9a9a", text_4="#6f6f6f", line="#3f3f3f",
    hover="rgba(255,255,255,0.08)", inverse=_D_TEXT, on_inverse="#1e1e1e",
    view_instructor="#6aa7f4", view_during="#57bc80", view_after="#e7885d",
    view_instructor_tint="#1c2f46", view_during_tint="#173523", view_after_tint="#422518",
    steps=tuple(ACCENTS["dark"][name] for name in _STEP_ACCENTS),
    error="#f87171", error_bg="#451a1a", error_fg="#fecaca",
    warning="#fbbf24", warning_bg=_D_WARNING_BG, warning_fg=_D_WARNING_FG,
    ok=_D_OK, ok_bg="#064e3b", ok_fg=_D_OK_FG,
    info=_D_INFO, info_bg="#1e3a5f", info_fg="#bfdbfe",
    cloud_bg=_D_WARNING_BG, cloud_border="#fbbf24", cloud_fg=_D_WARNING_FG, cloud_text="#fcd34d",
    local_icon=_D_OK, local_fg=_D_OK_FG, focus=_D_INFO,
    log_bg="#121212",
    syntax_comment="#6a9955",
    syntax_command="#569cd6",
    syntax_brace="#d7ba7d",
    syntax_env="#c586c0",
    syntax_math="#dcb67a",
    syntax_todo="#f04848",
    selection="#264f78",
    link="#4da6ff",
    **FIXED,
)


@dataclass(frozen=True)
class StageTokens:
    """Fixed presentation chrome, independent of the workspace theme."""

    stage_bg: str = FIXED["scrim"]
    stage_panel: str = "#1b1b1b"
    stage_text: str = "#eeeeee"
    stage_muted: str = "#9e9e9e"
    stage_active: str = "#1976d2"
    stage_warn: str = FIXED["warning_solid"]
    stage_over: str = FIXED["error_solid"]
    stage_scrim: str = FIXED["scrim"]
    stage_on_solid: str = FIXED["on_solid"]
    stage_paper: str = FIXED["paper"]
    stage_canvas: str = "#101010"
    stage_name: str = "#e0e0e0"
    strip: int = 16
    toast: int = 15


STAGE = StageTokens()

# ANSI greys and bright variants deliberately retain their established values.
LIGHT_ANSI = ("#1d1d1d", LIGHT.error, ACCENTS["light"]["green"], LIGHT.warning,
              ACCENTS["light"]["blue"], ACCENTS["light"]["violet"], ACCENTS["light"]["teal"], "#6b7280",
              "#4b5563", "#dc2626", "#059669", "#d97706", "#2563eb", "#9333ea", "#0891b2", "#858b96")
DARK_ANSI = ("#808080", DARK.error, ACCENTS["dark"]["green"], DARK.warning,
             ACCENTS["dark"]["blue"], ACCENTS["dark"]["violet"], ACCENTS["dark"]["teal"], "#d4d4d4",
             "#9a9a9a", "#fca5a5", "#6ee7b7", "#fde68a", "#93c5fd", "#d8b4fe", "#67e8f9", "#ffffff")


def tokens_for(dark: bool) -> Tokens:
    return DARK if dark else LIGHT


def with_alpha(color: str, alpha: float) -> str:
    """"#rrggbb" -> "rgba(r,g,b,alpha)" for QSS, which has no color-mix."""
    r, g, b = (int(color[i:i + 2], 16) for i in (1, 3, 5))
    return f"rgba({r},{g},{b},{alpha})"
