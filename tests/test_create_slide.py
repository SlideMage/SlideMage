# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Composite slide creation with a fake workspace/renderer; no model or listening socket."""
from dataclasses import replace
from types import SimpleNamespace

import pytest
from agent_fakes import FakeWorkspace, call

from slidemage import ai_review, compiler, deck_editor, deck_headers, fileio, preview_target, slide_add, slide_ids, slide_snapshot
from slidemage.ai.agent_types import EDIT_ASK, EDIT_AUTO, EditApplied
from slidemage.ai.tools import build_toolbox
from slidemage.ai.workspace import WorkspaceContext
from slidemage.deck_scan import read_deck, scan_decks
from slidemage.project import ProjectContext

SOURCE = "slides/abc-EN-Hello-current.tex"
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
    monkeypatch.setattr(slide_snapshot, "prepare_preview_images", lambda pdf, snapshots, widths: ((PNG, PNG), ()))
    (root / "fake.pdf").write_bytes(b"%PDF-1.4")
    box = build_toolbox(workspace, events.append, compiler.CancelToken(), EDIT_AUTO)
    return SimpleNamespace(root=root, project=project, deck=deck, workspace=workspace, box=box,
                           shown=shown, renders=renders, events=events)


def create(env, **args):
    return env.box.execute(call("create_slide", **(dict(title="Draft", slug="Draft", body=BODY) | args)))


def new_slides(env):
    return list(env.project.slides_dir.glob("*-Draft-current.tex"))


def assert_no_creation(env):
    assert not new_slides(env) and not env.workspace.changed and not env.renders


@pytest.mark.parametrize("after", [None, "abc"])
def test_create_commits_slide_and_deck_before_rendering_and_showing(env, monkeypatch, after):
    # Late header sync used to invalidate the first preview.
    commits = []
    write = fileio.write_texts

    def record(edits, **kwargs):
        commits.append(edits)
        write(edits, **kwargs)

    monkeypatch.setattr(fileio, "write_texts", record)
    monkeypatch.setattr(deck_headers, "write_texts", record)
    env.workspace._context = replace(env.workspace.context(), language="DE")
    body = BODY.replace("Drafted content.", "5% growth")
    result = create(env, body=body, **({"deck": str(env.deck.path), "after": after} if after else {}))
    assert not result.is_error, result.text
    path, = new_slides(env)
    assert slide_ids.slide_body(path).replace("\r\n", "\n") == body
    assert "-DE-" in path.name and env.renders[0][3] == "DE"
    calls = deck_editor.parse_slide_calls(read_deck(env.deck.path))
    id_slug = path.name.removesuffix("-current.tex")
    ids = [call.id_slug for call in calls]
    expected = ids.index("abc-EN-Hello") + 1 if after else len(ids) - 1
    assert [i for i, slug in enumerate(ids) if slug == id_slug] == [expected]
    entry = ai_review.unreviewed(env.project)[path.relative_to(env.root).as_posix()]
    assert entry["kind"] == "draft" and entry["decks"] == ["decks/test.tex"]
    assert env.shown == [path] and len(env.renders) == 1
    assert "%% Included in decks: test" in env.renders[0][1]
    assert [list(edits) for edits in commits] == [[path, env.deck.path, env.project.slide_ids_csv]]
    assert deck_headers.regenerate_headers(env.project)[0] == 0
    assert result.images == [PNG]
    assert id_slug in result.text and path.relative_to(env.root).as_posix() in result.text
    assert "[warning]" in result.text and "percent" in result.text
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


@pytest.mark.parametrize("deck", ["", "elsewhere/test.tex", None])
def test_wrong_or_missing_open_deck_writes_nothing(env, deck):
    if deck is None:
        env.workspace._context = replace(env.workspace.context(), deck=None)
        result = create(env)
        assert "No deck is open" in result.text
    else:
        result = create(env, deck=deck)
        assert "not the open deck" in result.text
    assert result.is_error
    assert_no_creation(env)


def fail_deck_write(env, monkeypatch, *, before_failure=lambda: None):
    publish = fileio.write_text_exact

    def failed(path, text, **kwargs):
        if path == env.deck.path:
            before_failure()
            raise OSError("insertion failed")
        return publish(path, text, **kwargs)

    monkeypatch.setattr(fileio, "write_text_exact", failed)


def test_insertion_failure_rolls_back_file_and_id(env, monkeypatch):
    ids_before = slide_ids.existing_ids_from_csv(env.project)
    deck_before = env.deck.path.read_bytes()
    fail_deck_write(env, monkeypatch)
    result = create(env)
    assert result.is_error and "Restored all files" in result.text
    assert not new_slides(env) and not env.renders
    assert slide_ids.existing_ids_from_csv(env.project) == ids_before
    assert env.deck.path.read_bytes() == deck_before
    assert not ai_review.unreviewed(env.project)


def test_add_retry_uses_original_deck_path_even_with_an_archived_namesake(env, monkeypatch):
    archived = env.project.archive_dir / env.deck.path.name
    archived.parent.mkdir(parents=True, exist_ok=True)
    archived.write_bytes(env.deck.path.read_bytes())
    archived_deck = next(deck for deck in scan_decks(env.project) if deck.path == archived)
    env.box.ctx.mode = EDIT_ASK

    def switch_deck():
        env.workspace._context = replace(env.workspace.context(), deck=archived_deck)

    env.workspace.before_confirm = switch_deck
    with monkeypatch.context() as failure:
        fail_deck_write(env, failure)
        result = env.box.execute(call("add_slide", title="Draft", slug="Draft", after="abc"))
    path, = new_slides(env)
    id_slug = path.name.removesuffix("-current.tex")
    assert result.is_error and f"insert_slide(slide='{id_slug}', deck='decks/test.tex', after='abc')" in result.text
    env.deck.path.write_bytes(b"% moved anchor\r\n" + env.deck.path.read_bytes())
    for _ in range(2):
        retry = env.box.execute(call("insert_slide", slide=id_slug, deck="decks/test.tex", after="abc"))
        assert not retry.is_error, retry.text
    assert new_slides(env) == [path]
    assert f"\\slide{{abc-EN-Hello}}\n\\slide{{{id_slug}}}" in env.deck.path.read_text()
    assert env.deck.path.read_text().count(id_slug) == 1 and id_slug not in archived.read_text()


@pytest.mark.parametrize("change,selection", [("dirty", {}), ("switch", {}), ("disk", {"deck": "test"})])
def test_deck_is_rechecked_after_confirmation(env, change, selection):
    env.box.ctx.mode = EDIT_ASK

    def changed():
        if change == "dirty":
            env.workspace.dirty.add(env.deck.path)
        elif change == "switch":
            env.workspace._context = replace(env.workspace.context(), deck=None)
        else:
            env.deck.path.write_text(env.deck.path.read_text() + "% changed\n")
    env.workspace.before_confirm = changed
    result = create(env, **selection)
    assert result.is_error
    assert_no_creation(env)
    if change == "disk":
        assert env.deck.path.read_text().endswith("% changed\n")
    elif change == "switch":
        assert "not the open deck" in result.text


def test_render_failure_keeps_created_slide_and_reports_fixable_error(env, monkeypatch):
    monkeypatch.setattr(preview_target, "render_text", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("! Undefined control sequence.\nl.4 \\unknown")))
    result = create(env)
    path, = new_slides(env)
    assert result.is_error and "Undefined control sequence" in result.text
    assert path.relative_to(env.root).as_posix() in result.text and "stays in place" in result.text
    assert path.name.removesuffix("-current.tex") in env.deck.path.read_text()
    assert env.shown == [path] and ai_review.is_unreviewed(env.project, path)


def test_translation_links_and_marks_both_slides_from_current_buffer(env):
    env.deck.path.with_name("other.tex").write_bytes(env.deck.path.read_bytes())
    source = env.root / SOURCE
    text = source.read_text() + "\n\\vbox to 0pt{Protected overlay}\n"
    env.workspace.open(source, text, dirty=True)
    translated = slide_ids.body_of(text).replace("Hello", "Hallo").replace("First point", "Erster Punkt")
    result = create(env, language="DE", translation_of="abc", body=translated)
    assert not result.is_error, result.text
    path, = new_slides(env)
    id_slug = path.name.removesuffix("-current.tex")
    assert "%% Translation of: abc-EN-Hello" in path.read_text()
    assert "%% Included in decks: other, test" in env.renders[0][1]
    assert "\\setSlideVersion" not in path.read_text()  # a fresh id starts its own history
    assert f"%% DE translation: {id_slug}" in env.workspace.buffer_text(source)
    assert "%% DE translation:" not in source.read_text()
    entries = ai_review.unreviewed(env.project)
    assert entries[path.relative_to(env.root).as_posix()]["kind"] == "translation"
    assert entries[source.relative_to(env.root).as_posix()]["kind"] == "translation"
    assert env.renders[0][3] == "DE"


def test_translation_protected_regions_and_same_language_are_refused(env):
    source = env.root / SOURCE
    source.write_text(source.read_text() + "\n\\setSlideVersion{Protected}\n")
    result = create(env, language="DE", translation_of="abc", body=slide_ids.slide_body(source).replace("Protected", "Changed"))
    assert result.is_error and "protected" in result.text and not new_slides(env)
    assert "already EN" in create(env, translation_of="abc").text


def test_translation_insertion_failure_restores_source(env, monkeypatch):
    source = env.root / SOURCE
    original = source.read_bytes()
    fail_deck_write(env, monkeypatch)
    result = create(env, language="DE", translation_of="abc", body=slide_ids.slide_body(source))
    assert result.is_error and source.read_bytes() == original
    assert not new_slides(env) and not ai_review.unreviewed(env.project)


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
    csv = env.project.slide_ids_csv
    before = slide_ids.existing_ids_from_csv(env.project)
    publish = fileio.write_text_exact

    def failed(path, text, **kwargs):
        if path == csv:
            csv.write_bytes(csv.read_bytes() + b'"xyz"\r\n')
        return publish(path, text, **kwargs)

    monkeypatch.setattr(fileio, "write_text_exact", failed)
    result = create(env)
    assert result.is_error and not new_slides(env)
    assert before | {"xyz"} <= slide_ids.existing_ids_from_csv(env.project)


def test_rejected_creation_writes_nothing(env):
    env.box.ctx.mode = EDIT_ASK
    env.workspace.approve = False
    result = create(env)
    assert result.is_error and "rejected" in result.text
    assert_no_creation(env)


def test_translation_preserves_newer_source_and_rolls_back_creation(env):
    source = env.root / SOURCE
    body = slide_ids.slide_body(source)
    env.box.ctx.mode = EDIT_ASK
    env.workspace.before_confirm = lambda: source.write_text(source.read_text() + "% newer source\n")
    result = create(env, language="DE", translation_of="abc", body=body)
    assert result.is_error and "changed on disk" in result.text
    assert source.read_text().endswith("% newer source\n") and not new_slides(env)


def test_translation_partial_write_reports_surviving_files(env, monkeypatch):
    source = env.root / SOURCE

    def outside_edit():
        source.write_bytes(source.read_bytes() + b"% newer edit\r\n")

    fail_deck_write(env, monkeypatch, before_failure=outside_edit)
    result = create(env, language="DE", translation_of="abc", body=slide_ids.slide_body(source))
    path, = new_slides(env)
    assert result.is_error and "Kept:" in result.text
    assert str(path) in result.text and str(source) in result.text
    assert source.read_bytes().endswith(b"% newer edit\r\n")
