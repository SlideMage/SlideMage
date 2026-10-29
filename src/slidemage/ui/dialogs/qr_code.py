# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The "Insert QR code" sheet of the Source view (qr_code.py has what it makes): the kind of code, the
fields of that kind, a live preview with the heights the rooms need, the height on the slide, the
caption, the file in media/ and, if wanted, a copy elsewhere (PDF, PNG, SVG or EPS). Insert writes the
file and exposes `snippet`, the \\SMQRCode call for the editor to put in place of its selection.

With the cursor in (or the selection around) one \\SMQRCode call whose file has a stored spec, the sheet
opens filled in as "Update": it writes the same file again and `snippet` replaces that call
(`existing_call`).
"""
from __future__ import annotations

import io
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import QDateTime, QTime, QTimer, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateTimeEdit,
    QDoubleSpinBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ... import qr_code
from ...project import ProjectContext
from ..kit.widgets import Button, Field, ModalSheet, SegmentedControl, Surface, caption, columns, row, set_property

PREVIEW_SIZE = 240
PREVIEW_SCALE = 8                     # pixels per module of the picture, scaled down to PREVIEW_SIZE
DEBOUNCE_MS = 150
HEIGHT_STEP = 0.05
MAX_BORDER = 10
LABELS = {"url": "Link", "to": "To", "subject": "Subject", "body": "Message", "name": "Name",
          "organization": "Organization", "title": "Title", "email": "Email", "phone": "Phone",
          "website": "Website", "street": "Street", "postcode": "Postcode", "city": "City",
          "country": "Country", "start": "Starts", "end": "Ends", "location": "Location",
          "description": "Description", "place": "Address, coordinates or map link", "label": "Label (optional)"}
PLACEHOLDERS = {"url": "https://example.org/page", "to": "name@example.org", "name": "Given Family",
                "email": "name@example.org", "phone": "+43 316 380 0", "website": "https://example.org",
                "place": "Universitätsplatz 3, Graz, or 47.0777, 15.4495", "label": "Lecture hall"}
ERROR_TIPS = {"L": "L: 7 % of the code can be damaged and still be read. The coarsest dots: the best choice "
                   "on a projected slide.",
              "M": "M: 15 % recoverable. A good balance for a short link.",
              "Q": "Q: 25 % recoverable. Finer dots; for a code that may be printed or partly covered.",
              "H": "H: 30 % recoverable. The finest dots; larger dots matter more on a projected slide."}
FORMAT_FILTERS = ";;".join(f"{name} (*.{ext})" for name, ext in (("PDF", "pdf"), ("PNG", "png"),
                                                                    ("SVG", "svg"), ("EPS", "eps")))
_CALL = re.compile(r"\\SMQRCode\[([0-9.]+)\\textheight\]\{([^{}]+)\}\{")
_LINK = re.compile(r"\[[^\]\n]*\]")
_WHEN = "yyyy-MM-dd HH:mm"
_DAY = "yyyy-MM-dd"


@dataclass
class ExistingCall:
    """A \\SMQRCode call in the editor and what its file was made from. `start`/`end` span the call in the text."""

    start: int
    end: int
    image: str
    height: float
    spec: qr_code.QRSpec
    caption_mode: str
    caption: str


def existing_call(project: ProjectContext, text: str, start: int, end: int) -> Optional[ExistingCall]:
    """The one \\SMQRCode call in text[start:end] -- or, with nothing selected, in the line of `start` --
    whose image has a stored spec; None for none, several, or an image made elsewhere."""
    if start == end:
        start, end = text.rfind("\n", 0, start) + 1, (text.find("\n", start) if "\n" in text[start:] else len(text))
    found = list(_CALL.finditer(text, start, end))
    if len(found) != 1:
        return None
    match = found[0]
    depth, position = 1, match.end()
    while position < len(text) and depth:
        char = text[position]
        if char == "\\":
            position += 1
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
        position += 1
    if depth:
        return None
    link = _LINK.match(text, position)          # the trailing [link] (qr_code.snippet) belongs to the call
    if link:
        position = link.end()
    image = match.group(2)
    stored = qr_code.load_spec(project, image)
    if stored is None:
        return None
    spec, extra = stored
    return ExistingCall(match.start(), position, image, float(match.group(1)), spec,
                        extra.get("caption_mode", qr_code.CAPTION_CONTENT), extra.get("caption", ""))


def _when(value: str) -> QDateTime:
    return QDateTime.fromString(value.replace("T", " ")[:16], _WHEN) if len(value) > 10 else \
        QDateTime.fromString(value[:10], _DAY)


class QRCodeDialog(ModalSheet):
    def __init__(self, parent, project: ProjectContext, existing: Optional[ExistingCall] = None) -> None:
        """After exec() accepted, `snippet` is the \\SMQRCode call and `created` what qr_code.create returned.
        With `existing`, the sheet is filled in from it and Update writes the same file again."""
        super().__init__("Insert QR code", parent, width=780)
        self.project = project
        self.existing = existing
        self.snippet = ""
        self.created: Optional[qr_code.Created] = None
        self._name_touched = existing is not None
        self._error_touched = existing is not None
        self._read: dict[str, dict[str, Callable[[], str]]] = {}
        self._write: dict[str, dict[str, Callable[[str], None]]] = {}
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(DEBOUNCE_MS)
        self._timer.timeout.connect(self.update_preview)

        body = Surface()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        top = QHBoxLayout()
        top.setSpacing(20)
        left = QVBoxLayout()
        left.setSpacing(12)
        self.kind_box = QComboBox()
        for kind in qr_code.KINDS:
            self.kind_box.addItem(qr_code.KIND_LABELS[kind], kind)
        self.kind_box.currentIndexChanged.connect(self._on_kind)
        left.addWidget(Field("What the code holds", self.kind_box))
        self.pages = QStackedWidget()
        for kind in qr_code.KINDS:
            self.pages.addWidget(self._build_page(kind))
        left.addWidget(self.pages)
        left.addStretch(1)
        top.addLayout(left, 1)

        right = QVBoxLayout()
        right.setSpacing(8)
        self.preview = QLabel()
        self.preview.setFixedSize(PREVIEW_SIZE, PREVIEW_SIZE)
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setWordWrap(True)
        right.addWidget(self.preview, 0, Qt.AlignmentFlag.AlignHCenter)
        self.info = caption()
        self.info.setFixedWidth(PREVIEW_SIZE + 20)
        right.addWidget(self.info)
        right.addStretch(1)
        top.addLayout(right)
        layout.addLayout(top)

        self.height_box = QDoubleSpinBox()
        self.height_box.setDecimals(2)
        self.height_box.setSingleStep(HEIGHT_STEP)
        self.height_box.setRange(HEIGHT_STEP, qr_code.MAX_HEIGHT)
        self.height_box.setValue(qr_code.DEFAULT_HEIGHT)
        self.height_box.valueChanged.connect(self._changed)
        self.height_hint = caption()
        self.height_hint.hide()
        height_field = Surface()
        height_layout = QVBoxLayout(height_field)
        height_layout.setContentsMargins(0, 0, 0, 0)
        height_layout.setSpacing(4)
        height_layout.addWidget(Field("Height on the slide (share of the text height)", self.height_box))
        height_layout.addWidget(self.height_hint)

        self.caption_mode = SegmentedControl([(qr_code.CAPTION_NONE, "None"), (qr_code.CAPTION_CONTENT, "Its text"),
                                              (qr_code.CAPTION_CUSTOM, "Custom")], current=qr_code.CAPTION_NONE)
        self.caption_mode.changed.connect(self._on_caption_mode)
        self.caption_text = QLineEdit()
        self.caption_text.setPlaceholderText("QR 1")
        self.caption_text.textChanged.connect(self._changed)
        self.caption_note = caption()
        caption_field = Surface()
        caption_layout = QVBoxLayout(caption_field)
        caption_layout.setContentsMargins(0, 0, 0, 0)
        caption_layout.setSpacing(4)
        caption_layout.addWidget(Field("Caption under the code", self.caption_mode))
        caption_layout.addWidget(self.caption_text)
        caption_layout.addWidget(self.caption_note)
        layout.addWidget(columns(height_field, caption_field))

        # At the cursor, or in a corner of the content area through \cornerfigure (2026-10-26, direct request).
        self.placement_box = QComboBox()
        for corner, label in qr_code.CORNERS.items():
            self.placement_box.addItem(label, corner)
        self.placement_box.setToolTip("A corner puts the code in \\cornerfigure[corner=…]: an overlay on the corner "
                                      "of the content area, whatever else is on the slide.")
        layout.addWidget(Field("On the slide", self.placement_box))

        self.name_edit = QLineEdit()
        self.name_edit.textEdited.connect(self._on_name_edited)
        self.format_box = SegmentedControl([(fmt, fmt.upper()) for fmt in qr_code.PROJECT_FORMATS], current="pdf")
        self.name_field = row(self.name_edit, self.format_box)
        layout.addWidget(Field("File name in media/", self.name_field))

        self.copy_check = QCheckBox("Also save a copy…")
        self.copy_check.toggled.connect(self._on_copy_toggled)
        self.copy_path = QLineEdit()
        self.copy_path.setPlaceholderText("PDF, PNG, SVG or EPS: the format follows the file name")
        self.copy_browse = Button("Browse…", "secondary", compact=True)
        self.copy_browse.clicked.connect(self._browse_copy)
        self.copy_row = row(self.copy_path, self.copy_browse)
        self.copy_row.setEnabled(False)
        layout.addWidget(self.copy_check)
        layout.addWidget(self.copy_row)

        self.advanced_button = Button("▸ Advanced", "ghost", compact=True)
        self.advanced_button.clicked.connect(self._toggle_advanced)
        layout.addWidget(self.advanced_button, 0, Qt.AlignmentFlag.AlignLeft)
        self.advanced = Surface()
        advanced_layout = QHBoxLayout(self.advanced)
        advanced_layout.setContentsMargins(0, 0, 0, 0)
        advanced_layout.setSpacing(12)
        self.error_box = QComboBox()
        for level in qr_code.ERROR_LEVELS:
            self.error_box.addItem(level, level)
            self.error_box.setItemData(self.error_box.count() - 1, ERROR_TIPS[level], Qt.ItemDataRole.ToolTipRole)
        self.error_box.setToolTip("Error correction: " + " ".join(ERROR_TIPS.values()))
        self.error_box.activated.connect(self._on_error_chosen)
        self.error_box.currentIndexChanged.connect(self._changed)
        self.border_box = QSpinBox()
        self.border_box.setRange(1, MAX_BORDER)
        self.border_box.setValue(qr_code.DEFAULT_BORDER)
        self.border_box.setToolTip("The light border around the code, in modules. A scanner needs at least 4.")
        self.border_box.valueChanged.connect(self._changed)
        advanced_layout.addWidget(Field("Error correction", self.error_box))
        advanced_layout.addWidget(Field("Quiet zone (modules)", self.border_box))
        advanced_layout.addStretch(1)
        self.advanced.hide()
        layout.addWidget(self.advanced)

        self.problem = caption()
        self.problem.hide()
        layout.addWidget(self.problem)

        self.add_tab("", body)
        self.add_button("Cancel", role="reject")
        self.insert_button = self.add_button("Update" if existing else "Insert", kind="primary")
        self.insert_button.setDefault(True)
        self.insert_button.clicked.connect(self._on_insert)

        if existing is not None:
            self._fill(existing)
            self.set_title("Update QR code")
        else:
            self.error_box.setCurrentIndex(self.error_box.findData(qr_code.default_error(qr_code.KIND_URL)))
        self._show_page()
        self._on_caption_mode(self.caption_mode_key())
        self.update_preview()
        self._focus_first()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._fit_height()

    def _fit_height(self) -> None:
        """As tall as the fields of the kind need at the sheet's width, once the layout has caught up (on the
        next turn of the event loop): the size Qt picks before the style sheet is applied left a gap under a
        link's one field."""
        def fit() -> None:
            self.layout().activate()
            self.resize(self.width(), max(self.heightForWidth(self.width()), self.minimumSizeHint().height()))
        QTimer.singleShot(0, self, fit)

    # -- building ------------------------------------------------------------------------

    def _build_page(self, kind: str) -> QWidget:
        """The fields of one kind, one entry per name in qr_code.FIELDS[kind]."""
        page = Surface()
        form = QVBoxLayout(page)
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(10)
        read, write = self._read.setdefault(kind, {}), self._write.setdefault(kind, {})

        def line(name: str) -> Field:
            edit = QLineEdit()
            edit.setPlaceholderText(PLACEHOLDERS.get(name, ""))
            edit.textChanged.connect(self._changed)
            read[name], write[name] = edit.text, edit.setText
            setattr(self, f"{kind}_{name}", edit)
            return Field(LABELS[name], edit)

        if kind == qr_code.KIND_EMAIL:
            form.addWidget(line("to"))
            form.addWidget(line("subject"))
            text = QPlainTextEdit()
            text.setFixedHeight(80)
            text.textChanged.connect(self._changed)
            read["body"], write["body"] = text.toPlainText, text.setPlainText
            self.email_body = text
            form.addWidget(Field(LABELS["body"], text))
        elif kind == qr_code.KIND_CONTACT:
            form.addWidget(line("name"))
            form.addWidget(columns(line("organization"), line("title")))
            form.addWidget(columns(line("email"), line("phone")))
            form.addWidget(line("website"))
            form.addWidget(line("street"))
            form.addWidget(columns(line("postcode"), line("city")))
            form.addWidget(line("country"))
        elif kind == qr_code.KIND_EVENT:
            form.addWidget(line("title"))
            self.all_day = QCheckBox("All day")
            self.all_day.toggled.connect(self._on_all_day)
            start = self.event_start = self._date_edit()
            end = self.event_end = self._date_edit()
            self._end_touched = False
            read["start"], write["start"] = (lambda: start.dateTime().toString(self._date_format()),
                                             lambda value: start.setDateTime(_when(value)))
            read["end"], write["end"] = (lambda: end.dateTime().toString(self._date_format()),
                                         lambda value: end.setDateTime(_when(value)))
            read["all_day"] = lambda: "true" if self.all_day.isChecked() else ""
            write["all_day"] = lambda value: self.all_day.setChecked(value == "true")
            # Tomorrow at 10:00: on the hour, so the time is quick to change, and a time a course meets.
            start.setDateTime(QDateTime(QDateTime.currentDateTime().addDays(1).date(), QTime(10, 0)))
            end.setDateTime(start.dateTime().addSecs(3600))
            start.dateTimeChanged.connect(self._on_start_changed)
            end.dateTimeChanged.connect(self._on_end_edited)
            form.addWidget(columns(Field(LABELS["start"], start), Field(LABELS["end"], end)))
            form.addWidget(self.all_day)
            form.addWidget(line("location"))
            description = line("description")
            form.addWidget(description)
            form.addWidget(line("url"))
        elif kind == qr_code.KIND_LOCATION:
            form.addWidget(line("place"))
            form.addWidget(line("label"))
            links = QComboBox()
            for key, label in qr_code.LINK_STYLES.items():
                links.addItem(label, key)
            links.currentIndexChanged.connect(self._changed)
            read["map_link"], write["map_link"] = (lambda: links.currentData(),
                                                   lambda value: links.setCurrentIndex(max(0, links.findData(value))))
            self.link_style = links
            form.addWidget(Field("Link to open", links))
        else:
            form.addWidget(line("url"))
        form.addStretch(1)
        return page

    def _date_edit(self) -> QDateTimeEdit:
        edit = QDateTimeEdit()
        edit.setCalendarPopup(True)
        edit.setDisplayFormat(_WHEN)
        return edit

    def _date_format(self) -> str:
        return _DAY if self.all_day.isChecked() else _WHEN

    def _focus_first(self) -> None:
        first = self.pages.currentWidget().findChild(QLineEdit)
        if first is not None:
            first.setFocus()

    # -- reading and filling ---------------------------------------------------------------

    def kind(self) -> str:
        return self.kind_box.currentData()

    def caption_mode_key(self) -> str:
        return self.caption_mode.current()

    def spec(self) -> qr_code.QRSpec:
        kind = self.kind()
        return qr_code.QRSpec(kind, {name: read() for name, read in self._read[kind].items()},
                              self.error_box.currentData(), self.border_box.value())

    def _fill(self, existing: ExistingCall) -> None:
        spec = existing.spec
        self.kind_box.setCurrentIndex(self.kind_box.findData(spec.kind))
        if spec.kind == qr_code.KIND_EVENT:
            self.all_day.setChecked(spec.value("all_day") == "true")
        for name, write in self._write[spec.kind].items():
            if name != "all_day":
                write(str(spec.fields.get(name, "")))
        self._end_touched = True
        self.error_box.setCurrentIndex(self.error_box.findData(spec.error))
        self.border_box.setValue(spec.border)
        self.height_box.setValue(existing.height)
        self.caption_mode.set_current(existing.caption_mode)
        self.caption_text.setText(existing.caption)
        self.name_edit.setText(Path(existing.image).stem)
        self.name_edit.setEnabled(False)
        suffix = Path(existing.image).suffix.lstrip(".")
        self.format_box.set_current(suffix if suffix in qr_code.PROJECT_FORMATS else "pdf")
        self.format_box.setEnabled(False)      # the file keeps its format: the call names it
        self.placement_box.setEnabled(False)   # Update replaces the call only; a \cornerfigure around it stays
        self.placement_box.setToolTip("Update changes the code where it is; move the call in the source to place it "
                                      "elsewhere.")

    # -- reacting ----------------------------------------------------------------------------

    def _changed(self, *_args) -> None:
        self._timer.start()

    def _show_page(self) -> None:
        """The current kind's fields, at their own height: a stack is as tall as its tallest page otherwise
        (the contact's)."""
        self.pages.setCurrentIndex(self.kind_box.currentIndex())
        for index in range(self.pages.count()):
            policy = QSizePolicy.Policy.Preferred if index == self.pages.currentIndex() else QSizePolicy.Policy.Ignored
            self.pages.widget(index).setSizePolicy(policy, policy)
        self._fit_height()

    def _on_kind(self, _index: int) -> None:
        self._show_page()
        if not self._error_touched:
            self.error_box.setCurrentIndex(self.error_box.findData(qr_code.default_error(self.kind())))
        self._focus_first()
        self._changed()

    def _on_error_chosen(self, _index: int) -> None:
        self._error_touched = True

    def _on_all_day(self, all_day: bool) -> None:
        for edit in (self.event_start, self.event_end):
            edit.setDisplayFormat(_DAY if all_day else _WHEN)
        self._changed()

    def _on_start_changed(self, value: QDateTime) -> None:
        if not self._end_touched:
            self.event_end.blockSignals(True)
            self.event_end.setDateTime(value.addSecs(3600))
            self.event_end.blockSignals(False)
        self._changed()

    def _on_end_edited(self, _value: QDateTime) -> None:
        self._end_touched = True
        self._changed()

    def _on_caption_mode(self, mode: str) -> None:
        self.caption_mode.set_current(mode)
        self.caption_text.setVisible(mode == qr_code.CAPTION_CUSTOM)
        self._changed()

    def _on_name_edited(self, _text: str) -> None:
        self._name_touched = True

    def _toggle_advanced(self) -> None:
        shown = self.advanced.isHidden()
        self.advanced.setVisible(shown)
        self.advanced_button.setText("▾ Advanced" if shown else "▸ Advanced")
        self._fit_height()

    def _on_copy_toggled(self, checked: bool) -> None:
        self.copy_row.setEnabled(checked)
        if checked and not self.copy_path.text():
            self._browse_copy()
            if not self.copy_path.text():
                self.copy_check.setChecked(False)

    def _browse_copy(self) -> None:
        start = self.copy_path.text() or str(Path.home() / f"{self.name_edit.text() or 'qr-code'}.pdf")
        path, _ = QFileDialog.getSaveFileName(self, "Save a copy of the QR code", start, FORMAT_FILTERS)
        if path:
            self.copy_path.setText(path)

    # -- the preview -------------------------------------------------------------------------------

    def _custom_caption(self) -> str:
        return self.caption_text.text() if self.caption_mode_key() == qr_code.CAPTION_CUSTOM else ""

    def update_preview(self) -> None:
        """Draw the code of the fields now (the picture, the sizes, the caption and the name that follow it);
        the message of a ValueError stands in the preview's place."""
        self._timer.stop()
        spec = self.spec()
        self.problem.hide()
        try:
            code = qr_code.make(spec)
        except ValueError as exc:
            self.preview.setPixmap(QPixmap())
            self.preview.setText(str(exc))
            self.info.setText("")
            self.info.setMinimumHeight(0)
            self.caption_note.setText("")
            self.height_hint.hide()
            return
        buffer = io.BytesIO()
        code.save(buffer, kind="png", scale=PREVIEW_SCALE, border=spec.border, dark="#000", light="#fff")
        pixmap = QPixmap()
        pixmap.loadFromData(buffer.getvalue())
        self.preview.setText("")
        self.preview.setPixmap(pixmap.scaled(PREVIEW_SIZE, PREVIEW_SIZE, Qt.AspectRatioMode.KeepAspectRatio,
                                             Qt.TransformationMode.FastTransformation))
        self.info.setText(qr_code.size_note(code, spec.border))
        # A word-wrapped label's height is not part of the column's minimum, so the layout could give it
        # less than its lines need and it ran under the preview (Windows, 125 % scaling): say it outright.
        self.info.setMinimumHeight(self.info.heightForWidth(self.info.width()))
        seminar_room, needed = qr_code.size_advice(code, spec.border)[0]
        low = self.height_box.value() < needed
        set_property(self.height_hint, "tone", "warning")
        self.height_hint.setText(f"Below the {seminar_room} recommendation ({needed:.2f}): the back rows may "
                                 f"not be able to scan it." if low else "")
        self.height_hint.setVisible(low)
        try:
            self.caption_note.setText("Shows: " + qr_code.default_caption(spec)
                                      if self.caption_mode_key() == qr_code.CAPTION_CONTENT else "")
        except ValueError:
            self.caption_note.setText("")
        if not self._name_touched:
            self.name_edit.setText(qr_code.suggest_name(spec, self._custom_caption()))

    # -- inserting ------------------------------------------------------------------------------------

    def _show_problem(self, text: str) -> None:
        self.problem.setText(text)
        set_property(self.problem, "tone", "error")
        self.problem.setVisible(bool(text))

    def _copy_target(self) -> Optional[Path]:
        if not self.copy_check.isChecked():
            return None
        text = self.copy_path.text().strip()
        if not text:
            raise ValueError("Choose where to save the copy, or untick it.")
        path = Path(text)
        if path.suffix.lstrip(".").lower() not in qr_code.FORMATS:
            raise ValueError(f"A copy is saved as {', '.join(qr_code.FORMATS)}: end its name with one of them.")
        return path

    def _on_insert(self) -> None:
        if self._timer.isActive():
            self.update_preview()      # the name follows the last keystroke
        spec = self.spec()
        try:
            copy = self._copy_target()
            created = qr_code.create(
                self.project, spec, height=self.height_box.value(), fmt=self.format_box.current(),
                caption_mode=self.caption_mode_key(), caption=self.caption_text.text(),
                name=self.name_edit.text().strip(), replace=self.existing.image if self.existing else "",
                corner="" if self.existing else self.placement_box.currentData())
            if copy is not None:
                qr_code.save(qr_code.make(spec), copy, border=spec.border)
        except (ValueError, OSError) as exc:
            self._show_problem(str(exc))
            return
        self.created = created
        self.snippet = created.snippet
        self.accept()
