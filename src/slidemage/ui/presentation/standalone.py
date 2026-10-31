# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Presenting a PDF without a project: the start screen's "Present a PDF…", and SlideMage Presenter
(docs/plans/presenter-app.md). Imports only the presentation modules, never the project, the compiler or the
workspace, so the small Presenter program can be built from it; tests/test_presenter_imports.py keeps it so."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QMessageBox

from ...presentation.pdf_source import PresentationDeck
from ...presentation.settings import PresentationSettings
from .controller import PresentationController


def present_pdf_file(path: Path) -> bool:
    """Present a PDF without a project: a presenter PDF with its notes, or a plain one. Returns when the
    presentation has ended; False when the PDF could not be opened."""
    from PySide6.QtCore import QEventLoop

    try:
        deck = PresentationDeck(path)
    except (ValueError, RuntimeError, OSError) as exc:
        QMessageBox.warning(None, "Present", f"{path.name} could not be opened: {exc}")
        return False
    controller = PresentationController(deck, PresentationSettings.load(), frames=deck.frame_map(),
                                        save_settings=lambda changed: changed.save())
    loop = QEventLoop()
    controller.finished.connect(loop.quit)
    controller.start()
    if not controller.ended:
        loop.exec()
    return True
