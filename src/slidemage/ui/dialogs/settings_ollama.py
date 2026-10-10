"""The Ollama tab of the Settings sheet: the server's address, and the models installed there --
update (pull) and delete, as `ollama pull` and `ollama rm` would (ai/ollama_admin.py).

Deleting removes a model from Ollama's own store, not from a list SlideMage keeps. Both actions take
the app-wide Ollama slot (`app.try_start_ollama_task`), so a model is not deleted or re-pulled under
a drafting or translation batch that is using it. An update runs on a thread that is not tied to the
sheet: it ends, and frees the slot, even when the sheet is closed meanwhile.
"""
from __future__ import annotations

import threading

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QAbstractItemView, QApplication, QLineEdit, QListWidget, QListWidgetItem, QMessageBox

from ... import app_settings, deck_snapshot
from ...ai import ollama_admin
from ...ai.providers import InstalledModel
from ..kit.widgets import Button, Field, Page, caption, row


class OllamaTab(Page):
    changed = Signal()            # the host or the installed models changed: ask Ollama again
    _update_done = Signal(object)  # [(model, ok, error)], from the update thread

    def __init__(self, app) -> None:
        super().__init__()
        self.app = app
        self.host_edit = QLineEdit(app_settings.get_ollama_host())
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
        self._update_done.connect(self._on_update_finished)
        self._sync_buttons()

    def fill(self, installed: list[InstalledModel]) -> None:
        self.models_list.clear()
        self.models_list.setEnabled(bool(installed))
        self.status.setText(
            f"{len(installed)} model(s) installed." if installed else
            f"Ollama is not reachable at {app_settings.get_ollama_host()}, or has no models installed.")
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
        app_settings.set_ollama_host(self.host_edit.text())
        # Re-read rather than trust the raw field: an empty entry clears the override, so this shows
        # the effective host ($OLLAMA_HOST or the plain default).
        self.host_edit.setText(app_settings.get_ollama_host())
        self.app.log(f"Ollama host set to {app_settings.get_ollama_host()}")
        self.changed.emit()

    def _on_delete(self) -> None:
        models = self.selected()
        if not models:
            return
        what = f"deleting {len(models)} model(s)" if len(models) > 1 else f"deleting {models[0]}"
        if not self.app.try_start_ollama_task(what):
            return
        try:
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
                return
            self.delete_button.setEnabled(False)
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            try:
                failures = []
                for model in models:
                    ok, error = ollama_admin.delete_model(model)
                    if ok:
                        self.app.log(f"Deleted Ollama model {model}")
                    else:
                        failures.append((model, error or "Unknown error"))
            finally:
                QApplication.restoreOverrideCursor()
        finally:
            self.app.end_ollama_task()
        if failures:
            QMessageBox.critical(
                self, "Delete failed",
                f"Deleted {len(models) - len(failures)} of {len(models)}. Failed:\n\n"
                + "\n".join(f"{model}: {error}" for model, error in failures))
        self.changed.emit()

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
        self.update_button.setEnabled(False)
        self.delete_button.setEnabled(False)
        self.models_list.setEnabled(False)
        threading.Thread(target=self._update_models, args=(models,), daemon=True).start()

    def _update_models(self, models: list[str]) -> None:
        results: list[tuple[str, bool, str]] = []
        try:
            for model in models:
                self.app.signals.log.emit(f"Updating Ollama model {model}…")
                ok, error = ollama_admin.update_model(model, on_progress=self.app.signals.log.emit)
                results.append((model, ok, error))
                self.app.signals.log.emit(
                    f"Updated Ollama model {model}" if ok else f"Failed to update {model}: {error}")
        finally:
            self.app.end_ollama_task()      # freed here, so closing the sheet cannot keep the slot
        try:
            self._update_done.emit(results)
        except RuntimeError:
            pass        # the sheet was closed before the update finished; the result is in the log

    def _on_update_finished(self, results: list[tuple[str, bool, str]]) -> None:
        self.models_list.setEnabled(True)
        self.changed.emit()
        failures = [(model, error) for model, ok, error in results if not ok]
        if failures:
            QMessageBox.critical(
                self, "Update failed",
                f"Updated {len(results) - len(failures)} of {len(results)}. Failed:\n\n"
                + "\n".join(f"{model}: {error}" for model, error in failures))
