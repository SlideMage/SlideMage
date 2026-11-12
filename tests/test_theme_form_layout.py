# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The theme form's layout fields (docs/plans/theme-editor.md, stage C2a): the layout profile, text sizes, margins, title
bar, footer and footnotes, bullet and citation format, each written as one line of the theme."""
from pathlib import Path

from PySide6.QtWidgets import QComboBox, QLabel, QLineEdit

from slidemage import theme_fields
from slidemage.theme_form_model import (LAYOUT_SECTIONS, check_length, citation_formats, format_size_pair,
                                        layout_profiles, parse_size_pair)
from slidemage.ui.kit.theme import ThemeManager
from slidemage.ui.workspace.source_editor import LatexPlainTextEdit
from slidemage.ui.workspace.theme_form import ThemeForm

ROOT = Path(__file__).resolve().parents[1]
SHIPPED = ROOT / "latex" / "SlideMage_template_slidemage.tex"
GREYSCALE = ROOT / "latex" / "SlideMage_template_greyscale.tex"


def make_form(path: Path):
    editor = LatexPlainTextEdit(ThemeManager())
    editor.set_text(path.read_text(encoding="utf-8").replace("\r\n", "\n"))
    return editor, ThemeForm(editor, path, ROOT / "example", ROOT / "latex" / "SlideMage_setup.tex")


def row_widget(form: ThemeForm, key: str):
    return form.layout_fields[key]


def test_every_tier_2_setting_has_a_place_in_the_form():
    placed = {key for _title, _note, keys in LAYOUT_SECTIONS for key in keys}
    tier2 = {f.name for f in theme_fields.FIELDS if f.tier == 2}
    assert tier2 <= placed, sorted(tier2 - placed)


def test_lengths_and_size_pairs():
    for good in ("0.45cm", "2.2ex", "41.58bp", "-3pt", "0.8\\paperheight", "\\linewidth", ""):
        assert check_length(good) == "", good
    for bad in ("12", "cm", "1,5cm", "3 apples"):
        assert check_length(bad), bad
    assert parse_size_pair("\\fontsize{5}{3}\\selectfont") == ("5", "3")
    assert parse_size_pair("\\small") is None
    assert format_size_pair("6", "4.5") == "\\fontsize{6}{4.5}\\selectfont"
    assert layout_profiles(ROOT / "example")[:3] == ["fira", "lmsans", "lmroman"]
    assert citation_formats()[0] == "default"


def test_a_length_is_a_number_and_a_unit(qapp):
    editor, form = make_form(SHIPPED)
    box = row_widget(form, "SMTopMargin")
    number, raw = box.findChildren(QLineEdit)
    unit = box.findChild(QComboBox)
    # unset: shown and typed in the display unit, mm (41.58bp = 14.67mm)
    assert number.placeholderText() == "14.67" and unit.currentText() == "mm" and raw.isHidden()
    number.setText("45")
    number.editingFinished.emit()
    assert "\\renewcommand{\\SMTopMargin}{45mm}" in editor.text()
    unit.setCurrentText("pt")
    unit.activated.emit(unit.currentIndex())
    assert "\\renewcommand{\\SMTopMargin}{45pt}" in editor.text()
    number.setText("4,5")
    number.editingFinished.emit()
    assert "{45pt}" in editor.text()
    assert any("no length" in label.text() for label in box.findChildren(QLabel))
    number.setText("")
    number.editingFinished.emit()
    assert "SMTopMargin" not in editor.text()
    left_number, _left_raw = row_widget(form, "SMTextMarginLeft").findChildren(QLineEdit)
    row_widget(form, "SMTextMarginLeft").findChild(QComboBox).setCurrentText("cm")
    left_number.setText("1")
    left_number.editingFinished.emit()
    assert "\\setlength{\\SMTextMarginLeft}{1cm}" in editor.text()


def test_a_length_of_another_form_shows_as_tex(qapp):
    editor, form = make_form(SHIPPED)
    form.apply(lambda: form.model.set_value("SMTextMarginRight", "0.02\\paperwidth"))
    number, raw = row_widget(form, "SMTextMarginRight").findChildren(QLineEdit)
    assert number.isHidden() and not raw.isHidden() and raw.text() == "0.02\\paperwidth"


def test_a_size_pair_is_two_numbers(qapp):
    editor, form = make_form(GREYSCALE)
    box = row_widget(form, "SMFooterTextSize")
    size, skip, raw = box.findChildren(QLineEdit)
    assert (size.text(), skip.text()) == ("6", "4") and raw.isHidden()
    size.setText("7")
    size.editingFinished.emit()
    assert "\\renewcommand{\\SMFooterTextSize}{\\fontsize{7}{4}\\selectfont}" in editor.text()
    size.setText("")
    skip.setText("")
    skip.editingFinished.emit()
    assert "SMFooterTextSize" not in editor.text()


def test_profile_bullet_and_citation(qapp):
    editor, form = make_form(SHIPPED)
    profile = row_widget(form, "SMLayoutProfile")
    assert isinstance(profile, QComboBox) and profile.findText("lmroman") > 0
    profile.setCurrentText("lmsans")
    profile.activated.emit(0)
    text = editor.text()
    assert text.index("\\newcommand{\\SMLayoutProfile}{lmsans}") < text.index("\\input{SlideMage_setup}")
    bullet = row_widget(form, "SMBulletSymbol")
    bullet.setCurrentIndex(bullet.findText("En dash"))
    bullet.activated.emit(bullet.currentIndex())
    assert "\\renewcommand{\\SMBulletSymbol}[1]{\\textcolor{#1}{\\textendash}}" in editor.text()
    bullet.setCurrentIndex(0)
    bullet.activated.emit(0)
    assert "SMBulletSymbol" not in editor.text()
    grey_editor, grey = make_form(GREYSCALE)
    assert row_widget(grey, "SMBulletSymbol").currentText() == "En dash"
    citation = row_widget(form, "SMCitationFormat")
    citation.setCurrentText("default")
    citation.activated.emit(0)
    assert "\\renewcommand{\\SMCitationFormat}{default}" in editor.text()


def test_lengths_show_in_one_unit_and_keep_their_own(qapp, monkeypatch):
    from slidemage.ui.workspace import theme_form
    stored = {}
    monkeypatch.setattr(theme_form.layout_settings, "get", lambda key, default=None: stored.get(key, default))
    monkeypatch.setattr(theme_form.layout_settings, "set", lambda key, value: stored.__setitem__(key, value))
    editor, form = make_form(GREYSCALE)
    form.geometry = lambda: {"page_width": 453.54, "page_height": 255.12, "SMFrametitleTopPadding": 15.99,
                             "SMTextMarginLeft": 28.35}
    form.refresh()
    assert form.display_unit == "mm"

    def note(key):
        return [label.text() for label in row_widget(form, key).findChildren(QLabel) if label.text()][0]

    assert note("SMTextMarginLeft") == "≈ 10.0 mm"              # written as 1cm: stays 1cm, shown in mm beside it
    assert note("SMFrametitleTopPadding") == "≈ 5.6 mm"          # written as 3.4ex: its rendered size
    assert r"\setlength{\SMTextMarginLeft}{1cm}" in editor.text()
    form.set_display_unit("pt")
    assert stored["theme_display_unit"] == "pt" and form.display_unit == "pt"
    form.geometry = lambda: {"page_width": 453.54, "page_height": 255.12, "SMFrametitleTopPadding": 15.99,
                             "SMTextMarginLeft": 28.35}
    form.refresh()
    assert note("SMTextMarginLeft") == "≈ 28.5 pt"
    assert r"\setlength{\SMTextMarginLeft}{1cm}" in editor.text()     # switching the unit rewrites nothing
