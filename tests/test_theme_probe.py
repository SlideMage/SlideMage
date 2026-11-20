# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Where a colour is used on the sample slides (theme_probe; docs/plans/theme-editor.md, section 3.3, stage C1c part 2):
the probe lines, the boxes read from the PDF, a real probe render, the sample panel's dimming and page jump, and the theme form telling
it which colour field has the focus; and the way back: a click on the slide that goes to the field of what is
there (a colour role or a layout setting)."""
import os
import shutil
from pathlib import Path
from types import SimpleNamespace

import pymupdf
import pytest

from conftest import EXAMPLE_PROJECT
from slidemage import theme_measures, theme_probe, theme_sample
from slidemage.theme_file import ThemeFile
from slidemage.ui.kit.theme import ThemeManager
from slidemage.ui.workspace.source_editor import LatexPlainTextEdit
from slidemage.ui.workspace.theme_form import ThemeForm
from slidemage.ui.workspace.theme_sample_view import ThemeSampleView

ROOT = Path(__file__).resolve().parents[1]
SHIPPED = ROOT / "latex" / "SlideMage_template_slidemage.tex"
CONDSHAPE = ROOT / "tests" / "fixtures" / "theme_files" / "SlideMage_template_condshape.tex"
TEX = pytest.mark.skipif(not os.environ.get("SLIDEMAGE_TEX_TESTS") or not shutil.which("lualatex"),
                         reason="compiles with lualatex: SLIDEMAGE_TEX_TESTS=1")


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")


def test_probe_colours_are_distinct_and_no_greys():
    assert len(theme_probe.PROBES) == 60 == len(set(theme_probe.PROBES))
    assert all(len({p[0:2], p[2:4], p[4:6]}) > 1 for p in theme_probe.PROBES)
    roles = theme_probe.names("role", ThemeFile(read(SHIPPED)))
    assert len(roles) <= len(theme_probe.PROBES) and "text" in roles and "SMHighlightTitleTextColor" in roles


def test_probe_lines_go_right_before_the_base_and_name_the_mode():
    text = read(SHIPPED)
    probed, mapping = theme_probe.probe_text(text, "role", "dark")
    before, _, after = probed.partition("% theme form: where each color is used (probe render)\n")
    assert before == text[:len(before)] and after.endswith(text[len(before):])
    index = list(mapping.values()).index("text")
    assert f"\\SMSetRole{{text}}{{dark}}{{SMProbe{index}}}" in after
    assert "\\renewcommand{\\SMHighlightTitleTextColor}" in after and len(mapping) == len(set(mapping.values()))
    base, _ = theme_probe.probe_text(text, "palette", "")
    assert "\\SMSetColor{c_primary_dark}{light}{HTML}{" in base            # the base mode by its name
    plain, _ = theme_probe.probe_text(read(CONDSHAPE), "role", "")
    assert "\\SMDeclareMode{probe}{}\n" in plain and "\\SMSetRole{text}{probe}{" in plain
    with pytest.raises(ValueError):
        theme_probe.probe_text("\\input{SlideMage_setup}\n", "role", "")


def probe_pdf(tmp_path, draw) -> Path:
    pdf = tmp_path / "probe.pdf"
    doc = pymupdf.open()
    draw(doc.new_page(width=200, height=100))
    doc.new_page(width=200, height=100)
    doc.save(pdf)
    doc.close()
    return pdf


def rgb(probe: str) -> tuple:
    return tuple(int(probe[i:i + 2], 16) / 255 for i in (0, 2, 4))


FIRST, SECOND, THIRD = theme_probe.PROBES[0], theme_probe.PROBES[1], theme_probe.PROBES[2]


def test_the_boxes_are_the_fills_and_the_text_of_a_probe_colour(tmp_path):
    def draw(page):
        page.draw_rect(pymupdf.Rect(0, 0, 200, 20), color=None, fill=rgb(FIRST))          # a title bar
        page.insert_text((10, 60), "Some words", fontsize=10, color=rgb(SECOND))
        page.insert_text((10, 90), "other text", fontsize=10, color=(0, 0, 0))
        page.draw_line((100, 80), (150, 80), color=rgb(THIRD), width=1)

    usage = theme_probe.usage_map(probe_pdf(tmp_path, draw), {FIRST: "title_fill", SECOND: "text", THIRD: "rule",
                                                             theme_probe.PROBES[3]: "unused"}, "role", "")
    assert len(usage.pages) == 2
    assert [usage.pages_using(n) for n in ("title_fill", "text", "rule", "unused", "x")] == [[1], [1], [1], [], []]
    assert usage.boxes(1, "title_fill") == [theme_probe.Box(0, 0, 1, 0.2, True)]       # the fill's own outline
    (text,) = usage.boxes(1, "text")                # one box for the line, with a little room, not exact
    assert not text.exact and text.x0 == pytest.approx(0.05 - theme_probe.PAD_X / 200, abs=0.005)
    assert 0.25 < text.x1 < 0.5 and 0.4 < text.y0 < 0.55 and 0.6 < text.y1 < 0.7
    (rule,) = usage.boxes(1, "rule")                # a line has no height of its own: its width and the room
    assert rule.y1 - rule.y0 == pytest.approx((1 + 2 * theme_probe.PAD_Y) / 100, abs=0.001)
    assert usage.boxes(2, "text") == [] and usage.boxes(1, "unused") == [] and usage.boxes(9, "text") == []


def test_a_rectangle_painted_later_covers_what_is_under_it(tmp_path):
    def draw(page):
        page.draw_rect(pymupdf.Rect(0, 0, 200, 100), color=None, fill=rgb(FIRST))         # the canvas
        page.draw_rect(pymupdf.Rect(0, 0, 200, 20), color=None, fill=rgb(SECOND))         # the title bar over it
        page.draw_rect(pymupdf.Rect(150, 0, 200, 30), color=None, fill=rgb(FIRST))        # the canvas again, a corner
        page.draw_rect(pymupdf.Rect(0, 90, 200, 100), color=None, fill=(0.5, 0.5, 0.5))   # a footer of no probe colour
        page.draw_circle((100, 50), 3, color=None, fill=rgb(THIRD))                        # a bullet: covers nothing
        page.draw_rect(pymupdf.Rect(20, 40, 60, 60), color=None, fill=rgb(THIRD))
        page.draw_rect(pymupdf.Rect(20, 40, 60, 60), color=None, fill=rgb(SECOND))        # hides the one before fully

    usage = theme_probe.usage_map(probe_pdf(tmp_path, draw), {FIRST: "canvas", SECOND: "title_fill", THIRD: "bullet"},
                                  "role", "")
    title = [box[:5] for box in usage.boxes(1, "title_fill")]         # without the place in the painting
    assert (0, 0, 0.75, 0.2, True) in title and (0.1, 0.4, 0.3, 0.6, True) in title and len(title) == 2
    # the way back: what is at a point, the topmost first; the hidden rectangle and the covered canvas are not there
    assert usage.at(1, 0.1, 0.1) == ["title_fill"] and usage.at(1, 0.9, 0.1) == ["canvas"]
    assert usage.at(1, 0.5, 0.5) == ["bullet", "canvas"] and usage.at(1, 0.2, 0.5) == ["title_fill"]
    assert usage.at(1, 0.5, 0.95) == [] and usage.at(2, 0.5, 0.5) == [] and usage.at(7, 0.5, 0.5) == []
    canvas = usage.boxes(1, "canvas")
    assert all(b.exact and (b.y0 >= 0.2 - 1e-9 or b.x0 >= 0.75 - 1e-9) for b in canvas)     # not under the title bar
    assert all(b.y1 <= 0.9 + 1e-9 for b in canvas)                                            # nor under the footer
    assert not any(b.x0 < 0.2 < b.x1 and b.y0 < 0.5 < b.y1 for b in canvas)                 # nor under the block
    assert any(b.x0 < 0.5 < b.x1 and b.y0 < 0.5 < b.y1 for b in canvas)                     # but under the bullet
    (bullet,) = usage.boxes(1, "bullet")            # the hidden rectangle is gone, the circle has its room
    assert not bullet.exact and bullet.x1 - bullet.x0 == pytest.approx((6 + 2 * theme_probe.PAD_X) / 200, abs=0.002)


def test_words_on_one_line_are_one_box_and_another_colour_between_them_splits_it(tmp_path):
    def draw(page):
        page.insert_text((10, 30), "one", fontsize=10, color=rgb(FIRST))
        page.insert_text((10 + pymupdf.get_text_length("one ", fontsize=10), 30), "two", fontsize=10, color=rgb(FIRST))
        page.insert_text((10, 60), "left", fontsize=10, color=rgb(FIRST))
        page.insert_text((40, 60), "other", fontsize=10, color=rgb(SECOND))
        page.insert_text((80, 60), "right", fontsize=10, color=rgb(FIRST))

    usage = theme_probe.usage_map(probe_pdf(tmp_path, draw), {FIRST: "text", SECOND: "alert"}, "role", "")
    boxes = sorted(usage.boxes(1, "text"), key=lambda b: (round(b.y0, 2), b.x0))
    assert len(boxes) == 3          # "one two" joined; "left" and "right" apart
    (alert,) = usage.boxes(1, "alert")
    room = 2 * theme_probe.PAD_X / 200
    assert boxes[1].x1 < alert.x0 + room and alert.x1 - room < boxes[2].x0


@TEX
def test_a_real_probe_finds_the_block_titles_and_the_code_panel():
    text = read(SHIPPED)
    probed, mapping = theme_probe.probe_text(text, "role", "")
    result = theme_sample.render(EXAMPLE_PROJECT, probed, "probe--role", "")
    assert result.pdf, result.log
    usage = theme_probe.usage_map(result.pdf, mapping, "role", "")
    assert usage.pages_using("block_title_fill") == [3]
    assert usage.pages_using("code_panel") == [4]
    assert 2 in usage.pages_using("text") and 3 in usage.pages_using("info_block_title_fill")
    (bar,) = usage.boxes(2, "title_fill")           # the title bar, less what the canvas paints over it again
    assert bar.exact and bar.x0 < 0.001 and bar.y0 < 0.001 and 0.85 < bar.x1 < 1 and 0.05 < bar.y1 < 0.15
    footer = usage.boxes(2, "footer_text")
    assert footer and all(not b.exact and b.y0 > 0.9 for b in footer)
    assert all(b.y0 > 0.1 for b in usage.boxes(2, "text"))         # no body text colour in the title bar
    assert not any(b.y0 < 0.05 and b.x0 < 0.5 for b in usage.boxes(2, "canvas"))   # the canvas: not under the bar


# --- the panel and the form -------------------------------------------------------------------------------------------

def sample_pdf(path: Path, pages: int = 3) -> Path:
    doc = pymupdf.open()
    for _ in range(pages):
        doc.new_page(width=160, height=90)
    doc.save(path)
    doc.close()
    return path


def wait_for(qapp, condition, tries=300):
    import time
    for _ in range(tries):
        qapp.processEvents()
        if condition():
            return True
        time.sleep(0.01)
    return False


def make_view(tmp_path, pages_with_role=(3,)):
    editor = LatexPlainTextEdit(ThemeManager())
    editor.set_text(read(SHIPPED))
    renders = []

    def fake_render(project, text, key, mode, cancel=None):
        renders.append(key)
        return theme_sample.SampleResult(sample_pdf(tmp_path / f"r{len(renders)}.pdf"), "", mode)

    def fake_read(pdf, mapping, kind, mode):
        usage = theme_probe.UsageMap(kind, mode, ["block_title_fill", "text", "link", "block_title_text"])
        for page in range(1, 4):
            top = [theme_probe.Box(0, 0, 1, 4 / 9, True, 1)]             # the top four ninths are the role's
            word = [theme_probe.Box(0.25, 0.6, 0.75, 0.8, False, 2)]      # and a piece of text lower down is a link
            title = [theme_probe.Box(0.1, 0.1, 0.4, 0.3, False, 3)]       # the block's title, on its fill
            usage.pages.append([top, [], word, title] if page in pages_with_role else [[], [], [], []])
        return usage

    view = ThemeSampleView(editor, "probe", SimpleNamespace(root=tmp_path), fake_render, fake_read)
    view.resize(400, 300)
    view.show()
    assert wait_for(qapp_ref[0], lambda: view._images)
    return editor, view, renders


qapp_ref = [None]


def test_the_panel_lights_up_the_focused_colour_and_jumps_to_its_page(qapp, tmp_path):
    qapp_ref[0] = qapp
    editor, view, renders = make_view(tmp_path)
    assert view._page == 2
    view.show_usage("role", "block_title_fill", "light")
    assert "Finding where Block title fill is used" in view.usage_label.text()
    assert wait_for(qapp, lambda: view._map() is not None)
    assert view._page == 3 and "page 3" in view.usage_label.text() and renders[-1] == "probe--probe-role"
    plain = view._images[2]
    lit = view._composite(plain)
    bottom = lit.pixelColor(80, 240)                      # outside the role: dimmed
    assert bottom.red() < plain.pixelColor(80, 240).red()
    assert lit.pixelColor(80, 5).red() == plain.pixelColor(80, 5).red()     # inside: as it is
    edge = plain.height() * 4 // 9
    assert lit.pixelColor(80, edge - 2) == plain.pixelColor(80, edge - 2)   # up to the edge: nothing shaded
    assert lit.pixelColor(80, edge + 2) == bottom                           # and fully dimmed right below it
    view.show_usage("role", "link", "light")
    word = view._composite(plain)                           # a rounded box: its middle and edges lit, its corner not
    width, height = plain.width(), plain.height()
    assert word.pixelColor(width // 2, int(height * 0.7)) == plain.pixelColor(width // 2, int(height * 0.7))
    assert word.pixelColor(int(width * 0.25) + 1, int(height * 0.7)) == plain.pixelColor(0, 0)
    assert word.pixelColor(int(width * 0.25), int(height * 0.6)).red() < plain.pixelColor(0, 0).red()
    assert word.pixelColor(80, 5) == bottom
    view.show_usage("role", "block_title_fill", "light")
    view.show_usage("role", "text", "light")
    assert "not used on the sample slides" in view.usage_label.text()
    view.clear_usage()
    assert view.usage_label.text() == "" and view._composite(plain) is plain
    editor.patch_text(editor.text() + "% a change\n")       # a new text needs a new probe
    assert view._maps == {}
    view.close()


def test_the_form_tells_which_colour_has_the_focus(qapp):
    editor = LatexPlainTextEdit(ThemeManager())
    editor.set_text(read(SHIPPED))
    form = ThemeForm(editor, SHIPPED, ROOT / "example", ROOT / "latex" / "SlideMage_setup.tex")
    told = []
    form.on_usage = lambda *usage: told.append(usage)
    form.on_usage_cleared = lambda: told.append(None)
    palette = next(c for c in form._cells if c.usage == ("palette", "c_primary_highlight", "light"))
    form.set_mode("dark")
    role = next(c for c in form._cells if c.usage == ("role", "title_fill", "dark"))
    form.focus_usage(palette.usage)
    form.hover_usage(role.usage)                  # the mouse over another cell wins while it is there
    form.hover_usage(None)
    form.blur_usage(palette.usage)
    assert told == [("palette", "c_primary_highlight", "light"), ("role", "title_fill", "dark"),
                    ("palette", "c_primary_highlight", "light"), None]
    form._toggle_group("Code panels")
    code = [c.usage for c in form._cells if c.usage and c.usage[1] == "code_keyword"]
    form.set_mode("light")
    code += [c.usage for c in form._cells if c.usage and c.usage[1] == "code_keyword"]
    assert code == [("role", "code_keyword", "dark"), ("role", "code_keyword", "light")]


def test_the_message_lines_keep_their_space_and_a_spinner_shows_while_a_probe_runs(qapp, tmp_path):
    qapp_ref[0] = qapp
    editor, view, renders = make_view(tmp_path)
    assert view.usage_label.isVisibleTo(view) and view.usage_label.minimumHeight() > 0
    assert view.status.isVisibleTo(view) and view.status.minimumHeight() > 0
    assert not view.spinner.isVisibleTo(view.image)             # nothing under way
    view.show_usage("role", "block_title_fill", "light")
    assert view.spinner.isVisibleTo(view.image)                 # the probe runs
    assert wait_for(qapp, lambda: view._map() is not None)
    assert wait_for(qapp, lambda: not view.spinner.isVisibleTo(view.image))
    view.close()


def test_a_field_with_a_value_of_its_own_looks_edited(qapp):
    editor = LatexPlainTextEdit(ThemeManager())
    editor.set_text(read(SHIPPED))
    form = ThemeForm(editor, SHIPPED, ROOT / "example", ROOT / "latex" / "SlideMage_setup.tex")
    cell = next(c for c in form._cells if c.usage == ("palette", "c_primary_highlight", "light"))
    cell.edit.setText("")
    assert not cell.edit.property("edited")
    cell.edit.setText("#123456")
    assert cell.edit.property("edited") is True


# --- the way back: a click on the slide ---------------------------------------------------------------------------

def test_a_click_on_the_slide_tells_the_role_and_asks_where_several_are(qapp, tmp_path, monkeypatch):
    from PySide6.QtCore import QPoint, QPointF
    from slidemage.ui import layout_settings
    monkeypatch.setattr(layout_settings, "set", lambda key, value: None)
    qapp_ref[0] = qapp
    editor, view, renders = make_view(tmp_path)
    view.set_pick("color")
    picked, asked = [], []
    view.picked.connect(lambda kind, name: picked.append((kind, name)))
    view._choose = lambda labels, at: asked.append(labels) or 1
    view.show_page(3)
    assert renders == ["probe"]                         # no probe before the mouse comes to the slide
    view.pick_at((0.5, 0.7), QPoint(0, 0))              # the map is not there yet: the click waits for it
    assert picked == [] and "Finding the colors" in view.usage_label.text()
    assert wait_for(qapp, lambda: picked)
    assert picked == [("role", "link")] and asked == [] and view.usage_label.text() == ""      # one thing: no menu
    view.pick_at((0.2, 0.2), QPoint(0, 0))              # text on a fill: the menu, the topmost first
    assert asked == [["Block title text", "Block title fill"]] and picked[-1] == ("role", "block_title_fill")
    view._choose = lambda labels, at: None              # the menu closed without a pick
    view.pick_at((0.2, 0.2), QPoint(0, 0))
    assert len(picked) == 2
    view.pick_at((0.9, 0.95), QPoint(0, 0))             # nothing a role sets
    assert len(picked) == 2 and "No color role" in view.usage_label.text()
    view.show_page(2)                                   # the note goes with the page
    assert view.usage_label.text() == ""
    view.pick_at(None, QPoint(0, 0))                    # beside the page
    assert len(picked) == 2
    # the label's point to the page's fractions: the picture is centred in its label
    view.show_page(3)
    pixmap = view.image.pixmap()
    left = (view.image.width() - pixmap.width()) / 2
    top = (view.image.height() - pixmap.height()) / 2
    x, y = view._fraction(QPointF(left + pixmap.width() / 2, top + pixmap.height() * 0.25))
    assert (x, y) == pytest.approx((0.5, 0.25), abs=0.01)
    assert view._fraction(QPointF(left + pixmap.width() / 2, top - 3)) is None if top >= 3 else True
    view._hover((0.5, 0.7))
    assert view.image.toolTip() == "Links"
    view._hover(None)
    assert view.image.toolTip() == ""
    view.close()


GEOMETRY = {"page_width": 400.0, "page_height": 200.0, "SMTitleBarBottom": 30.0, "SMTopMargin": 45.0,
            "SMFooterBoxHeight": 10.0, "SMTextMarginLeft": 20.0, "SMTextMarginRight": 25.0, "SMLeftMargin": 12.0,
            "SMFrametitleRightPadding": 8.0, "SMLogoHeight": 14.0, "SMLogoWidth": 40.0}


def test_the_layout_settings_of_a_point_of_the_slide():
    at = lambda x, y: theme_measures.keys_at(x, y, GEOMETRY)
    assert at(200, 195)[0] == "SMFooterBoxHeight"
    assert at(5, 10)[0] == "SMFrametitleLeftPadding" and at(390, 10)[:2] == ["SMLogoHeight", "SMFrametitleRightPadding"]
    assert at(200, 10) == list(theme_measures.TITLE_BAR_KEYS)
    assert at(200, 40) == ["SMTopMargin"]               # between the title bar and the first line
    assert at(10, 100) == ["SMTextMarginLeft"] and at(390, 100) == ["SMTextMarginRight"]
    assert at(30, 180) == ["SMTextMarginLeft", "SMTopMargin", "SMTextMarginRight", "SMBodyFontSize"]   # the nearest first
    assert theme_measures.keys_at(1, 1, {}) == []
    assert theme_measures.logo_rect(GEOMETRY) == (352.0, 16.0, 392.0, 30.0)     # at the bar's bottom, the padding away
    assert theme_measures.on_logo(370, 20, GEOMETRY) and not theme_measures.on_logo(340, 20, GEOMETRY)
    assert not theme_measures.on_logo(370, 20, {key: value for key, value in GEOMETRY.items() if key != "SMLogoWidth"})


def test_a_click_in_layout_mode_tells_the_layout_setting(qapp, tmp_path, monkeypatch):
    from PySide6.QtCore import QPoint
    from slidemage.ui import layout_settings
    monkeypatch.setattr(layout_settings, "set", lambda key, value: None)
    qapp_ref[0] = qapp
    editor, view, renders = make_view(tmp_path)
    view.geometry = dict(GEOMETRY)
    view.set_pick("layout")
    picked, asked = [], []
    view.picked.connect(lambda kind, name: picked.append((kind, name)))
    view._choose = lambda labels, at: asked.append(labels) or 0
    view.show_page(2)
    view.pick_at((0.5, 0.2), QPoint(0, 0))              # y = 40 bp: the Top Margin alone
    assert picked == [("layout", "SMTopMargin")] and asked == []
    view.pick_at((0.5, 0.05), QPoint(0, 0))             # the title bar: what shapes it
    assert len(asked) == 1 and len(asked[0]) == len(theme_measures.TITLE_BAR_KEYS)
    assert picked[-1] == ("layout", "SMFrametitleTopPadding")
    view.show_page(1)                                   # the title slide has neither bar nor footer
    view.pick_at((0.5, 0.05), QPoint(0, 0))
    assert len(picked) == 2 and "pages 2 to 5" in view.usage_label.text()
    assert renders == ["probe"]                         # layout picks need no probe
    view.show_page(2)                                   # the logo is the logo, whatever a click selects
    view.pick_at((370 / 400, 20 / 200), QPoint(0, 0))
    assert picked[-1] == ("logo", "SMInstituteLogoPath") and len(asked) == 1
    view.set_pick("color")
    view.pick_at((370 / 400, 20 / 200), QPoint(0, 0))
    assert picked[-2:] == [("logo", "SMInstituteLogoPath")] * 2 and view.usage_label.text() == ""
    view._hover((370 / 400, 20 / 200))
    assert view.image.toolTip() == "Logo"
    view.close()


def test_the_form_goes_to_the_field_a_click_asked_for(qapp):
    editor = LatexPlainTextEdit(ThemeManager())
    editor.set_text(read(SHIPPED))
    form = ThemeForm(editor, SHIPPED, ROOT / "example", ROOT / "latex" / "SlideMage_setup.tex")
    told, measured = [], []
    form.on_usage = lambda *usage: told.append(usage)
    form.on_measure = lambda key, value: measured.append(key)
    form.show_tab("Layout")
    assert "Lists, links and marks" not in form._open_groups
    assert form.reveal("role", "alert")                 # a role in a folded group: opened, its cell there and told
    assert form.TABS[form._tab] == "Colors" and "Lists, links and marks" in form._open_groups
    assert any(c.usage == ("role", "alert", form.mode) for c in form._cells)
    assert told[-1] == ("role", "alert", form.mode)
    assert form.reveal("role", "code_keyword") and "Code panels" in form._open_groups
    assert not form.reveal("role", "no_such_role") and not form.reveal("role", "SMHighlightTitleTextColor")
    assert form.reveal("layout", "SMTopMargin")
    assert form.TABS[form._tab] == "Layout" and measured[-1] == "SMTopMargin"
    assert form.reveal("layout", "SMFooterTextSize") and form.reveal("layout", "SMBodyFontSize")
    assert not form.reveal("layout", "SMNoSuchHook")
    assert form.reveal("logo", "SMInstituteLogoPath") and form.TABS[form._tab] == "Logo & notes"
    assert wait_for(qapp, lambda: form._logo_path.property("revealed") is True)
    assert form.reveal("layout", "SMTopMargin")
    cell = form.layout_fields["SMTopMargin"]
    assert wait_for(qapp, lambda: cell.property("revealed") is True)       # tinted for a moment



def test_the_slide_background_is_offered_only_where_nothing_else_is(qapp, tmp_path, monkeypatch):
    from slidemage.ui import layout_settings
    monkeypatch.setattr(layout_settings, "set", lambda key, value: None)
    qapp_ref[0] = qapp
    editor, view, renders = make_view(tmp_path)
    view.set_pick("color")
    usage = theme_probe.UsageMap("role", view.mode, ["canvas", "bullet"])
    usage.pages = [[[theme_probe.Box(0, 0, 1, 1, True, 1)], [theme_probe.Box(0.1, 0.1, 0.2, 0.2, False, 2)]]] * 3
    view._maps[view._role_key()] = usage
    assert [name for _kind, name, _label in view._found((0.15, 0.15))] == ["bullet"]
    assert [name for _kind, name, _label in view._found((0.5, 0.5))] == ["canvas"]
    view.close()


def test_the_wheel_over_a_dropdown_of_the_form_does_not_change_it(qapp):
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QWheelEvent
    from PySide6.QtWidgets import QComboBox
    editor = LatexPlainTextEdit(ThemeManager())
    editor.set_text(read(SHIPPED))
    form = ThemeForm(editor, SHIPPED, ROOT / "example", ROOT / "latex" / "SlideMage_setup.tex")
    form.resize(700, 500)
    form.show()
    combos = [c for c in form.pages.findChildren(QComboBox) if c.count() > 1]
    assert len(combos) > 3 and form._footnote_style in combos
    for combo in (form._footnote_style, combos[0]):
        combo.setFocus()                    # even with the focus, where Qt would turn the entries
        before = combo.currentIndex()
        for delta in (-120, 120):
            event = QWheelEvent(QPointF(5, 5), QPointF(combo.mapToGlobal(QPoint(5, 5))), QPoint(0, 0),
                                QPoint(0, delta), Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                                Qt.ScrollPhase.NoScrollPhase, False)
            qapp.sendEvent(combo, event)
            assert combo.currentIndex() == before and not event.isAccepted()
    form.close()


def test_a_click_on_a_footnote_marker_goes_to_the_marker_setting(qapp, tmp_path, monkeypatch):
    from PySide6.QtCore import QPoint
    from slidemage.ui import layout_settings
    monkeypatch.setattr(layout_settings, "set", lambda key, value: None)
    geometry = dict(GEOMETRY, footnote_marks=[(2, 100.0, 60.0, 104.0, 65.0)])
    assert theme_measures.on_footnote_mark(2, 102, 62, geometry) and theme_measures.on_footnote_mark(2, 99, 66, geometry)
    assert not theme_measures.on_footnote_mark(3, 102, 62, geometry) and not theme_measures.on_footnote_mark(2, 110, 62, geometry)
    assert not theme_measures.on_footnote_mark(2, 102, 62, GEOMETRY)
    qapp_ref[0] = qapp
    editor, view, renders = make_view(tmp_path)
    view.geometry = geometry
    picked = []
    view.picked.connect(lambda kind, name: picked.append((kind, name)))
    view.show_page(2)
    for pick in ("layout", "color"):
        view.set_pick(pick)
        view.pick_at((102 / 400, 62 / 200), QPoint(0, 0))
    assert picked == [("footnotes", "SMSetFootnoteMarkers")] * 2
    view.close()
    form_editor = LatexPlainTextEdit(ThemeManager())
    form_editor.set_text(read(SHIPPED))
    form = ThemeForm(form_editor, SHIPPED, ROOT / "example", ROOT / "latex" / "SlideMage_setup.tex")
    assert form.reveal("footnotes", "SMSetFootnoteMarkers") and form.TABS[form._tab] == "Logo & notes"
    assert wait_for(qapp, lambda: form._footnote_style.property("revealed") is True)
