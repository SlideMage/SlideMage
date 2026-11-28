# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""QR insertion, replacement, and validation in the editor."""
from __future__ import annotations

import pytest

from slidemage import qr_code
from slidemage.ui.dialogs import qr_code as qr_dialog
from slidemage.ui.dialogs.qr_code import QRCodeDialog
from slidemage.ui.workspace.source_view import SourcePane
from test_insert_popovers_gui import FakeApp


@pytest.fixture
def dialog(ctx, qapp):
    (ctx.root / "media").mkdir(exist_ok=True)
    return QRCodeDialog(None, ctx)


def choose_kind(dialog, kind):
    dialog.kind_box.setCurrentIndex(dialog.kind_box.findData(kind))


def test_custom_png_insertion_uses_the_caption_height_and_corner(dialog, ctx):
    dialog.url_url.setText("https://example.org")
    dialog.caption_mode.set_current(qr_code.CAPTION_CUSTOM)
    dialog._on_caption_mode(qr_code.CAPTION_CUSTOM)
    dialog.caption_text.setText("QR 1")
    dialog.format_box.set_current("png")
    dialog.height_box.setValue(0.8)
    dialog.placement_box.setCurrentIndex(dialog.placement_box.findData("se"))
    dialog._on_insert()
    assert dialog.snippet.startswith(r"\cornerfigure[corner=se]{\SMQRCode[0.80\textheight]{media/qr-1.png}{QR 1}")
    assert (ctx.root / "media/qr-1.png").is_file()


def test_event_and_contact_codes_are_written(dialog, ctx):
    choose_kind(dialog, qr_code.KIND_EVENT)
    dialog.event_title.setText("Guest lecture")
    assert dialog.spec().fields["all_day"] == "" and len(dialog.spec().fields["start"]) == 16
    dialog.all_day.setChecked(True)
    assert len(dialog.spec().fields["start"]) == 10
    assert dialog.error_box.currentData() == "L"          # follows the kind
    dialog._on_insert()
    assert dialog.result() == dialog.DialogCode.Accepted and len(list((ctx.root / "media").glob("qr-*.pdf"))) == 1

    other = QRCodeDialog(None, ctx)
    choose_kind(other, qr_code.KIND_CONTACT)
    other.contact_name.setText("Ada Lovelace")
    other.contact_city.setText("Graz")
    other._on_caption_mode(qr_code.CAPTION_CONTENT)
    other._on_insert()
    assert other.snippet.endswith("{Ada Lovelace}") and len(list((ctx.root / "media").glob("qr-*.pdf"))) == 2


def test_an_invalid_email_is_reported_inline_and_nothing_is_written(dialog, ctx):
    choose_kind(dialog, qr_code.KIND_EMAIL)
    dialog.email_to.setText("not-an-address")
    dialog._on_insert()
    assert dialog.result() != dialog.DialogCode.Accepted and dialog.snippet == ""
    assert "not an email address" in dialog.problem.text() and not dialog.problem.isHidden()
    assert not list((ctx.root / "media").glob("qr-*"))
    dialog.update_preview()
    assert "not an email address" in dialog.preview.text()      # the message stands in for the picture


def test_the_file_name_follows_the_input_until_edited_and_a_copy_is_saved(dialog, ctx, tmp_path):
    dialog.url_url.setText("https://example.org/one")
    dialog.update_preview()
    assert dialog.name_edit.text() == "qr-example-org-one"
    dialog.name_edit.setText("mine")
    dialog._on_name_edited("mine")
    dialog.url_url.setText("https://example.org/two")
    dialog.update_preview()
    assert dialog.name_edit.text() == "mine"
    copy = tmp_path / "out" / "copy.svg"
    dialog.copy_path.setText(str(copy))         # a path first: ticking an empty one opens the file picker
    dialog.copy_check.setChecked(True)
    dialog._on_insert()
    assert copy.is_file() and (ctx.root / "media" / "qr-mine.pdf").is_file()


def test_the_error_level_follows_the_kind_until_chosen(dialog):
    choose_kind(dialog, qr_code.KIND_CONTACT)
    assert dialog.error_box.currentData() == "L"
    dialog._on_error_chosen(0)
    dialog.error_box.setCurrentIndex(dialog.error_box.findData("H"))
    choose_kind(dialog, qr_code.KIND_URL)
    assert dialog.error_box.currentData() == "H"


@pytest.fixture
def pane(ctx, qapp):
    ctx.slides_dir.mkdir()
    return SourcePane(FakeApp(ctx))


def test_a_code_in_the_editor_opens_as_update_and_replaces_the_call(ctx, pane, monkeypatch):
    slides = ctx.slides_dir
    created = qr_code.create(ctx, qr_code.QRSpec(qr_code.KIND_URL, {"url": "https://example.org"}), height=0.5,
                             caption_mode=qr_code.CAPTION_CONTENT)       # the stored caption mode comes back
    path = slides / "abc-EN-Demo-current.tex"
    path.write_text(f"before\n{created.snippet}\nafter\n", encoding="utf-8")
    pane.show_path(path)
    editor = pane.current.editor
    editor.go_to_line(2)
    opened = []

    def fake_exec(self):
        opened.append(self)
        self.url_url.setText("https://example.org/new")
        self._on_insert()
        return self.result()

    monkeypatch.setattr(QRCodeDialog, "exec", fake_exec)
    pane._open_qr_dialog()
    dialog = opened[0]
    assert dialog.insert_button.text() == "Update" and dialog.height_box.value() == 0.5
    text = editor.text()
    assert text.count("\\SMQRCode") == 1 and "after" in text and text.startswith("before\n")
    assert f"{{{created.image}}}" in text and "example.org/new" in text
    assert len(list((ctx.root / "media").glob("qr-*.pdf"))) == 1       # the same file, regenerated


def test_insert_qr_inserts_into_the_selection_and_is_off_in_a_frozen_version(ctx, pane, monkeypatch):
    slides = ctx.slides_dir
    path = slides / "abc-EN-Demo-current.tex"
    path.write_text("x\n", encoding="utf-8")
    frozen = slides / "abc-EN-Demo-v1-0-0.tex"
    frozen.write_text("old", encoding="utf-8")
    pane.show_path(path)

    def fake_exec(self):
        self.url_url.setText("https://example.org")
        self._on_insert()
        return self.result()

    monkeypatch.setattr(QRCodeDialog, "exec", fake_exec)
    pane._on_insert_chosen("ext:1")                 # Insert, QR…
    assert pane.current.editor.text().startswith("\\SMQRCode[0.60\\textheight]{media/qr-")
    pane.show_path(frozen)
    before = pane.current.editor.text()
    pane._on_insert_chosen("ext:1")
    assert pane.current.editor.text() == before


def test_existing_call_finds_one_call_with_a_stored_spec_only(ctx):
    made = qr_code.create(ctx, qr_code.QRSpec(qr_code.KIND_URL, {"url": "https://example.org"}))
    text = f"a {made.snippet} b\n"
    found = qr_dialog.existing_call(ctx, text, 0, 0)
    assert found is not None and text[found.start:found.end] == made.snippet and found.image == made.image
    assert qr_dialog.existing_call(ctx, text + made.snippet, 0, len(text) + len(made.snippet)) is None
    assert qr_dialog.existing_call(ctx, "\\SMQRCode{media/other.pdf}{}\n", 0, 0) is None
