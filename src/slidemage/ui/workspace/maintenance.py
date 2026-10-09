"""Project and application maintenance of the main window, moved out of
qt_gui.py (step 3 of docs/UI_REDESIGN_PLAN.md) with the logic unchanged:

* checks that run shortly after start -- project compatibility (compat.py),
  the project's copies of the framework and the manual (bundled_copies.py)
  and the update check (updater.py);
* the Info menu actions that repeat them on demand;
* the Housekeeping actions (empty pdf/, remove temp files, archive unused
  content, reestablish translation links).

On start, when a change of this SlideMage that may break the project is
pending: Update project / Show report / Not now (asks again next time) /
Don't ask again (per change). Appearance-only changes never pop up; they are
listed under ⋮ → Project compatibility.

`MaintenanceMixin` is mixed into WorkspaceWindow (window.py), which provides
`log`, `signals`, `compiling` and `_resolve_dirty_edits()`.
"""
from __future__ import annotations

import shutil
import sys
import tempfile
import threading
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox, QProgressDialog

from ... import bundled_copies, compat, compiler, deck_snapshot, open_path, project, qt_compat_dialog, slide_rename
from ... import unused_content, updater
from ... import version as version_mod
from ...compiler import PDF_DIR
from ...deck_scan import DECKS_DIR, PROJECT_ROOT
from ...qt_archive_unused_dialog import ArchiveUnusedDialog
from ...qt_compat_dialog import CompatDialog
from ...qt_version_history_dialog import VersionHistoryDialog
from ...unused_content import archive_unused_content

# The project root's own workflow scratch folder (CONVERSION_NOTES.md) --
# where a PPTX mid-conversion, a higher-resolution source image waiting to
# be cropped, or similar working input gets placed by hand. Unlike .build/
# and decks/_slidemage_*.tex, this isn't SlideMage's own build output, but
# "Remove temp files" (2026-09-18, direct instruction) empties it too.
TEMP_DIR = PROJECT_ROOT / ".temp"

STARTUP_UPDATE_CHECK_DELAY_MS = 3000
# The framework/manual copy check (bundled_copies.py) runs once, shortly after
# the window is up -- a local comparison, no network.
BUNDLED_COPIES_CHECK_DELAY_MS = 1500
# The project compatibility check (compat.py): static scans of the project, a
# local comparison -- shown before the framework/manual update offer.
COMPAT_CHECK_DELAY_MS = 1000


class MaintenanceMixin:
    def schedule_compat_check(self) -> None:
        QTimer.singleShot(COMPAT_CHECK_DELAY_MS, self.check_project_compat)

    def check_project_compat(self) -> None:
        if project.is_snapshot(PROJECT_ROOT):
            return  # a deck snapshot is frozen: nothing to migrate
        app_version = version_mod.VERSION_NUMBER
        try:
            evaluation = compat.evaluate(PROJECT_ROOT, app_version)
        except Exception as exc:  # noqa: BLE001 -- a broken detector must not stop the app
            self.log(f"Couldn't check the project's compatibility: {exc}")
            return
        if evaluation.newer_notice:
            self._compat_newer_notice(evaluation.newer_notice, app_version)
        if evaluation.loud:
            self._show_compat(evaluation, review=False)

    def _compat_newer_notice(self, highest: str, app_version: str) -> None:
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Project from a newer SlideMage")
        box.setText(f"This project was last used with SlideMage {highest}, which is newer "
                    f"than this one ({app_version}).")
        box.setInformativeText("Features of the newer version may not work here. Info → Check for "
                               "updates… installs the newer one.")
        box.addButton("Not now", QMessageBox.ButtonRole.RejectRole)
        never = box.addButton("Don't ask again", QMessageBox.ButtonRole.DestructiveRole)
        box.exec()
        if box.clickedButton() is never:
            compat.ignore_newer(PROJECT_ROOT, highest)

    def _compat_report(self, evaluation) -> None:
        path = compat.write_report(PROJECT_ROOT, evaluation, version_mod.VERSION_NUMBER)
        self.log(f"Wrote {path.relative_to(PROJECT_ROOT).as_posix()}")
        try:
            open_path.open_in_default_app(path)
        except OSError as exc:
            self.log(f"*** couldn't open {path.name}: {exc} ***")

    def _show_compat(self, evaluation, *, review: bool) -> None:
        app_version = version_mod.VERSION_NUMBER
        dialog = CompatDialog(self, evaluation, app_version, review=review,
                              on_report=lambda: self._compat_report(evaluation))
        dialog.exec()
        choice = dialog.choice
        if choice == qt_compat_dialog.DONT_ASK:
            compat.dismiss(PROJECT_ROOT, [p.change.id for p in evaluation.loud])
            self.log("Compatibility notice dismissed for these changes "
                     "(Info → Project compatibility still lists them).")
        elif choice == qt_compat_dialog.MARK_READ:
            compat.dismiss(PROJECT_ROOT, [p.change.id for p in evaluation.everything])
        elif choice == qt_compat_dialog.UPDATE:
            self._compat_update(evaluation)

    def _compat_update(self, evaluation) -> None:
        app_version = version_mod.VERSION_NUMBER
        if self._slide_source_tabs:
            QMessageBox.information(
                self, "Update project",
                "Close the open slide and deck source editors first, so the update and "
                "an editor can't overwrite each other.")
            return
        result = compat.run_update(PROJECT_ROOT, evaluation.loud)
        for rel in result.changed:
            self.log(f"Updated {rel}")
        if result.backup:
            self.log(f"  backup: {result.backup}")
        for error in result.errors:
            self.log(f"*** update failed: {error} ***")
        self.refresh_open_deck_editors()
        remaining = compat.evaluate(PROJECT_ROOT, app_version)
        if remaining.loud or result.errors:
            self._compat_report(remaining)
            QMessageBox.warning(
                self, "Update project",
                f"{len(result.changed)} file(s) updated. Some changes need work by hand; the "
                "report lists where, and has a prompt for an AI tool.")
        else:
            compat.acknowledge(PROJECT_ROOT, app_version)
            QMessageBox.information(self, "Update project",
                                    f"{len(result.changed)} file(s) updated. Backups are in "
                                    ".slidemage/backups/.")

    def _on_project_compat(self) -> None:
        evaluation = compat.evaluate(PROJECT_ROOT, version_mod.VERSION_NUMBER)
        self._show_compat(evaluation, review=True)

    def _on_open_version_history(self) -> None:
        dialog = VersionHistoryDialog(self)
        dialog.exec()

    def _on_check_for_updates(self) -> None:
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            releases = updater.fetch_releases()
        except updater.UpdateError as exc:
            QMessageBox.warning(self, "Check for updates", str(exc))
            return
        finally:
            QApplication.restoreOverrideCursor()

        current = version_mod.VERSION_NUMBER
        plan = updater.plan_update(releases, current)
        if plan.latest is None:
            QMessageBox.information(
                self, "Check for updates", f"SlideMage {current} is up to date.")
            return
        if not updater.can_self_update():
            QMessageBox.information(
                self, "Update available",
                f"SlideMage {plan.latest.tag} is available (you have {current}).\n\n"
                "This copy runs from source, so it can't replace itself -- "
                f"update it with git pull, or download the release from:\n{plan.latest.page_url}",
            )
            return
        self._offer_update(plan, updater.get_update_mode(), manual=True)

    def schedule_bundled_copies_check(self) -> None:
        QTimer.singleShot(BUNDLED_COPIES_CHECK_DELAY_MS, self.check_bundled_copies)

    def check_bundled_copies(self) -> None:
        app_version = version_mod.VERSION_NUMBER
        if bundled_copies.is_dismissed(PROJECT_ROOT, app_version):
            return
        try:
            parts = bundled_copies.plan_updates(
                PROJECT_ROOT, latex_source=project._template_dir("latex"),
                example_source=project._template_dir("example"))
        except OSError as exc:
            self.log(f"Couldn't compare the project's framework/manual copies: {exc}")
            return
        if not parts:
            return
        lines = [line for part in parts for line in bundled_copies.summary_lines(part)]
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Information)
        box.setWindowTitle("Newer framework / manual")
        if all(part.new_install for part in parts):
            box.setText("SlideMage comes with its own manual, a deck that explains "
                        "and demonstrates everything. Add it to this project?")
        else:
            box.setText(f"SlideMage {app_version} comes with newer files than this "
                        "project's copies. Update them?")
        box.setInformativeText(
            "\n".join(lines) + "\n\nEvery file that is replaced or removed is backed up "
            "first, to .slidemage/backups/. Files changed in this project are kept.")
        update_button = box.addButton("Update", QMessageBox.ButtonRole.AcceptRole)
        if all(part.new_install for part in parts):
            update_button.setText("Add the manual")
        box.addButton("Not now", QMessageBox.ButtonRole.RejectRole)
        never_button = box.addButton(
            "Don't ask again for this version", QMessageBox.ButtonRole.DestructiveRole)
        box.setDefaultButton(update_button)
        box.exec()
        clicked = box.clickedButton()
        if clicked is never_button:
            bundled_copies.dismiss(PROJECT_ROOT, app_version)
            self.log(f"Framework/manual update for {app_version} declined; "
                     "not asking again until the next SlideMage version.")
            return
        if clicked is not update_button:
            return
        for part in parts:
            try:
                backup = bundled_copies.apply_update(PROJECT_ROOT, part, app_version)
            except OSError as exc:
                QMessageBox.critical(self, "Update failed", f"{part.label}: {exc}")
                continue
            for line in bundled_copies.summary_lines(part):
                self.log(f"Updated -- {line}")
            if part.update or part.remove:
                self.log(f"  backup: {backup}")
        self.reload_decks()

    def schedule_startup_update_check(self) -> None:
        if not updater.can_self_update():
            return  # a copy run from source is updated with git
        if updater.get_update_mode() == updater.UPDATE_MODE_OFF:
            return
        QTimer.singleShot(STARTUP_UPDATE_CHECK_DELAY_MS, self._startup_update_check)

    def _startup_update_check(self) -> None:
        def work() -> None:
            try:
                result = updater.plan_update(
                    updater.fetch_releases(), version_mod.VERSION_NUMBER)
            except updater.UpdateError as exc:
                result = exc
            self.signals.update_check_done.emit(result)

        threading.Thread(target=work, daemon=True).start()

    def _on_startup_update_check_done(self, result) -> None:
        """Never a popup for a failed check or an up-to-date copy -- only
        the log, so an offline start stays quiet."""
        if isinstance(result, updater.UpdateError):
            self.log(f"Update check failed: {result}")
            return
        if result.latest is None:
            self.log(f"SlideMage {version_mod.VERSION_NUMBER} is up to date.")
            return
        mode = updater.get_update_mode()
        if mode == updater.UPDATE_MODE_OFF:
            return  # switched off while the check was running
        self._offer_update(result, mode, manual=False)

    def _offer_update(self, plan: updater.UpdatePlan, mode: str, manual: bool) -> None:
        """Offer (or, in "auto" mode, install) `plan.latest`. `manual` is
        Info → Check for updates…, which always asks with a plain Yes/No."""
        latest = plan.latest
        if latest is None:
            return
        if plan.breaking:
            choice = self._ask_breaking_update(plan)
            if choice == "install":
                self._download_and_install_update(latest)
            elif choice == "stay" and plan.safe is not None:
                if mode == updater.UPDATE_MODE_AUTO or self._confirm_safe_update(plan.safe):
                    self._download_and_install_update(plan.safe)
            return
        if manual:
            reply = QMessageBox.question(
                self, "Update available",
                f"SlideMage {latest.tag} is available (you have "
                f"{version_mod.VERSION_NUMBER}).\n\nDownload it and replace this copy now?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if reply == QMessageBox.StandardButton.Yes:
                self._download_and_install_update(latest)
            return
        if mode == updater.UPDATE_MODE_AUTO:
            self.log(f"Installing SlideMage {latest.tag} (updates install automatically)")
            self._download_and_install_update(latest)
            return
        self._apply_update_choice(self._ask_update_choice(latest), latest)

    def _ask_update_choice(self, release: updater.Release) -> str:
        """"install", "later", "auto" or "off"."""
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle("Update available")
        box.setText(
            f"SlideMage {release.tag} is available (you have {version_mod.VERSION_NUMBER}).")
        box.setInformativeText(
            "Install it now? You can also change how SlideMage handles updates "
            "(Preferences → General).")
        install = box.addButton("Install now", QMessageBox.ButtonRole.AcceptRole)
        later = box.addButton("Not now", QMessageBox.ButtonRole.RejectRole)
        auto = box.addButton("Always install automatically", QMessageBox.ButtonRole.ActionRole)
        off = box.addButton("Stop checking for updates", QMessageBox.ButtonRole.ActionRole)
        box.setDefaultButton(install)
        box.setEscapeButton(later)
        box.exec()
        return {install: "install", auto: "auto", off: "off"}.get(box.clickedButton(), "later")

    def _apply_update_choice(self, choice: str, release: updater.Release) -> None:
        if choice in ("auto", "off"):
            mode = updater.UPDATE_MODE_AUTO if choice == "auto" else updater.UPDATE_MODE_OFF
            try:
                updater.set_update_mode(mode)
            except OSError as exc:
                self.log(f"Couldn't save the update setting: {exc}")
            else:
                self.log(
                    "Updates will be installed automatically (Preferences → General)"
                    if choice == "auto" else
                    "SlideMage will no longer check for updates on start "
                    "(Preferences → General; Info → Check for updates… still works)")
        if choice in ("install", "auto"):
            self._download_and_install_update(release)
        elif choice == "later":
            self.log(f"SlideMage {release.tag} is available; not installed for now")

    def _ask_breaking_update(self, plan: updater.UpdatePlan) -> str:
        """"install", "stay" or "later" -- asked whatever the update mode."""
        latest = plan.latest
        current = version_mod.VERSION_NUMBER
        notes = [note for release in plan.breaking for note in updater.breaking_notes(release)]
        if not notes:
            notes = [
                f"The major version number changes ({current} → {latest.tag}); "
                f"see the release notes: {latest.page_url}"
            ]
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("This update changes how SlideMage works")
        box.setText(
            f"SlideMage {latest.tag} is available (you have {current}). It breaks "
            "with the past -- some things may no longer work the way they did:")
        box.setInformativeText("\n\n".join(notes))
        install = box.addButton(f"Install {latest.tag} anyway", QMessageBox.ButtonRole.AcceptRole)
        stay = None
        if plan.safe is not None:
            major = (updater.parse_version(current) or (0,))[0]
            stay = box.addButton(f"Stay on v{major}.x", QMessageBox.ButtonRole.ActionRole)
        later = box.addButton("Not now", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(later)
        box.setEscapeButton(later)
        box.exec()
        clicked = box.clickedButton()
        if clicked is install:
            return "install"
        if stay is not None and clicked is stay:
            return "stay"
        return "later"

    def _confirm_safe_update(self, release: updater.Release) -> bool:
        reply = QMessageBox.question(
            self, "Update available",
            f"Install SlideMage {release.tag} instead? It has no breaking changes.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        return reply == QMessageBox.StandardButton.Yes

    def _download_and_install_update(self, release: updater.Release) -> None:
        executable = Path(sys.executable)
        binary_name = updater.ASSETS[sys.platform][1]
        progress = QProgressDialog(
            f"Downloading SlideMage {release.tag}…", "Cancel", 0, 0, self)
        progress.setWindowTitle("Updating SlideMage")
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.show()

        def on_progress(done: int, total: int) -> bool:
            if total:
                progress.setMaximum(total)
                progress.setValue(done)
            QApplication.processEvents()
            return not progress.wasCanceled()

        with tempfile.TemporaryDirectory(prefix="slidemage-update-") as tmp:
            zip_path = Path(tmp) / "update.zip"
            try:
                updater.download(release, zip_path, on_progress)
                progress.setLabelText("Installing…")
                progress.setCancelButton(None)
                QApplication.processEvents()
                updater.install_zip(zip_path, executable, binary_name)
            except updater.UpdateError as exc:
                progress.close()
                QMessageBox.warning(self, "Update failed", str(exc))
                return
        progress.close()

        reply = QMessageBox.question(
            self, "Update installed",
            f"SlideMage {release.tag} is installed in {executable.parent}.\n\n"
            "Restart now to use it?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        if self.compiling:
            QMessageBox.information(
                self, "Update installed",
                "A compile run is in progress -- restart SlideMage once it finishes.",
            )
            return
        if not self._resolve_dirty_edits():
            return
        project.relaunch_with_project(PROJECT_ROOT)
        self._dirty_edits_resolved_for_close = True
        self.close()

    def _empty_pdf_folder(self) -> None:
        self._empty_folder(PDF_DIR, "pdf/")

    def _remove_temp_files(self) -> None:
        if self.compiling:
            QMessageBox.information(
                self, "Busy", "Can't remove temp files while a compile run is in progress."
            )
            return
        build_entries = compiler.removable_build_entries()
        wrapper_files = list(DECKS_DIR.rglob("_slidemage_*.tex"))
        if not project.is_snapshot(PROJECT_ROOT):
            # left behind by an interrupted snapshot; in a snapshot they're its own
            wrapper_files += DECKS_DIR.rglob(f"{deck_snapshot.WRAPPER_PREFIX}*.tex")
        temp_entries = list(TEMP_DIR.iterdir()) if TEMP_DIR.exists() else []
        all_files = build_entries + wrapper_files
        if not all_files and not temp_entries:
            QMessageBox.information(self, "Nothing to do", "No temp files to remove.")
            return
        reply = QMessageBox.question(
            self,
            "Remove temp files",
            f"Delete {len(build_entries)} build item(s) in .build/, "
            f"{len(wrapper_files)} leftover wrapper file(s) in decks/, and "
            f"{len(temp_entries)} item(s) in .temp/ (the workflow scratch "
            "folder -- e.g. a PPTX mid-conversion or an image waiting to "
            "be cropped -- not just build output)?",
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        for p in build_entries:
            if p.is_dir():
                shutil.rmtree(p, ignore_errors=True)
            else:
                p.unlink(missing_ok=True)
        for p in wrapper_files:
            p.unlink(missing_ok=True)
        for p in temp_entries:
            if p.is_dir():
                shutil.rmtree(p, ignore_errors=True)
            else:
                p.unlink(missing_ok=True)
        self._log(
            f"Removed {len(all_files)} temp item(s) "
            f"({len(build_entries)} build item(s) in .build/, "
            f"{len(wrapper_files)} wrapper file(s) in decks/) "
            f"and {len(temp_entries)} item(s) in .temp/"
        )

    def _on_archive_unused_content(self) -> None:
        if self.compiling:
            QMessageBox.information(
                self,
                "Busy",
                "Can't archive unused content while a compile run is in "
                "progress -- a running compile could still need a file this "
                "would move.",
            )
            return
        # Scans first (a plain filesystem/text scan, fast enough to run on
        # the GUI thread) and shows exactly what would move before moving
        # anything (2026-09-27, direct instruction, after a batch run
        # archived far more than expected -- see ArchiveUnusedDialog's own
        # docstring). Only the actual move still runs in the background.
        unused_media = unused_content.find_unused_media()
        unused_slides = unused_content.find_unused_slides()
        if not unused_media and not unused_slides:
            QMessageBox.information(
                self, "Archive unused content", "No unused media files or slides found."
            )
            return
        dialog = ArchiveUnusedDialog(self, unused_media, unused_slides)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        threading.Thread(target=self._run_archive_unused_content, daemon=True).start()

    def _run_archive_unused_content(self) -> None:
        archive_unused_content(self.signals.log.emit)

    def _on_sync_translation_links(self) -> None:
        """Refreshes translation cross-reference comments from current
        disk state -- pure text scanning over slides/, no compile
        involved, so (unlike Archive unused content/Update previews) this
        runs synchronously rather than on a background thread."""
        changed, missing = slide_rename.regenerate_translation_links()
        self._log(f"Sync translation links: {changed} file(s) updated")
        for line in missing:
            self._log(f"    (unresolved: {line})")
        if missing:
            QMessageBox.warning(
                self, "Sync translation links",
                f"{changed} file(s) updated. {len(missing)} link(s) could "
                "not be resolved -- see the log pane for details.",
            )

    def _empty_folder(self, folder: Path, label: str) -> None:
        if not folder.exists():
            QMessageBox.information(self, "Nothing to do", f"{label} doesn't exist yet.")
            return
        files = [p for p in folder.iterdir() if p.is_file()]
        if not files:
            QMessageBox.information(self, "Nothing to do", f"{label} is already empty.")
            return
        reply = QMessageBox.question(self, "Empty folder", f"Delete all {len(files)} file(s) in {label}?")
        if reply != QMessageBox.StandardButton.Yes:
            return
        for p in files:
            p.unlink(missing_ok=True)
        self._log(f"Emptied {label} ({len(files)} file(s) deleted)")

