# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The agent's tools on a throwaway project (never the real example/): path confinement, reading,
finding, the edit rules (buffer or disk, protected parts, frozen versions, ask / auto), the
SlideMage tools over their backends, and the context block."""
from __future__ import annotations

import os
import time

import pytest
import pymupdf
from agent_fakes import FakeWorkspace, call
from conftest import SLIDE_TEXT

from slidemage import ai_review, compiler, preview_target, slide_snapshot, update_all_previews
from slidemage.ai import agent_context
from slidemage.ai.agent_types import (
    EDIT_ASK,
    EDIT_AUTO,
    EditApplied,
    EditProposed,
    EditRejected,
)
from slidemage.ai.tools import build_toolbox, focus, undo_edit
from slidemage.ai.tools.base import ToolError, tool
from slidemage.ai.tools import files as files_module
from slidemage.ai.tools import previews as previews_tools
from slidemage.ai.tools import slidemage as slidemage_tools
from slidemage.project import ProjectContext
from slidemage.ai.workspace import Workspace, WorkspaceContext
from slidemage.deck_scan import scan_decks


@pytest.fixture
def ctx(root):
    return ProjectContext.at(root)

SLIDE = "slides/abc-EN-Hello-current.tex"
LF = SLIDE_TEXT.replace("\r\n", "\n")


def plus(text):
    return text.replace("\\setSlideVersion{1-0-0}", "\\setSlideVersion{1-0-0+}")


class Box:
    """A toolbox on the throwaway project with the events it emitted."""

    def __init__(self, root, mode=EDIT_ASK, approve=True, deck=True):
        deck_ = next((d for d in scan_decks(ProjectContext.at(root)) if d.name == "test"), None) if deck else None
        self.ws = FakeWorkspace(root, WorkspaceContext(deck=deck_, slide_id="abc", path=root / SLIDE), approve)
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


def test_failed_calls_log_tool_end(box, monkeypatch):
    events = []
    monkeypatch.setattr("slidemage.timing.event", lambda root, name, **fields: events.append((name, fields)))

    @tool("fail", "Fail", {})
    def fail(ctx, args):
        raise ToolError("failed")

    box.box._tools["fail"] = fail
    assert box.run("fail").is_error
    assert events == [("tool_start", {"tool": "fail"}), ("tool_end", {"tool": "fail", "error": True})]
    events.clear()
    assert box.run("unknown").is_error
    assert events == []


def test_calls_get_separate_contexts_and_current_mode(box):
    contexts = []

    @tool("capture", "Capture context", {})
    def capture(ctx, args):
        contexts.append(ctx)
        return "ok"

    box.box._tools["capture"] = capture
    first, second = call("capture"), call("capture")
    box.box.execute(first)
    box.box.ctx.mode = EDIT_AUTO
    box.box.execute(second)
    assert [(ctx.call_id, ctx.mode) for ctx in contexts] == [(first.id, EDIT_ASK), (second.id, EDIT_AUTO)]
    assert contexts[0] is not contexts[1] and box.box.ctx.call_id == ""


# -- confinement ------------------------------------------------------------------------------------

def test_paths_outside_the_project_are_refused(box, tmp_path):
    (tmp_path / "secret.txt").write_text("outside")
    for path in ("../secret.txt", str(tmp_path / "secret.txt"), "slides/../../secret.txt"):
        assert "outside the project folder" in box.error("read_file", path=path)


def test_a_symlink_leading_out_is_refused(box, tmp_path):
    (tmp_path / "secret.txt").write_text("outside")
    try:
        os.symlink(tmp_path / "secret.txt", box.root / "link.txt")
    except OSError:
        pytest.skip("no symlinks here")
    assert "outside the project folder" in box.error("read_file", path="link.txt")
    assert "outside the project folder" in box.error("edit_file", path="link.txt", old_text="o", new_text="x")


def test_hidden_folders_do_not_exist_for_the_model(box):
    (box.root / "pdf").mkdir()
    (box.root / "pdf" / "deck.txt").write_text("x")
    (box.root / ".build").mkdir()
    (box.root / ".build" / "log.txt").write_text("x")
    for path in (".slidemage/app_settings.json", ".build/log.txt", "pdf/deck.txt"):
        assert "off limits" in box.error("read_file", path=path)
        assert "off limits" in box.error("write_file", path=path.replace("txt", "tex"), content="x")
    assert "sk-secret" not in box.ok("find_files", pattern="**/*")
    assert "Nothing found" in box.ok("search", query="sk-secret")
    assert ".slidemage" not in box.ok("find_files", pattern="*.json")


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
    ws = FakeWorkspace(box.root, WorkspaceContext(path=box.root / ".slidemage" / "app_settings.json"))
    toolbox = build_toolbox(ws, lambda event: None, compiler.CancelToken(), tools=[focus.get_focus])
    result = toolbox.execute(call("get_focus"))
    assert not result.is_error and "app_settings" not in result.text and "may see" in result.text


# -- reading and finding ----------------------------------------------------------------------------

def test_read_file_numbers_lines_normalises_line_ends_and_pages(box):
    text = box.ok("read_file", path=SLIDE)
    assert text.startswith(f"{SLIDE} (12 lines; file)\n1\t%% Included in decks: test\n")
    assert "\r" not in text and "6\t\\begin{standardframe}{Hello}" in text
    part = box.ok("read_file", path=SLIDE, start_line=7, max_lines=2)
    assert "7\t\t\\begin{itemize}" in part and "read on with start_line=9" in part
    assert "There is no line 99" in box.ok("read_file", path=SLIDE, start_line=99)
    box.ws.open(box.root / SLIDE, "buffer text\n", dirty=True)
    assert "1\tbuffer text" in box.ok("read_file", path=SLIDE)


def test_read_file_refuses_folders_missing_and_binary_files(box):
    (box.root / "media").mkdir()
    (box.root / "media" / "pic.bin").write_bytes(b"\x89PNG\0\0data")
    assert "is a folder" in box.error("read_file", path="slides")
    assert "does not exist" in box.error("read_file", path="slides/nope.tex")
    assert "not a text file" in box.error("read_file", path="media/pic.bin")


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


# -- argument checks ----------------------------------------------------------------------------------

def test_bad_arguments_and_unknown_tools_become_error_results(box):
    assert "Missing required argument 'path'" in box.error("read_file")
    assert "must be of type integer" in box.error("read_file", path=SLIDE, start_line="1")
    assert "Unknown argument" in box.error("read_file", path=SLIDE, colour="red")
    assert "no tool 'rm'" in box.error("rm", path="x")
    assert "must be one of" in box.error("add_slide", slug="A", title="T", frame="bogus")


# -- editing: the rules ---------------------------------------------------------------------------

@pytest.mark.parametrize("old, new", [
    ("First point", "1st point"),
    ("% A note on this slide", "% A better note"),
    ("{Hello}", "{Hello again}"),
], ids=["body", "next-to-header", "next-to-version"])
def test_edit_on_disk_saves_with_backup_keeps_crlf_and_reports(box, root, old, new):
    box.box.ctx.mode = EDIT_AUTO
    out = box.ok("edit_file", path=SLIDE, old_text=old, new_text=new)
    assert "saved it" in out
    raw = (root / SLIDE).read_bytes().decode()
    # A slide's current file gets the "+": changed since v1.0.0, which is frozen first.
    assert raw == plus(SLIDE_TEXT.replace(old, new)) and "\r\n" in raw
    assert (root / "slides" / "abc-EN-Hello-v1-0-0.tex").read_bytes().decode() == SLIDE_TEXT
    backups = list((root / "slides" / ".backups" / "abc-EN-Hello-current.tex").glob("*.tex"))
    assert len(backups) == 1 and backups[0].read_bytes().decode() == SLIDE_TEXT
    assert box.ws.changed == [(root / SLIDE, LF)]
    (proposed,), (applied,) = box.of_type(EditProposed), box.of_type(EditApplied)
    assert (applied.before, applied.after, applied.via_buffer) == (LF, LF.replace(old, new), False)
    assert proposed.after == applied.after and applied.call_id == proposed.call_id
    assert not box.ws.asked                                  # auto: nobody was asked


def test_edit_in_an_open_buffer_leaves_the_disk_alone(box, root):
    box.box.ctx.mode = EDIT_AUTO
    box.ws.open(root / SLIDE, LF.replace("First", "Unsaved"), dirty=True)     # the user typed already
    out = box.ok("edit_file", path=SLIDE, old_text="Second point", new_text="2nd point")
    assert "open editor" in out and "not saved" in out
    assert box.ws.buffers[root / SLIDE] == LF.replace("First", "Unsaved").replace("Second", "2nd")
    assert (root / SLIDE).read_bytes().decode() == SLIDE_TEXT and not box.ws.changed
    assert box.of_type(EditApplied)[0].via_buffer is True


def test_a_buffer_that_changed_while_the_edit_waited_is_not_overwritten(box, root):
    path = root / SLIDE
    box.ws.open(path, LF)
    box.ws.before_confirm = lambda: box.ws.buffers.__setitem__(path, LF + "typed meanwhile\n")
    assert "changed while the edit waited" in box.error("edit_file", path=SLIDE, old_text="First", new_text="1st")
    assert box.ws.buffers[path].endswith("typed meanwhile\n") and not box.of_type(EditApplied)


def test_a_read_only_buffer_refuses(box, root):
    box.ws.open(root / SLIDE, LF)
    box.ws.read_only.add(root / SLIDE)
    assert "read-only" in box.error("edit_file", path=SLIDE, old_text="First", new_text="1st")


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
    ("%% Included in decks: test", "%% Included in decks: test, other"),      # the header comment
    ("%%\n\n% A note", "%%\n%\n\n% A note"),
    ("\\setSlideVersion{1-0-0}", "\\setSlideVersion{1-1-0}"),
    ("\\setSlideVersion{1-0-0}\n", ""),
])
def test_protected_parts_of_a_slide_are_refused(box, root, old, new):
    box.box.ctx.mode = EDIT_AUTO
    assert "protected part" in box.error("edit_file", path=SLIDE, old_text=old, new_text=new)
    assert (root / SLIDE).read_bytes().decode() == SLIDE_TEXT and not box.of_type(EditProposed)


def test_overlay_blocks_of_a_slide_can_be_edited(box, root):      # (2026-10-30, direct request, after slide tjn)
    box.box.ctx.mode = EDIT_AUTO
    box.ok("edit_file", path=SLIDE, old_text="\\hbox{overlay}", new_text="\\hbox{changed}")
    assert "\\hbox{changed}" in (root / SLIDE).read_bytes().decode()


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

    box.ws.approve = True                                                 # the user changes their mind
    box.ok("edit_file", path=SLIDE, old_text="First", new_text="1st")
    assert "1st point" in (root / SLIDE).read_text()


def test_write_file_creates_new_text_files_only(box, root):
    box.box.ctx.mode = EDIT_AUTO
    box.ok("write_file", path="notes/todo.md", content="- one\r\n- two\n")
    assert (root / "notes" / "todo.md").read_bytes() == b"- one\n- two\n"
    assert box.ws.changed[-1] == (root / "notes" / "todo.md", None)
    assert box.of_type(EditApplied)[-1].undoable is False
    assert "exists already" in box.error("write_file", path="notes/todo.md", content="x")
    assert "add_slide" in box.error("write_file", path="slides/new-EN-Slide-current.tex", content="x")
    assert "outside" in box.error("write_file", path="../x.md", content="x")


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
    assert (root / SLIDE).read_bytes().decode() == SLIDE_TEXT       # exactly: 1.0.0, frozen by the edit

    box.ok("edit_file", path=SLIDE, old_text="First", new_text="1st")
    applied = box.of_type(EditApplied)[1]
    (root / SLIDE).write_bytes(b"changed since")
    assert "changed since" in undo_edit(box.ws, applied)
    assert (root / SLIDE).read_bytes() == b"changed since"


# -- the SlideMage tools -------------------------------------------------------------------------

def test_list_slides_shows_the_open_decks_slides(box):
    out = box.ok("list_slides")
    assert out.splitlines()[0].startswith("Deck test (decks/test.tex), viewed as instructor, EN: 2 slides.")
    assert "§ Intro\n  1. abc | Hello | slides/abc-EN-Hello-current.tex | \\slide" in out
    assert "§ Main\n  2. abd | Second | slides/abd-EN-Second-current.tex" in out
    assert "§ Main" not in box.ok("list_slides", section="intro")
    assert "abd" not in box.ok("list_slides", contains="hello")
    assert "No slide matches" in box.ok("list_slides", contains="zzz")
    assert "There is no deck 'nope'. Decks: test" in box.error("list_slides", deck="nope")


def test_list_slides_cuts_at_the_limit_without_an_empty_heading_and_says_so_only_when_it_cut(box, monkeypatch):
    monkeypatch.setattr(slidemage_tools, "LIST_LIMIT", 1)
    out = box.ok("list_slides")
    assert "abc" in out and "abd" not in out and "§ Main" not in out and "[Only the first 1;" in out
    monkeypatch.setattr(slidemage_tools, "LIST_LIMIT", 2)
    out = box.ok("list_slides")
    assert "abc" in out and "abd" in out and "[Only the first" not in out


def test_list_slides_without_an_open_deck_names_the_decks(root):
    assert "No deck is open. Decks: test" in Box(root, deck=False).error("list_slides")


def test_lint_checks_the_buffer_when_the_file_is_open(box, root):
    assert "no problems found" in box.ok("lint", path="abc")
    box.ws.open(root / SLIDE, LF + "\\begin{itemize}\n", dirty=True)
    out = box.ok("lint")                                                 # default: the file in focus
    assert "error(s)" in out and "[error]" in out
    assert "Only .tex" in box.error("lint", path="SlideMage.bib")


def test_render_preview_returns_the_image_of_the_buffer(box, root, monkeypatch):
    seen = {}

    def fake_render(target, text, view, language, **kwargs):
        seen.update(target=target, text=text, view=view, language=language, **kwargs)
        return root / "x.pdf"

    monkeypatch.setattr(preview_target, "render_text", fake_render)
    monkeypatch.setattr(slide_snapshot, "prepare_preview_images",
                        lambda *a: ((b"\x89PNG-image", b"\x89PNG-image"), ()))
    box.ws.open(root / SLIDE, LF + "% unsaved\n")
    result = box.run("render_preview")
    assert not result.is_error and result.images == [b"\x89PNG-image"]
    assert seen["text"].endswith("% unsaved\n") and seen["view"] == "instructor" and seen["language"] == "EN"
    assert seen["target"].id_slug == "abc-EN-Hello" and seen["target"].frame_number == 1     # as the deck calls it
    assert box.run("render_preview", slide="abd").images        # another slide, from disk

    def failing(*args, **kwargs):
        raise RuntimeError("! Undefined control sequence.")

    monkeypatch.setattr(preview_target, "render_text", failing)
    assert "Undefined control sequence" in box.error("render_preview")
    assert "not a slide" in box.error("render_preview", slide="SlideMage.bib")


@pytest.mark.parametrize("slug, title, frame, language, after", [
    ("Capital-Budgeting", "Capital budgeting", "standardframe", "EN", "abc"),
    ("Quote", "A quote", "quoteframe", "DE", None),
], ids=["insert-after-slide", "append-german-quote"])
def test_add_slide_creates_the_file_and_the_deck_call(box, root, slug, title, frame, language, after):
    box.box.ctx.mode = EDIT_AUTO
    out = box.ok("add_slide", slug=slug, title=title, frame=frame, language=language, **({"after": after} if after else {}))
    created = next((root / "slides").glob(f"*-{language}-{slug}-current.tex"))
    assert created.name in out and f"{{{title}}}" in created.read_text()
    deck_lines = (root / "decks" / "test.tex").read_text().splitlines()
    calls = [line for line in deck_lines if line.startswith("\\slide")]
    if after:
        assert "after abc in test" in out
        assert calls == ["\\slide{abc-EN-Hello}", f"\\slide{{{created.name[:-12]}}}", "\\slide{abd-EN-Second}"]
    else:
        assert "\\quoteframe" in created.read_text()
        assert deck_lines[-2] == f"\\slide{{{created.name[:-12]}}}"
    assert {path for path, _ in box.ws.changed} == {created, root / "decks" / "test.tex"}
    applied = box.of_type(EditApplied)[0]
    assert applied.path == created and applied.before == "" and applied.undoable is False


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


def test_insert_existing_slide_requires_consent_and_rechecks_dirty_deck(box, root):
    box.ok("add_slide", slug="Existing", title="T", add_to_deck=False)
    created, = (root / "slides").glob("*-EN-Existing-current.tex")
    path = created.relative_to(root).as_posix()
    deck = root / "decks/test.tex"
    before = deck.read_bytes()
    box.ws.approve = False
    assert "rejected" in box.error("insert_slide", slide=path)
    assert deck.read_bytes() == before
    box.ws.approve = True
    box.ws.before_confirm = lambda: box.ws.open(deck, "user's pending edits", dirty=True)
    assert "unsaved edits" in box.error("insert_slide", slide=path)
    assert deck.read_bytes() == before and box.ws.buffer_text(deck) == "user's pending edits"


@pytest.mark.parametrize("path", ["slides/missing-current.tex", "slides/abc-EN-Hello-v1-0-0.tex", "decks/test.tex", "../outside.tex"])
def test_insert_existing_rejects_missing_frozen_non_slide_and_outside_files(box, root, path):
    (root / "slides/abc-EN-Hello-v1-0-0.tex").write_text("frozen")
    files = set((root / "slides").iterdir())
    before = (root / "decks/test.tex").read_bytes()
    assert box.run("insert_slide", slide=path).is_error
    assert set((root / "slides").iterdir()) == files
    assert (root / "decks/test.tex").read_bytes() == before



def test_add_bib_entry_writes_a_sorted_entry_with_a_suggested_key(box, root):
    box.box.ctx.mode = EDIT_AUTO
    out = box.ok("add_bib_entry", kind="article", fields={
        "author": "Markowitz, Harry", "title": "Portfolio Selection", "year": "1952",
        "journaltitle": "Journal of Finance & Co"})
    assert "markowitz1952" in out and "\\fullcite{markowitz1952}" in out
    bib = (root / "SlideMage.bib").read_text()
    assert bib.index("markowitz1952") < bib.index("old2000")             # sorted by key
    assert "Journal of Finance \\& Co" in bib
    assert box.ws.changed[-1][0] == root / "SlideMage.bib"
    assert "already exists" in box.error("add_bib_entry", kind="book", key="old2000", fields={
        "author": "A, B", "title": "T", "year": "2000", "publisher": "P"})


def test_add_bib_entry_refuses_a_taken_key_before_asking_and_a_buffer_that_got_edits_while_asking(box, root):
    taken = dict(kind="book", key="old2000", fields={"author": "A, B", "title": "T", "year": "2000", "publisher": "P"})
    assert "already exists" in box.error("add_bib_entry", **taken) and not box.ws.asked          # ask mode: nobody was asked
    bib = root / "SlideMage.bib"
    box.ws.before_confirm = lambda: box.ws.dirty.add(bib)
    assert "meanwhile" in box.error("add_bib_entry", kind="book", key="new2001", fields={
        "author": "A, B", "title": "T", "year": "2001", "publisher": "P"})
    assert "new2001" not in bib.read_text()


def test_add_bib_entry_validates(box):
    assert "needs: year, journaltitle" in box.error("add_bib_entry", kind="article", fields={
        "author": "A, B", "title": "T"})
    assert "no field(s) colour" in box.error("add_bib_entry", kind="book", fields={
        "author": "A, B", "title": "T", "year": "2000", "publisher": "P", "colour": "red"})
    assert "lowercase surname" in box.error("add_bib_entry", kind="book", key="Bad Key", fields={
        "author": "A, B", "title": "T", "year": "2000", "publisher": "P"})
    box.ws.dirty.add(box.root / "SlideMage.bib")
    assert "unsaved edits" in box.error("add_bib_entry", kind="book", fields={
        "author": "A, B", "title": "T", "year": "2000", "publisher": "P"})


def test_make_qr_code_writes_media_and_returns_the_call(box, root):
    out = box.ok("make_qr_code", kind="url", fields={"url": "uni-graz.at/course"}, caption="QR 1")
    assert (root / "media" / "qr-1.pdf").is_file() and box.ws.changed[-1][0] == root / "media" / "qr-1.pdf"
    assert out.endswith("\\SMQRCode[0.60\\textheight]{media/qr-1.pdf}{QR 1}[https://uni-graz.at/course]")
    assert "Lecture hall ≥" in out
    out = box.ok("make_qr_code", kind="event", fields={"title": "Exam", "start": "2026-12-14 10:00"}, height=0.8,
                 caption="auto")
    assert out.endswith("\\SMQRCode[0.80\\textheight]{media/qr-exam-2026-12-14-10-00.pdf}{Exam, 2026-12-14 10:00}")
    assert box.ok("make_qr_code", kind="url", fields={"url": "a.org"}).endswith("{}[https://a.org]")   # no caption
    out = box.ok("make_qr_code", kind="url", fields={"url": "b.org"}, corner="se")
    assert out.endswith("\\cornerfigure[corner=se]{\\SMQRCode[0.60\\textheight]{media/qr-b-org.pdf}{}[https://b.org]}")


def test_make_qr_code_validates(box):
    assert "no field(s) colour" in box.error("make_qr_code", kind="url", fields={"url": "a.org", "colour": "red"})
    assert "not an email address" in box.error("make_qr_code", kind="email", fields={"to": "nobody"})
    assert "Enter the start" in box.error("make_qr_code", kind="event", fields={"title": "x"})
    assert "share of" in box.error("make_qr_code", kind="url", fields={"url": "a.org"}, height=2)


def test_compile_deck_reports_per_pdf_and_the_latex_errors(box, root):
    assert box.ok("compile_deck") == "test: ok"
    assert box.ws.compiled == [("test", "instructor")]
    box.ws.compile_results = {"test-after-course": False}
    box.ws.compile_log = ["slides/abc-EN-Hello-current.tex:7: Undefined control sequence.", "noise"]
    out = box.ok("compile_deck", view="after-course")
    assert box.ws.compiled[-1] == ("test", "after-course")
    assert "test-after-course: FAILED" in out and "slides/abc-EN-Hello-current.tex:7: Undefined control sequence." in out
    box.ws.compile_log = ["some", "plain", "log"]
    assert "Log (end):\nsome\nplain\nlog" in box.ok("compile_deck")


def fake_render(monkeypatch, root, fail=None):
    """Compile without LaTeX; exercise real rasterization and snapshot publication."""
    seen = []

    def render(target, text, view, language, **kwargs):
        seen.append((target.id_slug, target.frame_number, view, language, kwargs.get("capture_snapshot", True)))
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


def test_refresh_preview_rerenders_the_focused_slide_and_an_explicit_one(box, root, monkeypatch):
    seen = fake_render(monkeypatch, root)
    assert "abc: instructor, EN: rendered; cached for instructor." in box.ok("refresh_preview", view="instructor")          # the slide in focus
    assert seen == [("abc-EN-Hello", 1, "instructor", "EN", False)]                    # as the open deck calls it
    assert slide_snapshot.snapshot_path(box.ws.project, "abc", slide_snapshot.DEFAULT_TEMPLATE, id_slug="abc-EN-Hello").is_file()
    assert "abd: instructor, EN: rendered" in box.ok("refresh_preview", view="instructor", slide="abd")
    assert seen[-1][:2] == ("abd-EN-Second", 2)
    assert "abc: instructor, EN: rendered" in box.ok("refresh_preview", view="instructor", slide="slides/abc-EN-Hello-current.tex")


def test_refresh_preview_renders_the_instructor_view_whatever_the_user_looks_at(box, root, monkeypatch):
    box.ws._context = WorkspaceContext(deck=box.ws.context().deck, slide_id="abc", path=root / SLIDE,
                                       view="after-course", language="DE")
    seen = fake_render(monkeypatch, root)
    box.ok("refresh_preview", view="instructor")
    assert seen[0][2:4] == ("instructor", "EN")                    # the slide's own language, not the editing one


def test_refresh_preview_reports_the_first_latex_error_and_other_problems(box, root, monkeypatch):
    fake_render(monkeypatch, root, fail="Render failed for abc-EN-Hello:\nnoise\n! Undefined control sequence.\nmore")
    assert "! Undefined control sequence." in box.error("refresh_preview", view="instructor")
    fake_render(monkeypatch, root, fail="Render failed")
    assert "Render failed" in box.error("refresh_preview", slide="abd")
    assert "not a slide file" in box.error("refresh_preview", slide="SlideMage.bib")
    assert "frozen version" in box.error("refresh_preview", slide="slides/abc-EN-Hello-v1-0-0.tex")
    monkeypatch.setattr(slide_snapshot, "publish_preview", lambda *a: (_ for _ in ()).throw(OSError("disk full")))
    fake_render(monkeypatch, root)
    assert "publication failed: disk full" in box.error("refresh_preview", view="instructor")


def test_refresh_deck_previews_reports_counts_and_lists(box, root):
    box.ws.refresh_result = update_all_previews.DeckResult(refreshed=["abc-EN-Hello"], failed=["abd-EN-Second"],
                                                           error="! Undefined control sequence.")
    out = box.ok("refresh_deck_previews")                                       # the open deck
    assert box.ws.refreshed == ["test"]
    assert out == ("test: 1 of 2 slide preview(s) refreshed, 1 failed.\nRefreshed: abc\nFailed: abd\n"
                   "First error: ! Undefined control sequence.")
    box.ws.refresh_result = update_all_previews.DeckResult(refreshed=["abc-EN-Hello", "abd-EN-Second"])
    assert box.ok("refresh_deck_previews", deck="test") == "test: 2 of 2 slide preview(s) refreshed, 0 failed.\nRefreshed: abc, abd"
    box.ws.refresh_result = update_all_previews.DeckResult()
    assert "no slides to refresh" in box.ok("refresh_deck_previews")
    assert "There is no deck 'nope'" in box.error("refresh_deck_previews", deck="nope")
    assert box.ws.refreshed == ["test"] * 3


def test_refresh_deck_previews_says_why_it_could_not_run_or_was_stopped(box):
    box.ws.refresh_result = RuntimeError("SlideMage is busy with another compile run.")
    assert box.error("refresh_deck_previews") == "SlideMage is busy with another compile run."
    box.ws.refresh_result = update_all_previews.DeckResult()
    box.box.ctx.cancel.request_stop()
    assert "stopped by the user" in box.error("refresh_deck_previews")


def test_refresh_deck_previews_is_stopped_after_its_deadline(box, monkeypatch):
    monkeypatch.setattr(previews_tools, "DECK_TIMEOUT_S", 0.3)

    def slow(deck, cancel):                                  # a compile that only the deadline ends
        end = time.monotonic() + 5
        while not cancel.is_set() and time.monotonic() < end:
            time.sleep(0.02)
        return update_all_previews.DeckResult()

    monkeypatch.setattr(box.ws, "refresh_deck_previews", slow)
    assert "longer than" in box.error("refresh_deck_previews")


def test_read_guide_returns_a_frame_example_and_rejects_unknown_topics(box):
    frames = box.ok("read_guide", topic="frames")
    assert "\\begin{sideimageframe}{Title}{media/your-image.pdf}" in frames
    assert "must be one of" in box.error("read_guide", topic="everything")


# -- the context block ----------------------------------------------------------------------------

def test_context_of_a_slide_has_its_unsaved_text_and_lint_errors(root):
    box = Box(root)
    box.ws.open(root / SLIDE, LF + "\\begin{itemize}\n", dirty=True)
    text = agent_context.build_context(box.ws, agent_context.SCOPE_SLIDE)
    assert "Open deck: test (decks/test.tex)" in text and "Viewed as: instructor; editing language: EN" in text
    assert f"The editor shows: {SLIDE} (unsaved edits)" in text
    assert "Lint errors in it:\n  line" in text
    assert "Current text of abc-EN-Hello-current.tex (with unsaved edits):" in text and "\\begin{itemize}\n```" in text
    assert "\r" not in text


def test_context_of_the_whole_deck_lists_the_outline_instead_of_the_text(root):
    text = agent_context.build_context(Box(root).ws, agent_context.SCOPE_DECK)
    assert "the whole deck" in text and "§ Intro\n  1. abc | Hello\n§ Main\n  2. abd | Second" in text
    assert "Current text of" not in text


def test_context_without_a_deck_or_slide(root):
    text = agent_context.build_context(Workspace(ProjectContext.at(root)), agent_context.SCOPE_SLIDE)
    assert "Open deck: none" in text and "editor shows" not in text


def test_add_slide_translation_of_links_both_ways_and_copies_the_body(box, root):
    box.box.ctx.mode = EDIT_AUTO
    out = box.ok("add_slide", slug="Hallo", title="Hallo", language="DE", translation_of="abc", after="abc")
    created = next((root / "slides").glob("*-DE-Hallo-current.tex"))
    assert "linked" in out
    assert "%% Translation of: abc-EN-Hello" in created.read_text()
    assert f"%% DE translation: {created.name[:-12]}" in (root / "slides" / "abc-EN-Hello-current.tex").read_text()
    assert "already EN" in box.error("add_slide", slug="Same", title="T", language="EN", translation_of="abc")


# -- PDFs and images (attachments) ------------------------------------------------------------------

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


def test_read_file_pages_through_a_pdf_as_numbered_text(box, root):
    (root / "sources").mkdir()
    make_pdf(root / "sources" / "paper.pdf")
    text = box.ok("read_file", path="sources/paper.pdf")
    assert "(3 pages)" in text and "--- page 1 ---\nFindings of page 1" in text and "page 3" in text
    text = box.ok("read_file", path="sources/paper.pdf", start_page=2, max_pages=1)
    assert "Findings of page 2" in text and "page 1 ---" not in text and "start_page=3" in text
    assert "There is no page 9" in box.ok("read_file", path="sources/paper.pdf", start_page=9)


def test_read_file_shows_pdf_pages_and_image_files_as_images(box, root):
    make_pdf(root / "paper.pdf", pages=6)
    result = box.run("read_file", path="paper.pdf", pages_as_images=True, start_page=2)
    assert not result.is_error and len(result.images) == 4 and result.images[0].startswith(b"\x89PNG")
    assert "pages 2-5" in result.text
    import base64
    (root / "fig.png").write_bytes(base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="))
    (root / "fig.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg" width="40" height="20"><rect width="40" height="20"/></svg>')
    for name in ("fig.png", "fig.svg"):
        result = box.run("read_file", path=name)
        assert not result.is_error and result.images[0].startswith(b"\x89PNG"), result.text


def test_read_file_refuses_other_binaries_broken_pdfs_and_pdfs_outside(box, root, tmp_path):
    (root / "data.bin").write_bytes(b"\0\1\2" * 100)
    assert "not a text file" in box.error("read_file", path="data.bin")
    (root / "bad.pdf").write_bytes(b"not a pdf")
    assert "not a readable PDF" in box.error("read_file", path="bad.pdf")
    make_pdf(tmp_path / "outside.pdf")
    assert "outside the project folder" in box.error("read_file", path=str(tmp_path / "outside.pdf"))


def test_reading_files_never_runs_mupdf_in_the_app_process(box, root, monkeypatch):
    """MuPDF crashes when used from worker threads, so PDFs and drawings are read by the raster child process."""
    import pymupdf
    make_pdf(root / "paper.pdf")
    (root / "fig.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg" width="40" height="20"><rect width="40" height="20"/></svg>')

    def refuse(*args, **kwargs):
        raise AssertionError("MuPDF used in the app process")

    monkeypatch.setattr(pymupdf, "open", refuse)
    assert "Findings of page 1" in box.ok("read_file", path="paper.pdf")
    assert box.run("read_file", path="paper.pdf", pages_as_images=True).images
    assert box.run("read_file", path="fig.svg").images
    assert "pymupdf" not in open(files_module.__file__).read()


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
    assert not slide_snapshot.snapshot_path(box.ws.project, 'abc', slide_snapshot.DEFAULT_TEMPLATE).exists()


def test_render_preview_default_is_selected_view_and_refresh_default_is_all_views(box, root, monkeypatch):
    from dataclasses import replace
    box.ws._context = replace(box.ws.context(), view='during-course')
    seen = fake_render(monkeypatch, root)
    box.ws.open(root / SLIDE, LF + '% draft\n')
    assert box.run('render_preview').images
    assert seen[-1][2] == 'during-course'
    assert not slide_snapshot.snapshot_path(box.ws.project, 'abc', slide_snapshot.DEFAULT_TEMPLATE).exists()
    result = box.ok('refresh_preview')
    assert all(f'{view}, EN' in result for view in ('instructor', 'during-course', 'after-course'))
    assert sorted(row[2] for row in seen[-3:]) == sorted(['instructor', 'during-course', 'after-course'])     # the views render at once, in any order
    assert slide_snapshot.snapshot_path(box.ws.project, 'abc', slide_snapshot.DEFAULT_TEMPLATE, id_slug='abc-EN-Hello').exists()
    assert box.ws.context().view == 'during-course'


@pytest.mark.parametrize('args', [{}, {'view': 'all'}])
def test_refresh_all_views_uses_saved_source_and_returns_statuses_only(box, root, monkeypatch, args):
    seen = fake_render(monkeypatch, root)
    box.ws.open(root / SLIDE, 'UNSAVED')
    captures = []
    render = preview_target.render_text

    def capture(target, text, *args, **kwargs):
        captures.append(text)
        return render(target, text, *args, **kwargs)

    monkeypatch.setattr(preview_target, 'render_text', capture)
    result = box.run('refresh_preview', **args)
    assert not result.is_error and result.images == []
    assert sorted(row[2] for row in seen) == sorted(['instructor', 'during-course', 'after-course'])          # the views render at once, in any order
    assert all(text == (root / SLIDE).read_text() for text in captures)
    assert 'saved source' in result.text and 'cached for after-course' in result.text


def test_preview_tools_reject_invalid_view(box):
    assert "Argument 'view' must be one of" in box.error('render_preview', view='student')
    assert "Argument 'view' must be one of" in box.error('refresh_preview', view='student')


@pytest.mark.parametrize("scope", ["slide", "deck", None])
def test_scope_guards_writing_tools(box, root, monkeypatch, scope):
    box.box.ctx.scope = scope
    box.box.ctx.focus_slide = root / SLIDE
    other = "slides/abd-EN-Second-current.tex"
    monkeypatch.setattr(slidemage_tools, "apply_slide", lambda *args, **kwargs: ("applied", []))
    args = {"old_text": "First", "new_text": "Changed"}
    if scope == "slide":
        assert "switch_to_deck_mode" in box.error("edit_file", path=other, **args)
        assert "switch_to_deck_mode" in box.error("modify_slide", slide=other, edits=[{"old": "First", "new": "Changed"}])
        assert "switch_to_deck_mode" in box.error("write_file", path="decks/new.tex", content="x")
        assert "switch_to_deck_mode" in box.error("add_slide", slug="New", title="New", add_to_deck=False)
        assert "switch_to_deck_mode" in box.error("create_slide", title="New", slug="New", body="x", deck="test")
        assert not box.of_type(EditProposed)
    else:
        assert "Changed" in box.ok("edit_file", path=other, **args)
        assert box.ok("modify_slide", slide=other, edits=[{"old": "Changed", "new": "Again"}]) == "applied"
        assert "Created" in box.ok("write_file", path="decks/new.tex", content="x")
        assert "Created" in box.ok("add_slide", slug="New", title="New", add_to_deck=False)
        assert box.ok("create_slide", title="New", slug="Other", body="x", deck="test") == "applied"
    assert "Changed" in box.ok("edit_file", path=SLIDE, **args)
    assert box.ok("modify_slide", slide=SLIDE, edits=[{"old": "Changed", "new": "Again"}]) == "applied"


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


def test_recursive_argument_validation():
    from slidemage.ai.tools.base import ToolError, check_arguments, tool

    @tool("example", "", {
        "edits": {"type": "array", "minItems": 1, "items": {
            "type": "object", "properties": {"old": {"type": "string", "minLength": 1},
                                              "new": {"type": "string", "enum": ["yes", "no"]}},
            "required": ["old", "new"], "additionalProperties": False}},
        "fields": {"type": "object", "properties": {"known": {"type": "integer"}},
                   "additionalProperties": {"type": "array", "items": {"type": "number"}}},
        "number": {"type": "number"},
    }, ("edits",))
    def example(ctx, args):
        return ""

    valid = {"edits": [{"old": "a", "new": "yes"}], "fields": {"known": 1, "extra": [1, 2.5]}}
    check_arguments(example.spec, valid)
    check_arguments(example.spec, {**valid, "number": 0})
    check_arguments(example.spec, {**valid, "number": 1.5})
    cases = [
        ({}, "Missing required argument 'edits'."),
        ({**valid, "unexpected": 1}, "Unknown argument 'unexpected'. Known: edits, fields, number."),
        ({"edits": []}, "Argument 'edits' needs at least 1 item."),
        ({"edits": [1]}, "Argument 'edits[0]' must be of type object."),
        ({"edits": [{"old": "a", "new": "yes"}, {"old": "b", "new": "no"},
                    {"old": 1, "new": "yes"}]}, "Argument 'edits[2].old' must be of type string."),
        ({"edits": [{"old": "", "new": "yes"}]}, "Argument 'edits[0].old' needs at least 1 character."),
        ({"edits": [{"old": "a"}]}, "Missing required argument 'edits[0].new'."),
        ({"edits": [{"old": "a", "new": "maybe"}]}, "Argument 'edits[0].new' must be one of: yes, no."),
        ({"edits": [{"old": "a", "new": "yes", "other": 1}]},
         "Unknown argument 'edits[0].other'. Known: old, new."),
        ({**valid, "number": True}, "Argument 'number' must be of type number."),
        ({**valid, "fields": {"known": True}}, "Argument 'fields.known' must be of type integer."),
        ({**valid, "fields": {"extra": [True]}}, "Argument 'fields.extra[0]' must be of type number."),
    ]
    for args, expected in cases:
        with pytest.raises(ToolError) as exc:
            check_arguments(example.spec, args)
        assert str(exc.value) == expected


def test_fields_and_qr_height_are_checked_by_schema(box):
    assert "fields.year" not in box.error("add_bib_entry", kind="book", fields={"year": 2024})   # a year as number is fine
    assert box.error("make_qr_code", kind="url", fields={"url": False}) == (
        "Argument 'fields.url' must be of type string.")
    for height in (True, "0.5"):
        assert box.error("make_qr_code", kind="url", fields={"url": "a.org"}, height=height) == (
            "Argument 'height' must be of type number.")


def test_insert_slide_after_and_already_present(box, root):
    box.ok("add_slide", slug="Insert", title="T", add_to_deck=False)
    created, = (root / "slides").glob("*-EN-Insert-current.tex")
    slide = created.name.removesuffix("-current.tex")
    box.events.clear()
    assert "after abc" in box.ok("insert_slide", slide=slide, after="abc")
    deck = root / "decks/test.tex"
    text = deck.read_text()
    assert text.index("abc-EN-Hello") < text.index(slide) < text.index("abd-EN-Second")
    applied, = box.of_type(EditApplied)
    assert applied.path == deck and not applied.undoable
    assert (deck, applied.before) in box.ws.changed
    assert "decks/test.tex" in ai_review.unreviewed(box.ws.project)[created.relative_to(root).as_posix()]["decks"]
    box.events.clear()
    assert "already in test" in box.ok("insert_slide", slide=slide, after="missing")
    assert not box.events and deck.read_text() == text


def test_insert_slide_refuses_dirty_deck_and_slide_scope(box, root):
    box.ok("add_slide", slug="Insert", title="T", add_to_deck=False)
    slide = next((root / "slides").glob("*-EN-Insert-current.tex")).name.removesuffix("-current.tex")
    deck = root / "decks/test.tex"
    before = deck.read_bytes()
    box.events.clear()
    box.box.ctx.scope = "slide"
    assert "switch_to_deck_mode" in box.error("insert_slide", slide=slide)
    box.box.ctx.scope = None
    box.ws.dirty.add(deck)
    assert "unsaved edits" in box.error("insert_slide", slide=slide)
    assert not box.events and deck.read_bytes() == before


def test_add_slide_rejects_existing_argument(box):
    assert "Unknown argument 'existing'" in box.error("add_slide", existing="abc")
