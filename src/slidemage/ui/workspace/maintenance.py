"""Project and application maintenance of the main window:

* checks that run shortly after start -- project compatibility (compat.py),
  the project's copies of the framework and the manual (bundled_copies.py)
  and the update check (updater.py);
* the Info menu actions that repeat them on demand;
* the Housekeeping actions (empty pdf/, remove temp files, archive unused
  content, reestablish translation links), which the Housekeeping sheet
  (ui/dialogs/housekeeping.py) offers in one place.

On start, when a change of this SlideMage that may break the project is
pending: Update project / Show report / Not now (asks again next time) /
Don't ask again (per change). Appearance-only changes never pop up; they are
listed under ⋮ → Project compatibility.

`MaintenanceMixin` is mixed into WorkspaceWindow (window.py), which provides
`log`, `signals`, `compiling` and `_resolve_dirty_edits()`.
"""
from __future__ import annotations

import sys
import tempfile
import threading
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication, QMessageBox, QProgressDialog

from ... import bundled_copies, compat, housekeeping, open_path, project, slide_rename, updater
from ... import version as version_mod
from ...deck_scan import PROJECT_ROOT
from ..dialogs.about import AboutSheet
from ..dialogs.housekeeping import ARCHIVE_PAGE, HousekeepingSheet
from ..dialogs.open_project import NewerProjectSheet
from ..dialogs.project_compat import DONT_ASK, MARK_READ, UPDATE, CompatSheet

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

    def _project_needs_check(self, root: Path) -> bool:
        """Whether a change of compat.py is pending for another project (the picker's chip)."""
        if project.is_snapshot(root):
            return False
        try:
            return bool(compat.evaluate(root, version_mod.VERSION_NUMBER).loud)
        except Exception:  # noqa: BLE001 -- a broken detector must not stop the picker
            return False

    def _compat_newer_notice(self, highest: str, app_version: str) -> None:
        sheet = NewerProjectSheet(self, PROJECT_ROOT.name, highest, app_version, opening=False,
                                  on_update=self._on_check_for_updates)
        sheet.exec()
        if sheet.choice == NewerProjectSheet.NEVER:
            compat.ignore_newer(PROJECT_ROOT, highest)

    def _compat_report(self, evaluation) -> None:
        path = compat.write_report(PROJECT_ROOT, evaluation, version_mod.VERSION_NUMBER)
        self.log(f"Wrote {path.relative_to(PROJECT_ROOT).as_posix()}")
        try:
            open_path.open_in_default_app(path)
        except OSError as exc:
            self.log(f"*** couldn't open {path.name}: {exc} ***")

    def _show_compat(self, evaluation, *, review: bool) -> None:
        sheet = CompatSheet(self, evaluation, version_mod.VERSION_NUMBER, PROJECT_ROOT.name, review=review,
                            on_report=lambda: self._compat_report(evaluation))
        sheet.exec()
        if sheet.choice == DONT_ASK:
            compat.dismiss(PROJECT_ROOT, [p.change.id for p in evaluation.loud])
            self.log("Compatibility notice dismissed for these changes "
                     "(⋮ → Project compatibility still lists them).")
        elif sheet.choice == MARK_READ:
            compat.dismiss(PROJECT_ROOT, [p.change.id for p in evaluation.everything])
        elif sheet.choice == UPDATE:
            self._compat_update(evaluation)

    def _compat_update(self, evaluation) -> None:
        app_version = version_mod.VERSION_NUMBER
        if self.centre.source.dirty_files():
            QMessageBox.information(
                self, "Update project",
                "Save or revert the unsaved edits in the Source view first, so the update and "
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
        AboutSheet(self).exec()

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

    def _bundled_parts(self) -> list:
        """What the framework / manual copies of this project would get (bundled_copies.plan_updates)."""
        return bundled_copies.plan_updates(
            PROJECT_ROOT, latex_source=project.template_dir("latex"),
            example_source=project.template_dir("example"))

    def check_bundled_copies(self) -> None:
        app_version = version_mod.VERSION_NUMBER
        if bundled_copies.is_dismissed(PROJECT_ROOT, app_version):
            return
        try:
            parts = self._bundled_parts()
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
        if clicked is update_button:
            self._apply_bundled_parts(parts)

    def _apply_bundled_parts(self, parts: list) -> None:
        for part in parts:
            try:
                backup = bundled_copies.apply_update(PROJECT_ROOT, part, version_mod.VERSION_NUMBER)
            except OSError as exc:
                QMessageBox.critical(self, "Update failed", f"{part.label}: {exc}")
                continue
            for line in bundled_copies.summary_lines(part):
                self.log(f"Updated -- {line}")
            if part.update or part.remove:
                self.log(f"  backup: {backup}")
        self.reload_decks()

    def can_add_manual(self) -> bool:
        """Whether the SlideMage manual is not in this project and this copy carries it."""
        try:
            return any(part.new_install for part in self._bundled_parts())
        except OSError:
            return False

    def _on_add_manual(self) -> None:
        """Adds the SlideMage manual (bundled_copies, as the start-up offer does): its deck, slides,
        snippets and images; files that exist are never overwritten."""
        self._apply_bundled_parts([part for part in self._bundled_parts() if part.new_install])

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
            "(Settings → General).")
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
                    "Updates will be installed automatically (Settings → General)"
                    if choice == "auto" else
                    "SlideMage will no longer check for updates on start "
                    "(Settings → General; ⋮ → Check for updates… still works)")
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

    def _on_housekeeping(self) -> None:
        sheet = HousekeepingSheet(self)
        sheet.exec()
        if sheet.update_previews:
            self._on_update_previews()

    def _empty_pdf_folder(self) -> None:
        files = housekeeping.pdf_files()
        if not files:
            QMessageBox.information(self, "Nothing to do", "pdf/ is already empty (or doesn't exist yet).")
            return
        reply = QMessageBox.question(self, "Empty folder", f"Delete all {len(files)} file(s) in pdf/?")
        if reply != QMessageBox.StandardButton.Yes:
            return
        housekeeping.delete_files(files)
        self._log(f"Emptied pdf/ ({len(files)} file(s) deleted)")

    def _remove_temp_files(self) -> None:
        if self.compiling:
            QMessageBox.information(
                self, "Busy", "Can't remove temp files while a compile run is in progress."
            )
            return
        found = housekeeping.find_temp_files()
        if not found:
            QMessageBox.information(self, "Nothing to do", "No temp files to remove.")
            return
        reply = QMessageBox.question(
            self,
            "Remove temp files",
            f"Delete {len(found.build)} build item(s) in .build/, "
            f"{len(found.wrappers)} leftover wrapper file(s) in decks/, and "
            f"{len(found.scratch)} item(s) in .temp/ (the workflow scratch "
            "folder -- e.g. a PPTX mid-conversion or an image waiting to "
            "be cropped -- not just build output)?",
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        housekeeping.remove_temp_files(found)
        self._log(
            f"Removed {found.count - len(found.scratch)} temp item(s) "
            f"({len(found.build)} build item(s) in .build/, "
            f"{len(found.wrappers)} wrapper file(s) in decks/) "
            f"and {len(found.scratch)} item(s) in .temp/"
        )

    def _on_archive_unused_content(self) -> None:
        """Opens the Housekeeping sheet on its archive review: it lists every file the scan
        found before anything is moved (2026-09-27, direct instruction, after a batch run
        archived far more than expected -- see unused_content.py)."""
        sheet = HousekeepingSheet(self, ARCHIVE_PAGE)
        sheet.exec()

    def _on_sync_translation_links(self) -> int:
        """Refreshes translation cross-reference comments from current
        disk state -- pure text scanning over slides/, no compile
        involved, so (unlike Update previews) this runs synchronously rather
        than on a background thread. Returns the number of files updated."""
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
        return changed
