# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Actions on a deck: Open pdf, Settings, Source, Duplicate, Tags, Archive and Create Transcript.
The top bar's menus (menus.py) start them for the current deck.

Plain functions of the window: each takes the WorkspaceWindow (window.py) first, which
provides `project`, `state`, `compiling`, `log` and `reload_decks()`.
"""
from __future__ import annotations

from datetime import datetime
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog, QInputDialog, QMessageBox

from ... import (
    admin_slides, deck_duplicate, deck_editor, deck_new, deck_settings, deck_snapshot, open_path, slide_snapshot,
    transcript)
from ... import archive as archive_mod
from ...compiler import deck_pdfs, pdf_to_open
from ...deck_scan import GROUP_TAGS, TAG_MANUAL, Deck
from ...deck_settings import DeckSettings
from ...fileio import read_text_exact
from ..dialogs.admin_slides import AdminSlidesTab
from ..dialogs.deck_group import DeckGroupSheet
from ..dialogs.deck_settings import ADMIN, COMMAND, GENERAL, INSERT, DeckSettingsSheet
from ..dialogs.snapshot import SnapshotSheet
from . import compile_actions


def on_admin_slides(window, deck: Deck) -> None:
    """⋮ -> "Admin slides…": Deck settings on its Admin slides tab."""
    on_deck_settings(window, deck, tab=ADMIN)


def archive_deck(window, deck: Deck) -> None:
    """Archiving is when a deck stops being maintained, so it offers a
    snapshot first (v5.33.0): "Snapshot, then archive" (default) /
    "Archive only" / Cancel. The snapshot uses the settings last chosen
    in ⋮ → Create deck snapshot…, runs on the compile slot, and
    must come before archive.archive_deck() rewrites the deck's path
    lines -- the deck is archived only when it has finished (or, if it
    failed, after a second yes)."""
    options = deck_snapshot.saved_options(window.project)
    box = QMessageBox(window)
    box.setIcon(QMessageBox.Icon.Question)
    box.setWindowTitle("Archive deck")
    box.setText(f"Move {deck.name}.tex to decks/archive/?")
    box.setInformativeText(
        "Create a snapshot first? It keeps a window-contained copy of the deck "
        "as it compiles today in snapshots/ "
        f"({deck_snapshot.describe_options(options)} -- change in "
        "Decks → Create deck snapshot…).")
    snapshot_button = box.addButton("Snapshot, then archive",
                                    QMessageBox.ButtonRole.AcceptRole)
    archive_only_button = box.addButton("Archive only", QMessageBox.ButtonRole.AcceptRole)
    box.addButton(QMessageBox.StandardButton.Cancel)
    box.setDefaultButton(snapshot_button)
    box.exec()
    clicked = box.clickedButton()
    if clicked is archive_only_button:
        do_archive_deck(window, deck)
    elif clicked is snapshot_button:
        compile_actions.start_snapshots(window, 
            [deck], options,
            after=lambda results: archive_after_snapshot(window, deck, results))


def archive_after_snapshot(window, deck: Deck, results: list) -> None:
    result = results[0] if results else None
    if result is not None and result.ok:
        do_archive_deck(window, deck)
        return
    reason = result.error if result is not None else "no result"
    reply = QMessageBox.question(
        window, "Snapshot failed",
        f"The snapshot of {deck.name} failed ({reason}).\n\n"
        "Archive the deck anyway?",
        defaultButton=QMessageBox.StandardButton.No)
    if reply == QMessageBox.StandardButton.Yes:
        do_archive_deck(window, deck)


def do_archive_deck(window, deck: Deck) -> None:
    try:
        archive_mod.archive_deck(window.project, deck)
    except Exception as exc:  # noqa: BLE001 -- surface any failure to the user
        QMessageBox.critical(window, "Archive failed", str(exc))
        return
    window.log(f"Archived {deck.name}.tex -> decks/archive/{deck.name}.tex")
    if getattr(window, "background", None) is not None:
        window.background.deck_archived(deck)      # its prepared previews go, and it is no longer prepared
    window.reload_decks()


def on_create_deck_snapshot(window) -> None:
    """⋮ -> "Create deck snapshot…": the dialog, then one snapshot
    per checked deck, one after the other, on the compile slot."""
    decks = window.decks
    preselected = {window.state.deck.name} if window.state.deck is not None else set()
    sheet = SnapshotSheet(window, window.project, decks, preselected, busy=window.compiling)
    if sheet.exec() != QDialog.DialogCode.Accepted:
        return
    compile_actions.start_snapshots(window, sheet.selected_decks(), sheet.options())


def tags_with_group(deck_tags: list[str], group: str) -> list[str]:
    """`group` as the deck's group tag, keeping any other tags it has."""
    return [group] + [t for t in deck_tags if t not in GROUP_TAGS]


def on_open_latest_pdf(window, deck: Deck) -> None:
    """⌘K "Open latest PDF" (2026-09-21): opens the
    deck's preferred PDF (Settings -> "Open pdf opens", else the
    instructor PDF), unless a newer PDF of the deck comes from another
    compile run -- then it asks which one, newest first (2026-10-08,
    direct instructions; compiler.pdf_to_open())."""
    pdfs = deck_pdfs(window.project, deck)
    if not pdfs:
        QMessageBox.information(
            window, "No PDF yet", f"No PDF has been created for {deck.name} yet.")
        return
    chosen = pdf_to_open(pdfs)
    if chosen is None:
        labels = [f"{pdf.label} -- {datetime.fromtimestamp(pdf.mtime):%Y-%m-%d %H:%M} ({pdf.path.name})"
                  for pdf in pdfs]       # the file name keeps two PDFs of one label apart
        default = next((i for i, pdf in enumerate(pdfs) if pdf.preferred), 0)
        label, ok = QInputDialog.getItem(
            window, "Open pdf",
            f"{deck.name} has PDFs from a later compile run than the one it usually opens.\n"
            "Which one should open?", labels, default, False)
        if not ok:
            return
        chosen = pdfs[labels.index(label)]
    pdf_path = chosen.path
    try:
        open_path.open_in_default_app(pdf_path)
    except OSError as exc:
        window.log(f"*** couldn't open {pdf_path.name}: {exc} ***")


def on_deck_settings(window, deck: Deck, tab: int = GENERAL) -> None:
    """⋮ -> "Deck settings…": the deck-wide settings that live in the deck's own file
    (deck_settings.py), all written in one go, and the admin slides of its course page."""
    if window.centre.unsaved(deck.path):
        QMessageBox.information(
            window, "Deck settings",
            f"{deck.name}.tex has edits in the Source view that could not be saved -- resolve "
            "that first, so this change and that editor can't overwrite each other.",
        )
        return
    sheet = DeckSettingsSheet(window, deck, deck_settings.template_choices(window.project.root), tab=tab)
    if not sheet.exec():
        return
    if sheet.action == INSERT:
        insert_admin_slides(window, deck, sheet.admin)
    elif sheet.action.startswith(COMMAND):
        window.commands.run(sheet.action.removeprefix(COMMAND), window)
    else:
        save_deck_settings(window, deck, sheet.original, sheet.result_settings())


def save_deck_settings(window, deck: Deck, old: DeckSettings, new: DeckSettings) -> None:
    if new == old:
        return
    try:
        deck_settings.save_settings(deck.path, deck.text, old, new)
    except (deck_editor.StaleFileError, ValueError, OSError) as exc:
        QMessageBox.critical(window, "Deck settings failed", str(exc))
        return
    changed = [name for name in ("template", "language", "footer_text", "course_url",
                                 "output_folders", "appendix_toc", "open_pdf", "footer_hide", "dark_mode")
               if getattr(new, name) != getattr(old, name)]
    window.log(f"Updated settings of {deck.name}: " + ", ".join(
        name.replace("_", " ") for name in changed))
    window.refresh_open_deck_editors()
    window.reload_decks()
    if (old.footer_hide != new.footer_hide or old.footer_text != new.footer_text
            or old.dark_mode != new.dark_mode) and (
            window.state.deck is not None and window.state.deck.path == deck.path
            and window.state.mode in ("preview", "split")):
        # reload_decks refreshes the target with the saved preamble first.
        window.centre.preview.render_after_save()


def insert_admin_slides(window, deck: Deck, admin: AdminSlidesTab) -> None:
    try:
        slide_paths = admin_slides.insert_admin_slides(
            window.project, deck, admin.position, admin.slide_specs, admin.language)
    except (OSError, ValueError, deck_editor.StaleFileError) as exc:
        QMessageBox.critical(window, "Admin slides failed", str(exc))
        return
    window.after_deck_edit(
        deck.path, f"Inserted admin slides into {deck.name}", previous_text=deck.text)
    window.open_slide_editor(slide_paths[0])


def on_edit_deck_tags(window, deck: Deck) -> None:
    """⋮ -> "Tags…": choose the group the deck appears
    in. Written into the deck's own file as \\decktags{...}."""
    if window.centre.unsaved(deck.path):
        QMessageBox.information(
            window, "Tags",
            f"{deck.name}.tex has edits in the Source view that could not be saved -- resolve "
            "that first, so this change and that editor can't overwrite each other.",
        )
        return
    if deck.group == TAG_MANUAL:
        return  # its Tags button is disabled; the manual keeps its section
    sheet = DeckGroupSheet(window, f"Tags — {deck.name}", deck.group)
    if not sheet.exec():
        return
    group = sheet.group
    if group == deck.group and group in deck.tags:
        return  # already exactly that
    try:
        deck_editor.set_deck_tags(
            deck.path, deck.text, tags_with_group(deck.tags, group))
    except (deck_editor.StaleFileError, ValueError, OSError) as exc:
        QMessageBox.critical(window, "Tags failed", str(exc))
        return
    window.log(f"Tagged {deck.name} as {group}")
    window.refresh_open_deck_editors()


def on_new_deck(window) -> None:
    """⌘K / ⋮ "New deck…": an empty deck; its name, template (the open deck's, else the render template, to
    start with) and group are asked together like "Duplicate deck…"."""
    deck = window.state.deck
    template = slide_snapshot.detect_template(deck.preamble_text) if deck is not None \
        else slide_snapshot.render_template(window.project)
    available = slide_snapshot.available_templates(window.project.root) or [template]
    labels = [(key, slide_snapshot.template_label(key, window.project.root)) for key in available]
    sheet = DeckGroupSheet(
        window, "New deck", deck.group if deck is not None else "", ok_text="Create",
        name_prompt="Name of the new deck (the file decks/<name>.tex)",
        default_name="new-deck",
        validate_name=lambda n: deck_duplicate.is_valid_deck_name(n, window.project.decks_dir),
        templates=labels, current_template=template,
    )
    if not sheet.exec():
        return
    try:
        dest = deck_new.new_deck(window.project, sheet.name, sheet.template or template, sheet.group)
    except Exception as exc:  # noqa: BLE001 -- surface any failure to the user
        QMessageBox.critical(window, "New deck failed", str(exc))
        return
    window.log(f"Created {dest.name} ({slide_snapshot.template_label(sheet.template or template, window.project.root)})")
    window.reload_decks()
    created = next((d for d in window.decks if d.path == dest), None)
    if created is not None:
        window.state.set_deck(created)


def on_duplicate_deck(window, deck: Deck) -> None:
    # Creation is where a deck's tag is first chosen (2026-09-19): the
    # dialog takes the copy's name and its group together, defaulting
    # to the original's group.
    sheet = DeckGroupSheet(
        window, "Duplicate deck", deck.group, ok_text="Duplicate",
        name_prompt=f"Name for the copy of {deck.name}.tex",
        default_name=f"{deck.name}-copy",
        validate_name=lambda n: deck_duplicate.is_valid_deck_name(n, deck.path.parent),
    )
    if not sheet.exec():
        return
    new_name, group = sheet.name, sheet.group
    try:
        dest = deck_duplicate.duplicate_deck(window.project, deck, new_name)
    except Exception as exc:  # noqa: BLE001 -- surface any failure to the user
        QMessageBox.critical(window, "Duplicate failed", str(exc))
        return
    window.log(f"Duplicated {deck.name}.tex -> {dest.name}")
    if group != deck.group or group not in deck.tags:
        try:
            deck_editor.set_deck_tags(
                dest, read_text_exact(dest), tags_with_group(deck.tags, group))
            window.log(f"Tagged {dest.stem} as {group}")
        except (deck_editor.StaleFileError, ValueError, OSError) as exc:
            QMessageBox.warning(
                window, "Tags",
                f"{dest.name} was created, but tagging it as {group} failed: {exc}")
    window.reload_decks()
    # The copy opens, as a new deck does (v8.58.0): it is what the user goes on with.
    copy = next((d for d in window.decks if d.path == dest), None)
    if copy is not None:
        window.state.set_deck(copy)


def generate_deck_transcript(window, deck: Deck, version: str, *, quiet: bool = False) -> bool:
    """Whole-deck transcript generation (write_transcript(), written to
    transcripts/ or the deck's own \\deckoutputfolder[transcript]{}/
    bare \\deckoutputfolder{} override) -- shared by the deck-editor
    tab's own "Transcript" button and the Compile menu's transcript
    entries, so the success/error/log handling lives in exactly one
    place. Same synchronous-with-a-wait-cursor pattern the Images tab's
    own (now single-slide-only) generate button uses: this is a fast
    regex-based render, not a LaTeX compile, so no thread is needed.
    quiet=True skips the completion dialog on success (batch runs).
    Returns whether it succeeded."""
    target_dir, stem = transcript.resolve_transcript_location(window.project, deck, deck.path, version)
    QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
    try:
        md_path, html_path, result = transcript.write_transcript(
            window.project, deck.path, version, directory=target_dir, filename_stem=stem)
    except Exception as exc:  # noqa: BLE001 -- surface any failure to the user
        QMessageBox.critical(window, "Transcript failed", f"{deck.name} ({version}):\n{exc}")
        window.log(f"*** Transcript generation failed for {deck.path.stem} ({version}): {exc} ***")
        return False
    finally:
        QApplication.restoreOverrideCursor()

    window.log(
        f"Transcript for {deck.path.stem} ({version}): "
        f"{len(result.slides)} of {result.total_in_deck} slides -> "
        f"{md_path.name}, {html_path.name}"
    )
    if result.undescribed:
        window.log(
            f"    {result.undescribed} slide(s) contain an image with no "
            f"description yet; those points are marked in the transcript."
        )
    if not quiet:
        QMessageBox.information(
            window, "Transcript generated",
            f"{len(result.slides)} of {result.total_in_deck} slides written to:\n\n"
            f"{md_path}\n{html_path}"
            + (f"\n\n{result.undescribed} slide(s) still have an undescribed "
               f"image; those are flagged in place." if result.undescribed else ""),
        )
    return True
