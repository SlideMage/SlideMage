# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Deck -> Check spelling of this deck (docs/plans/ai-spellchecker.md, step 4): every unknown word of the deck in
one list, so that many can go to the word list at once.

The check runs on a worker (spelling/deck_check.py, with the window's SpellingSession: the Source view's
dictionaries, word lists and ignored words) over every slide file the deck shows, in every language of the project.
The list has one row per word and language, most frequent first, with a tick box; under it, where it occurs
(slide file and line). Double-clicking an occurrence opens the slide at that line in the Source view, where the
underline and its menu offer the corrections; the sheet stays open beside it (it is not modal). "Add to word list"
and "Ignore" act on the ticked words and take them off the list; every open slide is checked again.
"""
from __future__ import annotations

import logging
import threading
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QTreeWidget, QTreeWidgetItem, QVBoxLayout

from ... import languages
from ...spelling import deck_check
from ..background import run_in_background_with_progress
from ..kit.tokens import SPACE
from ..kit.widgets import BusyIndicator, Button, ModalSheet, Surface, caption

log = logging.getLogger("slidemage.spelling")

WORD, LANGUAGE, COUNT, WHERE = range(4)
FINDING = Qt.ItemDataRole.UserRole
WHERE_LIMIT = 3      # files named in a word's row; the rest are under it


class DeckSpellingSheet(ModalSheet):
    def __init__(self, window, deck) -> None:
        super().__init__(f"Spelling in {deck.name}", window, width=760)
        self.setModal(False)                # open slides from it and come back
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.window_ = window
        self.deck = deck
        self.result: Optional[deck_check.DeckSpelling] = None
        self._cancel: Optional[threading.Event] = None
        self._handle = None

        body = Surface()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACE.lg)
        layout.addWidget(caption(
            "The words of the deck's slide text that no dictionary or word list knows, in every language of the "
            "project. Tick words to add them to the project's word list or to ignore them for this session; "
            "double-click a line to open the slide there."))
        self.status = caption("")
        layout.addWidget(self.status)
        self.busy = BusyIndicator()
        layout.addWidget(self.busy)
        self.tree = QTreeWidget()
        self.tree.setColumnCount(4)
        self.tree.setHeaderLabels(["Word", "Language", "Times", "Where"])
        self.tree.setMinimumHeight(320)
        self.tree.setUniformRowHeights(True)
        self.tree.itemDoubleClicked.connect(self._open)
        self.tree.itemChanged.connect(lambda *_: self._update_buttons())
        layout.addWidget(self.tree, 1)
        bulk = QHBoxLayout()
        bulk.setContentsMargins(0, 0, 0, 0)
        self.tick_all = Button("Tick all", "ghost", compact=True)
        self.tick_all.clicked.connect(lambda: self._tick_all(True))
        self.tick_none = Button("Tick none", "ghost", compact=True)
        self.tick_none.clicked.connect(lambda: self._tick_all(False))
        bulk.addWidget(self.tick_all)
        bulk.addWidget(self.tick_none)
        bulk.addStretch(1)
        layout.addLayout(bulk)
        self.add_tab("Words", body)

        self.again_button = self.add_button("Check again")
        self.again_button.clicked.connect(self.run_check)
        self.ignore_button = self.add_button("Ignore")
        self.ignore_button.setToolTip("Not underlined again in this session, in any slide.")
        self.ignore_button.clicked.connect(lambda: self._act("ignore"))
        self.add_word_button = self.add_button("Add to word list", kind="primary")
        self.add_word_button.setToolTip("Into the project's spelling-words-<language>.txt, shared with co-authors.")
        self.add_word_button.clicked.connect(lambda: self._act("add"))
        close = self.add_button("Close", role="reject")
        close.setDefault(False)
        self.finished.connect(self._stop)
        self._update_buttons()

    # -- the check -----------------------------------------------------------------------------------------------
    def run_check(self) -> None:
        session = self.window_.spelling_session()
        if self._handle is not None or session is None:
            return
        ctx, deck = self.window_.project, self.deck
        cancel = self._cancel = threading.Event()
        self.tree.clear()
        self.result = None
        self.status.setText("Checking…")
        self.busy.start("Checking the deck's slides…")
        self._update_buttons()

        def work(report):
            paths = deck_check.deck_files(ctx, deck)
            return deck_check.check_files(session, ctx, paths, lambda done, total, message: report(
                (done, total, message)), cancel)

        self._handle = run_in_background_with_progress(work, self._on_progress, self._on_done, cancel=cancel,
                                                       parent=self, logger=log)

    def _on_progress(self, value) -> None:
        done, total, message = value
        self.status.setText(f"{message} ({done} of {total} files)" if total else message)

    def _on_done(self, result: Optional[deck_check.DeckSpelling], error) -> None:
        self._handle = None
        self.busy.finish()
        if error is not None or result is None:
            log.error("spelling: the deck check failed", exc_info=error)
            self.status.setText("The deck could not be checked; see the log.")
            self._update_buttons()
            return
        if result.cancelled:
            return
        self.result = result
        self._fill(result)
        self._update_buttons()

    def _stop(self, *_args) -> None:
        if self._cancel is not None:
            self._cancel.set()
        if self._handle is not None:
            self._handle.stop()
            self._handle = None

    # -- the list ------------------------------------------------------------------------------------------------
    def _fill(self, result: deck_check.DeckSpelling) -> None:
        self.tree.blockSignals(True)
        self.tree.clear()
        root = self.window_.project.slides_dir
        for finding in result.findings:
            files = finding.files
            where = ", ".join(p.name for p in files[:WHERE_LIMIT]) + (
                f" and {len(files) - WHERE_LIMIT} more" if len(files) > WHERE_LIMIT else "")
            item = QTreeWidgetItem([finding.word, languages.name(finding.language), str(finding.count), where])
            item.setData(WORD, FINDING, finding)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(WORD, Qt.CheckState.Unchecked)
            item.setTextAlignment(COUNT, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            for occurrence in finding.occurrences:
                place = occurrence.path.relative_to(root) if occurrence.path.is_relative_to(root) else occurrence.path
                note = " (frozen version)" if occurrence.frozen else ""
                child = QTreeWidgetItem(["", "", "", f"{place}, line {occurrence.line}{note}"])
                child.setData(WORD, FINDING, occurrence)
                item.addChild(child)
            self.tree.addTopLevelItem(item)
        for column in (WORD, LANGUAGE, COUNT):
            self.tree.resizeColumnToContents(column)
        self.tree.blockSignals(False)
        self.status.setText(_summary(result))

    def _rows(self) -> list[QTreeWidgetItem]:
        return [self.tree.topLevelItem(i) for i in range(self.tree.topLevelItemCount())]

    def ticked(self) -> list[deck_check.Finding]:
        return [row.data(WORD, FINDING) for row in self._rows() if row.checkState(WORD) == Qt.CheckState.Checked]

    def _tick_all(self, on: bool) -> None:
        state = Qt.CheckState.Checked if on else Qt.CheckState.Unchecked
        self.tree.blockSignals(True)
        for row in self._rows():
            row.setCheckState(WORD, state)
        self.tree.blockSignals(False)
        self._update_buttons()

    def _update_buttons(self) -> None:
        running = self._handle is not None
        has_rows = bool(self._rows())
        ticked = bool(self.ticked()) and not running
        self.add_word_button.setEnabled(ticked)
        self.ignore_button.setEnabled(ticked)
        self.again_button.setEnabled(not running)
        self.tick_all.setEnabled(has_rows and not running)
        self.tick_none.setEnabled(has_rows and not running)

    # -- acting --------------------------------------------------------------------------------------------------
    def _act(self, what: str) -> None:
        session = self.window_.spelling_session()
        findings = self.ticked()
        if session is None or not findings:
            return
        failed = []
        for finding in findings:
            try:
                if what == "add":
                    session.add_to_word_list(finding.language, finding.word)
                else:
                    session.ignore(finding.language, finding.word)
            except (OSError, ValueError) as e:
                log.error("spelling: %s %r failed: %s", what, finding.word, e)
                failed.append(finding.word)
        self.tree.blockSignals(True)
        for row in self._rows():
            if row.checkState(WORD) == Qt.CheckState.Checked and row.data(WORD, FINDING).word not in failed:
                self.tree.takeTopLevelItem(self.tree.indexOfTopLevelItem(row))
        self.tree.blockSignals(False)
        verb = "Added to the word list" if what == "add" else "Ignored"
        self.status.setText(f"{verb}: {len(findings) - len(failed)} words."
                            + (f" Could not add: {', '.join(failed)}." if failed else ""))
        self._update_buttons()
        self.window_.centre.source.recheck_spelling()

    def _open(self, item: QTreeWidgetItem, _column: int) -> None:
        data = item.data(WORD, FINDING)
        occurrence = data if isinstance(data, deck_check.Occurrence) else (
            data.occurrences[0] if isinstance(data, deck_check.Finding) and data.occurrences else None)
        if occurrence is not None:
            self.window_.open_slide_editor(occurrence.path, line=occurrence.line, tab=True)


def _summary(result: deck_check.DeckSpelling) -> str:
    words = len(result.findings)
    times = sum(f.count for f in result.findings)
    parts = [f"{words} unknown words ({times} times) in {result.files} slide files." if words
             else f"No unknown words in {result.files} slide files."]
    if result.missing:
        parts.append(f"Missing: {', '.join(result.missing[:5])}.")
    parts += list(dict.fromkeys(result.unavailable.values()))
    if result.unsupported:
        names = ", ".join(sorted(languages.name(code) for code in result.unsupported))
        parts.append(f"No dictionary for {names}: that text is not checked.")
    return " ".join(parts)


def open_for(window, deck) -> Optional[DeckSpellingSheet]:
    """Deck -> Check spelling of this deck."""
    if deck is None:
        return None
    sheet = DeckSpellingSheet(window, deck)
    sheet.show()
    sheet.run_check()
    return sheet
