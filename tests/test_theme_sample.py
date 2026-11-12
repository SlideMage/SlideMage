# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The theme sample deck and its render with a theme as edited (theme_sample; docs/plans/theme-editor.md, section 3.3,
stage C1c), the sample slides panel above the theme form (ui/workspace/theme_sample_view.py), and "New theme…"
(themes.new_theme, Settings -> Extensions -> Themes)."""
import os
import shutil
from pathlib import Path
from types import SimpleNamespace

import pymupdf
import pytest
from PySide6.QtWidgets import QMessageBox

from conftest import EXAMPLE_PROJECT
from slidemage import slide_templates, theme_sample, themes
from slidemage.ui.kit.theme import ThemeManager
from slidemage.ui.workspace.source_editor import LatexPlainTextEdit
from slidemage.ui.workspace.theme_sample_view import ThemeSampleView, pdf_pages
from slidemage.ui.workspace.window import WorkspaceWindow

ROOT = Path(__file__).resolve().parents[1]
GRAYSCALE = ROOT / "latex" / "SlideMage_template_grayscale.tex"
TEX = pytest.mark.skipif(not os.environ.get("SLIDEMAGE_TEX_TESTS") or not shutil.which("lualatex"),
                         reason="compiles with lualatex: SLIDEMAGE_TEX_TESTS=1")


# --- the deck ---------------------------------------------------------------------------------------------------------

def test_the_deck_gets_its_mode_and_theme_lines(tmp_path):
    text = theme_sample.deck_text("my-look", "dark", tmp_path)
    assert "\\newcommand{\\SMModeOverride}{dark}" in text and "\\input{SlideMage_template_my-look}" in text
    assert f"\\graphicspath{{{{{tmp_path.as_posix()}/}}}}" in text
    assert "%MODE%" not in text and "%THEME%" not in text
    assert "SMModeOverride" not in theme_sample.deck_text("my-look", "", tmp_path)
    assert text.count("\\begin{frame}") + text.count("frame}{") >= 1
    assert len(theme_sample.PAGES) == 7


def test_prepare_writes_the_buffer_as_the_theme_and_puts_it_first(tmp_path):
    work = theme_sample.work_dir(tmp_path / ".build", "my-look", "dark")
    deck = theme_sample.prepare(work, "% the buffer\n", "my-look", "dark", tmp_path)
    assert deck.parent == work and (work / "snippet.tex").is_file()
    assert (work / "SlideMage_template_my-look.tex").read_text(encoding="utf-8") == "% the buffer\n"
    paths = theme_sample.texinputs(work, tmp_path, {"TEXINPUTS": "rest"}).split(os.pathsep)
    assert paths[0] == str(work) and paths[1] == str(tmp_path) and paths[-1] == "rest"


@TEX
def test_the_sample_deck_compiles_in_each_mode():
    text = GRAYSCALE.read_text(encoding="utf-8")
    light = theme_sample.render(EXAMPLE_PROJECT, text, "probe", "")
    dark = theme_sample.render(EXAMPLE_PROJECT, text, "probe", "dark")
    assert light.pdf and dark.pdf, (light.log, dark.log)
    with pymupdf.open(light.pdf) as one, pymupdf.open(dark.pdf) as two:
        assert one.page_count == two.page_count == len(theme_sample.PAGES)
        corner = lambda doc: doc[1].get_pixmap(dpi=20).pixel(5, 60)        # the canvas below the title bar
        assert corner(one) == (255, 255, 255) and corner(two)[0] < 100
    broken = theme_sample.render(EXAMPLE_PROJECT, text.replace("\\input{SlideMage_base}", "\\undefinedmacro"),
                                 "probe", "")
    assert broken.pdf is None and broken.log


# --- the panel --------------------------------------------------------------------------------------------------------

def sample_pdf(path: Path, pages: int = 3) -> Path:
    doc = pymupdf.open()
    for _ in range(pages):
        doc.new_page(width=160, height=90)
    doc.save(path)
    doc.close()
    return path


def make_view(tmp_path, text=None, render=None):
    editor = LatexPlainTextEdit(ThemeManager())
    editor.set_text(text if text is not None else GRAYSCALE.read_text(encoding="utf-8").replace("\r\n", "\n"))
    calls = []

    def fake(project, text, key, mode, cancel=None):
        calls.append((key, mode))
        return theme_sample.SampleResult(sample_pdf(tmp_path / f"s{len(calls)}.pdf"), "", mode)
    view = ThemeSampleView(editor, "probe", SimpleNamespace(root=tmp_path), render or fake)
    return editor, view, calls


def wait_for(qapp, condition, tries=200):
    import time
    for _ in range(tries):
        qapp.processEvents()
        if condition():
            return True
        time.sleep(0.01)
    return False


def test_the_panel_offers_the_modes_and_renders_when_shown(qapp, tmp_path):
    editor, view, calls = make_view(tmp_path)
    assert [view.mode_combo.itemText(i) for i in range(view.mode_combo.count())] == ["Light", "Dark slides"]
    view.start()
    assert calls == []                      # not on show: nothing renders
    view.resize(400, 300)
    view.show()
    assert wait_for(qapp, lambda: view._images)
    assert calls == [("probe", "light")] and len(view._images) == 3
    assert view.page_label.text().startswith("Page 2 of 3")
    view.show_page(9)
    assert view._page == 3 and not view.next.isEnabled()
    view.mode_combo.setCurrentIndex(1)
    view.mode_combo.activated.emit(1)
    assert wait_for(qapp, lambda: len(calls) == 2) and calls[-1] == ("probe", "dark")
    view.close()


def test_a_change_during_a_render_renders_again_after_it(qapp, tmp_path):
    editor, view, calls = make_view(tmp_path)
    view.resize(400, 300)
    view.show()
    assert wait_for(qapp, lambda: view._images)
    view._cancel = SimpleNamespace(request_stop=lambda wait: None)        # as if one were running
    view.start()
    assert view._again and len(calls) == 1
    view._on_rendered(theme_sample.SampleResult(None, "", "light"))      # the running one ends: the next starts
    assert wait_for(qapp, lambda: len(calls) == 2)
    view.close()


def test_a_failed_render_says_why(qapp, tmp_path):
    editor, view, _calls = make_view(
        tmp_path, render=lambda *a, **k: theme_sample.SampleResult(None, "! Undefined control sequence.\nl.12", ""))
    view.resize(400, 300)
    view.show()
    assert wait_for(qapp, lambda: "does not compile" in view.status.text())
    assert "Undefined control sequence" in view.status.text() and "l.12" in view.status.toolTip()
    view.close()


def test_typing_adds_a_mode_to_the_picker(qapp, tmp_path):
    editor, view, _calls = make_view(tmp_path, text="\\input{SlideMage_setup}\n\\input{SlideMage_base}\n")
    assert view.mode_combo.isHidden() and view.mode == ""
    editor.patch_text("% SlideMage modes: light, dusk=Dusk\n\\input{SlideMage_setup}\n\\SMDeclareMode{light}{}\n"
                      "\\SMDeclareMode{dusk}{dark}\n\\input{SlideMage_base}\n")
    assert [view.mode_combo.itemText(i) for i in range(view.mode_combo.count())] == ["Light", "Dusk"]
    assert view._timer.isActive()


def test_pdf_pages(tmp_path):
    images = pdf_pages(sample_pdf(tmp_path / "x.pdf", 2), dpi=72)
    assert len(images) == 2 and images[0].width() == 160


# --- New theme… -------------------------------------------------------------------------------------------------------

def test_check_new_key(tmp_path, monkeypatch):
    monkeypatch.setattr(themes, "installed_dirs", lambda: [tmp_path / "installed" / "uni-x"])
    (tmp_path / "SlideMage_template_mine.tex").write_text("x", encoding="utf-8")
    assert themes.check_new_key("my-look", tmp_path) == ""
    for bad in ("x", "My-look", "1abc", "slidemage", "grayscale", "mine", "uni-x"):
        assert themes.check_new_key(bad, tmp_path), bad


def test_new_theme_copies_a_shipped_template_with_its_name(tmp_path, monkeypatch):
    monkeypatch.setattr(themes, "installed_dirs", lambda: [])
    monkeypatch.setattr(slide_templates, "framework_dirs", lambda root: [ROOT / "latex"])
    path = themes.new_theme("my-look", "My Look", tmp_path, "grayscale")
    assert path == tmp_path / "SlideMage_template_my-look.tex"
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    shipped = GRAYSCALE.read_text(encoding="utf-8").replace("\r\n", "\n")
    assert "% SlideMage template name: My Look\n" in text
    assert text.replace("My Look", "Grayscale (Latin Modern Roman)") == shipped
    plain = themes.new_theme("plain-look", "", tmp_path)          # the SlideMage template has no name line: one is added
    assert "% SlideMage template name: plain-look" in plain.read_text(encoding="utf-8")
    with pytest.raises(themes.ThemeError):
        themes.new_theme("my-look", "Again", tmp_path)


def test_the_window_makes_and_opens_the_new_theme(tmp_path, monkeypatch):
    monkeypatch.setattr(themes, "installed_dirs", lambda: [])
    monkeypatch.setattr(slide_templates, "framework_dirs", lambda root: [ROOT / "latex"])
    steps, warned = [], []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: warned.append(a[2])))
    fake = SimpleNamespace(project=SimpleNamespace(root=tmp_path), log=lambda line: steps.append("log"),
                           open_theme_editor=lambda p: steps.append(("open", p.name)),
                           reload_decks=lambda: steps.append("reload"))
    WorkspaceWindow.new_theme(fake, "my-look", "My Look")
    assert steps == ["log", ("open", "SlideMage_template_my-look.tex"), "reload"] and warned == []
    WorkspaceWindow.new_theme(fake, "slidemage", "Mine")
    assert len(warned) == 1 and "ships" in warned[0]


def test_settings_new_theme_closes_the_sheet_then_makes_the_theme(qapp, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QWidget
    from slidemage.ui.dialogs.settings_plugins import PluginsTab

    class App(QWidget):
        def __init__(self):
            super().__init__()
            self.project = SimpleNamespace(root=tmp_path)
            self.theme = ThemeManager()
            self.made = []

        def new_theme(self, key, name, start):
            self.made.append((key, name, start))

    app, left = App(), []
    tab = PluginsTab(app, leave=lambda action: (left.append("leave"), action()))
    assert tab.new_theme_button.text() == "New theme…"
    monkeypatch.setattr(tab, "ask_new_theme", lambda: ("my-look", "My Look", "grayscale"))
    tab.new_theme_from_dialog()
    assert left == ["leave"] and app.made == [("my-look", "My Look", "grayscale")]
    monkeypatch.setattr(tab, "ask_new_theme", lambda: None)
    tab.new_theme_from_dialog()
    assert app.made == [("my-look", "My Look", "grayscale")]


@TEX
def test_the_progress_bars_track_follows_the_slide_background():
    """v0.16.30: the track behind a progress bar was mixed into white, a light band on a dark slide; it is mixed into
    the canvas now (the same in a light mode)."""
    text = (ROOT / "latex" / "SlideMage_template_slidemage.tex").read_text(encoding="utf-8")
    text = text.replace("\input{SlideMage_base}", "\SMProgressBarPosition{foot}\n\input{SlideMage_base}", 1)
    tracks = {}
    for mode in ("", "dark"):
        result = theme_sample.render(EXAMPLE_PROJECT, text, "track", mode)
        assert result.pdf, result.log
        with pymupdf.open(result.pdf) as doc:
            pix = doc[1].get_pixmap(dpi=72)
            canvas = pix.pixel(int(pix.width * 0.5), int(pix.height * 0.6))
            column = [pix.pixel(int(pix.width * 0.9), y) for y in range(pix.height - 12, pix.height)]
            # the track is the coloured (not grey) row at the bottom, right of the bar
            track = next(p for p in reversed(column) if max(p) - min(p) > 12)
            tracks[mode] = (canvas, track)
    (light_canvas, light_track), (dark_canvas, dark_track) = tracks[""], tracks["dark"]
    brightness = lambda p: sum(p) / 3
    assert brightness(light_track) > 180                                  # a light track on the white slide
    assert abs(brightness(dark_track) - brightness(dark_canvas)) < 40      # a dark track on the dark slide
