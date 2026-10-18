"""The window's side of background rendering (background_renders.py): it feeds the idle gate with the user's input
and with what keeps the machine busy, tells the store which decks are used and where, shows what is left in a
small chip, and stops everything when the window closes.

The chip stands over the bottom left of the workspace and is there only while there is something to say: previews
being prepared (with how many are left), prepared previews waiting for the user to stop working (and why), or
slides that cannot be rendered. Clicking it shows the decks in the order they are worked through and the controls:
pause, render now, skip the open deck, retry the failed slides.
"""
from __future__ import annotations

import os
from typing import Optional

from PySide6.QtCore import QEvent, QObject, QPoint, QTimer, Signal
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QWidget

from ... import app_settings, background_renders, render_key, render_store
from ...background_renders import BackgroundRenderer
from ..kit.widgets import Chip

NO_BACKGROUND_ENV = "SLIDEMAGE_NO_BACKGROUND_PREVIEWS"     # set by the tests: nothing renders by itself
REFRESH_MS = 1000
MARGIN = 14
INPUT_EVENTS = {QEvent.Type.MouseMove, QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease, QEvent.Type.KeyPress,
                QEvent.Type.Wheel, QEvent.Type.TouchBegin}


class _InputWatcher(QObject):
    """Application-wide: every mouse, key, wheel and touch event is "the user is here"."""

    def __init__(self, on_input, parent: QObject) -> None:
        super().__init__(parent)
        self._on_input = on_input

    def eventFilter(self, watched, event) -> bool:      # noqa: N802 -- Qt's name
        if event.type() in INPUT_EVENTS:
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
        self.chip.clicked.connect(self.show_menu)
        self._central = central
        central.installEventFilter(self)
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
            on_change=self.changed.emit)
        self.renderer.gate._busy = self._busy_reasons
        self._watcher = _InputWatcher(self.renderer.user_active, self)
        QApplication.instance().installEventFilter(self._watcher)
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

    def stop(self) -> None:
        self._timer.stop()
        if self.renderer is not None:
            self.renderer.stop()
        if self.store is not None:
            self.store.close()
            self.store = None

    def stored_page(self, target, view: str, language: str):
        """The last page (every reveal step has been shown) of the stored render of `target` as PNG bytes if a
        current one is there, else None. A slidestep call keeps its own step restriction, which a stored
        unrestricted render does not show."""
        renderer = self.renderer
        if renderer is None or self.store is None or not renderer.enabled:
            return None
        if target.macro == "slidestep" and target.steps:
            return None
        deck = self.window.state.deck
        try:
            unit = render_key.unit_for(target, view, language, deck.name if deck is not None else "")
            found = renderer.resolver.lookup(unit)
            if not found.usable:
                return None
            return self.store.page(found.record, found.record["pages"])
        except Exception:  # noqa: BLE001 -- the store is a help; a broken one must not break the Preview
            return None

    # -- the chip --------------------------------------------------------------------------------

    def summary(self) -> tuple[str, str]:
        """(text, tone) of the chip; the text is empty when there is nothing to say."""
        renderer = self.renderer
        if renderer is None or not renderer.enabled:
            return "", "muted"
        progress = renderer.progress
        left = progress.left
        if left > 0:
            if progress.working is not None:
                return f"Preparing previews · {left} left", "info"
            reason = progress.paused_because
            return (f"Previews paused ({reason}) · {left} left" if reason else f"Previews · {left} left"), "muted"
        if progress.failures:
            return f"{progress.failures} slide{'s' if progress.failures != 1 else ''} cannot be rendered", "warning"
        return "", "muted"

    def refresh(self) -> None:
        text, tone = self.summary()
        if not text:
            self.chip.hide()
            return
        self.chip.set_text(text)
        self.chip.set_tone(tone)
        self.chip.adjustSize()
        self._place()
        self.chip.show()
        self.chip.raise_()

    def _place(self) -> None:
        self.chip.move(MARGIN, max(MARGIN, self._central.height() - self.chip.height() - MARGIN))

    def eventFilter(self, watched, event) -> bool:      # noqa: N802
        if watched is self._central and event.type() == QEvent.Type.Resize and self.chip.isVisible():
            self._place()
        return False

    # -- the menu --------------------------------------------------------------------------------

    def menu(self) -> QMenu:
        menu = QMenu(self.chip)
        renderer = self.renderer
        if renderer is None:
            return menu
        progress = renderer.progress
        for deck in progress.decks[:12]:
            action = menu.addAction(f"{deck.deck}: {deck.fresh} of {deck.total} ready" + (f", {deck.failed} failed" if deck.failed else ""))
            action.setEnabled(False)
        if len(progress.decks) > 12:
            menu.addAction(f"… and {len(progress.decks) - 12} more decks").setEnabled(False)
        used = (self.store.total_bytes() if self.store else 0) / 1024 ** 3
        menu.addAction(f"Stored: {used:.2f} GB of {renderer.limit_bytes() / 1024 ** 3:.1f} GB").setEnabled(False)
        menu.addSeparator()
        paused = renderer.gate.paused
        toggle = menu.addAction("Resume" if paused else "Pause")
        toggle.triggered.connect(self.toggle_pause)
        now = menu.addAction("Render now")
        now.triggered.connect(self.render_now)
        deck = self.window.state.deck
        if deck is not None:
            skip = menu.addAction(f"Prepare {deck.name} in the background")
            skip.setCheckable(True)
            skip.setChecked(deck.name not in renderer.decks_off())
            skip.toggled.connect(lambda on: self.set_deck_enabled(deck.name, on))
        if progress.failures:
            show = menu.addAction(f"Show the {progress.failures} failed slides…")
            show.triggered.connect(self.show_failures)
            retry = menu.addAction("Try the failed slides again")
            retry.triggered.connect(self.retry_failed)
        return menu

    def show_menu(self) -> None:
        menu = self.menu()
        menu.exec(self.chip.mapToGlobal(QPoint(0, -menu.sizeHint().height())))

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
