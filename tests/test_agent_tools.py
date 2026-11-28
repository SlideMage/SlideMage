# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Agent tools and context on a throwaway project."""
from __future__ import annotations

import base64
import os
from dataclasses import replace
import time

import pytest
import pymupdf
from agent_fakes import FakeWorkspace, call
from conftest import SLIDE_TEXT

from slidemage import ai_review, batch_render, compiler, preview_target, render_lookup
from slidemage.ai import agent_context, translation_style
from slidemage.ai.agent_types import (
    EDIT_ASK,
    EDIT_AUTO,
    EditApplied,
    EditProposed,
    EditRejected,
)
from slidemage.ai.tools import build_toolbox, focus, undo_edit
from slidemage.ai.tools import previews as previews_tools
from slidemage.ai.tools import slidemage as slidemage_tools
from slidemage.project import ProjectContext
from slidemage.ai.workspace import Workspace, WorkspaceContext
from slidemage.deck_scan import scan_decks


SLIDE = "slides/abc-EN-Hello-current.tex"
LF = SLIDE_TEXT.replace("\r\n", "\n")


def plus(text):
    return text.replace("\\setSlideVersion{1-0-0}", "\\setSlideVersion{1-0-0+}")


class Box:
    """A toolbox on the throwaway project with the events it emitted."""

    def __init__(self, root, mode=EDIT_ASK, approve=True):
        deck = next(d for d in scan_decks(ProjectContext.at(root)) if d.name == "test")
        self.ws = FakeWorkspace(root, WorkspaceContext(deck=deck, slide_id="abc", path=root / SLIDE), approve)
        self.events = []
        self.box = build_toolbox(self.ws, self.events.append, compiler.CancelToken(), mode)
        self.root = root

    def run(self, name, **arguments):
        return self.box.execute(call(name, **arguments))

    def ok(self, name, **arguments):
        result = self.run(name, **arguments)
        assert not result.is_error, result.text
        return result.text

    def error(self, name, **arguments):
        result = self.run(name, **arguments)
        assert result.is_error, result.text
        return result.text

    def of_type(self, kind):
        return [e for e in self.events if isinstance(e, kind)]


@pytest.fixture
def box(root):
    return Box(root)


def test_a_symlink_leading_out_is_refused(box, tmp_path):
    (tmp_path / "secret.txt").write_text("outside")
    for path in ("../secret.txt", str(tmp_path / "secret.txt")):
        assert "outside the project folder" in box.error("read_file", path=path)
    assert "outside" in box.error("write_file", path="../x.md", content="x")
    try:
        os.symlink(tmp_path / "secret.txt", box.root / "link.txt")
    except OSError:
        pytest.skip("no symlinks here")
    assert "outside the project folder" in box.error("read_file", path="link.txt")
    assert "outside the project folder" in box.error("edit_file", path="link.txt", old_text="o", new_text="x")


def test_find_and_search_skip_dot_files_and_links_into_hidden_folders(box):
    slides = box.root / "slides"
    (slides / ".hid-EN-Dot-current.tex").write_text("needle in a dot-file\n")
    secret = box.root / ".slidemage" / "app_settings.json"
    try:
        os.symlink(secret, slides / "lnk-EN-Link-current.tex")
        os.symlink(secret, box.root / "decks" / "linked.tex")
    except OSError:
        pytest.skip("no symlinks here")
    listed = box.ok("find_files", pattern="**/*.tex")
    assert "hid-EN-Dot" not in listed and "lnk-EN-Link" not in listed and "linked.tex" not in listed
    assert "Nothing found" in box.ok("search", query="sk-secret")
    assert "Nothing found" in box.ok("search", query="needle in a dot")


def test_get_focus_does_not_name_a_file_the_model_may_not_see(box):
    box.ws._context = WorkspaceContext(path=box.root / ".slidemage" / "app_settings.json")
    toolbox = build_toolbox(box.ws, box.events.append, compiler.CancelToken(), tools=[focus.get_focus])
    result = toolbox.execute(call("get_focus"))
    assert not result.is_error and "app_settings" not in result.text and "may see" in result.text


def test_read_file_numbers_lines_normalises_line_ends_and_pages(box):
    text = box.ok("read_file", path=SLIDE)
    assert text.startswith(f"{SLIDE} (12 lines; file)\n1\t%% Included in decks: test\n")
    assert "\r" not in text and "6\t\\begin{standardframe}{Hello}" in text
    part = box.ok("read_file", path=SLIDE, start_line=7, max_lines=2)
    assert "7\t\t\\begin{itemize}" in part and "read on with start_line=9" in part
    assert "There is no line 99" in box.ok("read_file", path=SLIDE, start_line=99)
    box.ws.open(box.root / SLIDE, "buffer text\n", dirty=True)
    assert "1\tbuffer text" in box.ok("read_file", path=SLIDE)


def test_read_file_refusals_are_logged(box, monkeypatch):
    events = []
    monkeypatch.setattr("slidemage.timing.event", lambda root, name, **fields: events.append((name, fields)))
    assert "is a folder" in box.error("read_file", path="slides")
    assert events == [("tool_start", {"tool": "read_file"}), ("tool_end", {"tool": "read_file", "error": True})]
    events.clear()
    box.error("unknown")
    assert not events

    assert "does not exist" in box.error("read_file", path="slides/nope.tex")
    (box.root / "pic.bin").write_bytes(b"\x89PNG\0\0data")
    assert "not a text file" in box.error("read_file", path="pic.bin")


def test_find_files_matches_patterns(box):
    assert box.ok("find_files", pattern="slides/*-current.tex").splitlines() == [
        "slides/abc-EN-Hello-current.tex", "slides/abd-EN-Second-current.tex"]
    assert "SlideMage.bib" in box.ok("find_files", pattern="*.bib")
    assert "decks/test.tex" in box.ok("find_files", pattern="**/*.tex")
    assert "No file matches" in box.ok("find_files", pattern="*.xyz")
    assert ".." in box.error("find_files", pattern="../*")


def test_search_finds_text_in_slides_and_the_bib(box):
    out = box.ok("search", query="second point")
    assert "slides/abc-EN-Hello-current.tex:9" in out and "slides/abd-EN-Second-current.tex" in out
    assert "SlideMage.bib" in box.ok("search", query="Older")
    assert "at least 2" in box.error("search", query="x")


def test_bad_arguments_and_unknown_tools_become_error_results(box):
    assert "Missing required argument 'path'" in box.error("read_file")
    assert "must be of type integer" in box.error("read_file", path=SLIDE, start_line="1")
    assert "Unknown argument 'existing'" in box.error("add_slide", existing="abc")
    assert "no tool 'rm'" in box.error("rm", path="x")
    for tool_name in ("render_preview", "refresh_preview"):
        assert "Argument 'view' must be one of" in box.error(tool_name, view="student")

    for edits, detail in (
        ([], "needs at least 1 item"),
        ([{"old": "", "new": "b"}], "Argument 'edits[0].old' needs at least 1 character"),
        ([{"old": "a"}], "Missing required argument 'edits[0].new'"),
        ([{"old": "a", "new": "b", "other": 1}], "Unknown argument 'edits[0].other'"),
    ):
        assert detail in box.error("modify_slide", slide="abc", edits=edits)
    assert "'fields.url' must be of type string" in box.error("make_qr_code", kind="url", fields={"url": False})
    assert "'height' must be of type number" in box.error("make_qr_code", kind="url", fields={"url": "a.org"}, height=True)


def test_edit_on_disk_preserves_crlf_backs_up_and_allows_notes_and_overlays(box, root):
    box.box.ctx.mode = EDIT_AUTO
    path = root / SLIDE
    old, new = "%%\n\n% A note", "%%\n% Source: a paper\n\n% A note"
    assert "saved it" in box.ok("edit_file", path=SLIDE, old_text=old, new_text=new)
    updated = LF.replace(old, new)
    assert path.read_bytes().decode() == plus(updated).replace("\n", "\r\n")
    assert path.with_name("abc-EN-Hello-v1-0-0.tex").read_bytes().decode() == SLIDE_TEXT
    backup, = (path.parent / ".backups" / path.name).glob("*.tex")
    assert backup.read_bytes().decode() == SLIDE_TEXT and box.ws.changed == [(path, LF)]
    (proposed,), (applied,) = box.of_type(EditProposed), box.of_type(EditApplied)
    assert (applied.before, applied.after, applied.via_buffer) == (LF, updated, False)
    assert (proposed.after, proposed.call_id) == (applied.after, applied.call_id) and not box.ws.asked
    box.ok("edit_file", path=SLIDE, old_text=r"\hbox{overlay}", new_text=r"\hbox{changed}")
    assert r"\hbox{changed}" in path.read_text()


def test_edit_in_an_open_buffer_leaves_the_disk_alone(box, root):
    box.box.ctx.mode = EDIT_AUTO
    box.ws.open(root / SLIDE, LF.replace("First", "Unsaved"), dirty=True)     # the user typed already
    out = box.ok("edit_file", path=SLIDE, old_text="Second point", new_text="2nd point")
    assert "open editor" in out and "not saved" in out
    assert box.ws.buffers[root / SLIDE] == LF.replace("First", "Unsaved").replace("Second", "2nd")
    assert (root / SLIDE).read_bytes().decode() == SLIDE_TEXT and not box.ws.changed
    assert box.of_type(EditApplied)[0].via_buffer is True


def test_read_only_and_changed_buffers_are_not_overwritten(box, root):
    path = root / SLIDE
    edit = dict(path=SLIDE, old_text="First", new_text="1st")
    box.ws.open(path, LF)
    box.ws.read_only.add(path)
    assert "read-only" in box.error("edit_file", **edit)
    assert box.ws.buffers[path] == LF
    box.ws.read_only.clear()

    changed = LF + "typed meanwhile\n"
    box.ws.before_confirm = lambda: box.ws.buffers.__setitem__(path, changed)
    assert "changed while the edit waited" in box.error("edit_file", **edit)
    assert box.ws.buffers[path] == changed and not box.of_type(EditApplied)


def test_a_file_changed_on_disk_after_reading_is_not_overwritten(box, root):
    box.ws.before_confirm = lambda: (root / SLIDE).write_bytes(b"someone else was here")
    assert "changed on disk" in box.error("edit_file", path=SLIDE, old_text="First", new_text="1st")
    assert (root / SLIDE).read_bytes() == b"someone else was here"


def test_old_text_must_occur_exactly_once(box, root):
    assert "occurs 2 times" in box.error("edit_file", path=SLIDE, old_text="point", new_text="p")
    assert "was not found" in box.error("edit_file", path=SLIDE, old_text="Third", new_text="x")
    assert "different spacing" in box.error("edit_file", path=SLIDE, old_text="First  point", new_text="x")
    assert "empty" in box.error("edit_file", path=SLIDE, old_text="", new_text="x")
    assert "nothing to change" in box.ok("edit_file", path=SLIDE, old_text="First", new_text="First")
    assert (root / SLIDE).read_bytes().decode() == SLIDE_TEXT and not box.ws.asked


@pytest.mark.parametrize("old, new", [
    ("%% Included in decks: test", "%% Included in decks: test, other"),      # SlideMage's '%%' header lines
    ("%% Included in decks: test\n%%\n", ""),
    ("\\setSlideVersion{1-0-0}", "\\setSlideVersion{1-1-0}"),
    ("\\setSlideVersion{1-0-0}\n", ""),
])
def test_protected_parts_of_a_slide_are_refused(box, root, old, new):
    box.box.ctx.mode = EDIT_AUTO
    assert "protected part" in box.error("edit_file", path=SLIDE, old_text=old, new_text=new)
    assert (root / SLIDE).read_bytes().decode() == SLIDE_TEXT and not box.of_type(EditProposed)


def test_frozen_versions_and_non_text_files_cannot_be_changed(box, root):
    assert "frozen version" in box.error("edit_file", path="slides/abc-EN-Hello-v1-0-0.tex", old_text="First", new_text="x")
    assert "frozen version" in box.error("write_file", path="slides/abc-EN-Hello-v9-0-0.tex", content="x")
    (root / "run.py").write_text("print(1)")
    assert "only text files" in box.error("edit_file", path="run.py", old_text="1", new_text="2")
    assert "only text files" in box.error("write_file", path="evil.bat", content="x")


def test_ask_mode_waits_for_the_user_and_reports_a_rejection(root):
    box = Box(root, approve=False)
    assert "rejected" in box.error("edit_file", path=SLIDE, old_text="First", new_text="1st")
    assert (root / SLIDE).read_bytes().decode() == SLIDE_TEXT and not box.of_type(EditApplied)
    assert [type(e) for e in box.events] == [EditProposed, EditRejected]
    assert box.ws.asked == [(root / SLIDE, LF, LF.replace("First", "1st"))]


def test_write_file_creates_new_text_files_only(box, root):
    box.box.ctx.mode = EDIT_AUTO
    box.ok("write_file", path="notes/todo.md", content="- one\r\n- two\n")
    assert (root / "notes" / "todo.md").read_bytes() == b"- one\n- two\n"
    assert box.ws.changed[-1] == (root / "notes" / "todo.md", None)
    assert box.of_type(EditApplied)[-1].undoable is False
    assert "exists already" in box.error("write_file", path="notes/todo.md", content="x")
    assert "add_slide" in box.error("write_file", path="slides/new-EN-Slide-current.tex", content="x")


def test_write_file_does_not_overwrite_a_file_that_appeared_while_the_user_decided(box, root):
    target = root / "notes.md"
    box.ws.before_confirm = lambda: target.write_text("theirs")
    assert "was created while" in box.error("write_file", path="notes.md", content="mine")
    assert target.read_text() == "theirs" and not box.of_type(EditApplied)


def test_undo_puts_the_old_text_back_unless_the_file_moved_on(box, root):
    box.box.ctx.mode = EDIT_AUTO
    box.ok("edit_file", path=SLIDE, old_text="First", new_text="1st")
    applied = box.of_type(EditApplied)[0]
    assert undo_edit(box.ws, applied) == ""
    assert (root / SLIDE).read_bytes().decode() == SLIDE_TEXT

    box.ok("edit_file", path=SLIDE, old_text="First", new_text="1st")
    applied = box.of_type(EditApplied)[1]
    (root / SLIDE).write_bytes(b"changed since")
    assert "changed since" in undo_edit(box.ws, applied)
    assert (root / SLIDE).read_bytes() == b"changed since"


def test_list_slides_shows_the_open_decks_slides(box):
    out = box.ok("list_slides")
    assert out.splitlines()[0].startswith("Deck test (decks/test.tex), viewed as instructor, EN: 2 slides.")
    assert "§ Intro\n  1. abc | Hello | slides/abc-EN-Hello-current.tex | \\slide" in out
    assert "§ Main\n  2. abd | Second | slides/abd-EN-Second-current.tex" in out
    assert "§ Main" not in box.ok("list_slides", section="intro")
    assert "abd" not in box.ok("list_slides", contains="hello")
    assert "No slide matches" in box.ok("list_slides", contains="zzz")
    assert "There is no deck 'nope'. Decks: test" in box.error("list_slides", deck="nope")
    box.ws._context = WorkspaceContext()
    assert "No deck is open. Decks: test" in box.error("list_slides")


def test_list_slides_uses_the_open_deck_path_and_refuses_an_ambiguous_name(box):
    project = box.ws.project
    project.archive_dir.mkdir()
    archived = project.archive_dir / "test.tex"
    archived.write_text("\\documentclass{beamer}\n\\begin{document}\n\\slide{abd-EN-Second}\n\\end{document}\n",
                        encoding="utf-8")
    deck = next(d for d in scan_decks(project) if d.path == archived)
    box.ws._context = WorkspaceContext(deck=deck)
    out = box.ok("list_slides")
    assert "abd | Second" in out and "abc | Hello" not in out

    error = box.error("list_slides", deck="test.tex")
    assert "ambiguous" in error and "decks/test.tex" in error and "decks/archive/test.tex" in error


def test_list_slides_cuts_at_the_limit_without_an_empty_heading_and_says_so_only_when_it_cut(box, monkeypatch):
    monkeypatch.setattr(slidemage_tools, "LIST_LIMIT", 1)
    out = box.ok("list_slides")
    assert "abc" in out and "abd" not in out and "§ Main" not in out and "[Only the first 1;" in out
    monkeypatch.setattr(slidemage_tools, "LIST_LIMIT", 2)
    out = box.ok("list_slides")
    assert "abc" in out and "abd" in out and "[Only the first" not in out


def test_lint_checks_the_buffer_when_the_file_is_open(box, root):
    assert "no problems found" in box.ok("lint", path="abc")
    box.ws.open(root / SLIDE, LF + "\\begin{itemize}\n", dirty=True)
    out = box.ok("lint")
    assert "error(s)" in out and "[error]" in out
    assert "Only .tex" in box.error("lint", path="SlideMage.bib")


def test_render_preview_uses_the_buffer_selected_view_and_current_cache(box, root, monkeypatch):
    box.ws._context = replace(box.ws.context(), view="during-course")
    texts = []
    seen = fake_render(monkeypatch, root, texts=texts)
    draft = LF + "% unsaved\n"
    box.ws.open(root / SLIDE, draft)
    result = box.run("render_preview")
    assert not result.is_error and len(result.images) == 1
    assert seen == [("abc-EN-Hello", 1, "during-course", "EN")] and texts == [draft]
    spec, = box.ws.prepare_preview_batch(root / SLIDE, "during-course")
    renderer = box.ws.preview_service().renderer(box.ws.project)
    state, record = render_lookup.select(dict(resolver=renderer.resolver, unit=spec.unit, spec=spec), strict=True)
    assert state == "current" and result.images == [renderer.store.page(record, record["pages"])]
    assert box.run("render_preview").images == result.images and len(seen) == 1

    fake_render(monkeypatch, root, fail="! Undefined control sequence.")
    box.ws.open(root / SLIDE, LF + "% another edit\n")
    assert "Undefined control sequence" in box.error("render_preview")


def test_add_slide_asks_first_and_refuses_what_it_cannot_do(root):
    box = Box(root, approve=False)
    assert "rejected" in box.error("add_slide", slug="Nope", title="T")
    assert not list((root / "slides").glob("*Nope*"))
    box.ws.approve = True
    assert "letters, digits" in box.error("add_slide", slug="bad slug", title="T")
    assert "no slide 'zzz'" in box.error("add_slide", slug="Ok", title="T", after="zzz")
    box.ws.dirty.add(root / "decks" / "test.tex")
    assert "unsaved edits" in box.error("add_slide", slug="Ok", title="T")
    assert "created" in box.ok("add_slide", slug="Ok", title="T", add_to_deck=False).lower()
    assert "Ok-current.tex" in "\n".join(p.name for p in (root / "slides").iterdir())
    assert "Ok" not in (root / "decks" / "test.tex").read_text()


def test_add_slide_rechecks_dirty_deck_after_confirmation(box, root):
    deck = root / "decks/test.tex"
    before = deck.read_bytes()
    box.ws.before_confirm = lambda: box.ws.open(deck, "user's pending edits", dirty=True)
    text = box.error("add_slide", slug="Pending", title="T")
    created, = (root / "slides").glob("*-EN-Pending-current.tex")
    assert created.name in text and "unsaved edits" in text and "insert_slide(slide=" in text
    assert deck.read_bytes() == before and box.ws.buffer_text(deck) == "user's pending edits"
    applied, = box.of_type(EditApplied)
    assert applied.path == created and applied.note == "not added to a deck"
    entry = ai_review.unreviewed(box.ws.project)[created.relative_to(root).as_posix()]
    assert entry["kind"] == "draft" and "decks" not in entry


def test_add_uses_the_approved_body_and_keeps_both_commits_when_review_fails(box, root, monkeypatch):
    project = box.ws.project
    template = project.slide_template_path
    template.write_text("\\begin{standardframe}{Title}\nApproved body\n\\end{standardframe}\n", encoding="utf-8")
    box.ws.before_confirm = lambda: template.write_text("Changed template", encoding="utf-8")
    checks = []

    def before_insert(*args, **kwargs):
        created, = project.slides_dir.glob("*-Captured-current.tex")
        assert "Approved body" in created.read_text()
        assert created.name[:3] in project.slide_ids_csv.read_text()
        assert created.name.removesuffix("-current.tex") not in (project.decks_dir / "test.tex").read_text()
        checks.append("library committed")
        raise OSError("slide review unavailable")

    def after_insert(_project, path, before, after, *args):
        assert path.read_bytes().decode() == after != before
        checks.append("deck committed")
        raise OSError("deck review unavailable")

    monkeypatch.setattr(ai_review, "mark", before_insert)
    monkeypatch.setattr(ai_review, "inserted_slides", after_insert)
    result = box.ok("add_slide", slug="Captured", title="Captured")
    assert checks == ["library committed", "deck committed"]
    assert "Created slide" in result and "slide review unavailable" in result and "deck review unavailable" in result


def test_insert_slide_checks_scope_consent_and_dirty_deck_before_inserting(box, root):
    box.ok("add_slide", slug="Insert", title="T", add_to_deck=False)
    created, = (root / "slides").glob("*-EN-Insert-current.tex")
    path = created.relative_to(root).as_posix()
    assert ai_review.unreviewed(box.ws.project)[path]["kind"] == "draft"
    deck = root / "decks/test.tex"
    before = deck.read_bytes()
    box.events.clear()
    box.box.ctx.scope = "slide"
    assert "switch_to_deck_mode" in box.error("insert_slide", slide=path)
    box.box.ctx.scope = None
    box.ws.dirty.add(deck)
    assert "unsaved edits" in box.error("insert_slide", slide=path)
    assert not box.events and deck.read_bytes() == before
    box.ws.dirty.clear()

    box.ws.approve = False
    assert "rejected" in box.error("insert_slide", slide=path)
    assert deck.read_bytes() == before
    box.ws.approve = True
    box.ws.before_confirm = lambda: box.ws.open(deck, "user's pending edits", dirty=True)
    assert "unsaved edits" in box.error("insert_slide", slide=path)
    assert deck.read_bytes() == before and box.ws.buffer_text(deck) == "user's pending edits"

    box.ws.before_confirm = None
    box.ws.dirty.clear()
    box.events.clear()
    assert "after abc" in box.ok("insert_slide", slide=path, after="abc")
    text = deck.read_text()
    slug = created.name.removesuffix("-current.tex")
    assert text.index("abc-EN-Hello") < text.index(slug) < text.index("abd-EN-Second")
    applied, = box.of_type(EditApplied)
    assert applied.path == deck and not applied.undoable and (deck, applied.before) in box.ws.changed
    assert ai_review.unreviewed(box.ws.project)[path]["decks"] == ["decks/test.tex"]
    box.events.clear()
    assert "already in test" in box.ok("insert_slide", slide=path, after="missing")
    assert not box.events and deck.read_text() == text


def test_insert_existing_rejects_missing_frozen_non_slide_and_outside_files(box, root):
    (root / "slides/abc-EN-Hello-v1-0-0.tex").write_text("frozen")
    files = set((root / "slides").iterdir())
    deck = root / "decks/test.tex"
    before = deck.read_bytes()
    for path in ("slides/missing-current.tex", "slides/abc-EN-Hello-v1-0-0.tex", "decks/test.tex", "../outside.tex"):
        box.error("insert_slide", slide=path)
        assert set((root / "slides").iterdir()) == files and deck.read_bytes() == before


def test_add_bib_entry_writes_a_sorted_entry_with_a_suggested_key(box, root):
    box.box.ctx.mode = EDIT_AUTO
    out = box.ok("add_bib_entry", kind="article", fields={
        "author": "Markowitz, Harry", "title": "Portfolio Selection", "year": "1952",
        "journaltitle": "Journal of Finance & Co"})
    assert "markowitz1952" in out and "\\fullcite{markowitz1952}" in out
    bib = (root / "SlideMage.bib").read_text()
    assert bib.index("markowitz1952") < bib.index("old2000")
    assert "Journal of Finance \\& Co" in bib
    assert box.ws.changed[-1][0] == root / "SlideMage.bib"


def test_add_bib_entry_rejects_duplicate_keys_and_protects_unsaved_edits(box, root):
    bib = root / "SlideMage.bib"
    fields = {"author": "A, B", "title": "T", "year": "2000", "publisher": "P"}
    assert "already exists" in box.error("add_bib_entry", kind="book", key="old2000", fields=fields)
    assert not box.ws.asked

    before = bib.read_bytes()
    box.ws.dirty.add(bib)
    assert "unsaved edits" in box.error("add_bib_entry", kind="book", fields=fields)
    box.ws.dirty.clear()
    box.ws.before_confirm = lambda: box.ws.dirty.add(bib)
    assert "meanwhile" in box.error("add_bib_entry", kind="book", key="new2001", fields=fields)
    assert bib.read_bytes() == before


def test_add_bib_entry_validates(box):
    assert "needs: year, journaltitle" in box.error("add_bib_entry", kind="article", fields={
        "author": "A, B", "title": "T"})
    assert "no field(s) color" in box.error("add_bib_entry", kind="book", fields={
        "author": "A, B", "title": "T", "year": "2000", "publisher": "P", "color": "red"})
    assert "lowercase surname" in box.error("add_bib_entry", kind="book", key="Bad Key", fields={
        "author": "A, B", "title": "T", "year": "2000", "publisher": "P"})


def test_make_qr_code_writes_media_and_returns_the_call(box, root):
    out = box.ok("make_qr_code", kind="url", fields={"url": "example.org/course"}, caption="QR 1")
    assert (root / "media" / "qr-1.pdf").is_file() and box.ws.changed[-1][0] == root / "media" / "qr-1.pdf"
    assert out.endswith("\\SMQRCode[0.60\\textheight]{media/qr-1.pdf}{QR 1}[https://example.org/course]")
    assert "Lecture hall ≥" in out
    out = box.ok("make_qr_code", kind="event", fields={"title": "Exam", "start": "2026-12-14 10:00"}, height=0.8,
                 caption="auto")
    assert out.endswith("\\SMQRCode[0.80\\textheight]{media/qr-exam-2026-12-14-10-00.pdf}{Exam, 2026-12-14 10:00}")
    out = box.ok("make_qr_code", kind="url", fields={"url": "b.org"}, corner="se")
    assert out.endswith("\\cornerfigure[corner=se]{\\SMQRCode[0.60\\textheight]{media/qr-b-org.pdf}{}[https://b.org]}")


def test_make_qr_code_validates(box):
    assert "no field(s) color" in box.error("make_qr_code", kind="url", fields={"url": "a.org", "color": "red"})
    assert "not an email address" in box.error("make_qr_code", kind="email", fields={"to": "nobody"})
    assert "Enter the start" in box.error("make_qr_code", kind="event", fields={"title": "x"})
    assert "share of" in box.error("make_qr_code", kind="url", fields={"url": "a.org"}, height=2)


def test_compile_deck_reports_per_pdf_and_the_latex_errors(box):
    assert box.ok("compile_deck") == "test: ok"
    assert box.ws.compiled == [("test", "instructor")]
    box.ws.compile_results = {"test-after-course": False}
    box.ws.compile_log = ["slides/abc-EN-Hello-current.tex:7: Undefined control sequence.", "noise"]
    out = box.ok("compile_deck", view="after-course")
    assert box.ws.compiled[-1] == ("test", "after-course")
    assert "test-after-course: FAILED" in out and "slides/abc-EN-Hello-current.tex:7: Undefined control sequence." in out
    box.ws.compile_log = ["some", "plain", "log"]
    assert "Log (end):\nsome\nplain\nlog" in box.ok("compile_deck")


def fake_render(monkeypatch, root, fail=None, *, texts=None):
    """Compile without LaTeX; exercise real preview rasterization."""
    seen = []

    def render(target, text, view, language, **kwargs):
        seen.append((target.id_slug, target.frame_number, view, language))
        if texts is not None:
            texts.append(text)
        if fail:
            raise RuntimeError(fail)
        # one folder per render, as a real render has (the service deletes it afterwards; views render at once)
        folder = root / f"slidemage_preview_{target.bare_id}_{view}_{len(seen)}"
        folder.mkdir(exist_ok=True)
        pdf = folder / "x.pdf"
        with pymupdf.open() as doc:
            doc.new_page(width=320, height=180)
            doc.save(pdf)
        return pdf

    monkeypatch.setattr(preview_target, "render_text", render)
    return seen


def test_refresh_preview_uses_explicit_or_all_views_and_the_slides_language(box, root, monkeypatch):
    box.ws._context = replace(box.ws.context(), view="after-course", language="DE")
    seen = fake_render(monkeypatch, root)
    assert "abc: instructor, EN: rendered; cached for instructor." in box.ok("refresh_preview", view="instructor")
    assert seen == [("abc-EN-Hello", 1, "instructor", "EN")]
    assert "abd: instructor, EN: rendered" in box.ok("refresh_preview", view="instructor", slide="abd")
    assert seen[-1][:2] == ("abd-EN-Second", 2)

    out = box.ok("refresh_preview", slide=SLIDE)
    views = {"instructor", "during-course", "after-course"}
    assert all(f"{view}, EN" in out for view in views)
    assert {row[2] for row in seen[-3:]} == views and box.ws.context().view == "after-course"


def test_refresh_preview_reports_the_first_latex_error_and_other_problems(box, root, monkeypatch):
    fake_render(monkeypatch, root, fail="Render failed for abc-EN-Hello:\nnoise\n! Undefined control sequence.\nmore")
    assert "! Undefined control sequence." in box.error("refresh_preview", view="instructor")
    fake_render(monkeypatch, root, fail="Render failed")
    assert "Render failed" in box.error("refresh_preview", slide="abd")
    assert "not a slide file" in box.error("refresh_preview", slide="SlideMage.bib")
    assert "frozen version" in box.error("refresh_preview", slide="slides/abc-EN-Hello-v1-0-0.tex")


def test_refresh_deck_previews_says_why_it_could_not_run_or_was_stopped(box):
    box.ws.refresh_result = RuntimeError("SlideMage is busy with another compile run.")
    assert box.error("refresh_deck_previews") == "SlideMage is busy with another compile run."
    box.ws.refresh_result = batch_render.DeckResult()
    box.box.ctx.cancel.request_stop()
    assert "stopped by the user" in box.error("refresh_deck_previews")


def test_refresh_deck_previews_is_stopped_after_its_deadline(box, monkeypatch):
    monkeypatch.setattr(previews_tools, "DECK_TIMEOUT_S", 0.3)

    def slow(deck, cancel):                                  # a compile that only the deadline ends
        end = time.monotonic() + 5
        while not cancel.is_set() and time.monotonic() < end:
            time.sleep(0.02)
        return batch_render.DeckResult()

    monkeypatch.setattr(box.ws, "refresh_deck_previews", slow)
    assert "longer than" in box.error("refresh_deck_previews")


def test_read_guide_returns_frame_examples_and_project_translation_style(box, root):
    assert "\\begin{sideimageframe}{Title}{media/your-image.pdf}" in box.ok("read_guide", topic="frames")
    assert "must be one of" in box.error("read_guide", topic="everything")
    assert "formally in every language (German: Sie)" in box.ok("read_guide", topic="translation")
    (root / ".slidemage" / "glossary.md").write_text("| EN | DE |\n|---|---|\n| slide | Folie |\n", encoding="utf-8")
    translation_style.set_address(box.ws.project, "informal")
    guide = box.ok("read_guide", topic="translation")
    assert "informally in every language (German: du)" in guide and "| slide | Folie |" in guide


def test_context_shows_unsaved_slide_text_or_the_deck_outline(box, root):
    box.ws.open(root / SLIDE, LF + "\\begin{itemize}\n", dirty=True)
    text = agent_context.build_context(box.ws, agent_context.SCOPE_SLIDE)
    assert "Open deck: test (decks/test.tex)" in text and "Viewed as: instructor; editing language: EN" in text
    assert f"The editor shows: {SLIDE} (unsaved edits)" in text and "Lint errors in it:\n  line" in text
    assert "Current text of abc-EN-Hello-current.tex (with unsaved edits):" in text and "\\begin{itemize}\n```" in text
    assert "\r" not in text

    text = agent_context.build_context(box.ws, agent_context.SCOPE_DECK)
    assert "the whole deck" in text and "§ Intro\n  1. abc | Hello\n§ Main\n  2. abd | Second" in text
    assert "Current text of" not in text

    text = agent_context.build_context(Workspace(box.ws.project), agent_context.SCOPE_SLIDE)
    assert "Open deck: none" in text and "editor shows" not in text


def test_add_slide_translation_of_links_both_ways_and_copies_the_body(box, root):
    box.box.ctx.mode = EDIT_AUTO
    out = box.ok("add_slide", slug="Hallo", title="Hallo", language="DE", translation_of="abc", after="abc")
    created = next((root / "slides").glob("*-DE-Hallo-current.tex"))
    body = created.read_text()
    assert "linked" in out and "First point" in body
    assert "%% Translation of: abc-EN-Hello" in body
    deck = (root / "decks/test.tex").read_text()
    assert deck.index("abc-EN-Hello") < deck.index(created.name.removesuffix("-current.tex")) < deck.index("abd-EN-Second")
    assert f"%% DE translation: {created.name[:-12]}" in (root / "slides" / "abc-EN-Hello-current.tex").read_text()
    assert "already EN" in box.error("add_slide", slug="Same", title="T", language="EN", translation_of="abc")
    entries = ai_review.unreviewed(box.ws.project)
    assert set(entries) == {SLIDE, created.relative_to(root).as_posix()}
    entry = entries[created.relative_to(root).as_posix()]
    assert entry["kind"] == "translation" and entry["decks"] == ["decks/test.tex"]


def make_pdf(path, pages=3):
    """A small PDF written by hand (MuPDF repairs the missing xref), so no MuPDF runs in the test process."""
    objects = ["<< /Type /Catalog /Pages 2 0 R >>",
               f"<< /Type /Pages /Kids [{' '.join(f'{4 + 2 * n} 0 R' for n in range(pages))}] /Count {pages} >>",
               "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    for n in range(1, pages + 1):
        stream = f"BT /F1 12 Tf 72 200 Td (Findings of page {n}) Tj ET"
        objects += [f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 300] /Contents {5 + 2 * (n - 1)} 0 R "
                    f"/Resources << /Font << /F1 3 0 R >> >> >>",
                    f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream"]
    body = "%PDF-1.4\n" + "".join(f"{i} 0 obj\n{o}\nendobj\n" for i, o in enumerate(objects, 1))
    path.write_bytes((body + "trailer\n<< /Root 1 0 R /Size 99 >>\n%%EOF\n").encode())


def test_read_file_pages_pdfs_and_returns_images_without_using_mupdf_in_process(box, root, monkeypatch):
    make_pdf(root / "paper.pdf", pages=6)
    (root / "fig.png").write_bytes(base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="))
    (root / "fig.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="40" height="20"><rect width="40" height="20"/></svg>')

    # MuPDF can crash when it runs in the app's worker threads.
    def refuse(*args, **kwargs):
        pytest.fail("MuPDF used in the app process")

    monkeypatch.setattr(pymupdf, "open", refuse)
    text = box.ok("read_file", path="paper.pdf")
    assert "(6 pages)" in text and "--- page 1 ---\nFindings of page 1" in text
    text = box.ok("read_file", path="paper.pdf", start_page=2, max_pages=1)
    assert "Findings of page 2" in text and "page 1 ---" not in text and "start_page=3" in text
    assert "There is no page 9" in box.ok("read_file", path="paper.pdf", start_page=9)

    result = box.run("read_file", path="paper.pdf", pages_as_images=True, start_page=2)
    assert not result.is_error and len(result.images) == 4 and "pages 2-5" in result.text
    assert result.images[0].startswith(b"\x89PNG")
    for name in ("fig.png", "fig.svg"):
        result = box.run("read_file", path=name)
        assert not result.is_error and result.images[0].startswith(b"\x89PNG"), result.text


def test_read_file_refuses_broken_pdfs_and_pdfs_outside(box, root, tmp_path):
    (root / "bad.pdf").write_bytes(b"not a pdf")
    assert "not a readable PDF" in box.error("read_file", path="bad.pdf")
    (tmp_path / "outside.pdf").write_bytes(b"outside")
    assert "outside the project folder" in box.error("read_file", path=str(tmp_path / "outside.pdf"))


def test_refresh_preview_hidden_instructor_slide_does_not_compile(box, monkeypatch):
    deck_path = box.ws.context().deck.path
    text = deck_path.read_text()
    assert r'\slide{abc-EN-Hello}' in text
    deck_path.write_text(text.replace(r'\slide{abc-EN-Hello}', r'\conditionalslide[during-course]{abc-EN-Hello}'))
    monkeypatch.setattr(preview_target, 'render', lambda *a, **k: pytest.fail('hidden slide compiled'))
    assert 'abc: instructor, EN: hidden; no preview rendered, no image.' in box.ok('refresh_preview', view='instructor')


def test_refresh_preview_headless_rejects_a_source_edit_during_render(box, root, monkeypatch):
    fake_render(monkeypatch, root)
    render = preview_target.render_text

    def changed(target, *args, **kwargs):
        pdf = render(target, *args, **kwargs)
        target.source_path.write_text('new saved source')
        return pdf

    monkeypatch.setattr(preview_target, 'render_text', changed)
    result = box.ok('refresh_preview')
    assert 'rendered' in result and 'superseded' in result and 'displayed' not in result


def test_slide_scope_guards_writes_to_other_files(box, root):
    box.box.ctx.scope, box.box.ctx.focus_slide = "slide", root / SLIDE
    other = "slides/abd-EN-Second-current.tex"
    edit = dict(old_text="First", new_text="Changed")
    assert "switch_to_deck_mode" in box.error("edit_file", path=other, **edit)
    assert "switch_to_deck_mode" in box.error("modify_slide", slide=other, edits=[{"old": "First", "new": "Changed"}])
    assert "switch_to_deck_mode" in box.error("write_file", path="decks/new.tex", content="x")
    assert "switch_to_deck_mode" in box.error("add_slide", slug="New", title="New", add_to_deck=False)
    assert "switch_to_deck_mode" in box.error("create_slide", title="New", slug="New", body="x", deck="test")
    assert not box.of_type(EditProposed)
    assert "Changed" in box.ok("edit_file", path=SLIDE, **edit)


def test_write_file_allows_focused_new_file_in_slide_scope(box, root):
    path = root / "slides" / "drafts" / "new.tex"
    box.box.ctx.scope, box.box.ctx.focus_slide = "slide", path
    assert "Created" in box.ok("write_file", path="slides/drafts/new.tex", content="x")


def test_modify_slide_checks_resolved_language_partner(box, root, monkeypatch):
    box.box.ctx.scope, box.box.ctx.focus_slide = "slide", root / SLIDE
    monkeypatch.setattr(slidemage_tools.slide_language.TranslationLinks, "find", lambda *args: "abd-EN-Second")
    assert "abd-EN-Second-current.tex" in box.error(
        "modify_slide", slide="abc", edits=[{"old": "First", "new": "Changed"}])
    assert not box.of_type(EditProposed)
