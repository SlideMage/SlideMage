"""The Admin slides tab of the Deck settings sheet (UI_REDESIGN_PLAN.md, step 9): fetch the Uni Graz
course the deck links and choose which admin slides to generate -- a title slide naming some of the
lecturers, and the sessions table of one group -- and where in the deck they go.

The fetching, the slide sources and the insertion are admin_slides'. The course is fetched once, on
a thread, when the tab is first shown; its two parts (schedule and course detail) can fail
independently, and a part that is not available leaves its section disabled. `slide_specs` is what
Insert slides will create, `position` where it goes.
"""
from __future__ import annotations

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QCheckBox, QComboBox, QPlainTextEdit, QVBoxLayout

from ... import admin_slides, course_schedule, deck_editor
from ...deck_scan import Deck
from ...transcript import deck_language_of
from .. import background
from ..kit.widgets import Field, Page, caption


class _Fetcher(QThread):
    loaded = Signal(object, object)

    def __init__(self, url: str, language: str) -> None:
        super().__init__()
        self.url = url
        self.language = language

    def run(self) -> None:
        self.loaded.emit(*admin_slides.fetch(self.url, self.language))


class AdminSlidesTab(Page):
    changed = Signal()        # slide_specs may be different now

    def __init__(self, deck: Deck) -> None:
        super().__init__()
        self.deck = deck
        self.language = deck_language_of(deck.text)       # "en" or "de", as a compile of the deck uses
        self.slide_specs: list[tuple[str, str]] = []
        self.schedule: course_schedule.CourseSchedule | None = None
        self.detail: course_schedule.CourseDetail | None = None
        self.selected_group: course_schedule.CourseGroup | None = None
        self._lecturer_checks: list[tuple[QCheckBox, course_schedule.Lecturer]] = []
        self._positions = deck_editor.slide_insert_positions(deck)
        self._started = self._cancelled = False

        layout = self.body
        self.status = caption("")
        layout.addWidget(self.status)
        self.language_warning = caption("", "error")
        self.language_warning.hide()
        layout.addWidget(self.language_warning)

        self.title_section = Page()
        self.title_check = QCheckBox("Title slide")
        self.title_status = caption("")
        self.lecturers = QVBoxLayout()
        self.lecturers.setContentsMargins(0, 0, 0, 0)
        self.lecturers.setSpacing(4)
        for widget in (self.title_check, self.title_status):
            self.title_section.body.addWidget(widget)
        self.title_section.body.addLayout(self.lecturers)
        layout.addWidget(self.title_section)

        self.sessions_section = Page()
        self.sessions_check = QCheckBox("Course sessions")
        self.sessions_status = caption("")
        self.group_combo = QComboBox()
        self.group_combo.hide()
        for widget in (self.sessions_check, self.sessions_status, self.group_combo):
            self.sessions_section.body.addWidget(widget)
        layout.addWidget(self.sessions_section)
        for section, check in ((self.title_section, self.title_check), (self.sessions_section, self.sessions_check)):
            check.setChecked(True)
            check.toggled.connect(self._update_preview)
            section.setEnabled(False)
        self.group_combo.currentIndexChanged.connect(self._on_group_changed)

        self.position_combo = QComboBox()
        for position in self._positions:
            self.position_combo.addItem(position.label)
        self.position_combo.setCurrentIndex(len(self._positions) - 1)
        self.position_field = Field("Insert", self.position_combo)
        layout.addWidget(self.position_field)

        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setFixedHeight(130)
        self.preview.setPlaceholderText("The generated LaTeX will appear here.")
        layout.addWidget(self.preview)
        layout.addStretch(1)
        self._show_waiting()

    @property
    def position(self) -> deck_editor.InsertPosition:
        return self._positions[self.position_combo.currentIndex()]

    def _show_waiting(self) -> None:
        """Before the fetch: the hint a deck with no linked course gets, else a waiting note."""
        linked = bool(self.deck.course_url)
        self.status.setText(
            "Loading the linked course…" if linked else
            "This deck links no course page. Add one as the Course link on the General tab, save, "
            "and open Admin slides again.")
        self.title_status.setText("Loading…" if linked else "")
        self.sessions_status.setText("Loading…" if linked else "")
        for widget in (self.title_section, self.sessions_section, self.position_field, self.preview):
            widget.setVisible(linked)

    def start(self) -> None:
        """Fetch the course (once); called when the tab is first shown."""
        if self._started or not self.deck.course_url:
            return
        self._started = True
        fetcher = _Fetcher(self.deck.course_url, self.language)
        fetcher.loaded.connect(self._on_loaded)
        background.start_detached(fetcher)

    def cancel(self) -> None:
        """The sheet closed: a result arriving later is ignored."""
        self._cancelled = True

    def _on_loaded(self, schedule_result: object, detail_result: object) -> None:
        if self._cancelled:
            return
        self.status.setText("")
        self._apply_schedule(schedule_result)
        self._apply_detail(detail_result)
        if isinstance(detail_result, course_schedule.CourseDetail):
            warning = admin_slides.language_warning(self.language, detail_result)
            self.language_warning.setText(warning)
            self.language_warning.setVisible(bool(warning))
        self._update_preview()

    def _apply_schedule(self, result: object) -> None:
        if isinstance(result, course_schedule.CourseSchedule) and result.groups:
            self.schedule = result
            self.selected_group = result.groups[0]
            self.group_combo.addItems(
                [group.name if group.sessions else f"{group.name} (empty)" for group in result.groups])
            self.group_combo.setVisible(len(result.groups) > 1)
            status = f"{len(result.groups)} group(s) found."
            if result.truncated:
                status += " Uni Graz returned only some of this course's groups -- check the course page."
            self.sessions_status.setText(status)
            self.sessions_section.setEnabled(True)
        else:
            self.sessions_status.setText(
                f"Not available: {result if isinstance(result, str) else 'No session groups found.'}")
            self.sessions_check.setChecked(False)

    def _apply_detail(self, result: object) -> None:
        if isinstance(result, course_schedule.CourseDetail) and result.lecturers:
            self.detail = result
            self.title_status.setText(f"{result.title} — {result.semester}")
            for lecturer in result.lecturers:
                check = QCheckBox(f"{lecturer.first_name} {lecturer.last_name} ({lecturer.function})")
                check.setChecked(True)
                check.toggled.connect(self._update_preview)
                self._lecturer_checks.append((check, lecturer))
                self.lecturers.addWidget(check)
            self.title_section.setEnabled(True)
        else:
            self.title_status.setText(
                f"Not available: {result if isinstance(result, str) else 'No lecturers found.'}")
            self.title_check.setChecked(False)

    def _on_group_changed(self, index: int) -> None:
        if self.schedule is not None and 0 <= index < len(self.schedule.groups):
            self.selected_group = self.schedule.groups[index]
            self._update_preview()

    def _update_preview(self) -> None:
        wanted = self.title_check.isChecked(), self.sessions_check.isChecked()
        self.slide_specs = admin_slides.plan_slides(
            self.language,
            detail=self.detail if wanted[0] else None,
            lecturers=tuple(lecturer for check, lecturer in self._lecturer_checks if check.isChecked()),
            group=self.selected_group if wanted[1] and self.schedule is not None else None)
        self.preview.setPlainText("\n\n".join(source for _, source in self.slide_specs))
        self.changed.emit()
