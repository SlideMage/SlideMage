"""Compile -> "Build options…": the checkboxes the compile flows (compile_actions.py) and the
editor tabs read."""
from __future__ import annotations

from PySide6.QtWidgets import QCheckBox, QDialog, QDialogButtonBox, QVBoxLayout, QWidget

from ... import app_settings
from .state import WorkspaceState


class BuildOptionsDialog(QDialog):
    """The four checkboxes that sat in the old window's bottom row, now behind
    Compile -> "Build options…". The checkboxes keep their state while the
    dialog is closed, which is what the compile code reads."""

    def __init__(self, parent: QWidget, state: WorkspaceState) -> None:
        super().__init__(parent)
        self.setWindowTitle("Build options")
        layout = QVBoxLayout(self)

        self.appendix_toc_checkbox = QCheckBox("Generate appendix TOC")
        self.appendix_toc_checkbox.setToolTip(
            "Adds a clickable appendix (agenda + one thumbnail grid per "
            "chapter) at the end of every whole-deck compile -- Presenter, "
            "Instructor, During-course and After-course, each listing the "
            "slides its version shows -- but not to the per-chapter jobs."
        )
        # Persisted (app_settings.py, same local per-machine store dark
        # mode/tab-width/model-picker settings already use) -- unlike
        # auto_open just below, which stay hardcoded
        # per-launch defaults; direct instruction, 2026-09-16.
        self.appendix_toc_checkbox.setChecked(bool(app_settings.get(state.project, "appendix_toc", False)))
        self.appendix_toc_checkbox.toggled.connect(
            lambda checked: app_settings.set(state.project, "appendix_toc", checked))
        layout.addWidget(self.appendix_toc_checkbox)

        # Page compiles (Compile -> Selected pages…, partial_compile.py,
        # v5.35.0): swap the new pages into the version's whole-deck PDF, or
        # write them to a separate "<pdf>-pages-....pdf". Remembered.
        self.replace_pages_checkbox = QCheckBox("Pages replace theirs in the full PDF")
        self.replace_pages_checkbox.setToolTip(
            "With selected pages: put the newly compiled pages into that "
            "version's whole-deck PDF in place of the old ones. Off: write them to a "
            "separate PDF next to it.")
        self.replace_pages_checkbox.setChecked(bool(app_settings.get(state.project, "replace_pages", True)))
        self.replace_pages_checkbox.toggled.connect(
            lambda checked: app_settings.set(state.project, "replace_pages", checked))
        layout.addWidget(self.replace_pages_checkbox)

        self.auto_open_checkbox = QCheckBox("Auto-open generated PDFs")
        self.auto_open_checkbox.setChecked(True)
        layout.addWidget(self.auto_open_checkbox)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.accept)
        layout.addWidget(buttons)
