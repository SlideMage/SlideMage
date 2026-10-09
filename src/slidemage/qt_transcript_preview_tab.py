"""A read-only per-slide transcript preview tab (2026-08-25) --
the Preview's "Render transcript" menu entry opens one of
these so the result can be reviewed in-app rather than needing to go find
and open a file externally (unlike the deck-wide "Generate transcript"
button in the Images tab, which still just writes transcripts/*.md/.html
and reports their paths -- this is a lighter-weight, throwaway preview of
one slide, nothing is written to disk).

QTextBrowser (already part of QtWidgets -- no new dependency, keeping
this project's "PySide6 only" policy intact, see PYSIDE6_MIGRATION.md)
renders transcript.markdown_to_html_body()'s own deliberately small HTML
subset (headings, paragraphs, lists, tables, bold/italic, links) directly;
a full QtWebEngineView would be considerably heavier for the same result
and this project declares no such dependency anywhere else.
"""
from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QTextBrowser, QVBoxLayout, QWidget

from .ui.kit.theme import CLOSE_BUTTON


class TranscriptPreviewTab(QWidget):
    def __init__(self, app, title: str) -> None:
        super().__init__()
        self.app = app

        outer = QVBoxLayout(self)
        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel(title))
        toolbar.addStretch()
        close_button = QPushButton("Close")
        close_button.setObjectName(CLOSE_BUTTON)
        close_button.clicked.connect(self._on_close)
        toolbar.addWidget(close_button)
        outer.addLayout(toolbar)

        self.browser = QTextBrowser()
        self.browser.setOpenExternalLinks(True)
        outer.addWidget(self.browser)

    def set_html(self, html: str) -> None:
        self.browser.setHtml(html)

    def _on_close(self) -> None:
        self.app.close_transcript_preview_tab(self)
