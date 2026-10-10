"""Actions on a deck, moved out of qt_gui.py (step 3 of docs/UI_REDESIGN_PLAN.md):
what the old deck table's per-deck buttons (Open pdf, Settings, Source, Duplicate,
Tags, Archive) and its Create Transcript button did. The top bar's menus
(menus.py) now start them for the current deck.

`DeckActionsMixin` is mixed into WorkspaceWindow (window.py), which provides
`state`, `compiling`, `_log` and `reload_decks()`.
"""
from __future__ import annotations

from datetime import datetime
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog, QInputDialog, QMessageBox

from ... import archive as archive_mod
from ... import deck_duplicate, deck_editor, deck_settings, deck_snapshot, open_path, transcript
from ...compiler import deck_pdfs, pdf_to_open
from ...deck_scan import GROUP_TAGS, TAG_MANUAL, Deck
from ...qt_deck_settings_dialog import DeckSettingsDialog
from ..dialogs.deck_group import DeckGroupSheet
from ..dialogs.snapshot import SnapshotSheet


class DeckActionsMixin:
    def _on_admin_slides(self, deck: Deck) -> None:
        """⋮ -> "Admin slides…": insert a title slide and/or a course-sessions
        table generated from the deck's linked Uni Graz course."""
        from ...qt_admin_slides_dialog import AdminSlidesDialog, insert_admin_slides

        dialog = AdminSlidesDialog(self, deck)
        if dialog.exec() != AdminSlidesDialog.DialogCode.Accepted or not dialog.slide_specs:
            return
        try:
            slide_paths = insert_admin_slides(
                deck, dialog.position, dialog.slide_specs, dialog.language)
        except (OSError, ValueError, deck_editor.StaleFileError) as exc:
            QMessageBox.critical(self, "Admin slides failed", str(exc))
            return
        self.after_deck_edit(
            deck.path, f"Inserted admin slides into {deck.name}", previous_text=deck.text)
        self.open_slide_editor(slide_paths[0])

    def _archive_deck(self, deck: Deck) -> None:
        """Archiving is when a deck stops being maintained, so it offers a
        snapshot first (v5.33.0): "Snapshot, then archive" (default) /
        "Archive only" / Cancel. The snapshot uses the settings last chosen
        in ⋮ → Create deck snapshot…, runs on the compile slot, and
        must come before archive.archive_deck() rewrites the deck's path
        lines -- the deck is archived only when it has finished (or, if it
        failed, after a second yes)."""
        options = deck_snapshot.saved_options()
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle("Archive deck")
        box.setText(f"Move {deck.name}.tex to decks/archive/?")
        box.setInformativeText(
            "Create a snapshot first? It keeps a self-contained copy of the deck "
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
            self._do_archive_deck(deck)
        elif clicked is snapshot_button:
            self._start_snapshots(
                [deck], options,
                after=lambda results: self._archive_after_snapshot(deck, results))

    def _archive_after_snapshot(self, deck: Deck, results: list) -> None:
        result = results[0] if results else None
        if result is not None and result.ok:
            self._do_archive_deck(deck)
            return
        reason = result.error if result is not None else "no result"
        reply = QMessageBox.question(
            self, "Snapshot failed",
            f"The snapshot of {deck.name} failed ({reason}).\n\n"
            "Archive the deck anyway?",
            defaultButton=QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            self._do_archive_deck(deck)

    def _do_archive_deck(self, deck: Deck) -> None:
        try:
            archive_mod.archive_deck(deck)
        except Exception as exc:  # noqa: BLE001 -- surface any failure to the user
            QMessageBox.critical(self, "Archive failed", str(exc))
            return
        self._log(f"Archived {deck.name}.tex -> decks/archive/{deck.name}.tex")
        self.reload_decks()

    def _on_create_deck_snapshot(self) -> None:
        """⋮ -> "Create deck snapshot…": the dialog, then one snapshot
        per checked deck, one after the other, on the compile slot."""
        decks = self.decks
        preselected = {self.state.deck.name} if self.state.deck is not None else set()
        sheet = SnapshotSheet(self, decks, preselected, busy=self.compiling)
        if sheet.exec() != QDialog.DialogCode.Accepted:
            return
        self._start_snapshots(sheet.selected_decks(), sheet.options())

    @staticmethod
    def _tags_with_group(deck_tags: list[str], group: str) -> list[str]:
        """`group` as the deck's group tag, keeping any other tags it has."""
        return [group] + [t for t in deck_tags if t not in GROUP_TAGS]

    def _on_open_latest_pdf(self, deck: Deck) -> None:
        """⋮ → "Open latest PDF" (2026-09-21): opens the
        deck's preferred PDF (Settings -> "Open pdf opens", else the
        instructor PDF), unless a newer PDF of the deck comes from another
        compile run -- then it asks which one, newest first (2026-10-08,
        direct instructions; compiler.pdf_to_open())."""
        pdfs = deck_pdfs(deck)
        if not pdfs:
            QMessageBox.information(
                self, "No PDF yet", f"No PDF has been created for {deck.name} yet.")
            return
        chosen = pdf_to_open(pdfs)
        if chosen is None:
            labels = [f"{pdf.label} -- {datetime.fromtimestamp(pdf.mtime):%Y-%m-%d %H:%M}"
                      for pdf in pdfs]
            default = next((i for i, pdf in enumerate(pdfs) if pdf.preferred), 0)
            label, ok = QInputDialog.getItem(
                self, "Open pdf",
                f"{deck.name} has PDFs from a later compile run than the one it usually opens.\n"
                "Which one should open?", labels, default, False)
            if not ok:
                return
            chosen = pdfs[labels.index(label)]
        pdf_path = chosen.path
        try:
            open_path.open_in_default_app(pdf_path)
        except OSError as exc:
            self._log(f"*** couldn't open {pdf_path.name}: {exc} ***")

    def _on_deck_settings(self, deck: Deck) -> None:
        """⋮ -> "Deck settings…": the deck-wide settings that live in
        the deck's own file (deck_settings.py), all written in one go."""
        if self.centre.is_dirty(deck.path):
            QMessageBox.information(
                self, "Deck settings",
                f"{deck.name}.tex has unsaved edits in the Source view -- save or "
                "revert them first, so this change and that editor can't overwrite each other.",
            )
            return
        old = deck_settings.read_settings(deck.text)
        dialog = DeckSettingsDialog(self, deck.name, old, deck_settings.template_choices())
        if not dialog.exec():
            return
        new = dialog.result_settings()
        if new != old:
            try:
                deck_settings.save_settings(deck.path, deck.text, old, new)
            except (deck_editor.StaleFileError, ValueError, OSError) as exc:
                QMessageBox.critical(self, "Deck settings failed", str(exc))
                return
            changed = [name for name in ("template", "language", "footer_text", "course_url",
                                         "output_folders", "appendix_toc")
                       if getattr(new, name) != getattr(old, name)]
            self._log(f"Updated settings of {deck.name}: " + ", ".join(
                name.replace("_", " ") for name in changed))
            self.refresh_open_deck_editors()
            self.reload_decks()
        if dialog.open_link_requested and new.course_url:
            try:
                open_path.open_in_default_app(new.course_url)
            except OSError as exc:
                QMessageBox.warning(self, "Course link", f"Could not open {new.course_url}: {exc}")
                self._log(f"*** couldn't open course link for {deck.name}: {exc} ***")

    def _on_edit_deck_tags(self, deck: Deck) -> None:
        """⋮ -> "Tags…": choose the group the deck appears
        in. Written into the deck's own file as \\decktags{...}."""
        if self.centre.is_dirty(deck.path):
            QMessageBox.information(
                self, "Tags",
                f"{deck.name}.tex has unsaved edits in the Source view -- save or "
                "revert them first, so this change and that editor can't overwrite each "
                "other.",
            )
            return
        if deck.group == TAG_MANUAL:
            return  # its Tags button is disabled; the manual keeps its section
        sheet = DeckGroupSheet(self, f"Tags — {deck.name}", deck.group)
        if not sheet.exec():
            return
        group = sheet.group
        if group == deck.group and group in deck.tags:
            return  # already exactly that
        try:
            deck_editor.set_deck_tags(
                deck.path, deck.text, self._tags_with_group(deck.tags, group))
        except (deck_editor.StaleFileError, ValueError, OSError) as exc:
            QMessageBox.critical(self, "Tags failed", str(exc))
            return
        self._log(f"Tagged {deck.name} as {group}")
        self.refresh_open_deck_editors()

    def _on_duplicate_deck(self, deck: Deck) -> None:
        # Creation is where a deck's tag is first chosen (2026-09-19): the
        # dialog takes the copy's name and its group together, defaulting
        # to the original's group.
        sheet = DeckGroupSheet(
            self, "Duplicate deck", deck.group, ok_text="Duplicate",
            name_prompt=f"Name for the copy of {deck.name}.tex",
            default_name=f"{deck.name}-copy",
            validate_name=lambda n: deck_duplicate.is_valid_deck_name(n, deck.path.parent),
        )
        if not sheet.exec():
            return
        new_name, group = sheet.name, sheet.group
        try:
            dest = deck_duplicate.duplicate_deck(deck, new_name)
        except Exception as exc:  # noqa: BLE001 -- surface any failure to the user
            QMessageBox.critical(self, "Duplicate failed", str(exc))
            return
        self._log(f"Duplicated {deck.name}.tex -> {dest.name}")
        if group != deck.group or group not in deck.tags:
            try:
                deck_editor.set_deck_tags(
                    dest, deck_editor._read(dest), self._tags_with_group(deck.tags, group))
                self._log(f"Tagged {dest.stem} as {group}")
            except (deck_editor.StaleFileError, ValueError, OSError) as exc:
                QMessageBox.warning(
                    self, "Tags",
                    f"{dest.name} was created, but tagging it as {group} failed: {exc}")
        self.reload_decks()

    def generate_deck_transcript(self, deck: Deck, version: str, *, quiet: bool = False) -> bool:
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
        target_dir, stem = transcript.resolve_transcript_location(deck, deck.path, version)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            md_path, html_path, result = transcript.write_transcript(
                deck.path, version, directory=target_dir, filename_stem=stem)
        except Exception as exc:  # noqa: BLE001 -- surface any failure to the user
            QMessageBox.critical(self, "Transcript failed", f"{deck.name} ({version}):\n{exc}")
            self._log(f"*** Transcript generation failed for {deck.path.stem} ({version}): {exc} ***")
            return False
        finally:
            QApplication.restoreOverrideCursor()

        self._log(
            f"Transcript for {deck.path.stem} ({version}): "
            f"{len(result.slides)} of {result.total_in_deck} slides -> "
            f"{md_path.name}, {html_path.name}"
        )
        if result.undescribed:
            self._log(
                f"    {result.undescribed} slide(s) contain an image with no "
                f"description yet; those points are marked in the transcript."
            )
        if not quiet:
            QMessageBox.information(
                self, "Transcript generated",
                f"{len(result.slides)} of {result.total_in_deck} slides written to:\n\n"
                f"{md_path}\n{html_path}"
                + (f"\n\n{result.undescribed} slide(s) still have an undescribed "
                   f"image; those are flagged in place." if result.undescribed else ""),
            )
        return True
