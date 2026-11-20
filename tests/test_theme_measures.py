# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Marks of margins and paddings on the sample slides (theme_measures, ThemeSampleView.show_measure; docs/plans/
theme-editor.md, section 3.3, stage C2b): a typed length in bp, which marks a field gets, the Top Margin's check against
the title bar, the geometry read from a real render, and the form telling the slides what to mark."""
import os
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QLabel, QLineEdit

from conftest import EXAMPLE_PROJECT
from slidemage import theme_measures, theme_sample
from slidemage.theme_measures import Mark, marks, title_bar_check, to_bp
from slidemage.ui.kit.theme import ThemeManager
from slidemage.ui.workspace.source_editor import LatexPlainTextEdit
from slidemage.ui.workspace.theme_form import ThemeForm
from slidemage.ui.workspace.theme_sample_view import ThemeSampleView

ROOT = Path(__file__).resolve().parents[1]
SHIPPED = ROOT / "latex" / "SlideMage_template_slidemage.tex"
GEOMETRY = {"page_width": 453.54, "page_height": 255.12, "SMTopMargin": 41.58, "SMTitleBarBottom": 25.23,
            "SMTextMarginLeft": 12.76, "SMTextMarginRight": 12.76, "SMFooterBoxHeight": 7.23, "SMLeftMargin": 17.4,
            "SMFrametitleRightPadding": 7.94, "SMFrametitleTopPadding": 17.4}
TEX = pytest.mark.skipif(not os.environ.get("SLIDEMAGE_TEX_TESTS") or not shutil.which("lualatex"),
                         reason="compiles with lualatex: SLIDEMAGE_TEX_TESTS=1")


def test_a_typed_length_in_bp():
    assert to_bp("45bp", "SMTopMargin", GEOMETRY) == 45
    assert to_bp("1in", "SMTopMargin", GEOMETRY) == 72
    assert to_bp("2.54cm", "SMTopMargin", GEOMETRY) == pytest.approx(72)
    assert to_bp("72.27pt", "SMTopMargin", GEOMETRY) == pytest.approx(72)
    # ex: scaled from the last render's value in the same unit (2.2ex rendered as 17.4bp)
    assert to_bp("4.4ex", "SMFrametitleTopPadding", GEOMETRY, "2.2ex") == pytest.approx(34.8)
    assert to_bp("4.4ex", "SMFrametitleTopPadding", GEOMETRY, "0.5cm") is None
    assert to_bp("0.8\\paperheight", "SMTopMargin", GEOMETRY) is None


def test_which_marks_a_field_gets():
    top = marks("SMTopMargin", 60.0, GEOMETRY)
    assert top[0] == Mark("h", 60.0, "Top Margin 21.2 mm", True, arrow=True)       # labelled in the display unit
    assert marks("SMTopMargin", 60.0, GEOMETRY, "pt")[0].label == "Top Margin 60.2 pt"
    assert top[1].at == 25.23 and not top[1].focus
    assert marks("SMTopMargin", None, GEOMETRY)[0].at == 41.58          # as rendered
    left, right = marks("SMTextMarginRight", 20.0, GEOMETRY)
    assert (left.at, left.focus) == (12.76, False) and (right.at, right.focus) == (pytest.approx(433.54), True)
    footer = marks("SMFooterBoxHeight", 10.0, GEOMETRY)
    assert footer == [Mark("box", pytest.approx(245.12), "footer box 3.5 mm", True, size=10.0)]
    bar = marks("SMFrametitleTopPadding", 30.0, GEOMETRY)
    assert bar[0].kind == "h" and "after the next render" in bar[0].label and bar[0].focus
    assert marks("SMBlockSideMargin", 5.0, GEOMETRY) == [] and marks("SMTopMargin", 50.0, {}) == []


def test_the_top_margin_against_the_title_bar():
    assert title_bar_check(41.58, GEOMETRY) == ("5.8 mm below the title bar", True)
    assert title_bar_check(41.58, GEOMETRY, "pt") == ("16.4 pt below the title bar", True)
    assert theme_measures.show(72.0) == "25.4 mm" and theme_measures.number_in(72.0, "mm") == "25.4"
    text, ok = title_bar_check(20.0, GEOMETRY)
    assert not ok and "above the title bar" in text
    assert title_bar_check(None, GEOMETRY) == ("", True)


@TEX
def test_a_render_brings_its_geometry():
    result = theme_sample.render(EXAMPLE_PROJECT, SHIPPED.read_text(encoding="utf-8"), "probe", "")
    geometry = result.geometry
    assert geometry["SMTopMargin"] == pytest.approx(41.58, abs=0.01)
    assert 0 < geometry["SMTitleBarBottom"] < geometry["SMTopMargin"]
    assert geometry["page_width"] == pytest.approx(453.54, abs=0.1) and geometry["SMTextMarginLeft"] > 0


def wait_for(qapp, condition, tries=300):
    import time
    for _ in range(tries):
        qapp.processEvents()
        if condition():
            return True
        time.sleep(0.01)
    return False


def test_the_slides_mark_a_focused_length(qapp, tmp_path):
    import pymupdf
    pdf = tmp_path / "s.pdf"
    doc = pymupdf.open()
    for _ in range(3):
        doc.new_page(width=453.54, height=255.12)
    doc.save(pdf)
    editor = LatexPlainTextEdit(ThemeManager())
    editor.set_text(SHIPPED.read_text(encoding="utf-8"))
    view = ThemeSampleView(editor, "probe", SimpleNamespace(root=tmp_path),
                           lambda *a, **k: theme_sample.SampleResult(pdf, "", "", dict(GEOMETRY)))
    seen = []
    view.geometry_changed.connect(lambda: seen.append(True))
    view.resize(500, 340)
    view.show()
    assert wait_for(qapp, lambda: view._images) and seen and view.geometry["SMTopMargin"] == 41.58
    view.show_page(1)
    plain = view._images[0]
    view.show_measure("SMTopMargin", 60.0)
    assert view._page == 2                       # the title frame has no ordinary title bar: a standard frame
    marked = view._paint_marks(view._images[1])
    y = int(60.0 * marked.width() / 453.54)
    assert marked.pixelColor(10, y).blue() > 150 and marked.pixelColor(10, y).red() < 120
    assert plain.pixelColor(10, y).red() == 255
    view.clear_measure()
    assert view._paint_marks(view._images[1]) is view._images[1]
    view.close()


def test_the_form_tells_the_slides_the_length_as_typed(qapp):
    editor = LatexPlainTextEdit(ThemeManager())
    editor.set_text(SHIPPED.read_text(encoding="utf-8"))
    form = ThemeForm(editor, SHIPPED, ROOT / "example", ROOT / "latex" / "SlideMage_setup.tex")
    told = []
    form.on_measure = lambda key, value: told.append((key, value))
    form.on_measure_cleared = lambda: told.append(None)
    form.geometry = lambda: dict(GEOMETRY)
    form.refresh()
    box = form.layout_fields["SMTopMargin"]
    number = box.findChildren(QLineEdit)[0]
    number.setText("20")
    number.textEdited.emit("20")                      # a new value is typed in the display unit, mm
    assert told[-1] == ("SMTopMargin", pytest.approx(20 * 72 / 25.4))
    assert any(label.text() == "11.1 mm below the title bar" for label in box.findChildren(QLabel))
    number.setText("5")
    number.textEdited.emit("5")
    assert any("above the title bar" in label.text() for label in box.findChildren(QLabel))
    margin = form.layout_fields["SMTextMarginLeft"].findChildren(QLineEdit)[0]
    margin.setText("1")
    margin.textEdited.emit("1")
    assert told[-1] == ("SMTextMarginLeft", pytest.approx(72 / 25.4))     # unset: typed in mm
    assert "SMTopMargin" not in editor.text()           # marking writes nothing; leaving the field does
    assert theme_measures.MEASURED[0] == "SMTopMargin"
