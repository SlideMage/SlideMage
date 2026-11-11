# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
r"""Read a theme (a SlideMage_template_<key>.tex) setting by setting, and change one setting in place
(docs/plans/theme-editor.md, section 3.1, stage C1a). The file stays the truth: a theme is hand-written and commented,
so nothing here regenerates it.

* Recognise, edit in place. Each setting is one command of the catalog (latex/SlideMage_setup.tex): \setlength,
  \renewcommand, \definecolor / \colorlet, the colour-mode data lines \SMDeclareMode, \SMSetColor, \SMSetRole, the
  optional-feature commands, \newcommand{\SMLayoutProfile} before the setup file, and the header lines
  `% SlideMage template name:` and `% SlideMage modes:`. Changing a value rewrites only that value: the command,
  its spacing and its trailing comment stay. A value set to what it already is changes nothing (byte for byte).
* A setting the file does not have is added: a mode line after the file's last mode line, anything else inside a
  marked block (`% --- SlideMage theme editor: begin ---` / `end ---`) right before \input{SlideMage_base}, in the
  catalog's order (theme_fields.order).
* Beyond the form is kept and counted. Lines inside a conditional (\ifdefined ... \fi), after \input{SlideMage_base},
  or holding commands the form cannot model (\setbeamercolor, \newfontfamily, \tikzset) are never touched;
  `beyond()` lists them so the form can say how many there are and open the source tab on them.

Keys are theme_fields' Field names: a hook's name (`SMLogoHeight`), a colour's name (`c_primary_dark`, a theme's own
`c_graz_dark_canvas`, an optional `SMCanvasColor`), `role:<id>` and `mode:<id>` (mode-layer lines, with the mode id as
`mode`), `header:name`, `header:modes`. A colour given in a mode (\SMSetColor) has its colour name as key and the mode
as `mode`."""
from __future__ import annotations

import re
from dataclasses import dataclass

from . import theme_fields
from .tex_source import braced_argument, masked_same_length

BLOCK_BEGIN = "% --- SlideMage theme editor: begin ---"
BLOCK_END = "% --- SlideMage theme editor: end ---"

_NAME = r"[A-Za-z][A-Za-z0-9_]*"
_COMMANDS = "|".join(sorted(theme_fields.COMMANDS))
_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("length", re.compile(r"\\setlength\s*\{\s*\\(SM[A-Za-z]+)\s*\}\s*(?=\{)")),
    ("macro", re.compile(r"\\renewcommand\*?\s*\{\s*\\(SM[A-Za-z]+)\s*\}\s*(?:\[(\d)\]\s*)?(?=\{)")),
    ("profile", re.compile(r"\\newcommand\*?\s*\{\s*\\(SMLayoutProfile)\s*\}\s*(?=\{)")),
    ("colour", re.compile(r"\\definecolor\s*\{(" + _NAME + r")\}\s*(?=\{)")),
    ("colorlet", re.compile(r"\\colorlet\s*\{(" + _NAME + r")\}\s*(?=\{)")),
    ("mode", re.compile(r"\\SMDeclareMode\s*\{(\w+)\}\s*(?=\{)")),
    ("role", re.compile(r"\\SMSetRole\s*\{(\w+)\}\s*\{(\w+)\}\s*(?=\{)")),
    ("modecolour", re.compile(r"\\SMSetColor\s*\{(" + _NAME + r")\}\s*\{(\w+)\}\s*(?=\{)")),
    ("command", re.compile(r"\\(" + _COMMANDS + r")\s*(?=\{)")),
]
_HEADERS = {"header:name": re.compile(r"^%+[ \t]*SlideMage template name:[ \t]*([^\r\n]*?)[ \t]*\r?$", re.M),
            "header:modes": re.compile(r"^%+[ \t]*SlideMage modes:[ \t]*([^\r\n]*?)[ \t]*\r?$", re.M)}
_HEADER_LINES = {"header:name": "% SlideMage template name: {}", "header:modes": "% SlideMage modes: {}"}
_SETUP_RE = re.compile(r"\\input\s*\{SlideMage_setup(?:\.tex)?\}")
_BASE_RE = re.compile(r"\\input\s*\{SlideMage_base(?:\.tex)?\}")
_COND_RE = re.compile(r"\\(newif\s*\\if[A-Za-z@]*|ifthenelse|if[A-Za-z@]*|fi)(?![A-Za-z@])")
_HEX_RE = re.compile(r"#?([0-9A-Fa-f]{6})")


@dataclass(frozen=True)
class Setting:
    key: str
    mode: str          # the mode of a \SMSetColor / \SMSetRole line; "" otherwise
    kind: str          # header | length | macro | profile | colour | colorlet | mode | role | modecolour | command
    value: str         # as written: "3ex", "c_primary_highlight", "ffd500" (with `model`), "dark" (a mode's derive)
    model: str         # a colour's model ("HTML", "RGB", ...); "" for an expression
    start: int         # the command's (or header line's) first character
    value_start: int   # the span the value occupies: for a colour {model}{spec}, else the braced argument's content
    value_end: int
    end: int           # after the command
    line: int          # 0-based line of `start`
    where: str         # before (the setup file) | settings | after (the base)
    conditional: bool  # inside \if ... \fi
    args: str = ""     # a macro's "[1]"

    @property
    def editable(self) -> bool:
        if self.kind == "header":
            return True
        if self.conditional:
            return False
        return self.where == "before" if self.kind == "profile" else self.where == "settings"


def _hex_value(value: str) -> str | None:
    found = _HEX_RE.fullmatch(value.strip())
    return found.group(1) if found else None


class ThemeFile:
    """One theme's text, its settings, and in-place edits of them. `text` is the current text after every edit."""

    def __init__(self, text: str):
        self.text = text
        self._parse()

    # --- reading ---------------------------------------------------------------------------------------------------

    @property
    def has_setup(self) -> bool:
        """Whether the theme \\inputs SlideMage_setup (a catalog theme the form can read)."""
        return self._setup_pos >= 0

    @property
    def has_base(self) -> bool:
        return self._base_pos >= 0

    @property
    def base_line_start(self) -> int:
        """The offset of the line holding \\input{SlideMage_base} (-1 without one): lines put there run right before it."""
        return self.text.rfind("\n", 0, self._base_pos) + 1 if self._base_pos >= 0 else -1

    @property
    def newline(self) -> str:
        return "\r\n" if "\r\n" in self.text else "\n"

    def _parse(self) -> None:
        text = self.text
        code = masked_same_length(text)
        setup = _SETUP_RE.search(code)
        base = _BASE_RE.search(code)
        self._setup_pos = setup.start() if setup else -1
        self._base_pos = base.start() if base else -1
        self._depth = self._conditionals(code)
        top = self._top_level(code)
        found: list[Setting] = []
        for key, pattern in _HEADERS.items():
            head_end = _nth_line_start(text, 30)
            match = pattern.search(text, 0, head_end)
            if match:
                found.append(self._setting(key, "", "header", match.group(1), "", match.start(), match.start(1),
                                           match.end(1), match.end()))
        for kind, pattern in _PATTERNS:
            for match in pattern.finditer(code):
                if not top[match.start()]:
                    continue
                setting = self._read(kind, match)
                if setting:
                    found.append(setting)
        self.settings = sorted(found, key=lambda s: s.start)

    def _read(self, kind: str, match: re.Match[str]) -> Setting | None:
        text = self.text
        value, after = braced_argument(text, match.end())
        if after == match.end():
            return None
        name = match.group(1)
        if kind == "length" or kind == "profile" or kind == "command":
            return self._setting(name, "", kind, value, "", match.start(), match.end() + 1, after - 1, after)
        if kind == "macro":
            return self._setting(name, "", kind, value, "", match.start(), match.end() + 1, after - 1, after,
                                 f"[{match.group(2)}]" if match.group(2) else "")
        if kind == "colorlet":
            return self._setting(name, "", kind, value, "", match.start(), match.end() + 1, after - 1, after)
        if kind == "mode":
            return self._setting("mode:" + name, "", kind, value, "", match.start(), match.end() + 1, after - 1, after)
        if kind == "role":
            return self._setting("role:" + name, match.group(2), kind, value, "", match.start(), match.end() + 1,
                                 after - 1, after)
        # colour (\definecolor{name}{model}{spec}) and modecolour (\SMSetColor{name}{mode}{model}{spec})
        spec_open = _skip_space(text, after)
        spec, spec_end = braced_argument(text, spec_open)
        if spec_end == spec_open:
            return None
        mode = match.group(2) if kind == "modecolour" else ""
        return self._setting(name, mode, kind, spec, value, match.start(), match.end(), spec_end, spec_end)

    def _setting(self, key, mode, kind, value, model, start, value_start, value_end, end, args="") -> Setting:
        if self._setup_pos >= 0 and start < self._setup_pos:
            where = "before"
        elif self._base_pos >= 0 and start > self._base_pos:
            where = "after"
        else:
            where = "settings"
        return Setting(key, mode, kind, value, model, start, value_start, value_end, end,
                       self.text.count("\n", 0, start), where, kind != "header" and self._depth[start] > 0, args)

    @staticmethod
    def _conditionals(code: str) -> list[int]:
        """The \\if ... \\fi depth at every offset of `code` (\\newif and \\ifthenelse are no conditionals)."""
        depth = [0] * (len(code) + 1)
        level, last = 0, 0
        for match in _COND_RE.finditer(code):
            word = match.group(1)
            if word.startswith(("newif", "ifthenelse")):
                continue
            for i in range(last, match.start()):
                depth[i] = level
            last = match.start()
            level = level + 1 if word != "fi" else max(level - 1, 0)
        for i in range(last, len(depth)):
            depth[i] = level
        return depth

    @staticmethod
    def _top_level(code: str) -> list[bool]:
        """Whether each offset of `code` lies outside every brace group (a setting inside another command's argument,
        say a \\newcommand's body, is not the theme's)."""
        top = [True] * (len(code) + 1)
        depth, i = 0, 0
        while i < len(code):
            char = code[i]
            top[i] = depth == 0
            if char == "\\":
                if i + 1 < len(code):
                    top[i + 1] = depth == 0
                i += 2
                continue
            if char == "{":
                depth += 1
            elif char == "}":
                depth = max(depth - 1, 0)
            i += 1
        return top

    def find(self, key: str, mode: str = "") -> Setting | None:
        """The setting the form edits for `key` in `mode`: the last editable one (in TeX the last line wins)."""
        hits = [s for s in self.settings if s.key == key and s.mode == mode and s.editable]
        return hits[-1] if hits else None

    def value(self, key: str, mode: str = "") -> str | None:
        """The value as written ("#rrggbb" for a HTML colour), or None when the theme does not set it."""
        setting = self.find(key, mode)
        if setting is None:
            return None
        if setting.model == "HTML" and _hex_value(setting.value):
            return "#" + setting.value.strip().lower()
        return setting.value

    def modes(self) -> list[tuple[str, str]]:
        """[(mode id, derive)] the theme declares, the first being its base mode."""
        return [(s.key[5:], s.value) for s in self.settings if s.kind == "mode" and s.editable]

    def own_colours(self) -> list[str]:
        """Palette colours of the theme's own (c_graz_dark_canvas): \\definecolor of a name the catalog lacks."""
        names = [s.key for s in self.settings if s.kind in ("colour", "colorlet") and s.editable
                 and s.key not in theme_fields.BY_NAME]
        return list(dict.fromkeys(names))

    def beyond(self) -> list[int]:
        """0-based lines with live code the form does not edit: not a recognised, editable setting, nor the
        \\input of the setup file or the base, nor the marked block's markers."""
        code = masked_same_length(self.text)
        covered: set[int] = set()
        for setting in self.settings:
            if setting.editable and setting.kind != "header":
                covered.update(range(setting.line, self.text.count("\n", 0, setting.end) + 1))
        for pattern in (_SETUP_RE, _BASE_RE):
            for match in pattern.finditer(code):
                if self._depth[match.start()] == 0:
                    covered.add(code.count("\n", 0, match.start()))
        result = []
        for number, line in enumerate(code.split("\n")):
            if line.strip() and number not in covered:
                result.append(number)
        return result

    # --- writing ---------------------------------------------------------------------------------------------------

    def set(self, key: str, value: str, mode: str = "") -> None:
        """Give `key` (in `mode`) the value `value`: in place when the theme sets it, else added. A colour takes
        "#rrggbb" (written as \\definecolor{..}{HTML}{..}) or an xcolor expression (\\colorlet); a mode line's
        colour takes "#rrggbb" only."""
        setting = self.find(key, mode)
        if setting is None:
            self._add(key, value, mode)
        else:
            self._replace(setting, value)
        self._parse()

    def remove(self, key: str, mode: str = "") -> None:
        """Take the setting out (the catalog's default applies again): its line goes when it holds nothing else."""
        setting = self.find(key, mode)
        if setting is None:
            return
        text = self.text
        line_start = text.rfind("\n", 0, setting.start) + 1
        line_end = text.find("\n", setting.end)
        line_end = len(text) if line_end < 0 else line_end + 1
        before = text[line_start:setting.start]
        rest = masked_same_length(text[setting.end:line_end])
        if not before.strip() and not rest.strip():
            self.text = text[:line_start] + text[line_end:]
        else:
            self.text = text[:setting.start] + text[setting.end:]
        self._drop_empty_block()
        self._parse()

    def _replace(self, setting: Setting, value: str) -> None:
        text = self.text
        if setting.kind == "header":
            new = value.strip()
        elif setting.kind in ("colour", "modecolour"):
            hex_value = _hex_value(value)
            if hex_value is None:
                if setting.kind == "modecolour":
                    raise ValueError(f"a mode's colour needs a #rrggbb value, not {value!r}")
                # \definecolor -> \colorlet: the command changes, its comment stays
                self.text = text[:setting.start] + f"\\colorlet{{{setting.key}}}{{{value.strip()}}}" + text[setting.end:]
                return
            old = setting.value.strip()
            if setting.model == "HTML" and old.lower() == hex_value.lower():
                return
            # keep the file's way of writing hex digits: upper case when the old value was
            hex_value = hex_value.upper() if setting.model == "HTML" and old == old.upper() and old != old.lower() \
                else hex_value.lower()
            args = text[setting.value_start:setting.value_end]
            _, model_end = braced_argument(args, 0)
            between = args[model_end:args.find("{", model_end)]
            self.text = (text[:setting.value_start] + "{HTML}" + between + "{" + hex_value + "}"
                         + text[setting.value_end:])
            return
        elif setting.kind == "colorlet":
            hex_value = _hex_value(value)
            if hex_value is not None:
                self.text = text[:setting.start] + f"\\definecolor{{{setting.key}}}{{HTML}}{{{hex_value}}}" + text[setting.end:]
                return
            new = value.strip()
        else:
            new = value
        if text[setting.value_start:setting.value_end] != new:
            self.text = text[:setting.value_start] + new + text[setting.value_end:]

    def _line_for(self, key: str, value: str, mode: str) -> str:
        field = theme_fields.BY_NAME.get(key)
        if key in _HEADER_LINES:
            return _HEADER_LINES[key].format(value.strip())
        if key.startswith("mode:"):
            return f"\\SMDeclareMode{{{key[5:]}}}{{{value}}}"
        if key.startswith("role:"):
            if not mode:
                raise ValueError(f"{key} is written per mode: give the mode")
            return f"\\SMSetRole{{{key[5:]}}}{{{mode}}}{{{value}}}"
        if key == "SMLayoutProfile":
            return f"\\newcommand{{\\SMLayoutProfile}}{{{value}}}"
        if key in theme_fields.COMMANDS:
            return f"\\{key}{{{value}}}"
        if (field.kind == "colour") if field else (not key.startswith("SM") or key.endswith("Color")):
            hex_value = _hex_value(value)
            if mode:
                if hex_value is None:
                    raise ValueError(f"a mode's colour needs a #rrggbb value, not {value!r}")
                return f"\\SMSetColor{{{key}}}{{{mode}}}{{HTML}}{{{hex_value}}}"
            if hex_value is None:
                return f"\\colorlet{{{key}}}{{{value.strip()}}}"
            return f"\\definecolor{{{key}}}{{HTML}}{{{hex_value}}}"
        if mode:
            raise ValueError(f"{key} has no value per mode")
        if field and field.kind == "length" and key not in MACRO_LENGTHS:
            return f"\\setlength{{\\{key}}}{{{value}}}"
        args = f"[{field.args}]" if field and field.args else ""
        return f"\\renewcommand{{\\{key}}}{args}{{{value}}}"

    def _add(self, key: str, value: str, mode: str) -> None:
        line = self._line_for(key, value, mode)
        nl = self.newline
        text = self.text
        if key in _HEADER_LINES:
            lines = text.split(nl)
            at = 0
            while at < len(lines) and re.match(r"%+\s*(SPDX-|SlideMage (template name|modes):)", lines[at]):
                at += 1
            self.text = nl.join(lines[:at] + [line] + lines[at:])
            return
        if key == "SMLayoutProfile":
            if self._setup_pos < 0:
                raise ValueError("the theme has no \\input{SlideMage_setup}")
            self._insert_line_before(self._setup_pos, line)
            return
        if key.startswith(("mode:", "role:")) or mode:
            kinds = ("mode",) if key.startswith("mode:") else ("mode", "role", "modecolour")
            anchors = [s for s in self.settings if s.kind in kinds and s.editable]
            if anchors:
                self._insert_line_after(anchors[-1].end, line)
                return
        self._add_to_block(line)

    def _insert_line_before(self, pos: int, line: str) -> None:
        start = self.text.rfind("\n", 0, pos) + 1
        self.text = self.text[:start] + line + self.newline + self.text[start:]

    def _insert_line_after(self, pos: int, line: str) -> None:
        end = self.text.find("\n", pos)
        if end < 0:
            self.text = self.text + self.newline + line
        else:
            self.text = self.text[:end + 1] + line + self.newline + self.text[end + 1:]

    def _add_to_block(self, line: str) -> None:
        nl = self.newline
        lines = self.text.split(nl)
        begin = next((i for i, text in enumerate(lines) if text.strip() == BLOCK_BEGIN), -1)
        end = next((i for i, text in enumerate(lines) if text.strip() == BLOCK_END and i > begin), -1)
        if begin < 0 or end < 0:
            if self._base_pos < 0:
                raise ValueError("the theme has no \\input{SlideMage_base}")
            base_line = self.text.count("\n", 0, self._base_pos)
            lines[base_line:base_line] = [BLOCK_BEGIN, line, BLOCK_END, ""]
            self.text = nl.join(lines)
            return
        rank = _rank(line)
        at = end
        for i in range(begin + 1, end):
            if _rank(lines[i]) > rank:
                at = i
                break
        lines[at:at] = [line]
        self.text = nl.join(lines)

    def _drop_empty_block(self) -> None:
        nl = self.newline
        lines = self.text.split(nl)
        for i in range(len(lines) - 1):
            if lines[i].strip() == BLOCK_BEGIN and lines[i + 1].strip() == BLOCK_END:
                drop = 3 if i + 2 < len(lines) and not lines[i + 2].strip() else 2
                del lines[i:i + drop]
                self.text = nl.join(lines)
                return


# Hooks that are macros although they hold a length (the catalog defines them with \newcommand; a test checks this).
MACRO_LENGTHS = frozenset({"SMTopMargin", "SMFootlineSidePadding", "SMSectionframeTitleGap", "SMLabelItemGap",
                           "SMEnumerateNestedSlotExtra", "SMEnumerateNestedLabelGap", "SMBesideFigureTopGap"})
_KEY_RE = re.compile(r"\\(?:setlength|renewcommand|definecolor|colorlet)\s*\{\\?([A-Za-z_][A-Za-z0-9_]*)\}"
                     r"|\\(" + _COMMANDS + r")\{")


def _rank(line: str) -> int:
    """Where a line of the marked block sorts: the catalog's order, then the mode declarations, then the mode lines
    (a \\SMSetRole for the base mode needs the declaration before it)."""
    if "\\SMDeclareMode" in line:
        return len(theme_fields.FIELDS)
    if "\\SMSetRole" in line or "\\SMSetColor" in line:
        return len(theme_fields.FIELDS) + 1
    match = _KEY_RE.search(line)
    return theme_fields.order(match.group(1) or match.group(2)) if match else -1


def _skip_space(text: str, pos: int) -> int:
    while pos < len(text) and text[pos] in " \t":
        pos += 1
    return pos


def _nth_line_start(text: str, count: int) -> int:
    pos = 0
    for _ in range(count):
        found = text.find("\n", pos)
        if found < 0:
            return len(text)
        pos = found + 1
    return pos
