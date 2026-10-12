"""Slide versions: the focused slide's current text and frozen versions, which deck uses which,
and the actions on them.

* Open: look at a version in the Source view (a frozen one is read-only).
* Make current: slide_versioning.restore_version() through CentreColumn.restore_version().
* "<deck> uses": pin the open deck's calls of the slide to a version, or let them follow the
  current one again (slide_usage.set_pin(); an edit of the deck, so it can be undone).
* Freeze as: keep the current content as a frozen version and move the slide on to the next
  (slide_versioning.freeze_current(), through CentreColumn.freeze_version()). Saving in the Source
  view does the same together with the edit.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

from PySide6.QtWidgets import QHBoxLayout, QMessageBox

from .... import deck_editor, slide_language, slide_source, slide_usage, slide_versioning
from ...kit import kit_qss as q
from ...kit.widgets import Button, PopoverMenu, SegmentedControl
from .base import Row, SidePanel, box, text

CURRENT = "current"   # the pin menu's key for "follow the current version"
LEVELS = (("major", "Major"), ("minor", "Minor"), ("patch", "Patch"))


class SlideVersions(SidePanel):
    key = "versions"
    title = "Slide versions"

    def __init__(self, app, state, actions) -> None:
        super().__init__(app, state, actions)
        self._level = "minor"

    def meta(self) -> str:
        slide = self.id_slug()
        count = len(deck_editor.available_versions(self.app.project, slide)) if slide else 0
        return f"{count} frozen" if count else "none frozen"

    def build(self, id_slug: str) -> None:
        current = slide_language.current_path_for_bare_id(self.app.project, slide_language.bare_id(id_slug))
        if current is None:
            self.body.addWidget(text("The slide's current file was not found.", q.DETAILS_LABEL))
            return
        frozen = list(reversed(deck_editor.available_versions(self.app.project, id_slug)))
        users = self._users(id_slug)
        source = slide_source.read_slide_source(current)[0]
        number = slide_versioning.parse_version(source)

        frame, layout = box()
        self._add_version(
            layout, "v" + slide_versioning.format_dot(number) if number else "untracked", current,
            "current, the live text" + self._used_by(users.get(None)))
        for version in frozen:
            path = current.parent / slide_language.frozen_name(id_slug, version)
            when = datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d") if path.is_file() else "?"
            self._add_version(layout, slide_versioning.version_label(version), path, f"frozen {when}" + self._used_by(users.get(version)))
        self.body.addWidget(frame)
        frame, layout = box()
        self._add_pin(layout, id_slug, frozen)
        self._add_freeze(layout, id_slug, source)
        self.place(frame, "Edits are saved to the current version.")

    # -- the version list --------------------------------------------------------------

    def _users(self, id_slug: str) -> dict[Optional[str], list[str]]:
        """Version -> the decks that use it (None: the current version, which the decks that follow it use)."""
        users: dict[Optional[str], list[str]] = {}
        for usage in slide_usage.find_usage(self.app.project, id_slug):
            for version in {c.version if c.macro in slide_usage.PINNED else None for c in usage.calls}:
                users.setdefault(version, []).append(usage.deck.name)
        return users

    @staticmethod
    def _used_by(decks: Optional[list[str]]) -> str:
        return " · used by " + ", ".join(decks) if decks else " · not used"

    def _add_version(self, layout, label: str, path: Path, caption: str) -> None:
        row = Row(layout)
        head = QHBoxLayout()
        head.addWidget(text(label, q.PANEL_MONO))
        head.addStretch(1)
        open_button = Button("Open", "secondary", compact=True)
        open_button.setToolTip("Look at this version in the Source view" + ("" if slide_language.is_current_file(path)
                                                                          else " (read-only)."))
        open_button.clicked.connect(lambda: self._open(path))
        head.addWidget(open_button)
        if not slide_language.is_current_file(path):
            make_current = Button("Make current", "secondary", compact=True)
            make_current.setToolTip("Make this the current version: what is current now is archived first, and "
                                    "the restored content gets a new, higher version number.")
            make_current.clicked.connect(lambda: self.actions.restore_version(path))
            head.addWidget(make_current)
        row.body.addLayout(head)
        row.add_text(caption, q.PANEL_CAPTION)

    def _open(self, path: Path) -> None:
        if path.is_file():
            self.app.open_slide_editor(path)
        else:
            QMessageBox.warning(self, "Version not found", f"{path.name} no longer exists.")
            self.refresh()

    # -- the open deck's pin -----------------------------------------------------------

    def _pinnable(self) -> list[deck_editor.SlideCall]:
        return [c for _, c in self.deck_calls() if c.macro in slide_usage.PINNED or c.macro in slide_usage.PINNABLE]

    def _add_pin(self, layout, id_slug: str, frozen: list[str]) -> None:
        row = Row(layout)
        deck = self.state.deck
        calls = self._pinnable()
        if not self.deck_calls():
            row.add_text(f"{deck.name if deck else 'The open deck'} does not call this slide.", q.DETAILS_LABEL)
            return
        if not calls:
            row.add_text(f"{deck.name} always uses the current version of this slide "
                         "(its calls have no pinned form).", q.DETAILS_LABEL)
            return
        pins = {c.version for c in calls if c.macro in slide_usage.PINNED}
        following = any(c.macro in slide_usage.PINNABLE for c in calls)
        shown = CURRENT if not pins else slide_versioning.version_label(next(iter(pins))) if len(pins) == 1 and not following else "mixed"
        line = QHBoxLayout()
        line.addWidget(text(f"{deck.name} uses", q.DETAILS_VALUE), 1)
        button = Button(shown + " ▾", "secondary", compact=True)
        button.clicked.connect(lambda: self._open_pin_menu(button, id_slug, frozen, shown))
        line.addWidget(button)
        row.body.addLayout(line)

    def _open_pin_menu(self, anchor, id_slug: str, frozen: list[str], shown: str) -> None:
        menu = PopoverMenu(self, min_width=180)
        for key, label in [(CURRENT, CURRENT)] + [(v, slide_versioning.version_label(v)) for v in frozen]:
            menu.add_item(key, label, icon="check" if label == shown else "")
        menu.triggered.connect(lambda key: self._set_pin(id_slug, None if key == CURRENT else key))
        menu.closed.connect(menu.deleteLater)
        menu.popup_below(anchor)

    def _set_pin(self, id_slug: str, version: Optional[str]) -> None:
        calls = self._pinnable()
        self.actions.edit_deck(
            "Change failed",
            f"{id_slug} in {self.state.deck.name} " + (f"now uses {slide_versioning.version_label(version)}" if version else "follows the current version"),
            lambda path, deck_text: slide_usage.set_pin(path, deck_text, calls, version))

    # -- freezing ------------------------------------------------------------------------

    def _next(self, source: str, level: str) -> str:
        return slide_versioning.format_dot(slide_versioning.plan_save(slide_versioning.parse_version(source), level)[0])

    def _add_freeze(self, layout, id_slug: str, source: str) -> None:
        row = Row(layout)
        line = QHBoxLayout()
        freeze = Button(f"Freeze as v{self._next(source, self._level)}", "primary", compact=True)
        freeze.setToolTip("Keep the current content as a frozen version and move the slide on to the next version.")
        freeze.clicked.connect(lambda: self.actions.freeze_version(id_slug, self._level))
        levels = SegmentedControl(LEVELS, current=self._level)
        levels.changed.connect(lambda level: self._on_level(level, freeze, source))
        line.addWidget(freeze)
        line.addWidget(levels)
        line.addStretch(1)
        row.body.addLayout(line)

    def _on_level(self, level: str, freeze: Button, source: str) -> None:
        self._level = level
        freeze.setText(f"Freeze as v{self._next(source, level)}")
