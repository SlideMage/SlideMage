# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The review state of an image's source (citation): stored in media/alt-text.json apart from the
description's status, set back to "to review" by every writer of a source (alt_images.set_source and
flag_source_change), and confirmed only by a person (mark_source_reviewed)."""
from __future__ import annotations

import json

import pytest

from slidemage import alt_images, bundled_copies, image_review
from slidemage.ai import claude_hook
from slidemage.ai.tools import build_toolbox
from slidemage.alt_images import SOURCE_REVIEWED, SOURCE_TO_REVIEW, ImageEntry
from slidemage.deck_scan import scan_decks
from slidemage.ai.workspace import WorkspaceContext
from slidemage.project import ProjectContext

IMG = "media/photo-a.png"
STORE = "media/alt-text.json"


def stored(ctx, image=IMG) -> ImageEntry:
    return alt_images.load_store(ctx)[image]


def put(ctx, **fields) -> None:
    alt_images.update_store(ctx, lambda entries: entries.update({IMG: ImageEntry(image=IMG, **fields)}) or True)


def raw_images(ctx) -> dict:
    return json.loads((ctx.media_dir / "alt-text.json").read_text(encoding="utf-8"))["images"]


# -- the store ---------------------------------------------------------------------------------------------


def test_a_new_entry_is_reviewed_and_an_empty_source_has_nothing_to_review():
    entry = ImageEntry(image=IMG)
    assert entry.source_status == SOURCE_REVIEWED and alt_images.source_state(entry) == ""
    entry.source = "Own illustration"
    assert alt_images.source_state(entry) == SOURCE_REVIEWED
    entry.source_status = SOURCE_TO_REVIEW
    assert alt_images.source_state(entry) == SOURCE_TO_REVIEW
    entry.source, entry.source_de = "", "Eigene Grafik"      # a German-only citation counts too
    assert alt_images.source_state(entry) == SOURCE_TO_REVIEW
    entry.source_de = ""
    assert alt_images.source_state(entry) == ""


def test_the_state_is_written_only_when_to_review_and_comes_back(ctx):
    put(ctx, source="Own illustration")
    assert "source_status" not in raw_images(ctx)[IMG]
    alt_images.save_source(ctx, IMG, source="Photo: Smith")
    assert raw_images(ctx)[IMG]["source_status"] == "to_review"
    assert stored(ctx).source_status == SOURCE_TO_REVIEW
    alt_images.mark_source_reviewed(ctx, IMG)
    assert "source_status" not in raw_images(ctx)[IMG]
    assert alt_images.source_state(stored(ctx)) == SOURCE_REVIEWED


def test_an_older_store_without_the_field_loads_as_reviewed(ctx):
    ctx.media_dir.mkdir(parents=True, exist_ok=True)
    (ctx.media_dir / "alt-text.json").write_text(json.dumps({"version": 2, "images": {
        "media/a.png": {"role": "informative", "status": "reviewed", "short": "s", "source": "Own illustration"},
        "media/b.png": {"role": "informative", "status": "auto"},
        "media/c.png": {"source": "x", "source_status": "nonsense"},
    }}), encoding="utf-8")
    entries = alt_images.load_store(ctx)
    assert [alt_images.source_state(entries[name]) for name in ("media/a.png", "media/b.png", "media/c.png")] == [
        SOURCE_REVIEWED, "", SOURCE_REVIEWED]
    # saving the store again keeps them reviewed and writes no new key
    alt_images.save_store(ctx, entries)
    assert all("source_status" not in raw for raw in raw_images(ctx).values())


def test_the_compile_csv_keeps_its_columns(ctx):
    put(ctx, source="Own illustration")
    alt_images.save_source(ctx, IMG, source="Changed")
    header = (ctx.media_dir / "alt-text.csv").read_text(encoding="utf-8").splitlines()[0]
    assert header == "image,role,status_en,short_alt_en,source_en,status_de,short_alt_de,source_de"


# -- the one rule ------------------------------------------------------------------------------------------


def test_set_source_marks_to_review_only_when_a_source_changes():
    entry = ImageEntry(image=IMG, source="A", source_de="B")
    assert not alt_images.set_source(entry) and not alt_images.set_source(entry, "A", "B")
    assert entry.source_status == SOURCE_REVIEWED
    assert alt_images.set_source(entry, source_de="C") and entry.source_status == SOURCE_TO_REVIEW
    entry.source_status = SOURCE_REVIEWED
    assert alt_images.set_source(entry, source="") and (entry.source, entry.source_de) == ("", "C")
    assert entry.source_status == SOURCE_TO_REVIEW


def test_a_changed_source_clears_the_reviewed_state_and_only_a_person_restores_it(ctx):
    put(ctx, source="Own illustration")
    assert alt_images.save_source(ctx, IMG, source_de="Eigene Grafik").source_status == SOURCE_TO_REVIEW
    assert alt_images.save_source(ctx, IMG, source="Own illustration") is None       # no change: nothing written
    assert alt_images.mark_source_reviewed(ctx, IMG).source_status == SOURCE_REVIEWED
    assert alt_images.save_source(ctx, "media/none.png", source="x") is None
    assert alt_images.mark_source_reviewed(ctx, "media/none.png") is None


def test_the_descriptions_review_and_the_sources_are_independent(ctx, tmp_path):
    slide = tmp_path / "1aaa-x-current.tex"
    slide.write_text("body", encoding="utf-8")
    put(ctx, short="s", long="l", source="Own illustration")

    def save(reviewed, **typed):
        entry = stored(ctx)
        baseline = image_review.form_baseline(entry, "1aaa")
        edit = image_review.FormEdit(IMG, {**baseline, **typed}, baseline, alt_images.en_text_hash(entry))
        image_review.save_slide_forms(ctx, "1aaa", slide, [edit], reviewed=reviewed)

    save(True, source="Photo: Smith")                         # a form edit of the source
    entry = stored(ctx)
    assert (entry.status, entry.source_status) == (alt_images.STATUS_REVIEWED, SOURCE_TO_REVIEW)
    save(True)                                                # reviewing the description again leaves it
    assert stored(ctx).source_status == SOURCE_TO_REVIEW
    alt_images.mark_source_reviewed(ctx, IMG)                 # reviewing the source leaves the description
    entry = stored(ctx)
    assert entry.status == alt_images.STATUS_REVIEWED and entry.used_on["1aaa"].reviewed
    save(False, short="new short")                            # an edit of the description leaves the source
    assert stored(ctx).source_status == SOURCE_REVIEWED
    save(False, source_de="Foto: Smith")
    assert stored(ctx).source_status == SOURCE_TO_REVIEW


def test_a_pipeline_draft_or_translation_does_not_touch_the_source(ctx):
    from slidemage import alt_draft

    put(ctx, source="Own illustration")
    assert alt_draft.apply_one_draft(ctx, IMG, alt_draft.DraftResult(short="s", long="l"), "model")
    entry = stored(ctx)
    assert (entry.source, entry.source_status) == ("Own illustration", SOURCE_REVIEWED)


# -- writers that cannot use the setter: the store file written directly -----------------------------------


def write_store(ctx, **by_image):
    """Write the file as a tool would, with the given raw entries."""
    ctx.media_dir.mkdir(parents=True, exist_ok=True)
    (ctx.media_dir / "alt-text.json").write_text(json.dumps({"version": 2, "images": by_image}), encoding="utf-8")


def test_flag_edited_sources_flags_changed_and_new_sources_whatever_status_the_file_claims(ctx):
    write_store(ctx, **{"media/a.png": {"source": "A"}, "media/b.png": {"source": "B"}, "media/c.png": {"short": "s"}})
    before = (ctx.media_dir / "alt-text.json").read_text(encoding="utf-8")
    write_store(ctx, **{"media/a.png": {"source": "A2", "source_status": "reviewed"}, "media/b.png": {"source": "B"},
                        "media/c.png": {"source": "C"}, "media/d.png": {"source_de": "D"}})
    assert alt_images.flag_edited_sources(ctx, ctx.media_dir / "alt-text.json", before)
    states = {name: alt_images.source_state(entry) for name, entry in alt_images.load_store(ctx).items()}
    assert states == {"media/a.png": SOURCE_TO_REVIEW, "media/b.png": SOURCE_REVIEWED,
                      "media/c.png": SOURCE_TO_REVIEW, "media/d.png": SOURCE_TO_REVIEW}


def test_flag_edited_sources_ignores_other_files_unchanged_sources_and_unreadable_text(ctx):
    write_store(ctx, **{"media/a.png": {"source": "A"}})
    path = ctx.media_dir / "alt-text.json"
    before = path.read_text(encoding="utf-8")
    assert not alt_images.flag_edited_sources(ctx, path, before)                     # nothing changed
    assert not alt_images.flag_edited_sources(ctx, ctx.root / "slides" / "x.tex", "")
    assert alt_images.flag_edited_sources(ctx, path, "")                             # a new file: all new
    assert alt_images.flag_edited_sources(ctx, path, "not json at all")               # unreadable before: all new
    path.write_text("{ broken", encoding="utf-8")
    assert not alt_images.flag_edited_sources(ctx, path, before)                     # not a store: nothing to flag


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


def test_a_chat_tool_edit_of_the_store_file_sends_the_changed_source_to_review(agent):
    ctx, run = agent
    put(ctx, source="Own illustration", short="s")
    assert stored(ctx).source_status == SOURCE_REVIEWED
    result = run("edit_file", path=STORE, old_text='"source": "Own illustration"', new_text='"source": "Photo: Smith"')
    assert not result.is_error, result.text
    entry = stored(ctx)
    assert (entry.source, entry.source_status) == ("Photo: Smith", SOURCE_TO_REVIEW)
    alt_images.mark_source_reviewed(ctx, IMG)
    result = run("edit_file", path=STORE, old_text='"short": "s"', new_text='"short": "t"')
    assert not result.is_error and stored(ctx).source_status == SOURCE_REVIEWED       # not the source: left alone


def test_a_chat_tool_creating_the_store_file_flags_its_sources(agent):
    ctx, run = agent
    content = json.dumps({"version": 2, "images": {IMG: {"source": "Photo: Smith", "short": "s"}}})
    assert not run("write_file", path=STORE, content=content).is_error
    assert alt_images.source_state(stored(ctx)) == SOURCE_TO_REVIEW


@pytest.mark.parametrize("tool", ["Edit", "Write", "MultiEdit"])
def test_the_claude_code_hook_sends_a_changed_source_to_review(root, tool):
    ctx = ProjectContext.at(root)
    put(ctx, source="Own illustration")
    path = ctx.media_dir / "alt-text.json"
    event = {"cwd": str(root), "tool_name": tool, "tool_use_id": "t1", "tool_input": {"file_path": str(path)}}
    claude_hook.record_write(ctx, {**event, "hook_event_name": "PreToolUse"})
    path.write_text(path.read_text(encoding="utf-8").replace("Own illustration", "Photo: Smith"), encoding="utf-8")
    claude_hook.record_write(ctx, {**event, "hook_event_name": "PostToolUse"})
    assert stored(ctx).source_status == SOURCE_TO_REVIEW
    assert not list(ctx.claude_hook_dir.glob("*.json"))


def test_the_hook_leaves_a_failed_write_and_other_edits_of_the_store_alone(root):
    ctx = ProjectContext.at(root)
    put(ctx, source="Own illustration", short="s")
    path = ctx.media_dir / "alt-text.json"
    event = {"cwd": str(root), "tool_name": "Edit", "tool_use_id": "t2", "tool_input": {"file_path": str(path)}}
    claude_hook.record_write(ctx, {**event, "hook_event_name": "PreToolUse"})
    path.write_text(path.read_text(encoding="utf-8").replace('"short": "s"', '"short": "t"'), encoding="utf-8")
    claude_hook.record_write(ctx, {**event, "hook_event_name": "PostToolUse"})
    assert stored(ctx).source_status == SOURCE_REVIEWED and stored(ctx).short == "t"


def test_importing_the_manual_sends_a_replaced_entry_with_another_source_to_review(root, tmp_path):
    ctx = ProjectContext.at(root)
    put(ctx, source="Old credit", short="old")
    bundled = {IMG: {"role": "informative", "status": "auto", "short": "new", "source": "New credit"},
               "media/same.png": {"short": "x", "source": "Credit"}}
    # the same merge bundled_copies runs for the manual, over this project's store
    part = type("Part", (), {"source": tmp_path / "bundle", "update": [IMG], "add": ["media/same.png"]})()
    (part.source / "media").mkdir(parents=True)
    (part.source / "media" / "alt-text.json").write_text(json.dumps({"version": 2, "images": bundled}), encoding="utf-8")
    alt_images.update_store(ctx, lambda entries: entries.update({"media/same.png": ImageEntry(
        image="media/same.png", source="Credit")}) or True)
    bundled_copies._merge_image_descriptions(ctx, part)
    entries = alt_images.load_store(ctx)
    assert (entries[IMG].short, entries[IMG].source_status) == ("new", SOURCE_TO_REVIEW)
    assert entries["media/same.png"].source_status == SOURCE_REVIEWED          # same citation: nothing to review


# -- the Images page filter -------------------------------------------------------------------------------


def test_the_source_to_review_filter_lists_slides_but_does_not_change_their_state(tmp_path):
    from slidemage import alt_blocks

    path = tmp_path / "1aaa-x-current.tex"
    path.write_text("body", encoding="utf-8")
    row = alt_blocks.SlideRow(path=path, slide_id="1aaa", title="t", images=[IMG])
    entries = {IMG: ImageEntry(image=IMG, short="s", long="l", status=alt_images.STATUS_REVIEWED, source="x",
                               source_status=SOURCE_TO_REVIEW)}
    entries[IMG].used_on["1aaa"] = alt_images.SlideUse(reviewed="2026-01-01", stored_hash="h")
    views = [image_review.SlideView(row, image_review.slide_state(row, entries, "h"), "h")]
    assert views[0].state == alt_images.STATE_REVIEWED
    labels = [label for label, _ in image_review.FILTERS]
    counts = image_review.filter_counts(views, entries)
    assert counts[labels.index("Source to review")] == 1 and counts[labels.index("Needs attention")] == 0
