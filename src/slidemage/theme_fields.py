# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
r"""What the theme form offers: one Field per setting of the hook catalog (latex/SlideMage_setup.tex), with the group,
kind, label and tier the form shows (docs/plans/theme-editor.md, sections 2 and 3.2). Defaults and help texts are not
copied here: `catalog()` reads them from the setup file the project compiles with, so the form shows what the framework
does. tests/test_theme_fields.py fails when a catalog name has no Field, or a Field names something the catalog no
longer has, so the form and the framework cannot drift apart.

Field names are the keys theme_file.ThemeFile uses: a hook's name without the backslash (`SMLogoHeight`), a palette
colour's name (`c_primary_dark`), `role:<id>` for a colour role (written per mode with \SMSetRole), and the two header
lines `header:name` and `header:modes`.

Tiers (section 2): 1 = the form's first release (identity, palette, logo, roles, code colours, footnote marker),
2 = its second (font, sizes, margins, title bar, footer, lists, citation), 3 = "Advanced" (frame types, fine spacing,
drawings, optional features)."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .tex_source import braced_argument, masked_same_length

# Kinds of field (section 3.2): colour (picker plus hex), palette_name (a colour name, for roles), length (number plus
# unit), size_pair (\fontsize{a}{b}\selectfont), number (a ratio), choice, text, file, profile, tex (raw TeX the form
# shows as text until it has a picker for it), modes (the header's list).
KINDS = {"colour", "palette_name", "length", "size_pair", "number", "choice", "text", "file", "profile", "tex",
         "modes"}


@dataclass(frozen=True)
class Field:
    name: str
    group: str
    kind: str
    label: str
    tier: int
    hook: str = ""          # a role whose base-mode value is a catalog macro: that macro (role:title_fill -> SMTitleBoxColor)
    args: int = 0           # a macro that takes arguments (\renewcommand{\SMFootnoteMark}[1]{...})
    choices: tuple[str, ...] = ()


def _f(name, group, kind, label, tier, **extra) -> Field:
    return Field(name, group, kind, label, tier, **extra)


_ROLE_LABELS = {
    # colour roles slides can name (c_text ...), base source in the catalog
    "text": "Body text", "canvas": "Slide background", "card": "Card fill", "line": "Card border",
    "text_muted": "Secondary text", "text_on_accent": "Text on a colored fill", "link": "Links",
    # parts of a slide
    "block_title_fill": "Block title fill", "alerted_block_title_fill": "Alert block title fill",
    "example_block_title_fill": "Example block title fill", "reference_block_title_fill": "Reference block title fill",
    "info_block_title_fill": "Info block title fill", "block_body_fill": "Block body fill",
    "block_body_text": "Block body text", "link_underline": "Link underline", "quote_attribution": "Quote attribution",
    "table_rule": "Table rules", "image_border": "Image border", "marker": "Markers (highlights, warning sign)",
    "citation": "Citation marks", "strip_fill": "Progress strip fill", "strip_text": "Progress strip text",
    "code_keyword": "Code commands", "code_comment": "Code comments", "code_panel": "Code panel",
    "code_text": "Code text", "standout_fill": "Standout frame fill", "button_text": "Button text",
    "process_line": "Process box border", "inline_code": "Inline code",
}
# Roles whose base-mode value is a hook macro of the catalog (\SM@rolehook in the setup file).
_ROLE_HOOKS = {
    "title_fill": ("SMTitleBoxColor", "Title bar"), "title_text": ("SMTitleTextColor", "Title text"),
    "footer_fill": ("SMFooterBoxColorDefault", "Footer box"), "footer_text": ("SMFooterTextColor", "Footer text"),
    "bullet": ("SMBulletColor", "Bullets"), "alert": ("SMAlertTextColor", "\\alert text"),
    "progress": ("SMProgressBarColor", "Progress bar"),
    "block_title_text": ("SMBlockTitleTextColor", "Block title text"),
    "alerted_block_title_text": ("SMAlertedBlockTitleTextColor", "Alert block title text"),
    "example_block_title_text": ("SMExampleBlockTitleTextColor", "Example block title text"),
    "reference_block_title_text": ("SMReferenceBlockTitleTextColor", "Reference block title text"),
    "info_block_title_text": ("SMInfoBlockTitleTextColor", "Info block title text"),
    "standout_text": ("SMStandoutTextColor", "Standout frame text"),
}

_PALETTE = [
    ("c_primary_dark", "Primary dark"), ("c_primary_highlight", "Highlight"), ("c_primary_gray", "Primary gray"),
    ("c_primary_white", "Primary white"),
    ("c_secondary_violet", "Violet"), ("c_tertiary_violet", "Violet, light"),
    ("c_secondary_blue", "Blue"), ("c_tertiary_blue", "Blue, light"),
    ("c_secondary_green", "Green"), ("c_tertiary_green", "Green, light"),
    ("c_secondary_red", "Red"), ("c_tertiary_red", "Red, light"),
    ("c_secondary_orange", "Orange"), ("c_tertiary_orange", "Orange, light"),
    ("c_secondary_yellow", "Yellow"), ("c_tertiary_yellow", "Yellow, light"),
    ("c_tertiary_gray", "Gray, light"),
    ("c_custom_gray", "Supporting gray"), ("c_custom_red", "Supporting red"), ("c_custom_green", "Supporting green"),
    ("c_custom_brown", "Supporting brown"),
]

_FEATURES = [
    ("SMMiniFramesPosition", "Mini frames: position", ("head", "foot", "left", "right", "none")),
    ("SMMiniFramesSpreading", "Mini frames: spreading", ("spreading", "centering", "left", "right")),
    ("SMMiniFramesSections", "Mini frames: section names", ("none", "section", "secsubsection")),
    ("SMMiniFramesCompress", "Mini frames: one row per section", ("true", "false")),
    ("SMProgressBarPosition", "Progress bar: position", ("head", "frametitle", "foot", "left", "right", "none")),
    ("SMProgressBarStyle", "Progress bar: style", ("rectangle", "rounded box")),
    ("SMProgressBarDirection", "Progress bar: direction", ("tlbr", "brlt")),
    ("SMProgressBarMiniFrames", "Progress bar: mini frames inside", ("true", "false")),
    ("SMDividerFrames", "Divider frames: levels", ()),
    ("SMDividerLook", "Divider frames: look",
     ("SMSimple", "SMProgressbar", "SMSplitvertSimple", "SMSplitvertProgressbar", "SMProgressvert")),
    ("SMWatermarkDefault", "Watermark on every frame", ("true", "false")),
    ("SMWatermarkTemplate", "Watermark template", ()),
]

FIELDS: tuple[Field, ...] = (
    # --- tier 1: identity, palette, roles, logo, code colours, footnote marker -------------------------------------
    _f("header:name", "identity", "text", "Name", 1),
    _f("header:modes", "identity", "modes", "Color modes", 1),
    _f("SMLayoutProfile", "font", "profile", "Layout profile (fonts)", 2),
    *(_f(name, "palette", "colour", label, 1) for name, label in _PALETTE),
    *(_f("role:" + role, "roles", "palette_name", label, 1, hook=hook) for role, (hook, label) in _ROLE_HOOKS.items()),
    _f("SMHighlightTitleTextColor", "roles", "palette_name", "Highlight frame title text", 1),
    *(_f("role:" + role, "roles", "palette_name", label, 1) for role, label in _ROLE_LABELS.items()),
    _f("SMCanvasColor", "cards", "colour", "Slide background", 3),
    _f("SMCardBackgroundColor", "cards", "colour", "Card fill", 3),
    _f("SMCardBorderColor", "cards", "colour", "Card border", 3),
    _f("SMProcessBorderColor", "cards", "colour", "Process box border", 3),
    _f("SMCodeKeywordColor", "code", "colour", "Code commands", 1),
    _f("SMCodeCommentColor", "code", "colour", "Code comments", 1),
    _f("SMCodeBackgroundColor", "code", "colour", "Code panel", 1),
    _f("SMCodeTextColor", "code", "colour", "Code text", 1),
    _f("SMCardHeadingStyle", "drawing", "tex", "Card heading font switch", 3),
    _f("SMInstituteLogoPath", "logo", "file", "Logo (vector PDF)", 1),
    _f("SMLogoHeight", "logo", "length", "Logo height", 1),
    # --- tier 2: sizes, margins, title bar, footer, lists, citation -----------------------------------------------
    _f("SMTopMargin", "margins", "length", "Top Margin", 2),
    _f("SMCitationFormat", "citation", "choice", "Citation format", 2),
    _f("SMBodyFontSize", "sizes", "length", "Body text size", 2),
    _f("SMTextMarginLeft", "margins", "length", "Text margin, left", 2),
    _f("SMTextMarginRight", "margins", "length", "Text margin, right", 2),
    _f("SMFrametitleTopPadding", "titlebar", "length", "Title bar, top padding", 2),
    _f("SMFrametitleBottomPadding", "titlebar", "length", "Title bar, bottom padding", 2),
    _f("SMFrametitleLeftPadding", "titlebar", "length", "Title bar, left padding", 2),
    _f("SMFrametitleRightPadding", "logo", "length", "Space around the logo", 1),
    _f("SMFrameSubtitleSep", "titlebar", "tex", "Between title and subtitle", 2),
    _f("SMFrameSubtitleStrutEnd", "titlebar", "length", "Extra space under a subtitle", 2),
    _f("SMFooterBoxHeight", "footer", "length", "Footer box height", 2),
    _f("SMFooterTextSize", "footer", "size_pair", "Footer text size", 2),
    _f("SMFooterIDSize", "footer", "size_pair", "Slide id size", 2),
    _f("SMFootlineSidePadding", "footer", "length", "Footer text, left padding", 2),
    _f("SMFootnoteFooterGap", "footer", "length", "Gap between footnotes and footer", 2),
    _f("SMFootnoteSize", "footer", "size_pair", "Footnote text size", 2),
    _f("SMSetFootnoteMarkers", "footnotes", "choice", "Footnote markers", 1, choices=("symbols", "boxed", "dice")),
    _f("SMFootnoteMark", "footnotes", "tex", "Footnote marker (TeX)", 1, args=1),
    _f("SMFootnoteSep", "footer", "length", "Space between footnotes", 2),
    _f("SMSideFootnoteHsize", "spacing", "length", "Side footnotes: line length", 3),
    _f("SMSideFootnoteTitleBlockSep", "spacing", "length", "Side footnotes: drop below the title", 3),
    _f("SMSideFootnoteRightInset", "spacing", "length", "Side footnotes: gap to the page edge", 3),
    _f("SMSideFootnoteMarkerShift", "spacing", "length", "Side footnotes: marker shift", 3),
    _f("SMBlockSideMargin", "margins", "length", "Block side margin", 2),
    _f("SMBlockTitleMarkerWidth", "blocks", "length", "Block title marker width", 3),
    # --- tier 3: frame types, fine spacing, drawings, optional features --------------------------------------------
    _f("SMTitleframeBoxHeight", "frametypes", "length", "Title frame: box height", 3),
    _f("SMTitleframeTextSep", "frametypes", "length", "Title frame: title to subtitle", 3),
    _f("SMTitleframeBandGap", "frametypes", "length", "Title frame: gap above the band", 3),
    _f("SMTitleframeBottomPad", "frametypes", "length", "Title frame: bottom padding", 3),
    _f("SMSectionframeBoxHeight", "frametypes", "length", "Section frame: bar height", 3),
    _f("SMSectionframeTitleGap", "frametypes", "length", "Section frame: title to bar edge", 3),
    _f("SMSectionframeContentDrop", "frametypes", "length", "Section frame: text drop", 3),
    _f("SMQuoteBoxHeight", "frametypes", "length", "Quote frame: box height", 3),
    _f("SMQuoteAttributionGap", "frametypes", "length", "Quote frame: gap above the attribution", 3),
    _f("SMProgressStripRoom", "frametypes", "length", "Progress strip: room below", 3),
    _f("SMBulletSymbol", "lists", "tex", "Bullet symbol", 2, args=1),
    *(_f(f"SMItemsepRatio{level}", "spacing", "number", f"Item spacing, level {level}", 3)
      for level in ("I", "II", "III", "IV")),
    *(_f(f"SMItemizeLevelDropSpaceRatio{level}", "spacing", "number", f"Space after a level {level} list", 3)
      for level in ("I", "II", "III", "IV")),
    *(_f(f"SMItemizeLevelOpenSpaceRatio{level}", "spacing", "number", f"Space before a level {level} list", 3)
      for level in ("I", "II", "III")),
    _f("SMTallItemBaseRatio", "spacing", "number", "Extra space of \\tallitem", 3),
    _f("SMLabelItemItemsep", "spacing", "length", "Labelled lists: item spacing", 3),
    _f("SMLabelItemGap", "spacing", "length", "Labelled lists: label to text", 3),
    _f("SMEnumerateNestedSlotExtra", "spacing", "length", "Nested enumerate: numeral clearance", 3),
    _f("SMEnumerateNestedLabelGap", "spacing", "length", "Nested enumerate: numeral to text", 3),
    _f("SMEnumerateTextExtra", "spacing", "length", "Enumerate text indent", 3),
    _f("SMTightDisplaySkip", "spacing", "length", "Tight display skip", 3),
    _f("SMBesideFigureTopGap", "spacing", "length", "besidefigure: top gap", 3),
    _f("SMImageBorderWidth", "drawing", "length", "Image border width", 3),
    _f("SMWarningSignPadding", "drawing", "length", "Warning sign padding", 3),
    _f("SMWarningSignBorderWidth", "drawing", "length", "Warning sign border", 3),
    _f("SMCodeSize", "sizes", "size_pair", "Code text size", 2),
    *(_f(name, "features", "choice" if choices else "text", label, 3, choices=choices)
      for name, label, choices in _FEATURES),
)

BY_NAME: dict[str, Field] = {field.name: field for field in FIELDS}
# A hook macro that is the base-mode value of a role: the role's field covers it.
ROLE_OF_HOOK: dict[str, str] = {field.hook: field.name for field in FIELDS if field.hook}
COMMANDS: frozenset[str] = frozenset(field.name for field in FIELDS if field.group == "features") | {"SMSetFootnoteMarkers"}
GROUPS = ("identity", "palette", "roles", "code", "logo", "footnotes", "font", "sizes", "margins", "titlebar", "footer",
          "lists", "citation", "blocks", "cards", "frametypes", "spacing", "drawing", "features")


def order(name: str) -> int:
    """Where a setting goes among the others the form writes: the catalog's order (FIELDS); a palette colour of the
    theme's own right after the palette; anything else last."""
    if name in BY_NAME:
        return list(BY_NAME).index(name)
    if name in ROLE_OF_HOOK:
        return order(ROLE_OF_HOOK[name])
    if not name.startswith(("SM", "role:", "mode:", "header:")):
        return order("c_custom_brown")
    return len(FIELDS)


# --- reading the catalog ---------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class CatalogEntry:
    name: str
    kind: str        # length | macro | colour | optional_colour | role | command | profile
    default: str     # as written in the setup file ("" for a role: see `source`)
    help: str        # its trailing comment
    source: str = "" # a role: what it resolves to in the base mode (a colour name or a hook macro)


_LENGTH_RE = re.compile(r"\\setlength\{\\(SM[A-Za-z]+)\}(?=\{)")
_NEWLENGTH_RE = re.compile(r"\\newlength\{\\(SM[A-Za-z]+)\}")
_MACRO_RE = re.compile(r"\\(newcommand|providecommand)\{\\(SM[A-Za-z]+)\}(?:\[\d\])?(?=\{)")
_COLOUR_RE = re.compile(r"\\definecolor\{(c_[a-z_]+)\}\{HTML\}(?=\{)")
_OPTIONAL_RE = re.compile(r"^%\s{2,}(SM[A-Za-z]+Color)\s+(.+?)\s*$", re.M)
_ROLE_COLOUR_RE = re.compile(r"\\SM@rolecolour\{(\w+)\}\{[^}]*\}\{([^{}]*(?:\{[^}]*\})?[^{}]*)\}")
_ROLE_HOOK_RE = re.compile(r"\\SM@rolehook\{(\w+)\}\\(SM@?[A-Za-z]+)")
_FEATURE_RE = re.compile(r"^%\s+\\(SM[A-Za-z]+)\{", re.M)
# Macros of the setup file that are no hook: its bookkeeping, the removed and renamed names (error macros) and the
# colour-mode layer's data lines (theme_file reads those as modes and role lines).
_NOT_HOOKS = {"SMSetupLoaded", "SMDeclareMode", "SMSetRole", "SMSetColor"}


def _comment(line: str) -> str:
    cut = line.find("%")
    return line[cut + 1:].strip() if cut >= 0 else ""


def catalog(setup_text: str) -> dict[str, CatalogEntry]:
    """The settings a template may make, read from SlideMage_setup.tex: {name: CatalogEntry}, in the file's order."""
    found: dict[str, CatalogEntry] = {}
    code = masked_same_length(setup_text)
    lengths = set(_NEWLENGTH_RE.findall(code))

    def line_of(pos: int) -> str:
        start = setup_text.rfind("\n", 0, pos) + 1
        end = setup_text.find("\n", pos)
        return setup_text[start:end if end >= 0 else len(setup_text)]

    events: list[tuple[int, CatalogEntry]] = []
    for match in _LENGTH_RE.finditer(code):
        if match.group(1) in lengths:
            value, _ = braced_argument(setup_text, match.end())
            events.append((match.start(), CatalogEntry(match.group(1), "length", value, _comment(line_of(match.start())))))
    for match in _MACRO_RE.finditer(code):
        name = match.group(2)
        value, _ = braced_argument(setup_text, match.end())
        if name in _NOT_HOOKS or value.lstrip().startswith(("\\SM@removedname", "\\SM@renamedname")):
            continue
        kind = "profile" if match.group(1) == "providecommand" else "macro"
        events.append((match.start(), CatalogEntry(name, kind, value, _comment(line_of(match.start())))))
    for match in _COLOUR_RE.finditer(code):
        value, _ = braced_argument(setup_text, match.end())
        events.append((match.start(), CatalogEntry(match.group(1), "colour", value, _comment(line_of(match.start())))))
    for match in _OPTIONAL_RE.finditer(setup_text):
        help_text, _, default = match.group(2).rpartition("(")
        events.append((match.start(), CatalogEntry(match.group(1), "optional_colour", default.rstrip(")").strip(),
                                                   help_text.strip())))
    for match in _ROLE_COLOUR_RE.finditer(code):
        events.append((match.start(), CatalogEntry("role:" + match.group(1), "role", "", "", match.group(2))))
    for match in _ROLE_HOOK_RE.finditer(code):
        events.append((match.start(), CatalogEntry("role:" + match.group(1), "role", "", "", match.group(2))))
    features = setup_text.find("Optional theme features")
    if features >= 0:
        for match in _FEATURE_RE.finditer(setup_text, features):
            events.append((match.start(), CatalogEntry(match.group(1), "command", "", _comment(line_of(match.start())))))
    for _, entry in sorted(events, key=lambda event: event[0]):
        if entry.kind == "macro" and entry.name in found and found[entry.name].kind == "length":
            continue
        found.setdefault(entry.name, entry)
    found.setdefault("SMSetFootnoteMarkers", CatalogEntry("SMSetFootnoteMarkers", "command", "symbols",
                                                          "the theme's footnote marker style: symbols, boxed or dice"))
    return found


def setup_file(root: Path) -> Path | None:
    """The SlideMage_setup.tex the project at `root` compiles with."""
    from . import slide_templates

    for folder in slide_templates.framework_dirs(root):
        if (folder / "SlideMage_setup.tex").is_file():
            return folder / "SlideMage_setup.tex"
    return None
