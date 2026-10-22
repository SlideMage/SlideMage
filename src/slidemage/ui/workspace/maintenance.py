# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
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

Plain functions of the window: each takes the WorkspaceWindow (window.py) first, which
provides `project`, `log`, `update_check_done`, `compiling` and `relaunch_with_project()`.
"""
from __future__ import annotations

import sys
import tempfile
import threading
from functools import partial
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication, QMessageBox, QProgressDialog

from ... import bundled_copies, compat, housekeeping, open_path, project, slide_preview, slide_rename, updater
from ... import version as version_mod
from ..dialogs.about import AboutSheet
from ..dialogs.housekeeping import ARCHIVE_PAGE, LIST_PAGE, HousekeepingJobs, HousekeepingSheet
from ..dialogs.open_project import NewerProjectSheet
from ..dialogs.project_compat import DONT_ASK, MARK_READ, UPDATE, CompatSheet
from . import compile_actions

STARTUP_UPDATE_CHECK_DELAY_MS = 3000
# The framework/manual copy check (bundled_copies.py) runs once, shortly after
# the window is up -- a local comparison, no network.
BUNDLED_COPIES_CHECK_DELAY_MS = 1500
RENDER_SWEEP_DELAY_MS = 8000
# The project compatibility check (compat.py): static scans of the project, a
# local comparison -- shown before the framework/manual update offer.
COMPAT_CHECK_DELAY_MS = 1000


def schedule_compat_check(window) -> None:
    QTimer.singleShot(COMPAT_CHECK_DELAY_MS, partial(check_project_compat, window))


def check_project_compat(window) -> None:
    if project.is_snapshot(window.project.root):
        return  # a deck snapshot is frozen: nothing to migrate
    app_version = version_mod.VERSION_NUMBER
    try:
        evaluation = compat.evaluate(window.project.root, app_version)
    except Exception as exc:  # noqa: BLE001 -- a broken detector must not stop the app
        window.log(f"Couldn't check the project's compatibility: {exc}")
        return
    if evaluation.newer_notice:
        compat_newer_notice(window, evaluation.newer_notice, app_version)
    if evaluation.loud:
        show_compat(window, evaluation, review=False)


def project_needs_check(root: Path) -> bool:
    """Whether a change of compat.py is pending for another project (the picker's chip)."""
    if project.is_snapshot(root):
        return False
    try:
        return bool(compat.evaluate(root, version_mod.VERSION_NUMBER).loud)
    except Exception:  # noqa: BLE001 -- a broken detector must not stop the picker
        return False


def compat_newer_notice(window, highest: str, app_version: str) -> None:
    sheet = NewerProjectSheet(window, window.project.root.name, highest, app_version, opening=False,
                              on_update=partial(on_check_for_updates, window))
    sheet.exec()
    if sheet.choice == NewerProjectSheet.NEVER:
        compat.ignore_newer(window.project.root, highest)


def compat_report(window, evaluation) -> None:
    path = compat.write_report(window.project.root, evaluation, version_mod.VERSION_NUMBER)
    window.log(f"Wrote {path.relative_to(window.project.root).as_posix()}")
    try:
        open_path.open_in_default_app(path)
    except OSError as exc:
        window.log(f"*** couldn't open {path.name}: {exc} ***")


def show_compat(window, evaluation, *, review: bool) -> None:
    sheet = CompatSheet(window, evaluation, version_mod.VERSION_NUMBER, window.project.root.name, review=review,
                        on_report=lambda: compat_report(window, evaluation))
    sheet.exec()
    if sheet.choice == DONT_ASK:
        compat.dismiss(window.project.root, [p.change.id for p in evaluation.loud])
        window.log("Compatibility notice dismissed for these changes "
                 "(⋮ → Project compatibility still lists them).")
    elif sheet.choice == MARK_READ:
        compat.dismiss(window.project.root, [p.change.id for p in evaluation.everything])
    elif sheet.choice == UPDATE:
        compat_update(window, evaluation)


def compat_update(window, evaluation) -> None:
    app_version = version_mod.VERSION_NUMBER
    window.centre.source.flush_all()      # saved as you type: only what could not be written is left
    if window.centre.source.dirty_files():
        QMessageBox.information(
            window, "Update project",
            "Some edits in the Source view could not be saved. Resolve that first, so the update and "
            "an editor can't overwrite each other.")
        return
    result = compat.run_update(window.project.root, evaluation.loud)
    for rel in result.changed:
        window.log(f"Updated {rel}")
    if result.backup:
        window.log(f"  backup: {result.backup}")
    for error in result.errors:
        window.log(f"*** update failed: {error} ***")
    window.refresh_open_deck_editors()
    remaining = compat.evaluate(window.project.root, app_version)
    if remaining.loud or result.errors:
        compat_report(window, remaining)
        QMessageBox.warning(
            window, "Update project",
            f"{len(result.changed)} file(s) updated. Some changes need work by hand; the "
            "report lists where, and has a prompt for an AI tool.")
    else:
        compat.acknowledge(window.project.root, app_version)
        QMessageBox.information(window, "Update project",
                                f"{len(result.changed)} file(s) updated. Backups are in "
                                ".slidemage/backups/.")


def on_project_compat(window) -> None:
    evaluation = compat.evaluate(window.project.root, version_mod.VERSION_NUMBER)
    show_compat(window, evaluation, review=True)


def on_open_version_history(window) -> None:
    AboutSheet(window).exec()


def on_check_for_updates(window) -> None:
    QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
    try:
        releases = updater.fetch_releases()
    except updater.UpdateError as exc:
        QMessageBox.warning(window, "Check for updates", str(exc))
        return
    finally:
        QApplication.restoreOverrideCursor()

    current = version_mod.VERSION_NUMBER
    plan = updater.plan_update(releases, current, need_asset=updater.can_self_update())
    if plan.latest is None:
        QMessageBox.information(
            window, "Check for updates", f"SlideMage {current} is up to date.")
        return
    if not updater.can_self_update():
        QMessageBox.information(
            window, "Update available",
            f"SlideMage {plan.latest.tag} is available (you have {current}).\n\n"
            "This copy runs from source, so it can't replace itself -- "
            f"update it with git pull, or download the release from:\n{plan.latest.page_url}",
        )
        return
    offer_update(window, plan, updater.get_update_mode(), manual=True)


def schedule_bundled_copies_check(window) -> None:
    QTimer.singleShot(BUNDLED_COPIES_CHECK_DELAY_MS, partial(check_bundled_copies, window))
    # Single-slide renders older than the cleanup setting (Settings -> General,
    # 24 hours by default, or Never) are deleted from the temp directory
    # (slide_preview.sweep_renders), off the GUI thread; the preview's render
    # worker sweeps again after every render.
    QTimer.singleShot(RENDER_SWEEP_DELAY_MS, partial(sweep_old_renders, window))


def sweep_old_renders(window) -> None:
    threading.Thread(target=slide_preview.sweep_renders, args=(window.project,), daemon=True).start()


def bundled_parts(window) -> list:
    """What the framework / manual copies of this project would get (bundled_copies.plan_updates)."""
    return bundled_copies.plan_updates(
        window.project.root, latex_source=project.template_dir("latex"),
        example_source=project.template_dir("example"))


def check_bundled_copies(window) -> None:
    app_version = version_mod.VERSION_NUMBER
    if bundled_copies.is_dismissed(window.project.root, app_version):
        return
    try:
        parts = bundled_parts(window)
    except OSError as exc:
        window.log(f"Couldn't compare the project's framework/manual copies: {exc}")
        return
    if not parts:
        return
    lines = [line for part in parts for line in bundled_copies.summary_lines(part)]
    box = QMessageBox(window)
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
        bundled_copies.dismiss(window.project.root, app_version)
        window.log(f"Framework/manual update for {app_version} declined; "
                 "not asking again until the next SlideMage version.")
        return
    if clicked is update_button:
        apply_bundled_parts(window, parts)


def apply_bundled_parts(window, parts: list) -> None:
    for part in parts:
        try:
            backup = bundled_copies.apply_update(window.project, part, version_mod.VERSION_NUMBER)
        except OSError as exc:
            QMessageBox.critical(window, "Update failed", f"{part.label}: {exc}")
            continue
        for line in bundled_copies.summary_lines(part):
            window.log(f"Updated -- {line}")
        if part.update or part.remove:
            window.log(f"  backup: {backup}")
    window.reload_decks()


def can_add_manual(window) -> bool:
    """Whether the SlideMage manual is not in this project and this copy carries it."""
    try:
        return any(part.new_install for part in bundled_parts(window))
    except OSError:
        return False


def on_add_manual(window) -> None:
    """Adds the SlideMage manual (bundled_copies, as the start-up offer does): its deck, slides,
    snippets and images; files that exist are never overwritten."""
    apply_bundled_parts(window, [part for part in bundled_parts(window) if part.new_install])


def schedule_startup_update_check(window) -> None:
    if not updater.can_self_update():
        return  # a copy run from source is updated with git
    if updater.get_update_mode() == updater.UPDATE_MODE_OFF:
        return
    QTimer.singleShot(STARTUP_UPDATE_CHECK_DELAY_MS, partial(startup_update_check, window))


def startup_update_check(window) -> None:
    def work() -> None:
        try:
            result = updater.plan_update(
                updater.fetch_releases(), version_mod.VERSION_NUMBER, need_asset=True)
        except updater.UpdateError as exc:
            result = exc
        window.update_check_done.emit(result)

    threading.Thread(target=work, daemon=True).start()


def on_startup_update_check_done(window, result) -> None:
    """Never a popup for a failed check or an up-to-date copy -- only
    the log, so an offline start stays quiet."""
    if isinstance(result, updater.UpdateError):
        window.log(f"Update check failed: {result}")
        return
    if result.latest is None:
        window.log(f"SlideMage {version_mod.VERSION_NUMBER} is up to date.")
        return
    mode = updater.get_update_mode()
    if mode == updater.UPDATE_MODE_OFF:
        return  # switched off while the check was running
    offer_update(window, result, mode, manual=False)


def offer_update(window, plan: updater.UpdatePlan, mode: str, manual: bool) -> None:
    """Offer (or, in "auto" mode, install) `plan.latest`. `manual` is
    Info → Check for updates…, which always asks with a plain Yes/No."""
    latest = plan.latest
    if latest is None:
        return
    if plan.breaking:
        choice = ask_breaking_update(window, plan)
        if choice == "install":
            download_and_install_update(window, latest)
        elif choice == "stay" and plan.safe is not None:
            if mode == updater.UPDATE_MODE_AUTO or confirm_safe_update(window, plan.safe):
                download_and_install_update(window, plan.safe)
        return
    if manual:
        reply = QMessageBox.question(
            window, "Update available",
            f"SlideMage {latest.tag} is available (you have "
            f"{version_mod.VERSION_NUMBER}).\n\nDownload it and replace this copy now?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if reply == QMessageBox.StandardButton.Yes:
            download_and_install_update(window, latest)
        return
    if mode == updater.UPDATE_MODE_AUTO:
        window.log(f"Installing SlideMage {latest.tag} (updates install automatically)")
        download_and_install_update(window, latest)
        return
    apply_update_choice(window, ask_update_choice(window, latest), latest)


def ask_update_choice(window, release: updater.Release) -> str:
    """"install", "later", "auto" or "off"."""
    box = QMessageBox(window)
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


def apply_update_choice(window, choice: str, release: updater.Release) -> None:
    if choice in ("auto", "off"):
        mode = updater.UPDATE_MODE_AUTO if choice == "auto" else updater.UPDATE_MODE_OFF
        try:
            updater.set_update_mode(mode)
        except OSError as exc:
            window.log(f"Couldn't save the update setting: {exc}")
        else:
            window.log(
                "Updates will be installed automatically (Settings → General)"
                if choice == "auto" else
                "SlideMage will no longer check for updates on start "
                "(Settings → General; Help → Check for updates… still works)")
    if choice in ("install", "auto"):
        download_and_install_update(window, release)
    elif choice == "later":
        window.log(f"SlideMage {release.tag} is available; not installed for now")


def ask_breaking_update(window, plan: updater.UpdatePlan) -> str:
    """"install", "stay" or "later" -- asked whatever the update mode."""
    latest = plan.latest
    current = version_mod.VERSION_NUMBER
    notes = [note for release in plan.breaking for note in updater.breaking_notes(release)]
    if not notes:
        notes = [
            f"The major version number changes ({current} → {latest.tag}); "
            f"see the release notes: {latest.page_url}"
        ]
    box = QMessageBox(window)
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


def confirm_safe_update(window, release: updater.Release) -> bool:
    reply = QMessageBox.question(
        window, "Update available",
        f"Install SlideMage {release.tag} instead? It has no breaking changes.",
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.Yes,
    )
    return reply == QMessageBox.StandardButton.Yes


def download_and_install_update(window, release: updater.Release) -> None:
    executable = Path(sys.executable)
    binary_name = updater.asset_names()[1]
    folder_build = updater.install_flavour() == updater.FOLDER
    staging: Optional[Path] = None
    progress = QProgressDialog(
        f"Downloading SlideMage {release.tag}…", "Cancel", 0, 0, window)
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
            if folder_build:
                staging = updater.stage_folder_update(zip_path, executable.parent, binary_name)
            else:
                updater.install_zip(zip_path, executable, binary_name)
        except updater.UpdateError as exc:
            progress.close()
            QMessageBox.warning(window, "Update failed", str(exc))
            return
    progress.close()

    reply = QMessageBox.question(
        window, "Update installed",
        f"SlideMage {release.tag} is {'ready to be installed in' if folder_build else 'installed in'} "
        f"{executable.parent}.\n\n"
        + ("Restart now to install and use it? (Otherwise it is installed when you close SlideMage.)"
           if folder_build else "Restart now to use it?"),
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.Yes,
    )
    restart = reply == QMessageBox.StandardButton.Yes
    if restart and window.compiling:
        QMessageBox.information(
            window, "Update installed",
            "A compile run is in progress -- restart SlideMage once it finishes.",
        )
        restart = False
    if folder_build and staging is not None:
        # The helper swaps the folders once this process has ended, and starts the new version when asked to.
        try:
            updater.spawn_folder_swap(executable.parent, staging, binary_name,
                                      ["--project", str(window.project.root)] if restart else None)
        except updater.UpdateError as exc:
            QMessageBox.warning(window, "Update failed", str(exc))
            return
        if restart:
            window.restart_after_update()
        return
    if restart:
        window.relaunch_with_project(window.project.root)


def housekeeping_sheet(window, page: int = LIST_PAGE) -> HousekeepingSheet:
    return HousekeepingSheet(window, HousekeepingJobs(
        partial(empty_pdf_folder, window), partial(remove_temp_files, window),
        partial(on_sync_translation_links, window)), page)


def on_housekeeping(window) -> None:
    sheet = housekeeping_sheet(window)
    sheet.exec()
    if sheet.update_previews:
        compile_actions.update_previews(window)


def empty_pdf_folder(window) -> None:
    files = housekeeping.pdf_files(window.project)
    if not files:
        QMessageBox.information(window, "Nothing to do", "pdf/ is already empty (or doesn't exist yet).")
        return
    reply = QMessageBox.question(window, "Empty folder", f"Delete all {len(files)} file(s) in pdf/?")
    if reply != QMessageBox.StandardButton.Yes:
        return
    housekeeping.delete_files(files)
    window.log(f"Emptied pdf/ ({len(files)} file(s) deleted)")


def remove_temp_files(window) -> None:
    if window.compiling:
        QMessageBox.information(
            window, "Busy", "Can't remove temp files while a compile run is in progress."
        )
        return
    found = housekeeping.find_temp_files(window.project)
    if not found:
        QMessageBox.information(window, "Nothing to do", "No temp files to remove.")
        return
    reply = QMessageBox.question(
        window,
        "Remove temp files",
        f"Delete {len(found.build)} build item(s) in .build/, "
        f"{len(found.wrappers)} leftover wrapper file(s) in decks/, and "
        f"{len(found.scratch)} item(s) in .temp/ (the workflow scratch "
        "folder -- e.g. a PPTX mid-conversion or an image waiting to "
        "be cropped -- not just build output)?",
    )
    if reply != QMessageBox.StandardButton.Yes:
        return
    housekeeping.remove_temp_files(window.project, found)
    window.log(
        f"Removed {found.count - len(found.scratch)} temp item(s) "
        f"({len(found.build)} build item(s) in .build/, "
        f"{len(found.wrappers)} wrapper file(s) in decks/) "
        f"and {len(found.scratch)} item(s) in .temp/"
    )


def on_archive_unused_content(window) -> None:
    """Opens the Housekeeping sheet on its archive review: it lists every file the scan
    found before anything is moved (2026-09-27, direct instruction, after a batch run
    archived far more than expected -- see unused_content.py)."""
    sheet = housekeeping_sheet(window, ARCHIVE_PAGE)
    sheet.exec()


def on_sync_translation_links(window) -> int:
    """Refreshes translation cross-reference comments from current
    disk state -- pure text scanning over slides/, no compile
    involved, so (unlike Update previews) this runs synchronously rather
    than on a background thread. Returns the number of files updated."""
    changed, missing = slide_rename.regenerate_translation_links(window.project)
    window.log(f"Sync translation links: {changed} file(s) updated")
    for line in missing:
        window.log(f"    (unresolved: {line})")
    if missing:
        QMessageBox.warning(
            window, "Sync translation links",
            f"{changed} file(s) updated. {len(missing)} link(s) could "
            "not be resolved -- see the log pane for details.",
        )
    return changed
