"""Version choices in Add Slide should be directly usable."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication, QWidget

from slidemage import qt_add_slide_dialog
from slidemage.qt_add_slide_dialog import AddSlideDialog


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.mark.parametrize("mode", ["existing", "new", "duplicate"])
def test_unchecking_version_selects_conditional_slide(mode, monkeypatch, qapp):
    monkeypatch.setattr(qt_add_slide_dialog.slide_ids, "list_id_slugs", lambda: [])
    parent = QWidget()
    dialog = AddSlideDialog(parent, SimpleNamespace(), 0, "\t")
    if mode == "new":
        dialog.new_radio.click()
    elif mode == "duplicate":
        dialog.duplicate_radio.click()

    assert dialog._current_macro_version() == ("slide", None)
    assert all(cb.isChecked() and cb.isEnabled()
               for cb in dialog.condition_checks.values())

    dialog.condition_checks["during-course"].click()

    assert dialog._current_macro_version() == ("conditionalslide", None)
    assert [version for version, cb in dialog.condition_checks.items()
            if cb.isChecked()] == ["instructor", "after-course"]

    dialog.variant_combo.setCurrentText(r"\slide (current)")
    assert all(cb.isChecked() for cb in dialog.condition_checks.values())
    dialog.variant_combo.setCurrentText(r"\slidefinal (current)")
    assert all(not cb.isEnabled() for cb in dialog.condition_checks.values())
