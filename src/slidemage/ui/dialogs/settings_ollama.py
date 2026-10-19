# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The Ollama tab of the Settings sheet: the server's address, and the models installed there --
update (pull) and delete, as `ollama pull` and `ollama rm` would (ai/ollama_admin.py).

Deleting removes a model from Ollama's own store, not from a list SlideMage keeps. Both actions take
the app-wide Ollama slot (`app.try_start_ollama_task`), so a model is not deleted or re-pulled under
a drafting or translation batch that is using it. Both run on a thread (ui/background) that is not
tied to the sheet: it ends, and frees the slot, even when the sheet is closed meanwhile.
"""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtWidgets import QAbstractItemView, QLineEdit, QListWidget, QListWidgetItem, QMessageBox

from ... import app_settings, deck_snapshot
from ...ai import ollama_admin
from ...ai.providers import InstalledModel
from .. import background
from ..kit.widgets import Button, Field, Page, caption, row

Results = list[tuple[str, bool, str]]      # (model, ok, error)


class _AdminWorker(QThread):
    """Runs `work()` (model administration calls, which can take minutes) and reports what it returned; the
    tab hears back whatever happens."""

    done = Signal(object)

    def __init__(self, work: Callable[[], Results]) -> None:
        super().__init__()
        self._work = work

    def run(self) -> None:
        try:
            results = self._work()
        except Exception as exc:  # noqa: BLE001 -- the list must be enabled again
            results = [("the request", False, f"{type(exc).__name__}: {exc}")]
        self.done.emit(results)


class OllamaTab(Page):
    changed = Signal()            # the host or the installed models changed: ask Ollama again

    def __init__(self, app) -> None:
        super().__init__()
        self.app = app
        self.host_edit = QLineEdit(app_settings.get_ollama_host(self.app.project))
        self.host_edit.setPlaceholderText("http://localhost:11434")
        self.host_edit.editingFinished.connect(self._on_host)
        refresh = Button("Refresh", compact=True)
        refresh.clicked.connect(self.changed)
        self.body.addWidget(Field("Ollama address", row(self.host_edit, refresh)))
        self.status = caption("")
        self.body.addWidget(self.status)

        self.models_list = QListWidget()
        self.models_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.models_list.setMinimumHeight(190)
        self.models_list.itemSelectionChanged.connect(self._sync_buttons)
        self.body.addWidget(Field("Installed models", self.models_list))
        self.update_button = Button("Update selected…", compact=True)
        self.update_button.clicked.connect(self._on_update)
        self.delete_button = Button("Delete selected…", compact=True)
        self.delete_button.clicked.connect(self._on_delete)
        self.body.addWidget(row(caption(
            "Update pulls the latest weights (a custom model you built with ollama create is relinked to "
            "its refreshed base). Delete removes the files from disk and cannot be undone short of "
            "pulling the model again."), self.update_button, self.delete_button))
        self.body.addStretch(1)
        self._sync_buttons()

    def fill(self, installed: list[InstalledModel]) -> None:
        self.models_list.clear()
        self.models_list.setEnabled(bool(installed))
        self.status.setText(
            f"{len(installed)} model(s) installed." if installed else
            f"Ollama is not reachable at {app_settings.get_ollama_host(self.app.project)}, or has no models installed.")
        for model in installed:
            item = QListWidgetItem(f"{model.name}   —   {deck_snapshot.format_size(model.size_bytes)}"
                                   + ("   (vision)" if "vision" in model.capabilities else ""))
            item.setData(Qt.ItemDataRole.UserRole, model.name)
            self.models_list.addItem(item)
        self._sync_buttons()

    def selected(self) -> list[str]:
        return [item.data(Qt.ItemDataRole.UserRole) for item in self.models_list.selectedItems()]

    def _sync_buttons(self) -> None:
        has = bool(self.selected()) and self.models_list.isEnabled()
        self.update_button.setEnabled(has)
        self.delete_button.setEnabled(has)

    def _on_host(self) -> None:
        app_settings.set_ollama_host(self.app.project, self.host_edit.text())
        # Re-read rather than trust the raw field: an empty entry clears the override, so this shows
        # the effective host ($OLLAMA_HOST or the plain default).
        self.host_edit.setText(app_settings.get_ollama_host(self.app.project))
        self.app.log(f"Ollama host set to {app_settings.get_ollama_host(self.app.project)}")
        self.changed.emit()

    def _on_delete(self) -> None:
        models = self.selected()
        if not models:
            return
        what = f"deleting {len(models)} model(s)" if len(models) > 1 else f"deleting {models[0]}"
        if not self.app.try_start_ollama_task(what):
            return
        detail = (f'"{models[0]}"' if len(models) == 1 else
                  f"these {len(models)} models:\n\n" + "\n".join(f"  • {m}" for m in models))
        confirm = QMessageBox.question(
            self, "Delete Ollama model" + ("s" if len(models) > 1 else ""),
            f"Permanently delete {detail} from Ollama's local model store? This removes the file(s) from "
            "disk and cannot be undone short of pulling the model again.\n\n"
            "Safe even if another installed model was created from one of these (ollama create) and "
            "shares its files: like \"ollama rm\", Ollama only removes files no other installed model "
            "still references.")
        if confirm != QMessageBox.StandardButton.Yes:
            self.app.end_ollama_task()
            return
        self._run(lambda: self._delete_models(models), "Deleted", "Delete failed")

    def _delete_models(self, models: list[str]) -> Results:
        results: Results = []
        try:
            for model in models:
                ok, error = ollama_admin.delete_model(model, app_settings.get_ollama_host(self.app.project))
                results.append((model, ok, error or "Unknown error"))
                if ok:
                    self.app.log(f"Deleted Ollama model {model}")
        finally:
            self.app.end_ollama_task()      # freed here, so closing the sheet cannot keep the slot
        return results

    def _on_update(self) -> None:
        models = self.selected()
        if not models:
            return
        detail = (f'"{models[0]}"' if len(models) == 1 else
                  f"these {len(models)} models:\n\n" + "\n".join(f"  • {m}" for m in models))
        confirm = QMessageBox.question(
            self, "Update Ollama model" + ("s" if len(models) > 1 else ""),
            f"Update {detail} to the latest version?\n\n"
            "This re-downloads the underlying weights (can be several GB per model and take a while) and "
            "cannot be cancelled once started.")
        if confirm != QMessageBox.StandardButton.Yes:
            return
        if not self.app.try_start_ollama_task(
                f"updating {len(models)} model(s)" if len(models) > 1 else f"updating {models[0]}"):
            return
        self._run(lambda: self._update_models(models), "Updated", "Update failed")

    def _update_models(self, models: list[str]) -> Results:
        results: Results = []
        try:
            for model in models:
                self.app.log(f"Updating Ollama model {model}…")
                ok, error = ollama_admin.update_model(model, app_settings.get_ollama_host(self.app.project),
                                                    on_progress=self.app.log)
                results.append((model, ok, error))
                self.app.log(
                    f"Updated Ollama model {model}" if ok else f"Failed to update {model}: {error}")
        finally:
            self.app.end_ollama_task()
        return results

    def _run(self, work: Callable[[], Results], done: str, failed_title: str) -> None:
        """Start `work` on a thread of its own with the list locked; `done` ("Deleted") and `failed_title`
        word the message about the models it failed for."""
        self.update_button.setEnabled(False)
        self.delete_button.setEnabled(False)
        self.models_list.setEnabled(False)
        worker = _AdminWorker(work)
        worker.done.connect(lambda results: self._on_finished(results, done, failed_title))
        background.start_detached(worker)

    def _on_finished(self, results: Results, done: str, failed_title: str) -> None:
        self.models_list.setEnabled(True)
        self.changed.emit()
        failures = [(model, error) for model, ok, error in results if not ok]
        if failures:
            QMessageBox.critical(
                self, failed_title,
                f"{done} {len(results) - len(failures)} of {len(results)}. Failed:\n\n"
                + "\n".join(f"{model}: {error}" for model, error in failures))
