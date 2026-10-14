"""Claude provenance persists until explicit review, across all writing processes."""
from datetime import datetime
from hashlib import sha256
import json
import os
import subprocess
import sys

import pytest

from test_agent_tools import Box, LF, SLIDE
from slidemage import ai_review, fileio, slide_rename, unused_content
from slidemage.ai import claude_hook, project_watch
from slidemage.ai.agent_types import EDIT_AUTO
from slidemage.ai.tools.edits import ToolError, write_text
from slidemage.project import ProjectContext


@pytest.fixture
def project(root):
    return ProjectContext.at(root)


def test_metadata_persists_through_user_edits_until_explicit_review(project):
    path = project.root / SLIDE
    ai_review.mark(project, path, "draft", "add_slide")
    saved = ai_review.unreviewed(project)[SLIDE]
    assert saved["by"] == "claude" and saved["kind"] == "draft" and saved["source"] == "add_slide"
    assert datetime.fromisoformat(saved["since"]).tzinfo is not None
    assert saved["text_hash"] == sha256(LF.encode()).hexdigest()
    path.write_text("user changed it")
    assert ai_review.is_unreviewed(ProjectContext.at(project.root), path)
    assert ai_review.unreviewed(project)[SLIDE] == saved
    ai_review.mark_reviewed(project, [SLIDE])
    assert not ai_review.is_unreviewed(project, path)
    ai_review.mark(project, path, "edit", "rewrite")
    assert ai_review.is_unreviewed(project, path)


def test_non_slides_frozen_missing_and_outside_paths_are_never_marked(project, tmp_path):
    outside = tmp_path / "abc-EN-Outside-current.tex"
    outside.write_text("x")
    for path in (outside, project.decks_dir / "test.tex", project.bibliography_path,
                 project.slides_dir / "abc-EN-Hello-v1-0-0.tex", "slides/xxx-New-current.tex"):
        ai_review.mark(project, path, "edit", "terminal")
        assert not ai_review.is_unreviewed(project, path)
    assert ai_review.unreviewed(project) == {}


def test_store_is_tolerant_and_scoped_to_the_project(project, tmp_path):
    project.ai_review_path.write_text("broken json")
    assert ai_review.unreviewed(project) == {}
    ai_review.mark(project, SLIDE, "edit", "chat")
    assert ai_review.unreviewed(ProjectContext.at(tmp_path)) == {}
    fileio.write_json(project.ai_review_path, {"decks/test.tex": {"by": "claude"}, SLIDE: "bad entry"})
    assert ai_review.unreviewed(project) == {}


def test_failed_atomic_write_leaves_the_previous_store_intact(project, monkeypatch):
    ai_review.mark(project, SLIDE, "draft", "add_slide")
    before = project.ai_review_path.read_bytes()
    def fail(*args, **kwargs):
        raise OSError("full disk")
    monkeypatch.setattr(fileio, "replace_with_retry", fail)
    with pytest.raises(OSError, match="full disk"):
        ai_review.mark_reviewed(project, [SLIDE])
    assert project.ai_review_path.read_bytes() == before
    assert not list(project.settings_dir.glob("*.tmp"))


def test_concurrent_process_marks_and_reviews_do_not_lose_updates(project):
    paths = []
    for index in range(8):
        path = project.slides_dir / f"a{index}x-EN-Test-current.tex"
        path.write_text("text")
        paths.append(path)
        if index >= 4:
            ai_review.mark(project, path, "draft", "initial")
    script = (
        "import sys; from pathlib import Path; from slidemage import ai_review; "
        "from slidemage.project import ProjectContext; c=ProjectContext.at(Path(sys.argv[1])); "
        "ai_review.mark(c, sys.argv[2], 'edit', 'hook') if sys.argv[3]=='mark' "
        "else ai_review.mark_reviewed(c, [sys.argv[2]])"
    )
    processes = [subprocess.Popen([sys.executable, "-c", script, str(project.root), str(path),
                                  "mark" if i < 4 else "review"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                 for i, path in enumerate(paths)]
    for process in processes:
        _, err = process.communicate(timeout=30)
        assert process.returncode == 0, err.decode()
    assert set(ai_review.unreviewed(project)) == {p.relative_to(project.root).as_posix() for p in paths[:4]}


@pytest.mark.parametrize("buffer", [False, True])
def test_chat_edits_mark_the_written_text_on_disk_or_in_buffer(project, buffer):
    box = Box(project.root, EDIT_AUTO)
    path = project.root / SLIDE
    if buffer:
        box.ws.open(path, LF)
    box.ok("edit_file", path=SLIDE, old_text="First point", new_text="New point")
    entry = ai_review.unreviewed(project)[SLIDE]
    assert entry["text_hash"] == sha256(LF.replace("First point", "New point").encode()).hexdigest()
    if buffer:
        assert "New point" not in path.read_text()


def test_rejected_noop_and_stale_edits_do_not_mark(project):
    box = Box(project.root, approve=False)
    box.error("edit_file", path=SLIDE, old_text="First point", new_text="New")
    box.ok("edit_file", path=SLIDE, old_text="First point", new_text="First point")
    with pytest.raises(ToolError):
        write_text(box.ws, project.root / SLIDE, "stale", "new")
    assert ai_review.unreviewed(project) == {}


@pytest.mark.parametrize("translation", [False, True])
def test_add_slide_marks_drafts_partners_and_deck_insertions(project, translation):
    box = Box(project.root, EDIT_AUTO)
    args = dict(title="New", slug="New", language="DE" if translation else "EN", after="abc")
    if translation:
        args["translation_of"] = "abc"
    box.ok("add_slide", **args)
    entries = ai_review.unreviewed(project)
    new = next(key for key in entries if "-New-" in key)
    assert entries[new]["kind"] == ("translation" if translation else "draft")
    assert entries[new]["decks"] == ["decks/test.tex"]
    assert (SLIDE in entries) == translation
    assert all(key.startswith("slides/") for key in entries)


def test_failed_insertion_still_marks_the_created_draft(project):
    box = Box(project.root)
    def dirty_after_creation(*args, **kwargs):
        box.ws.dirty.add(box.ws.context().deck.path)
        return True
    box.ws.before_confirm = dirty_after_creation
    box.error("add_slide", title="New", slug="New", language="EN", after="abc")
    entries = ai_review.unreviewed(project)
    assert len(entries) == 1
    assert "decks" not in next(iter(entries.values()))


@pytest.mark.parametrize("operation", ["slug", "language", "id"])
def test_renames_carry_provenance_but_never_mark_frozen_versions(project, operation):
    ai_review.mark(project, SLIDE, "translation", "translate")
    saved = ai_review.unreviewed(project)[SLIDE]
    if operation == "slug":
        renamed = slide_rename.rename_slide_slug(project, "abc-EN-Hello", "Renamed")
    elif operation == "language":
        renamed = slide_rename.set_slide_language(project, "abc-EN-Hello", "DE")
    else:
        renamed = slide_rename.rename_slide_id(project, "abc", "zzz")["abc-EN-Hello"]
    assert ai_review.unreviewed(project) == {f"slides/{renamed}-current.tex": saved}
    assert len(fileio.read_json(project.ai_review_path)) == 1


def test_deleting_and_archiving_drop_marks_but_skipped_archives_keep_them(project):
    ai_review.mark(project, SLIDE, "edit", "chat")
    slide_rename.delete_slide_id(project, "abc-EN-Hello")
    assert fileio.read_json(project.ai_review_path) == {}
    path = project.slides_dir / "abd-EN-Second-current.tex"
    ai_review.mark(project, path, "edit", "chat")
    archive = project.slides_dir / "archive"
    archive.mkdir()
    (archive / path.name).write_text("collision")
    assert unused_content.archive_files(project, [], [path], lambda _: None) == (0, 0)
    assert ai_review.is_unreviewed(project, path)
    (archive / path.name).unlink()
    assert unused_content.archive_files(project, [], [path], lambda _: None) == (0, 1)
    assert fileio.read_json(project.ai_review_path) == {}


@pytest.mark.parametrize("tool", ["Edit", "Write", "MultiEdit"])
def test_real_post_hook_process_marks_written_slide_and_poll_notices_store(project, tool):
    event = dict(cwd=str(project.root), tool_name=tool, tool_use_id="tool-1",
                 tool_input={"file_path": SLIDE})
    env = {**os.environ, "SLIDEMASTER_PROJECT": str(project.root)}
    def hook(name):
        payload = json.dumps({**event, "hook_event_name": name})
        done = subprocess.run([sys.executable, "-m", "slidemage.ai.claude_hook"],
                              input=payload, text=True, env=env, capture_output=True, timeout=30)
        assert done.returncode == 0, done.stderr
    hook("PreToolUse")
    path = project.root / SLIDE
    path.write_text(LF.replace("First point", "Native change"))
    before = project_watch.scan(project.root)
    hook("PostToolUse")
    entry = ai_review.unreviewed(project)[SLIDE]
    assert entry["source"] == f"Claude Code terminal: {tool}" and entry["kind"] == "edit"
    assert project.ai_review_path in project_watch.diff(before, project_watch.scan(project.root)).added
    assert not list(project.claude_hook_dir.glob("*.json"))


def test_hook_handles_relative_new_write_failures_noops_and_frozen_files(project):
    path = project.slides_dir / "zzz-EN-New-current.tex"
    event = dict(cwd=str(project.slides_dir), hook_event_name="PreToolUse", tool_name="Write",
                 tool_use_id="new", tool_input={"file_path": path.name, "content": "new"})
    claude_hook.record_write(project, event)
    path.write_text("new")
    claude_hook.record_write(project, {**event, "hook_event_name": "PostToolUse"})
    assert ai_review.unreviewed(project)["slides/" + path.name]["kind"] == "draft"
    ai_review.mark_reviewed(project, [path])
    claude_hook.record_write(project, event)
    claude_hook.record_write(project, {**event, "hook_event_name": "PostToolUse"})
    assert not ai_review.unreviewed(project)
    path.write_text("changed")
    claude_hook.record_write(project, {**event, "hook_event_name": "PostToolUse", "tool_response": {"isError": True}})
    frozen = project.slides_dir / "abc-EN-Hello-v1-0-0.tex"
    claude_hook.record_write(project, {**event, "hook_event_name": "PostToolUse", "tool_input": {"file_path": str(frozen)}})
    assert not ai_review.unreviewed(project)


def test_native_deck_write_notes_only_inserted_live_calls_on_the_slides(project):
    deck = project.decks_dir / "test.tex"
    event = dict(cwd=str(project.root), tool_name="Write", tool_use_id="deck-write",
                 hook_event_name="PreToolUse", tool_input={"file_path": str(deck)})
    claude_hook.record_write(project, event)
    deck.write_text(deck.read_text().replace("\\end{document}",
                    "\\slide{abd-EN-Second}\n\\slideversion{abc-EN-Hello}{1-0-0}\n\\end{document}"))
    claude_hook.record_write(project, {**event, "hook_event_name": "PostToolUse"})
    assert set(ai_review.unreviewed(project)) == {"slides/abd-EN-Second-current.tex"}
    assert next(iter(ai_review.unreviewed(project).values()))["decks"] == ["decks/test.tex"]


@pytest.mark.parametrize("buffer", [False, True])
def test_deck_insertion_provenance_survives_later_body_edits(project, buffer):
    box = Box(project.root, EDIT_AUTO)
    if buffer:
        path = project.decks_dir / "test.tex"
        box.ws.open(path, path.read_text())
    box.ok("edit_file", path="decks/test.tex", old_text="\\end{document}",
           new_text="\\slide{abc-EN-Hello}\n\\end{document}")
    box.ok("edit_file", path=SLIDE, old_text="First point", new_text="New point")
    assert ai_review.unreviewed(project)[SLIDE]["decks"] == ["decks/test.tex"]


# -- the text before the last AI edit (the earlier side of Compare rendered) -------------------------

@pytest.mark.parametrize("buffer", [False, True])
def test_a_chat_edit_keeps_the_text_it_replaced(project, buffer):
    box = Box(project.root, EDIT_AUTO)
    path = project.root / SLIDE
    if buffer:
        box.ws.open(path, LF)
    assert ai_review.last_before(project, path) is None
    box.ok("edit_file", path=SLIDE, old_text="First point", new_text="New point")
    assert ai_review.last_before(project, path) == LF
    box.ok("edit_file", path=SLIDE, old_text="New point", new_text="Newer point")        # the last edit only
    assert ai_review.last_before(project, path) == LF.replace("First point", "New point")
    ai_review.mark_reviewed(project, [SLIDE])
    assert ai_review.last_before(project, path) is not None                              # kept after the review


def test_the_hook_keeps_the_text_before_a_terminal_edit_but_not_for_a_new_slide(project):
    path = project.root / SLIDE
    event = dict(cwd=str(project.root), tool_name="Edit", tool_use_id="e1", hook_event_name="PreToolUse",
                 tool_input={"file_path": SLIDE})
    claude_hook.record_write(project, event)
    path.write_bytes(path.read_bytes().replace(b"First point", b"Native change"))
    claude_hook.record_write(project, {**event, "hook_event_name": "PostToolUse"})
    assert ai_review.last_before(project, path) == LF                     # line ends as the hook reads them
    new = project.slides_dir / "zzz-EN-New-current.tex"
    event = {**event, "tool_name": "Write", "tool_use_id": "e2", "tool_input": {"file_path": str(new)}}
    claude_hook.record_write(project, event)
    new.write_text("new")
    claude_hook.record_write(project, {**event, "hook_event_name": "PostToolUse"})
    assert ai_review.is_unreviewed(project, new) and ai_review.last_before(project, new) is None
    assert ai_review.last_before(project, project.bibliography_path) is None


def test_the_kept_text_follows_a_rename_and_ignores_an_unchanged_write(project):
    ai_review.mark(project, SLIDE, "edit", "chat", before=LF)           # nothing changed: nothing to keep
    assert ai_review.last_before(project, SLIDE) is None
    ai_review.mark(project, SLIDE, "edit", "chat", before=LF.replace("First", "Old"))
    renamed = slide_rename.rename_slide_slug(project, "abc-EN-Hello", "Renamed")
    assert ai_review.last_before(project, SLIDE) is None
    assert ai_review.last_before(project, project.slides_dir / f"{renamed}-current.tex") == LF.replace("First", "Old")
