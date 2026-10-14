"""The Images page's backend: slide views and their filters, saving a slide's forms, replacing an image."""
from pathlib import Path

import pytest

from slidemage import alt_blocks, alt_draft, alt_images, image_review
from slidemage.image_review import FormEdit, SlideView

IMG = "media/photo-a.png"


@pytest.fixture
def store(tmp_path, monkeypatch):
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


def test_scan_views_hash_and_state(ctx, store, monkeypatch):
    row = slide(store, "1a2b")
    monkeypatch.setattr(alt_blocks, "scan_slides_raw", lambda _ctx: [row])
    [only] = image_review.scan_views(ctx, {})
    assert (only.row, only.state) == (row, alt_images.STATE_NONE)
    assert only.slide_hash == alt_images.slide_context_hash(row.path)


def entries_of(**by_image):
    return {name: alt_images.ImageEntry(image=name, **fields) for name, fields in by_image.items()}


def test_visible_views_filter_and_order(store):
    rows = [slide(store, f"{i}aaa") for i in range(4)]
    views = [view(rows[0], "none"), view(rows[1], "draft"), view(rows[2], "reviewed"), view(rows[3], "stale")]
    ids = lambda shown: [v.row.slide_id for v in shown]   # noqa: E731
    needs, everything = 0, image_review.FILTER_ALL
    assert ids(image_review.visible_views(views, {}, needs)) == ["0aaa", "1aaa", "3aaa"]
    assert len(image_review.visible_views(views, {}, everything)) == 4
    # slides missing from the order keep their place, at the end
    assert ids(image_review.visible_views(views, {}, everything, order={"3aaa": 0, "1aaa": 1})) == [
        "3aaa", "1aaa", "0aaa", "2aaa"]
    assert image_review.filter_counts(views, {}) == [3, 4, 1, 1, 1, 1, 0, 0]
    summary_views = [*views, views[0]]
    assert image_review.state_counts(summary_views) == {"none": 2, "draft": 1, "stale": 1, "reviewed": 1}
    assert image_review.summary_text(summary_views) == "1 reviewed · 1 need re-check · 1 draft · 2 undescribed"


def test_no_german_filter_lists_slides_with_an_english_only_informative_image(store):
    german = "media/german.png"
    entries = entries_of(**{
        IMG: dict(short="en"),                                       # English only: no German
        "media/b.png": dict(long="en", short_de="de"),               # has German (stale or not, it exists)
        "media/c.png": dict(role=alt_images.ROLE_DECORATIVE),        # decorative: nothing to translate
        "media/d.png": dict(),                                       # nothing written yet
        german: dict(short="en", short_de="de"),
    })
    assert image_review.lacks_german(entries[IMG])
    assert not any(image_review.lacks_german(entries[name]) for name in ("media/b.png", "media/c.png", "media/d.png", german))
    stale = entries["media/b.png"]
    assert alt_images.translation_state(stale) == alt_images.STATE_STALE   # a stale German is not "no German"
    views = [view(slide(store, "1aaa", images=(IMG, "media/c.png")), "none"),
             view(slide(store, "2bbb", images=("media/b.png",)), "none"),
             view(slide(store, "3ccc", images=("media/c.png", "media/d.png", "media/missing.png")), "none")]
    no_german = [label for label, _ in image_review.FILTERS].index("No German")
    assert [v.row.slide_id for v in image_review.visible_views(views, entries, no_german)] == ["1aaa"]


def test_find_slide_by_id_or_stem(store):
    views = [view(slide(store, "1aaa"), "none"), view(slide(store, "2bbb"), "none")]
    assert image_review.find_slide(views, "2BBB").row.slide_id == "2bbb"
    assert image_review.find_slide(views, "2bbb-x").row.slide_id == "2bbb"
    assert image_review.find_slide(views, "1aaa-x-current").row.slide_id == "1aaa"
    assert image_review.find_slide(views, "zzzz") is None


def test_stamp_review_and_save_slide_image_agree(ctx, store):
    row = slide(store, "1aaa")
    alt_images.save_slide_image(ctx, IMG, "1aaa", row.path, role="informative", short="s", long="l", reviewed=True)
    entry = alt_images.load_store(ctx)[IMG]
    assert alt_images.slide_use_state(entry, "1aaa", alt_images.slide_context_hash(row.path)) == alt_images.STATE_REVIEWED
    alt_images.save_slide_image(ctx, IMG, "1aaa", row.path, role="informative", short="s", long="l", reviewed=False)
    assert alt_images.slide_use_state(alt_images.load_store(ctx)[IMG], "1aaa", "h") == alt_images.STATE_DRAFT


def test_save_slide_forms_writes_only_changed_fields_and_stamps(ctx, store):
    row = slide(store, "1aaa")
    alt_images.update_store(ctx, lambda e: e.update({IMG: alt_images.ImageEntry(image=IMG, short="old", long="L")}) or True)
    entry = alt_images.load_store(ctx)[IMG]
    edit = edit_of(entry, "1aaa", short="new")
    # a worker wrote the long text while the form was open: the untouched field keeps it
    alt_images.update_store(ctx, lambda e: setattr(e[IMG], "long", "worker") or True)
    image_review.save_slide_forms(ctx, "1aaa", row.path, [edit], reviewed=True)
    saved = alt_images.load_store(ctx)[IMG]
    assert (saved.short, saved.long, saved.status) == ("new", "worker", alt_images.STATUS_REVIEWED)
    assert saved.used_on["1aaa"].stored_hash == alt_images.slide_context_hash(row.path)
    image_review.save_slide_forms(ctx, "1aaa", row.path, [edit_of(saved, "1aaa")], reviewed=False)
    assert alt_images.load_store(ctx)[IMG].used_on["1aaa"].reviewed == ""


def test_save_slide_forms_creates_a_missing_entry(ctx, store):
    row = slide(store, "1aaa")
    blank = alt_images.ImageEntry(image=IMG)
    image_review.save_slide_forms(ctx, "1aaa", row.path, [edit_of(blank, "1aaa", short="s")], reviewed=False)
    assert alt_images.load_store(ctx)[IMG].short == "s"


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


def test_set_takeaway_default_clears_this_slides_override(ctx, store):
    entry = alt_images.ImageEntry(image=IMG)
    entry.used_on["1aaa"] = alt_images.SlideUse(takeaway="mine")
    alt_images.update_store(ctx, lambda e: e.update({IMG: entry}) or True)
    updated = alt_images.set_takeaway_default(ctx, IMG, "1aaa", "shared")
    assert updated.takeaway_default == "shared"
    stored = alt_images.load_store(ctx)[IMG]
    assert (stored.takeaway_default, stored.used_on["1aaa"].takeaway) == ("shared", "")
    assert alt_images.set_takeaway_default(ctx, "media/none.png", "1aaa", "x") is None


def test_replace_image_copies_and_repoints_slides(ctx, store):
    source = store / "picked.png"
    source.write_bytes(b"png")
    one = slide(store, "1aaa", text=f"\\includegraphics{{{IMG}}}")
    two = slide(store, "2bbb", text="no image here")
    entry = alt_images.ImageEntry(image=IMG, short="s")
    entry.used_on = {"1aaa": alt_images.SlideUse(), "2bbb": alt_images.SlideUse()}
    entries = {IMG: entry}
    rows = {"1aaa": one, "2bbb": two}

    assert image_review.copy_into_media(ctx, source, "photo-b.png") == store / "media" / "photo-b.png"
    assert (store / "media" / "photo-b.png").read_bytes() == b"png"
    changed, failures = image_review.repoint_slides(ctx, 
        entry, entries, {"1aaa": one.path, "2bbb": two.path}, rows, IMG, "media/photo-b.png")
    assert changed == ["1aaa"] and "2bbb: reference not found" in failures[0]
    assert "media/photo-b.png" in one.path.read_text(encoding="utf-8")
    assert not image_review.is_unused_after(entry, changed)
    assert image_review.is_unused_after(entry, ["1aaa", "2bbb"])
    assert image_review.has_text(entry) and not image_review.has_text(alt_images.ImageEntry(image=IMG))


def test_copy_into_media_never_overwrites_and_free_names_count_up(ctx, store):
    source = store / "picked.png"
    source.write_bytes(b"new")
    (store / "media").mkdir(exist_ok=True)
    (store / "media" / "photo-a.png").write_bytes(b"old")
    with pytest.raises(FileExistsError):
        image_review.copy_into_media(ctx, source, "photo-a.png")
    assert (store / "media" / "photo-a.png").read_bytes() == b"old"
    assert image_review.free_media_stem(ctx, "photo-a", ".png") == "photo-a-2"
    assert image_review.free_media_stem(ctx, "photo-a", ".jpg") == "photo-a"


def test_repoint_keeps_the_line_ends_and_makes_a_backup(ctx, store):
    entry = alt_images.ImageEntry(image=IMG, short="s")
    row = slide(store, "1aaa", text="x")
    row.path.write_bytes(f"a\r\n\\includegraphics{{{IMG}}}\r\n".encode())
    changed, failures = image_review.repoint_slides(ctx, entry, {IMG: entry}, {"1aaa": row.path}, {}, IMG, "media/n.png")
    assert (changed, failures) == (["1aaa"], [])
    assert row.path.read_bytes() == b"a\r\n\\includegraphics{media/n.png}\r\n"
    assert len(list((store / "slides" / ".backups" / row.path.name).glob("*.tex"))) == 1


def test_repoint_reports_unreadable_slide(ctx, store):
    entry = alt_images.ImageEntry(image=IMG)
    changed, failures = image_review.repoint_slides(ctx, entry, {}, {"1aaa": Path(store / "missing.tex")}, {}, IMG, "media/n.png")
    assert changed == [] and failures[0].startswith("1aaa:")


def test_repoint_leaves_a_slide_with_unsaved_source_edits_alone(ctx, store):
    """The Source buffer's own save would fail as stale if the file changed under it, and writing into the
    buffer would leave the slide on disk pointing at the old image: such a slide is refused, the rest go on."""
    entry = alt_images.ImageEntry(image=IMG, short="s")
    open_slide = slide(store, "1aaa", text=f"\\includegraphics{{{IMG}}}")
    other = slide(store, "2bbb", text=f"\\includegraphics{{{IMG}}}")
    targets = {"1aaa": open_slide.path, "2bbb": other.path}
    changed, failures = image_review.repoint_slides(ctx, 
        entry, {IMG: entry}, targets, {}, IMG, "media/n.png", unsaved=lambda path: path == open_slide.path)
    assert changed == ["2bbb"]
    assert len(failures) == 1 and failures[0].startswith("1aaa:") and "unsaved edits" in failures[0]
    assert IMG in open_slide.path.read_text(encoding="utf-8")            # untouched
    assert "media/n.png" in other.path.read_text(encoding="utf-8")


def test_a_tuned_draft_stores_the_hint_and_a_cleared_hint(ctx, store):
    alt_images.update_store(ctx, lambda entries: bool(entries.update({IMG: alt_images.ImageEntry(image=IMG, hint="old")})) or True)
    result = alt_draft.DraftResult(short="s", long="l", takeaway="t")
    assert alt_draft.apply_one_draft(ctx, IMG, result, "m", hint="") and alt_images.load_store(ctx)[IMG].hint == ""
    assert alt_draft.apply_one_draft(ctx, IMG, result, "m", hint="y axis max 6800")
    assert alt_images.load_store(ctx)[IMG].hint == "y axis max 6800"
    assert alt_draft.apply_one_draft(ctx, IMG, result, "m") and alt_images.load_store(ctx)[IMG].hint == "y axis max 6800"


def test_media_names():
    assert image_review.media_name_problem("chart-sales") == ""
    assert image_review.media_name_problem("") and image_review.media_name_problem("a/b") and image_review.media_name_problem("a\\b")


def test_apply_translation_merges_only_untouched_fields_and_proves_provenance():
    result = alt_draft.TranslationResult(short_de="S", long_de="L", takeaway_de="T",
                                         source_hash=image_review.source_hash("en", "long", "take"))
    asked = {"short_de": "", "long_de": "", "takeaway_de": ""}
    english = ("en", "long", "take")
    applied = image_review.apply_translation(result, asked, english, dict(asked), english)
    assert applied.fields == {"short_de": "S", "long_de": "L", "takeaway_de": "T"}
    assert applied.in_sync and applied.provenance == {"source_hash": result.source_hash, "fields": applied.fields}
    # German typed since the request is kept, and then no provenance can be proved
    typed = {**asked, "long_de": "mine"}
    kept = image_review.apply_translation(result, asked, english, typed, english)
    assert kept.fields == {"short_de": "S", "takeaway_de": "T"} and kept.provenance is None
    # English edited since the request: the translation is stale
    newer = image_review.apply_translation(result, asked, english, dict(asked), ("en", "newer", "take"))
    assert not newer.in_sync and newer.provenance is not None
    # a result of other English than was asked for proves nothing
    wrong = alt_draft.TranslationResult(short_de="S", long_de="L", takeaway_de="T", source_hash="other")
    assert image_review.apply_translation(wrong, asked, english, dict(asked), english).provenance is None


def test_preview_for_names_the_file_a_page_or_the_reason(ctx, store, monkeypatch):
    png = store / "media" / "photo-a.png"
    png.parent.mkdir(parents=True)
    png.write_bytes(b"png")
    eps = store / "media" / "figure.eps"
    eps.write_bytes(b"eps")
    pdf = store / "media" / "figure.pdf"
    pdf.write_bytes(b"pdf")
    monkeypatch.setattr(alt_blocks, "resolve_image", lambda _ctx, reference: store / reference)
    assert image_review.preview_for(ctx, IMG) == image_review.Preview(png, png)
    assert image_review.preview_for(ctx, "media/figure.eps").image is None
    assert image_review.preview_for(ctx, "media/figure.eps").original == eps
    rendered = store / "rendered.png"
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
