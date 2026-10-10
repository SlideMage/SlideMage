""""AI draft" dialog (2026-08-31, direct instruction) -- an open, free-text
prompt describing a change, sent with the slide's current buffer to a
local Ollama model (ai_draft.py), shown here as a line-level diff against
the real original. Nothing touches the editor until "Accept" is clicked;
"Generate" can be run again first (a fresh prompt, a different model, or
just retrying) with no commitment either way.

Non-modal: staying open alongside a
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
from PySide6.QtGui import QColor, QSyntaxHighlighter, QTextCharFormat
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

from . import ai_draft
from .ai.providers import OllamaProvider
from .qt_ai_models import fill_model_combo, provider_from_combo
from .ui.kit.theme import MUTED_LABEL
from .ui.workspace.source_editor import source_font


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
    def __init__(self, app, editor, filename: str) -> None:
        """`editor` is the SourceEditor (ui/workspace/source_editor.py) the draft is for."""
        super().__init__(app)
        self.app = app
        self.editor = editor
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
        # Preselects the default from Settings -> "AI models"; a different
        # pick here applies to this dialog only.
        self.refresh_model_preference()
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
        self.diff_view.setFont(source_font())
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
        """(Re)fill the model picker and preselect the default from
        Settings -> "AI models" -- on construction, and again from
        the main window after the Settings dialog closes, so a default changed
        there (or a model deleted) reaches this dialog while it's open."""
        if models is None:
            models = OllamaProvider().list_models()
        fill_model_combo(self.model_combo, "ai_draft", models, "(no AI models available)")

    # -- generate ------------------------------------------------------------

    def _on_generate(self) -> None:
        prompt = self.prompt_edit.toPlainText().strip()
        if not prompt:
            QMessageBox.critical(self, "AI draft", "Describe what you want changed first.")
            return
        provider = provider_from_combo(
            self, self.model_combo, "this slide's full LaTeX source and your request")
        if provider is None:
            return
        if not self.app.try_start_ollama_task("drafting a slide revision", provider):
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
        self.status_label.setText(f"Generating with {provider.label}… {disclaimer}")
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            current_text = self.editor.text()
            drafter = ai_draft.SlideDrafter(provider)
            result = drafter.draft(current_text, prompt)
        finally:
            QApplication.restoreOverrideCursor()
            self.generate_button.setEnabled(True)
            self.app.end_ollama_task(provider)

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
        if self.editor.text() != self._proposal_baseline:
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
        self.editor.replace_all_text(self._proposed_text)
        self.app.log(f"Applied an AI-drafted revision to {self.filename}")
        self.accept_button.setEnabled(False)
        self.status_label.setText(
            "Applied. Ctrl+Z in the editor undoes this. You can Generate again for "
            "another revision."
        )
