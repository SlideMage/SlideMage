# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The Insert QR code sheet: what it writes into media/, the call it hands the editor, its inline errors,
the sizes it shows, and the Source view's button."""
from __future__ import annotations

import pytest

from slidemage import qr_code
from slidemage.ui.dialogs import qr_code as qr_dialog
from slidemage.ui.dialogs.qr_code import QRCodeDialog
from slidemage.ui.kit.widgets import Button
from test_insert_popovers_gui import FakeApp


@pytest.fixture
def dialog(ctx, qapp):
    (ctx.root / "media").mkdir(exist_ok=True)
    return QRCodeDialog(None, ctx)


def choose_kind(dialog, kind):
    dialog.kind_box.setCurrentIndex(dialog.kind_box.findData(kind))


def test_a_link_becomes_a_pdf_in_media_and_a_call_without_a_caption(dialog, ctx):
    dialog.url_url.setText("https://example.org/talk")
    dialog._on_insert()
    assert dialog.result() == dialog.DialogCode.Accepted
    pdfs = list((ctx.root / "media").glob("qr-*.pdf"))
    assert len(pdfs) == 1
    assert dialog.snippet == f"\\SMQRCode[0.60\\textheight]{{media/{pdfs[0].name}}}{{}}[https://example.org/talk]"


def test_its_text_as_caption_and_a_corner(dialog, ctx):
    dialog.url_url.setText("https://example.org/talk")
    dialog._on_caption_mode(qr_code.CAPTION_CONTENT)
    dialog.placement_box.setCurrentIndex(dialog.placement_box.findData("se"))
    dialog._on_insert()
    image = list((ctx.root / "media").glob("qr-*.pdf"))[0].name
    assert dialog.snippet == (f"\\cornerfigure[corner=se]{{\\SMQRCode[0.60\\textheight]{{media/{image}}}"
                              "{\\url{https://example.org/talk}}[https://example.org/talk]}")


def test_a_custom_caption_and_the_png_format(dialog, ctx):
    dialog.url_url.setText("https://example.org")
    dialog.caption_mode.set_current(qr_code.CAPTION_CUSTOM)
    dialog._on_caption_mode(qr_code.CAPTION_CUSTOM)
    dialog.caption_text.setText("QR 1")
    dialog.format_box.set_current("png")
    dialog.height_box.setValue(0.8)
    dialog._on_insert()
    assert dialog.snippet.startswith("\\SMQRCode[0.80\\textheight]{media/qr-1.png}{QR 1}")
    assert list((ctx.root / "media").glob("*.png"))


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


def test_the_info_names_both_rooms_and_the_height_turns_amber_below_the_seminar_room(dialog):
    dialog.url_url.setText("https://example.org/a/rather/long/path/to/make/the/code/denser?x=1")
    dialog.update_preview()
    assert "Seminar room" in dialog.info.text() and "Lecture hall" in dialog.info.text()
    needed = qr_code.size_advice(qr_code.make(dialog.spec()), dialog.spec().border)[0][1]
    dialog.height_box.setValue(max(0.05, needed - 0.1))
    dialog.update_preview()
    assert not dialog.height_hint.isHidden() and dialog.height_hint.property("tone") == "warning"
    dialog.height_box.setValue(0.95)
    dialog.update_preview()
    assert dialog.height_hint.isHidden()


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


def test_a_code_in_the_editor_opens_as_update_and_replaces_the_call(ctx, qapp, tmp_path, monkeypatch):
    from slidemage.ui.workspace.source_view import SourcePane

    slides = tmp_path / "slides"
    slides.mkdir()
    created = qr_code.create(ctx, qr_code.QRSpec(qr_code.KIND_URL, {"url": "https://example.org"}), height=0.5,
                             caption_mode=qr_code.CAPTION_CONTENT)       # the stored caption mode comes back
    path = slides / "abc-EN-Demo-current.tex"
    path.write_text(f"before\n{created.snippet}\nafter\n", encoding="utf-8")
    pane = SourcePane(FakeApp(ctx))
    pane.show_path(path)
    assert isinstance(pane._qr_button, Button)
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


def test_the_button_inserts_into_the_selection_and_is_off_in_a_frozen_version(ctx, qapp, tmp_path, monkeypatch):
    from slidemage.ui.workspace.source_view import SourcePane

    slides = tmp_path / "slides"
    slides.mkdir()
    path = slides / "abc-EN-Demo-current.tex"
    path.write_text("x\n", encoding="utf-8")
    frozen = slides / "abc-EN-Demo-v1-0-0.tex"
    frozen.write_text("old", encoding="utf-8")
    pane = SourcePane(FakeApp(ctx))
    pane.show_path(path)

    def fake_exec(self):
        self.url_url.setText("https://example.org")
        self._on_insert()
        return self.result()

    monkeypatch.setattr(QRCodeDialog, "exec", fake_exec)
    pane._qr_button.click()
    assert pane.current.editor.text().startswith("\\SMQRCode[0.60\\textheight]{media/qr-")
    pane.show_path(frozen)
    before = pane.current.editor.text()
    pane._qr_button.click()
    assert pane.current.editor.text() == before


def test_existing_call_finds_one_call_with_a_stored_spec_only(ctx):
    made = qr_code.create(ctx, qr_code.QRSpec(qr_code.KIND_URL, {"url": "https://example.org"}))
    text = f"a {made.snippet} b\n"
    found = qr_dialog.existing_call(ctx, text, 0, 0)
    assert found is not None and text[found.start:found.end] == made.snippet and found.image == made.image
    assert qr_dialog.existing_call(ctx, text + made.snippet, 0, len(text) + len(made.snippet)) is None
    assert qr_dialog.existing_call(ctx, "\\SMQRCode{media/other.pdf}{}\n", 0, 0) is None
