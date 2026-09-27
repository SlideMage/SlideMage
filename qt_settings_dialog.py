"""Settings dialog (2026-08-25, direct instruction): a "Settings" menu
holding cross-cutting app preferences that don't belong scattered across
individual toolbars -- dark mode (moved here from its own toolbar
checkbox in qt_gui.py), the default Ollama model per AI task (an "AI
models" tab, whose "Translation prompts…" button opens
TranslationPromptsDialog's own per-(model, source language, target
language) prompt configuration -- its own dialog since 2026-09-27, no
longer a permanent tab here), and (2026-08-25) an "Ollama models" tab to
delete models this app no longer needs -- genuinely from Ollama's own
local model store (alt_draft.delete_model(), its own DELETE /api/delete),
not just some SlideMage-side list.
"""
from __future__ import annotations

import threading

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from . import alt_draft
from . import app_settings
from .qt_slide_source_tab import DEFAULT_TAB_WIDTH_CHARS, TAB_WIDTH_SETTING_KEY
from .qt_translation_prompts_dialog import TranslationPromptsDialog


def _human_size(num_bytes: int) -> str:
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} {unit}"
        size /= 1024
    return f"{size:.1f} TB"  # unreachable, satisfies type checkers


class SettingsDialog(QDialog):
    # Carries a list[tuple[model, ok, error]] back to the GUI thread once a
    # background "Update selected…" (2026-09-18) finishes -- see
    # _on_ollama_model_update()/_update_ollama_models_bg()/
    # _on_ollama_update_finished(). Same per-instance Signal(object)
    # cross-thread pattern qt_transcript_tab.py's _ImageEditor.translation_done
    # already uses for its own backgrounded Ollama call.
    _ollama_update_done = Signal(object)

    def __init__(self, app) -> None:
        super().__init__(app)
        self.app = app
        self.setWindowTitle("Settings")
        self.resize(680, 520)

        self._ollama_update_done.connect(self._on_ollama_update_finished)

        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        layout.addWidget(tabs, stretch=1)
        tabs.addTab(self._build_general_tab(), "General")
        tabs.addTab(self._build_ai_models_tab(), "AI models")

        # Close only -- every change here (dark mode, a model default) is
        # applied and persisted immediately by its own control, same as
        # every other dialog in this app that edits durable state (e.g.
        # qt_transcript_tab.py's review panel) -- there is nothing to
        # "commit" on an OK button, and nothing a Cancel could sensibly
        # undo. (The translation-prompt forms that used to live in this
        # dialog and needed their own unsaved-changes check moved out to
        # TranslationPromptsDialog 2026-09-27, along with that check.)
        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    # -- General ----------------------------------------------------------

    def _build_general_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        self.dark_mode_checkbox = QCheckBox("Dark mode")
        self.dark_mode_checkbox.setChecked(self.app.theme.dark)
        self.dark_mode_checkbox.toggled.connect(self.app.set_dark_mode)
        layout.addWidget(self.dark_mode_checkbox)

        # Slide-source editor's own Tab-key width (2026-08-29, direct
        # instruction -- was hardcoded, see qt_slide_source_tab.py's own
        # DEFAULT_TAB_WIDTH_CHARS comment for why 80px-default-tab-stop was
        # worth changing at all). Applied immediately (like dark mode
        # above), not deferred to this dialog's Close button -- there's
        # nothing to "commit", same reasoning as every other control here.
        tab_width_row = QHBoxLayout()
        tab_width_row.addWidget(QLabel("Slide editor tab width (characters):"))
        self.tab_width_spin = QSpinBox()
        self.tab_width_spin.setRange(1, 16)
        self.tab_width_spin.setValue(
            app_settings.get(TAB_WIDTH_SETTING_KEY, DEFAULT_TAB_WIDTH_CHARS)
        )
        self.tab_width_spin.valueChanged.connect(self.app.set_tab_width_chars)
        tab_width_row.addWidget(self.tab_width_spin)
        tab_width_row.addStretch(1)
        layout.addLayout(tab_width_row)

        layout.addStretch(1)
        return page

    # -- AI models ------------------------------------------------------------

    def _build_ai_models_tab(self) -> QWidget:
        """Default Ollama model per AI task (2026-09-26, direct
        instruction; replaces the old "whatever was used last" behaviour),
        plus (2026-09-27, direct instruction: same tab, visually separated
        -- both sections are about the AI models SlideMage uses) the
        former separate "Ollama models" tab underneath a divider. Applied
        immediately, like every other control in this dialog. The dialogs
        that offer a model picker preselect the default chosen here;
        picking a different model there only affects that dialog."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(QLabel(
            "Default model for each AI task. Every dialog with a model picker "
            "starts on the model chosen here; picking another one there "
            "applies to that dialog only."
        ))
        all_models = alt_draft.list_all_models()
        vision_models = alt_draft.list_vision_models()
        form = QFormLayout()
        rows = (
            ("syntax_check", "Syntax check:", all_models),
            ("ai_draft", "AI drafting:", all_models),
            ("image_description", "Image descriptions (vision models):", vision_models),
            ("translation", "Translation:", all_models),
        )
        for task, label, models in rows:
            combo = QComboBox()
            combo.addItem("(none chosen -- built-in fallback)", "")
            for model in models:
                combo.addItem(model, model)
            saved = app_settings.default_model(task)
            if saved and combo.findData(saved) == -1:
                combo.addItem(f"{saved} (not installed)", saved)
            combo.setCurrentIndex(max(0, combo.findData(saved)))
            combo.activated.connect(
                lambda index, t=task, c=combo: app_settings.set(
                    app_settings.MODEL_SETTINGS[t], c.itemData(index) or ""))
            if task == "translation":
                # "Translation prompts…" (2026-09-27, direct instruction --
                # replaces this dialog's own former "Translation prompts"
                # tab) opens the per-(model, source, target) prompt editor
                # right next to the model this row picks a default for.
                row_widget = QHBoxLayout()
                row_widget.addWidget(combo, stretch=1)
                prompts_button = QPushButton("Translation prompts…")
                prompts_button.clicked.connect(self._on_translation_prompts)
                row_widget.addWidget(prompts_button)
                form.addRow(label, row_widget)
            else:
                form.addRow(label, combo)
        layout.addLayout(form)
        if not all_models:
            layout.addWidget(QLabel(
                "Ollama is not reachable at localhost:11434, or has no models installed."))

        # Visual separator (2026-09-27, direct instruction) -- a plain
        # QFrame horizontal rule plus a bold heading, so the "Ollama
        # models" section below reads as clearly distinct from the
        # per-task defaults above even though both live on one page now.
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(separator)
        heading = QLabel("<b>Ollama models</b>")
        layout.addWidget(heading)
        self._build_ollama_models_section(layout)
        return page

    def _on_translation_prompts(self) -> None:
        """"Translation prompts…" button, next to the Translation model
        picker (2026-09-27, direct instruction -- replaces this dialog's
        own former "Translation prompts" tab). Non-modal-in-spirit but a
        plain exec() is simplest here: nothing else in this dialog needs
        to keep working while it's open."""
        TranslationPromptsDialog(self, self.app).exec()

    # -- Ollama models (a section of the AI models tab, not its own tab) --------

    def _build_ollama_models_section(self, layout: QVBoxLayout) -> None:
        layout.addWidget(QLabel(
            "Every model currently installed in Ollama, drafting and "
            "translation alike. Deleting one here removes it from Ollama's "
            "own local model store -- its actual files on disk -- not just "
            "something SlideMage was tracking; there is nothing else to "
            "clean up. This can't be undone short of re-pulling the model.\n\n"
            "\"Update selected…\" re-pulls the latest weights for a plain "
            "model, or -- for one of this project's own custom models "
            "(built as a num_ctx/temperature variant of a base model, e.g. "
            "\"gemma4:64k\") -- pulls that base and relinks the custom "
            "model to it, since the custom tag itself has no registry entry "
            "to pull."
        ))

        self.ollama_models_list = QListWidget()
        # Multi-select (2026-08-26, direct instruction) -- ctrl/shift-click
        # to pick several, deleted together by one "Delete selected…" click
        # instead of one model at a time.
        self.ollama_models_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        layout.addWidget(self.ollama_models_list, stretch=1)

        button_row = QHBoxLayout()
        refresh_button = QPushButton("Refresh")
        refresh_button.clicked.connect(self._reload_ollama_models)
        button_row.addWidget(refresh_button)
        button_row.addStretch(1)
        self.ollama_update_button = QPushButton("Update selected…")
        self.ollama_update_button.setEnabled(False)
        self.ollama_update_button.clicked.connect(self._on_ollama_model_update)
        button_row.addWidget(self.ollama_update_button)
        self.ollama_delete_button = QPushButton("Delete selected…")
        self.ollama_delete_button.setEnabled(False)
        self.ollama_delete_button.clicked.connect(self._on_ollama_model_delete)
        button_row.addWidget(self.ollama_delete_button)
        layout.addLayout(button_row)

        self.ollama_models_list.itemSelectionChanged.connect(
            lambda: (
                self.ollama_delete_button.setEnabled(bool(self.ollama_models_list.selectedItems())),
                self.ollama_update_button.setEnabled(bool(self.ollama_models_list.selectedItems())),
            ))

        self._reload_ollama_models()

    def _reload_ollama_models(self) -> None:
        self.ollama_models_list.clear()
        models = alt_draft.list_installed_models_detailed()
        if not models:
            self.ollama_models_list.addItem("(Ollama not reachable, or no models installed)")
            self.ollama_models_list.setEnabled(False)
            self.ollama_delete_button.setEnabled(False)
            self.ollama_update_button.setEnabled(False)
            return
        self.ollama_models_list.setEnabled(True)
        for model in models:
            item = QListWidgetItem(f"{model.name}   —   {_human_size(model.size_bytes)}")
            item.setData(Qt.ItemDataRole.UserRole, model.name)
            self.ollama_models_list.addItem(item)
        self.ollama_delete_button.setEnabled(False)
        self.ollama_update_button.setEnabled(False)

    def _on_ollama_model_delete(self) -> None:
        models = [
            item.data(Qt.ItemDataRole.UserRole)
            for item in self.ollama_models_list.selectedItems()
        ]
        models = [model for model in models if model is not None]
        if not models:
            return

        # Uses the same app-wide Ollama mutex every drafting/translation
        # call goes through (qt_gui.py's try_start_ollama_task()) -- not
        # because deleting itself is an Ollama *inference* call, but to
        # refuse deleting a model out from under a draft/translate batch
        # that's actively using it. Held for the whole loop below (2026-08-26,
        # direct instruction: delete every selected model in one go), not
        # re-acquired per model.
        if not self.app.try_start_ollama_task(
            f"deleting {len(models)} model(s)" if len(models) > 1 else f"deleting {models[0]}"
        ):
            return
        try:
            if len(models) == 1:
                detail = f"Permanently delete \"{models[0]}\""
            else:
                detail = "Permanently delete these {} models:\n\n{}".format(
                    len(models), "\n".join(f"  • {m}" for m in models)
                )
            confirm = QMessageBox.question(
                self, "Delete Ollama model" + ("s" if len(models) > 1 else ""),
                f"{detail} from Ollama's local model store? This removes "
                "the file(s) from disk and cannot be undone short of "
                "re-pulling.\n\n"
                "Safe to do even if another installed model was created "
                "from one of these (e.g. via \"ollama create\") and shares "
                "its underlying files -- Ollama's own deletion only removes "
                "files no other installed model still references, exactly "
                "like the \"ollama rm\" command.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if confirm != QMessageBox.StandardButton.Yes:
                return

            self.ollama_delete_button.setEnabled(False)
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            try:
                failures: list[tuple[str, str]] = []
                deleted = 0
                for model in models:
                    ok, error = alt_draft.delete_model(model)
                    if ok:
                        deleted += 1
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
                f"Deleted {deleted} of {len(models)}. Failed:\n\n"
                + "\n".join(f"{model}: {error}" for model, error in failures),
            )
        self._reload_ollama_models()

    def _on_ollama_model_update(self) -> None:
        models = [
            item.data(Qt.ItemDataRole.UserRole)
            for item in self.ollama_models_list.selectedItems()
        ]
        models = [model for model in models if model is not None]
        if not models:
            return

        derived = [m for m in models if m in alt_draft.DERIVED_MODEL_BASES]
        note = ""
        if derived:
            plural = len(derived) > 1
            note = (
                "\n\nNote: " + ", ".join(derived) + (" are" if plural else " is") +
                " custom model(s) built on top of another base model -- "
                "updating " + ("them" if plural else "it") + " pulls and "
                "relinks to that base instead of pulling " +
                ("themselves" if plural else "itself") + " directly."
            )
        detail = (f'"{models[0]}"' if len(models) == 1 else
                   "these {} models:\n\n{}".format(
                       len(models), "\n".join(f"  • {m}" for m in models)))
        confirm = QMessageBox.question(
            self, "Update Ollama model" + ("s" if len(models) > 1 else ""),
            f"Update {detail} to the latest version?{note}\n\n"
            "This re-downloads the underlying weights (can be several GB "
            "per model and take a while) and cannot be cancelled once "
            "started.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return

        # Same app-wide Ollama mutex delete uses above -- refuses to start
        # a many-minute download out from under an active draft/translate
        # batch, and vice versa. Released from the worker thread itself
        # (see _update_ollama_models_bg() below), not from the GUI-thread
        # signal handler, so it's freed even if this dialog is closed
        # before the update finishes.
        if not self.app.try_start_ollama_task(
            f"updating {len(models)} model(s)" if len(models) > 1 else f"updating {models[0]}"
        ):
            return

        self.ollama_delete_button.setEnabled(False)
        self.ollama_update_button.setEnabled(False)
        self.ollama_models_list.setEnabled(False)
        threading.Thread(
            target=self._update_ollama_models_bg, args=(models,), daemon=True
        ).start()

    def _update_ollama_models_bg(self, models: list[str]) -> None:
        results: list[tuple[str, bool, str]] = []
        try:
            for model in models:
                self.app.signals.log.emit(f"Updating Ollama model {model}…")

                def progress(line: str) -> None:
                    self.app.signals.log.emit(line)

                ok, error = alt_draft.update_model(model, on_progress=progress)
                results.append((model, ok, error))
                if ok:
                    self.app.signals.log.emit(f"Updated Ollama model {model}")
                else:
                    self.app.signals.log.emit(f"Failed to update {model}: {error}")
        finally:
            self.app.end_ollama_task()
        try:
            self._ollama_update_done.emit(results)
        except RuntimeError:
            # This dialog was closed before the update finished -- nothing
            # left to update it with; the result is still in the log above,
            # not silently dropped, same as _ImageEditor.translation_done's
            # own equivalent guard in qt_transcript_tab.py.
            pass

    def _on_ollama_update_finished(self, results: list[tuple[str, bool, str]]) -> None:
        self.ollama_models_list.setEnabled(True)
        self._reload_ollama_models()
        failures = [(model, error) for model, ok, error in results if not ok]
        if failures:
            QMessageBox.critical(
                self, "Update failed",
                f"Updated {len(results) - len(failures)} of {len(results)}. Failed:\n\n"
                + "\n".join(f"{model}: {error}" for model, error in failures),
            )
