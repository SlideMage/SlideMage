"""Screenshots of SlideMage's own windows for the SlideMage manual, made
offscreen against the example project: example/media/screenshot-slidemage-*.png.

    python tools/manual/make_screenshots.py

Builds the real widgets (no mock-ups), in the light theme at a fixed window
size, and saves QWidget.grab(). Modal dialogs are never exec()'d (that would
block forever offscreen): they are shown, grabbed and closed. Rerun after UI
changes. Before running, compile the manual (instructor version) and refresh
its previews -- this script does that from the compiled PDF:
example/decks/slidemage-manual.pdf -> .previews (slide_snapshot.capture_deck).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
EXAMPLE = REPO / "example"
os.environ["SLIDEMASTER_PROJECT"] = str(EXAMPLE)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if sys.platform == "win32":
    os.environ.setdefault("QT_QPA_FONTDIR", str(Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"))

from PySide6.QtCore import QPoint, QRect, QSize  # noqa: E402
from PySide6.QtGui import QFont  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox, QWidget  # noqa: E402

from slidemage import deck_scan, qt_gui, slide_snapshot, transcript, updater  # noqa: E402
from slidemage.qt_add_slide_dialog import AddSlideDialog  # noqa: E402
from slidemage.qt_settings_dialog import SettingsDialog  # noqa: E402
from slidemage.qt_slide_preview_popup import SlidePreviewPopup  # noqa: E402

MEDIA = EXAMPLE / "media"
MANUAL = "slidemage-manual"
SIZE = QSize(1100, 720)


def settle(app: QApplication, rounds: int = 6) -> None:
    for _ in range(rounds):
        app.processEvents()
        QTest.qWait(50)


def save(widget: QWidget, name: str, down_to: QWidget | None = None) -> None:
    """Grab `widget`; with `down_to`, only the part above that child's
    bottom edge (the main window without its toolbar row and log pane)."""
    path = MEDIA / f"screenshot-slidemage-{name}.png"
    if down_to is None:
        image = widget.grab()
    else:
        bottom = down_to.mapTo(widget, QPoint(0, down_to.height())).y() + 4
        image = widget.grab(QRect(0, 0, widget.width(), bottom))
    image.save(str(path))
    print(path.name, image.width(), "x", image.height())


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    # Offscreen Qt knows no system font: the platform's UI font by name
    # (run with QT_QPA_FONTDIR pointing at the system's font folder on Windows).
    app.setFont(QFont("Segoe UI" if sys.platform == "win32" else "DejaVu Sans", 9))
    theme = qt_gui.ThemeManager()
    theme.dark = False  # light theme, without saving the choice
    theme.apply()

    pdf = EXAMPLE / "decks" / f"{MANUAL}.pdf"
    if pdf.is_file():
        n = slide_snapshot.capture_deck(pdf, "slidemage")
        print(f"previews refreshed for {n} slides")

    window = qt_gui.SlideMageWindow(theme)
    window.resize(SIZE)
    window.show()
    settle(app)

    # 1. the main window, Active decks tab, and its deck table alone
    save(window, "main-window")
    table = window.active_table
    table_rows = table.grab(QRect(0, 0, table.width(), min(table.height(), 330)))
    table_rows.save(str(MEDIA / "screenshot-slidemage-deck-table.png"))
    print("screenshot-slidemage-deck-table.png", table_rows.width(), "x", table_rows.height())

    # the Tags dialog of a deck row (ask_deck_details() exec()s it itself)
    from slidemage import qt_deck_group_dialog

    def grab_dialog(dialog) -> int:
        dialog.show()
        settle(app)
        save(dialog, "tags-dialog")
        dialog.close()
        return 0
    original_dialog_exec = qt_deck_group_dialog.QDialog.exec
    qt_deck_group_dialog.QDialog.exec = grab_dialog
    try:
        qt_deck_group_dialog.ask_deck_details(window, f"Tags — {MANUAL}", "test")
    finally:
        qt_deck_group_dialog.QDialog.exec = original_dialog_exec

    deck = next(d for d in deck_scan.scan_decks() if d.name == MANUAL)

    # 2-4. the deck editor in its three views
    window.open_deck_editor(deck)
    settle(app)
    editor = window.tabs.currentWidget()
    save(window, "deck-editor-list", down_to=window.tabs)
    editor.thumbnail_view_radio.setChecked(True)
    settle(app, 12)
    save(window, "deck-editor-thumbnails", down_to=window.tabs)
    editor.grid_view_radio.setChecked(True)
    settle(app, 12)
    save(window, "deck-editor-grid", down_to=window.tabs)
    editor.list_view_radio.setChecked(True)
    settle(app)

    # 5. the Add slide dialog, opened from the deck editor
    dialog = AddSlideDialog(window, deck, insert_at=len(deck.text), indent="\t", return_to=editor)
    dialog.show()
    settle(app)
    save(dialog, "add-slide-dialog")
    dialog.close()

    # 6. the slide editor on the standardframe demo slide
    slide = EXAMPLE / "slides" / "1y8-EN-Standardframe-current.tex"
    window.open_slide_editor(slide)
    settle(app)
    save(window, "slide-editor", down_to=window.tabs)
    source_tab = window.tabs.currentWidget()

    # 7. the save dialog (version choice), grabbed instead of exec()'d
    def grab_instead_of_exec(box: QMessageBox) -> int:
        box.show()
        settle(app)
        save(box, "save-dialog")
        box.close()
        return 0
    original_exec = QMessageBox.exec
    QMessageBox.exec = grab_instead_of_exec
    try:
        source_tab._prompt_version_choice(None)
    finally:
        QMessageBox.exec = original_exec

    # 8. the preview popup for the same slide
    popup = SlidePreviewPopup(window, "1y8", slide, template="slidemage")
    popup.show()
    settle(app, 12)
    save(popup, "preview-popup")
    popup.close()

    # 9. the Images tab, on the figure slide
    window.open_images_for_slide("1rb-EN-Figureframe")
    settle(app, 12)
    save(window, "images-tab", down_to=window.tabs)

    # 10. a transcript of this manual, as SlideMage shows it
    result = transcript.generate(deck.path, "during-course")
    tab = window.open_transcript_preview("manual", "Transcript: slidemage-manual (during-course)")
    tab.set_html(transcript.to_html(result, "slidemage-manual"))
    settle(app)
    tab.browser.verticalScrollBar().setValue(0)
    settle(app)
    save(window, "transcript", down_to=window.tabs)

    # 11. Preferences -- with an empty GitHub token field: the user's own
    # token is neither shown nor touched (the field's save-on-edit signal is
    # disconnected before anything could fire it)
    original_saved_token = updater.saved_token
    updater.saved_token = lambda: ""
    try:
        settings = SettingsDialog(window)
        settings.github_token_edit.editingFinished.disconnect()
        settings.show()
        settle(app)
        save(settings, "preferences")
        settings.close()
    finally:
        updater.saved_token = original_saved_token

    window.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
