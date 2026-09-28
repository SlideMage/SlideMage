"""Import a linked Uni Graz course schedule as an editable SlideMage slide.

The table follows the deck's own \\decklanguage (v4.1.0, direct
instruction): an English deck gets English headings and its German
schedule terms translated (course_schedule.translate_schedule()), and the
new slide's id-slug carries EN instead of DE."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread, QTimer, Signal
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from . import course_schedule, deck_editor, slide_ids
from .deck_scan import Deck
from .transcript import deck_language_of


# Keep an in-flight request alive if its dialog is closed before the request ends.
_active_fetchers: set[QThread] = set()


def _wait_for_fetchers() -> None:
    """Avoid destroying a running QThread when Qt shuts down."""
    for fetcher in tuple(_active_fetchers):
        fetcher.wait()



class _ScheduleFetcher(QThread):
    loaded = Signal(object)
    failed = Signal(str)

    def __init__(self, url: str) -> None:
        super().__init__()
        self.url = url

    def run(self) -> None:
        try:
            schedule = course_schedule.fetch_schedule(self.url)
        except Exception as exc:
            self.failed.emit(str(exc))
        else:
            self.loaded.emit(schedule)


def build_schedule_slide_source(table: str, language: str = "de") -> str:
    """Wrap a generated LaTeX table in the normal editable slide format."""
    body = table.strip().replace("\r\n", "\n").replace("\r", "\n")
    title = course_schedule.LABELS.get(language, course_schedule.LABELS["de"])["title"]
    lines = [
        r"\setSlideVersion{1-0-0}",
        r"\begin{standardframe}{" + title + "}",
        body,
        r"\end{standardframe}",
        "",
    ]
    return slide_ids.build_new_slide_header() + "\r\n".join(lines)


def insert_schedule_slide(
    deck: Deck, position: deck_editor.InsertPosition, slide_source: str,
    language: str = "de",
) -> Path:
    """Create a new slide, then add its call to a still-current deck."""
    slide_id = slide_ids.mint_slide_id()
    id_slug = f"{slide_id}-{'EN' if language == 'en' else 'DE'}-Course-Sessions"
    slide_path = slide_ids.SLIDES_DIR / f"{id_slug}-current.tex"
    slide_path.parent.mkdir(parents=True, exist_ok=True)
    # Reserve the ID before editing the deck, like the ordinary Add slide path.
    slide_ids.append_slide_id(slide_id)
    with slide_path.open("x", encoding="utf-8", newline="") as destination:
        destination.write(slide_source)
    try:
        deck_editor.insert_slide_call(
            deck.path, deck.text, position.insert_at, position.indent,
            "slide", id_slug,
        )
    except Exception:
        slide_path.unlink(missing_ok=True)
        raise
    return slide_path


class CourseScheduleDialog(QDialog):
    """Fetch, choose a group when needed, and preview insertion position."""

    def __init__(self, parent: QWidget, deck: Deck) -> None:
        super().__init__(parent)
        self.deck = deck
        self._cancelled = False
        self.slide_source: str | None = None
        # "en" or "de", as a compile of this deck would use.
        self.language = deck_language_of(deck.text)
        self._positions = deck_editor.slide_insert_positions(deck)
        self.setWindowTitle("Import course sessions")
        self.resize(790, 560)

        layout = QVBoxLayout(self)
        self.status_label = QLabel("Loading the linked course schedule…")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        form = QFormLayout()
        self.position_combo = QComboBox()
        for position in self._positions:
            self.position_combo.addItem(position.label)
        self.position_combo.setCurrentIndex(len(self._positions) - 1)
        self.position_combo.setEnabled(False)
        form.addRow("Insert:", self.position_combo)
        layout.addLayout(form)

        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setPlaceholderText("The generated LaTeX table will appear here.")
        layout.addWidget(self.preview, stretch=1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.insert_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.insert_button.setText("Insert slide")
        self.insert_button.setEnabled(False)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        QTimer.singleShot(0, self._start_fetch)

    @property
    def position(self) -> deck_editor.InsertPosition:
        return self._positions[self.position_combo.currentIndex()]

    def _start_fetch(self) -> None:
        fetcher = _ScheduleFetcher(self.deck.course_url or "")
        app = QApplication.instance()
        if app is not None and not app.property("_slidemage_schedule_quit_hook"):
            app.aboutToQuit.connect(_wait_for_fetchers)
            app.setProperty("_slidemage_schedule_quit_hook", True)
        _active_fetchers.add(fetcher)
        fetcher.loaded.connect(self._show_schedule)
        fetcher.failed.connect(self._show_error)
        fetcher.finished.connect(lambda: _active_fetchers.discard(fetcher))
        fetcher.start()

    def reject(self) -> None:
        self._cancelled = True
        super().reject()

    def _show_error(self, message: str) -> None:
        if self._cancelled:
            return
        QMessageBox.critical(self, "Import course sessions failed", message)
        self.reject()

    def _show_schedule(self, schedule: course_schedule.CourseSchedule) -> None:
        if self._cancelled:
            return
        groups = schedule.groups
        if not groups:
            self._show_error("The course page contains no session groups.")
            return
        group = groups[0]
        if len(groups) > 1:
            names = [item.name for item in groups]
            chosen, ok = QInputDialog.getItem(
                self, "Select course group", "Group:", names, 0, False,
            )
            if not ok:
                self.reject()
                return
            group = groups[names.index(chosen)]

        note = ""
        if self.language == "en":
            group = course_schedule.translate_schedule(
                course_schedule.CourseSchedule(schedule.title, (group,))).groups[0]
            note = " — translated to English for this English deck"
        table = course_schedule.render_group_table(schedule, group, self.language)
        self.slide_source = build_schedule_slide_source(table, self.language)
        self.status_label.setText(
            f"{schedule.title} — {group.name} ({len(group.sessions)} sessions){note}"
        )
        self.preview.setPlainText(self.slide_source)
        self.position_combo.setEnabled(True)
        self.insert_button.setEnabled(True)
