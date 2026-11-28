# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Claude provenance persists until explicit review, across all writing processes."""
from datetime import datetime
from hashlib import sha256
import subprocess
import sys

import pytest

from test_agent_tools import Box, LF, SLIDE, plus
from slidemage import ai_review, fileio, slide_rename, unused_content
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


def test_media_changes_mark_only_affected_live_slides_and_preserve_drafts(project):
    media = project.root / "media"
    media.mkdir(exist_ok=True)
    plot, other = media / "plot.PNG", media / "other.png"
    plot.write_bytes(b"old")
    other.write_bytes(b"old")
    for name, image in (("Plot-current", "Plot"), ("Other-current", "other"), ("Plot-v1-0-0", "Plot")):
        (project.slides_dir / f"img-EN-{name}.tex").write_text(
            f"\\includegraphics{{media/{image}}}\n", encoding="utf-8")
    for folder in (".build", "pdf"):
        (project.root / folder).mkdir(exist_ok=True)
        (project.root / folder / "ignored.png").write_bytes(b"x")

    before = ai_review.media_snapshot(project)
    assert set(before) == {"media/plot.PNG", "media/other.png"}
    assert ai_review.mark_media_changes(project, before, "terminal") == []
    plot.write_bytes(b"replacement")
    marked, = ai_review.mark_media_changes(project, before, "terminal")
    assert marked.name == "img-EN-Plot-current.tex"
    entry = ai_review.unreviewed(project)["slides/img-EN-Plot-current.tex"]
    assert entry["kind"] == "edit" and entry["source"] == "terminal: media/plot.PNG"

    before = ai_review.media_snapshot(project)
    ai_review.mark(project, marked, "draft", "add_slide")
    plot.write_bytes(b"replacement again")
    other.unlink()
    ai_review.mark_media_changes(project, before, "terminal")
    entries = ai_review.unreviewed(project)
    assert entries["slides/img-EN-Plot-current.tex"]["kind"] == "draft"
    assert entries["slides/img-EN-Other-current.tex"]["kind"] == "edit"


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


def test_rejected_noop_and_stale_edits_do_not_mark(project):
    box = Box(project.root, approve=False)
    box.error("edit_file", path=SLIDE, old_text="First point", new_text="New")
    box.ok("edit_file", path=SLIDE, old_text="First point", new_text="First point")
    with pytest.raises(ToolError):
        write_text(box.ws, project.root / SLIDE, "stale", "new")
    assert ai_review.unreviewed(project) == {}


def test_renames_carry_provenance_and_kept_text_to_the_live_slide(project):
    ai_review.mark(project, SLIDE, "edit", "chat", before=LF)
    assert ai_review.last_before(project, SLIDE) is None
    previous = LF.replace("First", "Old")
    ai_review.mark(project, SLIDE, "edit", "chat", before=previous)
    saved = ai_review.unreviewed(project)[SLIDE]
    renamed = slide_rename.rename_slide_slug(project, "abc-EN-Hello", "Renamed")
    assert ai_review.last_before(project, SLIDE) is None
    assert ai_review.last_before(project, f"slides/{renamed}-current.tex") == previous
    assert fileio.read_json(project.ai_review_path) == {f"slides/{renamed}-current.tex": saved}
    renamed = slide_rename.set_slide_language(project, renamed, "DE")
    assert fileio.read_json(project.ai_review_path) == {f"slides/{renamed}-current.tex": saved}
    renamed = slide_rename.rename_slide_id(project, "abc", "zzz")[renamed]
    assert fileio.read_json(project.ai_review_path) == {f"slides/{renamed}-current.tex": saved}


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


@pytest.mark.parametrize("buffer", [False, True], ids=["disk", "buffer"])
def test_chat_edits_keep_the_replaced_text_and_deck_provenance(project, buffer):
    box = Box(project.root, EDIT_AUTO)
    deck, path = project.decks_dir / "test.tex", project.root / SLIDE
    if buffer:
        box.ws.open(deck, deck.read_text())
        box.ws.open(path, LF)
    box.ok("edit_file", path="decks/test.tex", old_text="\\end{document}",
           new_text="\\slide{abc-EN-Hello}\n\\end{document}")
    assert ai_review.last_before(project, path) is None
    box.ok("edit_file", path=SLIDE, old_text="First point", new_text="New point")
    assert ai_review.last_before(project, path) == LF
    written = LF.replace("First point", "New point")
    written = written if buffer else plus(written)
    entry = ai_review.unreviewed(project)[SLIDE]
    assert entry["text_hash"] == sha256(written.encode()).hexdigest()
    assert entry["decks"] == ["decks/test.tex"]
    if buffer:
        assert "New point" not in path.read_text()
    box.ok("edit_file", path=SLIDE, old_text="New point", new_text="Newer point")
    ai_review.mark_reviewed(project, [SLIDE])
    assert ai_review.last_before(project, path) == written


# -- the text before the last AI edit (the earlier side of Compare rendered) -------------------------
