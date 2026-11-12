# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""A theme's tab (docs/plans/theme-editor.md; its look: the mockup of 2026-11-12): the mode bar over everything, a
Form / Split / Source switch, and one splitter with the source, the sample slides and the form.

* Form (the default): the sample slides, large, beside the form; the source is hidden.
* Split: the source beside the form.
* Source: the source alone, as for any file.

The mode bar lists every colour mode the theme declares (an open list: light, dark, grey, colour-blind, projector...)
with what it starts from and how many values it sets itself; the mode picked there is the one the form shows and the
sample slides are rendered in. "+ Add mode..." adds one."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QSplitter, QVBoxLayout

from ...theme_form_model import PRESET_LABELS
from .. import layout_settings
from ..kit.tokens import SPACE
from ..kit.widgets import Button, SegmentedControl, Surface, caption
from .theme_form import ThemeForm, theme_key
from .theme_sample_view import ThemeSampleView

VIEW_KEY = "theme_view"         # this user's last view of a theme tab (layout_settings): form | split | source
VIEWS = (("form", "Form"), ("split", "Split"), ("source", "Source"))


class ModeBar(Surface):
    """One button per colour mode, the picked one checked; `on_pick(mode)` and `on_add()` are set by the workspace."""

    def __init__(self) -> None:
        super().__init__()
        self.on_pick = lambda _mode: None
        self.on_add = lambda: None
        self._row = QHBoxLayout(self)
        self._row.setContentsMargins(0, 0, 0, 0)
        self._row.setSpacing(SPACE.sm)
        self.buttons: dict[str, QPushButton] = {}

    def show_modes(self, form: ThemeForm) -> None:
        while self._row.count():
            item = self._row.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        self.buttons = {}
        model = form.model
        if model is None or not model.readable:
            return
        self._row.addWidget(caption("Colour mode"))
        modes = model.modes()
        for index, mode in enumerate(modes):
            if not mode.id:
                note = "no modes yet"
            elif index == 0:
                note = "base"
            else:
                start = f"{PRESET_LABELS.get(mode.derive, mode.derive)} preset" if mode.derive else "from the base"
                count = model.set_count(mode.id)
                note = f"{start} · {count} set"
            button = QPushButton(f"{mode.label}\n{note}")
            button.setCheckable(True)
            button.setChecked(mode.id == form.mode)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setToolTip(f"Show the theme in {mode.label}: the form's values and the sample slides")
            # The picked mode stands out: a ring in the selection colour (both themes), the others a hairline.
            button.setStyleSheet("QPushButton { text-align: left; padding: 4px 12px; border: 1px solid "
                                 "rgba(128,128,128,0.45); border-radius: 8px; }"
                                 "QPushButton:checked { border: 2px solid palette(highlight); }")
            button.clicked.connect(lambda _=False, m=mode.id: self.on_pick(m))
            self._row.addWidget(button)
            self.buttons[mode.id] = button
        add = Button("+ Add mode…", "secondary", compact=True)
        add.setToolTip("Add a colour mode: from the dark, grey or colour-blind preset, or from the base mode")
        add.clicked.connect(lambda: self.on_add())
        self._row.addWidget(add)
        self._row.addStretch(1)


class ThemeWorkspace(Surface):
    """The theme part of a SourceFile: `editor` is the file's editor, moved into this widget's splitter."""

    def __init__(self, editor, path: Path, project, setup_path: Optional[Path]) -> None:
        super().__init__()
        self.editor = editor
        self.form = ThemeForm(editor, path, project.root, setup_path)
        self.sample = ThemeSampleView(editor, theme_key(path), project)
        self.sample.follow_mode_bar()
        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        top = Surface()
        row = QHBoxLayout(top)
        row.setContentsMargins(SPACE.lg, SPACE.sm, SPACE.lg, SPACE.sm)
        row.setSpacing(SPACE.lg)
        self.mode_bar = ModeBar()
        self.mode_bar.on_pick = self.pick_mode
        self.mode_bar.on_add = self.form.add_mode
        row.addWidget(self.mode_bar, 1)
        self.view_switch = SegmentedControl(VIEWS, current="form")
        self.view_switch.changed.connect(self.set_view)
        row.addWidget(self.view_switch)
        column.addWidget(top)
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.addWidget(editor)
        self.splitter.addWidget(self.sample)
        self.splitter.addWidget(self.form)
        self.splitter.setStretchFactor(0, 3)
        self.splitter.setStretchFactor(1, 3)
        self.splitter.setStretchFactor(2, 2)
        column.addWidget(self.splitter, 1)
        # The form tells when its modes or the picked mode change; the usage of a focused colour goes to the slides.
        self.form.on_structure = self._sync
        self.form.on_usage = self.sample.show_usage
        self.form.on_usage_cleared = self.sample.clear_usage
        self._sync()
        view = layout_settings.get(VIEW_KEY, "form")
        self.set_view(view if view in dict(VIEWS) else "form")

    @property
    def view(self) -> str:
        return self._view

    def set_view(self, view: str) -> None:
        """Form, Split or Source (remembered for the next theme opened)."""
        self._view = view
        self.editor.setVisible(view in ("split", "source"))
        self.sample.setVisible(view == "form")
        self.form.setVisible(view != "source")
        self.mode_bar.setVisible(view != "source")
        self.view_switch.set_current(view)
        sizes = {"form": [0, 3000, 2000], "split": [3000, 0, 2000], "source": [5000, 0, 0]}[view]
        self.splitter.setSizes(sizes)
        layout_settings.set(VIEW_KEY, view)

    def pick_mode(self, mode: str) -> None:
        self.form.set_mode(mode)
        self._sync()

    def _sync(self) -> None:
        self.mode_bar.show_modes(self.form)
        self.sample.set_mode(self.form.mode)
