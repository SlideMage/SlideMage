# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The transcript preview (UI_REDESIGN_PLAN.md, step 9): one slide's transcript entry, rendered
the way a transcript shows it, in a sheet of its own.

It is a throwaway look at the entry for the text the Source view holds (nothing is written),
opened from the Render menu's "Render transcript" and from the Images page. The deck-wide
transcripts are built from the Compile menu. The entry is transcript.generate_single_slide()'s;
transcript.to_html() gives the small HTML subset that a QTextBrowser shows without any web engine.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox, QTextBrowser, QWidget

from ... import transcript
from ..kit.widgets import ModalSheet


class TranscriptPreviewSheet(ModalSheet):
    def __init__(self, parent: QWidget, title: str, html: str) -> None:
        super().__init__(title, parent, width=760)
        self.setMinimumHeight(560)
        self.browser = QTextBrowser()
        self.browser.setOpenExternalLinks(True)
        self.browser.setHtml(html)
        self.add_tab(title, self.browser)
        self.add_button("Close", kind="primary", role="accept")


def show_transcript_preview(app, source_text: str, bare_id: str, id_slug: str, version: str, language: str) -> None:
    """Render the entry of the slide `id_slug` for `version` ("during-course", "after-course"; any
    other falls back to During course) from `source_text`, in a sheet over the window `app`. The
    render is regex-only and fast enough for a wait cursor."""
    QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
    try:
        result = transcript.generate_single_slide(app.project, source_text, bare_id, version, language.lower())
    except Exception as exc:  # noqa: BLE001 -- surface any failure to the user
        QApplication.restoreOverrideCursor()
        QMessageBox.critical(app, "Transcript render failed", str(exc))
        return
    QApplication.restoreOverrideCursor()
    if result.undescribed:
        app.log(f"Transcript preview for {id_slug}: still has an undescribed image; flagged in place in the preview.")
    title = f"Transcript: {id_slug}"
    TranscriptPreviewSheet(app, title, transcript.to_html(result, f"Transcript preview: {id_slug}")).exec()
