# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Source hover lookup and the LaTeX help catalogues."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from slidemage import latex_help_standard, themes
from slidemage.latex_help import COMMANDS, ENVIRONMENTS, HelpFileError, help_at, help_html, parse_help
from slidemage.tex_source import COMMENT_RE

ROOT = Path(__file__).resolve().parents[1]
LATEX = ROOT / "latex"
QUICK_REFERENCE = [ROOT / "example" / "slides" / "1uw-EN-Quick-Reference-Slide-Commands-current.tex",
                   ROOT / "example" / "slides" / "1d7-EN-Quick-Reference-Deck-Commands-current.tex"]

# A name followed by @ is an internal helper (\SMTable@begin), not the command \SMTable.
_NAME = r"([A-Za-z]+)(?![A-Za-z@])"
_NEW_COMMAND_RE = re.compile(
    r"\\(?:newcommand|NewDocumentCommand|DeclareRobustCommand|providecommand|DeclareDocumentCommand|newlength)\*?"
    r"\s*\{?\\" + _NAME)
_DEF_RE = re.compile(r"\\(?:(?:g|e|x)?def|let|cs_new_protected:Npn|cs_new:Npn)\s*\\" + _NAME)
_NEW_ENV_RE = re.compile(r"\\(?:newenvironment|NewDocumentEnvironment)(?:<>)?\{([A-Za-z*]+)\}")
_NEWIF_RE = re.compile(r"\\newif\\if([A-Za-z]+)")


def test_framework_and_quick_reference_agree_with_help():
    files = sorted(LATEX.glob("*.tex")) + sorted(LATEX.glob("*.sty"))
    text = "\n".join(path.read_text(encoding="utf-8", errors="replace") for path in files)
    text = COMMENT_RE.sub("", text)
    commands = set(_NEW_COMMAND_RE.findall(text)) | set(_DEF_RE.findall(text))
    for name in _NEWIF_RE.findall(text):
        commands |= {f"if{name}", f"{name}true", f"{name}false"}
    environments = set(_NEW_ENV_RE.findall(text))
    # Aliased environments have both begin and end commands.
    lets = set(re.findall(r"\\let\\([A-Za-z]+)\\", text))
    let_environments = {name for name in lets if "end" + name in lets}
    environments |= let_environments
    commands -= let_environments | {"end" + name for name in let_environments}
    assert sorted(set(COMMANDS) - commands) == []
    assert sorted(set(ENVIRONMENTS) - environments) == []

    named = set()
    for path in QUICK_REFERENCE:
        text = path.read_text(encoding="utf-8")
        named |= set(re.findall(r"\\SMCmd\{([A-Za-z]+)\}", text))
        named |= set(re.findall(r"\\SMCode\{(?:\\textbackslash\s*)?([A-Za-z]+)", text))
    missing = sorted(name for name in named
                     if (name in commands and name not in COMMANDS)
                     or (name in environments and name not in ENVIRONMENTS and name not in COMMANDS))
    # \input is the TeX primitive; the framework only wraps it to find its files.
    assert [name for name in missing if name != "input"] == []


@pytest.mark.parametrize("family, names", [
    ("SMCorner", ["cornerfigure", "besidefigure"]),
    ("SMFit", ["fitfigure"]),
    ("SMFloatingBlock", ["SMFloatingBlock", "SMFloatingExampleBlock", "SMFloatingInfoBlock"]),
    ("SMTable", ["SMTable"]),
    ("SMTextBox", ["SMTextBox"]),
])
def test_the_keys_match_the_commands_pgfkeys(family, names):
    text = (LATEX / "SlideMage_base.tex").read_text(encoding="utf-8", errors="replace")
    block = re.search(r"\\pgfqkeys\{/" + family + r"\}\{(.*?)\n\}", text, re.DOTALL).group(1)
    framework = set(re.findall(r"^\s*([A-Za-z]+)/\.", block, re.MULTILINE))
    for name in names:
        help_ = COMMANDS.get(name) or ENVIRONMENTS[name]
        keys = {key.name for key in help_.keys}
        # gap is \besidefigure's distance from the text, stored in the same family; \cornerfigure has no text.
        expected = framework - {"gap"} if name == "cornerfigure" else framework
        assert keys == expected, name


LINE = r"\cornerfigure[height=5.6cm, corner=se, border]{media/chart-x.png}"


def test_help_identifies_the_command_and_option_spans():
    hit = help_at(LINE, 1)
    assert hit.help.name == "cornerfigure" and hit.key is None
    assert LINE[hit.start:hit.end] == r"\cornerfigure"
    for word, key in (("height", "height"), ("5.6cm", "height"), ("border", "border")):
        hit = help_at(LINE, LINE.index(word))
        assert hit.help.name == "cornerfigure" and hit.key == key
        assert LINE[hit.start:hit.end].split("=")[0] == key
    for word in ("[", ",", "=", "media"):
        assert help_at(LINE, LINE.index(word)) is None
    for offset in (-1, len(LINE), len(LINE) + 1):
        assert help_at(LINE + "\n", offset) is None


def test_in_a_comment():
    text = "Text % see \\cornerfigure[corner=se]"
    assert help_at(text, text.index("corner")) is None
    assert help_at(text, text.index("se]")) is None
    # an escaped percent sign starts no comment
    text = "50\\% \\cornerfigure{x}"
    assert help_at(text, text.index("corner")).help.name == "cornerfigure"


def test_unknown_commands_and_plain_text():
    text = "\\mycmd{bold} plain \\unknowncommand[width=3cm]"
    assert help_at(text, 2) is None
    assert help_at(text, text.index("plain")) is None
    assert help_at(text, text.index("width")) is None
    text = r"\cornerfigure{x} \[ a, height \]"
    assert help_at(text, text.index("height")) is None
    text = r"\titleframe{A}{B\\Summer term}"
    assert help_at(text, text.index("Summer")) is None


def test_environment_name_in_begin_and_end():
    text = "\\begin{besidefigure}[gap=8pt]{x.png}\n\tText\n\\end{besidefigure}"
    for offset in (1, text.index("besidefigure"), text.rindex("besidefigure") + 3):
        assert help_at(text, offset).help.name == "besidefigure"
    hit = help_at(text, text.index("gap"))
    assert hit.help.name == "besidefigure" and hit.key == "gap"
    assert help_at("\\begin{myenv}", 3) is None


def test_options_over_several_lines_and_with_braced_values():
    text = "\\cornerfigure[\n\theight=4cm,\n\tnode={rotate=5, anchor=west},\n\tcorner=sw]{x}"
    assert help_at(text, text.index("height")).key == "height"
    assert help_at(text, text.index("node")).key == "node"
    assert help_at(text, text.index("corner=sw")).key == "corner"
    assert help_at(text, text.index("rotate")) is None         # inside node={...}: TikZ's keys, not ours


def test_options_after_earlier_arguments():
    text = "\\slidestep{egk-EN-Overview}[instructor,after-course]{1,2}"
    assert help_at(text, text.index("after-course")).key == "after-course"
    text = "\\deckonly<3>[during-course]{\\item x}"
    assert help_at(text, text.index("during")).key == "during-course"
    text = "\\begin{SMTable}[gap=12pt]{lccc}"
    assert help_at(text, text.index("12pt")).key == "gap"
    text = r"\deckreveal*[3]{x}"
    hit = help_at(text, 3)
    assert hit.help.name == "deckreveal" and text[hit.start:hit.end] == r"\deckreveal*"
    assert help_at(text, text.index("3")) is None


def test_nested_floating_block_options():
    text = "\\cornerfigure[block]{\\begin{SMFloatingInfoBlock}[top=0pt]{6cm}{Note} x \\end{SMFloatingInfoBlock}}"
    hit = help_at(text, text.index("top"))
    assert hit.help.name == "SMFloatingInfoBlock" and hit.key == "top"
    assert help_at(text, text.index("block]")).help.name == "cornerfigure"


def test_help_html_lists_the_keys_and_bolds_the_hovered_one():
    hit = help_at(LINE, LINE.index("se"))
    page = help_html(hit)
    assert "\\cornerfigure[keys]{image file or content}" in page
    bold = re.findall(r"<b>.*?</b>", page)
    assert any(">corner</span>" in part for part in bold)
    assert "width</span>" in page and all(">width</span>" not in part for part in bold)
    assert "\\deckitem&lt;step-&gt;" in help_html(help_at(r"\deckitem<3->", 2))


def test_help_html_of_a_version_list_says_values():
    text = "\\conditionalpause[instructor]"
    page = help_html(help_at(text, text.index("instructor")))
    assert "Values:" in page and "Keys:" not in page


def test_catalogue_entries_are_complete_and_standard_names_do_not_overlap():
    standard = [*latex_help_standard.COMMANDS.values(), *latex_help_standard.ENVIRONMENTS.values()]
    framework = [*COMMANDS.values(), *ENVIRONMENTS.values()]
    for entry in [*standard, *framework]:
        assert entry.signature and entry.summary, entry.name
        assert len({key.name for key in entry.keys}) == len(entry.keys), entry.name
    for entry in framework:
        assert f"\\{entry.name}" in entry.signature or f"{{{entry.name}}}" in entry.signature
    assert len(latex_help_standard.COMMANDS) >= 50 and len(latex_help_standard.ENVIRONMENTS) >= 15
    assert all(entry.example for entry in standard)
    assert not set(latex_help_standard.COMMANDS) & set(COMMANDS)
    assert not set(latex_help_standard.ENVIRONMENTS) & set(ENVIRONMENTS)


def test_standard_latex_beamer_and_math_help_shows_on_hover():
    for text, word, name, key in (
        (r"\includegraphics[keepaspectratio, width=3cm]{x}", "3cm", "includegraphics", "width"),
        (r"\begin{frame}[fragile,t]{Title}", "fragile", "frame", "fragile"),
        (r"x = \frac{a}{b}", "frac", "frac", None),
    ):
        hit = help_at(text, text.index(word))
        assert (hit.help.name, hit.key) == (name, key)
        assert "<qt>" in help_html(hit)


THEME_HELP = r'''
[[command]]
name = "mytitle"
signature = "\\mytitle[keys]{text}"
summary = "The theme's big title."
[[command.keys]]
name = "color"
values = "red | blue"
text = "the title color"

[[environment]]
name = "mybox"
signature = "\\begin{mybox} ... \\end{mybox}"
summary = "A theme box."

[[command]]
name = "cornerfigure"
signature = "\\cornerfigure"
summary = "A theme must not redefine this."
'''


def test_a_themes_help_shows_but_slidemages_entries_win():
    extra = parse_help(THEME_HELP)
    text = "\\mytitle[color=red]{x} \\cornerfigure{y}\n\\begin{mybox}"
    assert help_at(text, 2) is None                              # without the theme: nothing
    hit = help_at(text, 2, extra)
    assert hit.help.summary == "The theme's big title."
    assert help_at(text, text.index("color"), extra).key == "color"
    assert help_at(text, text.index("mybox"), extra).help.environment
    assert "Palan" not in help_html(hit)
    assert help_at(text, text.index("cornerfigure") + 2, extra).help is COMMANDS["cornerfigure"]


@pytest.mark.parametrize("broken", [
    "[[command]]\nname = 'x'\nsummary = 's'\n",                      # no signature
    "[[command]]\nname = '\\x'\nsignature = 's'\nsummary = 's'\n",   # a backslash in the name
    "[[command]]\nname = 'x'\nsignature = 's'\nsummary = 's'\n[[command]]\nname = 'x'\nsignature = 's'\nsummary = 's'\n",
    "[other]\na = 1\n",
    "not toml [",
])
def test_a_broken_help_file_is_refused_strictly_and_skipped_leniently(broken):
    with pytest.raises(HelpFileError):
        parse_help(broken)
    parse_help(broken, strict=False)         # does not raise


def test_lenient_parsing_keeps_the_good_entries():
    good = parse_help(THEME_HELP + "\n[[command]]\nname = 'bad'\n", strict=False)
    assert set(good.commands) == {"mytitle", "cornerfigure"} and set(good.environments) == {"mybox"}


def test_themes_help_of_and_check_folder(tmp_path):
    folder = tmp_path / "t"
    folder.mkdir()
    assert themes.help_of(folder).commands == {}
    (folder / "help.toml").write_text(THEME_HELP, encoding="utf-8")
    assert "mytitle" in themes.help_of(folder).commands
    assert "help.toml" in themes.OPTIONAL_FILES
