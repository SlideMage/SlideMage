# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The help catalogue for the Source view's hover tooltips (latex_help.py, docs/plans/latex-hover-help.md): it stays
in step with latex/, and help_at() finds the command or key under the pointer."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from slidemage import latex_help
from slidemage.latex_help import COMMANDS, ENVIRONMENTS, help_at, help_html
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


def _framework_text() -> str:
    files = sorted(LATEX.glob("*.tex")) + sorted(LATEX.glob("*.sty"))
    text = "\n".join(path.read_text(encoding="utf-8", errors="replace") for path in files)
    return COMMENT_RE.sub("", text)        # a definition quoted in a comment defines nothing


@pytest.fixture(scope="module")
def defined() -> tuple[set[str], set[str]]:
    """The commands and the environments that latex/ defines (not those it only redefines)."""
    text = _framework_text()
    commands = set(_NEW_COMMAND_RE.findall(text)) | set(_DEF_RE.findall(text))
    for name in _NEWIF_RE.findall(text):
        commands |= {f"if{name}", f"{name}true", f"{name}false"}
    return commands, set(_NEW_ENV_RE.findall(text))


def test_every_entry_is_defined_in_the_framework(defined):
    commands, environments = defined
    assert sorted(set(COMMANDS) - commands) == []
    assert sorted(set(ENVIRONMENTS) - environments) == []


def test_every_command_of_the_quick_reference_slides_has_help(defined):
    """The Quick Reference slides list what a user writes ("Anything else is internal"); each of those that the
    framework defines needs an entry. Beamer's own commands (\\hyperlink, \\footnote, ...) are not checked."""
    commands, environments = defined
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


def test_every_entry_is_complete():
    for help_ in [*COMMANDS.values(), *ENVIRONMENTS.values()]:
        assert help_.signature and help_.summary, help_.name
        assert (f"\\{help_.name}" in help_.signature) or (f"{{{help_.name}}}" in help_.signature), help_.name
        assert len({key.name for key in help_.keys}) == len(help_.keys), help_.name


# -- help_at ----------------------------------------------------------------------------------------

LINE = r"\cornerfigure[height=5.6cm, corner=se, border]{media/chart-x.png}"


@pytest.mark.parametrize("offset", [0, 1, len(r"\cornerfig"), len(r"\cornerfigure") - 1])
def test_on_the_command_name(offset):
    hit = help_at(LINE, offset)
    assert hit.help.name == "cornerfigure" and hit.key is None
    assert (hit.start, hit.end) == (0, len(r"\cornerfigure"))


@pytest.mark.parametrize("word, key", [("height", "height"), ("5.6cm", "height"), ("corner", "corner"),
                                       ("se", "corner"), ("border", "border")])
def test_on_a_key_or_its_value(word, key):
    hit = help_at(LINE, LINE.index(word, len("\\cornerfigure")) + 1)
    assert hit.help.name == "cornerfigure" and hit.key == key
    assert LINE[hit.start:hit.end].split("=")[0] == key


@pytest.mark.parametrize("word", ["[", ",", "=", "media", "{"])
def test_not_on_brackets_separators_or_the_argument(word):
    assert help_at(LINE, LINE.index(word, len("\\cornerfigure"))) is None


def test_past_the_end_of_the_line_and_out_of_range():
    text = LINE + "\n"
    assert help_at(text, len(LINE)) is None
    assert help_at(text, len(text)) is None
    assert help_at(text, -1) is None


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


def test_a_line_break_before_a_word_is_no_command():
    text = "\\titleframe{A}{B\\\\Summer term}"
    assert help_at(text, text.index("Summer")) is None
    assert help_at(text, 3).help.name == "titleframe"


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
    text = "\\deckreveal*[3]{x}"
    assert help_at(text, text.index("3")) is None              # a step number, not a key


def test_display_math_brackets_are_not_options():
    text = "\\cornerfigure{x} \\[ a, height \\]"
    assert help_at(text, text.index("height")) is None


def test_nested_floating_block_options():
    text = "\\cornerfigure[block]{\\begin{SMFloatingInfoBlock}[top=0pt]{6cm}{Note} x \\end{SMFloatingInfoBlock}}"
    hit = help_at(text, text.index("top"))
    assert hit.help.name == "SMFloatingInfoBlock" and hit.key == "top"
    assert help_at(text, text.index("block]")).help.name == "cornerfigure"


def test_starred_command_name():
    text = "\\deckreveal*[2]{x}"
    hit = help_at(text, 3)
    assert hit.help.name == "deckreveal" and text[hit.start:hit.end] == "\\deckreveal*"


# -- the tooltip ----------------------------------------------------------------------------------

def test_help_html_lists_the_keys_and_bolds_the_hovered_one():
    hit = help_at(LINE, LINE.index("se"))
    page = help_html(hit, "Roboto Mono")
    assert page.startswith("<qt>") and page.endswith("</qt>")
    assert "\\cornerfigure[keys]{image file or content}" in page
    assert "Roboto Mono" in page and "Keys:" in page and "Example:" in page
    mono = "<span style=\"font-family: 'Roboto Mono', monospace;\">"
    assert f"<b>{mono}corner</span></b>" in page
    assert f"<b>{mono}=ne | nw | se | sw | e | w</span>&nbsp; which corner" in page
    assert f"<b>{mono}width" not in page and f"{mono}width</span>" in page


def test_help_html_of_a_version_list_says_values():
    text = "\\conditionalpause[instructor]"
    page = help_html(help_at(text, text.index("instructor")))
    assert "Values:" in page and "Keys:" not in page


def test_help_html_escapes():
    page = help_html(help_at("\\SMCode{x}", 2))
    assert "<qt>" in page and "&lt;" not in page.split("</p>")[0]          # the signature has no markup
    page = help_html(help_at("\\deckitem<3->", 2))
    assert "\\deckitem&lt;step-&gt;" in page


def test_setting_key():
    assert latex_help.HOVER_HELP_SETTING_KEY == "latex_hover_help"


# -- standard LaTeX/beamer/math help and a theme's help.toml ----------------------------------------------------

from slidemage import latex_help_standard, themes  # noqa: E402
from slidemage.latex_help import HelpFileError, parse_help  # noqa: E402


def test_the_standard_catalogue_is_complete_and_apart_from_slidemages():
    standard = [*latex_help_standard.COMMANDS.values(), *latex_help_standard.ENVIRONMENTS.values()]
    assert len(latex_help_standard.COMMANDS) >= 50 and len(latex_help_standard.ENVIRONMENTS) >= 15
    for help_ in standard:
        assert help_.signature and help_.summary and help_.example, help_.name
        assert len({key.name for key in help_.keys}) == len(help_.keys), help_.name
    assert not set(latex_help_standard.COMMANDS) & set(COMMANDS)
    assert not set(latex_help_standard.ENVIRONMENTS) & set(ENVIRONMENTS)


@pytest.mark.parametrize("text, word, name", [
    (r"\includegraphics[width=3cm]{x}", "include", "includegraphics"),
    (r"\pause", "pause", "pause"),
    (r"\only<2>{x}", "only", "only"),
    (r"x = \frac{a}{b}", "frac", "frac"),
    (r"\begin{frame}[plain]", "frame", "frame"),
    (r"\begin{pmatrix} 1 \end{pmatrix}", "pmatrix", "pmatrix"),
])
def test_standard_commands_show_on_hover(text, word, name):
    hit = help_at(text, text.index(word) + 1)
    assert hit is not None and hit.help.name == name and "<qt>" in help_html(hit)


def test_keys_of_standard_commands():
    text = r"\includegraphics[keepaspectratio, width=3cm]{x}"
    hit = help_at(text, text.index("keepaspectratio"))
    assert (hit.help.name, hit.key) == ("includegraphics", "keepaspectratio")
    assert help_at(text, text.index("3cm")).key == "width"
    text = r"\begin{frame}[fragile,t]{Title}"
    assert help_at(text, text.index("fragile")).key == "fragile"


THEME_HELP = r'''
[[command]]
name = "mytitle"
signature = "\\mytitle[keys]{text}"
summary = "The theme's big title."
example = "\\mytitle[color=red]{Hi}"

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
