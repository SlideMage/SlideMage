"""The runs of the Images page that take a model: drafting descriptions, translating them.

A run is a QThread (`Job`) so that the window can always stop it (`background.stop_worker`) and
none outlives the window. It works through a queue, writing each image to the store as it
finishes (alt_draft.run_batch / run_translation_batch), and reports through signals; the page
shows it in a `JobCard` with Stop and decides what a result means. The page runs one job at a
time, so a job holds the app-wide Ollama slot (local providers) from start to end.
"""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QProgressBar, QVBoxLayout

from ... import alt_draft, alt_images
from ...ai.providers import ChatProvider
from ..kit import kit_qss as q
from ..kit.widgets import Button, IconLabel


class Job(QThread):
    progress = Signal(int, int, str)    # position in the queue, its length, the image
    image_done = Signal(str, bool)      # a drafted image, whether the store changed
    result = Signal(object, object)     # this job, what `work` returned or the exception it raised

    def __init__(self, title: str, provider: ChatProvider, work: Callable[["Job"], object]) -> None:
        """`work(job)` does the run and returns its summary; it polls `should_stop()` between images."""
        super().__init__()
        self.title = title
        self.provider = provider      # whose Ollama slot the run holds
        self._work = work
        self.stop_requested = False   # Stop was clicked (a second click takes it back)

    def should_stop(self) -> bool:
        return self.stop_requested or self.isInterruptionRequested()

    def run(self) -> None:
        try:
            outcome = self._work(self)
        except Exception as exc:  # noqa: BLE001 -- reported through `result`, never raised in the thread
            outcome = exc
        self.result.emit(self, outcome)


def draft_work(queue: list[alt_draft.ImageJob], backend: alt_draft.ModelBackend) -> Callable[[Job], object]:
    return lambda job: alt_draft.run_batch(
        queue, backend, on_progress=lambda i, n, image_job: job.progress.emit(i, n, image_job.image),
        on_slide_done=job.image_done.emit, should_stop=job.should_stop)


def translate_work(queue: list[str], backend: alt_draft.ModelTranslationBackend) -> Callable[[Job], object]:
    return lambda job: alt_draft.run_translation_batch(
        queue, backend, on_progress=lambda i, n, image: job.progress.emit(i, n, image), should_stop=job.should_stop)


def translate_one_work(backend: alt_draft.ModelTranslationBackend, entry: alt_images.ImageEntry) -> Callable[[Job], object]:
    """The translation of one image's text (alt_draft.TranslationResult); the form applies it."""
    return lambda job: backend.translate(entry)


class JobCard(QFrame):
    """The running job: what it is, how far it is, and Stop. Hidden until `start()`."""

    def __init__(self, on_stop: Callable[[], None]) -> None:
        super().__init__()
        self.setObjectName(q.JOB_CARD)
        inner = QVBoxLayout(self)
        inner.setContentsMargins(20, 14, 20, 14)
        inner.setSpacing(8)
        head = QHBoxLayout()
        head.setSpacing(10)
        head.addWidget(IconLabel("autorenew", 22))
        titles = QVBoxLayout()
        titles.setSpacing(2)
        self.title = QLabel("")
        self.title.setObjectName(q.JOB_TITLE)
        self.detail = QLabel("")
        self.detail.setObjectName(q.JOB_SUB)
        titles.addWidget(self.title)
        titles.addWidget(self.detail)
        head.addLayout(titles, 1)
        self.percent = QLabel("")
        self.percent.setObjectName(q.JOB_PCT)
        head.addWidget(self.percent)
        self.single = False
        self.stop = Button("Stop", "secondary", compact=True)
        self.stop.clicked.connect(on_stop)
        head.addWidget(self.stop)
        inner.addLayout(head)
        self.bar = QProgressBar()
        self.bar.setObjectName(q.JOB_BAR)
        self.bar.setTextVisible(False)
        inner.addWidget(self.bar)
        self.note = QLabel("Each image is saved as soon as it is done, so you can stop any time; "
                           "what is left stays in the queue for next time.")
        self.note.setObjectName(q.PANEL_CAPTION)
        self.note.setWordWrap(True)
        inner.addWidget(self.note)
        self.hide()

    def start(self, title: str, detail: str, steps: int) -> None:
        """Show a job of `steps` images (one: a single request, shown as an unmeasured wait)."""
        self.single = steps <= 1
        self.title.setText(title)
        self.detail.setText(detail)
        self.percent.setText("")
        self.bar.setRange(0, 0 if self.single else 100)
        self.bar.setValue(0)
        self.stop.setText("Stop")
        self.note.setVisible(not self.single)
        self.show()

    def set_progress(self, index: int, total: int, image: str) -> None:
        self.detail.setText(f"Image {index} of {total} · {image}")
        done = (index - 1) * 100 // max(total, 1)
        self.bar.setValue(done)
        self.percent.setText(f"{done}%")

    def set_stopping(self, stopping: bool) -> None:
        self.stop.setText("Stopping after this image… (click to continue)" if stopping else "Stop")

