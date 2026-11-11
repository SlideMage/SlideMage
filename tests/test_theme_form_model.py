# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The theme form's model (theme_form_model.ThemeModel; docs/plans/theme-editor.md, stage C1b): modes as columns, what a
cell writes and what it comes to in each mode (the framework's resolution order), the contrast checks, and the edits,
each of which changes one line of the theme or adds one."""
import difflib
from pathlib import Path

import pytest

from slidemage.theme_form_model import CHECKS, ThemeModel, contrast, format_modes_header, parse_modes_header

ROOT = Path(__file__).resolve().parents[1]
LATEX = ROOT / "latex"
SETUP = (LATEX / "SlideMage_setup.tex").read_text(encoding="utf-8")
FIXTURES = ROOT / "tests" / "fixtures" / "theme_files"


def model(path: Path, root: Path = ROOT / "example", key: str = "probe") -> ThemeModel:
    return ThemeModel(path.read_text(encoding="utf-8").replace("\r\n", "\n"), root, key, SETUP)


def changes(old: str, new: str) -> list[str]:
    return [line for line in difflib.ndiff(old.split("\n"), new.split("\n")) if line[:1] in "+-"]


@pytest.fixture
def shipped() -> ThemeModel:
    return model(LATEX / "SlideMage_template_slidemage.tex")


@pytest.fixture
def modeshape() -> ThemeModel:
    return model(FIXTURES / "SlideMage_template_modeshape.tex")


@pytest.fixture
def condshape() -> ThemeModel:
    return model(FIXTURES / "SlideMage_template_condshape.tex")


def test_modes_are_the_columns(shipped, condshape):
    assert [(m.id, m.derive, m.label) for m in shipped.modes()] == [("light", "", "Light"), ("dark", "dark", "Dark slides")]
    assert shipped.base == "light" and shipped.header_mismatch() == ""
    assert [m.id for m in condshape.modes()] == [""]          # no modes: one column
    assert condshape.readable and shipped.readable
    assert not ThemeModel("\\definecolor{c_x}{HTML}{000000}\n", ROOT, "x", SETUP).readable


def test_what_a_role_comes_to_follows_the_frameworks_order(shipped, modeshape):
    # the dark preset's canvas: c_primary_dark (1e1e1e) 83 % with white
    assert shipped.resolve("role:canvas", "light") == "#ffffff"
    assert shipped.resolve("role:canvas", "dark") == "#444444"
    assert shipped.role_written("canvas", "dark") is None and shipped.role_follows("canvas", "dark") == "c_primary_dark!83!white"
    # an explicit line wins over the preset; a hook role's base value is its macro
    assert modeshape.resolve("role:canvas", "dark") == "#2a2a2a"
    assert modeshape.role_written("title_fill", "light") == "c_primary_highlight"
    assert modeshape.resolve("role:title_fill", "dark") == "#e0a000"
    # standout_fill follows the title bar's fill; standout_text with no line is the theme's pale yellow
    assert shipped.resolve("role:standout_fill", "light") == shipped.resolve("role:title_fill", "light")
    assert shipped.resolve("role:standout_text", "light") == "#fffff0"
    # a mode's palette line, and the alert hook's dark line of the shipped template
    assert shipped.palette_hex("c_custom_red", "dark") == "#ff9090"
    assert shipped.resolve("role:alert", "dark") == shipped.palette_hex("c_secondary_orange", "dark")


def test_a_theme_colorlet_keeps_the_base_palettes_colour_in_every_mode(shipped):
    """\\colorlet{SMCodeKeywordColor}{c_primary_highlight} runs before the mode applies: dark keeps the dark blue."""
    assert shipped.resolve("role:code_keyword", "dark") == "#0066cc"


def test_checks_cover_the_catalogs_pairs(shipped, modeshape):
    labels = [c.label for c in shipped.checks("light")]
    assert labels == [label for label, *_ in CHECKS]
    assert all(c.ok for c in shipped.checks("light"))
    standout = next(c for c in modeshape.checks("dark") if c.label == "Standout frame text")
    assert standout.ratio == pytest.approx(1.0) and not standout.ok        # highlight text on a highlight fill
    assert contrast("#000000", "#ffffff") == pytest.approx(21.0)


def test_palette_edits_change_one_line(modeshape):
    before = modeshape.text
    modeshape.set_palette("c_primary_highlight", "light", "#ff0000")
    modeshape.set_palette("c_custom_red", "dark", "#ff8080")
    assert changes(before, modeshape.text) == [
        "- \\definecolor{c_primary_highlight}{HTML}{e0a000}", "+ \\definecolor{c_primary_highlight}{HTML}{ff0000}",
        "- \\SMSetColor{c_custom_red}{dark}{HTML}{FF6B6B}   % 5.1:1; also the markers",
        "+ \\SMSetColor{c_custom_red}{dark}{HTML}{FF8080}   % 5.1:1; also the markers"]
    assert modeshape.palette_hex("c_primary_highlight", "light") == "#ff0000"
    modeshape.set_palette("c_custom_red", "dark", None)
    assert modeshape.palette_written("c_custom_red", "dark") is None
    assert modeshape.palette_hex("c_custom_red", "dark") == "#b00000"      # the base colour again
    with pytest.raises(ValueError):
        modeshape.set_palette("c_custom_red", "dark", "c_primary_dark!50")


def test_role_edits(modeshape, condshape):
    before = modeshape.text
    modeshape.set_role("title_fill", "light", "c_secondary_blue")          # base: the hook macro
    modeshape.set_role("title_fill", "dark", "c_test_dark_card")           # dark: a mode line after the others
    assert changes(before, modeshape.text) == [
        "- \\renewcommand{\\SMTitleBoxColor}{c_primary_highlight}", "+ \\renewcommand{\\SMTitleBoxColor}{c_secondary_blue}",
        "+ \\SMSetRole{title_fill}{dark}{c_test_dark_card}"]
    modeshape.set_role("canvas", "dark", None)
    assert modeshape.role_written("canvas", "dark") is None
    assert modeshape.resolve("role:canvas", "dark") == "#393939"     # the preset: c_primary_dark (101010) !83!white
    # a role without a hook has no base value of its own in a theme without modes
    assert not condshape.role_editable("canvas", "")
    with pytest.raises(ValueError):
        condshape.set_role("canvas", "", "c_primary_dark")
    assert condshape.role_editable("title_fill", "")


def test_adding_and_removing_modes(condshape):
    condshape.add_mode("dark", "dark", "Dark slides")
    assert [(m.id, m.derive) for m in condshape.modes()] == [("light", ""), ("dark", "dark")]
    assert condshape.file.value("header:modes") == "light, dark=Dark slides" and condshape.header_mismatch() == ""
    condshape.set_role("canvas", "dark", "c_primary_dark")
    condshape.set_palette("c_primary_highlight", "dark", "#ffcc00")
    condshape.add_mode("grey", "grey", "")
    assert condshape.file.value("header:modes") == "light, dark=Dark slides, grey"
    assert condshape.palette_hex("c_secondary_blue", "grey") != condshape.palette_hex("c_secondary_blue", "light")
    condshape.remove_mode("dark")
    assert [m.id for m in condshape.modes()] == ["light", "grey"]
    assert "{dark}" not in condshape.text and condshape.header_mismatch() == ""
    for bad in ("Dark", "grey", "light"):
        with pytest.raises(ValueError):
            condshape.add_mode(bad, "", "")
    with pytest.raises(ValueError):
        condshape.remove_mode("light")


def test_a_header_that_names_other_modes_is_reported(shipped):
    shipped.file.set("header:modes", "light")
    assert "names the modes light" in shipped.header_mismatch()
    assert parse_modes_header(" light , dark = Dark ") == [("light", ""), ("dark", "Dark")]
    assert format_modes_header([("light", ""), ("dark", "Dark")]) == "light, dark=Dark"


def test_own_colours(modeshape):
    modeshape.add_own_colour("c_test_accent", "#123456")
    assert "c_test_accent" in modeshape.palette_names() and "c_test_accent" in modeshape.colour_names()
    assert modeshape.palette_hex("c_test_accent", "dark") == "#123456"
    for bad in ("x_test", "c_primary_dark", "c_test_dark_card", "c_Bad"):
        with pytest.raises(ValueError):
            modeshape.add_own_colour(bad, "#000000")


def test_footnote_styles(modeshape):
    assert modeshape.footnote_style() == "boxed"
    modeshape.set_footnote_style("numbers")
    assert modeshape.footnote_style() == "numbers" and modeshape.file.find("SMSetFootnoteMarkers") is None
    assert "\\renewcommand{\\SMFootnoteMark}[1]{\\number#1}" in modeshape.text
    modeshape.set_footnote_style("dice")
    assert modeshape.footnote_style() == "dice" and modeshape.file.find("SMFootnoteMark") is None
    modeshape.set_footnote_style("symbols")
    assert modeshape.footnote_style() == "symbols" and "SetFootnoteMarkers" not in modeshape.text
    modeshape.file.set("SMFootnoteMark", "(\\number#1)")
    assert modeshape.footnote_style() == "custom"


def test_name_logo_and_plain_values(modeshape, tmp_path):
    modeshape.set_name("  New name  ")
    assert modeshape.name() == "New name"
    logo = tmp_path / "in" / "logo.pdf"
    logo.parent.mkdir()
    logo.write_bytes(b"%PDF-1.4 test")
    project = model(FIXTURES / "SlideMage_template_modeshape.tex", root=tmp_path, key="my-look")
    assert project.import_logo(logo) == "schemes/scheme_my_look/logo.pdf"
    assert (tmp_path / "schemes" / "scheme_my_look" / "logo.pdf").read_bytes() == b"%PDF-1.4 test"
    assert project.value("SMInstituteLogoPath") == "schemes/scheme_my_look/logo.pdf"
    other = tmp_path / "other" / "logo.pdf"
    other.parent.mkdir()
    other.write_bytes(b"%PDF-1.4 other")
    with pytest.raises(ValueError):
        project.import_logo(other)
    project.set_value("SMLogoHeight", "4ex")
    assert project.value("SMLogoHeight") == "4ex"
    project.set_value("SMLogoHeight", "")
    assert project.value("SMLogoHeight") is None and project.default("SMLogoHeight") == "3ex"
