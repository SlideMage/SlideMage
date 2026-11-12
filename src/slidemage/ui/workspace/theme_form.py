# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
r"""The theme form (docs/plans/theme-editor.md, stages C1 and C2; its look: the mockup of 2026-11-12): five tabs
(Identity, Colours, Layout, Logo & notes, Advanced) for one colour mode at a time, the mode picked in the theme tab's
mode bar (theme_workspace). A colour row says where its value comes from in that mode (set here, a preset, the base
mode, the framework) and ends in a strip of small swatches, one per mode.

Form and source are two views of one buffer: an edit here goes into the editor as one undo step
(LatexPlainTextEdit.patch_text, through theme_form_model / theme_file, which change one line), so autosave, the conflict
bar and Ctrl+Z work as for typing; typing in the source shows here after a pause. Nothing is written to disk here."""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import QEvent, QObject, QTimer, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QColorDialog, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QGridLayout, QHBoxLayout, QLabel,
    QLineEdit, QMessageBox, QScrollArea, QStackedWidget, QTabBar, QVBoxLayout, QWidget,
)

from ... import slide_templates, theme_fields, theme_measures, theme_source_folder
from .. import layout_settings
from ...theme_form_model import (BULLETS, CODE_COLOURS, DERIVES, FOOTNOTE_STYLES, LAYOUT_SECTIONS, PRESET_LABELS,
                                 ROLE_SECTIONS,
                                 UNITS, ThemeModel, check_length, citation_formats, format_size_pair, layout_profiles,
                                 parse_size_pair, split_length)
from ..kit.tokens import SPACE
from ..kit.widgets import (Badge, Button, Card, Chip, ColorSwatchButton, SegmentedControl, Surface, caption,
                           text_label)

REFRESH_DELAY_MS = 400      # after the last keystroke in the source
DISPLAY_UNIT_KEY = "theme_display_unit"     # mm or pt: what the theme form shows lengths in (layout_settings)
FONT_SIZE_KEYS = frozenset({"SMBodyFontSize"})     # lengths that are font sizes: always pt


def theme_key(path: Path) -> str:
    """The key of a SlideMage_template_<key>.tex, "" for another file."""
    name = path.name
    prefix = slide_templates.TEMPLATE_PREFIX
    return name[len(prefix):-4] if name.startswith(prefix) and name.endswith(".tex") else ""


def _label(field_name: str) -> str:
    field = theme_fields.BY_NAME.get(field_name)
    return field.label if field else field_name


class _Swatch(ColorSwatchButton):
    """A colour beside a value; clicking it opens the colour picker."""

    def __init__(self) -> None:
        super().__init__("")
        self.setFixedWidth(30)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def show_colour(self, value: Optional[str]) -> None:
        if value:
            self.setText("")
            self.set_color(value)
            self.setToolTip(value)
        else:           # no colour: a role that is off ("none"), or one that takes the text's colour
            self.setStyleSheet("")
            self.setText("–")
            self.setToolTip("No colour of its own")


class _Cell(Surface):
    """One colour value in the picked mode: a swatch with what it comes to, the field with what the theme writes (empty:
    it follows, and the field's grey text says what), a tag saying where the value comes from, Reset when the mode sets
    it itself, and a strip of small swatches, one per mode, so differences between the modes show at a glance."""

    def __init__(self, form: "ThemeForm", read: Callable[[], tuple[Optional[str], str, Optional[str]]],
                 write: Callable[[Optional[str]], None], *, choices: list[str] | None = None,
                 picker: bool = True, enabled: bool = True,
                 usage: Optional[tuple[str, str, str]] = None,
                 source: Optional[tuple[str, str]] = None, strip_role: str = "") -> None:
        super().__init__()
        self.form, self.read, self.write = form, read, write
        self.usage = usage          # (kind, name, mode): what the sample slides light up while this cell is in focus
        self.source = source        # (kind, name) for the provenance tag: "palette", "role" or "optional"
        self.strip_role = strip_role
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(SPACE.xs)
        self.swatch = _Swatch()
        self.swatch.setEnabled(enabled and picker)
        self.swatch.clicked.connect(self._pick)
        row.addWidget(self.swatch)
        if choices is not None:
            self.combo = QComboBox()
            self.combo.setEditable(True)
            self.combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            self.combo.setMinimumContentsLength(10)
            self.combo.addItems([""] + choices)
            self.combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
            self.edit = self.combo.lineEdit()
            self.combo.activated.connect(lambda _i: self._commit())
            self.combo.setMaximumWidth(200)
            row.addWidget(self.combo)
            self.combo.setEnabled(enabled)
        else:
            self.combo = None
            self.edit = QLineEdit()
            self.edit.setMinimumWidth(90)
            self.edit.setMaximumWidth(130)
            row.addWidget(self.edit)
            self.edit.setEnabled(enabled)
        self.edit.editingFinished.connect(self._commit)
        self.tag = Chip("", "muted")
        row.addWidget(self.tag)
        self.reset = Button("Reset", "ghost", compact=True)
        self.reset.setToolTip("Take this mode's own value out: it follows again")
        self.reset.clicked.connect(lambda: self.form.apply(lambda: self.write(None)))
        self.reset.setEnabled(enabled)
        row.addWidget(self.reset)
        self.strip = QHBoxLayout()
        self.strip.setSpacing(3)
        self._dots: list[QLabel] = []
        row.addLayout(self.strip)
        row.addStretch(1)
        if usage is not None:
            self.edit.installEventFilter(self)
            if self.combo is not None:
                self.combo.installEventFilter(self)
        self.update_value()

    def eventFilter(self, watched, event) -> bool:
        if event.type() == QEvent.Type.FocusIn:
            self.form.focus_usage(self.usage)
        elif event.type() == QEvent.Type.FocusOut:
            self.form.blur_usage(self.usage)
        return super().eventFilter(watched, event)

    def enterEvent(self, event) -> None:
        super().enterEvent(event)
        if self.usage is not None:
            self.form.hover_usage(self.usage)

    def leaveEvent(self, event) -> None:
        super().leaveEvent(event)
        if self.usage is not None:
            self.form.hover_usage(None)

    def update_value(self) -> None:
        written, follows, colour = self.read()
        self.swatch.show_colour(colour)
        if not self.edit.hasFocus():
            self.edit.setText(written or "")
        self.edit.setPlaceholderText(follows)
        self.edit.setToolTip(f"Follows: {follows}" if not written else f"Written in the theme: {written}")
        model = self.form.model
        mode = self.usage[2] if self.usage else ""
        if self.source is None or model is None:
            self.tag.hide()
            self.reset.hide()
            return
        kind, name = self.source
        text, tone = model.provenance(kind, name, mode)
        self.tag.set_text(text)
        self.tag.set_tone(tone)
        self.tag.setVisible(bool(mode) or kind != "palette" or written is not None)
        self.reset.setVisible(written is not None and text in ("set here", "set in the theme"))
        strip_kind, strip_name = ("role", self.strip_role) if self.strip_role else (kind, name)
        if strip_kind == "optional":
            values = []
        else:
            values = model.strip(strip_kind, strip_name)
        if len(values) < 2:
            values = []
        while len(self._dots) < len(values):
            dot = QLabel()
            dot.setFixedSize(16, 16)
            self.strip.addWidget(dot)
            self._dots.append(dot)
        for index, dot in enumerate(self._dots):
            if index >= len(values):
                dot.hide()
                continue
            mode_id, label, value = values[index]
            ring = "2px solid palette(highlight)" if mode_id == mode else "1px solid rgba(128,128,128,0.6)"
            dot.setStyleSheet(f"background: {value or 'transparent'}; border: {ring}; border-radius: 4px;")
            dot.setToolTip(f"{label}: {value or 'no colour of its own'}")
            dot.show()

    def _commit(self) -> None:
        text = self.edit.text().strip()
        written, _, _ = self.read()
        if text == (written or ""):
            return
        self.form.apply(lambda: self.write(text or None))

    def _pick(self) -> None:
        _, _, colour = self.read()
        chosen = QColorDialog.getColor(QColor(colour or "#ffffff"), self, "Choose a colour")
        if chosen.isValid():
            self.form.apply(lambda: self.write(chosen.name()))


class ThemeForm(QWidget):
    """The form of one theme file, editing `editor`'s buffer, one colour mode at a time (`mode`, picked in the theme
    tab's mode bar: theme_workspace). `root` is the project; `setup_path` the framework's SlideMage_setup.tex (its
    catalog gives defaults and the roles). Five tabs: Identity, Colours, Layout, Logo & notes, Advanced."""

    TABS = ("Identity", "Colours", "Layout", "Logo & notes", "Advanced")

    def __init__(self, editor, path: Path, root: Path, setup_path: Optional[Path]) -> None:
        super().__init__()
        self.editor = editor
        self.path = path
        self.root = root
        self.setMinimumWidth(360)
        setup_text = setup_path.read_text(encoding="utf-8") if setup_path and setup_path.is_file() else ""
        self.home = theme_source_folder.home(path, root)    # where the theme's logos and layout profile live
        self.model = ThemeModel(editor.text(), root, theme_key(path), setup_text, self.home) if setup_text else None
        self.mode = self.model.base if self.model is not None else ""
        self._cells: list[_Cell] = []
        self._refreshers: list[Callable[[], None]] = []
        self.layout_fields: dict[str, QWidget] = {}
        self._shape: tuple = ()
        self._pushing = False
        self._tab = 1                                   # Colours: what most edits are about
        self._show_all_palette = False
        self._show_checks = False
        self._open_groups: set[str] = {"Title bar and footer"}
        # Told when the modes (or the picked one) change, so the mode bar and the sample slides follow (theme_workspace).
        self.on_structure: Optional[Callable[[], None]] = None
        # The sample slides' "where is this colour used" (theme_sample_view.ThemeSampleView.show_usage / clear_usage):
        # set by the source tab; the focused cell's colour, overridden while the mouse is over another cell.
        self.on_usage: Optional[Callable[[str, str, str], None]] = None
        self.on_usage_cleared: Optional[Callable[[], None]] = None
        # The marks of a focused length on the sample slides (C2b) and the geometry of the last render, set by the tab.
        self.on_measure: Optional[Callable[[str, Optional[float]], None]] = None
        self.on_measure_cleared: Optional[Callable[[], None]] = None
        self.geometry: Callable[[], dict] = dict
        unit = layout_settings.get(DISPLAY_UNIT_KEY, theme_measures.DEFAULT_DISPLAY_UNIT)
        self.display_unit = unit if unit in theme_measures.DISPLAY_UNITS else theme_measures.DEFAULT_DISPLAY_UNIT
        self._filters: list[QObject] = []
        self._focused_usage: Optional[tuple[str, str, str]] = None
        self._hovered_usage: Optional[tuple[str, str, str]] = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.tab_bar = QTabBar()
        self.tab_bar.setExpanding(False)
        self.tab_bar.setDrawBase(False)
        for name in self.TABS:
            self.tab_bar.addTab(name.replace("&", "&&"))     # "&" alone would be a shortcut mark
        self.tab_bar.currentChanged.connect(self._on_tab)
        outer.addWidget(self.tab_bar)
        self.pages = QStackedWidget()
        outer.addWidget(self.pages, 1)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(REFRESH_DELAY_MS)
        self._timer.timeout.connect(self._from_source)
        editor.text_changed.connect(self._on_source_changed)
        self.rebuild()

    # --- the buffer --------------------------------------------------------------------------------------------------

    def apply(self, change: Callable[[], None]) -> None:
        """Run an edit of the model and put its text into the editor (one undo step)."""
        if self.model is None or self.editor.is_read_only():
            return
        self.model.set_text(self.editor.text())
        try:
            change()
        except ValueError as exc:
            QMessageBox.warning(self, "Theme form", str(exc))
            return
        self._pushing = True
        try:
            self.editor.patch_text(self.model.text)
        finally:
            self._pushing = False
        if self._structure() != self._shape:
            self.rebuild()
        else:
            self.refresh()

    def _on_source_changed(self) -> None:
        if not self._pushing:
            self._timer.start()

    def _from_source(self) -> None:
        if self.model is None:
            return
        self.model.set_text(self.editor.text())
        if self._structure() != self._shape:
            self.rebuild()
        else:
            self.refresh()

    def _structure(self) -> tuple:
        """What the form's rows depend on: rebuilt when it changes, else only the values are."""
        if self.model is None:
            return ()
        modes = tuple((m.id, m.label, m.derive) for m in self.model.modes())
        if self.mode not in [m[0] for m in modes]:
            self.mode = modes[0][0]
        palette = tuple(n for n in self.model.palette_names() if self._show_all_palette or self.model.palette_matters(n))
        return (self.model.readable, modes, self.mode, palette, len(self.model.file.beyond()),
                self.model.footnote_style(), self.editor.is_read_only(), self._show_all_palette, self._show_checks,
                tuple(sorted(self._open_groups)))

    def set_mode(self, mode: str) -> None:
        """Show the colour mode `mode` (the mode bar's pick)."""
        if mode != self.mode:
            self.mode = mode
            self.rebuild()

    def show_tab(self, name: str) -> None:
        self.tab_bar.setCurrentIndex(self.TABS.index(name))

    def _on_tab(self, index: int) -> None:
        self._tab = index
        self.pages.setCurrentIndex(index)

    def focus_usage(self, usage: tuple[str, str, str]) -> None:
        self._focused_usage = usage
        self._tell_usage()

    def blur_usage(self, usage: tuple[str, str, str]) -> None:
        if self._focused_usage == usage:
            self._focused_usage = None
            self._tell_usage()

    def hover_usage(self, usage: Optional[tuple[str, str, str]]) -> None:
        self._hovered_usage = usage
        self._tell_usage()

    def _tell_usage(self) -> None:
        usage = self._hovered_usage or self._focused_usage
        if usage is not None and self.on_usage is not None:
            self.on_usage(*usage)
        elif usage is None and self.on_usage_cleared is not None:
            self.on_usage_cleared()

    def refresh(self) -> None:
        for cell in self._cells:
            cell.update_value()
        for refresher in self._refreshers:
            refresher()

    # --- building ----------------------------------------------------------------------------------------------------

    def rebuild(self) -> None:
        scrolls = [self.pages.widget(i).verticalScrollBar().value() for i in range(self.pages.count())]
        while self.pages.count():
            page = self.pages.widget(0)
            self.pages.removeWidget(page)
            page.deleteLater()
        self._cells, self._refreshers = [], []
        self.layout_fields = {}
        self._shape = self._structure()
        readable = self.model is not None and self.model.readable
        for index, name in enumerate(self.TABS):
            body = Surface()
            column = QVBoxLayout(body)
            column.setContentsMargins(SPACE.lg, SPACE.lg, SPACE.lg, SPACE.lg)
            column.setSpacing(SPACE.lg)
            if self.model is None:
                column.addWidget(caption("The framework's SlideMage_setup.tex was not found, so the form has no "
                                         "catalog to show. Edit the theme in the source."))
            elif not readable:
                column.addWidget(caption("This file does not \\input SlideMage_setup and then SlideMage_base, so it "
                                         "is no theme the form can read. Edit it in the source."))
            else:
                for widget in self._page(name):
                    column.addWidget(widget)
            column.addStretch(1)
            body.setEnabled(not self.editor.is_read_only())
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QScrollArea.Shape.NoFrame)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            scroll.setWidget(body)
            self.pages.addWidget(scroll)
            if index < len(scrolls):
                QTimer.singleShot(0, scroll, lambda s=scroll, v=scrolls[index]: s.verticalScrollBar().setValue(v))
        self.tab_bar.setCurrentIndex(self._tab)
        self.pages.setCurrentIndex(self._tab)
        if self.on_structure is not None:
            self.on_structure()

    def _page(self, name: str) -> list[QWidget]:
        if name == "Identity":
            return [self._intro(), self._identity()]
        if name == "Colours":
            widgets = [self._mode_heading(), self._checks(), self._palette()]
            widgets += [self._roles(title, roles) for title, roles in ROLE_SECTIONS]
            return widgets + [self._code()]
        if name == "Layout":
            return [self._unit_switch()] + [self._layout_card(title, note, keys) for title, note, keys in LAYOUT_SECTIONS]
        if name == "Logo & notes":
            return [self._logo(), self._footnotes()]
        return [caption("Frame types, fine list spacing, drawing helpers and the optional features (mini frames, "
                        "progress bar, divider frames, watermark) come here in a later step (C3). Until then they are "
                        "edited in the source: switch to Split or Source above.")]

    def _card(self, title: str, note: str = "") -> tuple[Card, QVBoxLayout]:
        card = Card()
        layout = card.layout()
        layout.addWidget(text_label(title, "heading"))
        if note:
            layout.addWidget(caption(note))
        return card, layout

    def _intro(self) -> QWidget:
        box = Surface()
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        beyond = self.model.file.beyond()
        note = ("Each change is one line of the theme's source, saved like typing; Ctrl+Z in the source takes it back. "
                "An empty field follows: its grey text says what it takes.")
        if beyond:
            note += (f" {len(beyond)} line{'s' if len(beyond) != 1 else ''} of the theme "
                     f"{'are' if len(beyond) != 1 else 'is'} beyond the form (conditionals, lines after the base, "
                     "commands it cannot show): they stay as they are.")
        layout.addWidget(caption(note))
        if beyond:
            show = Button("Show them in the source", "ghost", compact=True)
            show.clicked.connect(lambda: self.editor.go_to_line(beyond[0] + 1))
            layout.addWidget(show, 0, Qt.AlignmentFlag.AlignLeft)
        return box

    def _identity(self) -> QWidget:
        card, layout = self._card("Name and colour modes")
        form = QFormLayout()
        name = QLineEdit(self.model.name())
        name.setMaxLength(40)
        name.setPlaceholderText(self.model.key)
        name.editingFinished.connect(lambda: name.text().strip() != self.model.name()
                                     and self.apply(lambda: self.model.set_name(name.text())))
        form.addRow("Name", name)
        form.addRow("Key", text_label(self.model.key or self.path.stem, "mono"))
        layout.addLayout(form)
        modes = self.model.modes()
        if modes[0].id:
            for index, mode in enumerate(modes):
                line = QHBoxLayout()
                what = "the base mode" if index == 0 else (
                    f"starts from the {PRESET_LABELS.get(mode.derive, mode.derive)} preset" if mode.derive
                    else "starts from the base mode")
                line.addWidget(text_label(f"{mode.label}  ·  {mode.id}, {what}"), 1)
                if index:
                    remove = Button("Remove", "ghost", compact=True)
                    remove.setToolTip(f"Take the mode {mode.id} out, with every line of it")
                    remove.clicked.connect(lambda _=False, m=mode.id: self._remove_mode(m))
                    line.addWidget(remove)
                layout.addLayout(line)
        else:
            layout.addWidget(caption("The theme has no colour modes: one set of colours. Add one to give decks a dark "
                                     "(or a grey, colour-blind, projector...) version of it."))
        mismatch = self.model.header_mismatch()
        if mismatch:
            layout.addWidget(caption(mismatch, "error"))
        add = Button("Add a colour mode…", "secondary", compact=True)
        add.clicked.connect(self.add_mode)
        layout.addWidget(add, 0, Qt.AlignmentFlag.AlignLeft)
        return card

    def add_mode(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("Add a colour mode")
        form = QFormLayout(dialog)
        taken = [m.id for m in self.model.modes()]
        mode_id = QLineEdit("dark" if "dark" not in taken else "")
        label = QLineEdit("Dark slides" if mode_id.text() else "")
        derive = QComboBox()
        names = {"dark": "The dark preset: derived from the palette", "grey": "The grey preset: every colour in grey",
                 "colorblind": "The colour-blind preset: Okabe–Ito accents", "": "Nothing: the base mode's colours"}
        for value in DERIVES:
            derive.addItem(names[value], value)
        form.addRow("Name (id)", mode_id)
        form.addRow("Shown in SlideMage as", label)
        form.addRow("Start from", derive)
        form.addRow(caption("A mode changes colours only (and the logo); fonts, margins and bullets stay the theme's. "
                            "Name it for what it is for: projector, print, high contrast..."))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            new = mode_id.text().strip()
            self.apply(lambda: self.model.add_mode(new, derive.currentData(), label.text()))
            if new in [m.id for m in self.model.modes()]:
                self.set_mode(new)

    def _remove_mode(self, mode_id: str) -> None:
        answer = QMessageBox.question(self, "Remove a colour mode",
                                      f"Take the mode {mode_id} out of the theme, with every line of it? "
                                      "Ctrl+Z in the source brings it back.")
        if answer == QMessageBox.StandardButton.Yes:
            self.apply(lambda: self.model.remove_mode(mode_id))

    def _mode_heading(self) -> QWidget:
        """Which mode the Colours tab shows, and what it starts from."""
        mode = next((m for m in self.model.modes() if m.id == self.mode), self.model.modes()[0])
        if not mode.id:
            text = "The theme's colours (it has no colour modes; add one under Identity)."
        elif mode.id == self.model.base:
            text = f"{mode.label}: the base mode. Every other mode starts from these colours."
        else:
            start = (f"the {PRESET_LABELS.get(mode.derive, mode.derive)} preset" if mode.derive else "the base mode")
            text = (f"{mode.label}: starts from {start}; {self.model.set_count(mode.id)} value"
                    f"{'s' if self.model.set_count(mode.id) != 1 else ''} set here. An empty field follows.")
        return caption(text)

    def _checks(self) -> QWidget:
        """The contrast checks of the picked mode as one line, the details on request, and the other modes' count."""
        box = Surface()
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACE.sm)
        line = QHBoxLayout()
        chip = Chip("", "ok", elide=True)
        line.addWidget(chip, 1)
        toggle = Button("", "ghost", compact=True)
        toggle.clicked.connect(lambda: self._toggle_checks())
        line.addWidget(toggle)
        others = Button("", "ghost", compact=True)
        line.addWidget(others)
        layout.addLayout(line)
        grid = QGridLayout()
        grid.setHorizontalSpacing(SPACE.md)
        grid.setVerticalSpacing(SPACE.xs)
        badges: list[Badge] = []
        if self._show_checks:
            for row, check in enumerate(self.model.checks(self.mode)):
                grid.addWidget(text_label(check.label, "body"), row, 0)
                badge = Badge("")
                grid.addWidget(badge, row, 1, Qt.AlignmentFlag.AlignLeft)
                badges.append(badge)
        layout.addLayout(grid)
        self._other_mode_target: Optional[str] = None
        others.clicked.connect(lambda: self._other_mode_target and self._pick_mode(self._other_mode_target))

        def refresh() -> None:
            checks = self.model.checks(self.mode)
            failing = [c for c in checks if not c.ok]
            label = self.model.mode_label(self.mode)
            if failing:
                first = failing[0]
                chip.set_text(f"Contrast in {label}: {len(failing)} below the minimum. {first.label}: "
                              f"{first.ratio:.1f}:1, {first.minimum:g}:1 asked.")
                chip.set_tone("error")
                chip.setToolTip("\n".join(f"{c.label}: {c.ratio:.1f}:1, {c.minimum:g}:1 asked"
                                          for c in failing if c.ratio))
            else:
                chip.set_text(f"Contrast in {label}: all {len(checks)} checks pass.")
                chip.set_tone("ok")
            toggle.setText("Hide the checks" if self._show_checks else f"Show all {len(checks)}")
            other_failing = [(m.id, sum(1 for c in self.model.checks(m.id) if not c.ok))
                             for m in self.model.modes() if m.id != self.mode]
            other_failing = [(m, n) for m, n in other_failing if n]
            others.setVisible(bool(other_failing))
            if other_failing:
                total = sum(n for _m, n in other_failing)
                self._other_mode_target = other_failing[0][0]
                others.setText(f"Other modes: {total} below")
                others.setToolTip("Show " + ", ".join(f"{self.model.mode_label(m)} ({n})" for m, n in other_failing))
            for badge, check in zip(badges, checks):
                if check.ratio is None:
                    badge.set_text("?")
                    badge.set_tone("neutral")
                else:
                    badge.set_text(f"{check.ratio:.1f}:1" + ("" if check.ok else f" < {check.minimum:g}"))
                    badge.set_tone("neutral" if check.ok else "error")
                    badge.setToolTip(f"{check.label}: {check.ratio:.2f}:1, at least {check.minimum:g}:1 asked")
        refresh()
        self._refreshers.append(refresh)
        return box

    def _toggle_checks(self) -> None:
        self._show_checks = not self._show_checks
        self.rebuild()

    def _pick_mode(self, mode: str) -> None:
        """Switch the picked mode (a link in the form); the mode bar follows through on_structure."""
        self.set_mode(mode)

    def _row_grid(self, layout: QVBoxLayout) -> QGridLayout:
        grid = QGridLayout()
        grid.setHorizontalSpacing(SPACE.md)
        grid.setVerticalSpacing(SPACE.xs)
        grid.setColumnStretch(1, 1)
        layout.addLayout(grid)
        return grid

    def _palette(self) -> QWidget:
        names = self.model.palette_names()
        shown = [n for n in names if self._show_all_palette or self.model.palette_matters(n)]
        card, layout = self._card("Palette", "The theme's colours. Shown: what the theme sets or what differs between "
                                             "modes; the swatches at the right are the colour in every mode.")
        grid = self._row_grid(layout)
        for row, name in enumerate(shown):
            label = text_label(_label(name), "body")
            label.setToolTip(name)
            grid.addWidget(label, row, 0)
            cell = _Cell(self, read=lambda n=name, m=self.mode: self._palette_read(n, m),
                         write=lambda value, n=name, m=self.mode: self.model.set_palette(n, m, value),
                         usage=("palette", name, self.mode), source=("palette", name))
            self._cells.append(cell)
            grid.addWidget(cell, row, 1)
        if not shown:
            layout.addWidget(caption("The theme sets no palette colour and none differs between its modes: it uses "
                                     "the framework's palette."))
        buttons = QHBoxLayout()
        more = Button("Show only what matters" if self._show_all_palette else f"Show all {len(names)}", "ghost",
                      compact=True)
        more.clicked.connect(self._toggle_palette)
        buttons.addWidget(more)
        add = Button("Add a colour of the theme's own…", "ghost", compact=True)
        add.clicked.connect(self._add_own_colour)
        buttons.addWidget(add)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        return card

    def _toggle_palette(self) -> None:
        self._show_all_palette = not self._show_all_palette
        self.rebuild()

    def _palette_read(self, name: str, mode: str) -> tuple[Optional[str], str, Optional[str]]:
        written = self.model.palette_written(name, mode)
        colour = self.model.palette_hex(name, mode)
        if mode == self.model.base:
            follows = f"framework: {self.model.default(name) or '?'}"
        else:
            follows = colour or "base colour"
        return written, follows, colour

    def _add_own_colour(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("Add a colour of the theme's own")
        form = QFormLayout(dialog)
        name = QLineEdit("c_")
        value = QLineEdit("#")
        form.addRow("Name", name)
        form.addRow("Colour (#rrggbb)", value)
        form.addRow(caption("The roles can then use it, in any mode: a dark canvas of the theme's own, say."))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.apply(lambda: self.model.add_own_colour(name.text().strip(), value.text().strip()))

    def _group(self, title: str, summary: str) -> tuple[QWidget, Optional[QVBoxLayout]]:
        """A folding group: its header (a button with the title and `summary`) and, when open, its body's layout."""
        box = Surface()
        column = QVBoxLayout(box)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(SPACE.sm)
        is_open = title in self._open_groups
        header = Button(f"{'▾' if is_open else '▸'}  {title}    ·  {summary}", "secondary")
        header.setStyleSheet("text-align: left;")
        header.clicked.connect(lambda: self._toggle_group(title))
        column.addWidget(header)
        if not is_open:
            return box, None
        card = Card()
        column.addWidget(card)
        return box, card.layout()

    def _toggle_group(self, title: str) -> None:
        self._open_groups ^= {title}
        self.rebuild()

    def _roles(self, title: str, roles: tuple[str, ...]) -> QWidget:
        set_here, total = self.model.role_set_counts(roles, self.mode)
        summary = f"{total} roles · " + (f"{set_here} set" if set_here else "all follow")
        box, layout = self._group(title, summary)
        if layout is None:
            return box
        grid = self._row_grid(layout)
        for row, role in enumerate(roles):
            label = text_label(_label("role:" + role), "body")
            label.setToolTip(f"role {role}" + (f" (\\{self.model.hook(role)})" if self.model.hook(role) else ""))
            grid.addWidget(label, row, 0)
            cell = _Cell(self, read=lambda r=role, m=self.mode: self._role_read(r, m),
                         write=lambda value, r=role, m=self.mode: self.model.set_role(r, m, value),
                         choices=self.model.colour_names(), picker=False,
                         enabled=self.model.role_editable(role, self.mode), usage=("role", role, self.mode),
                         source=("role", role))
            self._cells.append(cell)
            grid.addWidget(cell, row, 1)
        return box

    def _role_read(self, role: str, mode: str) -> tuple[Optional[str], str, Optional[str]]:
        return (self.model.role_written(role, mode), self.model.role_follows(role, mode),
                self.model.resolve("role:" + role, mode))

    def _code(self) -> QWidget:
        box, layout = self._group("Code panels", "4 colours of \\SMCodeFile")
        if layout is None:
            return box
        grid = self._row_grid(layout)
        base = self.mode == self.model.base
        for row, (name, role) in enumerate(CODE_COLOURS):
            grid.addWidget(text_label(_label(name), "body"), row, 0)
            if base:
                cell = _Cell(self, read=lambda n=name, m=self.mode: self._optional_read(n, m),
                             write=lambda value, n=name: self.model.set_value(n, value),
                             usage=("role", role, self.mode), source=("optional", name), strip_role=role)
            else:
                cell = _Cell(self, read=lambda r=role, m=self.mode: self._role_read(r, m),
                             write=lambda value, r=role, m=self.mode: self.model.set_role(r, m, value),
                             choices=self.model.colour_names(), picker=False, usage=("role", role, self.mode),
                             source=("role", role))
            self._cells.append(cell)
            grid.addWidget(cell, row, 1)
        return box

    def _optional_read(self, name: str, mode: str) -> tuple[Optional[str], str, Optional[str]]:
        return self.model.value(name), f"framework: {self.model.default(name)}", self.model.resolve(name, mode)

    def _logo(self) -> QWidget:
        card, layout = self._card("Logo", "A vector PDF cropped to its ink, at the right end of the title bar.")
        path = QLineEdit()
        choose = Button("Choose file…", "secondary", compact=True)
        choose.clicked.connect(self._choose_logo)
        row = QHBoxLayout()
        row.addWidget(path, 1)
        row.addWidget(choose)
        layout.addLayout(row)
        warning = caption("", "error")
        layout.addWidget(warning)
        form = QFormLayout()
        fields = {}
        for key in ("SMLogoHeight", "SMFrametitleRightPadding"):
            edit = QLineEdit()
            edit.editingFinished.connect(lambda k=key, e=edit: e.text().strip() != (self.model.value(k) or "")
                                         and self.apply(lambda: self.model.set_value(k, e.text())))
            form.addRow(_label(key), edit)
            fields[key] = edit
        layout.addLayout(form)
        path.editingFinished.connect(lambda: path.text().strip() != (self.model.value("SMInstituteLogoPath") or "")
                                     and self.apply(lambda: self.model.set_value("SMInstituteLogoPath", path.text())))

        def refresh() -> None:
            value = self.model.value("SMInstituteLogoPath")
            if not path.hasFocus():
                path.setText(value or "")
            path.setPlaceholderText(f"framework: {self.model.default('SMInstituteLogoPath')}")
            shown = value or ""
            problem = ""
            if shown and not shown.lower().endswith(".pdf"):
                problem = "The logo should be a vector PDF: other files look blurred when the slides are zoomed."
            elif shown and not (self.root / shown).is_file() and not (self.path.parent / shown).is_file():
                problem = ("No such file in the project folder (it may be on the TeX search path elsewhere)."
                           if self.home == self.root else
                           "No such file in the theme's folder (it may be on the TeX search path elsewhere).")
            warning.setText(problem)
            warning.setVisible(bool(problem))
            for key, edit in fields.items():
                if not edit.hasFocus():
                    edit.setText(self.model.value(key) or "")
                edit.setPlaceholderText(f"framework: {self.model.default(key)}")
        refresh()
        self._refreshers.append(refresh)
        return card

    def _choose_logo(self) -> None:
        chosen, _ = QFileDialog.getOpenFileName(self, "Choose the logo", str(self.home), "PDF (*.pdf);;All files (*)")
        if chosen:
            self.apply(lambda: self.model.import_logo(Path(chosen)))

    def _footnotes(self) -> QWidget:
        card, layout = self._card("Footnote markers")
        combo = QComboBox()
        for value, label in FOOTNOTE_STYLES:
            combo.addItem(label, value)
        style = self.model.footnote_style()
        if style == "custom":
            combo.addItem("The theme's own (in the source)", "custom")
        combo.setCurrentIndex(max(combo.findData(style), 0))
        combo.activated.connect(lambda _i: combo.currentData() != "custom"
                                and self.apply(lambda: self.model.set_footnote_style(combo.currentData())))
        layout.addWidget(combo)
        return card

    # --- layout fields (stage C2a) ----------------------------------------------------------------------------------

    def _layout_card(self, title: str, note: str, keys: tuple[str, ...]) -> QWidget:
        card, layout = self._card(title, note)
        form = QFormLayout()
        for key in keys:
            widget, refresh = self._layout_field(key)
            label = QLabel(_label(key))
            entry = self.model.catalog.get(key)
            if entry is not None and entry.help:
                label.setToolTip(entry.help)
                widget.setToolTip(entry.help)
            form.addRow(label, widget)
            self.layout_fields[key] = widget
            self._refreshers.append(refresh)
        layout.addLayout(form)
        return card

    def _layout_field(self, key: str) -> tuple[QWidget, Callable[[], None]]:
        """The widget of one layout setting and how it shows the theme's value again."""
        field = theme_fields.BY_NAME[key]
        default = self.model.default(key)
        if key == "SMLayoutProfile":
            return self._choice_field(key, layout_profiles(self.root, self.home), default or "fira")
        if key == "SMCitationFormat":
            return self._choice_field(key, citation_formats(), default or "default")
        if key == "SMBulletSymbol":
            return self._bullet_field(key)
        if field.kind == "size_pair":
            return self._size_pair_field(key, default)
        return self._text_field(key, default, length=field.kind == "length")

    def _text_field(self, key: str, default: str, *, length: bool) -> tuple[QWidget, Callable[[], None]]:
        if length:
            return self._length_field(key, default)
        box = Surface()
        column = QVBoxLayout(box)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        edit = QLineEdit()
        edit.setPlaceholderText(f"framework: {default}")
        problem = caption("", "error")
        problem.hide()
        column.addWidget(edit)
        column.addWidget(problem)

        def commit() -> None:
            text = edit.text().strip()
            if text == (self.model.value(key) or ""):
                problem.hide()
                return
            why = check_length(text) if length else ""
            problem.setText(why)
            problem.setVisible(bool(why))
            if not why:
                self.apply(lambda: self.model.set_value(key, text or None))

        edit.editingFinished.connect(commit)

        def refresh() -> None:
            if not edit.hasFocus():
                edit.setText(self.model.value(key) or "")
        refresh()
        return box, refresh

    def _unit_switch(self) -> QWidget:
        """Which unit the Layout tab shows lengths in (remembered). The theme keeps each length in its own unit."""
        box = Surface()
        row = QHBoxLayout(box)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(caption("Show lengths in"))
        switch = SegmentedControl([(unit, unit) for unit in theme_measures.DISPLAY_UNITS], current=self.display_unit)
        switch.changed.connect(self.set_display_unit)
        row.addWidget(switch)
        row.addWidget(caption("New values are written in this unit; the theme keeps the units it has (ex and em follow "
                              "the font)."), 1)
        return box

    def set_display_unit(self, unit: str) -> None:
        if unit in theme_measures.DISPLAY_UNITS and unit != self.display_unit:
            self.display_unit = unit
            layout_settings.set(DISPLAY_UNIT_KEY, unit)
            self.rebuild()

    def _length_bp(self, key: str, value: str, default: str) -> Optional[float]:
        """`value` (or, empty, what the theme comes to) in bp: the last render's, or worked out from its unit."""
        if not value:
            rendered = theme_measures.rendered(key, self.geometry())
            if rendered is not None and (self.model.value(key) or "") == "":
                return rendered
            value = self.model.value(key) or default
        return theme_measures.to_bp(value, key, self.geometry(), self.model.value(key) or default)

    def _length_field(self, key: str, default: str) -> tuple[QWidget, Callable[[], None]]:
        """A number and a unit (the mockup's look); a length of another form (0.8\\paperheight) shows as raw TeX."""
        box = Surface()
        column = QVBoxLayout(box)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        row = QHBoxLayout()
        row.setSpacing(SPACE.xs)
        number = QLineEdit()
        number.setMaximumWidth(110)
        unit = QComboBox()
        unit.addItems(list(UNITS))
        raw = QLineEdit()
        raw.setPlaceholderText(f"framework: {default}")
        note = caption("")
        row.addWidget(number)
        row.addWidget(unit)
        row.addWidget(raw, 1)
        row.addWidget(note, 1)
        column.addLayout(row)
        problem = caption("", "error")
        problem.hide()
        column.addWidget(problem)
        fallback = split_length(default)
        number.setPlaceholderText(fallback[0] if fallback else default)
        font_size = key in FONT_SIZE_KEYS

        def write(text: str) -> None:
            if text == (self.model.value(key) or ""):
                problem.hide()
                return
            why = check_length(text)
            problem.setText(why)
            problem.setVisible(bool(why))
            if not why:
                self.apply(lambda: self.model.set_value(key, text or None))

        def commit_split() -> None:
            text = number.text().strip()
            write(f"{text}{unit.currentText()}" if text else "")

        number.editingFinished.connect(commit_split)
        unit.activated.connect(lambda _i: number.text().strip() and commit_split())
        raw.editingFinished.connect(lambda: write(raw.text().strip()))
        check = caption("")
        check.hide()
        column.addWidget(check)

        def typed() -> str:
            """The length the fields hold now, typed or not yet written ("" when they follow)."""
            if not raw.isHidden():
                return raw.text().strip()
            text = number.text().strip()
            return f"{text}{unit.currentText()}" if text else ""

        def tell() -> None:
            """The sample slides mark the length as typed (C2b), and the Top Margin's check follows it."""
            value = typed()
            value_bp = self._length_bp(key, value, default)
            if value and value_bp is not None and not font_size and split_length(value) \
                    and split_length(value)[1] != self.display_unit:
                note.setText(f"≈ {theme_measures.show(value_bp, self.display_unit)}")
            if self.on_measure is not None and key in theme_measures.MEASURED:
                self.on_measure(key, value_bp)
            if key == "SMTopMargin":
                text, ok = theme_measures.title_bar_check(value_bp, self.geometry(), self.display_unit)
                check.setText(text)
                check.setProperty("tone", "" if ok else "error")
                check.style().unpolish(check)
                check.style().polish(check)
                check.setVisible(bool(text))

        for field in (number, raw):
            field.textEdited.connect(lambda _t: tell())
            field.installEventFilter(self._measure_filter(tell))
        unit.currentTextChanged.connect(lambda _t: number.hasFocus() and tell())

        def refresh() -> None:
            value = self.model.value(key)
            # A length the theme does not set is typed in the display unit; one it sets keeps its own unit. A font
            # size stays in pt (the unit fonts are sized in), with no equivalent beside it.
            parts = split_length(value) if value else (None, "pt" if font_size else self.display_unit)
            split = parts is not None
            number.setVisible(split)
            unit.setVisible(split)
            note.setVisible(True)
            raw.setVisible(not split)
            value_bp = self._length_bp(key, "", default)
            same = font_size or (parts[1] if split else "") == self.display_unit
            if split:
                if not number.hasFocus():
                    number.setText(parts[0] or "")
                unit.setCurrentText(parts[1])
            elif not raw.hasFocus():
                raw.setText(value or "")
            if not value and font_size:
                number.setPlaceholderText(fallback[0] if fallback else default)
                note.setText("framework")
            elif not value:
                number.setPlaceholderText(theme_measures.number_in(value_bp, self.display_unit) if value_bp is not None
                                          else (fallback[0] if fallback else default))
                note.setText("framework" + (f" ({default})" if fallback and fallback[1] != self.display_unit else ""))
            elif value_bp is not None and not same:
                note.setText(f"≈ {theme_measures.show(value_bp, self.display_unit)}")
            else:
                note.setText("")
            note.setToolTip("" if value_bp is None else f"{theme_measures.show(value_bp, 'mm')} · "
                            f"{theme_measures.show(value_bp, 'pt')} · {value_bp:.2f} bp (as the last render had it)")
            if key == "SMTopMargin":
                tell()
        refresh()
        return box, refresh

    def _measure_filter(self, tell: Callable[[], None]) -> QObject:
        """An event filter that marks a length on the sample slides while its field has the focus."""
        form = self

        class Filter(QObject):
            def eventFilter(self, watched, event) -> bool:
                if event.type() == QEvent.Type.FocusIn:
                    tell()
                elif event.type() == QEvent.Type.FocusOut and form.on_measure_cleared is not None:
                    form.on_measure_cleared()
                return False

        found = Filter(self)
        self._filters.append(found)
        return found

    def _choice_field(self, key: str, choices: list[str], default: str) -> tuple[QWidget, Callable[[], None]]:
        combo = QComboBox()
        combo.setEditable(True)
        combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        combo.addItems([""] + choices)
        combo.lineEdit().setPlaceholderText(f"framework: {default}")

        def commit() -> None:
            text = combo.currentText().strip()
            if text != (self.model.value(key) or ""):
                self.apply(lambda: self.model.set_value(key, text or None))

        combo.activated.connect(lambda _i: commit())
        combo.lineEdit().editingFinished.connect(commit)

        def refresh() -> None:
            if not combo.lineEdit().hasFocus():
                combo.setCurrentText(self.model.value(key) or "")
        refresh()
        return combo, refresh

    def _bullet_field(self, key: str) -> tuple[QWidget, Callable[[], None]]:
        combo = QComboBox()
        for value, label in BULLETS:
            combo.addItem(label, value)
        custom_index = -1

        def refresh() -> None:
            nonlocal custom_index
            value = self.model.value(key) or ""
            index = combo.findData(value)
            if index < 0:
                if custom_index < 0:
                    combo.addItem("The theme's own (in the source)", value)
                    custom_index = combo.count() - 1
                index = custom_index
            combo.setCurrentIndex(index)

        def commit() -> None:
            value = combo.currentData()
            if combo.currentIndex() == custom_index or value == (self.model.value(key) or ""):
                return
            self.apply(lambda: self.model.set_value(key, value or None))

        combo.activated.connect(lambda _i: commit())
        refresh()
        return combo, refresh

    def _size_pair_field(self, key: str, default: str) -> tuple[QWidget, Callable[[], None]]:
        """\\fontsize{size}{skip}\\selectfont as two numbers in pt; a value of another form shows as it is."""
        box = Surface()
        row = QHBoxLayout(box)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(SPACE.xs)
        size, skip = QLineEdit(), QLineEdit()
        size.setToolTip("Font size in pt")
        skip.setToolTip("Baseline skip (line distance) in pt")
        raw = QLineEdit()
        fallback = parse_size_pair(default) or ("", "")
        size.setPlaceholderText(fallback[0])
        skip.setPlaceholderText(fallback[1])
        raw.setPlaceholderText(f"framework: {default}")
        row.addWidget(size)
        row.addWidget(QLabel("pt on"))
        row.addWidget(skip)
        row.addWidget(QLabel("pt"))
        row.addWidget(raw, 1)

        def commit_pair() -> None:
            a, b = size.text().strip(), skip.text().strip()
            if not a and not b:
                value = None
            elif a and b and all(part.replace(".", "", 1).isdigit() for part in (a, b)):
                value = format_size_pair(a, b)
            else:
                return              # half typed, or not numbers: wait
            if (value or "") != (self.model.value(key) or ""):
                self.apply(lambda: self.model.set_value(key, value))

        def commit_raw() -> None:
            text = raw.text().strip()
            if text != (self.model.value(key) or ""):
                self.apply(lambda: self.model.set_value(key, text or None))

        size.editingFinished.connect(commit_pair)
        skip.editingFinished.connect(commit_pair)
        raw.editingFinished.connect(commit_raw)

        def refresh() -> None:
            value = self.model.value(key)
            pair = parse_size_pair(value) if value else ("", "")
            for widget in (size, skip):
                widget.setVisible(pair is not None)
            for index in range(row.count()):
                item = row.itemAt(index).widget()
                if isinstance(item, QLabel):
                    item.setVisible(pair is not None)
            raw.setVisible(pair is None)
            if pair is not None:
                if not size.hasFocus():
                    size.setText(pair[0])
                if not skip.hasFocus():
                    skip.setText(pair[1])
            elif not raw.hasFocus():
                raw.setText(value or "")
        refresh()
        return box, refresh
