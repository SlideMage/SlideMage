"""Screenshots of SlideMage's own windows for the SlideMage manual, made
offscreen against the example project: example/media/screenshot-slidemage-*.png.

    python tools/manual/make_screenshots.py

Builds the real widgets (no mock-ups), in the light theme at a fixed window
size, and saves QWidget.grab(). Modal dialogs are never exec()'d (that would
block forever offscreen): they are shown, grabbed and closed. The windows keep
their logical size (SIZE) but are rendered at SCALE times the pixels (a device
pixel ratio of 2: crisp text instead of a stretched 1340 px picture), so every
PNG is SCALE times as large; the slides place them by width, so nothing else
changes. Rerun after UI changes. Before running, compile the manual (instructor version) and refresh
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
SCALE = 2  # device pixel ratio of every screenshot; set before QApplication exists
os.environ.setdefault("QT_SCALE_FACTOR", str(SCALE))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if sys.platform == "win32":
    os.environ.setdefault("QT_QPA_FONTDIR", str(Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"))

from PySide6.QtCore import QPoint, QRect, QSize  # noqa: E402
from PySide6.QtGui import QFont  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox, QWidget  # noqa: E402

from slidemage import deck_scan, qt_gui, slide_snapshot, transcript  # noqa: E402

MEDIA = EXAMPLE / "media"
MANUAL = "slidemage-manual"
# Wide enough for a deck row with all its buttons (at 1100 px the row was cut
# off and the table scrolled sideways; the deck editor widens the window to
# about 1320 px anyway).
SIZE = QSize(1340, 720)

# Placeholder decks, one per deck group, so the deck table shows the grouping
# (slide 1d8) and full rows with all their buttons (slide 1ub) -- the example
# project itself has only the manual. Made from the manual's preamble with
# another \decktags and an empty body; deleted again at the end, also when the
# script fails.
PLACEHOLDER_DECKS = {
    "#workdeck": "work",
    "course-example-2027s": "course",
    "talk-example-seminar": "research",
}


def write_placeholder_decks() -> list[Path]:
    manual = (EXAMPLE / "decks" / f"{MANUAL}.tex").read_text(encoding="utf-8")
    preamble = manual.split("\\begin{document}")[0]
    paths = []
    for name, tag in PLACEHOLDER_DECKS.items():
        path = EXAMPLE / "decks" / f"{name}.tex"
        if path.exists():
            raise SystemExit(f"{path} exists -- not overwriting a real deck")
        text = preamble.replace("\\decktags{manual}", f"\\decktags{{{tag}}}")
        path.write_text("% TEMPORARY placeholder deck (tools/manual/make_screenshots.py)\n"
                        + text + "\\begin{document}\n\\end{document}\n", encoding="utf-8")
        paths.append(path)
    return paths


def callout_positions(window: QWidget, widgets: dict[str, "QWidget | QPoint"]) -> None:
    """Print each widget's centre as a fraction of the window -- x from the
    left, y from the bottom -- the coordinates slide 1ub's \\callout{x,y}{n}
    takes, since its picture is the whole window. Copy them into 1ub."""
    w, h = window.width(), window.height()
    print("callouts for slide 1ub (x,y as fractions, y from the bottom):")
    for label, widget in widgets.items():
        if isinstance(widget, QPoint):  # already in the window's coordinates
            centre = widget
        else:
            centre = widget.mapTo(window, QPoint(widget.width() // 2, widget.height() // 2))
        print(f"  {label}: {centre.x() / w:.3f},{1 - centre.y() / h:.3f}")


def checkbox_block_middle(window: QWidget, table, row) -> QPoint:
    """The middle of the version checkboxes, in window coordinates: halfway
    between the Instructor and the Presenter checkbox, on the course group's
    heading line just above the rows (the badge sits in the empty strip there
    instead of covering a checkbox)."""
    first, last = row.vars["instructor"], row.presenter_var
    left = first.mapTo(window, QPoint(0, 0)).x()
    right = last.mapTo(window, QPoint(last.width(), 0)).x()
    heading = table._group_headers["course"][0]  # the group heading is a button
    y = heading.mapTo(window, QPoint(0, heading.height() // 2)).y()
    return QPoint((left + right) // 2, y)


def row_button(table, row, text: str) -> QWidget:
    """The button labelled `text` in deck-table row `row` (rows keep no
    reference to their buttons; the one on the same line as the row's
    Instructor checkbox)."""
    from PySide6.QtWidgets import QPushButton
    row_y = row.vars["instructor"].mapTo(table, QPoint(0, row.vars["instructor"].height() // 2)).y()
    for button in table.findChildren(QPushButton):
        top = button.mapTo(table, QPoint(0, 0)).y()
        if button.text() == text and top <= row_y <= top + button.height():
            return button
    raise LookupError(text)


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

    placeholders = write_placeholder_decks()
    try:
        return screenshots(app, theme)
    finally:
        for path in placeholders:
            path.unlink(missing_ok=True)


def screenshots(app: QApplication, theme) -> int:
    # Every deck group unfolded, whatever the example project remembers
    # (collapsed_deck_groups_* in its app_settings.json, left untouched).
    from slidemage import app_settings
    original_get = app_settings.get
    app_settings.get = lambda key, default=None: (
        [] if key.startswith("collapsed_deck_groups") else original_get(key, default))
    try:
        window = qt_gui.SlideMageWindow(theme)
    finally:
        app_settings.get = original_get
    window.resize(SIZE)
    window.show()
    settle(app)

    # 1. the main window, Active decks tab, and its deck table alone
    save(window, "main-window")
    table = window.active_table
    course_row = next(row for row in table.rows if row.deck.name == "course-example-2027s")
    callout_positions(window, {
        "1 menus": window.menuBar(),
        "2 tabs": window.tabs.tabBar(),
        "3 version checkboxes": checkbox_block_middle(window, table, course_row),
        "4 row buttons (Duplicate)": row_button(table, course_row, "Duplicate"),
        "5 Create PDF": table.compile_button,
        "6 footer timestamp": window.footer_timestamp_checkbox,
        "7 log": window.log_text,
        "8 Find slide": window.slide_search_entry,
    })
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
        qt_deck_group_dialog.ask_deck_details(window, "Tags — course-example-2027s", "course")
    finally:
        qt_deck_group_dialog.QDialog.exec = original_dialog_exec

    deck = next(d for d in deck_scan.scan_decks() if d.name == MANUAL)

    # 2-3. the deck editor, List and Grid view
    window.open_deck_editor(deck)
    settle(app)
    editor = window.tabs.currentWidget()
    # The List view's rows are wider than the main window: widen the window
    # until the editor's scroll area needs no horizontal scrollbar, so the
    # rows' right-hand buttons (Remove, Preview, Images) are in the shot.
    from PySide6.QtWidgets import QScrollArea
    for area in editor.findChildren(QScrollArea):
        bar = area.horizontalScrollBar()
        if area.isVisible() and bar.maximum() > 0:
            window.resize(window.width() + bar.maximum() + 8, window.height())
            settle(app)
    print("window for the deck editor:", window.width(), "x", window.height())
    save(window, "deck-editor-list", down_to=window.tabs)
    editor.grid_view_radio.setChecked(True)
    settle(app, 12)
    save(window, "deck-editor-grid", down_to=window.tabs)
    editor.list_view_radio.setChecked(True)
    settle(app)

    # 4. the slide editor on the standardframe demo slide
    slide = EXAMPLE / "slides" / "1y8-EN-Standardframe-current.tex"
    window.open_slide_editor(slide)
    settle(app)
    save(window, "slide-editor", down_to=window.tabs)
    source_tab = window.tabs.currentWidget()
    # ... and just its two button rows, from Save to Delete slide / Render
    # transcript (slide 1b2 explains those buttons and wants them readable)
    from PySide6.QtWidgets import QPushButton
    buttons = {b.text(): b for b in source_tab.findChildren(QPushButton)}
    top_left = buttons["Save"].mapTo(window, QPoint(0, 0))
    right = buttons["Delete slide"].mapTo(window, QPoint(buttons["Delete slide"].width(), 0)).x()
    last = buttons["Render transcript"]
    bottom = last.mapTo(window, QPoint(0, last.height())).y()
    strip = window.grab(QRect(top_left.x() - 6, top_left.y() - 6,
                              right - top_left.x() + 12, bottom - top_left.y() + 12))
    strip.save(str(MEDIA / "screenshot-slidemage-slide-editor-buttons.png"))
    print("screenshot-slidemage-slide-editor-buttons.png", strip.width(), "x", strip.height())

    # 5. the save dialog (version choice), grabbed instead of exec()'d
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

    # 6. the Images tab, on the figure slide
    window.open_images_for_slide("1rb-EN-Figureframe")
    settle(app, 12)
    save(window, "images-tab", down_to=window.tabs)

    # 7. a transcript of this manual, as SlideMage shows it
    result = transcript.generate(deck.path, "during-course")
    tab = window.open_transcript_preview("manual", "Transcript: slidemage-manual (during-course)")
    tab.set_html(transcript.to_html(result, "slidemage-manual"))
    settle(app)
    tab.browser.verticalScrollBar().setValue(0)
    settle(app)
    save(window, "transcript", down_to=window.tabs)

    window.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
