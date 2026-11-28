# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""ThemeFile round trips and local edits across shipped and fixture themes.

SLIDEMAGE_REAL_THEMES can add private theme paths separated by os.pathsep.
"""
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
THEMES = [LATEX / "SlideMage_template_slidemage.tex", LATEX / "SlideMage_template_grayscale.tex",
          ROOT / "tests" / "fixtures" / "template_stress" / "SlideMage_template_stress-test.tex", MODESHAPE, CONDSHAPE,
                ROOT / "tests" / "fixtures" / "theme_package" / "sample-theme" / "SlideMage_template_sample-theme.tex"]
THEMES += [Path(p) for p in os.environ.get("SLIDEMAGE_REAL_THEMES", "").split(os.pathsep) if p.strip()]


def read(path: Path) -> str:
    return path.read_bytes().decode("utf-8").replace("\r\n", "\n")


def changed_lines(old: str, new: str) -> list[tuple[str, list[str], list[str]]]:
    a, b = old.split("\n"), new.split("\n")
    return [(tag, a[i1:i2], b[j1:j2]) for tag, i1, i2, j1, j2
            in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes() if tag != "equal"]


@pytest.fixture(params=THEMES, ids=lambda p: p.name)
def theme(request) -> Path:
    if not request.param.is_file():
        pytest.skip(f"{request.param} is not here")
    return request.param


def test_a_color_moves_between_definecolor_and_colorlet_keeping_its_comment():
    text = read(CONDSHAPE)
    edited = ThemeFile(text)
    edited.set("c_tertiary_blue", "c_secondary_blue!50")
    assert "\\colorlet{c_tertiary_blue}{c_secondary_blue!50} % derived (50% white-blend" in edited.text
    assert edited.value("c_tertiary_blue") == "c_secondary_blue!50"
    edited.set("c_tertiary_blue", "#8099B0")
    assert edited.text == text
    edited.set("SMCodeKeywordColor", "#112233")
    assert "  \\definecolor{SMCodeKeywordColor}{HTML}{112233}   % indented on purpose" in edited.text


def test_modes_change_in_place_and_new_lines_follow_the_existing_modes():
    text = read(MODESHAPE)
    edited = ThemeFile(text)
    assert edited.modes() == [("light", ""), ("dark", "dark")]
    edited.set("role:canvas", "c_primary_dark", "dark")
    edited.set("c_custom_red", "#ff7070", "dark")
    assert [new for _, _, new in changed_lines(text, edited.text)] == [
        [r"\SMSetRole{canvas}{dark}{c_primary_dark}"],
        [r"\SMSetColor{c_custom_red}{dark}{HTML}{FF7070}   % 5.1:1; also the markers"],
    ]
    assert edited.value("c_custom_red", "dark") == "#ff7070"
    assert edited.value("c_custom_red") == "#b00000"

    text = edited.text
    edited.set("role:title_fill", "c_test_dark_canvas", "dark")
    edited.set("c_custom_brown", "#d09a5c", "dark")
    edited.set("mode:gray", "gray")
    changes = changed_lines(text, edited.text)
    assert all(tag == "insert" for tag, _, _ in changes)
    lines = edited.text.split("\n")
    last = lines.index("\\SMSetRole{standout_text}{dark}{c_primary_highlight}")
    assert lines[last + 1:last + 3] == ["\\SMSetRole{title_fill}{dark}{c_test_dark_canvas}",
                                        "\\SMSetColor{c_custom_brown}{dark}{HTML}{d09a5c}"]
    assert lines[lines.index("\\SMDeclareMode{dark}{dark}") + 1] == "\\SMDeclareMode{gray}{gray}"
    assert edited.modes() == [("light", ""), ("dark", "dark"), ("gray", "gray")]
    edited.set("c_primary_white", "#fefefe")
    edited.set("c_primary_dark", "#ABCDEF")
    assert r"\definecolor{c_primary_white}{HTML}{FEFEFE}" in edited.text
    assert r"\definecolor{c_primary_dark}{HTML}{abcdef}" in edited.text


def test_a_theme_without_modes_gets_them_in_the_block_declarations_first():
    edited = ThemeFile(read(CONDSHAPE))
    edited.set("role:canvas", "c_primary_dark", "dark")
    edited.set("mode:dark", "dark")
    edited.set("mode:light", "")
    block = edited.text.split(BLOCK_BEGIN)[1].split(BLOCK_END)[0].strip().split("\n")
    assert block == ["\\SMDeclareMode{dark}{dark}", "\\SMDeclareMode{light}{}", "\\SMSetRole{canvas}{dark}{c_primary_dark}"]


def test_a_modes_color_takes_a_hex_value_and_a_role_takes_a_mode():
    edited = ThemeFile(read(MODESHAPE))
    with pytest.raises(ValueError):
        edited.set("c_custom_red", "c_primary_dark!50", "dark")
    with pytest.raises(ValueError):
        edited.set("role:title_fill", "c_primary_dark")
    with pytest.raises(ValueError):
        edited.set("SMLogoHeight", "4ex", "dark")


def test_added_settings_land_in_the_marked_block_in_catalog_order():
    text = read(LATEX / "SlideMage_template_slidemage.tex")
    edited = ThemeFile(text)
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


def test_macros_with_arguments_and_nested_braces():
    edited = ThemeFile(read(LATEX / "SlideMage_template_grayscale.tex"))
    assert edited.value("SMBulletSymbol") == r"\textcolor{#1}{\textendash}"
    edited.set("SMBulletSymbol", r"\textcolor{#1}{\textbullet}")
    assert r"\renewcommand{\SMBulletSymbol}[1]{\textcolor{#1}{\textbullet}}" in edited.text


def test_round_trip_and_local_edits_preserve_windows_line_ends(theme):
    text = read(theme).replace("\n", "\r\n")
    edited = ThemeFile(text)
    settings = [setting for setting in edited.settings if setting.editable]
    assert len(settings) >= 3
    for setting in settings:
        edited.set(setting.key, edited.value(setting.key, setting.mode), setting.mode)
    assert edited.text == text

    key = "c_primary_highlight"
    before = edited.find(key)
    edited.set(key, "#123abc")
    if before is None:
        assert [tag for tag, _, _ in changed_lines(text, edited.text)] == ["insert"]
        assert BLOCK_BEGIN in edited.text
    else:
        [(tag, [old], [new])] = changed_lines(text, edited.text)
        assert tag == "replace" and old.partition("%")[2] == new.partition("%")[2]
    assert edited.value(key) == "#123abc"
    edited.set("SMWarningSignPadding", "7pt")
    edited.set("role:alert", "c_secondary_orange", "dark")
    edited.set("header:name", "Line ends")
    assert "\n" not in edited.text.replace("\r\n", "")
    assert edited.value("header:name") == "Line ends"
    edited.remove("SMWarningSignPadding")
    assert "\n" not in edited.text.replace("\r\n", "")


def test_the_colors_read_equal_what_theme_colors_reads(theme, tmp_path):
    shutil.copy(theme, tmp_path / "SlideMage_template_probe.tex")
    edited = ThemeFile(read(theme))
    modes = [mode for mode, _ in edited.modes()] or [""]
    for mode in modes:
        resolved = theme_colors.theme_colors("probe", tmp_path, mode)
        for setting in edited.settings:
            # palette colors (theme_colors reads the optional SM*Color lines of the framework's conditionals too)
            if setting.kind != "color" or not setting.editable or setting.model != "HTML" or not setting.key.startswith("c_"):
                continue
            overridden = edited.find(setting.key, mode) if mode else None
            expected = edited.value(setting.key, mode) if overridden else edited.value(setting.key)
            assert resolved.get(setting.key) == expected, (theme.name, mode, setting.key)


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
    edited = ThemeFile(read(ROOT / "tests" / "fixtures" / "template_stress" / "SlideMage_template_stress-test.tex"))
    setup = (LATEX / "SlideMage_setup.tex").read_text(encoding="utf-8")
    catalog = theme_fields.catalog(setup)
    wanted = [name for name, entry in catalog.items() if entry.kind in ("length", "macro", "color", "optional_color")]
    missing = [name for name in wanted if edited.find(name) is None]
    assert not missing, missing


def bare(lines: str = "") -> str:
    return "\\input{SlideMage_setup}\n" + BLOCK_BEGIN + "\n" + lines + BLOCK_END + "\n\\input{SlideMage_base}\n"


@pytest.mark.parametrize("key", sorted(theme_fields.MACRO_COLORS))
def test_a_color_name_macro_is_set_with_renewcommand(key):
    theme = ThemeFile(bare())
    theme.set(key, " c_secondary_blue ")
    assert f"\\renewcommand{{\\{key}}}{{c_secondary_blue}}\n" in theme.text and "\\colorlet" not in theme.text
    assert theme.value(key) == "c_secondary_blue"
    theme.set(key, "c_primary_dark!50")
    assert theme.text.count(key) == 1 and theme.value(key) == "c_primary_dark!50"
    theme.remove(key)
    assert key not in theme.text
    with pytest.raises(ValueError):
        theme._line_for(key, "#123456", "dark")


def test_a_colorlet_of_a_macros_name_is_not_its_value_and_an_edit_puts_it_right():
    stale = ("\\definecolor{SMTitleBoxColor}{HTML}{112233}\n\\colorlet{SMBulletColor}{c_primary_gray}\n"
             "\\colorlet{SMTitleBoxColor}{c_secondary_blue} % the bar\n")
    theme = ThemeFile(bare(stale))
    assert theme.value("SMTitleBoxColor") is None           # TeX reads the macro, which these lines leave alone
    assert "SMTitleBoxColor" not in theme.own_colors() and "SMBulletColor" not in theme.own_colors()
    theme.set("SMTitleBoxColor", "c_secondary_blue")         # the last such line becomes the \renewcommand, in place
    assert theme.text == bare("\\colorlet{SMBulletColor}{c_primary_gray}\n"
                              "\\renewcommand{\\SMTitleBoxColor}{c_secondary_blue} % the bar\n")
    assert theme.value("SMTitleBoxColor") == "c_secondary_blue"
    theme.remove("SMBulletColor")                            # following the default again takes the stray line along
    assert "SMBulletColor" not in theme.text
    both = ThemeFile(bare("\\renewcommand{\\SMTitleBoxColor}{c_primary_gray}\n"
                          "\\colorlet{SMTitleBoxColor}{c_secondary_blue}\n"))
    assert both.value("SMTitleBoxColor") == "c_primary_gray"
    both.set("SMTitleBoxColor", "c_secondary_red")
    assert both.text == bare("\\renewcommand{\\SMTitleBoxColor}{c_secondary_red}\n")
    palette = ThemeFile(bare())                               # a real color of the catalog is still a color
    palette.set("SMCodeKeywordColor", "c_secondary_blue")
    assert "\\colorlet{SMCodeKeywordColor}{c_secondary_blue}" in palette.text
