"""Fetch a deck's linked Uni Graz course and insert admin slides from it:
a course-sessions table and/or a title slide, each optional."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread, QTimer, Signal
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from . import course_schedule, deck_editor, slide_ids
from .deck_scan import Deck


# Keep an in-flight request alive if its dialog is closed before the request ends.
_active_fetchers: set[QThread] = set()


def _wait_for_fetchers() -> None:
    """Avoid destroying a running QThread when Qt shuts down."""
    for fetcher in tuple(_active_fetchers):
        fetcher.wait()


class _AdminDataFetcher(QThread):
    """Fetches the schedule and the course detail independently -- one
    failing (e.g. a course with no public session list) doesn't block the
    other from offering its own slide."""

    loaded = Signal(object, object)

    def __init__(self, url: str) -> None:
        super().__init__()
        self.url = url

    def run(self) -> None:
        try:
            schedule: object = course_schedule.fetch_schedule(self.url)
        except Exception as exc:
            schedule = str(exc)
        try:
            detail: object = course_schedule.fetch_course_detail(self.url)
        except Exception as exc:
            detail = str(exc)
        self.loaded.emit(schedule, detail)


def _build_slide_source(body: str) -> str:
    """Wrap a generated LaTeX frame in the normal editable slide format."""
    body = body.strip().replace("\r\n", "\n").replace("\r", "\n")
    lines = [r"\setSlideVersion{1-0-0}", body, ""]
    return slide_ids.build_new_slide_header() + "\r\n".join(lines)


def build_sessions_slide_source(table: str) -> str:
    return _build_slide_source("\n".join((
        r"\begin{standardframe}{Abhaltungstermine}", table.strip(), r"\end{standardframe}",
    )))


def build_title_slide_source(titleframe_call: str) -> str:
    return _build_slide_source(titleframe_call)


def insert_admin_slides(
    deck: Deck, position: deck_editor.InsertPosition, slide_specs: list[tuple[str, str]],
) -> list[Path]:
    """Create one new slide per ``(id_suffix, slide_source)`` spec, then add
    all their calls to the deck in one edit, in order, at the insert
    position. If anything fails, the new slide files are removed and the
    deck is left untouched."""
    slide_paths: list[Path] = []
    id_slugs: list[str] = []
    try:
        for id_suffix, source in slide_specs:
            slide_id = slide_ids.mint_slide_id()
            id_slug = f"{slide_id}-DE-{id_suffix}"
            slide_path = slide_ids.SLIDES_DIR / f"{id_slug}-current.tex"
            slide_path.parent.mkdir(parents=True, exist_ok=True)
            # Reserve the ID before editing the deck, like the ordinary Add slide path.
            slide_ids.append_slide_id(slide_id)
            with slide_path.open("x", encoding="utf-8", newline="") as destination:
                destination.write(source)
            slide_paths.append(slide_path)
            id_slugs.append(id_slug)
        deck_editor.insert_slide_calls(
            deck.path, deck.text, position.insert_at, position.indent, id_slugs,
        )
    except Exception:
        for slide_path in slide_paths:
            slide_path.unlink(missing_ok=True)
        raise
    return slide_paths


class AdminSlidesDialog(QDialog):
    """Fetch the linked course, let the user pick which admin slides to
    generate (and, per slide, a group or a lecturer subset), and preview
    the insertion position."""

    def __init__(self, parent: QWidget, deck: Deck) -> None:
        super().__init__(parent)
        self.deck = deck
        self._cancelled = False
        self.schedule: course_schedule.CourseSchedule | None = None
        self.detail: course_schedule.CourseDetail | None = None
        self.selected_group: course_schedule.CourseGroup | None = None
        self._lecturer_checks: list[tuple[QCheckBox, course_schedule.Lecturer]] = []
        self.slide_specs: list[tuple[str, str]] = []
        self._positions = deck_editor.slide_insert_positions(deck)
        self.setWindowTitle("Admin slides")
        self.resize(790, 620)

        layout = QVBoxLayout(self)
        self.status_label = QLabel("Loading the linked course…")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.title_group = QGroupBox("Title slide")
        self.title_group.setCheckable(True)
        self.title_group.setChecked(True)
        self.title_group.setEnabled(False)
        title_layout = QVBoxLayout(self.title_group)
        self.title_status = QLabel("Loading…")
        self.title_status.setWordWrap(True)
        title_layout.addWidget(self.title_status)
        self.lecturer_layout = QVBoxLayout()
        title_layout.addLayout(self.lecturer_layout)
        self.title_group.toggled.connect(self._update_preview)
        layout.addWidget(self.title_group)

        self.sessions_group = QGroupBox("Course sessions")
        self.sessions_group.setCheckable(True)
        self.sessions_group.setChecked(True)
        self.sessions_group.setEnabled(False)
        sessions_layout = QVBoxLayout(self.sessions_group)
        self.sessions_status = QLabel("Loading…")
        self.sessions_status.setWordWrap(True)
        sessions_layout.addWidget(self.sessions_status)
        self.group_combo = QComboBox()
        self.group_combo.setVisible(False)
        self.group_combo.currentIndexChanged.connect(self._on_group_changed)
        sessions_layout.addWidget(self.group_combo)
        self.sessions_group.toggled.connect(self._update_preview)
        layout.addWidget(self.sessions_group)

        form = QFormLayout()
        self.position_combo = QComboBox()
        for position in self._positions:
            self.position_combo.addItem(position.label)
        self.position_combo.setCurrentIndex(len(self._positions) - 1)
        form.addRow("Insert:", self.position_combo)
        layout.addLayout(form)

        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setPlaceholderText("The generated LaTeX will appear here.")
        layout.addWidget(self.preview, stretch=1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.insert_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.insert_button.setText("Insert slides")
        self.insert_button.setEnabled(False)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        QTimer.singleShot(0, self._start_fetch)

    @property
    def position(self) -> deck_editor.InsertPosition:
        return self._positions[self.position_combo.currentIndex()]

    def _start_fetch(self) -> None:
        fetcher = _AdminDataFetcher(self.deck.course_url or "")
        app = QApplication.instance()
        if app is not None and not app.property("_slidemage_admin_slides_quit_hook"):
            app.aboutToQuit.connect(_wait_for_fetchers)
            app.setProperty("_slidemage_admin_slides_quit_hook", True)
        _active_fetchers.add(fetcher)
        fetcher.loaded.connect(self._on_loaded)
        fetcher.finished.connect(lambda: _active_fetchers.discard(fetcher))
        fetcher.start()

    def reject(self) -> None:
        self._cancelled = True
        super().reject()

    def _on_loaded(self, schedule_result: object, detail_result: object) -> None:
        if self._cancelled:
            return
        self.status_label.setText("")
        self._apply_schedule_result(schedule_result)
        self._apply_detail_result(detail_result)
        self._update_preview()

    def _apply_schedule_result(self, result: object) -> None:
        if isinstance(result, course_schedule.CourseSchedule) and result.groups:
            self.schedule = result
            self.selected_group = result.groups[0]
            names = [group.name if group.sessions else f"{group.name} (empty)"
                     for group in result.groups]
            self.group_combo.addItems(names)
            self.group_combo.setVisible(len(names) > 1)
            status = f"{len(result.groups)} group(s) found."
            if result.truncated:
                status += " Uni Graz returned only some of this course's groups -- check the course page."
            self.sessions_status.setText(status)
            self.sessions_group.setEnabled(True)
        else:
            message = result if isinstance(result, str) else "No session groups found."
            self.sessions_status.setText(f"Not available: {message}")
            self.sessions_group.setChecked(False)
            self.sessions_group.setEnabled(False)

    def _apply_detail_result(self, result: object) -> None:
        if isinstance(result, course_schedule.CourseDetail) and result.lecturers:
            self.detail = result
            self.title_status.setText(f"{result.title} — {result.semester}")
            for lecturer in result.lecturers:
                checkbox = QCheckBox(f"{lecturer.first_name} {lecturer.last_name} ({lecturer.function})")
                checkbox.setChecked(True)
                checkbox.toggled.connect(self._update_preview)
                self._lecturer_checks.append((checkbox, lecturer))
                self.lecturer_layout.addWidget(checkbox)
            self.title_group.setEnabled(True)
        else:
            message = result if isinstance(result, str) else "No lecturers found."
            self.title_status.setText(f"Not available: {message}")
            self.title_group.setChecked(False)
            self.title_group.setEnabled(False)

    def _on_group_changed(self, index: int) -> None:
        if self.schedule is not None and 0 <= index < len(self.schedule.groups):
            self.selected_group = self.schedule.groups[index]
            self._update_preview()

    def _update_preview(self) -> None:
        specs: list[tuple[str, str]] = []
        if self.title_group.isChecked() and self.detail is not None:
            selected = tuple(lecturer for checkbox, lecturer in self._lecturer_checks if checkbox.isChecked())
            call = course_schedule.render_title_slide(self.detail, selected)
            specs.append(("Title-Slide", build_title_slide_source(call)))
        if self.sessions_group.isChecked() and self.schedule is not None and self.selected_group is not None:
            table = course_schedule.render_group_table(self.selected_group)
            specs.append(("Course-Sessions", build_sessions_slide_source(table)))
        self.slide_specs = specs
        self.preview.setPlainText("\n\n".join(source for _, source in specs))
        self.insert_button.setEnabled(bool(specs))
