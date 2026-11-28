# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The Images page's backend: slide views and their filters, saving a slide's forms, replacing an image."""
from dataclasses import replace

import pytest

from slidemage import alt_blocks, alt_draft, alt_images, image_review
from slidemage.image_review import FormEdit, SlideView

IMG = "media/photo-a.png"


def slide(tmp_path, slide_id, images=(IMG,), text="body"):
    path = tmp_path / f"{slide_id}-x-current.tex"
    path.write_text(text, encoding="utf-8")
    return alt_blocks.SlideRow(path=path, slide_id=slide_id, title=slide_id, images=list(images))


def edit_of(entry, slide_id, **typed):
    baseline = image_review.form_baseline(entry, slide_id)
    return FormEdit(entry.image, {**baseline, **typed}, baseline, alt_images.en_text_hash(entry))


def test_slide_state_is_the_worst_of_its_images(tmp_path):
    row = slide(tmp_path, "1a2b", images=(IMG, "media/b.png"))
    done = alt_images.ImageEntry(image=IMG, short="s", long="l", status=alt_images.STATUS_REVIEWED)
    done.used_on["1a2b"] = alt_images.SlideUse(reviewed="2026-01-01", stored_hash="h")
    entries = {IMG: done, "media/b.png": alt_images.ImageEntry(image="media/b.png", short="draft")}
    assert image_review.slide_state(row, entries, "h") == alt_images.STATE_DRAFT
    assert image_review.slide_state(row, {IMG: done}, "h") == alt_images.STATE_NONE   # b.png has no entry
    assert image_review.slide_state(slide(tmp_path, "1a2b"), {IMG: done}, "other") == alt_images.STATE_STALE


def test_visible_views_filter_and_order(tmp_path):
    views = [SlideView(slide(tmp_path, f"{i}aaa"), state, "h")
             for i, state in enumerate(("none", "draft", "reviewed", "stale"))]
    assert image_review.visible_views(views, {}, 0) == [views[i] for i in (0, 1, 3)]
    ordered = image_review.visible_views(views, {}, image_review.FILTER_ALL, order={"3aaa": 0, "1aaa": 1})
    assert ordered == [views[i] for i in (3, 1, 0, 2)]
    assert image_review.state_counts([*views, views[0]]) == {"none": 2, "draft": 1, "stale": 1, "reviewed": 1}


def test_missing_translation_distinguishes_absent_stale_and_unneeded_translations(tmp_path):
    entries = {
        IMG: alt_images.ImageEntry(image=IMG, short="en"),
        "media/stale.png": alt_images.ImageEntry(image="media/stale.png", long="en", short_de="de"),
        "media/decorative.png": alt_images.ImageEntry(image="media/decorative.png", role=alt_images.ROLE_DECORATIVE),
        "media/blank.png": alt_images.ImageEntry(image="media/blank.png"),
    }
    views = [SlideView(slide(tmp_path, "1aaa"), "none", "h"),
             SlideView(slide(tmp_path, "2bbb", images=("media/stale.png",)), "none", "h"),
             SlideView(slide(tmp_path, "3ccc", images=("media/decorative.png", "media/blank.png", "media/missing.png")),
                       "none", "h")]
    missing = next(i for i, (label, _) in enumerate(image_review.FILTERS) if label == "Missing a translation")
    assert image_review.visible_views(views, entries, missing) == views[:1]


def test_save_slide_forms_writes_only_changed_fields_and_stamps(ctx, tmp_path):
    row = slide(tmp_path, "1aaa")
    blank = alt_images.ImageEntry(image=IMG)
    image_review.save_slide_forms(ctx, "1aaa", row.path, [edit_of(blank, "1aaa", short="old")], reviewed=False)
    entry = alt_images.load_store(ctx)[IMG]
    assert entry.short == "old"
    edit = edit_of(entry, "1aaa", short="new")
    # a worker wrote the long text while the form was open: the untouched field keeps it
    alt_images.update_store(ctx, lambda e: setattr(e[IMG], "long", "worker") or True)
    image_review.save_slide_forms(ctx, "1aaa", row.path, [edit], reviewed=True)
    saved = alt_images.load_store(ctx)[IMG]
    assert (saved.short, saved.long, saved.status) == ("new", "worker", alt_images.STATUS_REVIEWED)
    assert saved.used_on["1aaa"].stored_hash == alt_images.slide_context_hash(row.path)
    image_review.save_slide_forms(ctx, "1aaa", row.path, [edit_of(saved, "1aaa")], reviewed=False)
    assert alt_images.load_store(ctx)[IMG].used_on["1aaa"].reviewed == ""


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
    edit = edit_of(entry, "1aaa", short_tr="de")
    image_review.apply_form_edit(entry, "1aaa", edit)
    assert alt_images.translation_state(entry) == alt_images.STATE_REVIEWED
    entry.short = "changed meanwhile"
    edit = edit_of(entry, "1aaa", short_tr="de3")
    edit.baseline_en_hash = "older"
    image_review.apply_form_edit(entry, "1aaa", edit)
    assert entry.translated_from_hash == ""
    image_review.apply_form_edit(entry, "1aaa", edit_of(entry, "1aaa", short_tr="", long_tr=""))
    assert entry.translated_from_hash == ""


def test_translation_provenance_keeps_the_workers_source_hash():
    entry = alt_images.ImageEntry(image=IMG, short="en", long="l")
    source = image_review.source_hash("en", "l", "")
    assert source == alt_images.en_text_hash(entry)
    edit = edit_of(entry, "1aaa", short_tr="de", long_tr="dl")
    edit.provenance = {"source_hash": source, "fields": {"short_tr": "de", "long_tr": "dl", "takeaway_tr": ""}}
    image_review.apply_form_edit(entry, "1aaa", edit)
    assert entry.translated_from_hash == source


def test_set_takeaway_default_clears_this_slides_override(ctx):
    entry = alt_images.ImageEntry(image=IMG)
    entry.used_on["1aaa"] = alt_images.SlideUse(takeaway="mine")
    alt_images.update_store(ctx, lambda e: e.update({IMG: entry}) or True)
    updated = alt_images.set_takeaway_default(ctx, IMG, "1aaa", "shared")
    assert updated.takeaway_default == "shared"
    stored = alt_images.load_store(ctx)[IMG]
    assert (stored.takeaway_default, stored.used_on["1aaa"].takeaway) == ("shared", "")
    assert alt_images.set_takeaway_default(ctx, "media/none.png", "1aaa", "x") is None


def test_replace_repoints_clean_slides_with_a_backup_and_refuses_unsafe_targets(ctx, tmp_path):
    one = slide(tmp_path, "1aaa")
    original = f"a\r\n\\includegraphics{{{IMG}}}\r\n".encode()
    one.path.write_bytes(original)
    two = slide(tmp_path, "2bbb", text="no image here")
    dirty = slide(tmp_path, "3ccc", text=f"\\includegraphics{{{IMG}}}")
    rows = {row.slide_id: row for row in (one, two, dirty)}
    targets = {slide_id: row.path for slide_id, row in rows.items()}
    targets["4ddd"] = tmp_path / "missing.tex"
    entry = alt_images.ImageEntry(image=IMG, short="s", used_on={key: alt_images.SlideUse() for key in rows})
    changed, failures = image_review.repoint_slides(
        ctx, entry, {IMG: entry}, targets, rows, IMG, "media/photo-b.png", unsaved=lambda path: path == dirty.path)
    assert changed == ["1aaa"]
    missing_ref, unsaved, unreadable = failures
    assert missing_ref.startswith("2bbb: reference not found")
    assert unsaved.startswith("3ccc:") and "could not be saved" in unsaved
    assert unreadable.startswith("4ddd:")
    assert one.path.read_bytes() == b"\\setSlideVersion{1-0-0+}\r\na\r\n\\includegraphics{media/photo-b.png}\r\n"
    [backup] = (tmp_path / "slides" / ".backups" / one.path.name).glob("*.tex")
    assert backup.read_bytes().endswith(original)
    assert dirty.path.read_text(encoding="utf-8") == f"\\includegraphics{{{IMG}}}"
    assert not image_review.is_unused_after(entry, changed)
    assert image_review.is_unused_after(entry, list(rows))


def test_copy_into_media_never_overwrites_and_free_names_count_up(ctx, tmp_path):
    source = tmp_path / "picked.png"
    source.write_bytes(b"new")
    original = tmp_path / IMG
    original.parent.mkdir(exist_ok=True)
    original.write_bytes(b"old")
    with pytest.raises(FileExistsError):
        image_review.copy_into_media(ctx, source, original.name)
    assert original.read_bytes() == b"old"
    assert image_review.free_media_stem(ctx, original.stem, ".jpg") == original.stem
    free = image_review.free_media_stem(ctx, original.stem, ".png")
    assert free == "photo-a-2"
    copied = image_review.copy_into_media(ctx, source, f"{free}.png")
    assert copied == original.with_name("photo-a-2.png") and copied.read_bytes() == b"new"


def test_a_tuned_draft_stores_the_hint_and_a_cleared_hint(ctx):
    alt_images.update_store(ctx, lambda entries: bool(entries.update({IMG: alt_images.ImageEntry(image=IMG, hint="old")})) or True)
    result = alt_draft.DraftResult(short="s", long="l", takeaway="t")
    assert alt_draft.apply_one_draft(ctx, IMG, result, "m", hint="") and alt_images.load_store(ctx)[IMG].hint == ""
    assert alt_draft.apply_one_draft(ctx, IMG, result, "m", hint="y axis max 6800")
    assert alt_images.load_store(ctx)[IMG].hint == "y axis max 6800"
    assert alt_draft.apply_one_draft(ctx, IMG, result, "m") and alt_images.load_store(ctx)[IMG].hint == "y axis max 6800"


def test_apply_translation_merges_only_untouched_fields_and_proves_provenance():
    result = alt_draft.TranslationResult(short_de="S", long_de="L", takeaway_de="T",
                                         source_hash=image_review.source_hash("en", "long", "take"))
    asked = {"short_tr": "", "long_tr": "", "takeaway_tr": ""}
    english = ("en", "long", "take")
    applied = image_review.apply_translation(result, asked, english, dict(asked), english)
    assert applied.fields == {"short_tr": "S", "long_tr": "L", "takeaway_tr": "T"}
    assert applied.in_sync and applied.provenance == {"source_hash": result.source_hash, "fields": applied.fields}
    typed = {**asked, "long_tr": "mine"}
    kept = image_review.apply_translation(result, asked, english, typed, english)
    assert kept.fields == {"short_tr": "S", "takeaway_tr": "T"} and kept.provenance is None
    newer = image_review.apply_translation(result, asked, english, dict(asked), ("en", "newer", "take"))
    assert not newer.in_sync and newer.provenance is not None
    wrong = replace(result, source_hash="other")
    assert image_review.apply_translation(wrong, asked, english, dict(asked), english).provenance is None


def test_preview_for_names_the_file_a_page_or_the_reason(ctx, tmp_path, monkeypatch):
    png = tmp_path / "media" / "photo-a.png"
    png.parent.mkdir(parents=True)
    png.write_bytes(b"png")
    eps, pdf = (png.parent / f"figure.{extension}" for extension in ("eps", "pdf"))
    eps.touch()
    pdf.touch()
    monkeypatch.setattr(alt_blocks, "resolve_image", lambda _ctx, reference: tmp_path / reference)
    assert image_review.preview_for(ctx, IMG) == image_review.Preview(png, png)
    unsupported = image_review.preview_for(ctx, "media/figure.eps")
    assert unsupported.image is None and unsupported.original == eps
    rendered = tmp_path / "rendered.png"
    monkeypatch.setattr(image_review.media_render, "ensure_rendered", lambda ctx, path: rendered)
    assert image_review.preview_for(ctx, "media/figure.pdf") == image_review.Preview(rendered, pdf)

    def broken(ctx, path):
        raise RuntimeError("cannot render")

    lines = []
    monkeypatch.setattr(image_review.media_render, "ensure_rendered", broken)
    shown = image_review.preview_for(ctx, "media/figure.pdf", lines.append)
    assert shown.image is None and shown.original == pdf and "cannot render" in lines[0]
    monkeypatch.setattr(alt_blocks, "resolve_image", lambda _ctx, reference: None)
    assert "not found" in image_review.preview_for(ctx, IMG).problem
    monkeypatch.setattr(image_review.tikz_render, "ensure_rendered", lambda ctx, reference, log=None: rendered)
    assert image_review.preview_for(ctx, "tikz:abc") == image_review.Preview(rendered)
