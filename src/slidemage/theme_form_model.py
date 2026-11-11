# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
r"""What the theme form shows and does, without Qt (docs/plans/theme-editor.md, stage C1b): the theme's colour modes as
columns, the palette (with the theme's own colours), the colour roles, code colours, logo and footnote markers, the
colour each cell comes to in each mode, and the contrast checks of the catalog. Every edit goes through
theme_file.ThemeFile, so it changes one line (or adds one) and nothing else.

A cell's value has two parts: what the theme WRITES for it (a line of its own, or None: it follows) and what it COMES
TO in that mode (the colour a slide gets). The resolution follows latex/SlideMage_setup.tex (\SM@applymode): in a mode
that is not the base, a role takes the mode's \SMSetRole line, else the mode's derive preset (dark), else its base
value; a palette colour takes the mode's \SMSetColor line, else the preset's change (grey, colorblind), else its base
value. theme_colors does the palette part; the roles are resolved here, hook macros (\SMTitleBoxColor ...) included."""
from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from . import theme_colors, theme_fields
from .theme_file import ThemeFile

# Colours the beamer theme defines, which hook defaults name (beamerthemeSlideMage.sty); "" is a standout frame's text
# when no template names one: the theme's pale yellow.
FRAMEWORK_COLOURS = {"SMLightOrange": "#eb811b", "SMDeepYellowOrange": "#ffcc00", "": "#fffff0"}
DERIVES = ("dark", "grey", "colorblind", "")
MODE_ID_RE = re.compile(r"[a-z][a-z0-9_]{0,23}")
OWN_COLOUR_RE = re.compile(r"c_[a-z][a-z0-9_]{0,40}")

# The roles, grouped as the form shows them (code_* go with the code colours).
ROLE_SECTIONS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Slide colours", ("text", "text_muted", "canvas", "card", "line", "text_on_accent", "link")),
    ("Title bar and footer", ("title_fill", "title_text", "footer_fill", "footer_text", "standout_fill",
                              "standout_text")),
    ("Blocks", ("block_title_fill", "block_title_text", "alerted_block_title_fill", "alerted_block_title_text",
                "example_block_title_fill", "example_block_title_text", "reference_block_title_fill",
                "reference_block_title_text", "info_block_title_fill", "info_block_title_text", "block_body_fill",
                "block_body_text")),
    ("Lists, links and marks", ("bullet", "alert", "link_underline", "marker", "citation", "table_rule",
                                "image_border", "quote_attribution", "inline_code", "process_line", "button_text",
                                "progress", "strip_fill", "strip_text")),
)
CODE_COLOURS = (("SMCodeKeywordColor", "code_keyword"), ("SMCodeCommentColor", "code_comment"),
                ("SMCodeBackgroundColor", "code_panel"), ("SMCodeTextColor", "code_text"))

# The contrast pairs the catalog asks for (SlideMage_setup.tex, "Palette"), and the ones a form should check too:
# (what is checked, foreground, background, minimum). "role:<id>" is a role, anything else a colour expression or a
# hook macro ("\SMHighlightTitleTextColor").
CHECKS: tuple[tuple[str, str, str, float], ...] = (
    ("Body text on the slide", "role:text", "role:canvas", 4.5),
    ("Links on the slide", "role:link", "role:canvas", 4.5),
    ("Link underline on the slide", "role:link_underline", "role:canvas", 3.0),
    ("Title text on the title bar", "role:title_text", "role:title_fill", 4.5),
    ("Footer text on the footer", "role:footer_text", "role:footer_fill", 4.5),
    ("Standout frame text", "role:standout_text", "role:standout_fill", 4.5),
    ("Highlight frame title", "\\SMHighlightTitleTextColor", "c_primary_gray", 4.5),
    ("Block title text", "role:block_title_text", "role:block_title_fill", 4.5),
    ("Alert block title text", "role:alerted_block_title_text", "role:alerted_block_title_fill", 4.5),
    ("Example block title text", "role:example_block_title_text", "role:example_block_title_fill", 4.5),
    ("Reference block title text", "role:reference_block_title_text", "role:reference_block_title_fill", 4.5),
    ("Info block title text", "role:info_block_title_text", "role:info_block_title_fill", 4.5),
    ("Block body text", "role:block_body_text", "role:block_body_fill", 4.5),
    ("Code commands on the panel", "role:code_keyword", "role:code_panel", 4.5),
    ("Code comments on the panel", "role:code_comment", "role:code_panel", 4.5),
    ("Code text on the panel", "role:code_text", "role:code_panel", 4.5),
)
FOOTNOTE_STYLES = (("symbols", "Currency signs (default)"), ("boxed", "Number in a box"), ("dice", "Dice"),
                   ("numbers", "Plain numbers"))
_DERIVED_RE = re.compile(r"SM@derived@(\w+)(?:\\endcsname)?\{([^{}]*)\}")


@dataclass(frozen=True)
class Mode:
    id: str          # "" for a theme that declares no modes (one column: its colours)
    derive: str
    label: str


@dataclass(frozen=True)
class Check:
    label: str
    mode: str
    ratio: float | None     # None: a colour could not be worked out
    minimum: float

    @property
    def ok(self) -> bool:
        return self.ratio is None or self.ratio >= self.minimum - 0.005


def contrast(first: str, second: str) -> float:
    """The WCAG contrast ratio of two "#rrggbb" colours."""
    def luminance(value: str) -> float:
        def channel(c: float) -> float:
            return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
        r, g, b = (int(value[i:i + 2], 16) / 255 for i in (1, 3, 5))
        return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)
    light, dark = sorted((luminance(first), luminance(second)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


def parse_modes_header(value: str) -> list[tuple[str, str]]:
    """[(id, label)] of `% SlideMage modes: light, dark=Dark slides`."""
    found = []
    for part in value.split(","):
        mode_id, _, label = part.strip().partition("=")
        if mode_id.strip():
            found.append((mode_id.strip(), label.strip()))
    return found


def format_modes_header(modes: list[tuple[str, str]]) -> str:
    return ", ".join(f"{mode_id}={label}" if label else mode_id for mode_id, label in modes)


class ThemeModel:
    """The theme form's model of one theme's text. `text` is the current text after every edit."""

    def __init__(self, text: str, root: Path, key: str, setup_text: str) -> None:
        self.root = root
        self.key = key
        self.catalog = theme_fields.catalog(setup_text)
        self.preset_dark = {role: value for role, value in _DERIVED_RE.findall(setup_text)}
        self.file = ThemeFile(text)
        self._colours: dict[tuple[str, str], dict[str, str]] = {}

    # --- the text --------------------------------------------------------------------------------------------------

    @property
    def text(self) -> str:
        return self.file.text

    def set_text(self, text: str) -> None:
        """The buffer changed (typing in the source tab)."""
        if text != self.file.text:
            self.file = ThemeFile(text)

    @property
    def readable(self) -> bool:
        """Whether the form can edit this file: a theme that \\inputs SlideMage_setup and then SlideMage_base."""
        return self.file.has_setup and self.file.has_base

    # --- modes -----------------------------------------------------------------------------------------------------

    def modes(self) -> list[Mode]:
        declared = self.file.modes()
        if not declared:
            return [Mode("", "", "Colours")]
        labels = dict(parse_modes_header(self.file.value("header:modes") or ""))
        return [Mode(mode_id, derive, labels.get(mode_id) or mode_id.capitalize()) for mode_id, derive in declared]

    @property
    def base(self) -> str:
        return self.modes()[0].id

    def header_mismatch(self) -> str:
        """"" when the header line names the modes the theme declares, else what differs (the app reads the header, TeX
        the declarations)."""
        declared = [m for m, _ in self.file.modes()]
        header = [m for m, _ in parse_modes_header(self.file.value("header:modes") or "")]
        if declared == header:
            return ""
        return (f"The header line names the modes {', '.join(header) or 'none'}, the theme declares "
                f"{', '.join(declared) or 'none'}. SlideMage offers what the header names.")

    def add_mode(self, mode_id: str, derive: str, label: str) -> None:
        """Declare a mode (header line and \\SMDeclareMode). A theme without modes gets its base mode, "light", first."""
        if not MODE_ID_RE.fullmatch(mode_id):
            raise ValueError("A mode's name is lower-case letters, digits and _, starting with a letter.")
        if derive not in DERIVES:
            raise ValueError(f"Unknown derivation {derive!r}.")
        header = parse_modes_header(self.file.value("header:modes") or "")
        declared = [m for m, _ in self.file.modes()]
        if mode_id in declared:
            raise ValueError(f"The theme has a mode {mode_id} already.")
        if not declared:
            if mode_id == "light":
                raise ValueError("The base mode is called light: give the new mode another name.")
            self.file.set("mode:light", "")
            header = [("light", "")]
        elif not header:
            header = [(m, "") for m in declared]
        self.file.set("mode:" + mode_id, derive)
        self.file.set("header:modes", format_modes_header(header + [(mode_id, label.strip())]))
        self._colours.clear()

    def remove_mode(self, mode_id: str) -> None:
        """Take a mode out: its declaration, its header entry and every line of it. Not the base mode."""
        if mode_id == self.base:
            raise ValueError("The base mode cannot be removed.")
        for setting in [s for s in self.file.settings if s.mode == mode_id and s.editable]:
            self.file.remove(setting.key, mode_id)
        self.file.remove("mode:" + mode_id)
        header = [(m, label) for m, label in parse_modes_header(self.file.value("header:modes") or "") if m != mode_id]
        self.file.set("header:modes", format_modes_header(header))
        self._colours.clear()

    # --- colours ---------------------------------------------------------------------------------------------------

    def colours(self, mode: str) -> dict[str, str]:
        """{name: "#rrggbb"} of the palette (and the seven colour roles) in `mode`, from the current text."""
        key = (self.text, mode)
        if key not in self._colours:
            if len(self._colours) > 32:
                self._colours.clear()
            self._colours[key] = theme_colors.theme_colors_for_text(self.text, self.root, mode)
        return self._colours[key]

    def palette_names(self) -> list[str]:
        return [f.name for f in theme_fields.FIELDS if f.group == "palette"] + self.file.own_colours()

    def palette_written(self, name: str, mode: str) -> str | None:
        """What the theme writes for the palette colour in `mode` (the base: its \\definecolor), None if it follows."""
        return self.file.value(name, "" if mode == self.base else mode)

    def palette_hex(self, name: str, mode: str) -> str | None:
        return self.colours(mode).get(name)

    def set_palette(self, name: str, mode: str, value: str | None) -> None:
        """Give the palette colour `name` the value `value` ("#rrggbb", an expression in the base) in `mode`; None takes
        the line out (the base: the framework's colour; another mode: the base colour, or its preset's)."""
        mode = "" if mode == self.base else mode
        if value is None:
            self.file.remove(name, mode)
        else:
            self.file.set(name, value, mode)
        self._colours.clear()

    def add_own_colour(self, name: str, value: str) -> None:
        """A palette colour of the theme's own (c_..._canvas), offered to the roles."""
        if not OWN_COLOUR_RE.fullmatch(name):
            raise ValueError("A colour's name starts with c_ and has lower-case letters, digits and _.")
        if name in theme_fields.BY_NAME or name in ("c_true_black", "c_true_white") or self.file.find(name):
            raise ValueError(f"{name} exists already.")
        self.file.set(name, value)
        self._colours.clear()

    def colour_names(self) -> list[str]:
        """The names a role may take, for its drop-down."""
        return self.palette_names() + ["c_true_black", "c_true_white"]

    # --- roles -----------------------------------------------------------------------------------------------------

    def hook(self, role: str) -> str:
        field = theme_fields.BY_NAME.get("role:" + role)
        return field.hook if field else ""

    def role_editable(self, role: str, mode: str) -> bool:
        """A role in the base mode is a hook macro or, in a theme with modes, a \\SMSetRole line of the base mode."""
        return bool(mode) or bool(self.hook(role))

    def role_written(self, role: str, mode: str) -> str | None:
        """What the theme writes for the role in `mode`; None if it follows (the base, the preset)."""
        explicit = self.file.value("role:" + role, mode) if mode else None
        if explicit is not None:
            return explicit
        if mode == self.base and self.hook(role):
            return self.file.value(self.hook(role))
        return None

    def role_follows(self, role: str, mode: str) -> str:
        """What the role takes in `mode` when the theme writes nothing for it: shown in place of a value."""
        if mode != self.base:
            derive = next((m.derive for m in self.modes() if m.id == mode), "")
            if derive == "dark" and role in self.preset_dark:
                return self.preset_dark[role]
            return "as in " + self.modes()[0].label.lower()
        hook = self.hook(role)
        if hook:
            return self.catalog[hook].default or "(the theme's default)"
        source = self.catalog["role:" + role].source
        return {"SM@processline": "none", "SM@inlinecode": "(the text's colour)"}.get(source, source)

    def role_expression(self, role: str, mode: str) -> str:
        """The colour expression the role comes to in `mode` ("\\SMTitleBoxColor" for one that follows a hook)."""
        explicit = self.file.value("role:" + role, mode) if mode else None
        if explicit is not None:
            return explicit
        if mode != self.base:
            derive = next((m.derive for m in self.modes() if m.id == mode), "")
            if derive == "dark" and role in self.preset_dark:
                return self.preset_dark[role]
        hook = self.hook(role)
        return "\\" + hook if hook else self.catalog["role:" + role].source

    def set_role(self, role: str, mode: str, value: str | None) -> None:
        """Give the role a colour in `mode` (None: follow). In the base mode a hook role writes its macro."""
        hook = self.hook(role)
        if mode == self.base and hook:
            if value is None:
                self.file.remove(hook)
            else:
                self.file.set(hook, value)
        elif mode:
            if value is None:
                self.file.remove("role:" + role, mode)
            else:
                self.file.set("role:" + role, value, mode)
        else:
            raise ValueError("Declare colour modes before giving this role a colour of its own.")
        self._colours.clear()

    def resolve(self, expression: str, mode: str, _depth: int = 0) -> str | None:
        """"#rrggbb" of a colour expression, a role ("role:text") or a hook macro ("\\SMTitleBoxColor") in `mode`."""
        if _depth > 8:
            return None
        expression = expression.strip()
        if expression.startswith("role:"):
            return self.resolve(self.role_expression(expression[5:], mode), mode, _depth + 1)
        if expression.startswith("\\"):
            hook = expression[1:]
            role = theme_fields.ROLE_OF_HOOK.get(hook, "")[5:]
            explicit = self.file.value("role:" + role, mode) if role and mode else None
            value = explicit if explicit is not None else self.file.value(hook)
            if value is None:
                value = self.catalog[hook].default if hook in self.catalog else ""
            return self.resolve(value, mode, _depth + 1) if value else FRAMEWORK_COLOURS[""]
        if expression in FRAMEWORK_COLOURS:
            return FRAMEWORK_COLOURS[expression]
        colours = dict(self.colours(mode))
        base_colours = self.colours(self.base)
        for name, entry in self.catalog.items():
            if entry.kind != "optional_colour":
                continue
            # The theme's own \definecolor / \colorlet runs before any mode applies, so it is the base palette's
            # colour; the framework's default (\SM@applymode) is made after the mode's palette lines.
            own = self.file.value(name)
            if own is not None:
                resolved = own if own.startswith("#") else theme_colors.evaluate(own, base_colours)
            else:
                resolved = theme_colors.evaluate(entry.default, colours) if entry.default else None
            if resolved:
                colours[name] = resolved
        if expression in ("none", ""):
            return None
        return theme_colors.evaluate(expression, colours)

    # --- checks ----------------------------------------------------------------------------------------------------

    def checks(self, mode: str) -> list[Check]:
        found = []
        for label, fg, bg, minimum in CHECKS:
            fg_hex, bg_hex = self.resolve(fg, mode), self.resolve(bg, mode)
            ratio = contrast(fg_hex, bg_hex) if fg_hex and bg_hex else None
            found.append(Check(label, mode, ratio, minimum))
        return found

    # --- identity, logo, footnotes ---------------------------------------------------------------------------------

    def name(self) -> str:
        return self.file.value("header:name") or ""

    def set_name(self, name: str) -> None:
        if not name.strip():
            self.file.remove("header:name")
        else:
            self.file.set("header:name", name.strip()[:40])

    def value(self, key: str) -> str | None:
        return self.file.value(key)

    def default(self, key: str) -> str:
        entry = self.catalog.get(key)
        return entry.default if entry else ""

    def set_value(self, key: str, value: str | None) -> None:
        """A plain hook (logo height, the logo's padding ...); None or "" takes it out."""
        if value is None or not value.strip():
            self.file.remove(key)
        else:
            self.file.set(key, value.strip())

    def import_logo(self, source: Path) -> str:
        """Copy a logo file into the project's scheme folder of this theme (schemes/scheme_<key>/) and point the theme
        at it. A file of that name there is replaced only when it is the same file. Returns the path the theme writes."""
        folder = self.root / "schemes" / f"scheme_{self.key.replace('-', '_')}"
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / source.name
        if source.resolve() != target.resolve():
            if target.exists() and target.read_bytes() != source.read_bytes():
                raise ValueError(f"{target.relative_to(self.root).as_posix()} exists and is another file.")
            shutil.copyfile(source, target)
        relative = target.relative_to(self.root).as_posix()
        self.file.set("SMInstituteLogoPath", relative)
        return relative

    def footnote_style(self) -> str:
        """symbols | boxed | dice | numbers | custom (a \\renewcommand{\\SMFootnoteMark} of the theme's own)."""
        mark = self.file.value("SMFootnoteMark")
        if mark is not None:
            return "numbers" if mark.strip() == "\\number#1" else "custom"
        return self.file.value("SMSetFootnoteMarkers") or "symbols"

    def set_footnote_style(self, style: str) -> None:
        if style not in {s for s, _ in FOOTNOTE_STYLES}:
            raise ValueError(f"Unknown footnote style {style!r}.")
        if style == "numbers":
            self.file.remove("SMSetFootnoteMarkers")
            self.file.set("SMFootnoteMark", "\\number#1")
            return
        self.file.remove("SMFootnoteMark")
        if style == "symbols":
            self.file.remove("SMSetFootnoteMarkers")
        else:
            self.file.set("SMSetFootnoteMarkers", style)
