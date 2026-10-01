"""The slide editor's "Previous versions" dropdown and read-only frozen versions."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication

from slidemage import deck_editor
from slidemage.qt_slide_source_tab import SlideSourceTab, VERSIONS_COMBO_PLACEHOLDER
from slidemage.qt_theme import ThemeManager


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


def make_app(opened):
    return SimpleNamespace(theme=ThemeManager(), log=lambda _line: None,
                           open_slide_editor=lambda path, **kw: opened.append(path))


def test_dropdown_lists_frozen_versions_and_opens_them(qapp):
    opened = []
    current = deck_editor.SLIDES_DIR / "ZZZ-EN-Standard-content-current.tex"
    tab = SlideSourceTab(make_app(opened), current)
    labels = [tab.versions_combo.itemText(i) for i in range(tab.versions_combo.count())]
    assert labels[0] == VERSIONS_COMBO_PLACEHOLDER
    assert "v1.0.0" in labels
    assert tab.versions_combo.isEnabled()
    tab._on_version_chosen(labels.index("v1.0.0"))
    assert opened == [deck_editor.SLIDES_DIR / "ZZZ-EN-Standard-content-v1-0-0.tex"]
    assert tab.versions_combo.currentIndex() == 0
    assert not tab.widget.isReadOnly()


def test_frozen_version_opens_read_only_and_can_be_unlocked(qapp):
    frozen = deck_editor.SLIDES_DIR / "ZZZ-EN-Standard-content-v1-0-0.tex"
    tab = SlideSourceTab(make_app([]), frozen)
    assert tab.widget.isReadOnly()
    assert not hasattr(tab, "versions_combo")
    tab._on_unlock_frozen()
    assert not tab.widget.isReadOnly()
