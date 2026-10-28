# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The real plugin host: folders, settings, background work, deck edits, render priority, window delegation."""
from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path

import pytest

from conftest import DECK_TEXT, make_project, wait_until
from slidemage import deck_scan, plugin_api
from slidemage.background_renders import BackgroundRenderer
from slidemage.plugins import host as host_module
from slidemage.plugins.host import PluginHost, deck_snapshot, plugin_render_priority
from slidemage.plugins.loader import LoadedPlugin
from slidemage.plugins.manifest import read_manifest
from slidemage.plugins.registry import Contributions
from slidemage.project import ProjectContext

FIXTURES = Path(__file__).parent / "fixtures" / "plugins"


@pytest.fixture
def pctx(tmp_path, monkeypatch):
    monkeypatch.setattr(host_module.project, "config_dir", lambda: tmp_path / "config")
    return ProjectContext.at(make_project(monkeypatch, tmp_path / "project"))


@pytest.fixture
def host(pctx):
    return PluginHost(read_manifest(FIXTURES / "hello"), pctx)


def snapshot(pctx):
    return deck_snapshot(deck_scan.read_deck(pctx.decks_dir / "test.tex"), pctx)


def test_cache_dirs(host, tmp_path):
    path = host.cache_dir()
    assert path.is_dir() and path.parts[-2:] == ("plugins", "hello")
    assert path.parent.parent == host_module.project.cache_dir()
    assert host.legacy_cache_dir() == host_module.project.cache_dir()


def test_legacy_cache_dir_missing(host, monkeypatch, tmp_path):
    monkeypatch.setattr(host_module.project, "cache_dir", lambda: tmp_path / "nothing")
    assert host.legacy_cache_dir() is None


def test_settings_round_trip(host, pctx):
    s = host.settings()
    assert s.get("a", 5) == 5
    s.set("a", {"x": [1, "ä"]})
    path = host_module.project.config_dir() / "plugins" / "settings" / "hello.json"
    assert not path.exists()                   # memory only until save()
    s.save()
    assert json.loads(path.read_text(encoding="utf-8")) == {"a": {"x": [1, "ä"]}}
    assert not list(path.parent.glob("*.tmp"))
    again = PluginHost(read_manifest(FIXTURES / "hello"), pctx).settings()
    assert again.get("a") == {"x": [1, "ä"]}
    with pytest.raises(TypeError):
        s.set("bad", object())


def test_settings_save_is_atomic(host, monkeypatch):
    s = host.settings()
    s.set("a", 1)
    s.save()
    s.set("a", 2)

    def boom(*args):
        raise OSError("disk")

    monkeypatch.setattr(host_module.os, "replace", boom)
    with pytest.raises(OSError):
        s.save()
    assert json.loads(s.path.read_text(encoding="utf-8")) == {"a": 1}
    assert not list(s.path.parent.glob("*.tmp"))


def test_run_in_background_delivers_on_main_thread(host, qapp):
    got = []
    main = threading.get_ident()
    worker = []

    def work():
        worker.append(threading.get_ident())
        return 42

    host.run_in_background(work, lambda r, e: got.append((r, e, threading.get_ident())))
    wait_until(lambda: got)
    assert got == [(42, None, main)] and worker[0] != main


def test_run_in_background_error(host, qapp):
    got = []

    def work():
        raise ValueError("nope")

    host.run_in_background(work, lambda r, e: got.append((r, e)))
    wait_until(lambda: got)
    assert got[0][0] is None and isinstance(got[0][1], ValueError)


def test_insert_positions(host, pctx):
    labels = [p.label for p in host.insert_positions(snapshot(pctx))]
    assert labels == ["At the beginning", "After 1. abc-EN-Hello", "After 2. abd-EN-Second"]


def test_insert_slides(host, pctx):
    deck = snapshot(pctx)
    pos = host.insert_positions(deck)[1]
    paths = host.insert_slides(deck, pos, [("One", "\\begin{frame}A\\end{frame}"), ("Two", "B")], "en")
    assert len(paths) == 2 and all(p.is_file() for p in paths)
    text = paths[0].read_bytes().decode()
    assert text.startswith("%% Included in decks: (none)\r\n") and "\\setSlideVersion{1-0-0}\r\n" in text
    assert paths[0].name.endswith("-EN-One-current.tex")
    slugs = [p.name[:-len("-current.tex")] for p in paths]
    new = (pctx.decks_dir / "test.tex").read_text(encoding="utf-8", newline="")
    calls = [line for line in new.split("\r\n") if line.startswith("\\slide{")]
    assert calls == ["\\slide{abc-EN-Hello}", f"\\slide{{{slugs[0]}}}", f"\\slide{{{slugs[1]}}}",
                     "\\slide{abd-EN-Second}"]
    ids = pctx.slide_ids_csv.read_text()
    assert all(s.split("-")[0] in ids for s in slugs)
    de = host.insert_slides(snapshot(pctx), host.insert_positions(snapshot(pctx))[0], [("X", "c")], "de")
    assert de[0].name.split("-")[1] == "DE"


def test_insert_slides_all_or_nothing(host, pctx, monkeypatch):
    deck = snapshot(pctx)
    before = set(pctx.slides_dir.iterdir())
    csv = pctx.slide_ids_csv.read_bytes() if pctx.slide_ids_csv.exists() else None
    real = host_module.slide_ids.mint_slide_id
    calls = []

    def flaky(ctx):
        calls.append(1)
        if len(calls) == 2:
            raise OSError("disk full")
        return real(ctx)

    monkeypatch.setattr(host_module.slide_ids, "mint_slide_id", flaky)
    with pytest.raises(OSError):
        host.insert_slides(deck, host.insert_positions(deck)[0], [("A", "a"), ("B", "b")], "en")
    assert set(pctx.slides_dir.iterdir()) == before
    assert (pctx.slide_ids_csv.read_bytes() if pctx.slide_ids_csv.exists() else None) == csv
    assert (pctx.decks_dir / "test.tex").read_bytes() == DECK_TEXT.encode()


def test_stale(host, pctx):
    deck = snapshot(pctx)
    path = pctx.decks_dir / "test.tex"
    path.write_bytes(DECK_TEXT.replace("Intro", "Other").encode())
    before = set(pctx.slides_dir.iterdir())
    with pytest.raises(plugin_api.StaleFileError):
        host.insert_slides(deck, host.insert_positions(deck)[0], [("A", "a")], "en")
    assert set(pctx.slides_dir.iterdir()) == before
    with pytest.raises(plugin_api.StaleFileError):
        host.edit_deck_text(deck, lambda t: t + "x")


def test_edit_deck_text(host, pctx):
    deck = snapshot(pctx)
    new = host.edit_deck_text(deck, lambda t: t.replace("Intro", "Start"))
    assert "Start" in new and (pctx.decks_dir / "test.tex").read_bytes().decode() == new
    assert "\r\n" in new
    other = snapshot(pctx)
    with pytest.raises(ValueError):
        host.edit_deck_text(other, lambda t: (_ for _ in ()).throw(ValueError("bad")))
    assert (pctx.decks_dir / "test.tex").read_bytes().decode() == new


def test_deck_language(host, pctx):
    d = snapshot(pctx)
    assert host.deck_language(d) in ("de", "en")
    de = deck_snapshot(deck_scan.read_deck(pctx.decks_dir / "test.tex"))
    de.text = "\\decklanguage[de]\n"
    en = deck_snapshot(deck_scan.read_deck(pctx.decks_dir / "test.tex"))
    en.text = "\\decklanguage[en]\n"
    assert (host.deck_language(de), host.deck_language(en)) == ("de", "en")


def test_snapshot(pctx):
    d = snapshot(pctx)
    assert d.name == "test" and d.path == pctx.decks_dir / "test.tex" and d.text == DECK_TEXT
    assert isinstance(d.groups, tuple)


def test_open_url(host, monkeypatch):
    opened = []
    monkeypatch.setattr(host_module.open_path, "open_in_default_app", opened.append)
    host.open_url("https://example.org/x")
    host.open_url("HTTP://example.org")
    assert len(opened) == 2
    for bad in ("ftp://example.org", "file:///etc/passwd", "javascript:alert(1)", "example.org"):
        with pytest.raises(ValueError):
            host.open_url(bad)
    assert len(opened) == 2


def test_log_and_message_without_ui(host, caplog):
    with caplog.at_level(logging.INFO, logger="slidemage.plugins.hello"):
        host.log("hi")
        host.show_message("oops", error=True)
    assert [(r.name, r.levelno, r.getMessage()) for r in caplog.records] == [
        ("slidemage.plugins.hello", logging.INFO, "hi"), ("slidemage.plugins.hello", logging.ERROR, "oops")]


class FakeUi:
    def __init__(self):
        self.calls = []

    def open_deck_settings(self, deck, tab=None):
        self.calls.append(("settings", deck, tab))

    def Page(self):
        return "page"

    def Field(self, label, widget):
        return (label, widget)

    def caption(self, text, tone=""):
        return (text, tone)

    def show_message(self, text, error=False):
        self.calls.append(("message", text, error))


def test_ui_delegation(pctx):
    ui = FakeUi()
    h = PluginHost(read_manifest(FIXTURES / "hello"), pctx, ui)
    d = snapshot(pctx)
    h.open_deck_settings(d, "Tab")
    h.show_message("m", True)
    assert h.Page() == "page" and h.Field("l", 1) == ("l", 1) and h.caption("t", "error") == ("t", "error")
    assert ui.calls == [("settings", d, "Tab"), ("message", "m", True)]


def test_no_window(host, pctx):
    for call in (lambda: host.Page(), lambda: host.Field("a", None), lambda: host.caption("a"),
                 lambda: host.open_deck_settings(snapshot(pctx))):
        with pytest.raises(RuntimeError, match="no window"):
            call()


def loaded(plugin_id, *soons, state="loaded"):
    p = LoadedPlugin(Path("."), "dev", plugin_id, None, state)
    p.contributions = Contributions(render_priorities=list(soons))
    return p


def test_render_priority(pctx, caplog):
    deck = deck_scan.read_deck(pctx.decks_dir / "test.tex")
    seen = []

    def names(d):
        seen.append(d.name)
        return d.name == "test"

    def boom(d):
        raise RuntimeError("x")

    assert plugin_render_priority([])(deck) is False
    assert plugin_render_priority([loaded("a", lambda d: False), loaded("b", names)])(deck) is True
    assert seen == ["test"]
    soon = plugin_render_priority([loaded("bad", boom), loaded("c", lambda d: False)])
    with caplog.at_level(logging.ERROR):
        assert soon(deck) is False and soon(deck) is False
    assert len([r for r in caplog.records if r.name == "slidemage.plugins.bad"]) == 1
    assert plugin_render_priority([loaded("bad", boom), loaded("ok", lambda d: True)])(deck) is True
    assert plugin_render_priority([loaded("off", lambda d: True, state="disabled")])(deck) is False


def test_renderer_combines_core_and_plugin_rules(pctx):
    deck = deck_scan.read_deck(pctx.decks_dir / "test.tex")
    r = BackgroundRenderer.__new__(BackgroundRenderer)
    r._core_soon = lambda d: False
    r.plugin_soon = None
    assert r._soon(deck) is False
    r.plugin_soon = lambda d: True
    assert r._soon(deck) is True
    r._core_soon, r.plugin_soon = (lambda d: True), (lambda d: False)
    assert r._soon(deck) is True


def tex_files(pctx):
    return {p.name: p.read_bytes() for p in pctx.slides_dir.iterdir()}


# -- insertion is all or nothing -------------------------------------------------------------------------------

def assert_untouched(pctx, deck_bytes, slides, csv):
    assert (pctx.decks_dir / "test.tex").read_bytes() == deck_bytes
    assert tex_files(pctx) == slides
    assert (pctx.slide_ids_csv.read_bytes() if pctx.slide_ids_csv.exists() else None) == csv
    assert not [p for p in pctx.slides_dir.iterdir() if p.name.endswith(".tmp")]
    assert not [p for p in pctx.decks_dir.iterdir() if p.name.endswith(".tmp")]


@pytest.fixture
def state(host, pctx):
    csv = pctx.slide_ids_csv.read_bytes() if pctx.slide_ids_csv.exists() else None
    return snapshot(pctx), (pctx.decks_dir / "test.tex").read_bytes(), tex_files(pctx), csv


@pytest.mark.parametrize("where", ["fsync", "replace"])
def test_a_failure_while_writing_a_slide_leaves_nothing_behind(host, pctx, state, monkeypatch, where):
    deck, deck_bytes, slides, csv = state
    from slidemage import fileio
    real_fsync, real_replace = os.fsync, os.replace
    calls = []

    def boom_fsync(fd):
        calls.append(fd)
        if len(calls) == 2:                      # the second slide, after its text is written
            raise OSError("injected: disk full")
        return real_fsync(fd)

    def boom_replace(src, dst, *a):
        if str(dst).endswith("-current.tex"):
            calls.append(dst)
            if len(calls) == 2:
                raise OSError("injected: rename failed")
        return real_replace(src, dst, *a)

    monkeypatch.setattr(fileio.os, "fsync", boom_fsync)
    monkeypatch.setattr(fileio.os, "replace", boom_replace)
    with pytest.raises(OSError, match="injected"):
        host.insert_slides(deck, host.insert_positions(deck)[0], [("A", "a"), ("B", "b")], "en")
    assert_untouched(pctx, deck_bytes, slides, csv)


def test_a_slide_file_that_is_created_and_then_fails_is_removed(host, pctx, state, monkeypatch):
    """The new file is tracked before its content is written: a failure that leaves a partial file is cleaned."""
    deck, deck_bytes, slides, csv = state

    real = host_module.atomic_write

    def partial(path, data, **kw):
        if not path.name.endswith("-current.tex"):
            return real(path, data, **kw)           # the restore of slide_ids.csv
        path.write_bytes(data.encode()[:7])
        raise OSError("injected partial write")

    monkeypatch.setattr(host_module, "atomic_write", partial)
    with pytest.raises(OSError, match="injected"):
        host.insert_slides(deck, host.insert_positions(deck)[0], [("A", "a")], "en")
    assert_untouched(pctx, deck_bytes, slides, csv)


def test_a_failure_during_the_deck_commit_after_a_partial_write_keeps_the_deck(host, pctx, state, monkeypatch):
    deck, deck_bytes, slides, csv = state
    from slidemage import fileio
    real_fdopen = os.fdopen

    class Partial:
        def __init__(self, handle):
            self.handle = handle

        def __enter__(self):
            return self

        def write(self, data):
            fdopen.deck_phase[0] = False             # one fault only: the rollback writes normally
            self.handle.write(data[:9])
            self.handle.flush()
            raise OSError("injected: disk full after 9 bytes")

        def __getattr__(self, name):
            return getattr(self.handle, name)

        def __exit__(self, *args):
            self.handle.close()

    def fdopen(fd, mode="r", *a, **kw):
        handle = real_fdopen(fd, mode, *a, **kw)
        return Partial(handle) if "wb" in mode and fdopen.deck_phase[0] else handle

    fdopen.deck_phase = [False]
    real_slide_calls = host_module.deck_editor.insert_slide_calls

    def calls(*args, **kw):
        fdopen.deck_phase[0] = True              # the slides are written; now the deck
        return real_slide_calls(*args, **kw)

    monkeypatch.setattr(fileio.os, "fdopen", fdopen)
    monkeypatch.setattr(host_module.deck_editor, "insert_slide_calls", calls)
    with pytest.raises(OSError, match="injected"):
        host.insert_slides(deck, host.insert_positions(deck)[0], [("A", "a"), ("B", "b")], "en")
    assert_untouched(pctx, deck_bytes, slides, csv)


def test_a_failed_rename_of_the_deck_keeps_the_deck(host, pctx, state, monkeypatch):
    deck, deck_bytes, slides, csv = state
    from slidemage import fileio
    real = os.replace

    def replace(src, dst, *a):
        if str(dst).endswith("test.tex"):
            raise OSError("injected: rename failed")
        return real(src, dst, *a)

    monkeypatch.setattr(fileio.os, "replace", replace)
    with pytest.raises(OSError, match="injected"):
        host.insert_slides(deck, host.insert_positions(deck)[0], [("A", "a")], "en")
    assert_untouched(pctx, deck_bytes, slides, csv)


def test_a_deck_changed_at_the_commit_is_not_overwritten(host, pctx, state, monkeypatch):
    """The expected-text check is made at the moment of the replacement, not only before the slides are written."""
    deck, deck_bytes, slides, csv = state
    real = host_module.deck_editor.apply
    other = deck_bytes + b"%% edited elsewhere\r\n"

    def apply(path, expected, mutate):
        return real(path, expected, lambda t: (path.write_bytes(other), mutate(t))[1])

    monkeypatch.setattr(host_module.deck_editor, "apply", apply)
    with pytest.raises(plugin_api.StaleFileError):
        host.insert_slides(deck, host.insert_positions(deck)[0], [("A", "a")], "en")
    assert_untouched(pctx, other, slides, csv)


def test_legacy_settings_accessors(host, monkeypatch):
    from slidemage import app_settings
    from slidemage.plugins import migrate

    monkeypatch.setattr(migrate, "legacy_anthropic_key", lambda ctx: "old-key" if ctx is host.ctx else None)
    monkeypatch.setattr(app_settings, "get_ollama_host", lambda ctx: "http://old:11434")
    assert host.legacy_secret("anthropic_api_key") == "old-key"
    assert host.legacy_ollama_host() == "http://old:11434"
    with pytest.raises(ValueError):
        host.legacy_secret("other")


def test_progress_is_delivered_on_ui_thread_before_done(host, qapp):
    events = []
    main = threading.get_ident()

    def work(report):
        report("one")
        report("two")
        return 42

    host.run_in_background_with_progress(
        work, lambda value: events.append((value, threading.get_ident())),
        lambda result, error: events.append(((result, error), threading.get_ident())))
    wait_until(lambda: len(events) == 3)
    assert events == [("one", main), ("two", main), ((42, None), main)]


def test_model_choices_notification_delegates(host):
    seen = []
    host.model_choices_changed("ollama")
    host.ui = type("Ui", (), {"model_choices_changed": lambda self, route: seen.append(route)})()
    host.model_choices_changed("ollama")
    assert seen == ["ollama"]


def test_lazy_ai_exports():
    from slidemage import alt_draft, compiler
    from slidemage.ai import tasks

    assert plugin_api.Task is tasks.Task
    assert plugin_api.TRANSLATE is tasks.TRANSLATE
    assert plugin_api.check is tasks.check
    assert plugin_api.IMAGE_DESCRIPTION_SCHEMA is alt_draft.RESPONSE_SCHEMA
    assert plugin_api.DraftResult is alt_draft.DraftResult
    assert isinstance(plugin_api.CancelToken(), compiler.CancelToken)
    for name in ("answer_note", "repair_request", "translate_request", "SlideContext", "TranslationResult",
                 "build_prompt", "draft_from_fields", "effective_system_prompt", "ImageEntry", "en_text_hash",
                 "get_effective_prompt", "de_address", "glossary", "IMAGE_DESCRIPTION_RULES",
                 "CLAUDE_CODE_PRE_APPROVED", "Outcome", "PromptConfig", "FIX_LATEX", "UPDATE_TRANSLATION",
                 "PROOFREAD", "CONCISE", "TITLE", "NOTE", "SUMMARISE", "READABLE", "REWRITE", "REWRITE_PRESETS",
                 "PROOFREAD_SELECTION", "update_request", "proofread_request", "concise_request", "title_request",
                 "rewrite_request", "proofread_selection_request", "note_request", "summarise_request",
                 "fix_request", "readable_request"):
        assert getattr(plugin_api, name) is not None


def test_hook_context_without_window(host, monkeypatch):
    from slidemage import ai_review, alt_images, project, timing

    monkeypatch.setattr(project, "from_environment", lambda: host.ctx)
    hook = plugin_api.hook_context_from_environment()
    assert hook.root == host.ctx.root
    slide = host.ctx.slides_dir / "abc-EN-Hello-current.tex"
    assert hook.slide_kind(slide) == "current"
    assert hook.read_text(slide) == slide.read_bytes().decode("utf-8")
    hook.write_snapshot("../an opaque id", {"before": "a\r\nb"})
    assert hook.read_snapshot("../an opaque id") == {"before": "a\r\nb"}
    hook.delete_snapshot("../an opaque id")
    assert hook.read_snapshot("../an opaque id") == {}
    assert hook.is_deck(host.ctx.decks_dir / "test.tex")
    assert not hook.is_deck(slide)
    calls = []
    monkeypatch.setattr(alt_images, "is_store", lambda ctx, path: True)
    monkeypatch.setattr(alt_images, "flag_edited_sources", lambda ctx, path, before: True)
    monkeypatch.setattr(ai_review, "mark", lambda *args, **kwargs: calls.append((args, kwargs)))
    monkeypatch.setattr(ai_review, "inserted_slides", lambda *args: calls.append(args))
    monkeypatch.setattr(timing, "event", lambda *args: calls.append(args))
    assert hook.is_image_store(slide)
    assert hook.flag_edited_sources(slide, "before")
    hook.mark_review(slide, "edit", "plugin", before="old")
    hook.record_inserted_slides(slide, "old", "new", "plugin")
    hook.timing_event("prompt")
    assert calls[0] == ((host.ctx, slide, "edit", "plugin"), {"before": "old"})
    assert calls[1] == (host.ctx, slide, "old", "new", "plugin")
    assert calls[2] == (host.ctx.root, "prompt")


def test_route_task_lease_shares_core_slot_and_has_ownership(host, monkeypatch):
    from slidemage.ui.workspace.window import WorkspaceWindow
    from PySide6.QtWidgets import QMessageBox

    class Window:
        try_start_route_task = WorkspaceWindow.try_start_route_task
        end_route_task = WorkspaceWindow.end_route_task
        try_start_ollama_task = WorkspaceWindow.try_start_ollama_task
        end_ollama_task = WorkspaceWindow.end_ollama_task

        def __init__(self):
            self._route_tasks = {}
            self._legacy_ollama_owner = object()
            self._ollama_task_label = None

    window = Window()
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: None)
    host.ui = window
    assert window.try_start_ollama_task("drafting")
    assert host.acquire_route_task("ollama", "pulling") is None
    other = host.acquire_route_task("another", "working")
    assert other is not None
    window.end_ollama_task()
    lease = host.acquire_route_task("ollama", "pulling")
    assert lease is not None
    assert not window.try_start_ollama_task("drafting")
    window.end_ollama_task()  # cannot release another owner's lease
    assert host.acquire_route_task("ollama", "pulling") is None
    lease.release()
    lease.release()
    with other:
        assert host.acquire_route_task("another", "working") is None
    assert host.acquire_route_task("another", "working") is not None


def test_chat_surface_context_operations(host, monkeypatch):
    from types import SimpleNamespace
    from slidemage.ui.workspace.chat import plugin_surface

    calls = []
    class Signal:
        def connect(self, callback):
            self.callback = callback
        def emit(self, value):
            calls.append(("scope", value))
            if hasattr(self, "callback"):
                self.callback(value)
    class Scope:
        changed = Signal()
        def current(self):
            return "slide"
        def set_current(self, value):
            calls.append(("set", value))
    class Workspace:
        def __init__(self, app):
            pass
        def close(self):
            calls.append("closed")
        def show_slide(self, path):
            calls.append(("show", path))
    class Sync:
        def __init__(self, app, root):
            pass
        def _apply(self, changes):
            calls.append(("edits", changes))
    monkeypatch.setattr(plugin_surface, "GuiWorkspace", Workspace)
    monkeypatch.setattr(plugin_surface, "DiskSync", Sync)
    monkeypatch.setattr(plugin_surface.attachments, "place_file", lambda ctx, path, dash_spaces: "media/file")
    monkeypatch.setattr(plugin_surface.attachments, "save_image", lambda ctx, image: "media/image")
    monkeypatch.setattr(plugin_surface, "bubbles", lambda app: [])
    app = SimpleNamespace(ai_route=SimpleNamespace(open_setup=lambda: calls.append("setup")))
    state = SimpleNamespace(project=host.ctx, deck=None)
    context = plugin_surface.ChatSurfaceContext(app, state, Scope(), SimpleNamespace())
    assert context.project_root == host.ctx.root and context.scope() == "slide"
    context.on_scope_changed(lambda value: calls.append(("callback", value)))
    assert not context.set_scope("deck")
    state.deck = object()
    assert context.set_scope("deck")
    with pytest.raises(ValueError):
        context.set_scope("bad")
    context.open_ai_setup()
    assert context.attach_file(Path("file")) == "media/file"
    assert context.attach_image(object()) == "media/image"
    context.apply_external_edits("changes")
    assert context.tool_workspace() is context.tool_workspace()
    assert "nothing to translate" in context.translate_slide(Path("slide.tex"))
    context.close()
    assert calls == [("set", "deck"), ("scope", "deck"), ("callback", "deck"), "setup",
                     ("edits", "changes"), ("show", Path("slide.tex")), "closed"]


def test_builtin_terminal_uses_surface_context_for_deck_and_translation():
    from types import SimpleNamespace
    from slidemage.ui.workspace.terminal.view import ClaudeCodeView

    calls = []
    context = SimpleNamespace(set_scope=lambda scope: calls.append(scope) or True,
                              translate_slide=lambda path: f"translated {path.name}")
    view = SimpleNamespace(_surface_context=context)
    assert ClaudeCodeView._switch_to_deck(view) == "SlideMage is in Deck Mode now: go on with the request."
    assert calls == ["deck"]
    assert ClaudeCodeView._translate_slide(view, Path("slide.tex")) == "translated slide.tex"
    context.set_scope = lambda scope: False
    assert ClaudeCodeView._switch_to_deck(view) == "No deck is open in SlideMage: ask the user to open one."


def test_progress_error_is_delivered_after_reports(host, qapp):
    events = []
    def work(report):
        report("before failure")
        raise ValueError("failed")
    host.run_in_background_with_progress(work, events.append, lambda result, error: events.append((result, error)))
    wait_until(lambda: len(events) == 2)
    assert events[0] == "before failure"
    assert events[1][0] is None and isinstance(events[1][1], ValueError)


def test_cancel_token_stops_host_tools(host):
    cancel = plugin_api.CancelToken()
    cancel.request_stop()
    assert cancel.is_set()
    box = host.ai_tools(cancel=cancel)
    assert box is not None


def test_tool_workspace_is_unwrapped_for_tools(host, monkeypatch):
    from slidemage.ai import agent_toolbox
    from slidemage.ui.workspace.chat import plugin_surface

    core_workspace = object()
    handle = plugin_surface.ToolWorkspace.__new__(plugin_surface.ToolWorkspace)
    handle._workspace = core_workspace
    monkeypatch.setattr(agent_toolbox, "agent_toolbox", lambda workspace, *args: workspace)
    assert host.ai_tools(workspace=handle) is core_workspace


def test_chat_reserves_the_captured_route(host, monkeypatch, qapp):
    from types import SimpleNamespace
    from slidemage.ui.workspace.chat import session as chat_session

    class Window:
        def __init__(self):
            self.taken = {}
        def try_start_route_task(self, route, label, owner):
            if route in self.taken:
                return False
            self.taken[route] = owner
            return True
        def end_route_task(self, route, owner):
            if self.taken.get(route) is owner:
                del self.taken[route]
    class Thread:
        def __init__(self, *args):
            pass
        def start(self):
            pass
    monkeypatch.setattr(chat_session, "Agent", lambda *args, **kwargs: object())
    monkeypatch.setattr(chat_session, "_AgentThread", Thread)
    window = Window()
    workspace = SimpleNamespace(begin_request=lambda: None)
    session = chat_session.ChatSession(workspace, window)
    route = SimpleNamespace(route="plugin-local", is_local=True)
    assert session.start(object(), "hello", "slide", route)
    assert window.taken == {"plugin-local": session}
    session._release(route)()
    assert window.taken == {}


def test_chat_context_builds_fresh_tools_on_gui_and_exposes_full_focus(host, monkeypatch):
    from types import SimpleNamespace
    from slidemage.ui.workspace.chat import plugin_surface

    calls = []
    path = host.ctx.root / "slides" / "abc.tex"
    class Workspace:
        def __init__(self, window):
            pass
        def on_gui(self, work, default):
            calls.append("gui")
            return work()
        def begin_request(self):
            calls.append("begin")
        def context(self):
            return SimpleNamespace(path=path)
        def close(self):
            calls.append("close")
    monkeypatch.setattr(plugin_surface, "GuiWorkspace", Workspace)
    app = SimpleNamespace(centre=SimpleNamespace(path=path, is_dirty=lambda path: True))
    state = SimpleNamespace(project=host.ctx, focused_slide="abc", view="instructor", language="EN",
                            deck=SimpleNamespace(path=host.ctx.root / "decks/test.tex", is_test_deck=False))
    context = plugin_surface.ChatSurfaceContext(app, state, SimpleNamespace(), SimpleNamespace())
    monkeypatch.setattr(host, "ai_tools", lambda scope, **kwargs: (scope, kwargs))
    details = context.focus_details()
    assert (details.slide_id, details.slide, details.deck, details.view, details.language, details.dirty) == (
        "abc", path, state.deck.path, "instructor", "EN", True)
    cancel = object()
    scope, kwargs = context.build_tools(host, "deck", cancel)
    assert scope == "deck" and kwargs["focus_slide"] == path and kwargs["cancel"] is cancel
    assert kwargs["workspace"] is context.tool_workspace()
    assert calls == ["gui", "begin"]
    state.deck.is_test_deck = True
    assert context.focus_details().deck is None
    context.close()


def test_claude_surface_builds_from_public_host_and_context(host, qapp):
    from types import SimpleNamespace
    from slidemage.ui.kit.widgets import caption
    from slidemage.ui.workspace.terminal.view import ClaudeCodeView

    host.ui = SimpleNamespace(caption=caption, terminal_tokens=lambda: SimpleNamespace(info="#123456"))
    callbacks, closed = [], []
    context = SimpleNamespace(on_scope_changed=callbacks.append,
                              selected_route=lambda route, task: SimpleNamespace(label="Claude Code · Sonnet"),
                              close=lambda: closed.append(True))
    launch = SimpleNamespace(INSTALL_URL="https://example.org", find_claude=lambda: None)
    surface = ClaudeCodeView(host, context, launch, None, None, lambda: "hook")
    try:
        assert "Sonnet" in surface.caption.text()
        surface._started = True
        surface._open()
        assert surface.needs_setup and "not installed" in surface.setup_title.text()
        assert len(callbacks) == 1
    finally:
        surface.shutdown()
        surface.deleteLater()
    assert closed == [True]
