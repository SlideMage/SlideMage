# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Reading a theme setting by setting and changing one in place (theme_file.ThemeFile; docs/plans/theme-editor.md,
section 3.1, stage C1a). The acceptance tests of the plan, on every theme shape we have: (1) setting every value to
itself leaves the file byte for byte, (2) a changed palette colour changes exactly one line, (3) a mode's line changes or
is added after the theme's mode lines, nothing else moves, (4) a setting the theme lacks lands in the marked block before
\\input{SlideMage_base}, in the catalog's order, (5) the colours read equal what theme_colors reads for the same file.

The shapes: the two shipped templates, the stress-test template (every hook), the test theme package, and two test themes with the shapes of
real institution themes (tests/fixtures/theme_files/: mode lines and own colours; a conditional and \\colorlet). The
institution themes themselves are not in this repository (their corporate design must not be published); to run the
same tests on them, name their files in SLIDEMAGE_REAL_THEMES (separated by os.pathsep)."""
import difflib
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from slidemage import theme_colors, theme_fields
from slidemage.theme_file import BLOCK_BEGIN, BLOCK_END, ThemeFile

ROOT = Path(__file__).resolve().parents[1]
LATEX = ROOT / "latex"
FIXTURES = ROOT / "tests" / "fixtures" / "theme_files"
MODESHAPE = FIXTURES / "SlideMage_template_modeshape.tex"
CONDSHAPE = FIXTURES / "SlideMage_template_condshape.tex"
THEMES = [LATEX / "SlideMage_template_slidemage.tex", LATEX / "SlideMage_template_greyscale.tex",
          ROOT / "tests" / "fixtures" / "template_stress" / "SlideMage_template_stress-test.tex", MODESHAPE, CONDSHAPE,
          # the shape of an installed theme package: a layout profile before the setup file, an \input after the base
          ROOT / "tests" / "fixtures" / "theme_package" / "sample-theme" / "SlideMage_template_sample-theme.tex"]
THEMES += [Path(p) for p in os.environ.get("SLIDEMAGE_REAL_THEMES", "").split(os.pathsep) if p.strip()]


def read(path: Path) -> str:
    """The file with "\\n" line ends (a Windows checkout has "\\r\\n"; test_windows_line_ends_stay covers those)."""
    return path.read_bytes().decode("utf-8").replace("\r\n", "\n")


def changed_lines(old: str, new: str) -> list[tuple[str, list[str], list[str]]]:
    """(opcode, old lines, new lines) for every place the two texts differ."""
    a, b = old.split("\n"), new.split("\n")
    return [(tag, a[i1:i2], b[j1:j2]) for tag, i1, i2, j1, j2
            in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes() if tag != "equal"]


@pytest.fixture(params=THEMES, ids=lambda p: p.name)
def theme(request) -> Path:
    if not request.param.is_file():
        pytest.skip(f"{request.param} is not here")
    return request.param


# --- (1) round trip --------------------------------------------------------------------------------------------------

def test_reading_and_writing_every_value_back_changes_nothing(theme):
    text = read(theme)
    edited = ThemeFile(text)
    assert edited.text == text
    count = 0
    for setting in list(edited.settings):
        if setting.editable:
            edited.set(setting.key, edited.value(setting.key, setting.mode), setting.mode)
            count += 1
    assert edited.text == text
    assert count >= 3          # the test theme package sets five


# --- (2) one palette colour, one line --------------------------------------------------------------------------------

def test_a_changed_palette_colour_changes_exactly_that_line(theme):
    text = read(theme)
    edited = ThemeFile(text)
    before = edited.find("c_primary_highlight")
    edited.set("c_primary_highlight", "#123abc")
    changes = changed_lines(text, edited.text)
    if before is None:          # the shipped SlideMage template keeps the catalog's: added in the block
        assert [tag for tag, _, _ in changes] == ["insert"]
        assert BLOCK_BEGIN in edited.text
    else:
        assert len(changes) == 1 and changes[0][0] == "replace"
        (old_line,), (new_line,) = changes[0][1], changes[0][2]
        assert "123abc" in new_line.lower()
        # the trailing comment stays
        assert old_line.partition("%")[2] == new_line.partition("%")[2]
    assert edited.value("c_primary_highlight") == "#123abc"


def test_upper_case_hex_stays_upper_case():
    edited = ThemeFile(read(MODESHAPE))
    edited.set("c_primary_white", "#fefefe")
    assert "\\definecolor{c_primary_white}{HTML}{FEFEFE}" in edited.text
    edited.set("c_primary_dark", "#ABCDEF")
    assert "\\definecolor{c_primary_dark}{HTML}{abcdef}" in edited.text


def test_a_colour_moves_between_definecolor_and_colorlet_keeping_its_comment():
    text = read(CONDSHAPE)
    edited = ThemeFile(text)
    edited.set("c_tertiary_blue", "c_secondary_blue!50")
    assert "\\colorlet{c_tertiary_blue}{c_secondary_blue!50} % derived (50% white-blend" in edited.text
    assert edited.value("c_tertiary_blue") == "c_secondary_blue!50"
    edited.set("c_tertiary_blue", "#8099B0")
    assert edited.text == text
    edited.set("SMCodeKeywordColor", "#112233")
    assert "  \\definecolor{SMCodeKeywordColor}{HTML}{112233}   % indented on purpose" in edited.text


# --- (3) colour modes ------------------------------------------------------------------------------------------------

def test_a_modes_line_changes_in_place():
    text = read(MODESHAPE)
    edited = ThemeFile(text)
    assert edited.modes() == [("light", ""), ("dark", "dark")]
    edited.set("role:canvas", "c_primary_dark", "dark")
    edited.set("c_custom_red", "#ff7070", "dark")
    changes = changed_lines(text, edited.text)
    assert [new for _, _, new in changes] == [["\\SMSetRole{canvas}{dark}{c_primary_dark}"],
                                              ["\\SMSetColor{c_custom_red}{dark}{HTML}{FF7070}   % 5.1:1; also the markers"]]
    assert edited.value("c_custom_red", "dark") == "#ff7070"
    assert edited.value("c_custom_red") == "#b00000"          # the base mode's value is another setting


def test_a_new_modes_line_goes_after_the_last_mode_line_and_nothing_else_moves():
    text = read(MODESHAPE)
    edited = ThemeFile(text)
    edited.set("role:title_fill", "c_test_dark_canvas", "dark")
    edited.set("c_custom_brown", "#d09a5c", "dark")
    edited.set("mode:grey", "grey")
    changes = changed_lines(text, edited.text)
    assert all(tag == "insert" for tag, _, _ in changes)
    lines = edited.text.split("\n")
    last = lines.index("\\SMSetRole{standout_text}{dark}{c_primary_highlight}")
    assert lines[last + 1:last + 3] == ["\\SMSetRole{title_fill}{dark}{c_test_dark_canvas}",
                                        "\\SMSetColor{c_custom_brown}{dark}{HTML}{d09a5c}"]
    assert lines[lines.index("\\SMDeclareMode{dark}{dark}") + 1] == "\\SMDeclareMode{grey}{grey}"
    assert edited.modes() == [("light", ""), ("dark", "dark"), ("grey", "grey")]


def test_a_theme_without_modes_gets_them_in_the_block_declarations_first():
    edited = ThemeFile(read(CONDSHAPE))
    edited.set("role:canvas", "c_primary_dark", "dark")
    edited.set("mode:dark", "dark")
    edited.set("mode:light", "")
    block = edited.text.split(BLOCK_BEGIN)[1].split(BLOCK_END)[0].strip().split("\n")
    assert block == ["\\SMDeclareMode{dark}{dark}", "\\SMDeclareMode{light}{}", "\\SMSetRole{canvas}{dark}{c_primary_dark}"]


def test_a_modes_colour_takes_a_hex_value_and_a_role_takes_a_mode():
    edited = ThemeFile(read(MODESHAPE))
    with pytest.raises(ValueError):
        edited.set("c_custom_red", "c_primary_dark!50", "dark")
    with pytest.raises(ValueError):
        edited.set("role:title_fill", "c_primary_dark")
    with pytest.raises(ValueError):
        edited.set("SMLogoHeight", "4ex", "dark")


# --- (4) settings the theme does not have ----------------------------------------------------------------------------

def test_added_settings_land_in_the_marked_block_in_catalog_order(theme):
    text = read(theme)
    edited = ThemeFile(text)
    if edited.find("SMBodyFontSize") or edited.find("SMTopMargin") or BLOCK_BEGIN in text:
        pytest.skip("the theme sets these already")
    edited.set("SMBodyFontSize", "10pt")
    edited.set("SMTopMargin", "45bp")
    assert all(tag == "insert" for tag, _, _ in changed_lines(text, edited.text))
    lines = edited.text.split("\n")
    begin = lines.index(BLOCK_BEGIN)
    assert lines[begin:begin + 5] == [BLOCK_BEGIN, "\\renewcommand{\\SMTopMargin}{45bp}",
                                      "\\setlength{\\SMBodyFontSize}{10pt}", BLOCK_END, ""]
    assert lines[begin + 5].startswith("\\input{SlideMage_base}")
    assert edited.value("SMTopMargin") == "45bp"
    edited.remove("SMTopMargin")
    edited.remove("SMBodyFontSize")
    assert edited.text == text


def test_a_conditional_setting_is_kept_and_counted_as_beyond_the_form():
    text = read(CONDSHAPE)
    edited = ThemeFile(text)
    conditional = [s for s in edited.settings if s.key == "SMInfoBlockTitleTextColor"]
    assert len(conditional) == 1 and conditional[0].conditional and not conditional[0].editable
    assert edited.find("SMInfoBlockTitleTextColor") is None
    lines = text.split("\n")
    assert [lines[n].strip() for n in edited.beyond()] == [
        "\\ifdefined\\SMInfoBlockTitleTextColor", "\\renewcommand{\\SMInfoBlockTitleTextColor}{c_primary_white}",
        "\\fi", "\\input{SlideMage_project_macros}"]
    edited.set("SMInfoBlockTitleTextColor", "c_primary_dark")
    assert "  \\renewcommand{\\SMInfoBlockTitleTextColor}{c_primary_white}" in edited.text
    assert all(tag == "insert" for tag, _, _ in changed_lines(text, edited.text))


def test_what_lies_beyond_the_form():
    assert ThemeFile(read(LATEX / "SlideMage_template_greyscale.tex")).beyond() == []
    shape = ThemeFile(read(MODESHAPE))
    assert [shape.text.split("\n")[n] for n in shape.beyond()] == ["\\input{SlideMage_bibliography_default}"]
    assert shape.own_colours() == ["c_test_dark_canvas", "c_test_dark_card"]
    assert shape.value("SMSetFootnoteMarkers") == "boxed"


def test_a_setting_inside_another_commands_argument_is_not_the_themes():
    text = ("\\input{SlideMage_setup}\n\\newcommand{\\MyDark}{\\colorlet{c_primary_dark}{black}}\n"
            "\\input{SlideMage_base}\n")
    edited = ThemeFile(text)
    assert edited.settings == [] and edited.beyond() == [1]


def test_headers_and_the_layout_profile():
    text = read(LATEX / "SlideMage_template_slidemage.tex")
    edited = ThemeFile(text)
    assert edited.value("header:name") is None and edited.value("header:modes") == "light, dark=Dark slides"
    edited.set("header:name", "My look")
    edited.set("SMLayoutProfile", "lmsans")
    lines = edited.text.split("\n")
    assert lines[3] == "% SlideMage template name: My look"          # after the SPDX and modes lines
    assert lines[lines.index("\\input{SlideMage_setup}") - 1] == "\\newcommand{\\SMLayoutProfile}{lmsans}"
    assert all(tag == "insert" for tag, _, _ in changed_lines(text, edited.text))
    grey = ThemeFile(read(LATEX / "SlideMage_template_greyscale.tex"))
    grey.set("SMLayoutProfile", "fira")
    grey.set("header:name", "Greys")
    assert [new for _, _, new in changed_lines(read(LATEX / "SlideMage_template_greyscale.tex"), grey.text)] == [
        ["% SlideMage template name: Greys"], ["\\newcommand{\\SMLayoutProfile}{fira}"]]


def test_macros_with_arguments_and_nested_braces():
    text = read(LATEX / "SlideMage_template_greyscale.tex")
    edited = ThemeFile(text)
    assert edited.value("SMBulletSymbol") == "\\textcolor{#1}{\\textendash}"
    assert edited.value("SMFootnoteMark") == "\\number#1"
    edited.set("SMFootnoteMark", "(\\number#1)")
    assert "\\renewcommand{\\SMFootnoteMark}[1]{(\\number#1)}" in edited.text
    shipped = ThemeFile(read(LATEX / "SlideMage_template_slidemage.tex"))
    shipped.set("SMBulletSymbol", "\\textcolor{#1}{\\textbullet}")
    assert "\\renewcommand{\\SMBulletSymbol}[1]{\\textcolor{#1}{\\textbullet}}" in shipped.text


def test_windows_line_ends_stay(theme):
    text = read(theme).replace("\n", "\r\n")
    edited = ThemeFile(text)
    for setting in list(edited.settings):
        if setting.editable:
            edited.set(setting.key, edited.value(setting.key, setting.mode), setting.mode)
    assert edited.text == text
    edited.set("SMWarningSignPadding", "7pt")
    edited.set("role:alert", "c_secondary_orange", "dark")
    edited.set("c_primary_highlight", "#000001")
    edited.set("header:name", "Line ends")
    assert "\n" not in edited.text.replace("\r\n", "")
    assert edited.value("header:name") == "Line ends"
    edited.remove("SMWarningSignPadding")
    assert "\n" not in edited.text.replace("\r\n", "")


def test_removing_a_setting_drops_its_line():
    text = read(MODESHAPE)
    edited = ThemeFile(text)
    edited.remove("c_custom_brown")
    assert [tag for tag, _, _ in changed_lines(text, edited.text)] == ["delete"]
    assert edited.find("c_custom_brown") is None


# --- (5) the same colours as theme_colors ----------------------------------------------------------------------------

def test_the_colours_read_equal_what_theme_colors_reads(theme, tmp_path):
    shutil.copy(theme, tmp_path / "SlideMage_template_probe.tex")
    edited = ThemeFile(read(theme))
    modes = [mode for mode, _ in edited.modes()] or [""]
    for mode in modes:
        resolved = theme_colors.theme_colors("probe", tmp_path, mode)
        for setting in edited.settings:
            # palette colours (theme_colors reads the optional SM*Color lines of the framework's conditionals too)
            if setting.kind != "colour" or not setting.editable or setting.model != "HTML" or not setting.key.startswith("c_"):
                continue
            overridden = edited.find(setting.key, mode) if mode else None
            expected = edited.value(setting.key, mode) if overridden else edited.value(setting.key)
            assert resolved.get(setting.key) == expected, (theme.name, mode, setting.key)


# --- the edited file still compiles ----------------------------------------------------------------------------------

@pytest.mark.skipif(not os.environ.get("SLIDEMAGE_TEX_TESTS") or not shutil.which("lualatex"),
                    reason="compiles with lualatex: SLIDEMAGE_TEX_TESTS=1")
def test_an_edited_shipped_template_compiles(tmp_path):
    edited = ThemeFile(read(LATEX / "SlideMage_template_slidemage.tex"))
    edited.set("c_primary_highlight", "#aa3300")
    edited.set("SMBodyFontSize", "10pt")
    edited.set("SMTopMargin", "45bp")
    edited.set("role:title_fill", "c_secondary_blue", "dark")
    (tmp_path / "SlideMage_template_edited.tex").write_text(edited.text, encoding="utf-8")
    (tmp_path / "deck.tex").write_text(
        "\\documentclass[aspectratio=169]{beamer}\n\\newcommand{\\SMModeOverride}{dark}\n"
        "\\input{SlideMage_template_edited}\n\\newcommand{\\FooterText}{edited}\n"
        "\\begin{document}\\begin{frame}{T}x\\end{frame}\\end{document}\n",
        encoding="utf-8")
    env = dict(os.environ, TEXINPUTS=os.pathsep.join([str(LATEX), str(tmp_path), ""]))
    subprocess.run(["lualatex", "-interaction=nonstopmode", "-halt-on-error", "deck.tex"], cwd=tmp_path, env=env,
                   capture_output=True, timeout=300)
    log = (tmp_path / "deck.log").read_text(encoding="utf-8", errors="replace")
    assert (tmp_path / "deck.pdf").is_file() and "! " not in log


def test_the_form_reads_every_catalog_kind_from_the_stress_template():
    """The stress-test template sets every hook: each one is an editable setting the form finds."""
    edited = ThemeFile(read(ROOT / "tests" / "fixtures" / "template_stress" / "SlideMage_template_stress-test.tex"))
    setup = (LATEX / "SlideMage_setup.tex").read_text(encoding="utf-8")
    catalog = theme_fields.catalog(setup)
    wanted = [name for name, entry in catalog.items() if entry.kind in ("length", "macro", "colour", "optional_colour")]
    missing = [name for name in wanted if edited.find(name) is None]
    assert not missing, missing
