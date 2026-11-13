# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Where a colour is used on the sample slides (theme_probe; docs/plans/theme-editor.md, section 3.3, stage C1c part 2):
the probe lines, the boxes read from the PDF, a real probe render, the sample panel's dimming and page jump, and the theme form telling
it which colour field has the focus."""
import os
import shutil
from pathlib import Path
from types import SimpleNamespace

import pymupdf
import pytest

from conftest import EXAMPLE_PROJECT
from slidemage import theme_probe, theme_sample
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
    title = usage.boxes(1, "title_fill")
    assert theme_probe.Box(0, 0, 0.75, 0.2, True) in title and theme_probe.Box(0.1, 0.4, 0.3, 0.6, True) in title
    assert len(title) == 2
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
    assert bar.exact and (bar.x0, bar.y0) == (0, 0) and 0.85 < bar.x1 < 1 and 0.05 < bar.y1 < 0.15
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
        usage = theme_probe.UsageMap(kind, mode, ["block_title_fill", "text", "link"])
        for page in range(1, 4):
            top = [theme_probe.Box(0, 0, 1, 4 / 9, True)]            # the top four ninths are the role's
            word = [theme_probe.Box(0.25, 0.6, 0.75, 0.8, False)]     # and a piece of text lower down is a link
            usage.pages.append([top, [], word] if page in pages_with_role else [[], [], []])
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
