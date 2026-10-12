"""The agent's tools on a throwaway project (never the real example/): path confinement, reading,
finding, the edit rules (buffer or disk, protected parts, frozen versions, ask / auto), the
SlideMage tools over their backends, and the context block."""
from __future__ import annotations

import os

import pytest
from agent_fakes import FakeWorkspace, call
from conftest import SLIDE_TEXT

from slidemage import compiler, preview_target, slide_snapshot
from slidemage.ai import agent_context
from slidemage.ai.agent_types import (
    EDIT_ASK,
    EDIT_AUTO,
    EditApplied,
    EditProposed,
    EditRejected,
)
from slidemage.ai.tools import build_toolbox, focus, undo_edit
from slidemage.ai.tools import slidemage as slidemage_tools
from slidemage.project import ProjectContext
from slidemage.ai.workspace import Workspace, WorkspaceContext
from slidemage.deck_scan import scan_decks


@pytest.fixture
def ctx(root):
    return ProjectContext.at(root)

SLIDE = "slides/abc-EN-Hello-current.tex"
LF = SLIDE_TEXT.replace("\r\n", "\n")


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
    assert text.startswith(f"{SLIDE} (12 lines)\n1\t%% Included in decks: test\n")
    assert "\r" not in text and "6\t\\begin{standardframe}{Hello}" in text
    part = box.ok("read_file", path=SLIDE, start_line=7, max_lines=2)
    assert "7\t\t\\begin{itemize}" in part and "read on with start_line=9" in part
    assert "There is no line 99" in box.ok("read_file", path=SLIDE, start_line=99)
    box.ws.open(box.root / SLIDE, "buffer text\n", dirty=True)
    assert "1\tbuffer text" in box.ok("read_file", path=SLIDE)


def test_read_file_refuses_folders_missing_and_binary_files(box):
    (box.root / "media").mkdir()
    (box.root / "media" / "pic.png").write_bytes(b"\x89PNG\0\0data")
    assert "is a folder" in box.error("read_file", path="slides")
    assert "does not exist" in box.error("read_file", path="slides/nope.tex")
    assert "not a text file" in box.error("read_file", path="media/pic.png")


def test_find_files_matches_patterns(box):
    assert box.ok("find_files", pattern="slides/*-current.tex").splitlines() == [
        "slides/abc-EN-Hello-current.tex", "slides/abd-EN-Second-current.tex"]
    assert "Slidemaster.bib" in box.ok("find_files", pattern="*.bib")
    assert "decks/test.tex" in box.ok("find_files", pattern="**/*.tex")
    assert "No file matches" in box.ok("find_files", pattern="*.xyz")
    assert ".." in box.error("find_files", pattern="../*")


def test_search_finds_text_in_slides_and_the_bib(box):
    out = box.ok("search", query="second point")
    assert "slides/abc-EN-Hello-current.tex:9" in out and "slides/abd-EN-Second-current.tex" in out
    assert "Slidemaster.bib" in box.ok("search", query="Older")
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
    assert raw == SLIDE_TEXT.replace(old, new) and "\r\n" in raw
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
    ("\\hbox{overlay}", "\\hbox{changed}"),                                  # inside \vbox to 0pt{...}
    ("\t\\vbox to 0pt{\\vss\\hbox{overlay}}\n", ""),
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
    assert (root / SLIDE).read_bytes().decode() == SLIDE_TEXT

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
    assert "Only .tex" in box.error("lint", path="Slidemaster.bib")


def test_render_preview_returns_the_image_of_the_buffer(box, root, monkeypatch):
    seen = {}

    def fake_render(target, text, view, language, **kwargs):
        seen.update(target=target, text=text, view=view, language=language, **kwargs)
        return root / "x.pdf"

    monkeypatch.setattr(preview_target, "render_text", fake_render)
    monkeypatch.setattr(slide_snapshot, "page_png", lambda pdf, width: b"\x89PNG-image")
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
    assert "not a slide" in box.error("render_preview", slide="Slidemaster.bib")


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


def test_add_bib_entry_writes_a_sorted_entry_with_a_suggested_key(box, root):
    box.box.ctx.mode = EDIT_AUTO
    out = box.ok("add_bib_entry", kind="article", fields={
        "author": "Markowitz, Harry", "title": "Portfolio Selection", "year": "1952",
        "journaltitle": "Journal of Finance & Co"})
    assert "markowitz1952" in out and "\\fullcite{markowitz1952}" in out
    bib = (root / "Slidemaster.bib").read_text()
    assert bib.index("markowitz1952") < bib.index("old2000")             # sorted by key
    assert "Journal of Finance \\& Co" in bib
    assert box.ws.changed[-1][0] == root / "Slidemaster.bib"
    assert "already exists" in box.error("add_bib_entry", kind="book", key="old2000", fields={
        "author": "A, B", "title": "T", "year": "2000", "publisher": "P"})


def test_add_bib_entry_refuses_a_taken_key_before_asking_and_a_buffer_that_got_edits_while_asking(box, root):
    taken = dict(kind="book", key="old2000", fields={"author": "A, B", "title": "T", "year": "2000", "publisher": "P"})
    assert "already exists" in box.error("add_bib_entry", **taken) and not box.ws.asked          # ask mode: nobody was asked
    bib = root / "Slidemaster.bib"
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
    box.ws.dirty.add(box.root / "Slidemaster.bib")
    assert "unsaved edits" in box.error("add_bib_entry", kind="book", fields={
        "author": "A, B", "title": "T", "year": "2000", "publisher": "P"})


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
