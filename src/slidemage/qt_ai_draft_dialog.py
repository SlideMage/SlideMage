""""AI draft" dialog (2026-08-31, direct instruction) -- an open, free-text
prompt describing a change, sent with the slide's current buffer to a
local Ollama model (ai_draft.py), shown here as a line-level diff against
the real original. Nothing touches the editor until "Accept" is clicked;
"Generate" can be run again first (a fresh prompt, a different model, or
just retrying) with no commitment either way.

Non-modal, same reasoning as SyntaxCheckDialog: staying open alongside a
clickable editor is the point, not a limitation -- reading a proposed
rewrite is much easier with the real slide still visible/scrollable
underneath.

ai_draft.py's own mask/unmask machinery is what makes "Accept" defensible
at all despite this being an open, unverifiable rewrite: the model never
sees this slide's header metadata, \\setSlideVersion{} line, or any
\\vbox to 0pt{...} absolute-overlay block, and a proposal missing,
duplicating, or inventing one of those placeholders is refused entirely
(result.ok is False) before it ever reaches this dialog. That does not
make the *rest* of a proposal trustworthy -- ordinary slide content is
still an open rewrite from a local model, hence the diff view and the
explicit Accept gate.
"""
from __future__ import annotations

import difflib

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QSyntaxHighlighter, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from . import ai_draft, alt_draft, app_settings
from .qt_theme import MUTED_LABEL


class _DiffHighlighter(QSyntaxHighlighter):
    """Colors difflib.ndiff() output by its own 2-char line prefix -- "+ "
    added, "- " removed, everything else (including "  " unchanged)
    plain. "? " intraline-hint lines are filtered out by the caller
    before this ever sees the text, not handled here."""

    def __init__(self, document) -> None:
        super().__init__(document)
        self._added = QTextCharFormat()
        self._added.setBackground(QColor(30, 90, 40))
        self._removed = QTextCharFormat()
        self._removed.setBackground(QColor(100, 35, 35))

    def highlightBlock(self, text: str) -> None:
        if text.startswith("+ "):
            self.setFormat(0, len(text), self._added)
        elif text.startswith("- "):
            self.setFormat(0, len(text), self._removed)


class AiDraftDialog(QDialog):
    def __init__(self, source_tab, filename: str) -> None:
        super().__init__(source_tab)
        self.app = source_tab.app
        self.source_tab = source_tab
        self.filename = filename
        self._proposed_text: str | None = None
        self._proposal_baseline: str | None = None
        self.setWindowTitle(f"AI draft — {filename}")
        self.setModal(False)
        self.resize(760, 560)
        self._build()

    # -- widgets ------------------------------------------------------------------

    def _build(self) -> None:
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("Describe the change you want:"))
        self.prompt_edit = QPlainTextEdit()
        self.prompt_edit.setFixedHeight(70)
        self.prompt_edit.setPlaceholderText(
            'e.g. "Add a third bullet point comparing X and Y" or '
            '"Rephrase the second item to be more concise"'
        )
        layout.addWidget(self.prompt_edit)

        model_row = QHBoxLayout()
        model_row.addWidget(QLabel("Model:"))
        self.model_combo = QComboBox()
        self.refresh_model_preference()
        self.model_combo.activated.connect(self._on_model_selected)
        model_row.addWidget(self.model_combo)
        self.generate_button = QPushButton("Generate")
        self.generate_button.clicked.connect(self._on_generate)
        model_row.addWidget(self.generate_button)
        model_row.addStretch(1)
        layout.addLayout(model_row)

        self.status_label = QLabel(
            "Protected: this slide's own header comment, \\setSlideVersion{}, and "
            "every \\vbox to 0pt{...} absolute-overlay block are hidden from the "
            "model and restored afterward -- it can propose changes to everything "
            "else. Nothing is applied until you click Accept."
        )
        self.status_label.setObjectName(MUTED_LABEL)
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.diff_view = QPlainTextEdit()
        self.diff_view.setReadOnly(True)
        self.diff_view.setFont(self.source_tab.widget.font())
        self._diff_highlighter = _DiffHighlighter(self.diff_view.document())
        layout.addWidget(self.diff_view, stretch=1)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        self.accept_button = QPushButton("Accept")
        self.accept_button.setToolTip(
            "Replace this editor's entire buffer with the proposal above, as "
            "one Undo step."
        )
        self.accept_button.setEnabled(False)
        self.accept_button.clicked.connect(self._on_accept)
        button_row.addWidget(self.accept_button)
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.close)
        button_row.addWidget(close_button)
        layout.addLayout(button_row)

    def refresh_model_preference(self, models: list[str] | None = None) -> None:
        """Select the Other AI default from the available models."""
        if models is None:
            models = alt_draft.list_all_models()
        self.model_combo.clear()
        self.model_combo.addItems(models or ["(no Ollama models installed)"])
        self.model_combo.setEnabled(bool(models))
        remembered = app_settings.get_other_model()
        if remembered in models:
            self.model_combo.setCurrentText(remembered)

    def _on_model_selected(self, index: int) -> None:
        app_settings.set("other_model", self.model_combo.itemText(index))

    # -- generate ------------------------------------------------------------

    def _on_generate(self) -> None:
        prompt = self.prompt_edit.toPlainText().strip()
        if not prompt:
            QMessageBox.critical(self, "AI draft", "Describe what you want changed first.")
            return
        model = self.model_combo.currentText()
        if not model or model.startswith("("):
            QMessageBox.critical(self, "AI draft", "No Ollama models are installed.")
            return
        if not self.app.try_start_ollama_task("drafting a slide revision"):
            return

        self._proposed_text = None
        self._proposal_baseline = None
        self.accept_button.setEnabled(False)
        self.diff_view.clear()
        self.generate_button.setEnabled(False)
        disclaimer = (
            "Review carefully -- a local model can misunderstand LaTeX structure, "
            "invent content, or make plausible-looking but wrong changes."
        )
        self.status_label.setText(f"Generating with {model}… {disclaimer}")
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            current_text = self.source_tab.widget.toPlainText()
            drafter = ai_draft.OllamaSlideDrafter(model=model)
            result = drafter.draft(current_text, prompt)
        finally:
            QApplication.restoreOverrideCursor()
            self.generate_button.setEnabled(True)
            self.app.end_ollama_task()

        if not result.ok:
            self.status_label.setText(f"Draft failed: {result.error}")
            return

        if result.proposed_text == current_text:
            self.status_label.setText(
                f"{result.model} proposed no changes ({result.elapsed_s:.0f}s). "
                "Try rephrasing the request."
            )
            return

        self._proposed_text = result.proposed_text
        self._proposal_baseline = current_text
        diff_lines = [
            line for line in difflib.ndiff(
                current_text.splitlines(), result.proposed_text.splitlines())
            if not line.startswith("? ")
        ]
        self.diff_view.setPlainText("\n".join(diff_lines))
        self.status_label.setText(
            f"Proposed by {result.model} ({result.elapsed_s:.0f}s). {disclaimer} "
            "Nothing is applied until you click Accept."
        )
        self.accept_button.setEnabled(True)

    # -- accept ------------------------------------------------------------

    def _on_accept(self) -> None:
        if self._proposed_text is None or self._proposal_baseline is None:
            return
        if self.source_tab.widget.toPlainText() != self._proposal_baseline:
            # The dialog is nonmodal, so the source editor can change after
            # this diff was generated. Refuse to apply a whole-buffer
            # proposal whose displayed baseline no longer matches the live
            # document; the user can Generate again against the new text.
            self.accept_button.setEnabled(False)
            self.status_label.setText(
                "The source changed after this proposal was generated. "
                "Nothing was applied; generate a fresh proposal to review "
                "changes against the current source."
            )
            return
        cursor = self.source_tab.widget.textCursor()
        cursor.beginEditBlock()
        cursor.select(QTextCursor.SelectionType.Document)
        cursor.insertText(self._proposed_text)
        cursor.endEditBlock()
        self.source_tab.widget.setTextCursor(cursor)
        self.app.log(f"Applied an AI-drafted revision to {self.filename}")
        self.accept_button.setEnabled(False)
        self.status_label.setText(
            "Applied. Ctrl+Z in the editor undoes this. You can Generate again for "
            "another revision."
        )
