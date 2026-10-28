# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The window's side of background rendering (background_renders.py): it feeds the idle gate with the user's input
and with what keeps the machine busy, tells the store which decks are used and where, shows what is left in a
small chip, and stops everything when the window closes.

The chip stands over the bottom left of the workspace and is there only while there is something to say: previews
being prepared (with how many are left), prepared previews waiting for the user to stop working (and why), or
slides that cannot be rendered; once everything is rendered it says so in green. Clicking it, or the dial beside
it, opens the status window: the decks in the order they are worked through, which ones are prepared at all, the
renders running now, the disk space used and the controls: pause, render now, retry the failed slides.
"""
from __future__ import annotations

import os
import sys
from weakref import WeakSet
from typing import Optional

from PySide6.QtCore import QEvent, QObject, QPoint, QRectF, QSize, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QCursor, QFont, QPainter, QPen
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QDialog, QHBoxLayout, QHeaderView, QLabel, QMessageBox,
                               QProgressBar, QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from ... import app_settings, background_renders, compile_records, compiler, idle_gate, render_key, render_store
from ...background_renders import BackgroundRenderer
from ...plugins import session
from ...plugins.host import plugin_render_priority
from ..kit.widgets import Chip

NO_BACKGROUND_ENV = "SLIDEMAGE_NO_BACKGROUND_PREVIEWS"     # set by the tests: nothing renders by itself
REFRESH_MS = 1000
USE_WIDGET_INPUT_WATCHER = sys.platform.startswith("linux")
MARGIN = 14
INPUT_EVENTS = {QEvent.Type.MouseMove, QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease, QEvent.Type.KeyPress,
                QEvent.Type.Wheel, QEvent.Type.TouchBegin}


VIEW_COLUMNS = (("instructor", "Instructor"), ("during-course", "During course"), ("after-course", "After course"))
DIAL_SIZE = 34
BIG_DIAL_SIZE = 88      # the status window's, top right


def waiting_text(reason: str) -> str:
    """Why nothing renders now, for the dial's tooltip and the status window."""
    return idle_gate.IN_USE_EXPLAINED if reason == idle_gate.IN_USE else f"Waiting: {reason}."


class Dial(QWidget):
    """A ring that fills with the share of the renders that are up to date; the number in it is the percentage.
    Small and clickable in the main window; large, with a % sign and not clickable, in the status window."""

    clicked = Signal()

    def __init__(self, parent: QWidget | None = None, size: int = DIAL_SIZE, clickable: bool = True) -> None:
        super().__init__(parent)
        self.percent = 0.0
        self.state = "idle"          # idle, working, waiting, done, failed
        self.setFixedSize(QSize(size, size))
        if clickable:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setAccessibleName("Background previews")

    def set_value(self, percent: float, state: str) -> None:
        self.percent, self.state = max(0.0, min(100.0, percent)), state
        self.update()

    def text(self) -> str:
        return f"{int(self.percent)}" + ("%" if self.width() > DIAL_SIZE else "")

    def mousePressEvent(self, event) -> None:      # noqa: N802 -- Qt's name
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()

    def keyPressEvent(self, event) -> None:        # noqa: N802
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.clicked.emit()
        else:
            super().keyPressEvent(event)

    def paintEvent(self, _event) -> None:          # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        text = self.palette().windowText().color()
        track = QColor(text)
        track.setAlpha(50)
        colours = {"done": QColor("#2e9e5b"), "working": QColor("#2f7fd8"), "failed": QColor("#d9822b")}
        arc = colours.get(self.state, QColor(text))
        if self.state in ("idle", "waiting"):
            arc.setAlpha(150)
        scale = self.width() / DIAL_SIZE
        width = 3 * scale ** 0.5        # the ring grows thinner than the dial, or a large one looks heavy
        rect = QRectF(width, width, self.width() - 2 * width, self.height() - 2 * width)
        painter.setPen(QPen(track, width))
        painter.drawEllipse(rect)
        pen = QPen(arc, width)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawArc(rect, 90 * 16, -int(self.percent * 3.6 * 16))
        font = QFont(self.font())
        font.setPixelSize(round(10 * scale * (0.8 if scale > 1 else 1)))     # room for the % sign
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(text)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, self.text())


class StatusDialog(QDialog):
    """Which decks are up to date and which are outstanding, per version, in the order they are worked through.
    Opened from the dial and from the chip. A deck's tick says whether it is prepared in the background."""

    def __init__(self, controller: "BackgroundPreviews", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.controller = controller
        self.setWindowTitle("Background previews")
        self.setMinimumSize(720, 420)
        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.summary.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        top.addWidget(self.summary, 1)
        self.dial = Dial(self, BIG_DIAL_SIZE, clickable=False)
        top.addWidget(self.dial, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(top)
        self.overall = QProgressBar()
        self.overall.setRange(0, 100)
        layout.addWidget(self.overall)
        self.tree = QTreeWidget()
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(True)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.tree.setHeaderLabels(["Deck", *[label for _view, label in VIEW_COLUMNS], "Status"])
        self.tree.headerItem().setToolTip(0, "Ticked decks are prepared in the background.")
        self.tree.itemChanged.connect(self._deck_ticked)
        header = self.tree.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in range(1, 5):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.tree, 1)
        self.running_title = QLabel()
        layout.addWidget(self.running_title)
        self.running = QTreeWidget()
        self.running.setRootIsDecorated(False)
        self.running.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.running.setHeaderLabels(["Deck", "Slide", "Version", "Language", "For", "Running"])
        running_header = self.running.header()
        running_header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for column in (0, 2, 3, 4, 5):
            running_header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        self.running.setMaximumHeight(170)
        layout.addWidget(self.running)
        self.note = QLabel()
        self.note.setWordWrap(True)
        layout.addWidget(self.note)
        buttons = QHBoxLayout()
        self.pause = QPushButton()
        self.pause.clicked.connect(lambda: (controller.toggle_pause(), self.refresh()))
        self.render_now = QPushButton("Render now")
        self.render_now.clicked.connect(lambda: (controller.render_now(), self.refresh()))
        self.failures = QPushButton("Failed slides…")
        self.failures.clicked.connect(controller.show_failures)
        self.retry = QPushButton("Try failed slides again")
        self.retry.clicked.connect(lambda: (controller.retry_failed(), self.refresh()))
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        for button in (self.pause, self.render_now, self.failures, self.retry):
            buttons.addWidget(button)
        buttons.addStretch(1)
        buttons.addWidget(close)
        layout.addLayout(buttons)
        self._timer = QTimer(self)
        self._timer.setInterval(REFRESH_MS)
        self._timer.timeout.connect(self.refresh)
        self._timer.start()
        self.refresh()

    @staticmethod
    def cell(counts: Optional[list]) -> str:
        if not counts:
            return "–"
        total, fresh, failed = counts
        return f"{fresh} / {total}" + (f"  ({failed} failed)" if failed else "")

    def refresh(self) -> None:
        controller = self.controller
        renderer = controller.renderer
        if renderer is None:
            self.summary.setText("Background previews are not available.")
            return
        progress = renderer.progress
        used = (controller.store.total_bytes() if controller.store else 0) / 1024 ** 3
        self.summary.setText(f"{controller.hover_text()}\nStored previews: {used:.2f} GB of {renderer.limit_bytes() / 1024 ** 3:.1f} GB.")
        self.dial.set_value(progress.percent, controller.dial_state())
        self.overall.setValue(int(progress.percent))
        off = renderer.decks_off()          # the setting, not the plan: a tick holds before the next plan
        self.tree.blockSignals(True)
        self.tree.clear()
        for deck in progress.decks:
            if deck.off:
                status = "left out"
            elif deck.total == 0:
                status = "no slides"
            elif deck.up_to_date:
                status = "up to date"
            elif deck.left == 0:
                status = f"{deck.failed} failed"
            else:
                status = f"{deck.left} outstanding"
                if progress.working and progress.working.startswith(deck.deck + ":"):
                    status += " · rendering"
            item = QTreeWidgetItem([deck.deck, *[self.cell(deck.views.get(view)) for view, _label in VIEW_COLUMNS], status])
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(0, Qt.CheckState.Unchecked if deck.deck in off else Qt.CheckState.Checked)
            for column in range(1, 4):
                item.setTextAlignment(column, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.tree.addTopLevelItem(item)
        self.tree.blockSignals(False)
        self._refresh_running(renderer)
        reason = renderer.waiting_because()
        self.note.setText(waiting_text(reason) if reason and progress.left else "")
        self.pause.setText("Resume" if renderer.gate.paused else "Pause")
        self.failures.setVisible(bool(progress.failures))
        self.retry.setVisible(bool(progress.failures))

    def _deck_ticked(self, item: QTreeWidgetItem, column: int) -> None:
        if column == 0:
            self.controller.set_deck_enabled(item.text(0), item.checkState(0) == Qt.CheckState.Checked)

    def _refresh_running(self, renderer) -> None:
        """One row per render running now (several run at once); the title says how many may and why not more."""
        from ... import background_renders

        running = renderer.running()
        allowed, load = renderer.capacity()
        title = f"Running now: {len(running)} of up to {allowed}"
        if load is not None:
            title += f" · processor {round(load * 100)}% busy"
            if running and len(running) < allowed and load >= background_renders.CPU_LIMIT:
                title += f" (more start below {round(background_renders.CPU_LIMIT * 100)}%)"
        self.running_title.setText(title)
        labels = dict(VIEW_COLUMNS)
        self.running.clear()
        for entry in running:
            seconds = int(entry["seconds"])
            item = QTreeWidgetItem([entry["deck"] or "–", entry["slide"], labels.get(entry["view"], entry["view"]),
                                    entry["language"], entry["kind"], f"{seconds // 60}:{seconds % 60:02d}"])
            item.setTextAlignment(5, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.running.addTopLevelItem(item)
        self.running.setVisible(bool(running))

    def done(self, result) -> None:
        self._timer.stop()
        super().done(result)


class _InputWatcher(QObject):
    """Watch input application-wide, using widget filters on Linux.

    On Linux, an application event filter can crash in Shiboken while wrapping
    Qt WebEngine's private focus objects. Discover widgets periodically there;
    other platforms keep the application filter without a polling timer.
    """

    def __init__(self, on_input, parent: QObject) -> None:
        super().__init__(parent)
        self._on_input = on_input
        self._mouse = None
        self._watched = WeakSet()
        self._timer: Optional[QTimer] = None
        if not USE_WIDGET_INPUT_WATCHER:
            QApplication.instance().installEventFilter(self)
            return
        self._cursor = QCursor.pos()
        self._timer = QTimer(self)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self._watch_widgets)
        self._watch_widgets()
        self._timer.start()

    def _watch_widgets(self) -> None:
        # Widgets without mouse tracking discard unpressed mouse moves before
        # their filters run. Poll movement while this application is active too.
        cursor = QCursor.pos()
        if cursor != self._cursor and QApplication.activeWindow() is not None:
            self._on_input()
        self._cursor = cursor
        for widget in QApplication.allWidgets():
            if widget not in self._watched:
                widget.installEventFilter(self)
                self._watched.add(widget)

    def stop(self) -> None:
        if self._timer is None:
            QApplication.instance().removeEventFilter(self)
            return
        self._timer.stop()
        for widget in QApplication.allWidgets():
            if widget in self._watched:
                widget.removeEventFilter(self)
        self._watched.clear()

    def eventFilter(self, watched, event) -> bool:      # noqa: N802 -- Qt's name
        kind = event.type()
        if kind not in INPUT_EVENTS:
            return False
        if kind == QEvent.Type.MouseMove:
            # Qt also sends mouse moves of its own when widgets appear or change under a still cursor (the Preview
            # refreshes every few seconds): only the mouse actually moving is "the user is here".
            position = event.globalPosition().toPoint() if hasattr(event, "globalPosition") else None
            moved, self._mouse = position != self._mouse, position
            if not event.spontaneous() or not moved:
                return False
        self._on_input()
        return False


class BackgroundPreviews(QObject):
    changed = Signal()      # from any thread: the progress moved

    def __init__(self, window, central: QWidget, *, autostart: Optional[bool] = None) -> None:
        super().__init__(window)
        self.window = window
        self.project = window.project
        self.store: Optional[render_store.RenderStore] = None
        self.renderer: Optional[BackgroundRenderer] = None
        self.chip = Chip("", "info", pressable=True, parent=central)
        self.chip.hide()
        self.chip.clicked.connect(self.show_status)
        self.dial = Dial(central)
        self.dial.hide()
        self.dial.clicked.connect(self.show_status)
        self._status_dialog: Optional[StatusDialog] = None
        self._central = central
        # In the centre column's own status row when there is one (laid out, so it never covers the views).
        self._row = getattr(getattr(window, "centre", None), "status_row", None)
        if self._row is not None:
            self._row.layout().insertWidget(0, self.dial)
            self._row.layout().insertWidget(1, self.chip)
        central.installEventFilter(self)
        stack = getattr(window, "stack", None)
        if stack is not None:
            stack.installEventFilter(self)
        self._timer = QTimer(self)
        self._timer.setInterval(REFRESH_MS)
        self._timer.timeout.connect(self.refresh)
        self.changed.connect(self.refresh)
        try:
            self.store = render_store.RenderStore(self.project)
        except Exception:  # noqa: BLE001 -- no cache folder, no background rendering; the app works without
            return
        self.renderer = BackgroundRenderer(
            self.project, self.store, decks=lambda: window.decks, open_deck=lambda: window.state.deck,
            on_change=self.changed.emit, plugin_soon=plugin_render_priority(session.loaded(), self.project))
        self.renderer.gate._busy = self._busy_reasons
        if autostart is None and not os.environ.get(NO_BACKGROUND_ENV):
            # The trace file of what background rendering decided (background_renders.Trace), in the cache folder.
            from ...project import cache_dir
            self.renderer._trace = background_renders.Trace(cache_dir() / "background-trace.log")
        self._chip_said = None
        compiler.COMPILE_LISTENERS.append(self._on_compiled)
        self._watcher = _InputWatcher(self.renderer.user_active, self)
        # Background renders only while SlideMage is not in front; coming back stops the running ones (v8.52.0).
        app = QApplication.instance()
        app.applicationStateChanged.connect(self._application_state)
        self.renderer.gate.note_focus(app.applicationState() == Qt.ApplicationState.ApplicationActive)
        self.renderer.gate.presenting = lambda: getattr(window, "presentation", None) is not None
        state = window.state
        state.deck_changed.connect(self._deck_opened)
        state.focused_slide_changed.connect(self._slide_focused)
        state.view_changed.connect(lambda view: self._touch(view=view))
        state.language_changed.connect(lambda language: self._touch(language=language))
        window.compile.ended.connect(self.renderer.replan)
        if autostart is None:
            autostart = not os.environ.get(NO_BACKGROUND_ENV)
        if autostart:
            self.renderer.start()
            self._timer.start()

    # -- what the gate asks ------------------------------------------------------------------

    def _busy_reasons(self) -> list[str]:
        from ... import busy
        reasons = busy.reasons()
        window = self.window
        if getattr(window, "compile", None) is not None and window.compile.running:
            reasons.append("a compile")
        runner = getattr(getattr(window, "assistant", None), "tasks", None)
        if runner is not None and getattr(runner, "busy", False):
            reasons.append("an AI task")
        preview = getattr(getattr(window, "centre", None), "preview", None)
        if preview is not None and getattr(preview, "_busy", False):
            reasons.append("the Preview")
        if QApplication.activeModalWidget() is not None:
            reasons.append("a dialog")
        return reasons

    def _application_state(self, state) -> None:
        if self.renderer is not None:
            self.renderer.window_focus(state == Qt.ApplicationState.ApplicationActive)
            self.refresh()

    # -- what the store is told ----------------------------------------------------------------

    def _deck_opened(self, deck) -> None:
        if deck is None or self.store is None:
            return
        state = self.window.state
        self.store.touch_deck(deck.name, opened=True, view=state.view, language=state.language)
        self.renderer.replan()

    def _slide_focused(self, slide_id) -> None:
        if slide_id and self.window.state.deck is not None and self.store is not None:
            self.store.touch_deck(self.window.state.deck.name, slide=slide_id)

    def _touch(self, **fields) -> None:
        if self.window.state.deck is not None and self.store is not None:
            self.store.touch_deck(self.window.state.deck.name, **fields)

    def deck_archived(self, deck) -> None:
        if self.renderer is not None:
            self.renderer.deck_archived(deck)

    def settings_changed(self) -> None:
        if self.renderer is not None:
            self.renderer.settings_changed()
            if self.renderer.enabled and self._timer is not None and not self._timer.isActive():
                self.renderer.start()
                self._timer.start()
        self.refresh()

    def _on_compiled(self, ctx, job, pdf) -> None:
        """A whole-deck compile of this project ended (called on a thread of its own): its slides go to the store, and
        the Preview shows them as current renders (background_renders.ingest_compile)."""
        renderer = self.renderer
        if renderer is None or self.store is None or not renderer.enabled or ctx.root != self.project.root:
            return
        record = compile_records.read_record(ctx.build_dir, job.jobname)
        if record is not None and renderer.ingest_compile(job, pdf, record):
            self.changed.emit()
        renderer.replan()          # the slides that need their deck can be typeset in this compile now

    def stop(self) -> None:
        if self._on_compiled in compiler.COMPILE_LISTENERS:
            compiler.COMPILE_LISTENERS.remove(self._on_compiled)
        self._timer.stop()
        if hasattr(self, "_watcher"):
            self._watcher.stop()
            try:
                QApplication.instance().applicationStateChanged.disconnect(self._application_state)
            except (RuntimeError, TypeError):
                pass
        if self.renderer is not None:
            self.renderer.stop()
        if self.store is not None:
            self.store.close()
            self.store = None

    def stored_page(self, target, view: str, language: str, deck_name: str):
        """The last page (every reveal step has been shown) of the stored render of `target` as PNG bytes if a
        current one is there, else None. A slidestep call keeps its own step restriction, which a stored
        unrestricted render does not show. Runs on the Preview's display worker: `deck_name` is the open deck's,
        read by the caller on the GUI thread."""
        renderer = self.renderer
        if renderer is None or self.store is None or not renderer.enabled:
            return None
        if target.macro == "slidestep" and target.steps:
            return None
        try:
            unit = render_key.unit_for(target, view, language, deck_name)
            found = renderer.resolver.lookup(unit)
            if not found.usable:
                return None
            return self.store.page(found.record, found.record["pages"])
        except Exception:  # noqa: BLE001 -- the store is a help; a broken one must not break the Preview
            return None

    def stored_pages(self, target, view: str, language: str, deck_name: str):
        """Every page (reveal step) of the stored render of `target` as PNG bytes if a current one is there, else
        None. The reveal bar takes its steps from here instead of counting them with a render. Like `stored_page`,
        it runs on the display worker."""
        renderer = self.renderer
        if renderer is None or self.store is None or not renderer.enabled:
            return None
        if target.needs_context or (target.macro == "slidestep" and target.steps):
            return None
        try:
            unit = render_key.unit_for(target, view, language, deck_name)
            found = renderer.resolver.lookup(unit)
            if not found.usable or found.record.get("partial"):
                return None                 # a deck compile's page is the last step only: not the list of steps
            pages = [self.store.page(found.record, number) for number in range(1, int(found.record["pages"]) + 1)]
            return pages if pages and all(pages) else None
        except Exception:  # noqa: BLE001 -- the store is a help
            return None

    def store_steps(self, target, view: str, language: str, pdf, pages) -> None:
        """Keep the reveal bar's own all-steps render in the store (called from its worker thread)."""
        renderer = self.renderer
        if renderer is None or self.store is None or not renderer.enabled:
            return
        if target.needs_context or (target.macro == "slidestep" and target.steps):
            return
        deck = self.window.state.deck
        unit = render_key.unit_for(target, view, language, deck.name if deck is not None else "")
        renderer.store_reveal(unit, pdf, pages)

    # -- the chip --------------------------------------------------------------------------------

    def summary(self) -> tuple[str, str]:
        """(text, tone) of the chip; the text is empty when there is nothing to say."""
        renderer = self.renderer
        if renderer is None or not renderer.enabled:
            return "", "muted"
        progress = renderer.progress
        left = progress.left
        if left > 0:
            if renderer.sweeping():
                return f"Preparing previews · {left} left", "info"
            reason = renderer.waiting_because()
            if reason == idle_gate.IN_USE:
                return f"Previews wait while you use SlideMage · {left} left", "muted"
            return (f"Preview rendering paused ({reason}) · {left} left" if reason else f"Previews · {left} left"), "muted"
        if progress.failures:
            return f"{progress.failures} slide{'s' if progress.failures != 1 else ''} cannot be rendered", "warning"
        return "All previews are up to date.", "ok_text"

    def hover_text(self) -> str:
        """What the dial's tooltip and the status window's first lines say."""
        renderer = self.renderer
        if renderer is None or not renderer.enabled:
            return "Background previews are switched off (Settings → General)."
        progress = renderer.progress
        if not progress.scanned_at:
            return "Background previews: looking at your decks…"
        lines = [f"{progress.percent:.0f} % of the previews of your decks are up to date: "
                 f"{progress.fresh} of {progress.total} renders, {progress.decks_up_to_date} of {progress.decks_counted} decks complete."]
        if progress.left:
            lines.append(f"{progress.left} outstanding, most recently used decks first, instructor version first.")
        if progress.failures:
            lines.append(f"{progress.failures} slide{'s' if progress.failures != 1 else ''} cannot be rendered.")
        if renderer.sweeping():
            lines.append("Rendering now.")
        elif progress.left and renderer.waiting_because():
            lines.append(waiting_text(renderer.waiting_because()))
        elif not progress.left:
            lines.append("Everything is ready.")
        return "\n".join(lines)

    def dial_state(self) -> str:
        progress = self.renderer.progress
        if self.renderer.sweeping():
            return "working"
        if progress.left == 0:
            return "failed" if progress.failures else "done"
        return "waiting"

    def refresh(self) -> None:
        renderer = self.renderer
        if renderer is None or not renderer.enabled or not renderer.progress.scanned_at:
            self.dial.hide()
            self.chip.hide()
            if self._row is not None:
                self._row.hide()
            return
        progress = renderer.progress
        self.dial.set_value(progress.percent, self.dial_state())
        self.dial.setToolTip(self.hover_text() + "\nClick for the decks.")
        self.dial.setAccessibleDescription(self.hover_text())
        text, tone = self.summary()
        if text != self._chip_said:
            self._chip_said = text
            self.renderer.trace(f"chip: {text or '(hidden)'} · dial {self.dial_state()}")
        if text:
            self.chip.set_text(text)
            self.chip.set_tone(tone)
            self.chip.adjustSize()
        self.chip.setVisible(bool(text))
        self.dial.show()
        if self._row is not None:
            self._row.show()
        self._place()
        self.dial.raise_()
        if text:
            self.chip.raise_()

    def _place(self) -> None:
        """Bottom left of the centre column (not over the slide list's buttons): follows the splitter and the window.
        Only without the centre column's status row, which lays the two out itself."""
        if self._row is not None:
            return
        stack = getattr(self.window, "stack", None)
        if stack is not None and stack.isVisible():
            corner = self._central.mapFromGlobal(stack.mapToGlobal(QPoint(0, stack.height())))
            x, y = corner.x() + MARGIN, corner.y() - self.dial.height() - MARGIN
        else:
            x, y = MARGIN, self._central.height() - self.dial.height() - MARGIN
        y = max(MARGIN, y)
        self.dial.move(x, y)
        self.chip.move(x + self.dial.width() + 8, y + max(0, (self.dial.height() - self.chip.height()) // 2))

    def show_status(self) -> None:
        """The window with every deck's state: opened from the dial and from the chip."""
        if self.renderer is None:
            return
        if self._status_dialog is None or not self._status_dialog.isVisible():
            self._status_dialog = StatusDialog(self, self.window)
        self._status_dialog.show()
        self._status_dialog.raise_()
        self._status_dialog.activateWindow()

    def eventFilter(self, watched, event) -> bool:      # noqa: N802
        if event.type() in (QEvent.Type.Resize, QEvent.Type.Move, QEvent.Type.Show) and self.dial.isVisible() and (
                watched is self._central or watched is getattr(self.window, "stack", None)):
            self._place()
        return False

    # -- the status window's controls -------------------------------------------------------------

    def toggle_pause(self) -> None:
        gate = self.renderer.gate
        gate.paused = not gate.paused
        self.refresh()

    def render_now(self) -> None:
        self.renderer.gate.paused = False
        self.renderer.gate.force()
        self.renderer.replan()

    def set_deck_enabled(self, name: str, on: bool) -> None:
        off = self.renderer.decks_off()
        (off.discard if on else off.add)(name)
        app_settings.set(self.project, background_renders.DECKS_OFF_KEY, sorted(off))
        if not on:
            self.renderer.scheduler.cancel_group(name)
        self.renderer.replan()

    def show_failures(self) -> None:
        lines = [f"{f['error'].strip().splitlines()[0] if f['error'].strip() else f['kind']}" for f in self.store.failures()[:20]]
        QMessageBox.information(self.window, "Slides that cannot be rendered", "\n".join(lines) or "None.")

    def retry_failed(self) -> None:
        self.store.forget_failure()
        self.renderer.replan()
