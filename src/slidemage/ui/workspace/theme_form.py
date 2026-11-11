# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
r"""The theme form beside a theme's source (docs/plans/theme-editor.md, stage C1b): identity and colour modes, the
palette with the theme's own colours, the colour roles, code colours, logo, footnote markers and the contrast checks,
one column per colour mode.

Form and source are two views of one buffer: an edit here goes into the editor as one undo step
(LatexPlainTextEdit.patch_text, through theme_form_model / theme_file, which change one line), so autosave, the conflict
bar and Ctrl+Z work as for typing; typing in the source shows here after a pause. Nothing is written to disk here."""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QColorDialog, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QGridLayout, QHBoxLayout,
    QLineEdit, QMessageBox, QScrollArea, QVBoxLayout, QWidget,
)

from ... import slide_templates, theme_fields
from ...theme_form_model import CODE_COLOURS, DERIVES, FOOTNOTE_STYLES, ROLE_SECTIONS, ThemeModel
from ..kit.tokens import SPACE
from ..kit.widgets import Badge, Button, Card, ColorSwatchButton, Surface, caption, text_label

REFRESH_DELAY_MS = 400      # after the last keystroke in the source


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
    """One value in one mode: a swatch with what it comes to, and the field with what the theme writes (empty: it
    follows, and the field's grey text says what)."""

    def __init__(self, form: "ThemeForm", read: Callable[[], tuple[Optional[str], str, Optional[str]]],
                 write: Callable[[Optional[str]], None], *, choices: list[str] | None = None,
                 picker: bool = True, enabled: bool = True) -> None:
        super().__init__()
        self.form, self.read, self.write = form, read, write
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
            self.combo.setMinimumContentsLength(6)
            self.combo.addItems([""] + choices)
            self.combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
            self.edit = self.combo.lineEdit()
            self.combo.activated.connect(lambda _i: self._commit())
            row.addWidget(self.combo, 1)
            self.combo.setEnabled(enabled)
        else:
            self.combo = None
            self.edit = QLineEdit()
            row.addWidget(self.edit, 1)
            self.edit.setEnabled(enabled)
        self.edit.editingFinished.connect(self._commit)
        self.update_value()

    def update_value(self) -> None:
        written, follows, colour = self.read()
        self.swatch.show_colour(colour)
        if not self.edit.hasFocus():
            self.edit.setText(written or "")
        self.edit.setPlaceholderText(follows)
        self.edit.setToolTip(f"Follows: {follows}" if not written else f"Written in the theme: {written}")

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


class ThemeForm(QScrollArea):
    """The form of one theme file, editing `editor`'s buffer. `root` is the project; `setup_path` the framework's
    SlideMage_setup.tex (its catalog gives defaults and the roles)."""

    def __init__(self, editor, path: Path, root: Path, setup_path: Optional[Path]) -> None:
        super().__init__()
        self.editor = editor
        self.path = path
        self.root = root
        self.setWidgetResizable(True)
        self.setFrameShape(QScrollArea.Shape.NoFrame)
        self.setMinimumWidth(320)
        setup_text = setup_path.read_text(encoding="utf-8") if setup_path and setup_path.is_file() else ""
        self.model = ThemeModel(editor.text(), root, theme_key(path), setup_text) if setup_text else None
        self._cells: list[_Cell] = []
        self._refreshers: list[Callable[[], None]] = []
        self._shape: tuple = ()
        self._pushing = False
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
        """What the form's rows and columns depend on: rebuilt when it changes, else only the values are."""
        if self.model is None:
            return ()
        return (self.model.readable, tuple((m.id, m.label, m.derive) for m in self.model.modes()),
                tuple(self.model.file.own_colours()), len(self.model.file.beyond()), self.model.footnote_style(),
                self.editor.is_read_only())

    def refresh(self) -> None:
        for cell in self._cells:
            cell.update_value()
        for refresher in self._refreshers:
            refresher()

    # --- building ----------------------------------------------------------------------------------------------------

    def rebuild(self) -> None:
        scroll = self.verticalScrollBar().value()
        self._cells, self._refreshers = [], []
        body = Surface()
        column = QVBoxLayout(body)
        column.setContentsMargins(SPACE.lg, SPACE.lg, SPACE.lg, SPACE.lg)
        column.setSpacing(SPACE.lg)
        self._shape = self._structure()
        if self.model is None:
            column.addWidget(caption("The framework's SlideMage_setup.tex was not found, so the form has no catalog "
                                     "to show. Edit the theme in the source."))
        elif not self.model.readable:
            column.addWidget(caption("This file does not \\input SlideMage_setup and then SlideMage_base, so it is no "
                                     "theme the form can read. Edit it in the source."))
        else:
            column.addWidget(self._intro())
            column.addWidget(self._identity())
            column.addWidget(self._checks())
            column.addWidget(self._palette())
            for title, roles in ROLE_SECTIONS:
                column.addWidget(self._roles(title, roles))
            column.addWidget(self._code())
            column.addWidget(self._logo())
            column.addWidget(self._footnotes())
        column.addStretch(1)
        body.setEnabled(not self.editor.is_read_only())
        self.setWidget(body)
        QTimer.singleShot(0, self, lambda: self.verticalScrollBar().setValue(scroll))    # dies with the form

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
        layout.addWidget(text_label("Theme form", "title"))
        beyond = self.model.file.beyond()
        note = ("Each change goes into the source beside it, one line at a time, and is saved like typing. "
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

    def _mode_grid(self, layout: QVBoxLayout) -> QGridLayout:
        grid = QGridLayout()
        grid.setHorizontalSpacing(SPACE.md)
        grid.setVerticalSpacing(SPACE.xs)
        modes = self.model.modes()
        if len(modes) > 1 or modes[0].id:
            for column, mode in enumerate(modes, start=1):
                head = text_label(mode.label, "secondary")
                head.setToolTip(f"Mode {mode.id}" + (" (the base: the colours the theme sets directly)" if column == 1
                                                     else f", derived from the {mode.derive} preset" if mode.derive else ""))
                grid.addWidget(head, 0, column)
        for column in range(1, len(modes) + 1):
            grid.setColumnStretch(column, 1)
        layout.addLayout(grid)
        return grid

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
                what = "the base mode" if index == 0 else (f"from the {mode.derive} preset" if mode.derive
                                                           else "no preset")
                line.addWidget(text_label(f"{mode.label}  ·  {mode.id}, {what}"), 1)
                if index:
                    remove = Button("Remove", "ghost", compact=True)
                    remove.setToolTip(f"Take the mode {mode.id} out, with every line of it")
                    remove.clicked.connect(lambda _=False, m=mode.id: self._remove_mode(m))
                    line.addWidget(remove)
                layout.addLayout(line)
        else:
            layout.addWidget(caption("The theme has no colour modes: one set of colours. Add one to give decks a dark "
                                     "(or another) version of it."))
        mismatch = self.model.header_mismatch()
        if mismatch:
            layout.addWidget(caption(mismatch, "error"))
        add = Button("Add a colour mode…", "secondary", compact=True)
        add.clicked.connect(self._add_mode)
        layout.addWidget(add, 0, Qt.AlignmentFlag.AlignLeft)
        return card

    def _add_mode(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("Add a colour mode")
        form = QFormLayout(dialog)
        mode_id = QLineEdit("dark" if "dark" not in [m.id for m in self.model.modes()] else "")
        label = QLineEdit("Dark slides" if mode_id.text() else "")
        derive = QComboBox()
        names = {"dark": "Dark: derived from the palette", "grey": "Grey: every colour in grey",
                 "colorblind": "Colour-blind safe accents", "": "None: only what you set"}
        for value in DERIVES:
            derive.addItem(names[value], value)
        form.addRow("Name (id)", mode_id)
        form.addRow("Label in SlideMage", label)
        form.addRow("Start from", derive)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.apply(lambda: self.model.add_mode(mode_id.text().strip(), derive.currentData(), label.text()))

    def _remove_mode(self, mode_id: str) -> None:
        answer = QMessageBox.question(self, "Remove a colour mode",
                                      f"Take the mode {mode_id} out of the theme, with every line of it? "
                                      "Ctrl+Z in the source brings it back.")
        if answer == QMessageBox.StandardButton.Yes:
            self.apply(lambda: self.model.remove_mode(mode_id))

    def _checks(self) -> QWidget:
        card, layout = self._card("Contrast", "WCAG contrast of what the catalog asks to stay readable: 4.5:1 for "
                                              "text, 3:1 for the link underline.")
        grid = self._mode_grid(layout)
        modes = self.model.modes()
        badges: list[list[Badge]] = []
        for row, check in enumerate(self.model.checks(modes[0].id), start=1):
            grid.addWidget(text_label(check.label, "body"), row, 0)
            badges.append([])
            for column in range(1, len(modes) + 1):
                badge = Badge("")
                grid.addWidget(badge, row, column, Qt.AlignmentFlag.AlignLeft)
                badges[-1].append(badge)

        def refresh() -> None:
            for column, mode in enumerate(self.model.modes()):
                for row, check in enumerate(self.model.checks(mode.id)):
                    if row >= len(badges) or column >= len(badges[row]):
                        continue
                    badge = badges[row][column]
                    if check.ratio is None:
                        badge.set_text("?")
                        badge.set_tone("neutral")
                        badge.setToolTip("A colour of this pair could not be worked out.")
                    else:
                        badge.set_text(f"{check.ratio:.1f}:1" + ("" if check.ok else f" < {check.minimum:g}"))
                        badge.set_tone("neutral" if check.ok else "error")
                        badge.setToolTip(f"{check.label}: {check.ratio:.2f}:1, at least {check.minimum:g}:1 asked")
        refresh()
        self._refreshers.append(refresh)
        return card

    def _palette(self) -> QWidget:
        card, layout = self._card("Palette", "The theme's colours (\\definecolor). In another mode an empty field "
                                             "keeps the base colour, or what the mode's preset makes of it.")
        grid = self._mode_grid(layout)
        modes = self.model.modes()
        for row, name in enumerate(self.model.palette_names(), start=1):
            label = text_label(_label(name), "body")
            label.setToolTip(name)
            grid.addWidget(label, row, 0)
            for column, mode in enumerate(modes, start=1):
                cell = _Cell(self, read=lambda n=name, m=mode.id: self._palette_read(n, m),
                             write=lambda value, n=name, m=mode.id: self.model.set_palette(n, m, value))
                self._cells.append(cell)
                grid.addWidget(cell, row, column)
        add = Button("Add a colour of the theme's own…", "ghost", compact=True)
        add.clicked.connect(self._add_own_colour)
        layout.addWidget(add, 0, Qt.AlignmentFlag.AlignLeft)
        return card

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

    def _roles(self, title: str, roles: tuple[str, ...]) -> QWidget:
        card, layout = self._card(title)
        grid = self._mode_grid(layout)
        for row, role in enumerate(roles, start=1):
            label = text_label(_label("role:" + role), "body")
            label.setToolTip(f"role {role}" + (f" (\\{self.model.hook(role)})" if self.model.hook(role) else ""))
            grid.addWidget(label, row, 0)
            for column, mode in enumerate(self.model.modes(), start=1):
                cell = _Cell(self, read=lambda r=role, m=mode.id: self._role_read(r, m),
                             write=lambda value, r=role, m=mode.id: self.model.set_role(r, m, value),
                             choices=self.model.colour_names(), picker=False,
                             enabled=self.model.role_editable(role, mode.id))
                self._cells.append(cell)
                grid.addWidget(cell, row, column)
        return card

    def _role_read(self, role: str, mode: str) -> tuple[Optional[str], str, Optional[str]]:
        return (self.model.role_written(role, mode), self.model.role_follows(role, mode),
                self.model.resolve("role:" + role, mode))

    def _code(self) -> QWidget:
        card, layout = self._card("Code panels", "The colours of \\SMCodeFile. The base column is the theme's colour; "
                                                 "another mode's sets the code role of that mode.")
        grid = self._mode_grid(layout)
        modes = self.model.modes()
        for row, (name, role) in enumerate(CODE_COLOURS, start=1):
            grid.addWidget(text_label(_label(name), "body"), row, 0)
            for column, mode in enumerate(modes, start=1):
                if column == 1:
                    cell = _Cell(self, read=lambda n=name, m=mode.id: self._optional_read(n, m),
                                 write=lambda value, n=name: self.model.set_value(n, value))
                else:
                    cell = _Cell(self, read=lambda r=role, m=mode.id: self._role_read(r, m),
                                 write=lambda value, r=role, m=mode.id: self.model.set_role(r, m, value),
                                 choices=self.model.colour_names(), picker=False)
                self._cells.append(cell)
                grid.addWidget(cell, row, column)
        return card

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
                problem = "No such file in the project folder (it may be on the TeX search path elsewhere)."
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
        chosen, _ = QFileDialog.getOpenFileName(self, "Choose the logo", str(self.root), "PDF (*.pdf);;All files (*)")
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
