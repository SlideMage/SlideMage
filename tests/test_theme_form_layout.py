# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The theme form's layout fields (docs/plans/theme-editor.md, stage C2a): the layout profile, text sizes, margins, title
bar, footer and footnotes, bullet and citation format, each written as one line of the theme."""
from pathlib import Path

from PySide6.QtWidgets import QComboBox, QLabel, QLineEdit

from slidemage import theme_fields
from slidemage.theme_form_model import ADVANCED_ELSEWHERE, ADVANCED_SECTIONS, LAYOUT_SECTIONS, ThemeModel
from slidemage.ui.kit.theme import ThemeManager
from slidemage.ui.workspace.source_editor import LatexPlainTextEdit
from slidemage.ui.workspace.theme_form import ThemeForm

ROOT = Path(__file__).resolve().parents[1]
SHIPPED = ROOT / "latex" / "SlideMage_template_slidemage.tex"
GRAYSCALE = ROOT / "latex" / "SlideMage_template_grayscale.tex"
SETUP = ROOT / "latex" / "SlideMage_setup.tex"


def make_form(path: Path):
    editor = LatexPlainTextEdit(ThemeManager())
    editor.set_text(path.read_text(encoding="utf-8").replace("\r\n", "\n"))
    return editor, ThemeForm(editor, path, ROOT / "example", SETUP)


def test_catalog_settings_have_a_place_in_the_form():
    placed = {key for _title, _note, keys in LAYOUT_SECTIONS for key in keys}
    tier2 = {f.name for f in theme_fields.FIELDS if f.tier == 2}
    assert tier2 <= placed, sorted(tier2 - placed)

    shown = [key for _title, _note, keys in ADVANCED_SECTIONS for key in keys]
    assert len(shown) == len(set(shown))
    tier3 = {field.name for field in theme_fields.FIELDS if field.tier == 3}
    assert set(shown) | ADVANCED_ELSEWHERE == tier3 and not set(shown) & ADVANCED_ELSEWHERE


def test_a_length_is_a_number_and_a_unit(qapp):
    editor, form = make_form(SHIPPED)
    box = form.layout_fields["SMTopMargin"]
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
    left_number, _left_raw = form.layout_fields["SMTextMarginLeft"].findChildren(QLineEdit)
    form.layout_fields["SMTextMarginLeft"].findChild(QComboBox).setCurrentText("cm")
    left_number.setText("1")
    left_number.editingFinished.emit()
    assert "\\setlength{\\SMTextMarginLeft}{1cm}" in editor.text()


def test_a_length_of_another_form_shows_as_tex(qapp):
    editor, form = make_form(SHIPPED)
    form.apply(lambda: form.model.set_value("SMTextMarginRight", "0.02\\paperwidth"))
    number, raw = form.layout_fields["SMTextMarginRight"].findChildren(QLineEdit)
    assert number.isHidden() and not raw.isHidden() and raw.text() == "0.02\\paperwidth"


def test_a_size_pair_is_two_numbers(qapp):
    editor, form = make_form(GRAYSCALE)
    box = form.layout_fields["SMFooterTextSize"]
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
    profile = form.layout_fields["SMLayoutProfile"]
    assert isinstance(profile, QComboBox) and profile.findText("lmroman") > 0
    profile.setCurrentText("lmsans")
    profile.activated.emit(0)
    text = editor.text()
    assert text.index("\\newcommand{\\SMLayoutProfile}{lmsans}") < text.index("\\input{SlideMage_setup}")
    bullet = form.layout_fields["SMBulletSymbol"]
    bullet.setCurrentIndex(bullet.findText("En dash"))
    bullet.activated.emit(bullet.currentIndex())
    assert "\\renewcommand{\\SMBulletSymbol}[1]{\\textcolor{#1}{\\textendash}}" in editor.text()
    bullet.setCurrentIndex(0)
    bullet.activated.emit(0)
    assert "SMBulletSymbol" not in editor.text()
    _, grey = make_form(GRAYSCALE)
    assert grey.layout_fields["SMBulletSymbol"].currentText() == "En dash"
    citation = form.layout_fields["SMCitationFormat"]
    citation.setCurrentText("default")
    citation.activated.emit(0)
    assert "\\renewcommand{\\SMCitationFormat}{default}" in editor.text()


def test_lengths_show_in_one_unit_and_keep_their_own(qapp, monkeypatch):
    from slidemage.ui.workspace import theme_form
    stored = {}
    monkeypatch.setattr(theme_form.layout_settings, "get", lambda key, default=None: stored.get(key, default))
    monkeypatch.setattr(theme_form.layout_settings, "set", lambda key, value: stored.__setitem__(key, value))
    editor, form = make_form(GRAYSCALE)
    form.geometry = lambda: {"page_width": 453.54, "page_height": 255.12, "SMFrametitleTopPadding": 15.99,
                             "SMTextMarginLeft": 28.35}
    form.refresh()
    assert form.display_unit == "mm"

    def note(key):
        return [label.text() for label in form.layout_fields[key].findChildren(QLabel) if label.text()][0]

    assert note("SMTextMarginLeft") == "≈ 10.0 mm"              # written as 1cm: stays 1cm, shown in mm beside it
    assert note("SMFrametitleTopPadding") == "≈ 5.6 mm"          # written as 3.4ex: its rendered size
    assert r"\setlength{\SMTextMarginLeft}{1cm}" in editor.text()
    form.set_display_unit("pt")
    assert stored["theme_display_unit"] == "pt" and form.display_unit == "pt"
    form.refresh()
    assert note("SMTextMarginLeft") == "≈ 28.5 pt"
    assert r"\setlength{\SMTextMarginLeft}{1cm}" in editor.text()     # switching the unit rewrites nothing


def test_every_advanced_field_is_written_read_and_taken_out_again():
    text = SHIPPED.read_text(encoding="utf-8").replace("\r\n", "\n")
    setup = SETUP.read_text(encoding="utf-8")
    samples = {"length": "7pt", "number": "0.33", "text": "section", "tex": r"\bfseries"}
    for _title, _note, keys in ADVANCED_SECTIONS:
        for key in keys:
            field = theme_fields.BY_NAME[key]
            value = field.choices[0] if field.choices else samples[field.kind]
            model = ThemeModel(text, ROOT / "example", "probe", setup)
            assert model.value(key) is None, key
            model.set_value(key, value)
            assert model.value(key) == value, key
            again = ThemeModel(model.text, ROOT / "example", "probe", setup)
            assert again.value(key) == value, key
            again.set_value(key, None)
            assert again.text == text, key


def test_the_advanced_tab_writes_features_ratios_and_lengths(qapp):
    editor, form = make_form(SHIPPED)
    form.show_tab("Advanced")
    position = form.layout_fields["SMProgressBarPosition"]
    position.combo.setCurrentText("foot")
    position.combo.activated.emit(position.combo.currentIndex())
    assert r"\SMProgressBarPosition{foot}" in editor.text()
    position.combo.setCurrentText("bottom")
    position.combo.lineEdit().editingFinished.emit()
    assert r"\SMProgressBarPosition{foot}" in editor.text()
    position.combo.setCurrentText("")
    position.combo.lineEdit().editingFinished.emit()
    assert "SMProgressBarPosition" not in editor.text()
    ratio = form.layout_fields["SMItemsepRatioI"].findChild(QLineEdit)
    ratio.setText("0,5")
    ratio.editingFinished.emit()
    assert "SMItemsepRatioI" not in editor.text()
    ratio.setText("0.5")
    ratio.editingFinished.emit()
    assert r"\renewcommand{\SMItemsepRatioI}{0.5}" in editor.text()
    gap = form.layout_fields["SMBesideFigureTopGap"].findChild(QLineEdit)
    gap.setText("wide")
    gap.editingFinished.emit()
    assert "SMBesideFigureTopGap" not in editor.text()
    gap.setText("3pt")
    gap.editingFinished.emit()
    assert r"\SMBesideFigureTopGap}{3pt}" in editor.text()
