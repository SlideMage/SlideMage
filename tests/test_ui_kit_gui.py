"""UI kit (slidemage.ui.kit): fonts, tokens, widgets and the debug gallery in
light and dark mode. No golden screenshots: the checks are structural
(non-empty render, fonts registered, icon ligatures draw a glyph)."""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QFont, QFontDatabase, QFontMetrics
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFrame, QLabel, QPushButton, QWidget

from slidemage.ui.kit import kit_qss
from slidemage.ui.kit import fonts as fonts_module
from slidemage.ui.kit.fonts import FONT_DIR, load_fonts
from slidemage.ui.kit.gallery import KitGallery
from slidemage.ui.kit.theme import ThemeManager
from slidemage.ui.kit.tokens import FONT_ICONS, FONT_MONO, FONT_SANS
from slidemage.ui.kit.widgets import (
    Chip,
    Field,
    IconLabel,
    ModalSheet,
    PopoverMenu,
    SegmentedControl,
    SplitButton,
    ThumbnailGrid,
    Toast,
    ToggleChip,
)


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    assert load_fonts()
    return app


@pytest.fixture
def theme(qapp):
    """A ThemeManager that never touches the settings file (set_dark() would
    persist the choice) nor the app-wide stylesheet: re-styling the whole
    app costs seconds once other tests have left many widgets alive, so tests
    style only the widget under test (see styled())."""
    return ThemeManager()


def styled(widget: QWidget, theme: ThemeManager, dark: bool) -> None:
    theme.dark = dark
    widget.setStyleSheet(theme._build_qss())


def test_font_files_are_bundled_and_registered(qapp):
    for name in ("Roboto-Regular.ttf", "Roboto-Medium.ttf", "Roboto-Bold.ttf", "Roboto-Italic.ttf", "Roboto-Black.ttf",
                 "Roboto[ital,wdth,wght].ttf", "RobotoMono-Regular.ttf", "RobotoMono-Bold.ttf", "RobotoMono-Italic.ttf",
                 "RobotoMono[wght].ttf", "RobotoMono-Italic[wght].ttf", "MaterialIcons-Regular.ttf"):
        assert (FONT_DIR / name).is_file() and name in fonts_module._FONT_FILES
    files = fonts_module._FONT_FILES
    assert max(i for i, n in enumerate(files) if "[" not in n) < min(i for i, n in enumerate(files) if "[" in n)
    families = QFontDatabase.families()
    for family in (FONT_SANS, FONT_MONO, FONT_ICONS):
        assert family in families
    assert {"Regular", "Medium", "Bold"} <= set(QFontDatabase.styles(FONT_SANS))
    # 600 is a real SemiBold (the variable font), not Medium made fatter, whose w and W show dark gaps on Windows
    assert "SemiBold" in QFontDatabase.styles(FONT_SANS) or "SemiBold" in QFontDatabase.styles(FONT_SANS + " SemiBold")
    assert load_fonts()  # idempotent


def test_icon_ligature_draws_a_single_glyph(qapp):
    font = QFont(FONT_ICONS)
    font.setPixelSize(20)
    metrics = QFontMetrics(font)
    # With ligatures the name is one 20 px glyph; without them it would be
    # the width of eleven letters.
    assert metrics.horizontalAdvance("expand_more") == metrics.horizontalAdvance("expand_less") > 0
    assert metrics.horizontalAdvance("expand_more") < metrics.horizontalAdvance("zzzzzz_nope") / 4
    label = IconLabel("more_vert")
    assert label.fontMetrics().horizontalAdvance(label.text()) > 0


@pytest.mark.parametrize("dark", [False, True], ids=["light", "dark"])
def test_form_controls_draw_their_images_from_files(theme, dark):
    """The arrows and ticks of combos, spin boxes, checkboxes and radio buttons are PNG files QSS points to."""
    theme.dark = dark
    sheet = theme._build_qss()
    urls = re.findall(r"url\(([^)]+)\)", sheet)
    assert {Path(u).name.split("-")[0] for u in urls} == set(kit_qss.KIT_ICONS)
    assert all(Path(u).is_file() and Path(u).with_name(Path(u).stem + "@2x.png").is_file() for u in urls)


def test_toggle_chip_is_a_checkable_button_that_follows_its_view(theme):
    chip = ToggleChip("During course", "during")
    styled(chip, theme, False)
    seen = []
    chip.toggled.connect(seen.append)
    chip.show()
    QTest.mouseClick(chip, Qt.MouseButton.LeftButton)
    assert chip.isChecked() and seen == [True] and chip.property("tone") == "during"
    chip.setEnabled(False)
    QTest.mouseClick(chip, Qt.MouseButton.LeftButton)
    assert chip.isChecked()


def test_segmented_control_emits_only_for_user_clicks(theme):
    control = SegmentedControl([("a", "A"), ("b", "B")], tones={"a": "instructor"})
    control.show()
    seen = []
    control.changed.connect(seen.append)
    assert control.current() == "a"
    control.set_current("b")
    assert control.current() == "b" and seen == []
    QTest.mouseClick(control._buttons["a"], Qt.MouseButton.LeftButton)
    assert control.current() == "a" and seen == ["a"]


def test_chip_tone_and_click(theme):
    chip = Chip("outdated", "warning", "warning")
    chip.show()
    clicks = []
    chip.clicked.connect(lambda: clicks.append(1))
    QTest.mouseClick(chip, Qt.MouseButton.LeftButton)
    chip.set_tone("error")
    assert clicks == [1] and chip.property("tone") == "error" and chip.text() == "outdated"


def test_popover_menu_triggers_and_skips_disabled(theme):
    menu = PopoverMenu()
    menu.add_header("Compile")
    menu.add_item("a", "Alpha", meta="Ctrl+1", icon="school")
    menu.add_item("off", "Off", enabled=False)
    menu.add_item("b", "Beta", tone="danger", swatch="#e4684b")
    seen = []
    menu.triggered.connect(seen.append)
    menu.popup_at(QPoint(10, 10))
    assert menu.isVisible() and len(menu._rows) == 3
    assert len(menu.findChildren(QFrame, kit_qss.MENU_SWATCH)) == 1
    QTest.keyClick(menu, Qt.Key.Key_Down)
    QTest.keyClick(menu, Qt.Key.Key_Down)  # skips the disabled row
    QTest.keyClick(menu, Qt.Key.Key_Return)
    assert seen == ["b"] and not menu.isVisible()
    menu.popup_at(QPoint(10, 10))
    QTest.mouseClick(menu._rows[0], Qt.MouseButton.LeftButton)
    assert seen == ["b", "a"]


def test_split_button_main_and_caret(theme):
    split = SplitButton("Compile")
    menu = PopoverMenu()
    menu.add_item("x", "X")
    split.set_menu(menu)
    split.show()
    clicks = []
    split.clicked.connect(lambda: clicks.append(1))
    QTest.mouseClick(split._main, Qt.MouseButton.LeftButton)
    assert clicks == [1]
    split._caret.click()
    assert menu.isVisible() and split._caret.text() == "expand_less"
    menu.close()
    assert split._caret.text() == "expand_more"
    replacement = PopoverMenu()
    split.set_menu(replacement)
    split._caret.setText("expand_less")
    menu.closed.emit()
    assert split._caret.text() == "expand_less"  # regression: a replaced menu must be disconnected
    replacement.closed.emit()
    assert split._caret.text() == "expand_more"


def test_toast_actions_and_auto_hide(theme):
    host = QWidget()
    host.resize(500, 300)
    host.show()
    toast = Toast(host)
    seen = []
    toast.action_triggered.connect(seen.append)
    toast.show_message("Removed 1y8", [("undo", "Undo")], timeout_ms=50)
    assert toast.isVisible() and toast.geometry().bottom() < host.height()
    assert abs(toast.geometry().center().x() - host.width() / 2) <= 1
    toast.findChild(QPushButton, kit_qss.TOAST_ACTION).click()
    assert seen == ["undo"] and not toast.isVisible()
    toast.show_message("Saved", timeout_ms=20)
    QTest.qWait(120)
    assert not toast.isVisible()


def test_modal_sheet_tabs_and_buttons(theme):
    sheet = ModalSheet("Settings")
    sheet.add_tab("One", QLabel("1"))
    assert sheet._tabs.isHidden()
    sheet.add_tab("Two", QLabel("2"))
    sheet.show()
    assert not sheet._tabs.isHidden()
    shown = []
    sheet.tab_changed.connect(shown.append)
    sheet.set_current_tab(1)
    assert sheet._stack.currentIndex() == 1 and sheet.current_tab() == 1 and shown == [1]
    sheet.add_button("Save", kind="primary", role="accept").click()
    assert sheet.result() == 1
    sheet.add_button("Cancel", role="reject")


def test_thumbnail_grid_chooses_one_and_emits_only_for_user_clicks(theme, tmp_path):
    from PySide6.QtGui import QColor, QPixmap

    picture = tmp_path / "x.png"
    pixmap = QPixmap(16, 9)
    pixmap.fill(QColor("red"))
    pixmap.save(str(picture))
    grid = ThumbnailGrid([("a", "A", picture), ("b", "B", picture), ("c", "C", tmp_path / "missing.png")], columns=2)
    styled(grid, theme, False)
    grid.show()
    seen = []
    grid.chosen.connect(seen.append)
    assert grid.current() == "a"
    grid.set_current("b")
    assert grid.current() == "b" and seen == []
    QTest.mouseClick(grid._tiles["c"], Qt.MouseButton.LeftButton)
    assert grid.current() == "c" and seen == ["c"] and not grid._tiles["a"].property("current")
    assert grid.grab().toImage().width() > 0
    field = Field("Frame", grid)
    assert field.label.text() == "Frame"


@pytest.mark.parametrize("dark", [False, True], ids=["light", "dark"])
def test_gallery_renders(theme, dark):
    gallery = KitGallery(theme)
    styled(gallery, theme, dark)
    gallery.show()
    QApplication.processEvents()
    image = gallery.grab().toImage()
    assert not image.isNull() and image.width() > 100 and image.height() > 100
    # Page background token reaches the pixels: the gallery is not blank.
    colors = {image.pixelColor(x, y).name() for x in range(0, image.width(), 9) for y in range(0, image.height(), 9)}
    assert len(colors) > 6
    assert theme.tokens.bg in colors or theme.colors["bg"] in colors
    # Icons are drawn from the bundled font, not as long fallback text.
    icon = gallery.findChildren(IconLabel)[0]
    assert icon.font().family() == FONT_ICONS
    assert icon.fontMetrics().horizontalAdvance(icon.text()) <= icon.width() + 4
    gallery.toast.show_message("hello", [("a", "Act")])
    assert gallery.grab().toImage().width() == image.width()
    gallery.close()


def test_segment_badge_shows_a_count_and_hides_at_zero(theme):
    control = SegmentedControl([("p", "Preview"), ("s", "Source")])
    styled(control, theme, False)
    control.show()
    badge = control._badges["s"]
    assert badge.isHidden()
    control.set_badge("s", 3)
    QApplication.processEvents()
    assert badge.isVisible() and badge.text() == "3" and control._buttons["s"].property("badge") is True
    assert badge.geometry().right() <= control._buttons["s"].geometry().width()
    control.set_badge("s", 120)
    assert badge.text() == "99+"
    control.set_badge("s", 0)
    assert badge.isHidden() and control._buttons["s"].property("badge") is False
    assert control.current() == "p"          # a badge is not a click
