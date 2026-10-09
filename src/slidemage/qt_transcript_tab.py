"""The image-description review tab (ALT_TEXT_NOTES.md, phase 2).

A permanent third tab next to Active/Archived decks. Left: every slide that
includes at least one image, with its review state. Right: for the selected
slide, each of its images shown at a workable size with the fields that
describe it.

Why the image is shown large rather than as a thumbnail: the drafting pass
(phase 3) produces descriptions containing *numbers read off charts*, and
that is exactly where a model goes wrong -- the design sample misread bar
values off a scanned figure by more than the values themselves would
tolerate. A review UI that doesn't let you check a number against the chart
is not a review UI.

Everything about an image -- role, short/long description, a default
takeaway -- lives in one place now: media/alt-text.json (alt_images.py),
shared across every slide that uses the image. Only the *takeaway* can
still differ per slide (why this image is on *this* slide is genuinely
contextual), and only the *reviewed* stamp is per (image, slide) pair --
see alt_images.py's own docstring for the full reasoning. This tab is the
only thing that writes to that store.
"""
from __future__ import annotations

import datetime as _dt
import shutil
import threading
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QStringListModel, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCompleter,
    QDialog,
    QDialogButtonBox,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from . import open_path
from . import (
    alt_blocks, alt_draft, alt_images, media_render,
    slide_ids, slide_language, tikz_render, transcript,
)
from .ai.providers import ChatProvider, OllamaProvider
from .qt_ai_models import fill_model_combo, provider_from_combo
from .ui.kit.theme import CLOSE_BUTTON, MUTED_LABEL, WARNING_LABEL
from .deck_editor import parse_slide_calls
from .deck_scan import PROJECT_ROOT, Deck, scan_decks

# Qt can only paint raster formats directly. A .pdf is rendered to a
# cached PNG on the fly instead (media_render.py, 2026-08-26) -- see
# _build_preview() below; .eps has no renderer in this project and still
# falls through to the plain "can't preview" notice.
_VIEWABLE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".gif"}


def _underline(text: str) -> str:
    """`text` with a combining low-line (U+0332) after every character --
    genuine plain-text underlining, for a widget (QPushButton) that doesn't
    parse rich text at all. See review_button's own comment for why this,
    not HTML, is what actually renders as underlined here."""
    return "".join(ch + "̲" for ch in text)


def _review_button_label(image_count: int) -> str:
    """review_button's own text -- plain "Save and mark reviewed" for a
    slide with zero or one image (where "all images" would just be a
    confusing way to say "the image"), "Save and mark <u>all images</u>
    reviewed" once there's more than one (2026-09-15, direct instruction --
    the plain-for-one/emphasized-for-many split makes the button itself the
    signal that this slide has more than one image to check, not just a
    permanent reminder that stops standing out once every button says it)."""
    if image_count > 1:
        return "Save and mark " + _underline("all images") + " reviewed"
    return "Save and mark reviewed"

# How long TranscriptTab._schedule_scroll_restore() keeps re-applying its
# target scroll value in response to the scroll area's own range changing,
# after every editor on the current slide is torn down and rebuilt.
# Generous on purpose -- imperceptible to a human either way, but this is
# what makes the restore survive however many real layout-settling passes
# an actual onscreen window turns out to need, not just one.
_SCROLL_RESTORE_WINDOW_MS = 300

# Fill says how complete, color says how much to trust it -- so "draft" and
# "needs re-check" are both half-filled but differently colored, and "no
# description" is distinguishable from "draft" at a glance rather than being
# the same red dot.
_STATE_MARKERS = {
    alt_images.STATE_NONE: "○",       # empty: nothing there
    alt_images.STATE_DRAFT: "◐",      # half: written, nobody has checked it
    alt_images.STATE_STALE: "◐",      # half: was checked, then changed
    alt_images.STATE_REVIEWED: "●",   # full: checked and current
}

_STATE_COLORS = {
    alt_images.STATE_NONE: "#c0392b",
    alt_images.STATE_DRAFT: "#c0392b",
    alt_images.STATE_STALE: "#d68910",
    alt_images.STATE_REVIEWED: "#1e8449",
}

# _ImageEditor's own "German" header label text per alt_images.translation_state()
# -- shared with the two places (2026-08-25) that now set it directly rather
# than going through translation_state() itself: _mark_translation_possibly_stale()
# (a live edit to the English text can't recompute a hash-based state without
# writing anything yet) and _on_translation_done() (a background translation
# just finished, and the fields now genuinely match the English text it was
# given, even though that isn't saved -- and therefore not reflected in
# translated_from_hash -- yet).
_TRANSLATION_STATE_LABELS = {
    alt_images.STATE_NONE: "not translated yet",
    alt_images.STATE_STALE: "⚠ stale -- English text edited since translation",
    alt_images.STATE_REVIEWED: "translation matches current English text",
}

_FILTERS = [
    ("Needs attention", (alt_images.STATE_NONE, alt_images.STATE_DRAFT,
                         alt_images.STATE_STALE)),
    ("All slides with images", None),
    ("No description", (alt_images.STATE_NONE,)),
    ("Draft, unreviewed", (alt_images.STATE_DRAFT,)),
    ("Needs re-check", (alt_images.STATE_STALE,)),
    ("Reviewed", (alt_images.STATE_REVIEWED,)),
]


@dataclass
class _SlideView:
    """One slide's row in the list: its scan result plus the worst review
    state across the images it shows -- the per-slide aggregate the old
    single %%ALT block used to carry directly, now computed from the
    per-(image, slide) states of everything it references."""

    row: alt_blocks.SlideRow
    state: str
    slide_hash: str


# Worst-first, matching alt_images.STATE_LABELS's own ordering.
_STATE_RANK = {alt_images.STATE_NONE: 0, alt_images.STATE_DRAFT: 1,
              alt_images.STATE_STALE: 2, alt_images.STATE_REVIEWED: 3}


def _slide_state(row: alt_blocks.SlideRow, entries: dict[str, alt_images.ImageEntry],
                 slide_hash: str) -> str:
    worst = alt_images.STATE_REVIEWED
    for reference in row.images:
        entry = alt_images.lookup(entries, reference)
        if entry is None:
            state = alt_images.STATE_NONE
        else:
            state = alt_images.slide_use_state(entry, row.slide_id, slide_hash)
        if _STATE_RANK[state] < _STATE_RANK[worst]:
            worst = state
    return worst


# Shown under the Source field (2026-09-19, direct instruction). The
# "AI-generated -- " prefix convention is documented in CONVERSION_NOTES.md
# ("Image sources go into media/alt-text.json"); this is the same rule
# surfaced at the moment someone is actually typing a source.
_SOURCE_HELP = (
    "Feeds the automatic \"Image source(s):\" footnote. For an AI-generated "
    "image, write: AI-generated -- <engine> <version>, prompt: ``<prompt "
    "exactly as entered>''. Example: AI-generated -- Midjourney 7, prompt: "
    "``a garden with paths leading to statues, aerial view --ar 16:9''. "
    "Any other image just gets its ordinary credit (e.g. Own illustration.)."
)

# Same convention README.md's own "Directory layout" section documents for
# media/ -- kept as a short, human-facing summary here rather than a link,
# since this dialog is exactly the moment someone's picking a name and
# benefits from seeing it right there instead of switching to the docs.
_MEDIA_NAMING_HELP = (
    "Name as <type>-<slug>[-cropped].<ext>, so the kind of image is "
    "obvious from the filename alone. Common type prefixes: chart-, "
    "photo-, screenshot-, midjourney-, chapter-logo-. Append -cropped if "
    "this is a cropped version of a plain source image (keep the "
    "uncropped original too, under its own name, if you still have it)."
)


def _ask_new_filename(parent: QWidget, suggested_stem: str, extension: str) -> str | None:
    """Prompts for the new file's own name (without its extension, which
    is fixed to whatever the picked source file actually is -- a JPEG
    can't be relabeled .png without actually converting it). Returns the
    chosen stem, or None if cancelled."""
    dialog = QDialog(parent)
    dialog.setWindowTitle("Replace image")
    layout = QVBoxLayout(dialog)
    layout.addWidget(QLabel("New name for the copy in media/:"))

    row = QHBoxLayout()
    stem_edit = QLineEdit(suggested_stem)
    stem_edit.selectAll()
    row.addWidget(stem_edit, stretch=1)
    row.addWidget(QLabel(extension))
    layout.addLayout(row)

    help_label = QLabel(_MEDIA_NAMING_HELP)
    help_label.setWordWrap(True)
    help_label.setObjectName(MUTED_LABEL)
    layout.addWidget(help_label)

    buttons = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    stem_edit.setFocus()

    while True:
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        stem = stem_edit.text().strip()
        if not stem or "/" in stem or "\\" in stem:
            QMessageBox.warning(
                parent, "Replace image",
                "Enter a name with no path separators (the file always "
                "goes directly into media/).",
            )
            continue
        return stem


class _ImageEditor(QFrame):
    """The editing panel for one image within the selected slide."""

    # Carries an alt_draft.TranslationResult back to the GUI thread once a
    # background "Translate now" (2026-08-25) finishes -- see _on_translate/
    # _translate_bg/_on_translation_done.
    translation_done = Signal(object)

    def __init__(self, app, reference: str, entry: alt_images.ImageEntry,
                 slide_id: str, slide_hash: str, translation_model_combo: QComboBox,
                 on_save_and_translate: Callable[[str], None],
                 on_replace_image: Callable[["_ImageEditor"], None]) -> None:
        super().__init__()
        self.app = app
        # Owned by TranscriptTab (2026-09-18): replacing an image touches
        # the media/ file, the slide's own .tex source, possibly *other*
        # slides sharing this image, and the alt-text store -- all things
        # this one panel has no business owning itself. See this tab's own
        # _on_replace_image_clicked().
        self._on_replace_image = on_replace_image
        # Read live (not copied at construction time) so a mid-session
        # model change in the tab's own toolbar picker applies to the very
        # next "Translate now" click, not just editors built afterward.
        self._translation_model_combo = translation_model_combo
        # Called by _on_translate() when the user picks "Save, then
        # translate" (2026-08-26, direct instruction) -- owned by
        # TranscriptTab, not this editor, since it has to run the same
        # whole-slide Save draft this tab's own button does (this editor
        # only ever holds one image's fields, but a save writes every
        # image on the slide together). See TranscriptTab._request_save_and_translate.
        self._on_save_and_translate = on_save_and_translate
        self.reference = reference
        self.slide_id = slide_id
        self.dirty = False
        # Read by TranscriptTab._has_in_flight_translation() (2026-08-25,
        # direct instruction) before tearing this editor down for a
        # different slide selection -- see _on_translate/_on_translation_done.
        self.translating = False
        self.setFrameShape(QFrame.StyledPanel)

        layout = QVBoxLayout(self)

        header = QHBoxLayout()
        name = QLabel(f"<b>{reference}</b>")
        name.setTextInteractionFlags(Qt.TextSelectableByMouse)
        header.addWidget(name, stretch=1)

        # Role radios and the status label used to live in TranscriptTab's
        # shared action row, next to Save draft / Mark reviewed -- but that
        # row only has horizontal room for about one image's worth of
        # controls. A slide with three or four images (a multi-panel figure)
        # ran out of space and the groups started overlapping. Each image's
        # own header has as much width as the panel does, and panels stack
        # vertically, so this scales to any number of images.
        #
        # Radio buttons rather than a dropdown: with only two mutually
        # exclusive values, a combo costs two clicks (open, pick) for what
        # radios do in one, and this choice is made once per image across
        # ~280 images.
        self.role_group = QButtonGroup(self)
        self._role_buttons: dict[str, QRadioButton] = {}
        header.addWidget(QLabel("Role:"))
        for role in (alt_images.ROLE_INFORMATIVE, alt_images.ROLE_DECORATIVE):
            button = QRadioButton(role)
            button.setChecked(role == entry.role)
            self.role_group.addButton(button)
            self._role_buttons[role] = button
            header.addWidget(button)
        self.role_group.buttonToggled.connect(self._on_role_changed)

        # MUTED_LABEL (theme-aware c['muted_fg']) rather than the previous
        # inline `color: palette(mid)`: this app only ever calls
        # QApplication.setStyleSheet(), never setPalette(), so `palette(mid)`
        # stayed pinned to Qt's default *light*-mode mid-gray regardless of
        # this app's own dark/light toggle.
        self.status_label = QLabel()
        self.status_label.setObjectName(MUTED_LABEL)
        self._refresh_status_label(entry, slide_hash)
        header.addWidget(self.status_label)

        # Hidden (not just disabled) for a tikz: reference (2026-09-18) --
        # a hand-drawn illustration has no file on disk to swap out; there
        # is nothing this button could sensibly do for one.
        if not reference.startswith(alt_blocks.TIKZ_PREFIX):
            replace_button = QPushButton("Replace image…")
            replace_button.setToolTip(
                "Pick a different image file from your PC, copy it into "
                "media/ under a new name, and repoint this slide (and "
                "optionally every other slide using the same image) at it."
            )
            replace_button.clicked.connect(lambda: self._on_replace_image(self))
            header.addWidget(replace_button)

        layout.addLayout(header)

        if len(entry.used_on) > 1:
            others = sorted(sid for sid in entry.used_on if sid != slide_id)
            if others:
                # WARNING_LABEL (theme-aware red/orange, c['warning_fg']),
                # not MUTED_LABEL -- this is easy to miss as plain gray
                # italics (direct report, 2026-09-16) and matters: editing
                # this image's description here changes it everywhere it's
                # used, not just on this one slide (see clear_button's own
                # tooltip a few hundred lines below).
                shared_note = QLabel(
                    f"<i>Also used on: {', '.join(others)}</i>")
                shared_note.setObjectName(WARNING_LABEL)
                layout.addWidget(shared_note)

        layout.addWidget(self._build_preview(reference))

        self.fields: dict[str, QPlainTextEdit] = {}
        for key, label, height, initial in (
            ("short", "Short alt (one locating sentence -- goes into the PDF; "
                      "shared across every slide using this image)", 60, entry.short),
            ("long", "Long description (structured; goes into the transcript; "
                     "shared across every slide using this image)", 260, entry.long),
        ):
            layout.addWidget(QLabel(label))
            edit = QPlainTextEdit(initial)
            edit.setFixedHeight(height)
            layout.addWidget(edit)
            self.fields[key] = edit
            # Connected *after* the initial setText, so loading a slide does
            # not itself mark the editor dirty. `dirty` is what stops a
            # running batch from refreshing fields the user is typing into.
            edit.textChanged.connect(self._mark_dirty)
            if key in ("short", "long"):
                # Live staleness signal (2026-08-25, direct instruction) --
                # short/long are exactly the two fields en_text_hash() (and
                # therefore translation_state()) hashes alongside the
                # takeaway default, so an edit to either one really does
                # mean the German translation below no longer matches.
                edit.textChanged.connect(self._mark_translation_possibly_stale)

        # Takeaway: per-slide, with an image-level default. Empty override
        # means "follows the default" -- the field is pre-filled with
        # whichever is currently effective, and a small label plus button
        # make which state it's in (and how to change it) visible rather
        # than implicit.
        takeaway_row = QHBoxLayout()
        takeaway_row.addWidget(QLabel(
            "Takeaway (why this image is on this slide)"), stretch=1)
        self.takeaway_state_label = QLabel()
        self.takeaway_state_label.setObjectName(MUTED_LABEL)
        takeaway_row.addWidget(self.takeaway_state_label)
        self.set_default_button = QPushButton("Set as default")
        self.set_default_button.setToolTip(
            "Push this slide's current takeaway text to become this image's "
            "default -- what any other slide using it (that hasn't written "
            "its own) will show. Writes immediately, independent of Save.")
        self.set_default_button.clicked.connect(self._on_set_default)
        takeaway_row.addWidget(self.set_default_button)
        layout.addLayout(takeaway_row)

        self._entry = entry
        # Immutable values as the form was first shown. _entry itself is
        # refreshed by "Set as default" below, so it cannot safely serve as
        # a conflict baseline for other fields during a later save.
        self._form_baseline = {
            "role": entry.role,
            "short": entry.short,
            "long": entry.long,
            "source": entry.source,
            "takeaway": entry.takeaway_for(slide_id),
            "short_de": entry.short_de,
            "long_de": entry.long_de,
            "source_de": entry.source_de,
            "takeaway_de": entry.takeaway_for_de(slide_id),
        }
        self._form_baseline_en_hash = alt_images.en_text_hash(entry)
        self._translation_provenance: dict[str, object] | None = None
        takeaway_edit = QPlainTextEdit(entry.takeaway_for(slide_id))
        takeaway_edit.setFixedHeight(70)
        takeaway_edit.textChanged.connect(self._mark_dirty)
        takeaway_edit.textChanged.connect(self._refresh_takeaway_indicator)
        layout.addWidget(takeaway_edit)
        self.fields["takeaway"] = takeaway_edit
        self._refresh_takeaway_indicator()

        # Source last, not third (2026-08-27, direct instruction) -- same
        # field, just after the takeaway rather than before it.
        layout.addWidget(QLabel(
            "Source (citation/attribution -- shared across every slide "
            "using this image)"))
        source_help = QLabel(_SOURCE_HELP)
        source_help.setWordWrap(True)
        source_help.setObjectName(MUTED_LABEL)
        layout.addWidget(source_help)
        source_edit = QPlainTextEdit(entry.source)
        source_edit.setFixedHeight(50)
        source_edit.textChanged.connect(self._mark_dirty)
        layout.addWidget(source_edit)
        self.fields["source"] = source_edit

        # -- German (2026-08-24) ---------------------------------------------
        # Produced by translating the finalized English text above, not an
        # independent vision draft -- see alt_draft.translate_to_german's
        # own module docstring / LANGUAGE_NOTES.md for why. Grouped as its
        # own block below the English fields rather than interleaved field
        # by field, so "what's English, what's German" stays visually
        # obvious at a glance.
        german_header = QHBoxLayout()
        german_header.addWidget(QLabel("<b>German</b>"), stretch=1)
        self.translation_state_label = QLabel()
        self.translation_state_label.setObjectName(MUTED_LABEL)
        german_header.addWidget(self.translation_state_label)
        self.translate_button = QPushButton("Translate now")
        self.translate_button.setToolTip(
            "Translate the English short/long/takeaway above into German "
            "via a local Ollama model -- fills in the fields below, "
            "doesn't save on its own (Save draft / Save and mark reviewed "
            "still does that, same as a vision draft)."
        )
        self.translate_button.clicked.connect(self._on_translate)
        self.translation_done.connect(self._on_translation_done)
        german_header.addWidget(self.translate_button)

        # A direct shortcut for the same "Save, then translate" choice
        # _on_translate()'s own unsaved-changes dialog already offers
        # (2026-09-16, direct instruction) -- calls the exact same
        # TranscriptTab-owned callback that dialog option does (see this
        # editor's own __init__ comment on self._on_save_and_translate),
        # skipping straight past the dialog for the common case of "I just
        # edited the English text above and want it saved and translated
        # in one click," rather than making that a two-step click-then-
        # pick-an-option every time.
        save_translate_button = QPushButton("Save, then translate")
        save_translate_button.setToolTip(
            "Saves this slide's draft (every image on it, same as Save "
            "draft below) and then translates this image's just-saved "
            "English text into German -- no prompt, unlike \"Translate "
            "now\" when the English text has unsaved changes."
        )
        save_translate_button.clicked.connect(
            lambda: self._on_save_and_translate(self.reference)
        )
        german_header.addWidget(save_translate_button)
        layout.addLayout(german_header)
        self._refresh_translation_state()

        for key, label, height, initial in (
            ("short_de", "Kurzbeschreibung (short_de)", 60, entry.short_de),
            ("long_de", "Langbeschreibung (long_de)", 260, entry.long_de),
        ):
            layout.addWidget(QLabel(label))
            edit = QPlainTextEdit(initial)
            edit.setFixedHeight(height)
            layout.addWidget(edit)
            self.fields[key] = edit
            edit.textChanged.connect(self._mark_dirty)

        layout.addWidget(QLabel("Erkenntnis (takeaway_de)"))
        takeaway_de_edit = QPlainTextEdit(entry.takeaway_for_de(slide_id))
        takeaway_de_edit.setFixedHeight(70)
        takeaway_de_edit.textChanged.connect(self._mark_dirty)
        layout.addWidget(takeaway_de_edit)
        self.fields["takeaway_de"] = takeaway_de_edit

        # Source last, not third -- same as the English block above.
        layout.addWidget(QLabel(
            "Quelle (source_de -- leave blank to use the English source "
            "above unchanged)"))
        source_de_edit = QPlainTextEdit(entry.source_de)
        source_de_edit.setFixedHeight(50)
        source_de_edit.textChanged.connect(self._mark_dirty)
        layout.addWidget(source_de_edit)
        self.fields["source_de"] = source_de_edit

        self._apply_role_visibility()

    def _refresh_translation_state(self) -> None:
        state = alt_images.translation_state(self._entry)
        self.translation_state_label.setText(_TRANSLATION_STATE_LABELS[state])

    def _mark_translation_possibly_stale(self) -> None:
        """Live update (2026-08-25, direct instruction): previously this
        label only reflected translated_from_hash as of when this editor
        was built (or last reloaded from disk after a save) --
        _refresh_translation_state() was never called again after that, so
        editing the English text here -- even saving it via "Save draft" --
        never changed the label until the whole editor was rebuilt from a
        fresh disk read. Now any edit to the short/long fields flips it to
        the stale message immediately; it deliberately stays that way for
        the rest of this editing session even if the text is edited back to
        its original wording -- a live diff-against-original wasn't asked
        for, just "don't keep claiming this is in sync while I'm still
        working on it." _on_translation_done() below is the only thing
        that clears it back within this same session, since only that
        event actually makes it true again."""
        self.translation_state_label.setText(_TRANSLATION_STATE_LABELS[alt_images.STATE_STALE])

    def _on_translate(self) -> None:
        # If the English text has unsaved changes, ask which version to
        # translate (2026-08-25, direct instruction) -- silently preferring
        # the in-form draft (the previous, only behavior) meant a translate
        # you actually wanted run against the last-*saved* wording had no
        # way to ask for that without discarding the edit first. Compared
        # against self._entry (the on-disk snapshot this editor was built
        # from), not some separate dirty flag, so it's always exactly right
        # regardless of *why* the fields differ from disk.
        english_modified = (
            self.short != self._entry.short
            or self.long != self._entry.long
            or self.takeaway_text != self._entry.takeaway_for(self.slide_id)
        )
        if english_modified:
            box = QMessageBox(self)
            box.setWindowTitle("Translate now")
            box.setText(
                "The English text above has unsaved changes. Translate the "
                "current (unsaved) draft, the version currently saved on "
                "disk, or save the draft first and then translate it?"
            )
            unsaved_button = box.addButton("Unsaved draft", QMessageBox.ButtonRole.AcceptRole)
            disk_button = box.addButton("Version on disk", QMessageBox.ButtonRole.AcceptRole)
            save_button = box.addButton("Save, then translate", QMessageBox.ButtonRole.AcceptRole)
            box.addButton(QMessageBox.StandardButton.Cancel)
            box.setDefaultButton(unsaved_button)
            box.exec()
            clicked = box.clickedButton()
            if clicked is unsaved_button:
                use_short, use_long, use_takeaway = self.short, self.long, self.takeaway_text
            elif clicked is disk_button:
                use_short, use_long = self._entry.short, self._entry.long
                use_takeaway = self._entry.takeaway_for(self.slide_id)
            elif clicked is save_button:
                # Runs the same whole-slide Save draft this tab's own
                # button does (saving every image on the slide, not just
                # this one), which rebuilds every editor from the
                # now-current disk state -- including this one, so this
                # instance can't keep going past this point. The fresh
                # editor built for this same reference picks the pending
                # auto-translate request up and starts translating itself
                # (now against the version it was just saved as), no
                # further prompt needed since it's no longer "unsaved" by
                # then. See TranscriptTab._request_save_and_translate/
                # _show_slide.
                self._on_save_and_translate(self.reference)
                return
            else:
                return  # cancelled -- no Ollama task reserved yet, nothing to undo
        else:
            use_short, use_long, use_takeaway = self.short, self.long, self.takeaway_text

        provider = provider_from_combo(
            self, self._translation_model_combo, "this image's description text")
        if provider is None:
            return
        if not self.app.try_start_ollama_task("translating this image"):
            return
        self._translation_provenance = None
        self._translation_field_baseline = {
            key: self.fields[key].toPlainText()
            for key in ("short_de", "long_de", "takeaway_de")
        }
        self._translation_source_baseline = (use_short, use_long, use_takeaway)
        self.translating = True
        self.translate_button.setEnabled(False)
        self.translate_button.setText("Translating...")
        # Model comes from the tab's own "Translation model:" picker, read
        # live so a mid-session change applies immediately.
        live_entry = alt_images.ImageEntry(
            image=self.reference, short=use_short, long=use_long,
            takeaway_default=use_takeaway,
        )
        # Backgrounded (2026-08-25, direct instruction: this used to block
        # the whole app for the several-second-to-tens-of-seconds duration
        # of three sequential Ollama calls) -- translation_done is a
        # per-instance Signal, delivered back to the GUI thread the normal
        # cross-thread queued way; _translate_bg's own try/except around
        # the emit() call is what keeps a translation that outlives this
        # editor (the user picked a different slide while it was running)
        # from raising into an unhandled background-thread exception.
        threading.Thread(
            target=self._translate_bg, args=(provider, live_entry), daemon=True
        ).start()
        # Confirms this point was actually reached (2026-08-27, direct
        # report: "Save, then translate" saved but didn't visibly start
        # translating) -- the button's own "Translating..." text says the
        # same thing, but only while the editor is on screen and only if
        # someone's looking right at it; this stays in the log pane.
        self.app.log(f"Translating {self.reference} into German ({provider.label})...")

    def _translate_bg(self, provider: ChatProvider, live_entry: alt_images.ImageEntry) -> None:
        backend = alt_draft.ModelTranslationBackend(provider)
        try:
            result = backend.translate(live_entry)
        except Exception as exc:  # noqa: BLE001 -- reported via the result, not raised
            result = alt_draft.TranslationResult(error=str(exc))
        finally:
            # Always released from here, not from the GUI-thread signal
            # handler below -- self.app (the main window) outlives this
            # editor regardless of whether the editor itself is still
            # around by the time this finishes, and the Ollama mutex must
            # never stay held just because the user navigated away.
            self.app.end_ollama_task()
        try:
            self.translation_done.emit(result)
        except RuntimeError:
            # This editor panel was closed/rebuilt (e.g. the user switched
            # to a different slide, or -- 2026-08-27, direct report --
            # something rebuilt it again out from under an in-flight
            # "Save, then translate") before the translation finished --
            # nothing left to update it with; the result is discarded
            # rather than crashing this background thread, but logged
            # rather than silently dropped, since that used to be
            # indistinguishable from the translation never having started
            # at all.
            try:
                # self.app.signals.log.emit(...), not self.app.log(...): this
                # runs on _translate_bg's own background thread, and log()
                # is documented main-thread-only (the main window) -- emitting the
                # signal instead queues the call onto the GUI thread the
                # same way every compile-log line already does.
                self.app.signals.log.emit(
                    f"*** Translation of {self.reference} finished, but its "
                    f"editor panel was already gone -- discarded. ***"
                )
            except RuntimeError:
                pass  # self.app itself is gone too (app shutting down)

    def _on_translation_done(self, result: "alt_draft.TranslationResult") -> None:
        self.translating = False
        self.translate_button.setEnabled(True)
        self.translate_button.setText("Translate now")

        if not result.ok:
            self._translation_provenance = None
            self._translation_field_baseline = None
            self._translation_source_baseline = None
            self.app.log(f"*** Translation of {self.reference} failed: {result.error} ***")
            QMessageBox.warning(self, "Translation failed", result.error or "Unknown error")
            return

        self.app.log(f"Translated {self.reference} into German.")
        fields_before_translation = self._translation_field_baseline or {}
        source_before_translation = self._translation_source_baseline
        all_fields_applied = source_before_translation is not None
        for key, value in (
            ("short_de", result.short_de),
            ("long_de", result.long_de),
            ("takeaway_de", result.takeaway_de),
        ):
            edit = self.fields[key]
            # These widgets remain editable while translation runs. Apply a
            # result only to fields the user has not changed since the
            # request began; a completion must not overwrite newer typing.
            if edit.toPlainText() == fields_before_translation.get(key, edit.toPlainText()):
                edit.setPlainText(value)
            else:
                all_fields_applied = False
        source_is_current = (
            source_before_translation is None
            or (self.short, self.long, self.takeaway_text) == source_before_translation
        )
        self._translation_provenance = None
        if source_before_translation is not None:
            short, long, takeaway = source_before_translation
            requested_hash = alt_images.en_text_hash(alt_images.ImageEntry(
                image=self.reference, short=short, long=long,
                takeaway_default=takeaway,
            ))
            if all_fields_applied and result.source_hash == requested_hash:
                # Save may happen after English was edited in this form. Keep
                # the worker's exact source hash and applied German values so
                # Save can prove the merged record still matches this result.
                self._translation_provenance = {
                    "source_hash": result.source_hash,
                    "fields": {
                        "short_de": self.short_de,
                        "long_de": self.long_de,
                        "takeaway_de": self.takeaway_de_text,
                    },
                }
        self._translation_field_baseline = None
        self._translation_source_baseline = None
        self.dirty = True
        # The translation is current only if the English fields still match
        # the exact snapshot sent to the worker.
        state = alt_images.STATE_REVIEWED if source_is_current else alt_images.STATE_STALE
        self.translation_state_label.setText(_TRANSLATION_STATE_LABELS[state])

    def _refresh_status_label(self, entry: alt_images.ImageEntry, slide_hash: str) -> None:
        state = alt_images.slide_use_state(entry, self.slide_id, slide_hash)
        # "saved, not reviewed" rather than "unconfirmed": the image can be
        # auto-guessed (STATUS_AUTO) with a description already drafted for
        # it, and "unconfirmed" read as unrelated to what the adjacent
        # "Save and mark reviewed" button actually does.
        text = {
            alt_images.STATE_NONE: "no description yet",
            alt_images.STATE_DRAFT: "saved, not reviewed",
            alt_images.STATE_STALE: "needs re-check",
            alt_images.STATE_REVIEWED: "confirmed",
        }[state]
        self.status_label.setText(text)

    def _refresh_takeaway_indicator(self) -> None:
        current = self.fields["takeaway"].toPlainText().strip()
        default = self._entry.takeaway_default
        if current == default:
            self.takeaway_state_label.setText(
                "(using default)" if default else "(no default set yet)")
        else:
            self.takeaway_state_label.setText("(overridden on this slide)")

    def _on_set_default(self) -> None:
        text = self.fields["takeaway"].toPlainText().strip()

        def mutate(entries: dict[str, alt_images.ImageEntry]) -> bool:
            entry = entries.get(self.reference)
            if entry is None:
                return False
            entry.takeaway_default = text
            # This slide's own override, if it had one, now equals the
            # default it just set -- clear it so it reads as "following"
            # rather than "coincidentally identical override".
            use = entry.used_on.get(self.slide_id)
            if use is not None:
                use.takeaway = ""
            self._entry = entry
            # This immediate action changed only the takeaway baseline. Keep
            # the form's original snapshots for every other field so a
            # background update is not mistaken for a human edit at Save.
            self._form_baseline["takeaway"] = entry.takeaway_for(self.slide_id)
            return True

        alt_images.update_store(mutate)
        self._refresh_takeaway_indicator()

    def _build_preview(self, reference: str) -> QWidget:
        if reference.startswith(alt_blocks.TIKZ_PREFIX):
            # No file on disk at all -- rendered fresh from the slide's own
            # current tikz source (tikz_render.py), cached by that source's
            # own hash so re-opening the same, unchanged illustration is
            # instant. A render failure (the id renamed/removed, or a
            # genuine compile error) reports the same way a broken image
            # already does, rather than a blank panel.
            try:
                display_path = tikz_render.ensure_rendered(reference, log=self.app.log)
            except RuntimeError as exc:
                self.app.log(f"*** {exc} ***")
                return QLabel(f"<i>Could not render tikz illustration: {exc}</i>")
            pixmap = QPixmap(str(display_path))
            if pixmap.isNull():
                return QLabel(f"<i>Could not load {display_path.name}</i>")
            return self._pixmap_preview_container(pixmap)

        resolved = alt_blocks.resolve_image(reference)
        if resolved is None:
            return QLabel(f"<i>Image not found on disk: {reference}</i>")
        display_path = resolved
        if resolved.suffix.lower() == ".pdf":
            # Rendered on the fly, cached (media_render.py, 2026-08-26) --
            # the panel used to just say "can't preview" for every .pdf;
            # this is what actually shows something instead, for the
            # panel's own preview only. resolved (the real .pdf) is what
            # _build_unpreviewable_notice's "open externally" button below
            # still opens on a render failure.
            try:
                display_path = media_render.ensure_rendered(resolved)
            except RuntimeError as exc:
                self.app.log(f"*** {exc} ***")
                return self._build_unpreviewable_notice(resolved)
        elif resolved.suffix.lower() not in _VIEWABLE_SUFFIXES:
            return self._build_unpreviewable_notice(resolved)
        pixmap = QPixmap(str(display_path))
        if pixmap.isNull():
            return QLabel(f"<i>Could not load {display_path.name}</i>")
        return self._pixmap_preview_container(pixmap)

    def _pixmap_preview_container(self, pixmap: QPixmap) -> QWidget:
        # Bounded by height so a tall chart doesn't push the fields off
        # screen, and by width so a wide one doesn't stretch the panel.
        scaled = pixmap.scaled(760, 420, Qt.KeepAspectRatio, Qt.SmoothTransformation)

        label = QLabel()
        label.setPixmap(scaled)
        # Fixed to the *scaled pixmap's own* size, not left to the layout
        # (2026-08-27, direct report -- a first attempt at the border just
        # below put it around this label's own box, which a QVBoxLayout
        # stretches to the panel's full width regardless of the image's
        # own, often-narrower, aspect-ratio-preserved size, so it framed
        # empty space around the image rather than the image itself).
        # Fixed white, not theme-following: most of these PNGs have a
        # transparent background and are designed to sit on the deck's own
        # white slide background, same in the dark app theme as the light
        # one -- the app's own QLabel QSS rule (transparent, so the app
        # window's background shows through) would otherwise make a
        # transparent PNG look wrong specifically in dark mode. The thin
        # magenta border (2026-08-27, direct instruction -- a first, gray
        # attempt didn't stand out enough) marks where the image itself
        # actually ends -- otherwise indistinguishable from this label's
        # own white background for the many images that are themselves
        # white/near-white.
        label.setFixedSize(scaled.size())
        label.setStyleSheet("background-color: #ffffff; border: 1px solid #ff00ff;")

        # Centered horizontally in a wrapper, now that the label itself is
        # sized to the image rather than stretched to the panel's width --
        # without this it would sit flush left instead of centered, the
        # one visual difference from before this fix that isn't the point
        # of it.
        container = QWidget()
        # White too, not just the label above (2026-08-27, direct report --
        # the space this wrapper's own stretches open up on either side of
        # a narrower-than-panel image, previously covered by the label's
        # own white background before it was fixed-size, was rendering as
        # this app's normal (dark-mode) widget background instead once the
        # label stopped covering it).
        container.setStyleSheet("background-color: #ffffff;")
        row = QHBoxLayout(container)
        row.setContentsMargins(0, 0, 0, 0)
        row.addStretch(1)
        row.addWidget(label)
        row.addStretch(1)
        return container

    def _build_unpreviewable_notice(self, resolved: Path) -> QWidget:
        """A vector/PDF/EPS image Qt can't render inline -- text plus a
        button that opens it in its associated application (open_path,
        same pattern as opening a compiled PDF elsewhere in this project),
        so reviewing it doesn't mean leaving SlideMage to hunt for it in
        Explorer."""
        container = QWidget()
        row = QHBoxLayout(container)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(QLabel(
            f"<i>{resolved.suffix} image -- not previewable here.</i>"))
        open_button = QPushButton(f"Open {resolved.name}")
        open_button.clicked.connect(lambda: self._open_externally(resolved))
        row.addWidget(open_button)
        row.addStretch(1)
        return container

    def _open_externally(self, path: Path) -> None:
        try:
            open_path.open_in_default_app(path)
        except OSError as exc:
            QMessageBox.warning(self, "Could not open file", str(exc))

    def _mark_dirty(self) -> None:
        self.dirty = True

    def _on_role_changed(self, _button, checked: bool) -> None:
        # buttonToggled fires twice per change (one button off, one on);
        # only act on the one being switched *on*.
        if not checked:
            return
        self.dirty = True
        self.status_label.setText("changed, unsaved")
        self._apply_role_visibility()

    def _apply_role_visibility(self) -> None:
        decorative = self.role == alt_images.ROLE_DECORATIVE
        for key, edit in self.fields.items():
            # Source is attribution, not description -- independent of role.
            # A decorative Midjourney illustration still needs crediting even
            # though it carries no alt text (real precedent: dh6-Private-
            # Equity-Categorization already hand-authors exactly that
            # combination). Stays enabled regardless of the role radios.
            # source_de (2026-08-24) follows the same rule as source.
            if key in ("source", "source_de"):
                continue
            edit.setEnabled(not decorative)
            edit.setPlaceholderText(
                "Decorative -- no description needed; it is marked as a PDF "
                "artifact and noted in one line in the transcript."
                if decorative else ""
            )

    @property
    def role(self) -> str:
        for role, button in self._role_buttons.items():
            if button.isChecked():
                return role
        return alt_images.ROLE_INFORMATIVE

    @property
    def short(self) -> str:
        return self.fields["short"].toPlainText().strip()

    @property
    def long(self) -> str:
        return self.fields["long"].toPlainText().strip()

    @property
    def source(self) -> str:
        return self.fields["source"].toPlainText().strip()

    @property
    def takeaway_text(self) -> str:
        return self.fields["takeaway"].toPlainText().strip()

    @property
    def short_de(self) -> str:
        return self.fields["short_de"].toPlainText().strip()

    @property
    def long_de(self) -> str:
        return self.fields["long_de"].toPlainText().strip()

    @property
    def source_de(self) -> str:
        return self.fields["source_de"].toPlainText().strip()

    @property
    def takeaway_de_text(self) -> str:
        return self.fields["takeaway_de"].toPlainText().strip()


class PromptTuningDialog(QDialog):
    """Draft one image with an editable prompt, iterating until it reads right.

    The one place in this tab where drafting is deliberately *not* durable:
    you are experimenting, so nothing touches the store until Accept.

    A caveat worth knowing before reaching for this: prompt tuning fixes
    *misreadings* (a wrong axis maximum, a mistaken chart type). It does not
    fix what the model cannot resolve at all -- measured on slide 4r7's
    scanned bar charts, explicit anti-interpolation instructions did not stop
    qwen3-vl:32b inventing an evenly-spaced value ramp. See ALT_TEXT_NOTES.md.
    """

    def __init__(self, parent, reference: str, image_path,
                 context, backend_factory, existing_hint: str = "") -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Tune the prompt — {reference}")
        self.resize(1180, 860)
        self._reference = reference
        self._image_path = image_path
        self._context = context
        self._backend_factory = backend_factory
        self._running = False
        self.result_draft: alt_draft.DraftResult | None = None

        outer = QHBoxLayout(self)

        # Left: the image, big enough to actually check numbers against.
        left = QVBoxLayout()
        preview = QLabel()
        pixmap = QPixmap(str(image_path))
        if pixmap.isNull():
            preview.setText(f"<i>Cannot preview {image_path.name}</i>")
        else:
            preview.setPixmap(pixmap.scaled(560, 700, Qt.KeepAspectRatio,
                                            Qt.SmoothTransformation))
            # Fixed white, not theme-following -- see the matching comment
            # on _ImageEditor._build_preview. Only set once a pixmap actually
            # loaded, so the "Cannot preview" text keeps the app's normal
            # (theme-aware) label background instead of white-on-white.
            preview.setStyleSheet("background-color: #ffffff;")
        preview.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
        left.addWidget(preview, stretch=1)
        outer.addLayout(left, stretch=1)

        # Right: the controls.
        right = QVBoxLayout()
        right.addWidget(QLabel(
            "<b>Hint for this image</b> — a short correction, stored with the "
            "image and reused by future redrafts. This is the lever that "
            "works: it reaches the model without disturbing the output format."))
        self.hint_edit = QPlainTextEdit(existing_hint)
        self.hint_edit.setFixedHeight(60)
        self.hint_edit.setPlaceholderText(
            "e.g. the y-axis maximum is 6800, not 250")
        right.addWidget(self.hint_edit)

        right.addWidget(QLabel(
            "<b>System prompt</b> — applies to this run only. "
            "<span style='color:#c0392b'>Editing this often makes the model "
            "abandon the required output format and answer in prose; the hint "
            "above is the reliable lever.</span>"))
        # effective_system_prompt(), not the bare SYSTEM_PROMPT constant --
        # if the user has saved a custom default in Preferences (2026-09-23,
        # draft_prompts.py), tuning should start from what batches actually
        # send, not the original hardcoded text underneath it.
        self.prompt_edit = QPlainTextEdit(alt_draft.effective_system_prompt())
        self.prompt_edit.setFixedHeight(220)
        right.addWidget(self.prompt_edit)

        buttons_row = QHBoxLayout()
        self.draft_button = QPushButton("Draft")
        self.draft_button.clicked.connect(self._on_draft)
        buttons_row.addWidget(self.draft_button)
        reset = QPushButton("Reset prompt")
        reset.clicked.connect(
            lambda: self.prompt_edit.setPlainText(alt_draft.effective_system_prompt()))
        buttons_row.addWidget(reset)
        buttons_row.addStretch(1)
        right.addLayout(buttons_row)

        right.addWidget(QLabel("<b>Result</b>"))
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setPlaceholderText("Nothing drafted yet.")
        right.addWidget(self.output, stretch=1)

        self.buttonbox = QDialogButtonBox(
            QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        self.buttonbox.button(QDialogButtonBox.Save).setText("Accept draft")
        self.buttonbox.button(QDialogButtonBox.Save).setEnabled(False)
        self.buttonbox.accepted.connect(self.accept)
        self.buttonbox.rejected.connect(self.reject)
        right.addWidget(self.buttonbox)

        outer.addLayout(right, stretch=1)

    @property
    def hint(self) -> str:
        return self.hint_edit.toPlainText().strip()

    def _on_draft(self) -> None:
        if self._running:
            return
        self._running = True
        self.draft_button.setEnabled(False)
        self.draft_button.setText("Drafting…")
        self.output.setPlainText("Drafting…")
        QApplication.processEvents()

        context = replace(self._context, hint=self.hint)
        backend = self._backend_factory(self.prompt_edit.toPlainText())
        result = backend.draft(self._image_path, context)

        self._running = False
        self.draft_button.setEnabled(True)
        self.draft_button.setText("Draft again")

        if not result.ok:
            self.output.setPlainText(f"FAILED after {result.elapsed_s:.0f}s\n\n"
                                     f"{result.error}")
            self.buttonbox.button(QDialogButtonBox.Save).setEnabled(False)
            return

        self.result_draft = result
        warning = ("\n\n*** A value table was removed automatically: its numbers "
                   "looked interpolated rather than measured. ***"
                   if result.suspected_fabrication else "")
        self.output.setPlainText(
            f"[{result.elapsed_s:.0f}s · role suggestion: "
            f"{result.role_suggestion or 'n/a'}]\n\n"
            f"SHORT\n{result.short}\n\nLONG\n{result.long}\n\n"
            f"TAKEAWAY\n{result.takeaway}{warning}")
        self.buttonbox.button(QDialogButtonBox.Save).setEnabled(True)


_RELATED_GAP = 6
_GROUP_GAP = 28


class TranscriptTab(QWidget):
    # Drafting runs on a background thread (one image takes 10-60s, a full
    # batch takes hours) and would otherwise freeze the window. Widget
    # mutation has to happen on the GUI thread, so completion comes back
    # over a signal -- same pattern as qt_slide_source_tab.py's render
    # button. Signal(object) carries an alt_draft.BatchSummary; the drafts
    # themselves are already on disk by then.
    drafts_ready = Signal(object)
    # One image of a batch finished. Carries (image, written: bool) so the
    # list can update as the run proceeds instead of only at the end.
    batch_slide_done = Signal(object)
    # Translation's own sibling of drafts_ready (2026-08-25) -- kept as a
    # fully separate signal/state pair (_translating, not reusing
    # _drafting) rather than unifying the two batch kinds: they're
    # conceptually different operations (drafting needs a vision model and
    # an image, translation is text-only and reads whatever's already on
    # disk/in an open editor), even though both ultimately write through
    # alt_images.update_store()'s same lock and are safe to run at
    # unrelated times. Carries an alt_draft.TranslationBatchSummary.
    translations_ready = Signal(object)

    def __init__(self, app) -> None:
        super().__init__()
        self.app = app
        self._drafting = False
        self._stop_requested = False
        self._translating = False
        self._translate_stop_requested = False
        # Set before any widget is built: _populate_models and
        # _update_draft_button both read it during construction.
        self._entries: dict[str, alt_images.ImageEntry] = {}
        self.drafts_ready.connect(self._on_drafts_ready)
        self.batch_slide_done.connect(self._on_batch_slide_done)
        self.translations_ready.connect(self._on_translations_ready)
        self._rows: list[_SlideView] = []
        # Populated by _on_sort_deck_selected() from the picked deck's own
        # \slide{}-family call order (bare slide id -> position); empty
        # means "no sort" (the sort_combo's own first entry). Cached here
        # rather than re-parsing the deck file on every _visible_rows()
        # call -- that method also runs on every single list click
        # (_on_slide_selected()), not just on a combo change.
        self._sort_order: dict[str, int] = {}
        self._sort_decks: list[Deck] = []
        self._editors: list[_ImageEditor] = []
        self._current: _SlideView | None = None
        # The path of the last slide actually *shown* (i.e. the last
        # non-None view) -- see _show_slide's own comment for why this,
        # not self._current, is what its same-slide/scroll-reset check
        # needs to survive a reload's transient _show_slide(None) call.
        self._last_shown_path: Path | None = None
        # Set by _request_save_and_translate() (2026-08-26, direct
        # instruction: "Save, then translate" from an image's own Translate
        # dialog), consumed once by _show_slide() right after the save it
        # triggered reloads/rebuilds every editor on this slide -- see both.
        self._auto_translate_reference: str | None = None
        # The slide path a plain (mark_reviewed=False) _save() is about to
        # write and reload -- set by _save() itself, kept visible in
        # _visible_rows() below regardless of the currently active filter,
        # for exactly that one reload (2026-08-27, direct report --
        # confirmed directly: a plain save always clears *this slide's
        # own* "reviewed" flag, per _save()'s own mutate(); if that flips
        # the slide's state to something the active filter excludes --
        # e.g. viewing an already-reviewed slide under the "Reviewed"
        # filter -- it silently drops out of the now-filtered list the
        # instant it's saved, so reload()'s preserve-by-path matching in
        # _populate_list() can no longer find it and falls back to
        # whatever's at row 0 of an unrelated slide instead. For a plain
        # "Save draft" that meant landing on the wrong slide's form
        # (reported as an unwanted scroll-to-top, but same_slide was
        # correctly seeing a genuinely different slide -- this was never
        # really a scroll bug for that case). For "Save, then translate"
        # specifically it also meant the auto-translate pickup below could
        # never find a matching editor on that wrong slide either, so
        # nothing after "Saved draft for ..." ever ran, let alone logged
        # anything. Never set for mark_reviewed=True -- moving on to a
        # slide that still needs attention is the wanted behavior there.
        # Consumed (cleared) unconditionally by the very next real
        # (non-None) _show_slide() call, not only inside the
        # auto-translate pickup -- see that same spot.
        self._pin_visible_path: Path | None = None
        # The slide_list row actually showing right now -- kept in sync
        # only when a selection change is actually committed (2026-08-25),
        # so _on_slide_selected can revert slide_list's own current row
        # back here if the user declines to discard an in-flight
        # translation (see _has_in_flight_translation()).
        self._current_row_index = -1
        # True for the whole duration of _populate_list()'s own systemic
        # clear()+reselect (2026-08-25) -- see _on_slide_selected's own
        # comment for why that path must never trigger the in-flight-
        # translation warning meant for an interactive row click.
        self._suppress_switch_warning = False
        # A list rebuild can be cancelled if its selection would replace an
        # unsaved image form. Remember the last accepted controls so a
        # rejected filter/sort change can restore their visible state.
        self._allow_dirty_selection = False
        self._last_filter_index = 0
        self._last_sort_index = 0

        outer = QVBoxLayout(self)

        # Two toolbars (2026-09-18, direct instruction). Top: the things that
        # act on images via a model -- translation, drafting, transcript
        # preview -- in that order. Second: finding/filtering slides.
        # Two gap sizes only: controls that belong together (a label, its
        # dropdown, the button acting on it) sit _RELATED_GAP apart, distinct
        # functions _GROUP_GAP apart. QHBoxLayout adds its own spacing on each
        # side of every item, so addSpacing(n) yields n + 2 * spacing().
        toolbar = QHBoxLayout()
        toolbar.setSpacing(_RELATED_GAP)
        nav_toolbar = QHBoxLayout()
        nav_toolbar.setSpacing(_RELATED_GAP)

        toolbar.addWidget(QLabel("Model:"))
        self.model_combo = QComboBox()
        self._populate_models()
        toolbar.addWidget(self.model_combo)

        self.draft_button = QPushButton("Draft descriptions")
        self.draft_button.clicked.connect(self._on_draft)
        toolbar.addWidget(self.draft_button)
        self.draft_all_button = QPushButton("Draft all…")
        self.draft_all_button.clicked.connect(self._on_draft_all)
        self.draft_all_button.setToolTip(
            "Draft every image that still needs one, unattended. Writes each\n"
            "image as it finishes, so it can be stopped and resumed later."
        )
        toolbar.addWidget(self.draft_all_button)

        self.tune_button = QPushButton("Tune prompt…")
        self.tune_button.clicked.connect(self._on_tune_prompt)
        self.tune_button.setToolTip(
            "Draft one image with an editable prompt, iterating until it reads\n"
            "the chart correctly. Nothing is written until you accept."
        )
        toolbar.addWidget(self.tune_button)

        clear_button = QPushButton("Clear draft")
        clear_button.clicked.connect(self._on_clear_draft)
        clear_button.setToolTip(
            "Discard this slide's unreviewed image draft(s). Never touches a\n"
            "reviewed description. An image used on other slides too is\n"
            "cleared for all of them -- there is only one shared copy."
        )
        toolbar.addWidget(clear_button)

        toolbar.addSpacing(_GROUP_GAP - 2 * _RELATED_GAP)
        # German translation (2026-08-25): a different model list than
        # drafting's (all models, not
        # only vision ones -- translation is text-only, so any
        # installed model works, not just a vision-capable one) and a
        # separate "all" action, per direct instruction to make the model
        # choice itself pickable rather than hardcoded.
        toolbar.addWidget(QLabel("Translation model:"))
        self.translation_model_combo = QComboBox()
        self._populate_translation_models()
        toolbar.addWidget(self.translation_model_combo)

        self.translate_all_button = QPushButton("Translate all…")
        self.translate_all_button.clicked.connect(self._on_translate_all)
        self.translate_all_button.setToolTip(
            "Translate every image's short/long/takeaway into German, for\n"
            "every image that has English text and no current (non-stale)\n"
            "translation yet. Writes each image as it finishes, so it can\n"
            "be stopped and resumed later. Each image's own \"Translate now\"\n"
            "button (in its editor panel below) uses this same model."
        )
        toolbar.addWidget(self.translate_all_button)

        toolbar.addSpacing(_GROUP_GAP - 2 * _RELATED_GAP)
        # A single-slide transcript *preview* -- whole-deck generation
        # (write_transcript(), written to transcripts/) moved to the main
        # deck table's own "Create Transcript" button and the deck-editor
        # tab's own "Transcript" button (2026-09-17, direct instruction:
        # this tab's job is reviewing one slide at a time already, a deck
        # picker here was solving a different problem). No deck to pick
        # any more -- the currently-selected slide (self._current.row) is
        # already unambiguous, and generate_single_slide() below needs no
        # deck identity at all (see its own docstring: a slide's inclusion
        # in a *deck* is a separate question from previewing it directly).
        toolbar.addWidget(QLabel("Transcript version:"))
        self.version_combo = QComboBox()
        self.version_combo.addItems(list(transcript.STUDENT_VERSIONS))
        self.version_combo.setToolTip(
            "Student versions only -- only matters here for this slide's own\n"
            "\\deckonly/\\deckvisible-style conditionals, if it has any."
        )
        toolbar.addWidget(self.version_combo)

        generate_button = QPushButton("Generate transcript")
        generate_button.clicked.connect(self._on_generate_transcript)
        generate_button.setToolTip(
            "Preview this one slide's transcript entry -- never written to\n"
            "disk, shown in its own tab instead."
        )
        toolbar.addWidget(generate_button)
        toolbar.addStretch(1)
        outer.addLayout(toolbar)

        nav_toolbar.addWidget(QLabel("Show:"))
        self.filter_combo = QComboBox()
        self.filter_combo.addItems([label for label, _ in _FILTERS])
        self.filter_combo.currentIndexChanged.connect(self._populate_list)
        nav_toolbar.addWidget(self.filter_combo)

        nav_toolbar.addSpacing(_RELATED_GAP)
        nav_toolbar.addWidget(QLabel("Sort:"))
        self.sort_combo = QComboBox()
        self.sort_combo.addItem("(no sort)")
        for deck in scan_decks():
            if deck.archived:
                continue
            self.sort_combo.addItem(deck.name)
            self._sort_decks.append(deck)
        self.sort_combo.setToolTip(
            "Order the slide list below by a deck's own \\slide{} order --\n"
            "any slide not in that deck sorts to the end, keeping its\n"
            "position from whatever order was in effect before."
        )
        self.sort_combo.currentIndexChanged.connect(self._on_sort_deck_selected)
        nav_toolbar.addWidget(self.sort_combo)

        rescan_button = QPushButton("Rescan")
        rescan_button.clicked.connect(self.reload)
        nav_toolbar.addWidget(rescan_button)

        nav_toolbar.addSpacing(_GROUP_GAP - 2 * _RELATED_GAP)
        # An inline dropdown, not a button opening a dialog (2026-09-18,
        # direct instruction: picking a slide from the popup should land on
        # it immediately, no separate "go" click) -- same QLineEdit +
        # QCompleter pattern as the main window's own "Find slide:" search
        # box (the main window's "Go to slide…"), just wired to this tab's own
        # _find_and_show_slide() instead of opening a slide editor.
        # completer.activated fires directly from a popup click (or Enter
        # on a highlighted suggestion) with no OK button in between;
        # returnPressed covers typing a full id/slug and pressing Enter
        # without ever opening the popup.
        nav_toolbar.addWidget(QLabel("Find slide:"))
        self.find_slide_entry = QLineEdit()
        self.find_slide_entry.setFixedWidth(220)
        self.find_slide_entry.setToolTip(
            "Jump straight to a slide by its id or id-slug, regardless of "
            "the current Show:/Sort: filters -- only works for a slide "
            "that has at least one image, same as this tab's own list."
        )
        # Backed by a model rather than a fixed list, so reload() can
        # replace its contents: a completer built from a plain list stays
        # frozen at whatever slides existed when this tab was created, and
        # never suggested a slide added since, even after "Rescan". Starts
        # with every slide; reload() narrows it to the slides this tab
        # actually lists (those with images), which is all it can jump to.
        self._find_slide_model = QStringListModel(slide_ids.list_id_slugs(), self)
        find_slide_completer = QCompleter(self._find_slide_model, self)
        find_slide_completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        find_slide_completer.setFilterMode(Qt.MatchFlag.MatchContains)
        find_slide_completer.activated.connect(self._on_find_slide_activated)
        self.find_slide_entry.setCompleter(find_slide_completer)
        self.find_slide_entry.returnPressed.connect(self._on_find_slide_return_pressed)
        nav_toolbar.addWidget(self.find_slide_entry)

        nav_toolbar.addSpacing(_GROUP_GAP - 2 * _RELATED_GAP)
        source_button = QPushButton("Open slide source")
        source_button.clicked.connect(self._on_open_source)
        nav_toolbar.addWidget(source_button)

        nav_toolbar.addStretch(1)
        self.summary_label = QLabel("")
        nav_toolbar.addWidget(self.summary_label)
        outer.addLayout(nav_toolbar)

        splitter = QSplitter(Qt.Horizontal)

        self.slide_list = QListWidget()
        self.slide_list.currentRowChanged.connect(self._on_slide_selected)
        splitter.addWidget(self.slide_list)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        # No bottom margin: the images area's bottom edge must line up with
        # the slide list's (which sits in the splitter with no margin).
        _margins = right_layout.contentsMargins()
        right_layout.setContentsMargins(_margins.left(), _margins.top(), _margins.right(), 0)
        # Save buttons sit right of the slide title, above the images
        # (2026-09-18, direct instruction), so the image/description area
        # can extend all the way down.
        header_row = QHBoxLayout()
        self.slide_header = QLabel("")
        self.slide_header.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.slide_header.setWordWrap(True)
        header_row.addWidget(self.slide_header, stretch=1)
        self.save_button = QPushButton("Save draft")
        self.save_button.clicked.connect(lambda: self._save(mark_reviewed=False))
        header_row.addWidget(self.save_button)
        # Text set per-slide by _show_slide() (_review_button_label()) --
        # plain "Save and mark reviewed" for one image, "Save and mark
        # <u>all images</u> reviewed" for more than one, so the button
        # itself flags a multi-image slide rather than saying "all images"
        # unconditionally, which would stop standing out the moment every
        # slide's button said it. No slide selected yet at construction
        # time, so this starts at the plain, single-image default.
        self.review_button = QPushButton(_review_button_label(1))
        self.review_button.clicked.connect(lambda: self._save(mark_reviewed=True))
        header_row.addWidget(self.review_button)
        right_layout.addLayout(header_row)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.editor_host = QWidget()
        self.editor_layout = QVBoxLayout(self.editor_host)
        self.editor_layout.addStretch(1)
        self.scroll.setWidget(self.editor_host)
        right_layout.addWidget(self.scroll, stretch=1)

        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)
        outer.addWidget(splitter, stretch=1)

        self._loaded = False
        self.slide_header.setText("<i>Opening…</i>")

    # -- data ---------------------------------------------------------------

    def ensure_loaded(self) -> None:
        """First scan, run when the tab is first opened rather than at launch
        (the main window's _on_page_changed) -- it walks every slide, hashes the
        images they reference, and writes any new rows to the JSON store."""
        if self._loaded:
            return
        self._loaded = True
        self.reload()

    def reload(self, preserve: Path | None = None, *, keep_dirty: bool = False) -> bool:
        allow_dirty = False
        if self._any_editor_dirty():
            if keep_dirty:
                self.app.log(
                    "Refresh deferred because the current image form has unsaved edits; "
                    "save or discard those edits before rescanning."
                )
                return False
            choice = QMessageBox.question(
                self, "Unsaved image edits",
                "Rescanning will discard unsaved image edits. Continue?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if choice != QMessageBox.StandardButton.Yes:
                return False
            allow_dirty = True
        report = alt_images.sync_store()
        if report.added:
            self.app.log(
                f"alt-text store: added {len(report.added)} new image row(s)."
            )
        if report.new_uses:
            self.app.log(
                f"alt-text store: {len(report.new_uses)} new slide/image "
                f"reference(s) found."
            )
        self._entries = alt_images.load_store()

        views: list[_SlideView] = []
        for row in alt_blocks.scan_slides_raw():
            slide_hash = alt_images.slide_context_hash(row.path)
            state = _slide_state(row, self._entries, slide_hash)
            views.append(_SlideView(row=row, state=state, slide_hash=slide_hash))
        self._rows = views
        self._find_slide_model.setStringList(sorted(
            view.row.path.name[: -len("-current.tex")] for view in views))
        self._populate_list(preserve, allow_dirty=allow_dirty)
        return True

    def _visible_rows(self) -> list[_SlideView]:
        _, states = _FILTERS[self.filter_combo.currentIndex()]
        rows = self._rows if states is None else [
            view for view in self._rows if view.state in states
        ]
        # See self._pin_visible_path's own comment for why this exists --
        # forces one specific slide to stay visible/selectable through a
        # reload even if its own state no longer matches the active
        # filter, without touching the filter itself.
        if self._pin_visible_path is not None and not any(
            view.row.path == self._pin_visible_path for view in rows
        ):
            pinned = next(
                (view for view in self._rows if view.row.path == self._pin_visible_path),
                None,
            )
            if pinned is not None:
                rows = [pinned, *rows]
        if self._sort_order:
            # Stable sort (Python's own guarantee): every slide missing
            # from the chosen deck shares the same fallback key
            # (len(self._sort_order), one past the last real position) and
            # so keeps whatever relative order it already had -- "listed
            # at the end" without needing a second explicit tiebreaker.
            rows = sorted(
                rows,
                key=lambda view: self._sort_order.get(view.row.slide_id, len(self._sort_order)),
            )
        return rows

    def _on_sort_deck_selected(self, index: int) -> None:
        if index <= 0:
            self._sort_order = {}
        else:
            deck = self._sort_decks[index - 1]  # -1: combo index 0 is "(no sort)"
            self._sort_order = {
                call.id: position for position, call in enumerate(parse_slide_calls(deck))
            }
        self._populate_list()

    def _populate_list(
        self, preserve: Path | None = None, *, allow_dirty: bool = False
    ) -> None:
        """Rebuild the list, re-selecting `preserve` **by path**, not by index.

        Selecting by index was a real bug: repopulating fires
        currentRowChanged, which reassigns self._current, and after a save
        the row a slide sits at can change (it may leave the active filter
        entirely). A later save then wrote its descriptions into whichever
        slide the list happened to land on -- observed writing slide 22s's
        file while slide 3px was on screen.
        """
        if self._any_editor_dirty() and not allow_dirty:
            choice = QMessageBox.question(
                self, "Unsaved image edits",
                "Refreshing or changing the slide list will discard unsaved "
                "image edits. Continue?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if choice != QMessageBox.StandardButton.Yes:
                self.filter_combo.blockSignals(True)
                self.filter_combo.setCurrentIndex(self._last_filter_index)
                self.filter_combo.blockSignals(False)
                self.sort_combo.blockSignals(True)
                self.sort_combo.setCurrentIndex(self._last_sort_index)
                self.sort_combo.blockSignals(False)
                return
            allow_dirty = True

        previous_allow_dirty = self._allow_dirty_selection
        self._allow_dirty_selection = allow_dirty or previous_allow_dirty
        self._suppress_switch_warning = True
        try:
            # Signals blocked through the whole clear()+rebuild below
            # (2026-08-27, direct report -- confirmed directly): Qt fires
            # currentRowChanged not just once from clear() (already relied
            # on elsewhere in this file) but repeatedly *while* addItem()
            # is refilling a list that has nothing selected yet, at
            # whatever row it happens to auto-select at each point --
            # invisible with only a handful of rows (nothing else to land
            # on), but with a real, hundred-row filtered list this fired a
            # *real*, premature _on_slide_selected()/_show_slide() call on
            # some unrelated mid-rebuild row, which is exactly what
            # consumed "Save, then translate"'s one-shot
            # _auto_translate_reference/_pin_visible_path before the
            # intended final selection below ever got to use them. Nothing
            # here needs any of those intermediate, purely-mechanical
            # "current row" changes -- only the deliberate final one below.
            self.slide_list.blockSignals(True)
            try:
                self.slide_list.clear()
                for view in self._visible_rows():
                    row = view.row
                    item = QListWidgetItem(
                        f"{_STATE_MARKERS[view.state]}  {row.slide_id} — {row.title}"
                    )
                    item.setToolTip(
                        f"{alt_images.STATE_LABELS[view.state]}\n{row.path.name}\n"
                        + "\n".join(row.images)
                    )
                    item.setData(Qt.UserRole, row.path)
                    item.setForeground(QColor(_STATE_COLORS[view.state]))
                    self.slide_list.addItem(item)
            finally:
                self.slide_list.blockSignals(False)

            self._update_summary()
            if not self.slide_list.count():
                self._show_slide(None)
                return

            target_row = 0
            if preserve is not None:
                for index in range(self.slide_list.count()):
                    if self.slide_list.item(index).data(Qt.UserRole) == preserve:
                        target_row = index
                        break
            self.slide_list.setCurrentRow(target_row)
            # setCurrentRow only emits currentRowChanged when Qt's own
            # notion of the current row actually changes -- which, after
            # clear() above (confirmed directly: fires currentRowChanged(-1)
            # as a side effect, updating _current_row_index to -1 via the
            # normal connected slot), is true for essentially every
            # target_row. The explicit re-show below exists only as a
            # fallback for whatever edge case leaves it not firing (e.g. Qt
            # auto-selecting row 0 on the very first addItem() into a list
            # that was empty, making this setCurrentRow(0) a no-op) -- so
            # it must only run when _on_slide_selected hasn't already: two
            # calls in a row silently double-build this slide's editors
            # (2026-08-26, confirmed directly -- discovered because the
            # second, redundant build was throwing away a translation
            # in-flight-triggered on the first one's editor, but it wasted
            # work and lost editor state unconditionally even before that).
            if self._current_row_index != target_row:
                self._on_slide_selected(target_row)
        finally:
            self._suppress_switch_warning = False
            self._allow_dirty_selection = previous_allow_dirty
        self._last_filter_index = self.filter_combo.currentIndex()
        self._last_sort_index = self.sort_combo.currentIndex()

    # -- selection ----------------------------------------------------------

    def _on_slide_selected(self, index: int) -> None:
        rows = self._visible_rows()
        target_view = rows[index] if 0 <= index < len(rows) else None

        current_path = self._current.row.path if self._current is not None else None
        target_path = target_view.row.path if target_view is not None else None
        if (
            not self._suppress_switch_warning
            and not self._allow_dirty_selection
            and target_path != current_path
            and self._any_editor_dirty()
        ):
            confirm = QMessageBox.question(
                self, "Unsaved image edits",
                "Switching slides will discard unsaved image edits. Switch anyway?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if confirm != QMessageBox.StandardButton.Yes:
                self.slide_list.blockSignals(True)
                self.slide_list.setCurrentRow(self._current_row_index)
                self.slide_list.blockSignals(False)
                return

        # Warn before discarding an in-flight translation (2026-08-25,
        # direct instruction) -- only for an actual, interactive switch to
        # a different slide (a direct currentRowChanged from clicking a row
        # in the list). _populate_list()'s own systemic clear()+reselect
        # during a reload sets _suppress_switch_warning around the whole
        # thing, since that's not the user choosing to switch away -- and
        # QListWidget.clear() itself fires currentRowChanged(-1) as a side
        # effect (confirmed directly), which would otherwise trip this
        # check on a list that's mid-rebuild.
        if not self._suppress_switch_warning and self._has_in_flight_translation():
            confirm = QMessageBox.question(
                self, "Translation in progress",
                "A German translation is still being generated for an "
                "image on this slide. Switching to a different slide now "
                "will discard the result when it finishes. Switch anyway?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if confirm != QMessageBox.StandardButton.Yes:
                # currentRowChanged already fired -- the list's own
                # selection has already moved by the time this runs, so
                # "declining" means moving it back, not preventing it.
                # Signals blocked so that revert doesn't re-enter this
                # same method.
                self.slide_list.blockSignals(True)
                self.slide_list.setCurrentRow(self._current_row_index)
                self.slide_list.blockSignals(False)
                return

        self._current_row_index = index
        self._show_slide(target_view)

    def _has_in_flight_translation(self) -> bool:
        return any(editor.translating for editor in self._editors)

    def _show_slide(self, view: _SlideView | None) -> None:
        # Reset scroll position only on an actual switch to a *different*
        # slide (2026-08-26, direct report) -- this runs after every save
        # too (reload(preserve=...) re-lands here even when nothing about
        # the current selection changed), and jumping to the top on a
        # plain "Save draft"/"Save, then translate" that keeps you on the
        # same slide was reported as unwanted (three times over -- see the
        # two fixes below); landing on a genuinely different slide (arrow
        # keys, a list click, or "Save and mark reviewed" moving you to
        # the next one) should still start at the top.
        #
        # Compared against self._last_shown_path, not self._current
        # (2026-08-26, direct report -- comparing against self._current
        # still jumped to the top on every "Save draft"). Root cause,
        # confirmed directly: _populate_list()'s own slide_list.clear()
        # fires currentRowChanged(-1) as a side effect (already relied on
        # elsewhere in this file), which reaches this same method as
        # _show_slide(None) *in between* the old slide and its own
        # post-save reshow, and was clobbering self._current right before
        # the reshow that followed it could compare against it.
        # self._last_shown_path is left untouched whenever view is None,
        # so it survives that transient call intact.
        same_slide = view is not None and self._last_shown_path == view.row.path
        if view is not None:
            self._last_shown_path = view.row.path
            # Consumed here, unconditionally, not only inside the
            # auto-translate pickup further below (2026-08-27, direct
            # report -- a plain "Save draft" needs this pin too, not just
            # "Save, then translate", and a plain save never touches
            # _auto_translate_reference at all). One-shot regardless of
            # which kind of save set it: by the time a real (non-None)
            # view reaches here, whatever _populate_list() cycle needed it
            # has already used it, in both of its own _visible_rows()
            # calls (building the list, then resolving this very view).
            self._pin_visible_path = None

        # Explicitly captured and restored (2026-08-26, direct report --
        # "Save, then translate" still jumped to the top even with the fix
        # above), rather than just leaving the scrollbar's value alone and
        # trusting it survives the teardown-and-rebuild below unchanged.
        # It doesn't reliably: tearing every editor down first (right
        # below) can itself shrink this scroll area's content down to
        # nothing for a moment, which a *real* running Qt event loop can
        # process and use to clamp the scrollbar's value before the new
        # editors ever get added back -- a plain headless test never
        # caught this because processing that intermediate resize/layout
        # event happens on a real event loop tick this method's own single
        # synchronous call never yields to. QTimer.singleShot(0, ...)
        # explicitly waits for exactly that tick (after the new editors
        # below are already in place and Qt has sized this scroll area for
        # them) before restoring the value, rather than racing it.
        restore_scroll = self.scroll.verticalScrollBar().value() if same_slide else 0
        self._current = view
        for editor in self._editors:
            editor.setParent(None)
            editor.deleteLater()
        self._editors = []

        if view is None:
            self.slide_header.setText("<i>No slide selected.</i>")
            self.save_button.setEnabled(False)
            self.review_button.setEnabled(False)
            self.review_button.setText(_review_button_label(1))
            self._update_draft_button()
            return

        row = view.row
        self.save_button.setEnabled(True)
        self.review_button.setEnabled(True)
        self.review_button.setText(_review_button_label(len(row.images)))
        self.slide_header.setText(
            f"<b>{row.slide_id} — {row.title}</b><br>"
            f"{row.path.name} · {alt_images.STATE_LABELS[view.state]}"
        )

        for reference in row.images:
            entry = alt_images.lookup(self._entries, reference)
            if entry is None:
                entry = alt_images.ImageEntry(image=reference)
            editor = _ImageEditor(
                self.app, reference, entry, row.slide_id, view.slide_hash,
                self.translation_model_combo, self._request_save_and_translate,
                self._on_replace_image_clicked,
            )
            self.editor_layout.insertWidget(self.editor_layout.count() - 1, editor)
            self._editors.append(editor)

        # Pick up a pending "Save, then translate" request (2026-08-26,
        # direct instruction) -- set by _request_save_and_translate() right
        # before the _save() that led here. The fresh editor for that same
        # reference now holds exactly the version that was just saved, so
        # its own _on_translate() proceeds straight to translating instead
        # of re-prompting about unsaved changes. Cleared unconditionally
        # (even if the reference is gone -- e.g. the image was removed from
        # this slide) so a stale request can never fire on some later,
        # unrelated slide switch.
        if self._auto_translate_reference is not None:
            reference = self._auto_translate_reference
            self._auto_translate_reference = None
            matched = False
            for editor in self._editors:
                if editor.reference == reference:
                    matched = True
                    # Wrapped (2026-08-27, direct report: "Save, then
                    # translate" saves but doesn't visibly start
                    # translating) -- this is a *direct* Python call, not
                    # a Qt signal emission, deep inside the synchronous
                    # save/reload/rebuild chain that started from the
                    # original editor's own button click; an exception
                    # here would propagate all the way back up through
                    # that whole chain, silently aborting everything still
                    # to run in this method (including the scroll-restore
                    # call below) along with it, and PySide6's own
                    # exception hook only prints to stderr -- invisible in
                    # the compiled app's windowed (console-less) build.
                    # Logged instead of guessed at further.
                    try:
                        editor._on_translate()
                    except Exception as exc:  # noqa: BLE001 -- surfaced, not swallowed
                        self.app.log(
                            f"*** \"Save, then translate\" failed to start "
                            f"translating {reference}: {exc!r} ***"
                        )
                    break
            if not matched:
                # Another silent-failure point closed off (2026-08-27,
                # direct report) -- this used to do nothing at all and log
                # nothing if no rebuilt editor's own .reference happened to
                # match, which would look identical to "the button click
                # was silently ignored" from the outside.
                self.app.log(
                    f"*** \"Save, then translate\" could not find "
                    f"{reference} among this slide's own images after "
                    f"saving -- translation not started. ***"
                )

        self._update_draft_button()
        self._schedule_scroll_restore(restore_scroll)

    def _schedule_scroll_restore(self, target: int) -> None:
        """Keeps re-applying `target` to this scroll area's vertical
        scrollbar for a short real-time window, rather than trusting one
        deferred call to land after Qt has settled the new editors' final
        layout (2026-08-27, direct report -- v3.3.19's QTimer.singleShot(0,
        ...) *still* wasn't enough for "Save, then translate", even though
        the exact same mechanism was verified headlessly). Most likely
        explanation, not confirmable in the offscreen/headless test
        environment this project's own test scripts run in (no real
        window, so no real native resize/paint round-trips to begin with):
        a real onscreen QScrollArea can take more than one event-loop tick
        to finish resizing for newly (re)built content, especially with
        several stacked editor panels each with their own nested layout,
        so a single-tick restore can still race a range recalculation that
        hasn't finished yet and get silently clamped back to 0.
        verticalScrollBar().rangeChanged fires on every recalculation
        while that settles; re-applying `target` each time it fires, for
        up to _SCROLL_RESTORE_WINDOW_MS, converges on the right value
        however many passes it actually takes, then stops listening."""
        bar = self.scroll.verticalScrollBar()

        def _apply(*_args) -> None:
            try:
                bar.setValue(target)
            except RuntimeError:
                pass  # this tab was closed/destroyed in the meantime

        def _stop() -> None:
            try:
                bar.rangeChanged.disconnect(_apply)
            except (RuntimeError, TypeError):
                pass  # already disconnected, or the bar itself is gone

        bar.rangeChanged.connect(_apply)
        _apply()  # covers the common case where the range is final already
        QTimer.singleShot(_SCROLL_RESTORE_WINDOW_MS, _stop)

    # -- saving -------------------------------------------------------------

    def _request_save_and_translate(self, reference: str) -> None:
        """"Save, then translate" from an image editor's Translate dialog
        (2026-08-26, direct instruction). Runs the same whole-slide Save
        draft the tab's own button does -- not a partial, single-image
        save -- so this stays exactly consistent with every other save
        (takeaway default/override promotion, un-reviewing this slide's
        own use, etc.), then lets _show_slide()'s reload-driven rebuild
        pick `reference` up and start translating it once its fresh editor
        exists. See _show_slide's own handling of _auto_translate_reference.
        Pinning this slide visible through that reload regardless of the
        active filter is _save()'s own job now, not this method's -- see
        its own comment, right where it sets self._pin_visible_path."""
        self._auto_translate_reference = reference
        self._save(mark_reviewed=False)

    def _save(self, mark_reviewed: bool) -> None:
        view = self._current
        if view is None:
            return
        row = view.row
        # Captured before anything can repopulate the list underneath us --
        # every write below targets this slide, never self._current again.
        slide_id = row.slide_id
        target_path = row.path

        # Pinned visible through the reload at the end of this method
        # regardless of the active filter, for a plain save (2026-08-27,
        # direct report -- "Save draft" alone was *also* jumping to the
        # top of a different slide's form, not just "Save, then
        # translate"). Root cause, confirmed directly: a plain save always
        # clears *this slide's own* "reviewed" flag (just below), which
        # can silently drop it out of a filter like "Reviewed" the instant
        # it's saved -- reload()'s preserve-by-path matching in
        # _populate_list() then can't find it and falls back to whatever's
        # at row 0 of some unrelated slide instead, which is a genuinely
        # different slide landing (hence the scroll reset -- same_slide
        # correctly sees it as such) rather than a scroll-restore bug on
        # its own. Not pinned for mark_reviewed=True ("Save and mark
        # reviewed"): moving on to a slide that still needs attention once
        # this one no longer does is the explicitly wanted behavior there.
        if not mark_reviewed:
            self._pin_visible_path = target_path

        if mark_reviewed:
            missing = [
                editor.reference for editor in self._editors
                if editor.role == alt_images.ROLE_INFORMATIVE and not editor.long
            ]
            if missing:
                QMessageBox.warning(
                    self, "Nothing to review yet",
                    "These images are marked informative but have no long "
                    "description yet:\n\n" + "\n".join(missing)
                    + "\n\nEither write one, or set the role to decorative.",
                )
                return

        # The hash is recomputed here rather than reused from the scan: the
        # slide file may have been edited since the list was last populated,
        # and stamping a stale hash would mark the slide reviewed against
        # content nobody actually looked at.
        current_hash = alt_images.slide_context_hash(target_path)
        today = _dt.date.today().isoformat()

        def mutate(entries: dict[str, alt_images.ImageEntry]) -> bool:
            for editor in self._editors:
                entry = entries.get(editor.reference)
                if entry is None:
                    entry = alt_images.ImageEntry(image=editor.reference)
                    entries[editor.reference] = entry
                baseline = editor._form_baseline
                # The store can change while this form is open (draft and
                # translation workers write each image as they finish). Only
                # copy fields the person changed in this form; every untouched
                # value stays at its newest persisted value.
                if editor.role != baseline["role"]:
                    entry.role = editor.role
                if editor.short != baseline["short"]:
                    entry.short = editor.short
                if editor.long != baseline["long"]:
                    entry.long = editor.long
                if editor.source != baseline["source"]:
                    entry.source = editor.source

                use = entry.used_on.setdefault(slide_id, alt_images.SlideUse())
                typed = editor.takeaway_text
                if typed != baseline["takeaway"]:
                    if typed == entry.takeaway_default:
                        use.takeaway = ""            # follows the latest default
                    elif not entry.takeaway_default and typed:
                        entry.takeaway_default = typed
                        use.takeaway = ""
                    else:
                        use.takeaway = typed         # a real slide-specific override

                german_changed = (
                    editor.short_de != baseline["short_de"]
                    or editor.long_de != baseline["long_de"]
                    or editor.takeaway_de_text != baseline["takeaway_de"]
                )
                if editor.short_de != baseline["short_de"]:
                    entry.short_de = editor.short_de
                if editor.long_de != baseline["long_de"]:
                    entry.long_de = editor.long_de
                if editor.source_de != baseline["source_de"]:
                    entry.source_de = editor.source_de

                typed_de = editor.takeaway_de_text
                if typed_de != baseline["takeaway_de"]:
                    if typed_de == entry.takeaway_default_de:
                        use.takeaway_de = ""
                    elif not entry.takeaway_default_de and typed_de:
                        entry.takeaway_default_de = typed_de
                        use.takeaway_de = ""
                    else:
                        use.takeaway_de = typed_de

                provenance = editor._translation_provenance
                provenance_fields = provenance.get("fields", {}) if provenance else {}
                provenance_matches = (
                    bool(provenance)
                    and provenance_fields.get("short_de") == entry.short_de
                    and provenance_fields.get("long_de") == entry.long_de
                    and provenance_fields.get("takeaway_de") == entry.takeaway_for_de(slide_id)
                    and provenance.get("source_hash") == alt_images.en_text_hash(entry)
                )
                if provenance_matches:
                    entry.translated_from_hash = str(provenance["source_hash"])
                elif german_changed:
                    if not entry.short_de and not entry.long_de:
                        entry.translated_from_hash = ""
                    elif alt_images.en_text_hash(entry) == editor._form_baseline_en_hash:
                        # A manual German edit can be considered in sync
                        # only while the latest English source still matches
                        # the form's original source.
                        entry.translated_from_hash = alt_images.en_text_hash(entry)
                    else:
                        # The user edited German against an older form, but
                        # the live English text has since changed (possibly
                        # alongside a worker translation). Do not retain that
                        # worker's current hash: it would falsely bless the
                        # human-edited German as matching the newer English.
                        # An empty source hash keeps the pair visibly stale.
                        entry.translated_from_hash = ""
                if mark_reviewed:
                    entry.status = alt_images.STATUS_REVIEWED
                    use.reviewed = today
                    use.stored_hash = current_hash
                else:
                    # "Save draft" now explicitly un-reviews this slide's
                    # own use of the image (2026-08-25, direct instruction)
                    # -- previously left review status untouched, so a
                    # by-hand edit via "Save draft" could silently keep
                    # showing as "Reviewed" against text nobody had
                    # actually re-checked. Only this slide's own SlideUse
                    # is cleared, not entry.status (shared across every
                    # slide using this image) -- another slide that
                    # already reviewed the same image is unaffected;
                    # slide_use_state() already returns STATE_DRAFT purely
                    # from use.reviewed being empty, regardless of
                    # entry.status.
                    use.reviewed = ""
            return True

        alt_images.update_store(mutate)
        for editor in self._editors:
            editor.dirty = False
        self.app.log(
            f"{'Reviewed' if mark_reviewed else 'Saved draft for'} {target_path.name}"
        )
        self.reload(preserve=target_path)

    def _on_open_source(self) -> None:
        if self._current is not None:
            self.app.open_slide_editor(self._current.row.path, return_to=self)

    def _on_find_slide_activated(self, text: str) -> None:
        """Fires the instant a completer suggestion is picked -- by a
        popup click or by Enter on a highlighted one -- landing on that
        slide with no further click needed (2026-09-18, direct
        instruction: the previous "Find slide…" button's own OK step was
        one click too many).

        The immediate `.clear()` this used to call here didn't actually
        stick (2026-09-25, direct report) -- QLineEdit.setCompleter()
        wires its own internal "fill the line edit with the picked
        completion" slot to this same `activated` signal, and since that
        wiring is set up *after* this method's own connect() call above,
        Qt runs it *after* this handler on every emission, silently
        overwriting whatever `.clear()` just did with the completion
        text. Deferring the actual clear to the next event-loop
        iteration (QTimer.singleShot(0, ...)) runs it strictly after
        that internal slot has already fired, so it's the one that
        sticks. _on_find_slide_return_pressed below has no such
        interference -- it only fires when Enter is pressed with no
        completer suggestion active in the first place -- so its own
        direct `.clear()` is left as is."""
        if text.strip():
            self._find_and_show_slide(text)
        QTimer.singleShot(0, self.find_slide_entry.clear)

    def _on_find_slide_return_pressed(self) -> None:
        """Enter pressed with nothing highlighted in the completer popup
        (typing a full id/slug and pressing Enter without ever opening
        it) -- same destination as _on_find_slide_activated, just reading
        the field's own text instead of the popup's chosen one."""
        text = self.find_slide_entry.text().strip()
        self.find_slide_entry.clear()
        if text:
            self._find_and_show_slide(text)

    def _find_and_show_slide(self, text: str) -> None:
        """Jumps this tab's own slide list to `text` (a bare slide id, or
        an "id-slug" as the completer above offers it) and shows its
        images -- only ever searches self._rows (every slide with at least
        one image, i.e. everything scan_slides_raw() found), so a slide
        with no images correctly reports as not found here rather than
        silently doing nothing."""
        candidate_id = text.split("-", 1)[0].strip().lower()
        match = next(
            (view for view in self._rows if view.row.slide_id.lower() == candidate_id),
            None,
        )
        if match is None:
            # Fallback for anything that didn't parse as "id-rest" cleanly
            # (a bare slug fragment, stray whitespace, ...) -- match against
            # the slide file's own "<id>-<slug>" stem instead.
            match = next(
                (view for view in self._rows
                 if view.row.path.name.lower().startswith(text.lower())),
                None,
            )
        if match is None:
            QMessageBox.information(
                self, "Find slide",
                f"No slide matching \"{text}\" with any images was found. "
                "This tab only lists slides that reference at least one "
                "image -- there's nothing here to show for one that doesn't.",
            )
            return
        # Force "All slides with images" (index 1 in _FILTERS) so the match
        # is guaranteed visible regardless of whatever Show:/Sort: filter
        # is currently active, without otherwise touching the sort order.
        self.filter_combo.blockSignals(True)
        self.filter_combo.setCurrentIndex(1)
        self.filter_combo.blockSignals(False)
        self._populate_list(preserve=match.row.path)

    # -- replacing an image --------------------------------------------------

    def _on_replace_image_clicked(self, editor: "_ImageEditor") -> None:
        """"Replace image…" (2026-09-18, direct instruction): pick a file
        from disk, copy it into media/ under a name the user picks (with
        the project's naming convention shown as help text), repoint this
        slide's own reference at it, optionally repoint every other slide
        sharing the old image too, and offer to delete the old image's now-
        orphaned description once nothing references it any more.

        Never touches the old file on disk -- only the new copy and the
        slide(s)' own .tex text change; if the user declines replacing it
        everywhere, the old file and its description both legitimately stay
        in use elsewhere and are left alone.
        """
        old_reference = editor.reference
        view = self._current
        if view is None or view.row.slide_id != editor.slide_id:
            return  # the shown slide changed out from under this click

        picked, _filter = QFileDialog.getOpenFileName(
            self, "Choose replacement image", "",
            "Images (*.png *.jpg *.jpeg *.pdf *.eps);;All files (*.*)",
        )
        if not picked:
            return
        source_path = Path(picked)

        old_name = old_reference.rsplit("/", 1)[-1]
        suggested_stem = old_name.rsplit(".", 1)[0] if "." in old_name else old_name
        extension = source_path.suffix.lower() or ".png"

        new_stem = _ask_new_filename(self, suggested_stem, extension)
        if new_stem is None:
            return
        new_name = f"{new_stem}{extension}"
        media_dir = PROJECT_ROOT / "media"
        dest_path = media_dir / new_name
        if dest_path.exists():
            confirm = QMessageBox.question(
                self, "Replace image",
                f"media/{new_name} already exists. Overwrite it?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if confirm != QMessageBox.StandardButton.Yes:
                return
        new_reference = f"media/{new_name}"

        # Every slide (besides this one) currently recorded as using the
        # old image -- offered as an optional batch, not applied
        # unconditionally: "used on 12 slides" is exactly the case where
        # silently repointing all of them without asking would be a
        # surprise, not a convenience.
        other_slide_ids = sorted(sid for sid in editor._entry.used_on if sid != editor.slide_id)
        targets = {editor.slide_id: view.row.path}
        if other_slide_ids:
            detail = "\n".join(f"  • {sid}" for sid in other_slide_ids)
            confirm = QMessageBox.question(
                self, "Replace image",
                f"\"{old_reference}\" is also used on {len(other_slide_ids)} "
                f"other slide(s):\n\n{detail}\n\n"
                "Replace it there too? (\"No\" only replaces it on the "
                "slide currently shown -- the others keep pointing at the "
                "old file, which is left on disk either way.)",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if confirm == QMessageBox.StandardButton.Yes:
                by_id = {v.row.slide_id: v.row for v in self._rows}
                for sid in other_slide_ids:
                    row = by_id.get(sid)
                    if row is not None:
                        targets[sid] = row.path

        try:
            media_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(source_path), str(dest_path))
        except OSError as exc:
            QMessageBox.critical(self, "Replace image", f"Could not copy the file: {exc}")
            return
        self.app.log(f"Copied {source_path} to media/{new_name}")

        changed_slides: list[str] = []
        failures: list[str] = []
        rows_by_id = {v.row.slide_id: v.row for v in self._rows}
        for sid, path in targets.items():
            # The raw text this *specific* slide actually spells the old
            # reference as (extension present or not) can differ from
            # editor.reference, which only reflects the currently-shown
            # slide's own spelling -- resolved the same way _show_slide()
            # matched a raw reference to this entry in the first place.
            raw_reference = old_reference
            row = rows_by_id.get(sid)
            if row is not None:
                for candidate in row.images:
                    candidate_entry = alt_images.lookup(self._entries, candidate)
                    if candidate_entry is not None and candidate_entry.image == editor._entry.image:
                        raw_reference = candidate
                        break
            try:
                text = path.read_text(encoding="utf-8")
            except OSError as exc:
                failures.append(f"{sid}: {exc}")
                continue
            new_text, count = alt_blocks.replace_image_reference(text, raw_reference, new_reference)
            if count == 0:
                failures.append(f"{sid}: reference not found in {path.name} as written")
                continue
            try:
                path.write_text(new_text, encoding="utf-8")
            except OSError as exc:
                failures.append(f"{sid}: {exc}")
                continue
            changed_slides.append(sid)

        if changed_slides:
            self.app.log(
                f"Replaced {old_reference} with {new_reference} on: "
                + ", ".join(changed_slides)
            )
        if failures:
            QMessageBox.warning(
                self, "Replace image",
                "Some slides could not be updated:\n\n" + "\n".join(failures),
            )

        open_elsewhere = sorted(
            path.name for sid, path in targets.items()
            if sid in changed_slides and path in self.app._slide_source_tabs
        )
        if open_elsewhere:
            QMessageBox.information(
                self, "Replace image",
                "These slides are open in an editor tab and were updated "
                "on disk, but their open tab still shows the old text -- "
                "close and reopen to see the change:\n\n"
                + "\n".join(open_elsewhere),
            )

        # Is the old image now unused everywhere? Only then does its stored
        # description actually still describe a picture something shows.
        remaining_uses = set(editor._entry.used_on) - set(changed_slides)
        if not remaining_uses:
            has_content = bool(
                editor._entry.short or editor._entry.long
                or editor._entry.takeaway_default or editor._entry.source
            )
            if has_content:
                confirm = QMessageBox.question(
                    self, "Replace image",
                    f"\"{old_reference}\" is no longer used on any slide. "
                    "Delete its now-unused description (short/long/"
                    "takeaway/source text)?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                )
                if confirm == QMessageBox.StandardButton.Yes:
                    alt_images.delete_entry(editor._entry.image)
                    self.app.log(f"Deleted now-unused description for {editor._entry.image}")
            else:
                # Nothing worth keeping (never drafted, never reviewed) --
                # no point asking about an empty row.
                alt_images.delete_entry(editor._entry.image)

        self.reload(preserve=view.row.path)

    def _update_summary(self) -> None:
        counts = {state: 0 for state in _STATE_COLORS}
        for view in self._rows:
            counts[view.state] += 1
        self.summary_label.setText(
            f"{counts[alt_images.STATE_REVIEWED]} reviewed · "
            f"{counts[alt_images.STATE_STALE]} need re-check · "
            f"{counts[alt_images.STATE_DRAFT]} draft · "
            f"{counts[alt_images.STATE_NONE]} undescribed"
        )

    def _any_editor_dirty(self) -> bool:
        return any(editor.dirty for editor in self._editors)

    def _on_batch_slide_done(self, payload) -> None:
        """One image of a running batch finished. Update every slide row
        that shows it.

        Deliberately does not re-filter or re-sort the list: a row vanishing
        from under the cursor while the user is working through the queue is
        worse than a stale filter. The next Rescan applies filters afresh.
        """
        image, written = payload
        if not written:
            return

        self._entries = alt_images.load_store()
        touched_paths: set[Path] = set()
        for view in self._rows:
            if image not in view.row.images:
                continue
            view.state = _slide_state(view.row, self._entries, view.slide_hash)
            touched_paths.add(view.row.path)

        for index in range(self.slide_list.count()):
            item = self.slide_list.item(index)
            path = item.data(Qt.UserRole)
            if path not in touched_paths:
                continue
            view = next((v for v in self._rows if v.row.path == path), None)
            if view is None:
                continue
            item.setText(f"{_STATE_MARKERS[view.state]}  {view.row.slide_id} — {view.row.title}")
            item.setForeground(QColor(_STATE_COLORS[view.state]))
            item.setToolTip(f"{alt_images.STATE_LABELS[view.state]}\n{view.row.path.name}\n"
                            + "\n".join(view.row.images))

        self._update_summary()

        # Refresh the open slide only if the user has not typed into it --
        # otherwise their in-progress edits would vanish mid-keystroke.
        if (self._current is not None and self._current.row.path in touched_paths
                and not self._any_editor_dirty()):
            current = next(v for v in self._rows if v.row.path == self._current.row.path)
            self._show_slide(current)

    # -- transcript ---------------------------------------------------------

    def _on_generate_transcript(self) -> None:
        """Preview -- not write -- this one slide's own transcript entry.
        Same pattern as qt_slide_source_tab.py's own "Render transcript"
        button (_on_render_transcript): generate_single_slide() never
        touches disk beyond its own throwaway tempfile.mkdtemp(), deleted
        before it returns, so this satisfies "don't save it, just show it"
        with no extra scratch-path bookkeeping of its own."""
        if self._current is None:
            return
        row = self._current.row
        version = self.version_combo.currentText()
        id_slug = row.path.stem.removesuffix("-current")
        own = slide_language.own_language(id_slug)
        language = "de" if own == "DE" else "en"

        try:
            source_text = row.path.read_text(encoding="utf-8")
        except OSError as exc:
            QMessageBox.critical(self, "Transcript failed", str(exc))
            return

        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            result = transcript.generate_single_slide(
                source_text, row.slide_id, version, language)
        except Exception as exc:
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self, "Transcript failed", str(exc))
            self.app.log(f"*** Transcript generation failed: {exc} ***")
            return
        finally:
            if QApplication.overrideCursor() is not None:
                QApplication.restoreOverrideCursor()

        html = transcript.to_html(result, f"Transcript: {id_slug}")
        tab = self.app.open_transcript_preview(row.slide_id, f"Transcript: {id_slug}")
        tab.set_html(html)
        if result.undescribed:
            self.app.log(
                f"Transcript preview for {id_slug}: still has an undescribed "
                f"image; flagged in place in the preview."
            )

    # -- drafting -----------------------------------------------------------

    def _populate_models(self, models: list[str] | None = None) -> None:
        if models is None:
            models = OllamaProvider().list_models(vision_only=True)
        # Preselects the image-description default from Settings -> "AI
        # models" (2026-09-26, direct instruction; replaces the earlier
        # remember-the-last-pick behaviour -- picking another model here
        # applies to this tab only), when it is in today's list.
        if fill_model_combo(self.model_combo, "image_description", models,
                            "(no vision models available)"):
            self.model_combo.setToolTip(
                "Vision-capable Ollama models, plus Claude models when an API "
                "key is set and Local AI only is off")
        else:
            self.model_combo.setToolTip(
                "Ollama is unreachable or has no vision-capable model "
                "installed, and no Claude API key is set."
            )

    def _populate_translation_models(self, models: list[str] | None = None) -> None:
        if models is None:
            models = OllamaProvider().list_models()
        # The translation default from Settings -> "AI models" takes
        # priority over the hardcoded DEFAULT_TRANSLATION_MODEL, same "only
        # if still in today's list" guard as _populate_models() above --
        # falls back to the hardcoded default when none is set or that
        # model isn't installed here.
        if fill_model_combo(self.translation_model_combo, "translation", models,
                            "(no AI models available)",
                            fallback_local=alt_draft.DEFAULT_TRANSLATION_MODEL):
            self.translation_model_combo.setToolTip(
                "Every model Ollama currently has -- translation is "
                "text-only, so any of them works, not just a vision-"
                "capable one -- plus Claude models when enabled."
            )
        else:
            self.translation_model_combo.setToolTip(
                "Ollama is unreachable or has no models installed, and no "
                "Claude API key is set."
            )

    def refresh_model_preferences(
        self, models: list[str], vision_models: list[str]
    ) -> None:
        """Re-fill both model pickers (and re-preselect their Settings ->
        "AI models" defaults) after the Settings dialog closes -- called by
        the main window, so a changed default or a deleted model reaches this
        already-open tab."""
        self._populate_models(vision_models)
        self._populate_translation_models(models)
        self._update_draft_button()

    def _current_draftable(self) -> list[tuple[str, Path]]:
        if self._current is None:
            return []
        return alt_draft.draftable_images(self._current.row, self._entries)

    def _update_draft_button(self) -> None:
        """Enabled only when there is something to draft and a model to do it."""
        if self._drafting:
            self.draft_button.setEnabled(False)
            self.tune_button.setEnabled(False)
            return  # draft_all_button is owned by the batch handlers here
        has_model = self.model_combo.isEnabled()
        has_target = bool(self._current is not None and self._current_draftable())
        self.draft_button.setEnabled(has_model and has_target)
        self.tune_button.setEnabled(has_model and has_target)
        if not has_model:
            self.draft_button.setToolTip("No Ollama vision model available")
        elif not has_target:
            self.draft_button.setToolTip(
                "Nothing to draft on this slide — its images are decorative, "
                "or are vector files the model cannot read."
            )
        else:
            self.draft_button.setToolTip(
                "Generate an unreviewed draft description for this slide's "
                "images. Overwrites what is currently in the fields; nothing "
                "is written to disk until you save."
            )

    def _backend(self) -> alt_draft.ModelBackend | None:
        """The backend for the picked model; None (user already told) when
        there is none or a cloud request was declined. Called before an
        Ollama slot is reserved, on the GUI thread."""
        provider = provider_from_combo(
            self, self.model_combo, "the slide's text and the images to describe")
        return None if provider is None else alt_draft.ModelBackend(provider)

    def _on_draft(self) -> None:
        """Draft the selected slide's images. Writes unreviewed drafts."""
        view = self._current
        if view is None or self._drafting:
            return
        backend = self._backend()
        if backend is None or not self.app.try_start_ollama_task("drafting descriptions"):
            return
        self._begin_drafting(f"Drafting {view.row.path.name} via {backend.label}…")
        threading.Thread(
            target=self._draft_one_bg, args=(view, backend), daemon=True
        ).start()

    def _draft_one_bg(self, view: _SlideView, backend) -> None:
        summary = alt_draft.BatchSummary()
        pairs = alt_draft.draftable_images(view.row, self._entries)
        try:
            for reference, resolved in pairs:
                context = alt_draft.build_context(view.row.path, reference)
                result = backend.draft(resolved, context)
                summary.attempted += 1
                summary.seconds += result.elapsed_s
                if not result.ok:
                    summary.errors.append(f"{reference}: {result.error}")
                elif result.suspected_fabrication:
                    summary.fabrications += 1
                    summary.errors.append(
                        f"{reference}: value table removed - the numbers "
                        f"looked interpolated, not measured")
                elif result.role_suggestion == alt_images.ROLE_DECORATIVE:
                    summary.errors.append(
                        f"{reference}: model suggests this image is decorative"
                    )
                if alt_draft.apply_one_draft(reference, result, backend.label):
                    summary.written += 1
                else:
                    summary.skipped += 1
        except Exception as exc:
            summary.failed += 1
            summary.errors.append(str(exc))
        self.drafts_ready.emit(summary)

    def _on_tune_prompt(self) -> None:
        """Open the prompt-tuning dialog for one image on the current slide."""
        view = self._current
        if view is None or self._drafting:
            return
        provider = provider_from_combo(
            self, self.model_combo, "the slide's text and the image to describe")
        if provider is None or not self.app.try_start_ollama_task("tuning a description prompt"):
            return
        try:
            pairs = alt_draft.draftable_images(view.row, self._entries)
            if not pairs:
                QMessageBox.information(
                    self, "Nothing to draft",
                    "This slide has no image the model can read.")
                return

            reference, resolved = pairs[0]
            if len(pairs) > 1:
                self.app.log(
                    f"Tuning the prompt for the first of {len(pairs)} images "
                    f"({reference}).")

            context = alt_draft.build_context(view.row.path, reference)
            entry = alt_images.lookup(self._entries, reference)

            # The lock is held for the dialog's whole modal lifetime, not
            # just one call -- "Draft again" inside it can fire off several
            # separate Ollama requests before the user is done.
            dialog = PromptTuningDialog(
                self, reference, resolved, context,
                backend_factory=lambda prompt: alt_draft.ModelBackend(
                    provider, system_prompt=prompt),
                existing_hint=entry.hint if entry else "",
            )
            if dialog.exec() != QDialog.Accepted or dialog.result_draft is None:
                return

            result = dialog.result_draft
            # Write it the same way a normal draft is written, so the review
            # state, the drafted-by marker and the reviewed-never-overwritten
            # guarantee are all identical -- the only difference is the prompt.
            if not alt_draft.apply_one_draft(reference, result, result.model):
                QMessageBox.warning(
                    self, "Not written",
                    "This image is reviewed (or was reviewed while this dialog "
                    "was open), so the draft was not written over it. Clear the "
                    "review first if you want to replace it.")
                return

            # Persist the hint alongside the description for future redrafts.
            if dialog.hint:
                def mutate(entries: dict[str, alt_images.ImageEntry], ref=reference,
                           hint=dialog.hint) -> bool:
                    target = entries.get(ref)
                    if target is None:
                        return False
                    target.hint = hint
                    return True
                alt_images.update_store(mutate)

            self.app.log(f"Tuned draft written for {view.row.path.name} [{reference}]")
            self.reload(preserve=view.row.path)
        finally:
            self.app.end_ollama_task()

    # -- batch --------------------------------------------------------------

    def _on_draft_all(self) -> None:
        if self._drafting:                      # button doubles as Stop
            if self._stop_requested:
                # Clicked again while "Stopping…" is showing (2026-08-25,
                # direct instruction) -- rescind it. should_stop's own
                # lambda reads _stop_requested fresh on its next check, so
                # flipping it back to False here is all the batch runner
                # needs to keep going with no other change.
                self._stop_requested = False
                self.draft_all_button.setText("Stop")
                self.app.log("Stop rescinded -- drafting continues.")
            else:
                self._stop_requested = True
                self.draft_all_button.setText("Stopping…")
                self.app.log("Stopping after the current image…")
            return

        backend = self._backend()
        if backend is None or not self.app.try_start_ollama_task("drafting descriptions"):
            return

        queue = alt_draft.images_needing_drafts()
        redraftable = alt_draft.images_needing_drafts(
            redraft_unless_model=backend.label)
        other_model = max(len(redraftable) - len(queue), 0)

        if not queue and not other_model:
            QMessageBox.information(
                self, "Nothing to draft",
                "Every describable image already has a draft or a reviewed "
                "description.")
            self.app.end_ollama_task()
            return

        box = QMessageBox(self)
        box.setWindowTitle("Draft all descriptions")
        box.setText(f"Draft {len(queue)} image(s) using {backend.label}?")
        box.setInformativeText(
            "Each image is written to disk as it finishes, so you can stop "
            "any time and resume later — the queue is recomputed from the "
            "files.\n\nReviewed descriptions are never overwritten. Expect "
            "this to take hours; it can run in the background."
        )
        checkbox = None
        if other_model:
            checkbox = QCheckBox(
                f"Also redraft {other_model} image(s) drafted by a different model"
            )
            box.setCheckBox(checkbox)
        box.setStandardButtons(QMessageBox.Ok | QMessageBox.Cancel)
        box.button(QMessageBox.Ok).setText("Start")
        if box.exec() != QMessageBox.Ok:
            self.app.end_ollama_task()
            return

        if checkbox is not None and checkbox.isChecked():
            queue = redraftable

        self._stop_requested = False
        self._begin_drafting(
            f"Drafting {len(queue)} image(s) via {backend.label}. "
            f"Stop any time — finished images stay on disk."
        )
        self.draft_all_button.setText("Stop")
        self.draft_all_button.setEnabled(True)
        # Reuses the "Close" buttons' own red-outline/red-fill-on-hover
        # style (ui/kit/theme.py) while this button doubles as Stop, so a
        # drafting run in progress is visually obvious, not just a text
        # change -- objectName after the widget is already styled needs a
        # polish to pick up the new QSS rule (same fix
        # qt_slide_preview_popup.py's own status_label already uses).
        self.draft_all_button.setObjectName(CLOSE_BUTTON)
        self.draft_all_button.style().unpolish(self.draft_all_button)
        self.draft_all_button.style().polish(self.draft_all_button)
        threading.Thread(
            target=self._draft_batch_bg, args=(queue, backend), daemon=True
        ).start()

    def _draft_batch_bg(self, queue, backend) -> None:
        def progress(index, total, job):
            # signals.log.emit, not self.app.log() directly: this callback
            # runs on this method's own background thread (alt_draft.run_batch
            # calls it synchronously, in-line with each image), and log() is
            # documented main-thread-only -- see _translate_bg's own fix for
            # the same bug.
            self.app.signals.log.emit(f"  [{index}/{total}] {job.image} (via {job.slide_id})")

        try:
            summary = alt_draft.run_batch(
                queue, backend,
                on_progress=progress,
                on_slide_done=lambda image, written: (
                    self.batch_slide_done.emit((image, written))),
                should_stop=lambda: self._stop_requested,
            )
        except Exception as exc:
            summary = alt_draft.BatchSummary(failed=1, errors=[str(exc)])
        self.drafts_ready.emit(summary)

    # -- translating ----------------------------------------------------------

    def _on_translate_all(self) -> None:
        if self._translating:                    # button doubles as Stop
            self._translate_stop_requested = True
            self.translate_all_button.setText("Stopping…")
            self.app.log("Stopping translation after the current image…")
            return

        provider = provider_from_combo(
            self, self.translation_model_combo, "the descriptions of all untranslated images")
        if provider is None or not self.app.try_start_ollama_task("translating images"):
            return

        backend = alt_draft.ModelTranslationBackend(provider)
        queue = alt_draft.images_needing_translation()
        if not queue:
            QMessageBox.information(
                self, "Nothing to translate",
                "Every image with English text already has a current "
                "(non-stale) German translation.")
            self.app.end_ollama_task()
            return

        box = QMessageBox(self)
        box.setWindowTitle("Translate all images")
        box.setText(f"Translate {len(queue)} image(s) into German using {backend.label}?")
        box.setInformativeText(
            "Each image is written to disk as it finishes, so you can stop "
            "any time and resume later — the queue is recomputed from the "
            "files.\n\nThese are unreviewed translations, same as a drafted "
            "description: check them before relying on them."
        )
        box.setStandardButtons(QMessageBox.Ok | QMessageBox.Cancel)
        box.button(QMessageBox.Ok).setText("Start")
        if box.exec() != QMessageBox.Ok:
            self.app.end_ollama_task()
            return

        self._translate_stop_requested = False
        self._translating = True
        self.translate_all_button.setText("Stop")
        self.app.log(
            f"Translating {len(queue)} image(s) via {backend.label}. "
            f"Stop any time — finished images stay on disk."
        )
        threading.Thread(
            target=self._translate_batch_bg, args=(queue, backend), daemon=True
        ).start()

    def _translate_batch_bg(self, queue: list[str], backend) -> None:
        def progress(index: int, total: int, image: str) -> None:
            # Same background-thread fix as _draft_batch_bg's own progress().
            self.app.signals.log.emit(f"  [{index}/{total}] {image}")

        try:
            summary = alt_draft.run_translation_batch(
                queue, backend,
                on_progress=progress,
                should_stop=lambda: self._translate_stop_requested,
            )
        except Exception as exc:
            summary = alt_draft.TranslationBatchSummary(failed=1, errors=[str(exc)])
        self.translations_ready.emit(summary)

    def _on_translations_ready(self, summary: "alt_draft.TranslationBatchSummary") -> None:
        self._translating = False
        self._translate_stop_requested = False
        self.translate_all_button.setText("Translate all…")
        self.app.end_ollama_task()

        for line in summary.errors:
            self.app.log(f"    {line}")

        minutes = summary.seconds / 60
        self.app.log(
            f"{'Stopped' if summary.stopped_early else 'Finished'} translating: "
            f"{summary.written} image(s) translated, {summary.skipped} skipped, "
            f"{summary.failed} failed, in {minutes:.1f} min. "
            f"All translations are unreviewed — check them before relying on them."
        )

        preserve = self._current.row.path if self._current is not None else None
        self.reload(preserve=preserve, keep_dirty=True)

    # -- shared drafting state ----------------------------------------------

    def _begin_drafting(self, message: str) -> None:
        self._drafting = True
        self.draft_button.setEnabled(False)
        self.draft_button.setText("Drafting…")
        self.draft_all_button.setEnabled(False)
        self.app.log(message)

    def _on_drafts_ready(self, summary: alt_draft.BatchSummary) -> None:
        """Runs on the GUI thread once a draft or a whole batch finishes.

        Drafts are written to the store by the worker, so unlike the first
        version of this there is nothing to route back into widgets and
        nothing to lose if the selection moved while it ran -- the result is
        already durable. Reloading picks it up wherever the user now is.
        """
        self._drafting = False
        self._stop_requested = False
        self.draft_button.setText("Draft descriptions")
        self.draft_all_button.setText("Draft all…")
        self.draft_all_button.setEnabled(True)
        self.draft_all_button.setObjectName("")
        self.draft_all_button.style().unpolish(self.draft_all_button)
        self.draft_all_button.style().polish(self.draft_all_button)
        self.app.end_ollama_task()

        for line in summary.errors:
            self.app.log(f"    {line}")

        minutes = summary.seconds / 60
        self.app.log(
            f"{'Stopped' if summary.stopped_early else 'Finished'}: "
            f"{summary.written} image(s) drafted, {summary.skipped} skipped, "
            f"{summary.failed} failed, in {minutes:.1f} min. "
            + (f"{summary.fabrications} value table(s) removed as unreliable. "
               if summary.fabrications else "")
            + (f"{summary.skipped_changed} skipped because you reviewed them "
               f"mid-run. " if summary.skipped_changed else "")
            +
            f"All drafts are unreviewed — check every number against the image."
        )

        preserve = self._current.row.path if self._current is not None else None
        self.reload(preserve=preserve, keep_dirty=True)

    # -- clearing -----------------------------------------------------------

    def _on_clear_draft(self) -> None:
        view = self._current
        if view is None:
            return
        row = view.row

        entries = alt_images.load_store()
        clearable = [
            reference for reference in row.images
            if (entry := alt_images.lookup(entries, reference)) is not None
            and alt_images.image_state(entry) == alt_images.STATE_DRAFT
        ]
        if not clearable:
            QMessageBox.information(
                self, "Nothing to clear",
                "Clear draft only removes an *unreviewed* description. None "
                "of this slide's images are in that state.")
            return

        shared = [
            reference for reference in clearable
            if len(alt_images.lookup(entries, reference).used_on) > 1
        ]
        warning = ""
        if shared:
            warning = (
                "\n\nNote: " + ", ".join(shared) + " " +
                ("is" if len(shared) == 1 else "are") +
                " also used on other slides — there is one shared "
                "description, so clearing it clears it everywhere."
            )
        if QMessageBox.question(
            self, "Clear draft",
            f"Discard the unreviewed draft for {', '.join(clearable)}?" + warning,
        ) != QMessageBox.Yes:
            return

        def mutate(entries: dict[str, alt_images.ImageEntry]) -> bool:
            changed = False
            for reference in clearable:
                entry = entries.get(reference)
                if entry is None or alt_images.image_state(entry) != alt_images.STATE_DRAFT:
                    continue
                entry.short = ""
                entry.long = ""
                entry.drafted_by = ""
                changed = True
            return changed

        alt_images.update_store(mutate)
        self.app.log(f"Cleared draft(s) on {row.path.name}: {', '.join(clearable)}")
        self.reload(preserve=row.path)
