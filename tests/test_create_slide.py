"""Composite slide creation with a fake workspace/renderer; no model or listening socket."""
from dataclasses import replace
from types import SimpleNamespace

import pytest
from agent_fakes import FakeWorkspace, call

from slidemage import ai_review, compiler, deck_editor, preview_target, slide_add, slide_ids, slide_snapshot
from slidemage.ai.agent_types import EDIT_ASK, EDIT_AUTO, EditApplied
from slidemage.ai.mcp_server import McpServer
from slidemage.ai.tools import CLAUDE_CODE_TOOLS, build_toolbox
from slidemage.ai.workspace import WorkspaceContext
from slidemage.deck_scan import scan_decks
from slidemage.project import ProjectContext

BODY = "\\begin{standardframe}{Draft}\nDrafted content.\n\\end{standardframe}\n"
PNG = b"\x89PNG\r\n\x1a\nfake"


@pytest.fixture
def env(root, monkeypatch):
    project = ProjectContext.at(root)
    deck = next(d for d in scan_decks(project) if d.name == "test")
    workspace = FakeWorkspace(root, WorkspaceContext(deck=deck))
    shown, renders, events = [], [], []
    monkeypatch.setattr(workspace, "show_slide", shown.append)

    def render(target, text, view, language, **kwargs):
        renders.append((target, text, view, language, kwargs))
        assert target.source_path.is_file()
        assert ai_review.is_unreviewed(project, target.source_path)
        assert target.id_slug in deck.path.read_text()
        return root / "fake.pdf"

    monkeypatch.setattr(preview_target, "render_text", render)
    monkeypatch.setattr(slide_snapshot, "page_png", lambda pdf, width: PNG)
    # The render service reads the rendered PDF's images (prepare_preview_images) for saved and draft renders alike.
    monkeypatch.setattr(slide_snapshot, "prepare_preview_images", lambda pdf, snapshots, widths: ((PNG, PNG), ()))
    (root / "fake.pdf").write_bytes(b"%PDF-1.4")
    box = build_toolbox(workspace, events.append, compiler.CancelToken(), EDIT_AUTO)
    return SimpleNamespace(root=root, project=project, deck=deck, workspace=workspace, box=box,
                           shown=shown, renders=renders, events=events)


def create(env, **args):
    return env.box.execute(call("create_slide", **(dict(title="Draft", slug="Draft", body=BODY, deck="test") | args)))


def new_slides(env):
    return list(env.project.slides_dir.glob("*-Draft-current.tex"))


@pytest.mark.parametrize("deck", ["test", "test.tex", "decks/test.tex", "absolute"])
@pytest.mark.parametrize("after", [None, "abc"])
def test_one_call_creates_inserts_marks_renders_and_shows(env, deck, after):
    args = dict(deck=str(env.deck.path) if deck == "absolute" else deck)
    if after:
        args["after"] = after
    result = create(env, **args)
    assert not result.is_error, result.text
    path, = new_slides(env)
    assert slide_ids.slide_body(path).replace("\r\n", "\n") == BODY
    calls = deck_editor.parse_slide_calls(next(d for d in scan_decks(env.project) if d.name == "test"))
    id_slug = path.name.removesuffix("-current.tex")
    assert [c.id_slug for c in calls].count(id_slug) == 1
    position = next(i for i, c in enumerate(calls) if c.id_slug == id_slug)
    assert position == (next(i for i, c in enumerate(calls) if c.id == "abc") + 1 if after else len(calls) - 1)
    entry = ai_review.unreviewed(env.project)[path.relative_to(env.root).as_posix()]
    assert entry["kind"] == "draft" and entry["decks"] == ["decks/test.tex"]
    assert env.shown == [path] and len(env.renders) == 1
    assert result.images == [PNG]
    assert id_slug in result.text and path.relative_to(env.root).as_posix() in result.text
    assert ("after abc" if after else "at the end") in result.text
    assert "Lint:" in result.text and "Not reviewed" in result.text
    applied = [event for event in env.events if isinstance(event, EditApplied)]
    assert len(applied) == 2
    assert applied[-1].after == path.read_text() and not applied[-1].undoable


@pytest.mark.parametrize("body, message", [
    (BODY.replace("Drafted content.", "A & B"), "ampersand"),
    (BODY + BODY, "exactly one frame"),
    ("Just text.", "exactly one frame"),
    ("\\documentclass{beamer}\n" + BODY, "documentclass"),
    ("\\begin{document}\n" + BODY + "\\end{document}", "document environment"),
    ("\\usepackage{foo}\n" + BODY, "usepackage"),
    ("\\input{slides/other}\n" + BODY, "input"),
    (BODY.replace("\\end{standardframe}", "\\end{frame}"), "does not match"),
])
def test_invalid_body_writes_nothing(env, body, message):
    before = {p: p.read_bytes() for p in env.root.rglob("*") if p.is_file()}
    result = create(env, body=body)
    assert result.is_error and message in result.text
    assert {p: p.read_bytes() for p in env.root.rglob("*") if p.is_file()} == before
    assert not env.workspace.changed and not env.renders and not env.shown


def test_warning_is_returned_and_does_not_block(env):
    result = create(env, body=BODY.replace("Drafted content.", "5% growth"))
    assert not result.is_error, result.text
    assert "[warning]" in result.text and "percent" in result.text
    assert len(env.renders) == 1


@pytest.mark.parametrize("deck", ["other", "decks/other.tex", "", "elsewhere/test.tex"])
def test_wrong_deck_writes_nothing(env, deck):
    result = create(env, deck=deck)
    assert result.is_error and "not the open deck" in result.text
    assert not new_slides(env) and not env.workspace.changed


def test_insertion_failure_rolls_back_file_and_id(env, monkeypatch):
    ids_before = slide_ids.existing_ids_from_csv(env.project)
    deck_before = env.deck.path.read_bytes()
    monkeypatch.setattr(deck_editor, "insert_slide_call", lambda *args: (_ for _ in ()).throw(OSError("insertion failed")))
    result = create(env)
    assert result.is_error and "rolled back" in result.text
    assert not new_slides(env) and not env.renders
    assert slide_ids.existing_ids_from_csv(env.project) == ids_before
    assert env.deck.path.read_bytes() == deck_before
    assert not ai_review.unreviewed(env.project)


def test_failed_rollback_returns_existing_retry_and_never_mints_a_second_slide(env, monkeypatch):
    insert = deck_editor.insert_slide_call
    monkeypatch.setattr(deck_editor, "insert_slide_call", lambda *args: (_ for _ in ()).throw(OSError("insert failed")))
    monkeypatch.setattr(slide_add, "remove_created", lambda *args: (_ for _ in ()).throw(OSError("rollback failed")))
    result = create(env, after="abc")
    path, = new_slides(env)
    id_slug = path.name.removesuffix("-current.tex")
    assert result.is_error and f"add_slide(existing='{id_slug}', after='abc')" in result.text
    assert "Rollback failed" in result.text and path.relative_to(env.root).as_posix() in result.text
    monkeypatch.setattr(deck_editor, "insert_slide_call", insert)
    for _ in range(2):
        retry = env.box.execute(call("add_slide", existing=id_slug, after="abc"))
        assert not retry.is_error, retry.text
    assert new_slides(env) == [path]
    assert env.deck.path.read_text().count(f"\\slide{{{id_slug}}}") == 1


@pytest.mark.parametrize("change", ["dirty", "switch", "disk"])
def test_deck_is_rechecked_after_confirmation(env, change):
    env.box.ctx.mode = EDIT_ASK
    def changed():
        if change == "dirty":
            env.workspace.dirty.add(env.deck.path)
        elif change == "switch":
            env.workspace._context = replace(env.workspace.context(), deck=None)
        else:
            env.deck.path.write_text(env.deck.path.read_text() + "% changed\n")
    env.workspace.before_confirm = changed
    result = create(env)
    assert result.is_error and not new_slides(env)
    if change == "disk":
        assert env.deck.path.read_text().endswith("% changed\n")


def test_render_failure_keeps_created_slide_and_reports_fixable_error(env, monkeypatch):
    monkeypatch.setattr(preview_target, "render_text", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("! Undefined control sequence.\nl.4 \\unknown")))
    result = create(env)
    path, = new_slides(env)
    assert result.is_error and "Undefined control sequence" in result.text
    assert path.relative_to(env.root).as_posix() in result.text and "stays in place" in result.text
    assert path.name.removesuffix("-current.tex") in env.deck.path.read_text()
    assert env.shown == [path] and ai_review.is_unreviewed(env.project, path)


def test_translation_links_and_marks_both_slides_from_current_buffer(env):
    source = env.root / "slides/abc-EN-Hello-current.tex"
    text = source.read_text() + "\n\\vbox to 0pt{Protected overlay}\n"
    env.workspace.open(source, text, dirty=True)
    translated = slide_ids.body_of(text).replace("Hello", "Hallo").replace("First point", "Erster Punkt")
    result = create(env, language="DE", translation_of="abc", body=translated)
    assert not result.is_error, result.text
    path, = new_slides(env)
    id_slug = path.name.removesuffix("-current.tex")
    assert "%% Translation of: abc-EN-Hello" in path.read_text()
    assert "\\setSlideVersion" not in path.read_text()  # a fresh id starts its own history
    assert f"%% DE translation: {id_slug}" in env.workspace.buffer_text(source)
    assert "%% DE translation:" not in source.read_text()
    entries = ai_review.unreviewed(env.project)
    assert entries[path.relative_to(env.root).as_posix()]["kind"] == "translation"
    assert entries[source.relative_to(env.root).as_posix()]["kind"] == "translation"
    assert env.renders[0][3] == "DE"


def test_translation_protected_regions_and_same_language_are_refused(env):
    source = env.root / "slides/abc-EN-Hello-current.tex"
    source.write_text(source.read_text() + "\n\\vbox to 0pt{Protected}\n")
    result = create(env, language="DE", translation_of="abc", body=slide_ids.slide_body(source).replace("Protected", "Changed"))
    assert result.is_error and "protected" in result.text and not new_slides(env)
    assert "already EN" in create(env, translation_of="abc").text


def test_translation_insertion_failure_restores_source(env, monkeypatch):
    source = env.root / "slides/abc-EN-Hello-current.tex"
    original = source.read_bytes()
    monkeypatch.setattr(deck_editor, "insert_slide_call", lambda *a: (_ for _ in ()).throw(OSError("failed")))
    result = create(env, language="DE", translation_of="abc", body=slide_ids.slide_body(source))
    assert result.is_error and source.read_bytes() == original
    assert not new_slides(env) and not ai_review.unreviewed(env.project)


def test_mcp_exposes_create_slide_and_returns_png_content(env):
    import base64
    server = McpServer(lambda: build_toolbox(env.workspace, env.events.append, compiler.CancelToken(), EDIT_AUTO,
                                            tools=CLAUDE_CODE_TOOLS))
    response = server.handle(dict(jsonrpc="2.0", id=1, method="tools/call", params=dict(
        name="create_slide", arguments=dict(title="Draft", slug="Draft", body=BODY, deck="test"))))
    result = response["result"]
    assert not result["isError"]
    assert result["content"][1] == dict(type="image", mimeType="image/png", data=base64.b64encode(PNG).decode())
    response = server.handle(dict(jsonrpc="2.0", id=2, method="tools/call", params=dict(
        name="create_slide", arguments=dict(title="Draft", slug="Draft", body="bad", deck="test"))))
    assert response["result"]["isError"]


def test_default_language_is_the_edited_language(env):
    env.workspace._context = replace(env.workspace.context(), language="DE")
    result = create(env)
    assert not result.is_error, result.text
    path, = new_slides(env)
    assert "-DE-" in path.name and env.renders[0][3] == "DE"


@pytest.mark.parametrize("frame", slide_add.FRAMES)
def test_frame_forms_and_commented_examples(env, frame):
    body = slide_add.frame_body(env.project, frame, "Draft").replace("\r\n", "\n")
    body = body.replace("media/your-image.pdf", "media/known.pdf")
    (env.root / "media").mkdir(exist_ok=True)
    (env.root / "media" / "known.pdf").touch()
    result = create(env, frame=frame, body="% \\begin{frame} example\n" + body)
    assert not result.is_error, result.text
    assert len(env.renders) == 1


def test_rollback_preserves_an_id_appended_by_another_writer(env, monkeypatch):
    before = slide_ids.existing_ids_from_csv(env.project)
    def failed(*args):
        slide_ids.append_slide_id(env.project, "xyz")
        raise OSError("failed")
    monkeypatch.setattr(deck_editor, "insert_slide_call", failed)
    result = create(env)
    assert result.is_error and not new_slides(env)
    assert slide_ids.existing_ids_from_csv(env.project) == before | {"xyz"}


def test_rejected_creation_writes_nothing(env):
    env.box.ctx.mode = EDIT_ASK
    env.workspace.approve = False
    result = create(env)
    assert result.is_error and "rejected" in result.text
    assert not new_slides(env) and not env.workspace.changed


def test_translation_preserves_newer_source_and_rolls_back_creation(env):
    source = env.root / "slides/abc-EN-Hello-current.tex"
    body = slide_ids.slide_body(source)
    env.box.ctx.mode = EDIT_ASK
    env.workspace.before_confirm = lambda: source.write_text(source.read_text() + "% newer source\n")
    result = create(env, language="DE", translation_of="abc", body=body)
    assert result.is_error and "rolled back" in result.text
    assert source.read_text().endswith("% newer source\n") and not new_slides(env)


def test_translation_rollback_failure_marks_both_surviving_slides(env, monkeypatch):
    source = env.root / "slides/abc-EN-Hello-current.tex"
    monkeypatch.setattr(deck_editor, "insert_slide_call", lambda *a: (_ for _ in ()).throw(OSError("insert failed")))
    monkeypatch.setattr(slide_add, "remove_created", lambda *a: (_ for _ in ()).throw(OSError("cleanup failed")))
    result = create(env, language="DE", translation_of="abc", body=slide_ids.slide_body(source))
    path, = new_slides(env)
    assert result.is_error and "add_slide(existing=" in result.text
    assert ai_review.is_unreviewed(env.project, path) and ai_review.is_unreviewed(env.project, source)


@pytest.mark.parametrize("buffer", [False, True])
def test_shared_tail_uses_the_existing_edit_write_and_undo_path(env, buffer):
    from slidemage.ai.tools.slidemage import apply_slide

    path = env.root / "slides/abc-EN-Hello-current.tex"
    before = path.read_text()
    after = before.replace("First point", "Edited point")
    if buffer:
        env.workspace.open(path, before)
    text, images = apply_slide(env.box.ctx, path, before, after)
    assert "Not reviewed" in text and images == [PNG]
    written = after if buffer else after.replace("\\setSlideVersion{1-0-0}", "\\setSlideVersion{1-0-0+}")
    assert (env.workspace.buffer_text(path) if buffer else path.read_text()) == written
    assert ai_review.unreviewed(env.project)[path.relative_to(env.root).as_posix()]["kind"] == "edit"
    applied = next(e for e in env.events if isinstance(e, EditApplied))
    assert applied.undoable and applied.via_buffer == buffer
    assert env.shown == [path] and len(env.renders) == 1
    assert bool(list((env.project.slide_backups_dir / path.name).glob("*.tex"))) != buffer


def test_shared_tail_preserves_text_typed_during_confirmation(env):
    from slidemage.ai.tools import ToolError
    from slidemage.ai.tools.slidemage import apply_slide

    path = env.root / "slides/abc-EN-Hello-current.tex"
    before = path.read_text()
    env.workspace.open(path, before)
    env.box.ctx.mode = EDIT_ASK
    env.workspace.before_confirm = lambda: env.workspace.buffers.update({path: before + "% user typed\n"})
    with pytest.raises(ToolError, match="changed while"):
        apply_slide(env.box.ctx, path, before, before.replace("First point", "Edited point"))
    assert env.workspace.buffer_text(path).endswith("% user typed\n") and not env.renders
    assert not ai_review.unreviewed(env.project)
