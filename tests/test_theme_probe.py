# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Where a colour is used on the sample slides (theme_probe; docs/plans/theme-editor.md, section 3.3, stage C1c part 2):
the probe lines, the pixel map, a real probe render, the sample panel's dimming and page jump, and the theme form telling
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
    before, _, after = probed.partition("% theme form: where each colour is used (probe render)\n")
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


def test_the_pixel_map_reads_probe_colours(tmp_path):
    pdf = tmp_path / "probe.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=144, height=72)          # 2 x 1 inch: at 72 dpi 144 x 72 pixels
    first, second = theme_probe.PROBES[0], theme_probe.PROBES[1]
    rgb = lambda h: tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    page.draw_rect(pymupdf.Rect(0, 0, 72, 72), color=None, fill=rgb(first))
    page.draw_rect(pymupdf.Rect(100, 20, 120, 40), color=None, fill=rgb(second))
    doc.new_page(width=144, height=72)
    doc.save(pdf)
    usage = theme_probe.usage_map(pdf, {first: "text", second: "link"}, "role", "", dpi=72)
    assert (usage.width, usage.height) == (144, 72) and len(usage.pages) == 2
    assert usage.pages_using("text") == [1] and usage.pages_using("link") == [1] and usage.pages_using("x") == []
    mask = usage.mask(1, "link")
    assert mask[30 * 144 + 110] == 255 and mask[30 * 144 + 10] == 0 and sum(mask) // 255 == pytest.approx(400, abs=60)
    assert not any(usage.mask(2, "text"))


@TEX
def test_a_real_probe_finds_the_block_titles_and_the_code_panel():
    text = read(SHIPPED)
    probed, mapping = theme_probe.probe_text(text, "role", "")
    result = theme_sample.render(EXAMPLE_PROJECT, probed, "probe--role", "")
    assert result.pdf, result.log
    usage = theme_probe.usage_map(result.pdf, mapping, "role", "", dpi=60)
    assert usage.pages_using("block_title_fill") == [3]
    assert usage.pages_using("code_panel") == [4]
    assert 2 in usage.pages_using("text") and 3 in usage.pages_using("info_block_title_fill")


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

    def fake_read(pdf, mapping, kind, mode, dpi):
        usage = theme_probe.UsageMap(kind, mode, ["block_title_fill", "text"], 16, 9)
        for page in range(1, 4):
            grid = bytearray(16 * 9)
            if page in pages_with_role:
                grid[0:16 * 4] = b"\x01" * (16 * 4)         # the top four rows are the role's
            usage.pages.append(bytes(grid))
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
    bottom = lit.pixelColor(80, 80)                       # outside the role: dimmed
    assert bottom.red() < plain.pixelColor(80, 80).red()
    assert lit.pixelColor(80, 5).red() == plain.pixelColor(80, 5).red()     # inside: as it is
    view.show_usage("role", "text", "light")
    assert "not used on the sample slides" in view.usage_label.text()
    view.clear_usage()
    assert view.usage_label.isHidden() and view._composite(plain) is plain
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
