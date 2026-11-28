# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""An image citation has its own review state across all write paths."""
from __future__ import annotations

import json

import pytest

from slidemage import alt_blocks, alt_draft, alt_images, bundled_copies, image_review
from slidemage.ai.tools import build_toolbox
from slidemage.ai.workspace import WorkspaceContext
from slidemage.alt_images import SOURCE_REVIEWED, SOURCE_TO_REVIEW, ImageEntry
from slidemage.deck_scan import scan_decks
from slidemage.project import ProjectContext

IMG = "media/photo-a.png"
STORE = "media/alt-text.json"


def stored(ctx) -> ImageEntry:
    return alt_images.load_store(ctx)[IMG]


def put(ctx, **fields) -> None:
    alt_images.update_store(ctx, lambda entries: entries.update({IMG: ImageEntry(image=IMG, **fields)}) or True)


def raw_images(ctx) -> dict:
    return json.loads((ctx.media_dir / "alt-text.json").read_text(encoding="utf-8"))["images"]


def test_source_changes_round_trip_until_a_person_reviews_them(ctx):
    put(ctx, source="Own illustration")
    assert stored(ctx).source_status == SOURCE_REVIEWED and "source_status" not in raw_images(ctx)[IMG]
    assert alt_images.save_source(ctx, IMG, source="Own illustration") is None
    alt_images.save_source(ctx, IMG, source="", source_de="Eigene Grafik")
    assert raw_images(ctx)[IMG]["source_status"] == SOURCE_TO_REVIEW
    entry = stored(ctx)
    assert (entry.source, entry.source_de) == ("", "Eigene Grafik")
    assert alt_images.source_state(entry) == SOURCE_TO_REVIEW
    alt_images.mark_source_reviewed(ctx, IMG)
    assert "source_status" not in raw_images(ctx)[IMG] and alt_images.source_state(stored(ctx)) == SOURCE_REVIEWED
    alt_images.save_source(ctx, IMG, source_de="")
    assert alt_images.source_state(stored(ctx)) == ""
    header = (ctx.media_dir / "alt-text.csv").read_text(encoding="utf-8").splitlines()[0]
    assert header == "image,role,status_en,short_alt_en,source_en,status_de,short_alt_de,source_de"


def test_the_descriptions_review_and_the_sources_are_independent(ctx, tmp_path):
    slide = tmp_path / "1aaa-x-current.tex"
    slide.write_text("body", encoding="utf-8")
    put(ctx, short="s", long="l", source="Own illustration")

    def save(reviewed, **typed):
        entry = stored(ctx)
        baseline = image_review.form_baseline(entry, "1aaa")
        edit = image_review.FormEdit(IMG, {**baseline, **typed}, baseline, alt_images.en_text_hash(entry))
        image_review.save_slide_forms(ctx, "1aaa", slide, [edit], reviewed=reviewed)

    save(True, source="Photo: Smith")
    entry = stored(ctx)
    assert (entry.status, entry.source_status) == (alt_images.STATUS_REVIEWED, SOURCE_TO_REVIEW)
    save(True)
    assert stored(ctx).source_status == SOURCE_TO_REVIEW
    alt_images.mark_source_reviewed(ctx, IMG)
    entry = stored(ctx)
    assert entry.status == alt_images.STATUS_REVIEWED and entry.used_on["1aaa"].reviewed
    save(False, short="new short")
    assert stored(ctx).source_status == SOURCE_REVIEWED
    save(False, source_tr="Foto: Smith")
    assert stored(ctx).source_status == SOURCE_TO_REVIEW


def test_a_pipeline_draft_leaves_the_reviewed_source_alone(ctx):
    put(ctx, source="Own illustration")
    assert alt_draft.apply_one_draft(ctx, IMG, alt_draft.DraftResult(short="s", long="l"), "model")
    entry = stored(ctx)
    assert (entry.source, entry.source_status) == ("Own illustration", SOURCE_REVIEWED)


def write_store(path, entries):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"version": 2, "images": entries}), encoding="utf-8")


def test_flag_edited_sources_handles_external_edits_and_invalid_files(ctx):
    path = ctx.root / STORE
    write_store(path, {IMG: {"source": "A"}, "media/b.png": {"source": "B"}})
    before = path.read_text(encoding="utf-8")
    assert not alt_images.flag_edited_sources(ctx, path, before)
    assert not alt_images.flag_edited_sources(ctx, ctx.root / "slides" / "x.tex", "")
    write_store(path, {IMG: {"source": "A2", "source_status": "reviewed"}, "media/b.png": {"source": "B"},
                       "media/c.png": {"source_de": "C"}})
    assert alt_images.flag_edited_sources(ctx, path, before)
    states = {name: alt_images.source_state(entry) for name, entry in alt_images.load_store(ctx).items()}
    assert states == {IMG: SOURCE_TO_REVIEW, "media/b.png": SOURCE_REVIEWED, "media/c.png": SOURCE_TO_REVIEW}
    assert alt_images.flag_edited_sources(ctx, path, "")
    assert alt_images.flag_edited_sources(ctx, path, "not json at all")
    path.write_text("{ broken", encoding="utf-8")
    assert not alt_images.flag_edited_sources(ctx, path, before)


@pytest.fixture
def agent(root):
    from agent_fakes import FakeWorkspace, call
    from slidemage import compiler
    from slidemage.ai.agent_types import EDIT_AUTO

    ctx = ProjectContext.at(root)
    deck = next(d for d in scan_decks(ctx) if d.name == "test")
    workspace = FakeWorkspace(root, WorkspaceContext(deck=deck, slide_id="abc", path=root / "slides" / "abc-EN-Hello-current.tex"), True)
    box = build_toolbox(workspace, lambda event: None, compiler.CancelToken(), EDIT_AUTO)
    return ctx, lambda name, **arguments: box.execute(call(name, **arguments))


def test_chat_tools_flag_created_and_edited_sources_for_review(agent):
    ctx, run = agent
    content = json.dumps({"version": 2, "images": {IMG: {"source": "Own illustration", "short": "s"}}})
    assert not run("write_file", path=STORE, content=content).is_error
    assert alt_images.source_state(stored(ctx)) == SOURCE_TO_REVIEW
    alt_images.mark_source_reviewed(ctx, IMG)
    result = run("edit_file", path=STORE, old_text='"source": "Own illustration"', new_text='"source": "Photo: Smith"')
    assert not result.is_error, result.text
    entry = stored(ctx)
    assert (entry.source, entry.source_status) == ("Photo: Smith", SOURCE_TO_REVIEW)
    alt_images.mark_source_reviewed(ctx, IMG)
    result = run("edit_file", path=STORE, old_text='"short": "s"', new_text='"short": "t"')
    assert not result.is_error and stored(ctx).source_status == SOURCE_REVIEWED


def test_importing_the_manual_sends_a_replaced_entry_with_another_source_to_review(root, tmp_path):
    ctx = ProjectContext.at(root)
    put(ctx, source="Old credit", short="old")
    bundled = {IMG: {"role": "informative", "status": "auto", "short": "new", "source": "New credit"},
               "media/same.png": {"short": "x", "source": "Credit"}}
    part = type("Part", (), {"source": tmp_path / "bundle", "update": [IMG], "add": ["media/same.png"]})()
    write_store(part.source / STORE, bundled)
    alt_images.update_store(ctx, lambda entries: entries.update({"media/same.png": ImageEntry(
        image="media/same.png", source="Credit")}) or True)
    bundled_copies._merge_image_descriptions(ctx, part)
    entries = alt_images.load_store(ctx)
    assert (entries[IMG].short, entries[IMG].source_status) == ("new", SOURCE_TO_REVIEW)
    assert entries["media/same.png"].source_status == SOURCE_REVIEWED


def test_the_source_to_review_filter_lists_slides_but_does_not_change_their_state(tmp_path):
    path = tmp_path / "1aaa-x-current.tex"
    row = alt_blocks.SlideRow(path=path, slide_id="1aaa", title="t", images=[IMG])
    entries = {IMG: ImageEntry(image=IMG, short="s", long="l", status=alt_images.STATUS_REVIEWED, source="x",
                               source_status=SOURCE_TO_REVIEW)}
    entries[IMG].used_on["1aaa"] = alt_images.SlideUse(reviewed="2026-01-01", stored_hash="h")
    views = [image_review.SlideView(row, image_review.slide_state(row, entries, "h"), "h")]
    assert views[0].state == alt_images.STATE_REVIEWED
    labels = [label for label, _ in image_review.FILTERS]
    counts = image_review.filter_counts(views, entries)
    assert counts[labels.index("Source to review")] == 1 and counts[labels.index("Needs attention")] == 0
