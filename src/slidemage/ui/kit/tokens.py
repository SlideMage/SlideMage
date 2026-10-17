"""Design tokens taken from the Prototype v3 (2026-10-09), as plain data.

The prototype defines light colors only: its "dark mode" is a CSS
`invert(1) hue-rotate(180deg)` filter over the whole page, which Qt has no
equivalent for. The dark values below are therefore our own (2026-10-09):
backgrounds and text reuse the existing dark palette in palette.py, the
accents are the lighter "400" shades of the light ones.

No Qt import here, so both theme.py (which turns tokens into QSS) and the
kit widgets can read them without a cycle.
"""
from __future__ import annotations

from dataclasses import dataclass

# Font families bundled in assets/fonts/ and loaded by fonts.py.
FONT_SANS = "Roboto"
FONT_MONO = "Roboto Mono"
FONT_ICONS = "Material Icons"

# Corner radii in px (prototype: 4 for controls, 8 for cards and sheets,
# 999 for chips and badges).
RADIUS_SM = 4
RADIUS_MD = 8
RADIUS_PILL = 999


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

    def view_color(self, view: str) -> str:
        """`view` is "instructor", "during" or "after"."""
        return getattr(self, f"view_{view}")

    def view_tint(self, view: str) -> str:
        return getattr(self, f"view_{view}_tint")


VIEWS = ("instructor", "during", "after")

LIGHT = Tokens(
    bg="#f3f4f6", surface="#ffffff", text="#1d1d1d", text_2="#4b5563",
    text_3="#6b7280", text_4="#9ca3af", line="#e5e7eb",
    hover="rgba(0,0,0,0.05)", inverse="#1d1d1d", on_inverse="#ffffff",
    # oklch(0.55 0.14 255/155/45) and oklch(0.96 0.025-0.03 ...), converted.
    view_instructor="#3072c1", view_during="#00884b", view_after="#b2511e",
    view_instructor_tint="#e7f3ff", view_during_tint="#e3f8e9", view_after_tint="#ffece2",
    steps=("#1d1d1d", "#2563eb", "#d97706", "#059669", "#9333ea", "#db2777"),
    error="#b91c1c", error_bg="#fef2f2", error_fg="#7f1d1d", error_solid="#b91c1c",
    warning="#b45309", warning_bg="#fef3c7", warning_fg="#78350f",
    # The prototype has the green #059669 but no green tint; the tint and
    # text colors are the Tailwind 100/800 shades.
    ok="#059669", ok_bg="#d1fae5", ok_fg="#065f46",
    info="#2563eb", info_bg="#dbeafe", info_fg="#1e40af",
    cloud_bg="#fef3c7", cloud_border="#f59e0b", cloud_fg="#78350f", cloud_solid="#b45309", cloud_text="#92400e",
    local_icon="#059669", local_fg="#065f46", focus="#2563eb",
    on_solid="#ffffff", paper="#ffffff", paper_text="#4b5563", paper_outline="#ff00ff",
    log_bg="#1d1d1d", log_text="#e8e6e1",
)

DARK = Tokens(
    bg="#1e1e1e", surface="#2d2d2d", text="#e0e0e0", text_2="#b0b0b0",
    text_3="#9a9a9a", text_4="#6f6f6f", line="#3f3f3f",
    hover="rgba(255,255,255,0.08)", inverse="#e0e0e0", on_inverse="#1e1e1e",
    view_instructor="#6aa7f4", view_during="#57bc80", view_after="#e7885d",
    view_instructor_tint="#1c2f46", view_during_tint="#173523", view_after_tint="#422518",
    steps=("#e0e0e0", "#60a5fa", "#fbbf24", "#34d399", "#c084fc", "#f472b6"),
    error="#f87171", error_bg="#451a1a", error_fg="#fecaca", error_solid="#b91c1c",
    warning="#fbbf24", warning_bg="#422006", warning_fg="#fde68a",
    ok="#34d399", ok_bg="#064e3b", ok_fg="#a7f3d0",
    info="#60a5fa", info_bg="#1e3a5f", info_fg="#bfdbfe",
    cloud_bg="#422006", cloud_border="#fbbf24", cloud_fg="#fde68a", cloud_solid="#b45309", cloud_text="#fcd34d",
    local_icon="#34d399", local_fg="#a7f3d0", focus="#60a5fa",
    on_solid="#ffffff", paper="#ffffff", paper_text="#4b5563", paper_outline="#ff00ff",
    log_bg="#121212", log_text="#e8e6e1",
)


def tokens_for(dark: bool) -> Tokens:
    return DARK if dark else LIGHT


def with_alpha(color: str, alpha: float) -> str:
    """"#rrggbb" -> "rgba(r,g,b,alpha)" for QSS, which has no color-mix."""
    r, g, b = (int(color[i:i + 2], 16) for i in (1, 3, 5))
    return f"rgba({r},{g},{b},{alpha})"
