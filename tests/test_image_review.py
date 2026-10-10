"""The Images page's backend: slide views and their filters, saving a slide's forms, replacing an image."""
from pathlib import Path

import pytest

from slidemage import alt_blocks, alt_images, image_review
from slidemage.image_review import FormEdit, SlideView

IMG = "media/photo-a.png"


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(alt_images, "STORE_PATH", tmp_path / "media" / "alt-text.json")
    monkeypatch.setattr(alt_images, "_COMPILE_CSV_PATH", tmp_path / "media" / "alt-text.csv")
    monkeypatch.setattr(image_review, "PROJECT_ROOT", tmp_path)
    return tmp_path


def slide(tmp_path, slide_id, images=(IMG,), text="body"):
    path = tmp_path / f"{slide_id}-x-current.tex"
    path.write_text(text, encoding="utf-8")
    return alt_blocks.SlideRow(path=path, slide_id=slide_id, title=slide_id, images=list(images))


def view(row, state):
    return SlideView(row, state, "h")


def edit_of(entry, slide_id, **typed):
    baseline = image_review.form_baseline(entry, slide_id)
    return FormEdit(entry.image, {**baseline, **typed}, baseline, alt_images.en_text_hash(entry))


def test_slide_state_is_the_worst_of_its_images(store):
    row = slide(store, "1a2b", images=(IMG, "media/b.png"))
    done = alt_images.ImageEntry(image=IMG, short="s", long="l", status=alt_images.STATUS_REVIEWED)
    done.used_on["1a2b"] = alt_images.SlideUse(reviewed="2026-01-01", stored_hash="h")
    entries = {IMG: done, "media/b.png": alt_images.ImageEntry(image="media/b.png", short="draft")}
    assert image_review.slide_state(row, entries, "h") == alt_images.STATE_DRAFT
    assert image_review.slide_state(row, {IMG: done}, "h") == alt_images.STATE_NONE   # b.png has no entry
    assert image_review.slide_state(row, {IMG: done}, "other") == alt_images.STATE_NONE
    assert image_review.slide_state(slide(store, "1a2b", images=(IMG,)), {IMG: done}, "other") == alt_images.STATE_STALE
    assert image_review.slide_state(slide(store, "1a2b", images=()), {}, "h") == alt_images.STATE_REVIEWED


def test_scan_views_hash_and_state(store, monkeypatch):
    row = slide(store, "1a2b")
    monkeypatch.setattr(alt_blocks, "scan_slides_raw", lambda: [row])
    [only] = image_review.scan_views({})
    assert (only.row, only.state) == (row, alt_images.STATE_NONE)
    assert only.slide_hash == alt_images.slide_context_hash(row.path)


def test_visible_views_filter_pin_and_order(store):
    rows = [slide(store, f"{i}aaa") for i in range(4)]
    views = [view(rows[0], "none"), view(rows[1], "draft"), view(rows[2], "reviewed"), view(rows[3], "stale")]
    needs = image_review.FILTERS[0][1]
    ids = lambda shown: [v.row.slide_id for v in shown]   # noqa: E731
    assert ids(image_review.visible_views(views, needs)) == ["0aaa", "1aaa", "3aaa"]
    assert len(image_review.visible_views(views, None)) == 4
    assert ids(image_review.visible_views(views, needs, pin=rows[2].path)) == ["2aaa", "0aaa", "1aaa", "3aaa"]
    assert ids(image_review.visible_views(views, needs, pin=rows[0].path)) == ["0aaa", "1aaa", "3aaa"]
    # slides missing from the order keep their place, at the end
    assert ids(image_review.visible_views(views, None, order={"3aaa": 0, "1aaa": 1})) == ["3aaa", "1aaa", "0aaa", "2aaa"]
    assert [label for label, _ in image_review.FILTERS][image_review.FILTER_ALL] == "All slides with images"


def test_counts_and_summary(store):
    views = [view(slide(store, "1aaa"), s) for s in ("none", "none", "reviewed", "stale", "draft")]
    assert image_review.state_counts(views) == {"none": 2, "draft": 1, "stale": 1, "reviewed": 1}
    assert image_review.summary_text(views) == "1 reviewed · 1 need re-check · 1 draft · 2 undescribed"


def test_find_slide_by_id_or_stem(store):
    views = [view(slide(store, "1aaa"), "none"), view(slide(store, "2bbb"), "none")]
    assert image_review.find_slide(views, "2BBB").row.slide_id == "2bbb"
    assert image_review.find_slide(views, "2bbb-x").row.slide_id == "2bbb"
    assert image_review.find_slide(views, "1aaa-x-current").row.slide_id == "1aaa"
    assert image_review.find_slide(views, "zzzz") is None


def test_needs_long_description():
    assert image_review.needs_long_description(alt_images.ROLE_INFORMATIVE, "")
    assert not image_review.needs_long_description(alt_images.ROLE_INFORMATIVE, "text")
    assert not image_review.needs_long_description(alt_images.ROLE_DECORATIVE, "")


def test_stamp_review_and_save_slide_image_agree(store):
    row = slide(store, "1aaa")
    alt_images.save_slide_image(IMG, "1aaa", row.path, role="informative", short="s", long="l", reviewed=True)
    entry = alt_images.load_store()[IMG]
    assert alt_images.slide_use_state(entry, "1aaa", alt_images.slide_context_hash(row.path)) == alt_images.STATE_REVIEWED
    alt_images.save_slide_image(IMG, "1aaa", row.path, role="informative", short="s", long="l", reviewed=False)
    assert alt_images.slide_use_state(alt_images.load_store()[IMG], "1aaa", "h") == alt_images.STATE_DRAFT


def test_save_slide_forms_writes_only_changed_fields_and_stamps(store):
    row = slide(store, "1aaa")
    alt_images.update_store(lambda e: e.update({IMG: alt_images.ImageEntry(image=IMG, short="old", long="L")}) or True)
    entry = alt_images.load_store()[IMG]
    edit = edit_of(entry, "1aaa", short="new")
    # a worker wrote the long text while the form was open: the untouched field keeps it
    alt_images.update_store(lambda e: setattr(e[IMG], "long", "worker") or True)
    image_review.save_slide_forms("1aaa", row.path, [edit], reviewed=True)
    saved = alt_images.load_store()[IMG]
    assert (saved.short, saved.long, saved.status) == ("new", "worker", alt_images.STATUS_REVIEWED)
    assert saved.used_on["1aaa"].stored_hash == alt_images.slide_context_hash(row.path)
    image_review.save_slide_forms("1aaa", row.path, [edit_of(saved, "1aaa")], reviewed=False)
    assert alt_images.load_store()[IMG].used_on["1aaa"].reviewed == ""


def test_save_slide_forms_creates_a_missing_entry(store):
    row = slide(store, "1aaa")
    blank = alt_images.ImageEntry(image=IMG)
    image_review.save_slide_forms("1aaa", row.path, [edit_of(blank, "1aaa", short="s")], reviewed=False)
    assert alt_images.load_store()[IMG].short == "s"


def test_takeaway_follows_default_becomes_default_or_overrides():
    entry = alt_images.ImageEntry(image=IMG)
    image_review.apply_form_edit(entry, "1aaa", edit_of(entry, "1aaa", takeaway="first"))
    assert (entry.takeaway_default, entry.used_on["1aaa"].takeaway) == ("first", "")
    image_review.apply_form_edit(entry, "2bbb", edit_of(entry, "2bbb", takeaway="mine"))
    assert (entry.takeaway_default, entry.used_on["2bbb"].takeaway) == ("first", "mine")
    image_review.apply_form_edit(entry, "2bbb", edit_of(entry, "2bbb", takeaway="first"))
    assert entry.used_on["2bbb"].takeaway == ""


def test_german_edit_marks_translation_in_sync_only_against_unchanged_english():
    entry = alt_images.ImageEntry(image=IMG, short="en", long="l")
    edit = edit_of(entry, "1aaa", short_de="de")
    image_review.apply_form_edit(entry, "1aaa", edit)
    assert alt_images.translation_state(entry) == alt_images.STATE_REVIEWED
    entry.short = "changed meanwhile"
    image_review.apply_form_edit(entry, "1aaa", edit_of(entry, "1aaa", short_de="de2"))   # baseline is current: in sync
    edit = edit_of(entry, "1aaa", short_de="de3")
    edit.baseline_en_hash = "older"
    image_review.apply_form_edit(entry, "1aaa", edit)
    assert entry.translated_from_hash == ""
    image_review.apply_form_edit(entry, "1aaa", edit_of(entry, "1aaa", short_de="", long_de=""))
    assert entry.translated_from_hash == ""


def test_translation_provenance_keeps_the_workers_source_hash():
    entry = alt_images.ImageEntry(image=IMG, short="en", long="l")
    source = image_review.source_hash("en", "l", "")
    assert source == alt_images.en_text_hash(entry)
    edit = edit_of(entry, "1aaa", short_de="de", long_de="dl")
    edit.provenance = {"source_hash": source, "fields": {"short_de": "de", "long_de": "dl", "takeaway_de": ""}}
    image_review.apply_form_edit(entry, "1aaa", edit)
    assert entry.translated_from_hash == source


def test_set_takeaway_default_clears_this_slides_override(store):
    entry = alt_images.ImageEntry(image=IMG)
    entry.used_on["1aaa"] = alt_images.SlideUse(takeaway="mine")
    alt_images.update_store(lambda e: e.update({IMG: entry}) or True)
    updated = alt_images.set_takeaway_default(IMG, "1aaa", "shared")
    assert updated.takeaway_default == "shared"
    stored = alt_images.load_store()[IMG]
    assert (stored.takeaway_default, stored.used_on["1aaa"].takeaway) == ("shared", "")
    assert alt_images.set_takeaway_default("media/none.png", "1aaa", "x") is None


def test_replace_image_copies_and_repoints_slides(store):
    source = store / "picked.png"
    source.write_bytes(b"png")
    one = slide(store, "1aaa", text=f"\\includegraphics{{{IMG}}}")
    two = slide(store, "2bbb", text="no image here")
    entry = alt_images.ImageEntry(image=IMG, short="s")
    entry.used_on = {"1aaa": alt_images.SlideUse(), "2bbb": alt_images.SlideUse()}
    entries = {IMG: entry}
    rows = {"1aaa": one, "2bbb": two}

    assert image_review.copy_into_media(source, "photo-b.png") == store / "media" / "photo-b.png"
    assert (store / "media" / "photo-b.png").read_bytes() == b"png"
    changed, failures = image_review.repoint_slides(
        entry, entries, {"1aaa": one.path, "2bbb": two.path}, rows, IMG, "media/photo-b.png")
    assert changed == ["1aaa"] and "2bbb: reference not found" in failures[0]
    assert "media/photo-b.png" in one.path.read_text(encoding="utf-8")
    assert not image_review.is_unused_after(entry, changed)
    assert image_review.is_unused_after(entry, ["1aaa", "2bbb"])
    assert image_review.has_text(entry) and not image_review.has_text(alt_images.ImageEntry(image=IMG))


def test_repoint_reports_unreadable_slide(store):
    entry = alt_images.ImageEntry(image=IMG)
    changed, failures = image_review.repoint_slides(entry, {}, {"1aaa": Path(store / "missing.tex")}, {}, IMG, "media/n.png")
    assert changed == [] and failures[0].startswith("1aaa:")
