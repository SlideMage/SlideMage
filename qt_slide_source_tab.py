"""Phase 6 of the PySide6 migration (see PYSIDE6_MIGRATION.md): the slide
(and deck-source) editor tab -- ports slide_source_tab.py's SlideSourceTab
onto Qt widgets. slide_source.py (read_slide_source/save_slide_source) and
slide_preview.py (call_for_slide_path/render_slide_text_to_pdf/open_pdf)
are reused completely unchanged.

QSyntaxHighlighter is a genuine improvement over the Tk version's own
approach, not just a port: Tk's _highlight() re-scans the *entire* buffer
on every keystroke (deliberately, per that module's own docstring --
"cheap enough at slide-file sizes... rather than debounce or highlight
incrementally"). QSyntaxHighlighter instead re-runs highlightBlock() only
for the text block(s) that actually changed, automatically, so there's no
equivalent tradeoff to make here at all.
"""
from __future__ import annotations

import re
import string
import threading
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import (
    QFont,
    QFontMetricsF,
    QKeySequence,
    QPainter,
    QShortcut,
    QSyntaxHighlighter,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
    QColor,
)
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from . import (
    alt_images, app_settings, bibliography, slide_language, slide_preview,
    slide_rename, slide_snapshot, slide_source, slide_versioning, transcript,
)
from .qt_ai_draft_dialog import AiDraftDialog
from .qt_duplicate_slide_dialog import DuplicateSlideDialog
from .qt_syntax_check_dialog import SyntaxCheckDialog
from .qt_slide_preview_popup import SlidePreviewPopup
from .qt_theme import CLOSE_BUTTON, FORMAT_TOOLBAR, MUTED_LABEL, WARNING_LABEL

# Same three base regexes as slide_source_tab.py, unchanged -- see that
# module's own comments for the escaping/comment-boundary caveats (not
# repeated here to avoid the two copies drifting in wording, not in
# behavior). The rest (ENV_RE/MATH_RE/TODO_RE) are new -- QSyntaxHighlighter
# re-runs highlightBlock() only for changed blocks (unlike the Tk version's
# whole-buffer rescan), so richer per-block highlighting costs nothing extra
# here that wasn't already being paid.
COMMENT_RE = re.compile(r"(?<!\\)%.*")
COMMAND_RE = re.compile(r"\\[a-zA-Z]+\*?|\\.")
BRACE_RE = re.compile(r"(?<!\\)[{}]")
ENV_RE = re.compile(r"\\(?:begin|end)\{([a-zA-Z*]+)\}")
MATH_RE = re.compile(r"(?<!\\)\$[^$]*\$")
TODO_RE = re.compile(r"\b(?:TODO|FIXME|XXX)\b")
HEADER_COMMENT_LINE_RE = re.compile(r"^\s*%")

# "Reindent" button (2026-08-31, direct instruction) -- deliberately only
# `\begin{}`/`\end{}` line-start tokens, the same scope LatexPlainTextEdit's
# own smart-Enter feature already commits to (see that class's own
# _BEGIN_ENV_RE comment): a full brace-nesting indenter would also have to
# reason about braces inside math/macro arguments, which this project's
# slide content uses constantly and unpredictably (\textcolor{}{}, nested
# \footnote{\fullcite{}}, tikz node options, ...). Environment nesting
# alone is unambiguous and matches every slide file's own real convention
# throughout this project: the frame's own \begin{standardframe}{...} sits
# flush left, its body one tab in, a nested \begin{itemize} one tab deeper
# still, etc.
_REINDENT_BEGIN_RE = re.compile(r"^\\begin\{")
_REINDENT_END_RE = re.compile(r"^\\end\{")


def reindent_latex(text: str) -> str:
    """Recompute every line's own leading whitespace from its \\begin{}/
    \\end{} nesting depth (one tab per level), leaving the rest of each
    line -- and blank lines, left truly empty rather than tab-filled --
    untouched. A line already *at* \\end{} dedents before its own indent
    is assigned, so it lines up with its own \\begin{}, not the level
    inside it; depth is clamped at 0 rather than going negative if the
    text has an unmatched \\end{} (a real bug elsewhere in the file, not
    something this should crash over or otherwise amplify).

    A pure function (Qt-free) so it can be unit-tested directly against
    real slide content -- qt_slide_source_tab.py's own _on_reindent() is
    just the thin Qt-buffer/undo-step wrapper around this.
    """
    depth = 0
    out_lines = []
    for line in text.split("\n"):
        content = line.strip()
        if not content:
            out_lines.append("")
            continue
        content = line.lstrip(" \t")
        if _REINDENT_END_RE.match(content):
            depth = max(0, depth - 1)
        out_lines.append(("\t" * depth) + content)
        if _REINDENT_BEGIN_RE.match(content):
            depth += 1
    return "\n".join(out_lines)


SOURCE_FONT = QFont("Consolas", 10)

# Qt's own QPlainTextEdit default (80px, unrelated to any particular
# font's own character width) rendered a Tab about 6 characters wide with
# SOURCE_FONT -- far more indentation than intended for a code-style
# editor (direct instruction, 2026-08-28). 2 characters' worth is the
# fallback when nothing is saved yet; settable from here on (2026-08-29,
# direct instruction) via the Settings dialog's General tab
# (qt_settings_dialog.py), stored under this same app_settings.py key.
DEFAULT_TAB_WIDTH_CHARS = 2
TAB_WIDTH_SETTING_KEY = "tab_width_chars"


def _tab_stop_distance_px() -> float:
    """The current tab-width setting (app_settings.py, falling back to
    DEFAULT_TAB_WIDTH_CHARS if never saved), converted to pixels via
    SOURCE_FONT's own metrics rather than a hardcoded pixel count, so it
    stays exactly N characters wide regardless of SOURCE_FONT's own
    family/size."""
    chars = app_settings.get(TAB_WIDTH_SETTING_KEY, DEFAULT_TAB_WIDTH_CHARS)
    return QFontMetricsF(SOURCE_FONT).horizontalAdvance(" ") * chars

VERSIONS = ["instructor", "during-course", "after-course"]
VERSION_LABELS = {
    "instructor": "Instructor",
    "during-course": "During-course",
    "after-course": "After-course",
}

# "Multilingual" (not "Bilingual") in the combo, "mult" in the actual
# id-slug -- see Slidemaster_preamble_base.tex's \setSlideLanguageFromSlug
# and slide_language.LANGUAGES for why: a third language later only needs
# a new entry here, not a renaming pass.
_LANGUAGE_COMBO_TO_CODE = {"(untagged)": None, "EN": "EN", "DE": "DE", "Multilingual": "mult"}
_LANGUAGE_CODE_TO_COMBO = {code: label for label, code in _LANGUAGE_COMBO_TO_CODE.items() if code}

_TEXTCOLOR_CATEGORY_ORDER = {"custom": 0, "primary": 1, "secondary": 2, "tertiary": 3}


def _textcolor_sort_key(name: str) -> tuple[int, str]:
    category = name.split("_")[1]
    return (_TEXTCOLOR_CATEGORY_ORDER[category], name)


TEXTCOLOR_PALETTE = sorted(
    [
        "c_primary_dark", "c_primary_highlight", "c_primary_gray", "c_primary_white",
        "c_secondary_violet", "c_tertiary_violet", "c_secondary_blue", "c_tertiary_blue",
        "c_secondary_green", "c_tertiary_green", "c_secondary_red", "c_tertiary_red",
        "c_secondary_orange", "c_tertiary_orange", "c_secondary_yellow", "c_tertiary_yellow",
        "c_tertiary_gray", "c_custom_gray", "c_custom_red", "c_custom_green",
    ],
    key=_textcolor_sort_key,
)
COLOR_COMBO_PLACEHOLDER = "Text color..."

# Actual \definecolor{...}{HTML}{...} values from Slidemaster_preamble_
# uni-graz.tex -- the preamble nearly every real deck in this project
# \inputs (confirmed by grep: only test-ibk.tex/test-mci.tex use the
# uni-ibk/mci variants, everything else uses uni-graz). A few of these
# names resolve to a *different* hex per institution, so this swatch set
# is an approximation for whichever deck a slide actually compiles under
# -- close enough to be useful as a picker preview, not a guarantee of
# the exact rendered color for every deck.
TEXTCOLOR_SWATCHES = {
    "c_primary_dark": "#000000",
    "c_primary_highlight": "#ffd500",
    "c_primary_gray": "#c6c6c6",
    "c_primary_white": "#ffffff",
    "c_secondary_violet": "#948dc3",
    "c_tertiary_violet": "#c2bddf",
    "c_secondary_blue": "#689cce",
    "c_tertiary_blue": "#bacce8",
    "c_secondary_green": "#9fcb81",
    "c_tertiary_green": "#cce2ba",
    "c_secondary_red": "#e4684b",
    "c_tertiary_red": "#f1ae95",
    "c_secondary_orange": "#f6a968",
    "c_tertiary_orange": "#fbd0aa",
    "c_secondary_yellow": "#ffe063",
    "c_tertiary_yellow": "#ffeeaf",
    "c_tertiary_gray": "#e3e3e3",
    "c_custom_gray": "#333333",
    "c_custom_red": "#c00000",
    "c_custom_green": "#00b050",
}


def _contrasting_text_color(hex_color: str) -> QColor:
    """Black or white, whichever reads better on hex_color -- standard
    relative-luminance threshold, same idea as WCAG's contrast heuristic
    (good enough for picking legible combo-item text, not a strict
    conformance calculation)."""
    hex_color = hex_color.lstrip("#")
    r, g, b = (int(hex_color[i : i + 2], 16) / 255 for i in (0, 2, 4))
    luminance = 0.2126 * r + 0.7152 * g + 0.0722 * b
    return QColor("black") if luminance > 0.5 else QColor("white")

# Each entry is (display label, kind, payload):
#   "literal"  -- payload is None; the label itself is inserted verbatim
#                 (replacing the selection if any), via
#                 _replace_selection_or_insert.
#   "wrap_macro" -- payload is a macro name (no braces); wraps the
#                   selection as \{payload}{selection}, or inserts
#                   \{payload}{} with the cursor in between, via
#                   _wrap_or_insert -- same as the toolbar's Italic/Bold/
#                   Text-color buttons.
#   "wrap_env" -- payload is an environment name; wraps the selection
#                 between \begin{payload}/\end{payload} lines, or inserts
#                 an empty one with the cursor on its own line in between,
#                 via _wrap_environment.
#   "wrap_multilingual" -- payload is a two-argument macro name; with a
#                           selection, wraps it into the *first* braces
#                           (assumed English, matching \multilingualtext's
#                           own {EN}{DE} argument order) and leaves the
#                           cursor in the empty second braces ready for the
#                           translation; with no selection, both brace
#                           pairs are empty and the cursor lands in the
#                           first one -- via _insert_multilingual.
INSERT_COMMANDS = [
    ("\\conditionalpause[instructor]", "literal", None),
    ("\\only<2->{...}", "wrap_macro", "only<2->"),
    ("\\tallitem", "literal", None),
    ("\\tallitemnobullet", "literal", None),
    ("\\begin{itemize}...\\end{itemize}", "wrap_env", "itemize"),
    ("\\multilingualtext{EN}{DE}", "wrap_multilingual", "multilingualtext"),
]
COMMAND_COMBO_PLACEHOLDER = "Insert command..."


class LatexSyntaxHighlighter(QSyntaxHighlighter):
    def __init__(self, document, theme) -> None:
        super().__init__(document)
        self.theme = theme
        self._formats: dict[str, QTextCharFormat] = {}
        self.refresh_colors()

    def refresh_colors(self) -> None:
        """Call after a dark/light toggle -- rebuilds the tag colors from
        the current theme, then forces every block to re-highlight."""
        colors = self.theme.syntax_colors()

        def make_format(color_key: str, *, bold: bool = False, italic: bool = False) -> QTextCharFormat:
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(colors[color_key]))
            if bold:
                fmt.setFontWeight(QFont.Weight.Bold)
            if italic:
                fmt.setFontItalic(True)
            return fmt

        self._formats = {
            "comment": make_format("comment", italic=True),
            "command": make_format("command"),
            "brace": make_format("brace"),
            "env": make_format("env", bold=True),
            "math": make_format("math"),
            "todo": make_format("todo", bold=True),
        }
        self.rehighlight()

    def highlightBlock(self, text: str) -> None:
        comment_spans = [m.span() for m in COMMENT_RE.finditer(text)]

        def in_comment(pos: int) -> bool:
            return any(start <= pos < end for start, end in comment_spans)

        # Math and \begin/\end{env} are only meaningful outside comments;
        # checked before comment/command/brace below so those don't paint
        # over the more specific formats here.
        for m in MATH_RE.finditer(text):
            if not in_comment(m.start()):
                self.setFormat(m.start(), m.end() - m.start(), self._formats["math"])
        for m in ENV_RE.finditer(text):
            if not in_comment(m.start()):
                self.setFormat(m.start(), m.end() - m.start(), self._formats["command"])
                self.setFormat(m.start(1), m.end(1) - m.start(1), self._formats["env"])

        for m in COMMAND_RE.finditer(text):
            if not in_comment(m.start()):
                self.setFormat(m.start(), m.end() - m.start(), self._formats["command"])
        for m in BRACE_RE.finditer(text):
            if not in_comment(m.start()):
                self.setFormat(m.start(), m.end() - m.start(), self._formats["brace"])

        # Comments (and TODO/FIXME/XXX within them) painted last so they
        # always win over whatever a comment's own text happens to contain
        # (e.g. a literal "{" in a commented-out line).
        for start, end in comment_spans:
            self.setFormat(start, end - start, self._formats["comment"])
        for start, end in comment_spans:
            for m in TODO_RE.finditer(text, start, end):
                self.setFormat(m.start(), m.end() - m.start(), self._formats["todo"])


class _LineNumberArea(QWidget):
    """The gutter widget itself -- all sizing and painting lives on the
    editor it belongs to (LatexPlainTextEdit), which knows the blocks."""

    def __init__(self, editor: "LatexPlainTextEdit") -> None:
        super().__init__(editor)
        self._editor = editor

    def sizeHint(self) -> QSize:
        return QSize(self._editor.line_number_area_width(), 0)

    def paintEvent(self, event) -> None:
        self._editor.paint_line_numbers(event)


class LatexPlainTextEdit(QPlainTextEdit):
    """Line numbers (2026-09-19, direct instruction): a gutter down the
    left edge, numbering real file lines -- a line hidden by the header
    fold is skipped, not renumbered around, so numbers always match the
    file (and e.g. TeX's own "l.123" error lines).

    Smart Enter key (2026-08-31, direct instruction): a new line always
    continues its predecessor's own leading whitespace (tabs -- matching
    this project's own indentation convention throughout slides/, never
    spaces), and pressing Enter right at the end of a `\\begin{ENV}` line
    additionally opens the matching `\\end{ENV}` on the line below, at the
    *same* indentation as `\\begin{}` itself, with the cursor left on its
    own line in between, one tab deeper -- pre-seeded with `\\item ` when
    ENV is `itemize`/`enumerate`, since a bare list environment is never
    useful without at least one item to start typing into.

    Only fires when `\\begin{ENV}` is the very last thing on its own line
    (cursor at the block's end) -- a `\\begin{}` typed mid-line (rare, but
    possible while editing existing content) falls back to plain
    indentation-continuation instead, since splicing a second `\\end{}`
    into the middle of a line would corrupt it rather than complete it.
    """

    # No trailing "$" anchor -- a \begin{ENV} is very often followed by its
    # own brace/bracket arguments on the same line (\begin{standardframe}
    # {Title}, \begin{figureframe}[c]{Title}, a title itself containing
    # further nested braces like \footnote{\fullcite{key}}...) that this
    # deliberately makes no attempt to brace-match. Detecting just the
    # opening `\begin{ENV}` token, combined with the cursor.atBlockEnd()
    # check below (Enter pressed at the true end of *whatever* is on this
    # line), is enough to know "this line opens ENV" without needing to
    # parse the rest of the line at all.
    _BEGIN_ENV_RE = re.compile(r"\\begin\{([A-Za-z*]+)\}")
    _LIST_ENVIRONMENTS = {"itemize", "enumerate"}
    # \item-continuation (2026-08-31, direct instruction): checked only
    # after the \begin{ENV} trigger above finds nothing, so a line like
    # "\item \begin{itemize}" (an item that itself opens a nested list)
    # still gets the more specific begin/end handling, not this one.
    _ITEM_LINE_RE = re.compile(r"^\\item\b")

    def __init__(self, theme=None) -> None:
        super().__init__()
        # Colors are read from the theme at paint time, so a dark/light
        # toggle is picked up on the next repaint with nothing to refresh.
        self._theme = theme
        self._line_area = _LineNumberArea(self)
        self.blockCountChanged.connect(self._update_line_area_width)
        self.updateRequest.connect(self._update_line_area)
        self.cursorPositionChanged.connect(self._line_area.update)
        self._update_line_area_width()

    # -- line numbers -----------------------------------------------------------

    def line_number_area_width(self) -> int:
        digits = max(3, len(str(max(1, self.blockCount()))))
        return 8 + self.fontMetrics().horizontalAdvance("9") * digits

    def _update_line_area_width(self, _new_block_count: int = 0) -> None:
        self.setViewportMargins(self.line_number_area_width(), 0, 0, 0)

    def _update_line_area(self, rect: QRect, dy: int) -> None:
        if dy:
            self._line_area.scroll(0, dy)
        else:
            self._line_area.update(0, rect.y(), self._line_area.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self._update_line_area_width()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        area = self.contentsRect()
        self._line_area.setGeometry(
            QRect(area.left(), area.top(), self.line_number_area_width(), area.height()))

    def paint_line_numbers(self, event) -> None:
        colors = self._theme.colors if self._theme is not None else {}
        painter = QPainter(self._line_area)
        painter.fillRect(event.rect(), QColor(colors.get("panel_bg", "#eeeeee")))
        painter.setFont(self.font())
        height = self.fontMetrics().height()
        width = self._line_area.width() - 4
        current = self.textCursor().blockNumber()
        normal = QColor(colors.get("muted_fg", "#888888"))
        strong = QColor(colors.get("fg", "#000000"))

        block = self.firstVisibleBlock()
        number = block.blockNumber()
        top = round(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        bottom = top + round(self.blockBoundingRect(block).height())
        while block.isValid() and top <= event.rect().bottom():
            # isVisible() is False for a line hidden by the header fold; it
            # takes no height, and is skipped without shifting the numbers.
            if block.isVisible() and bottom >= event.rect().top():
                painter.setPen(strong if number == current else normal)
                painter.drawText(0, top, width, height, Qt.AlignmentFlag.AlignRight, str(number + 1))
            block = block.next()
            top = bottom
            bottom = top + round(self.blockBoundingRect(block).height())
            number += 1

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self._smart_return():
            return
        super().keyPressEvent(event)

    def _smart_return(self) -> bool:
        cursor = self.textCursor()
        if cursor.hasSelection():
            return False  # let the default Enter (replace selection) happen
        block_text = cursor.block().text()
        indent = re.match(r"[ \t]*", block_text).group(0)
        content = block_text[len(indent):]

        if cursor.atBlockEnd():
            # Last match, not first -- on the rare line with more than one
            # \begin{} token, the one most recently typed (rightmost) is
            # the one Enter is actually completing.
            matches = list(self._BEGIN_ENV_RE.finditer(block_text))
            if matches:
                env = matches[-1].group(1)
                inner_indent = indent + "\t"
                item_line = (
                    f"{inner_indent}\\item " if env in self._LIST_ENVIRONMENTS else inner_indent
                )
                insert_pos = cursor.position()
                cursor.beginEditBlock()
                cursor.insertText(f"\n{item_line}\n{indent}\\end{{{env}}}")
                cursor.endEditBlock()
                # Land the cursor right at the end of item_line -- between
                # the two newlines this just inserted -- not wherever
                # insertText() itself left it (the very end of \end{env}).
                cursor.setPosition(insert_pos + 1 + len(item_line))
                self.setTextCursor(cursor)
                return True

            if self._ITEM_LINE_RE.match(content):
                # Same indentation as the \item line itself, not one level
                # deeper -- sibling items in one list, not nested content.
                cursor.insertText(f"\n{indent}\\item ")
                self.setTextCursor(cursor)
                return True

        cursor.insertText("\n" + indent)
        self.setTextCursor(cursor)
        return True


class SlideSourceTab(QWidget):
    """Also used, unmodified, for a deck's own raw .tex source (see
    qt_gui.py's open_deck_source_editor) -- `path` need not live under
    slides/ at all. Render-to-PDF only makes sense for an actual
    slides/*.tex file, so it's built only when
    slide_preview.call_for_slide_path(path) actually resolves."""

    def __init__(
        self,
        app,
        path: Path,
        on_saved: Optional[Callable[[str], None]] = None,
        return_to: Optional[QWidget] = None,
    ) -> None:
        super().__init__()
        self.app = app
        self.path = path
        self.on_saved = on_saved
        self.return_to = return_to
        try:
            _macro, _id_slug, _version = slide_preview.call_for_slide_path(path)
            self._is_slide = True
            # The bare id (e.g. "dsk" from "dsk-Reference-Point-..."), used
            # everywhere a slide's *identity* matters rather than the macro
            # argument needed to \input{} it -- slide_snapshot.py's own
            # cache keys, and now this slide's transcript summary too.
            self._slide_bare_id = slide_snapshot.bare_id(_id_slug)
            # Automatic version-bump-on-save (slide_versioning.py) only
            # ever applies to a slide's own *current.tex -- a frozen
            # "-vX-Y-Z.tex" file opened and saved directly (a rare, manual
            # edit-history path) has no "current version" to bump, so it
            # just saves plainly like any non-slide file. _macro is
            # "slide" only for the -current.tex case (call_for_slide_path
            # returns "slideversion" for a version file).
            self._is_current_slide = _macro == "slide"
            self._slide_id_slug = _id_slug
        except ValueError:
            self._is_slide = False
            self._slide_bare_id = ""
            self._is_current_slide = False
            self._slide_id_slug = ""

        # Only Slidemaster.bib itself gets the citation-key jump bar below
        # -- this same tab class also opens a deck's raw .tex source (see
        # this class's own docstring), where an A-Z-by-first-letter jump
        # would be meaningless.
        self._is_bib = path == bibliography.DEFAULT_BIB

        self.text, self.eol = slide_source.read_slide_source(path)
        self._dirty = False

        # Whether the render bar's "Render language:" control is worth
        # showing: this slide is tagged "mult" (the whole point of that
        # tag), or its text reads \ifgothamGerman via \multilingualtext{}{}
        # somewhere anyway (a legacy untagged slide that happens to use the
        # macro). Initial value only -- _update_render_language_visibility()
        # (2026-08-25) recomputes this from *live* state after a rename or
        # a save, since the first version of this (computed once here and
        # never again) needed a close/reopen to notice a same-session
        # EN -> mult rename or a freshly-typed \multilingualtext{}{} call.
        self._slide_has_multilingual_text = (
            "\\multilingualtext" in self.text
            or (self._is_slide and slide_language.own_language(self._slide_id_slug) == "mult")
        )

        outer = QVBoxLayout(self)

        # Top bar: Save/Revert/Find, this slide's own identity (Duplicate,
        # the language badge + rename control), and Close. Render-related
        # controls (Preview/Render to PDF/Render transcript and their
        # dropdowns) live in their own bar below (2026-08-25, direct
        # instruction) -- a visually separate row from "does something to
        # THIS file" vs. "does something with a compiled/derived view of
        # it".
        toolbar = QHBoxLayout()
        save_button = QPushButton("Save")
        save_button.clicked.connect(self._on_save)
        toolbar.addWidget(save_button)

        self.revert_button = QPushButton("Revert")
        self.revert_button.setEnabled(False)
        self.revert_button.clicked.connect(self._on_revert)
        toolbar.addWidget(self.revert_button)

        find_button = QPushButton("Find")
        find_button.setToolTip(
            "Search this editor's text (Ctrl+F). Next/Previous wrap around "
            "at the end/start of the buffer; Escape closes the bar."
        )
        find_button.clicked.connect(self._show_find_bar)
        toolbar.addWidget(find_button)

        if self._is_slide:
            reindent_button = QPushButton("Reindent")
            reindent_button.setToolTip(
                "Recompute every line's leading indentation from its "
                "\\begin{}/\\end{} nesting depth (one tab per level) -- "
                "fixes drifted/mixed indentation throughout the whole "
                "buffer. Only touches leading whitespace; one Undo step."
            )
            reindent_button.clicked.connect(self._on_reindent)
            toolbar.addWidget(reindent_button)

        if not self._is_bib:
            check_syntax_button = QPushButton("Check syntax")
            check_syntax_button.setToolTip(
                "Ask a local Ollama model to look for LaTeX syntax problems "
                "in this editor's current buffer (unbalanced braces, "
                "mismatched \\begin{}/\\end{}, unescaped special "
                "characters, ...) and, where it can confidently write one, "
                "offer a one-click fix for the exact line it's looking at. "
                "A heuristic check, not a real LaTeX compile."
            )
            check_syntax_button.clicked.connect(self._on_check_syntax)
            toolbar.addWidget(check_syntax_button)

        if self._is_slide:
            ai_draft_button = QPushButton("AI draft")
            ai_draft_button.setToolTip(
                "Describe a change in an open prompt and let a local Ollama "
                "model propose a full revision of this slide's source, shown "
                "as a diff -- nothing is applied until you click Accept. This "
                "slide's own header comment, \\setSlideVersion{}, and any "
                "\\vbox to 0pt{...} absolute-overlay block are hidden from "
                "the model and restored afterward, untouched."
            )
            ai_draft_button.clicked.connect(self._on_ai_draft)
            toolbar.addWidget(ai_draft_button)

        if self._is_current_slide:
            self.duplicate_button = QPushButton("Duplicate slide")
            self.duplicate_button.setToolTip(
                "Create a new slide seeded from this one's saved content -- "
                "either a plain same-language copy, or a cross-referenced "
                "translation into another language (with an optional "
                "machine-translation pass)."
            )
            self.duplicate_button.clicked.connect(self._on_duplicate_slide)
            toolbar.addWidget(self.duplicate_button)

        if self._is_slide:
            # Language badge + rename control (2026-08-24) -- only for
            # -current.tex (mirrors the version-bump dialog's own
            # self._is_current_slide gating: a frozen -vX-Y-Z.tex snapshot
            # is never renamed). The combo always starts on whatever the
            # filename currently encodes ("(untagged)" for a legacy
            # slide); picking a different value and clicking "Set" calls
            # slide_rename.set_slide_language() -- a real rename that
            # rewrites every deck reference, so it's deliberately a
            # separate action with its own confirmation dialog rather than
            # silently folded into the version-bump Save dialog. Saving
            # while the combo is left on some other value than this
            # slide's actual current language does still offer to run it,
            # though (_maybe_apply_pending_language_change(), 2026-08-29)
            # -- otherwise a picked-but-never-"Set" combo value would
            # silently do nothing and just keep lying about the slide's
            # real language.
            self.language_badge_label = QLabel("")
            self.language_badge_label.setObjectName(MUTED_LABEL)
            toolbar.addWidget(self.language_badge_label)
            if self._is_current_slide:
                toolbar.addWidget(QLabel("Language:"))
                self.set_language_combo = QComboBox()
                self.set_language_combo.addItems(["(untagged)", "EN", "DE", "Multilingual"])
                toolbar.addWidget(self.set_language_combo)
                self.set_language_button = QPushButton("Set")
                self.set_language_button.clicked.connect(self._on_set_language)
                toolbar.addWidget(self.set_language_button)
                self._refresh_language_controls()

        close_button = QPushButton("Close")
        close_button.setObjectName(CLOSE_BUTTON)
        close_button.clicked.connect(self._on_close)
        toolbar.addWidget(close_button)

        self.close_save_button = QPushButton("Close and save")
        self.close_save_button.setObjectName(CLOSE_BUTTON)
        self.close_save_button.setEnabled(False)
        self.close_save_button.clicked.connect(self._on_close_and_save)
        toolbar.addWidget(self.close_save_button)

        self.dirty_label = QLabel("")
        self.dirty_label.setObjectName(WARNING_LABEL)
        toolbar.addWidget(self.dirty_label)
        toolbar.addStretch()
        outer.addLayout(toolbar)

        # Citation-key jump bar (Slidemaster.bib only, direct instruction):
        # one button per letter: A-Z, jump to the first entry (already
        # alphabetically sorted -- see qt_gui.py's _on_edit_bib/
        # close_slide_editor_tab, which run bibliography.sort_entries() on
        # open/close of this exact tab) whose citation key starts with it.
        if self._is_bib:
            jump_bar = QHBoxLayout()
            jump_bar.addWidget(QLabel("Jump to:"))
            for letter in string.ascii_uppercase:
                letter_button = QPushButton(letter)
                letter_button.setFixedWidth(32)
                letter_button.clicked.connect(
                    lambda checked=False, ltr=letter: self._jump_to_bib_letter(ltr)
                )
                jump_bar.addWidget(letter_button)
            jump_bar.addStretch()
            outer.addLayout(jump_bar)

        # Render bar (2026-08-25, direct instruction): every control that
        # produces a compiled/derived *view* of this slide rather than
        # acting on the file itself -- Preview (cached), the version/
        # language pickers, Render to PDF, Render transcript.
        if self._is_slide:
            render_bar = QHBoxLayout()

            self.preview_button = QPushButton("Preview")
            self.preview_button.setToolTip(
                "Show the cached compile-time preview (instant, but only as "
                "current as the last real compile of the saved file -- not "
                "this editor's unsaved changes, if any). \"Render now\" "
                "inside it refreshes that cache."
            )
            self.preview_button.clicked.connect(self._on_preview)
            render_bar.addWidget(self.preview_button)

            render_bar.addWidget(QLabel("Render version:"))
            self.version_combo = QComboBox()
            self.version_combo.addItems([VERSION_LABELS[v] for v in VERSIONS])
            render_bar.addWidget(self.version_combo)

            # One-off render language (2026-08-24) -- same scope/lifetime
            # as version_combo above, never persisted: lets a
            # \multilingualtext{}{} ("mult") slide be spot-checked in
            # either language without needing a real deck file. Row hidden
            # (2026-08-25) unless this slide's own text actually reads
            # \multilingualtext{}{} anywhere (_slide_has_multilingual_text,
            # computed once at open) -- for an ordinary EN/DE-tagged slide
            # the render never actually differs by language, so the
            # control has nothing to do. Still defaults to this slide's
            # own tagged language (not just "EN") when hidden, so a DE-
            # tagged slide's "Render to PDF"/"Render transcript" send the
            # right \decklanguage[...] even though the picker itself is
            # never shown.
            self.render_language_label = QLabel("Render language:")
            render_bar.addWidget(self.render_language_label)
            self.render_language_combo = QComboBox()
            self.render_language_combo.addItems(["EN", "DE"])
            self.render_language_combo.setToolTip(
                "Language for this one-off render only (mainly matters for a "
                "multilingual/\"mult\" slide's own \\multilingualtext{}{} "
                "switch) -- not saved, not tied to any deck."
            )
            own_language_for_render = (
                slide_language.own_language(self._slide_id_slug) if self._is_slide else None
            )
            if own_language_for_render == "DE":
                self.render_language_combo.setCurrentText("DE")
            render_bar.addWidget(self.render_language_combo)
            self.render_language_label.setVisible(self._slide_has_multilingual_text)
            self.render_language_combo.setVisible(self._slide_has_multilingual_text)

            self.render_button = QPushButton("Render to PDF")
            self.render_button.setToolTip(
                "Compile this editor's current buffer, unsaved changes "
                "included -- opens the real PDF. Does not update the "
                "cached Preview (that only reflects the saved file)."
            )
            self.render_button.clicked.connect(self._on_render)
            render_bar.addWidget(self.render_button)

            self.transcript_button = QPushButton("Render transcript")
            self.transcript_button.setToolTip(
                "Render this editor's current buffer, unsaved changes "
                "included, as a one-slide transcript preview -- opens in "
                "its own review tab. Uses the version/language above; "
                "silently substitutes the during-course version if "
                "\"Instructor\" is selected (transcripts don't exist for "
                "that version at all). Nothing is written to disk."
            )
            self.transcript_button.clicked.connect(self._on_render_transcript)
            render_bar.addWidget(self.transcript_button)

            render_bar.addStretch()
            outer.addLayout(render_bar)

        # Free text for this slide's *transcript* entry -- not tied to any
        # image, so it doesn't belong in the Images tab's per-image cards.
        # Lives in media/alt-text.json (alt_images.SlideNotes), not in the
        # .tex file, so it has its own Save button and its own dirty
        # tracking entirely separate from the source buffer's.
        if self._is_slide:
            summary_row = QHBoxLayout()
            # AlignTop on the label/button -- QHBoxLayout otherwise
            # vertically centers each item against the row's tallest
            # widget (summary_edit's own fixed 50px height), which read as
            # the label/button floating below the field's own top edge
            # (direct instruction, 2026-08-17: top-align them with it).
            # summary_edit itself needs no alignment flag: at its fixed
            # height it already defines the row's height, so it has no
            # extra space to be centered/top-aligned within to begin with.
            summary_row.addWidget(
                QLabel("Transcript summary:"), alignment=Qt.AlignmentFlag.AlignTop
            )
            self.summary_edit = QPlainTextEdit()
            self.summary_edit.setFixedHeight(50)
            self.summary_edit.setPlaceholderText(
                "Optional -- shown at the top of this slide's transcript "
                "entry, before its body text. Leave blank for none."
            )
            self.summary_edit.setPlainText(alt_images.load_slide_notes().get(
                self._slide_bare_id, alt_images.SlideNotes()).summary)
            # Connected *after* the initial setPlainText, same reasoning as
            # the main editor's own modificationChanged connection below --
            # loading the slide must not itself mark this dirty.
            self.summary_edit.textChanged.connect(self._on_summary_changed)
            summary_row.addWidget(self.summary_edit, stretch=1)
            self.save_summary_button = QPushButton("Save summary")
            self.save_summary_button.setEnabled(False)
            self.save_summary_button.clicked.connect(self._on_save_summary)
            summary_row.addWidget(self.save_summary_button, alignment=Qt.AlignmentFlag.AlignTop)
            outer.addLayout(summary_row)

        # Second toolbar row -- text-formatting/insertion shortcuts. Wrapped
        # in its own QWidget (not just a bare QHBoxLayout, which has no
        # objectName a QSS selector could target) so it can be styled
        # distinctly from the Save/Revert/... row above it.
        format_toolbar_container = QWidget()
        format_toolbar_container.setObjectName(FORMAT_TOOLBAR)
        format_toolbar = QHBoxLayout(format_toolbar_container)
        format_toolbar.setContentsMargins(4, 4, 4, 4)
        # Each button's own label is rendered in the style it applies --
        # italic I, bold B, underlined U -- so the toolbar doubles as a
        # legend for what it does.
        for label, prefix, width, font_trait in (
            ("I", "textit", 32, "italic"),
            ("B", "textbf", 32, "bold"),
            ("U", "underline", 32, "underline"),
            ("Tt", "texttt", 32, None),
        ):
            button = QPushButton(label)
            button.setFixedWidth(width)
            button.clicked.connect(lambda checked=False, p=prefix: self._wrap_or_insert(p))
            if font_trait is not None:
                font = QFont(button.font())
                if font_trait == "italic":
                    font.setItalic(True)
                elif font_trait == "bold":
                    font.setBold(True)
                elif font_trait == "underline":
                    font.setUnderline(True)
                button.setFont(font)
            format_toolbar.addWidget(button)
        for label, prefix in (("Source", "source"), ("Footnote", "footnote")):
            button = QPushButton(label)
            button.clicked.connect(lambda checked=False, p=prefix: self._wrap_or_insert(p))
            format_toolbar.addWidget(button)

        # Comment/Uncomment (direct instruction) -- unlike the I/B/U/Tt
        # buttons above, this doesn't wrap the selection in a LaTeX macro;
        # it toggles a leading "%" on every *line* the selection touches.
        comment_button = QPushButton("%")
        comment_button.setFixedWidth(32)
        comment_button.setToolTip("Comment/uncomment selected lines (Ctrl+/)")
        comment_button.clicked.connect(self._on_toggle_comment)
        format_toolbar.addWidget(comment_button)

        self.color_combo = QComboBox()
        self.color_combo.addItems([COLOR_COMBO_PLACEHOLDER] + TEXTCOLOR_PALETTE)
        # Swatch the popup list itself with each color's actual (uni-graz)
        # value -- background, not the combo's own text/chrome, per
        # explicit instruction -- so picking a color is "click the one
        # that looks right" rather than reading names off a plain list.
        for i, name in enumerate(TEXTCOLOR_PALETTE, start=1):
            hex_color = TEXTCOLOR_SWATCHES[name]
            self.color_combo.setItemData(i, QColor(hex_color), Qt.ItemDataRole.BackgroundRole)
            self.color_combo.setItemData(
                i, _contrasting_text_color(hex_color), Qt.ItemDataRole.ForegroundRole
            )
        # activated (not currentIndexChanged/currentTextChanged) only
        # fires on an actual user pick, never on the programmatic
        # setCurrentIndex(0) reset below -- so, unlike the Tk version
        # (which had to reason about <<ComboboxSelected>> only firing on a
        # value *change*), there's no risk of the reset itself re-
        # triggering this handler.
        self.color_combo.activated.connect(self._on_color_selected)
        format_toolbar.addWidget(self.color_combo)

        self.command_combo = QComboBox()
        self.command_combo.addItems(
            [COMMAND_COMBO_PLACEHOLDER] + [label for label, _, _ in INSERT_COMMANDS]
        )
        self.command_combo.activated.connect(self._on_command_selected)
        format_toolbar.addWidget(self.command_combo)
        format_toolbar.addStretch()
        outer.addWidget(format_toolbar_container)

        # Find bar -- hidden until Ctrl+F/the "Find" toolbar button opens
        # it (_show_find_bar). Sits directly below the formatting bar and
        # above the (possibly folded) header-comment block (2026-08-25,
        # direct instruction: previously below the fold toggle, which put
        # it right against the text area instead of reading as its own
        # distinct row) -- "search within this buffer" regardless of what
        # kind of file is loaded (a slide, a deck source, or
        # Slidemaster.bib via the "Tabs -> Edit .bib" menu action).
        self.find_bar = QWidget()
        find_layout = QHBoxLayout(self.find_bar)
        find_layout.setContentsMargins(4, 4, 4, 4)
        find_layout.addWidget(QLabel("Find:"))
        self.find_entry = QLineEdit()
        self.find_entry.returnPressed.connect(self._on_find_next)
        find_layout.addWidget(self.find_entry, stretch=1)
        self.find_status_label = QLabel("")
        self.find_status_label.setObjectName(MUTED_LABEL)
        find_layout.addWidget(self.find_status_label)
        find_prev_button = QPushButton("Previous")
        find_prev_button.clicked.connect(self._on_find_previous)
        find_layout.addWidget(find_prev_button)
        find_next_button = QPushButton("Next")
        find_next_button.clicked.connect(self._on_find_next)
        find_layout.addWidget(find_next_button)
        find_close_button = QPushButton("Close")
        find_close_button.clicked.connect(self._hide_find_bar)
        find_layout.addWidget(find_close_button)
        self.find_bar.setVisible(False)
        outer.addWidget(self.find_bar)

        # The leading "% Converted from ... / v1-N-0 ..." history block many
        # slide files carry (see CONVERSION_NOTES.md) can run to 30+ lines
        # before the actual \slide{}-family call -- collapsed by default so
        # opening a slide shows the actual code first, with a toggle to
        # bring it back.
        self._header_fold_line_count = self._count_header_comment_lines()
        if self._header_fold_line_count > 0:
            self.fold_button = QPushButton()
            self.fold_button.setFlat(True)
            self.fold_button.setStyleSheet("text-align: left; border: none;")
            self.fold_button.clicked.connect(self._toggle_header_fold)
            outer.addWidget(self.fold_button)

        # WidgetWithChildrenShortcut (not the default WindowShortcut) --
        # several SlideSourceTab instances can be open in the same
        # QMainWindow at once, and WindowShortcut would make Ctrl+F
        # ambiguous between them regardless of which tab is actually
        # focused. Scoped to `self`, so it fires as long as focus is
        # anywhere inside this tab (the text buffer, or the find bar
        # itself if already open).
        find_shortcut = QShortcut(QKeySequence.StandardKey.Find, self)
        find_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        find_shortcut.activated.connect(self._show_find_bar)
        # Escape only closes the bar while the find entry itself has focus
        # (WidgetShortcut, the narrowest context) -- this tab has no other
        # use for a bare Escape, but scoping it this tightly means it can
        # never fire while the user is just typing/editing normally.
        find_escape_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Escape), self.find_entry)
        find_escape_shortcut.setContext(Qt.ShortcutContext.WidgetShortcut)
        find_escape_shortcut.activated.connect(self._hide_find_bar)

        # Comment/Uncomment shortcut (direct instruction) -- Ctrl+/ is the
        # de facto standard binding for this action across editors (VS
        # Code, Sublime, ...); same WidgetWithChildrenShortcut scoping as
        # Ctrl+F above, for the same multi-tab-ambiguity reason.
        comment_shortcut = QShortcut(QKeySequence("Ctrl+/"), self)
        comment_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        comment_shortcut.activated.connect(self._on_toggle_comment)

        self.widget = LatexPlainTextEdit(self.app.theme)
        self.widget.setFont(SOURCE_FONT)
        self.widget.setTabStopDistance(_tab_stop_distance_px())
        self.widget.setPlainText(self.text)
        self.highlighter = LatexSyntaxHighlighter(self.widget.document(), self.app.theme)
        self.widget.document().setModified(False)
        self.widget.document().modificationChanged.connect(self._set_dirty)
        self.widget.cursorPositionChanged.connect(self._highlight_matching_brace)
        outer.addWidget(self.widget)

        if self._header_fold_line_count > 0:
            self._set_header_folded(True)

    def refresh_tab_width(self) -> None:
        """Called from qt_gui.py's set_tab_width_chars() on every already-
        open tab -- the same live-refresh pattern set_dark_mode() already
        uses for highlighter.refresh_colors(), since this tab's own
        tabStopDistance was baked in from app_settings.py at __init__ time
        and needs an explicit nudge to pick up a value changed afterward
        from the Settings dialog."""
        self.widget.setTabStopDistance(_tab_stop_distance_px())

    # -- actions --------------------------------------------------------------------

    @staticmethod
    def _selected_text(cursor: QTextCursor) -> str:
        """QTextCursor.selectedText() uses U+2029 (paragraph separator) in
        place of a real newline for any selection spanning multiple lines
        -- undocumented-looking but is Qt's documented behavior. Left
        unconverted, a multi-line Bold/Italic/color/environment wrap would
        silently write that Unicode character into the saved .tex file in
        place of the newlines that were there before."""
        return cursor.selectedText().replace("\u2029", "\n")

    def _wrap_or_insert(self, prefix: str) -> None:
        """If text is currently selected, wrap it in \\{prefix}{...};
        otherwise insert \\{prefix}{} with the cursor placed between the
        braces. beginEditBlock()/endEditBlock() coalesce the
        setPosition()+insertText() pair into one atomic undo step, the Qt
        equivalent of the Tk version's own .replace()-based guarantee."""
        cursor = self.widget.textCursor()
        cursor.beginEditBlock()
        if not cursor.hasSelection():
            token = f"\\{prefix}{{}}"
            pos = cursor.position()
            cursor.insertText(token)
            cursor.setPosition(pos + len(token) - 1)
        else:
            # QTextCursor.insertText() replaces the current selection on
            # its own -- no separate delete step needed.
            selected = self._selected_text(cursor)
            cursor.insertText(f"\\{prefix}{{{selected}}}")
        cursor.endEditBlock()
        self.widget.setTextCursor(cursor)
        self.widget.setFocus()

    def _on_toggle_comment(self) -> None:
        """"Comment/Uncomment" button/Ctrl+/ (direct instruction): toggles
        a leading "%" on every line the current selection touches (or just
        the cursor's own line, with no selection) -- same "comment wins"
        rule most editors use on a mixed selection: if every non-blank
        touched line is already commented, uncomment all of them;
        otherwise comment every touched line (blank ones included, so a
        second toggle uniformly reverses the first). "%" is inserted/
        removed at column 0, not after existing indentation -- simplest
        and always unambiguously reversible, matching the plain \\begin{}/
        \\end{} indentation style elsewhere in this file rather than
        preserving each line's own leading whitespace before the mark.
        One edit block, so a single Ctrl+Z undoes the whole toggle."""
        cursor = self.widget.textCursor()
        doc = self.widget.document()
        start_block = doc.findBlock(cursor.selectionStart()).blockNumber()
        end_block = doc.findBlock(cursor.selectionEnd()).blockNumber()
        # A selection ending exactly at the start of a line (nothing of
        # that line actually selected) shouldn't pull it in -- matches how
        # most editors treat a drag-selection landing exactly on a newline.
        if cursor.hasSelection() and end_block > start_block:
            end_cursor = QTextCursor(doc)
            end_cursor.setPosition(cursor.selectionEnd())
            if end_cursor.atBlockStart():
                end_block -= 1

        lines = [doc.findBlockByNumber(n).text() for n in range(start_block, end_block + 1)]
        non_blank = [line for line in lines if line.strip()]
        should_uncomment = bool(non_blank) and all(line.lstrip().startswith("%") for line in non_blank)

        cursor.beginEditBlock()
        for n in range(start_block, end_block + 1):
            block = doc.findBlockByNumber(n)
            text = block.text()
            if should_uncomment:
                match = re.match(r"[ \t]*(%)", text)
                if match:
                    line_cursor = QTextCursor(block)
                    line_cursor.setPosition(block.position() + match.start(1))
                    line_cursor.setPosition(block.position() + match.end(1), QTextCursor.MoveMode.KeepAnchor)
                    line_cursor.removeSelectedText()
            else:
                line_cursor = QTextCursor(block)
                line_cursor.setPosition(block.position())
                line_cursor.insertText("%")
        cursor.endEditBlock()
        self.widget.setFocus()

    @staticmethod
    def _line_indent(cursor: QTextCursor) -> str:
        """Leading whitespace of the line the selection *starts* on (not
        wherever cursor.position() itself currently is -- for a selection,
        that can be either end depending on which way it was dragged)."""
        start_cursor = QTextCursor(cursor.document())
        start_cursor.setPosition(cursor.selectionStart())
        return re.match(r"[ \t]*", start_cursor.block().text()).group(0)

    def _wrap_environment(self, env: str) -> None:
        """Same idea as _wrap_or_insert, for a \\begin{env}/\\end{env} pair
        instead of a single \\macro{...} -- selection goes on its own line
        between them; with no selection, an empty line is left in between
        with the cursor on it, ready to type straight into.

        \\end{env}'s own line is prefixed with the selection's starting
        line's own indentation -- without it, \\begin{...} inherits
        whatever indent the selection happened to start at (fine), but
        \\end{...} landed flush at column 0 regardless, breaking the
        block's visual indentation (confirmed directly).

        itemize/enumerate (LatexPlainTextEdit._LIST_ENVIRONMENTS, same set
        the smart-Enter completion above already treats specially) get
        extra care over a bare \\begin/\\end pair (2026-09-22, direct
        instruction): with no selection, the body isn't left blank -- it's
        pre-seeded with "\\item ", cursor right after it, exactly what
        pressing Enter right after a freshly-typed \\begin{itemize} already
        does (_smart_return above), since an empty list is never actually
        useful to land in. With a selection spanning one or more lines,
        each non-blank line becomes its own "\\item <that line's own
        stripped text>" line inside the new block, instead of the
        selection's raw text (with whatever newlines/indentation it
        already had) landing verbatim between \\begin/\\end -- turning
        already-typed lines into a list is the whole reason to select more
        than one before clicking this. A selection that turns out to be
        only blank lines still gets one empty "\\item " rather than a
        body-less list, same fallback as the no-selection case."""
        cursor = self.widget.textCursor()
        indent = self._line_indent(cursor)
        is_list_env = env in self.widget._LIST_ENVIRONMENTS
        cursor.beginEditBlock()
        if not cursor.hasSelection():
            inner = f"{indent}\t\\item " if is_list_env else f"{indent}\t"
            before = f"\\begin{{{env}}}\n{inner}"
            after = f"\n{indent}\\end{{{env}}}"
            pos = cursor.position()
            cursor.insertText(before + after)
            cursor.setPosition(pos + len(before))
        elif is_list_env:
            lines = self._selected_text(cursor).split("\n")
            items = [f"{indent}\t\\item {line.strip()}" for line in lines if line.strip()]
            body = "\n".join(items) if items else f"{indent}\t\\item "
            cursor.insertText(f"\\begin{{{env}}}\n{body}\n{indent}\\end{{{env}}}")
        else:
            selected = self._selected_text(cursor)
            cursor.insertText(f"\\begin{{{env}}}\n{selected}\n{indent}\\end{{{env}}}")
        cursor.endEditBlock()
        self.widget.setTextCursor(cursor)
        self.widget.setFocus()

    def _insert_multilingual(self, macro: str) -> None:
        """For a two-argument macro like \\multilingualtext{EN}{DE}
        (2026-08-25): a selection goes into the *first* braces (assumed
        English, matching that macro's own argument order) and the cursor
        lands in the empty second braces, ready to type the translation;
        with no selection, both brace pairs are empty and the cursor lands
        in the first one, same convention as _wrap_or_insert's own no-
        selection case."""
        cursor = self.widget.textCursor()
        cursor.beginEditBlock()
        if not cursor.hasSelection():
            token = f"\\{macro}{{}}{{}}"
            pos = cursor.position()
            cursor.insertText(token)
            cursor.setPosition(pos + len(f"\\{macro}{{"))
        else:
            selected = self._selected_text(cursor)
            pos = cursor.selectionStart()
            token = f"\\{macro}{{{selected}}}{{}}"
            cursor.insertText(token)
            cursor.setPosition(pos + len(token) - 1)
        cursor.endEditBlock()
        self.widget.setTextCursor(cursor)
        self.widget.setFocus()

    def _replace_selection_or_insert(self, literal: str) -> None:
        cursor = self.widget.textCursor()
        cursor.insertText(literal)  # replaces the selection if any, else inserts at the cursor
        self.widget.setFocus()

    def _on_color_selected(self, index: int) -> None:
        if index <= 0:
            return
        color = self.color_combo.itemText(index)
        self.color_combo.setCurrentIndex(0)
        self._wrap_or_insert(f"textcolor{{{color}}}")

    def _on_command_selected(self, index: int) -> None:
        if index <= 0:
            return
        label = self.command_combo.itemText(index)
        self.command_combo.setCurrentIndex(0)
        lookup = {lbl: (kind, payload) for lbl, kind, payload in INSERT_COMMANDS}
        if label not in lookup:
            return
        kind, payload = lookup[label]
        if kind == "literal":
            self._replace_selection_or_insert(label)
        elif kind == "wrap_macro":
            self._wrap_or_insert(payload)
        elif kind == "wrap_env":
            self._wrap_environment(payload)
        elif kind == "wrap_multilingual":
            self._insert_multilingual(payload)

    # -- find -------------------------------------------------------------------

    def _show_find_bar(self) -> None:
        self.find_bar.setVisible(True)
        cursor = self.widget.textCursor()
        if cursor.hasSelection():
            self.find_entry.setText(self._selected_text(cursor))
        self.find_entry.setFocus()
        self.find_entry.selectAll()

    def _hide_find_bar(self) -> None:
        self.find_bar.setVisible(False)
        self.find_status_label.setText("")
        self.widget.setFocus()

    def _find(self, backward: bool) -> None:
        """QPlainTextEdit.find() only searches from the current cursor
        onward (or backward), it never wraps on its own -- a single retry
        from the far end of the buffer, only once a plain search comes up
        empty, gives Next/Previous the usual wrap-around feel without
        looping forever on a genuinely absent query."""
        query = self.find_entry.text()
        if not query:
            self.find_status_label.setText("")
            return
        flags = QTextDocument.FindFlag.FindBackward if backward else QTextDocument.FindFlag(0)
        found = self.widget.find(query, flags)
        if not found:
            cursor = self.widget.textCursor()
            cursor.movePosition(
                QTextCursor.MoveOperation.End if backward else QTextCursor.MoveOperation.Start
            )
            self.widget.setTextCursor(cursor)
            found = self.widget.find(query, flags)
        self.find_status_label.setText("" if found else "Not found")

    def _on_find_next(self) -> None:
        self._find(backward=False)

    def _on_find_previous(self) -> None:
        self._find(backward=True)

    # -- bib citation-key jump bar ------------------------------------------------

    # Same shape as bibliography.py's own _ENTRY_RE (kept as its own local
    # copy rather than importing that module's underscore-prefixed
    # constant): "@type{key," anchored to the start of a line, since every
    # real entry in this file already starts one (blank-line-separated,
    # per sort_entries()'s own docstring) -- a stray "@" appearing
    # mid-line (inside a URL, say) is never mistaken for an entry this way.
    _BIB_ENTRY_KEY_RE = re.compile(r"^@\w+\s*\{\s*([^,\s]+)\s*,", re.MULTILINE)

    def _jump_to_bib_letter(self, letter: str) -> None:
        text = self.widget.toPlainText()
        for m in self._BIB_ENTRY_KEY_RE.finditer(text):
            key = m.group(1)
            if key and key[0].upper() == letter:
                cursor = self.widget.textCursor()
                cursor.setPosition(m.start())
                self.widget.setTextCursor(cursor)
                self.widget.centerCursor()
                self.widget.setFocus()
                return
        self.app.log(f"No .bib entry with a citation key starting with '{letter}'")

    # -- header-comment fold ----------------------------------------------------

    def _count_header_comment_lines(self) -> int:
        count = 0
        for line in self.text.splitlines():
            if HEADER_COMMENT_LINE_RE.match(line):
                count += 1
            else:
                break
        return count

    def _set_header_folded(self, folded: bool) -> None:
        self._header_folded = folded
        doc = self.widget.document()
        block = doc.firstBlock()
        for _ in range(self._header_fold_line_count):
            if not block.isValid():
                break
            block.setVisible(not folded)
            block = block.next()
        doc.markContentsDirty(0, doc.characterCount())
        self.widget.viewport().update()
        # QPlainTextEdit's vertical scrollbar is block-indexed, and its
        # stored value doesn't get remapped when the set of visible blocks
        # changes -- confirmed directly: without this, toggling straight
        # from folded to unfolded left the viewport showing the same
        # (now-wrong) blocks it was already showing, instead of jumping
        # back to the newly-revealed content at the top.
        self.widget.verticalScrollBar().setValue(0)
        n = self._header_fold_line_count
        self.fold_button.setText(
            f"\u25b8 Show {n}-line header comment" if folded
            else f"\u25be Hide {n}-line header comment"
        )

    def _toggle_header_fold(self) -> None:
        self._set_header_folded(not self._header_folded)

    # -- matching-brace highlight -------------------------------------------------

    def _highlight_matching_brace(self) -> None:
        """Highlights the brace pair the cursor is currently touching (on
        either side), so a slide's own deeply nested \\slide{...}{...}{...}
        calls or macro arguments are easier to scan -- not something the Tk
        version could do live off a Text widget's own cursor position
        without a lot more bookkeeping than the whole-buffer-rescan
        highlighter it already leaned on."""
        cursor = self.widget.textCursor()
        text = self.widget.toPlainText()
        pos = cursor.position()
        start_pos = None
        for candidate in (pos, pos - 1):
            if 0 <= candidate < len(text) and text[candidate] in "{}" and not self._is_escaped_brace(text, candidate):
                start_pos = candidate
                break
        selections: list[QTextEdit.ExtraSelection] = []
        if start_pos is not None:
            match_pos = self._find_matching_brace(text, start_pos)
            if match_pos is not None:
                fmt = QTextCharFormat()
                fmt.setBackground(QColor(self.app.theme.syntax_colors()["brace_match_bg"]))
                for p in (start_pos, match_pos):
                    sel = QTextEdit.ExtraSelection()
                    sel.format = fmt
                    sel_cursor = QTextCursor(self.widget.document())
                    sel_cursor.setPosition(p)
                    sel_cursor.setPosition(p + 1, QTextCursor.MoveMode.KeepAnchor)
                    sel.cursor = sel_cursor
                    selections.append(sel)
        self.widget.setExtraSelections(selections)

    @staticmethod
    def _is_escaped_brace(text: str, pos: int) -> bool:
        return pos > 0 and text[pos - 1] == "\\"

    @classmethod
    def _find_matching_brace(cls, text: str, pos: int) -> Optional[int]:
        char = text[pos]
        depth = 0
        if char == "{":
            for i in range(pos, len(text)):
                if cls._is_escaped_brace(text, i):
                    continue
                if text[i] == "{":
                    depth += 1
                elif text[i] == "}":
                    depth -= 1
                    if depth == 0:
                        return i
            return None
        else:
            for i in range(pos, -1, -1):
                if cls._is_escaped_brace(text, i):
                    continue
                if text[i] == "}":
                    depth += 1
                elif text[i] == "{":
                    depth -= 1
                    if depth == 0:
                        return i
            return None

    def _set_dirty(self, dirty: bool) -> None:
        self._dirty = dirty
        self.dirty_label.setText("(unsaved changes)" if dirty else "")
        self.revert_button.setEnabled(dirty)
        self.close_save_button.setEnabled(dirty)

    def _prompt_version_choice(
        self, old_version: Optional[slide_versioning.Version]
    ) -> Optional[str]:
        """The save-time "how significant is this change?" prompt for a
        slide's own current.tex (2026-08-20, direct instruction): major/
        minor/patch freeze the outgoing on-disk content under its own
        tracked version and bump the new content's version accordingly;
        "Overwrite" just saves -- no freeze, no version change (a
        never-tracked slide stays untracked). Returns the chosen level,
        "overwrite", or None if the user cancelled the save entirely.
        """
        baseline = old_version if old_version is not None else slide_versioning.DEFAULT_BASELINE
        current_label = (
            slide_versioning.format_dot(old_version) if old_version is not None else "untracked"
        )
        box = QMessageBox(self)
        box.setWindowTitle("Save slide")
        box.setText(f"Current version: {current_label}\n\nHow significant is this change?")
        level_buttons: dict[str, "QPushButton"] = {}
        for level in ("major", "minor", "patch"):
            target = slide_versioning.format_dot(slide_versioning.bump(baseline, level))
            level_buttons[level] = box.addButton(
                f"{level.capitalize()} (→ {target})", QMessageBox.ButtonRole.AcceptRole
            )
        overwrite_label = (
            f"Overwrite (stays {current_label})"
            if old_version is not None
            else "Overwrite (no version tracked)"
        )
        overwrite_button = box.addButton(overwrite_label, QMessageBox.ButtonRole.DestructiveRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(overwrite_button)
        box.exec()
        clicked = box.clickedButton()
        for level, button in level_buttons.items():
            if clicked is button:
                return level
        if clicked is overwrite_button:
            return "overwrite"
        return None

    @staticmethod
    def _diff_replace_range(old: str, new: str) -> tuple[int, int, str]:
        """The smallest (start, end, replacement) such that
        old[:start] + replacement + old[end:] == new -- a plain common-
        prefix/common-suffix diff, cheap enough at slide-file sizes (same
        reasoning this module's own docstring already gives for
        QSyntaxHighlighter's per-block rescan). Used to patch just the
        version-marker line into the live editor buffer after a save
        (see _on_save()) without disturbing the rest of the document."""
        max_prefix = min(len(old), len(new))
        prefix_len = 0
        while prefix_len < max_prefix and old[prefix_len] == new[prefix_len]:
            prefix_len += 1
        max_suffix = max_prefix - prefix_len
        suffix_len = 0
        while (
            suffix_len < max_suffix
            and old[len(old) - 1 - suffix_len] == new[len(new) - 1 - suffix_len]
        ):
            suffix_len += 1
        return prefix_len, len(old) - suffix_len, new[prefix_len:len(new) - suffix_len]

    def _apply_minimal_text_replace(self, old: str, new: str) -> None:
        """Patches self.widget's own live buffer from `old` (what it held
        when this text was read out of it) to `new` (what was actually
        written to disk), touching only the region that actually differs
        -- unlike setPlainText(), which would reset the cursor to the top
        of the document, discard the undo history, and jump the scroll
        position, all for what's normally just a single header line
        changing out from under the user right after they hit Save."""
        start, end, replacement = self._diff_replace_range(old, new)
        if start == end and not replacement:
            return
        scrollbar = self.widget.verticalScrollBar()
        scroll_value = scrollbar.value()
        visible_cursor = self.widget.textCursor()
        old_pos = visible_cursor.position()
        if old_pos <= start:
            new_pos = old_pos
        elif old_pos >= end:
            new_pos = old_pos - end + start + len(replacement)
        else:
            new_pos = start + len(replacement)  # was inside the replaced region

        edit_cursor = QTextCursor(self.widget.document())
        edit_cursor.beginEditBlock()
        edit_cursor.setPosition(start)
        edit_cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        edit_cursor.insertText(replacement)
        edit_cursor.endEditBlock()

        visible_cursor.setPosition(new_pos)
        self.widget.setTextCursor(visible_cursor)
        scrollbar.setValue(scroll_value)

    def _on_save(self) -> bool:
        """Returns whether the save actually happened -- False only when
        the version-bump dialog below was shown and cancelled, so
        _on_close/_on_close_and_save (which chain a close right after
        saving) don't discard unsaved work on a cancel."""
        raw_text = self.widget.toPlainText()
        new_text = raw_text
        previous_text = self.text

        if self._is_current_slide:
            old_version = slide_versioning.parse_version(self.text)
            choice = self._prompt_version_choice(old_version)
            if choice is None:
                return False
            final_version, freeze_as = slide_versioning.plan_save(old_version, choice)
            if freeze_as is not None:
                frozen = slide_versioning.freeze_slide(self.path, self._slide_id_slug, freeze_as)
                if frozen is not None:
                    self.app.log(
                        f"    (froze outgoing v{slide_versioning.format_dot(freeze_as)} "
                        f"-> {frozen.name})"
                    )
                else:
                    self.app.log(
                        f"    (v{slide_versioning.format_dot(freeze_as)} was already "
                        f"frozen -- left it alone)"
                    )
            new_text = (
                slide_versioning.set_marker(new_text, final_version)
                if final_version is not None
                else slide_versioning.strip_marker(new_text)
            )

        backup_path = slide_source.save_slide_source(self.path, new_text, self.eol)
        self.text = new_text
        if new_text != raw_text:
            # The version-bump above rewrote the \setSlideVersion{} line in
            # what got saved to disk, but never touched self.widget's own
            # buffer -- without this, the editor kept showing the pre-bump
            # version right after a save that just bumped it (direct
            # report, 2026-08-29).
            self._apply_minimal_text_replace(raw_text, new_text)
        self.widget.document().setModified(False)
        self._update_render_language_visibility()
        if backup_path is not None:
            from .deck_scan import PROJECT_ROOT

            self.app.log(f"Saved {self.path.name} (backup: {backup_path.relative_to(PROJECT_ROOT)})")
        else:
            self.app.log(f"Saved {self.path.name} (new file, no prior content to back up)")
        if self.on_saved is not None:
            self.on_saved(previous_text)
        self._maybe_apply_pending_language_change()
        return True

    def _maybe_apply_pending_language_change(self) -> None:
        """If the language combo (set_language_combo) is sitting on a
        different, valid language than this slide is actually tagged
        with -- i.e. the user picked a new value but never clicked "Set"
        -- the file/filename would otherwise silently keep its old
        language forever, with the combo now lying about what it actually
        is (direct report, 2026-08-29: the "separate, explicit action"
        design above was fine as long as the combo couldn't drift from
        reality unnoticed, which it turned out it easily could). Offers to
        apply it right here via the exact same _on_set_language() the
        button itself calls, complete with its own confirmation dialog
        (rename + reference-count details) -- called only after a real
        pending mismatch is confirmed here, since _on_set_language() would
        otherwise pop its own "(untagged)" error on every single save of
        every still-untagged slide, where the combo correctly shows
        "(untagged)" and there is nothing pending at all."""
        if not hasattr(self, "set_language_combo"):
            return
        new_language = _LANGUAGE_COMBO_TO_CODE.get(self.set_language_combo.currentText())
        if new_language is None:
            return
        if slide_language.own_language(self._slide_id_slug) == new_language:
            return
        self._on_set_language()

    def _on_reindent(self) -> None:
        """"Reindent" button (direct instruction) -- reindent_latex() does
        the actual work (a pure, independently-tested function, module
        level above); this is just the Qt-buffer/undo-step wrapper. Whole
        document replaced as one edit block, so a single Ctrl+Z undoes the
        entire pass, not one line at a time."""
        old_text = self.widget.toPlainText()
        new_text = reindent_latex(old_text)
        if new_text == old_text:
            self.app.log(f"{self.path.name}: indentation already correct")
            return
        cursor = self.widget.textCursor()
        cursor.beginEditBlock()
        cursor.select(QTextCursor.SelectionType.Document)
        cursor.insertText(new_text)
        cursor.endEditBlock()
        # A whole-buffer reindent makes "same character offset as before"
        # meaningless (every line's own length just changed) -- landing
        # back at the top is a saner default than wherever insertText()
        # itself leaves the cursor (the very end of the document).
        cursor.setPosition(0)
        self.widget.setTextCursor(cursor)
        self.app.log(f"Reindented {self.path.name}")

    def _on_check_syntax(self) -> None:
        """"Check syntax" button (direct instruction) -- non-modal, and
        reused rather than reopened on a second click (see
        SyntaxCheckDialog's own docstring for why it's non-modal at all):
        a second dialog over the same buffer would just be confusing, not
        useful."""
        if getattr(self, "_syntax_check_dialog", None) is not None:
            self._syntax_check_dialog.raise_()
            self._syntax_check_dialog.activateWindow()
            return
        dialog = SyntaxCheckDialog(self, self.path.name)
        self._syntax_check_dialog = dialog
        dialog.finished.connect(lambda _result: setattr(self, "_syntax_check_dialog", None))
        dialog.show()

    def _on_ai_draft(self) -> None:
        """"AI draft" button (direct instruction) -- same singleton-per-tab,
        non-modal pattern as _on_check_syntax() above, for the same reason."""
        if getattr(self, "_ai_draft_dialog", None) is not None:
            self._ai_draft_dialog.raise_()
            self._ai_draft_dialog.activateWindow()
            return
        dialog = AiDraftDialog(self, self.path.name)
        self._ai_draft_dialog = dialog
        dialog.finished.connect(lambda _result: setattr(self, "_ai_draft_dialog", None))
        dialog.show()

    def _on_revert(self) -> None:
        if not self._dirty:
            return
        reply = QMessageBox.question(
            self, "Revert", f"Discard unsaved changes to {self.path.name} and reload the saved version?"
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self.text, self.eol = slide_source.read_slide_source(self.path)
        self.widget.setPlainText(self.text)
        self.widget.document().setModified(False)
        # setPlainText() rebuilds every QTextBlock, so a prior fold's
        # visibility state doesn't survive it -- recompute and reapply.
        if hasattr(self, "fold_button"):
            self._header_fold_line_count = self._count_header_comment_lines()
            self._set_header_folded(self._header_folded)
        self.app.log(f"Reverted {self.path.name} to the saved version")

    def _on_summary_changed(self) -> None:
        self.save_summary_button.setEnabled(True)

    def _on_save_summary(self) -> None:
        text = self.summary_edit.toPlainText().strip()

        def mutate(notes: dict[str, alt_images.SlideNotes]) -> bool:
            notes.setdefault(
                self._slide_bare_id, alt_images.SlideNotes()).summary = text
            return True

        alt_images.update_slide_notes(mutate)
        self.save_summary_button.setEnabled(False)
        self.app.log(
            f"Saved transcript summary for {self._slide_bare_id}"
            if text else f"Cleared transcript summary for {self._slide_bare_id}"
        )

    def _on_preview(self) -> None:
        try:
            macro, id_slug, version = slide_preview.call_for_slide_path(self.path)
        except ValueError as exc:
            QMessageBox.critical(self, "Preview failed", str(exc))
            return

        def render() -> None:
            # Always the *saved* file (macro/version exactly matching what
            # \slide{}/\slideversion{} would load from disk for this file),
            # never this editor's buffer (unlike Render to PDF) -- the
            # cached preview this refreshes has to mean the same thing
            # everywhere it's shown (deck view's own Preview popup compiles
            # the saved file too), and an unsaved edit compiled here would
            # silently give it a different meaning depending on which tab
            # happened to trigger it. No explicit deck_version: leaves it
            # at the instructor default, matching what actually gets
            # cached (see slide_preview.render_slide_to_pdf's own
            # docstring).
            # Read live, same as _on_render()'s own "Render to PDF" button
            # (2026-08-26 fix) -- this popup's "Render now" had the same
            # bug, just never fixed alongside it (direct report, 2026-08-30).
            pdf_path = slide_preview.render_slide_to_pdf(
                macro, id_slug, version,
                footer_timestamp=self.app.footer_timestamp_checkbox.isChecked(),
                log=self.app.signals.log.emit)
            slide_preview.open_pdf(pdf_path)

        # id_slug here is the full slug ("dsk-Reference-Point-..."), the
        # \slide{}/\slideversion{} macro argument -- needed whole by
        # render() above to \input{} the right file, but snapshots are
        # keyed by the short id \setSlideID actually derives from it (see
        # slide_snapshot.bare_id()).
        #
        # Always the default (Graz) template here, not a picker -- this
        # tab has no one deck it belongs to (a slide file can be used by
        # several, under different institutions), and every real deck
        # today is Graz anyway. render() above renders with GENERIC_PREAMBLE
        # (also Graz), so this lookup matches what "Render now" will
        # actually produce.
        popup = SlidePreviewPopup(
            self, slide_snapshot.bare_id(id_slug), self.path, render_fn=render,
            template=slide_snapshot.DEFAULT_TEMPLATE)
        popup.exec()

    def _on_render(self) -> None:
        # Always renders the current in-editor buffer directly (never
        # saves first, never touches the file on disk).
        try:
            _, id_slug, _ = slide_preview.call_for_slide_path(self.path)
        except ValueError as exc:
            QMessageBox.critical(self, "Render failed", str(exc))
            return

        slide_body = self.widget.toPlainText()
        version_label = self.version_combo.currentText()
        deck_version = next(v for v, label in VERSION_LABELS.items() if label == version_label)
        deck_language = self.render_language_combo.currentText().lower()
        # Read live, same as every other user of this checkbox (2026-08-26,
        # direct report -- this render path used to ignore it entirely,
        # always showing the footer timestamp regardless of its state).
        footer_timestamp = self.app.footer_timestamp_checkbox.isChecked()

        self.render_button.setEnabled(False)
        threading.Thread(
            target=self._render_bg,
            args=(id_slug, slide_body, deck_version, deck_language, footer_timestamp),
            daemon=True,
        ).start()

    def _render_bg(
        self, id_slug: str, slide_body: str, deck_version: str, deck_language: str,
        footer_timestamp: bool,
    ) -> None:
        log = self.app.signals.log.emit
        try:
            pdf_path = slide_preview.render_slide_text_to_pdf(
                id_slug, slide_body,
                deck_version=deck_version, deck_language=deck_language,
                footer_timestamp=footer_timestamp, log=log,
            )
        except RuntimeError as exc:
            log(f"*** Render failed: {exc} ***")
        else:
            slide_preview.open_pdf(pdf_path)
        finally:
            self.app.signals.enable_button.emit(self.render_button)

    def _on_render_transcript(self) -> None:
        """"Render transcript" (2026-08-25) -- a one-slide transcript
        preview of this editor's current buffer, opened in its own review
        tab (qt_transcript_preview_tab.py) rather than written to disk.
        Fast enough (regex-only Markdown assembly, no LaTeX compile, no
        network call) to run synchronously with a wait cursor, same
        precedent as _ImageEditor._on_translate()'s single-image
        translation call in qt_transcript_tab.py."""
        version_label = self.version_combo.currentText()
        deck_version = next(v for v, label in VERSION_LABELS.items() if label == version_label)
        deck_language = self.render_language_combo.currentText().lower()
        slide_body = self.widget.toPlainText()

        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            result = transcript.generate_single_slide(
                slide_body, self._slide_bare_id, deck_version, deck_language)
        except Exception as exc:  # noqa: BLE001 -- surface any failure to the user
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self, "Transcript render failed", str(exc))
            return
        QApplication.restoreOverrideCursor()

        html = transcript.to_html(result, f"Transcript preview: {self._slide_id_slug}")
        tab = self.app.open_transcript_preview(
            self._slide_bare_id, f"Transcript: {self._slide_id_slug}")
        tab.set_html(html)
        if result.undescribed:
            self.app.log(
                f"Transcript preview for {self._slide_id_slug}: still has an "
                f"undescribed image; flagged in place in the preview."
            )

    # -- duplicate (2026-08-25) -------------------------------------------------------

    def _on_duplicate_slide(self) -> None:
        if self._dirty:
            QMessageBox.warning(
                self, "Duplicate slide",
                "Save or revert this slide's unsaved changes first -- "
                "duplicating always seeds the new slide from the saved "
                "file on disk, never from an unsaved buffer.",
            )
            return

        dialog = DuplicateSlideDialog(self, self._slide_id_slug, self.path)
        if dialog.exec() != DuplicateSlideDialog.DialogCode.Accepted:
            return
        assert dialog.new_id_slug is not None and dialog.new_path is not None
        self.app.log(f"Duplicated {self._slide_id_slug} -> {dialog.new_id_slug}")
        self.app.open_slide_editor(dialog.new_path, return_to=self)

    # -- language (2026-08-24) -------------------------------------------------------

    def _refresh_language_controls(self) -> None:
        """Updates the badge label and (for -current.tex) resets the
        rename combo to whatever the filename currently encodes. Called
        once at __init__ and again after a successful rename."""
        own = slide_language.own_language(self._slide_id_slug)
        cross_lang = slide_language.cross_referenced_language(self._slide_id_slug, self.path)
        if own is not None and cross_lang is not None and cross_lang != own:
            # Both this slide's own language *and* a cross-referenced
            # translation in another language exist -- highlighted per
            # direct instruction, so a linked translation is obvious at a
            # glance rather than something you'd only notice by opening
            # the header comment.
            self.language_badge_label.setText(f"[{own} + {cross_lang}]")
            self.language_badge_label.setStyleSheet("font-weight: bold;")
        elif own is not None:
            self.language_badge_label.setText(f"[{own}]")
            self.language_badge_label.setStyleSheet("")
        else:
            self.language_badge_label.setText("")
            self.language_badge_label.setStyleSheet("")

        if hasattr(self, "set_language_combo"):
            target_text = _LANGUAGE_CODE_TO_COMBO.get(own, "(untagged)")
            index = self.set_language_combo.findText(target_text)
            if index != -1:
                self.set_language_combo.setCurrentIndex(index)

        # Keep the render bar's own language default in sync with a rename
        # too (own_language_for_render at __init__ time only ever runs
        # once) -- otherwise a slide just renamed EN -> DE would still
        # silently render/preview-transcript as English until the tab is
        # closed and reopened.
        if hasattr(self, "render_language_combo") and own == "DE":
            self.render_language_combo.setCurrentText("DE")
        self._update_render_language_visibility()

    def _update_render_language_visibility(self) -> None:
        """Recomputes whether the render bar's "Render language:" row
        should show, from *live* state -- this slide's current tag plus
        the editor's current buffer text, not the fixed values __init__
        computed once when the file was first opened. Re-run after a
        rename (via _refresh_language_controls()) and after a save
        (2026-08-25, direct instruction: renaming a slide EN -> mult, or
        typing in a \\multilingualtext{}{} call, previously needed a
        close/reopen before the row actually appeared)."""
        if not hasattr(self, "render_language_combo"):
            return
        own = slide_language.own_language(self._slide_id_slug)
        show = own == "mult" or "\\multilingualtext" in self.widget.toPlainText()
        self.render_language_label.setVisible(show)
        self.render_language_combo.setVisible(show)

    def _on_set_language(self) -> None:
        if self._dirty:
            QMessageBox.warning(
                self, "Set language",
                "Save or revert this slide's unsaved changes first -- "
                "renaming moves the file on disk, and an unsaved buffer "
                "would then be saved under (or lost relative to) the wrong "
                "name.",
            )
            return

        new_language = _LANGUAGE_COMBO_TO_CODE.get(self.set_language_combo.currentText())
        if new_language is None:
            QMessageBox.critical(
                self, "Set language",
                "Pick EN, DE, or Multilingual -- a slide can't be set back "
                "to untagged once it's been tagged.",
            )
            self._refresh_language_controls()
            return

        old_id_slug = self._slide_id_slug
        if slide_language.own_language(old_id_slug) == new_language:
            return

        n_refs = slide_rename.count_references(old_id_slug)
        confirm = QMessageBox.question(
            self, "Set language",
            f"This will rename {old_id_slug}-current.tex (and any frozen "
            f"versions of it) to language {new_language}, and rewrite "
            f"{n_refs} deck reference(s) to match. Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return

        try:
            new_id_slug = slide_rename.set_slide_language(old_id_slug, new_language)
        except (FileNotFoundError, FileExistsError, ValueError) as exc:
            QMessageBox.critical(self, "Set language failed", str(exc))
            return

        new_path = self.path.parent / f"{new_id_slug}-current.tex"
        # rename_slide_editor_tab() reads self.path as the *old* path to
        # pop from the app's tab dict, so it must run before self.path is
        # overwritten below -- reordered after a headless smoke test
        # caught the stale-key bug this order avoids (both the old and
        # new path stayed in the dict when this ran the other way around).
        self.app.rename_slide_editor_tab(self, new_path)
        self.path = new_path
        self._slide_id_slug = new_id_slug
        self.app.log(
            f"Set language of {old_id_slug} -> {new_id_slug} "
            f"({n_refs} deck reference(s) updated)"
        )
        self._refresh_language_controls()
        # Without this, any already-open deck-editor tab kept showing the
        # slide under its old id-slug -- clicking it tried to open a file
        # that no longer existed on disk (2026-08-25, direct instruction).
        self.app.refresh_open_deck_editors()

    def _on_close(self) -> None:
        if self._dirty:
            choice = QMessageBox.question(
                self,
                "Close slide source",
                f"Save changes to {self.path.name} before closing?",
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.No
                | QMessageBox.StandardButton.Cancel,
            )
            if choice == QMessageBox.StandardButton.Cancel:
                return
            if choice == QMessageBox.StandardButton.Yes:
                if not self._on_save():
                    return  # version-bump dialog cancelled -- don't close on top of it
        self.app.close_slide_editor_tab(self)

    def _on_close_and_save(self) -> None:
        if self._dirty:
            if not self._on_save():
                return
        self.app.close_slide_editor_tab(self)
