# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The real plugin host: folders, settings, background work, deck edits, render priority, window delegation."""
from __future__ import annotations

import json
import logging
import os
import threading
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from conftest import DECK_TEXT, make_project, wait_until
from slidemage import deck_scan, fileio, plugin_api
from slidemage.plugins import host as host_module
from slidemage.plugins.host import PluginHost, deck_snapshot, plugin_render_priority
from slidemage.plugins.loader import LoadedPlugin
from slidemage.plugins.manifest import read_manifest
from slidemage.plugins.registry import Contributions
from slidemage.project import ProjectContext
from slidemage.ui.workspace.window import WorkspaceWindow

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


def test_cache_dirs(host):
    cache = host_module.project.cache_dir()
    assert host.cache_dir() == cache / "plugins" / "hello"
    assert host.cache_dir().is_dir() and host.legacy_cache_dir() == cache


def test_settings_round_trip_and_atomic_save(host, pctx, monkeypatch):
    settings = host.settings()
    value = {"x": [1, "ä"]}
    path = host_module.project.config_dir() / "plugins" / "settings" / "hello.json"
    assert settings.get("a", 5) == 5
    settings.set("a", value)
    assert not path.exists()
    settings.save()
    assert PluginHost(host.manifest, pctx).settings().get("a") == value
    with pytest.raises(TypeError):
        settings.set("bad", object())

    def disk_full(*args):
        raise OSError("disk full")

    settings.set("a", 2)
    monkeypatch.setattr(os, "replace", disk_full)
    with pytest.raises(OSError, match="disk full"):
        settings.save()
    assert json.loads(path.read_text(encoding="utf-8")) == {"a": value}
    assert not list(path.parent.glob("*.tmp"))


def test_background_completion_delivers_result_and_error_on_gui_thread(host, qapp):
    main = threading.get_ident()
    got = []

    def fail():
        raise ValueError("nope")

    def done(result, error):
        got.append((result, error, threading.get_ident()))

    host.run_in_background(threading.get_ident, done)
    wait_until(lambda: got)
    worker, error, callback_thread = got.pop()
    assert worker != main and error is None and callback_thread == main
    host.run_in_background(fail, done)
    wait_until(lambda: got)
    result, error, callback_thread = got.pop()
    assert result is None and isinstance(error, ValueError) and callback_thread == main


def test_insert_slides_preserves_a_concurrent_registry_append(host, pctx, state, monkeypatch):
    deck, deck_bytes, slides, csv_before = state
    position = host.insert_positions(deck)[0]
    publish = fileio.write_text_exact
    csv = pctx.slide_ids_csv

    def publish_with_append(path, data, **kwargs):
        if path == csv:
            csv.write_bytes(csv_before + b'"xyz"\r\n')
        return publish(path, data, **kwargs)

    monkeypatch.setattr(fileio, "write_text_exact", publish_with_append)
    with pytest.raises(plugin_api.StaleFileError, match="Restored all files"):
        host.insert_slides(deck, position, [("A", "a")], "en")
    assert_untouched(pctx, deck_bytes, slides, csv_before + b'"xyz"\r\n')


def test_insert_refuses_an_id_that_appears_under_another_slug(host, pctx, monkeypatch):
    deck = snapshot(pctx)
    draw = host_module.slide_ids.draw_slide_id

    def draw_then_publish(occupied):
        bare = draw(occupied)
        (pctx.slides_dir / f"{bare.upper()}-EN-Elsewhere-current.tex").write_text("newer slide", encoding="utf-8")
        return bare

    monkeypatch.setattr(host_module.slide_ids, "draw_slide_id", draw_then_publish)
    with pytest.raises(plugin_api.StaleFileError, match="Slide ID already in use"):
        host.insert_slides(deck, host.insert_positions(deck)[0], [("A", "a")], "en")
    assert not list(pctx.slides_dir.glob("*-A-current.tex"))
    assert deck.path.read_bytes() == DECK_TEXT.encode()


def test_deck_edits_preserve_crlf_and_refuse_stale_snapshots(host, pctx, state):
    deck, _, slides, csv = state
    new = host.edit_deck_text(deck, lambda text: text.replace("Intro", "Start"))
    assert "Start" in new and "\r\n" in new and deck.path.read_bytes() == new.encode()

    def fail(text):
        raise ValueError("bad edit")

    with pytest.raises(ValueError, match="bad edit"):
        host.edit_deck_text(snapshot(pctx), fail)
    with pytest.raises(plugin_api.StaleFileError):
        host.insert_slides(deck, host.insert_positions(deck)[0], [("A", "a")], "en")
    with pytest.raises(plugin_api.StaleFileError):
        host.edit_deck_text(deck, lambda text: text + "x")
    assert_untouched(pctx, new.encode(), slides, csv)


def test_inserting_french_slides_preserves_deck_order_and_crlf(host, pctx):
    from slidemage import languages

    deck = snapshot(pctx)
    assert (deck.name, deck.text) == ("test", DECK_TEXT)
    position = host.insert_positions(deck)[1]
    assert position.label == "After 1. abc-EN-Hello"
    slides = [("Bonjour", r"\begin{frame}A\end{frame}"), ("Suite", "B")]
    assert host.project_languages() == ["en", "de"]
    with pytest.raises(ValueError, match="one of en, de"):
        host.insert_slides(deck, position, slides, "fr")
    languages.set_project_languages(pctx, "fr", ["en"])
    assert host.project_languages() == ["fr", "en"]
    french = snapshot(pctx)
    french.text = "\\decklanguage[fr]\n"
    assert host.deck_language(french) == "fr"

    first, second = host.insert_slides(deck, position, slides, "fr")
    assert first.name.endswith("-FR-Bonjour-current.tex") and second.name.endswith("-FR-Suite-current.tex")
    text = first.read_bytes().decode()
    assert text.startswith("%% Included in decks: (none)\r\n") and "\\setSlideVersion{1-0-0}\r\n" in text
    assert second.is_file()
    slugs = [path.name.removesuffix("-current.tex") for path in (first, second)]
    calls = [line for line in deck.path.read_bytes().decode().split("\r\n") if line.startswith("\\slide{")]
    assert calls == ["\\slide{abc-EN-Hello}", *(f"\\slide{{{slug}}}" for slug in slugs), "\\slide{abd-EN-Second}"]
    assert all(slug.split("-")[0] in pctx.slide_ids_csv.read_text() for slug in slugs)
    assert host.deck_slides(snapshot(pctx), "instructor", "fr")


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


def test_no_window(host, pctx):
    for call in (host.Page, lambda: host.Field("a", None), lambda: host.caption("a"),
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


def tex_files(pctx):
    return {p.name: p.read_bytes() for p in pctx.slides_dir.iterdir()}


# -- insertion rollback

def assert_untouched(pctx, deck_bytes, slides, csv):
    assert (pctx.decks_dir / "test.tex").read_bytes() == deck_bytes
    assert tex_files(pctx) == slides
    assert pctx.slide_ids_csv.read_bytes() == csv
    assert not list(pctx.decks_dir.glob("*.tmp"))


@pytest.fixture
def state(pctx):
    deck = snapshot(pctx)
    return deck, deck.path.read_bytes(), tex_files(pctx), pctx.slide_ids_csv.read_bytes()


@pytest.mark.parametrize("operation", ["fsync", "link"])
def test_a_failure_while_publishing_the_second_slide_rolls_back(host, pctx, state, monkeypatch, operation):
    deck, deck_bytes, slides, csv = state
    real = getattr(os, operation)
    calls = []

    def fail_second(*args):
        calls.append(args)
        if len(calls) == 2:
            raise OSError("injected: second slide")
        return real(*args)

    monkeypatch.setattr(os, operation, fail_second)
    with pytest.raises(OSError, match="injected: second slide"):
        host.insert_slides(deck, host.insert_positions(deck)[0], [("A", "a"), ("B", "b")], "en")
    assert_untouched(pctx, deck_bytes, slides, csv)


def test_a_partial_write_during_deck_commit_rolls_back(host, pctx, state, monkeypatch):
    deck, deck_bytes, slides, csv = state
    real_fdopen, publish = os.fdopen, fileio.atomic_write

    @contextmanager
    def fdopen(fd, mode):
        with real_fdopen(fd, mode) as handle:
            def write(data):
                handle.write(data[:9])
                handle.flush()
                raise OSError("injected: partial deck write")

            yield SimpleNamespace(write=write)

    def publish_with_fault(path, data, **kwargs):
        with monkeypatch.context() as patch:
            if path == deck.path:
                patch.setattr(os, "fdopen", fdopen)
            return publish(path, data, **kwargs)

    monkeypatch.setattr(fileio, "atomic_write", publish_with_fault)
    with pytest.raises(OSError, match="injected: partial deck write"):
        host.insert_slides(deck, host.insert_positions(deck)[0], [("A", "a")], "en")
    assert_untouched(pctx, deck_bytes, slides, csv)


def test_a_failed_rename_of_the_deck_keeps_the_deck(host, pctx, state, monkeypatch):
    deck, deck_bytes, slides, csv = state
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
    deck, deck_bytes, slides, csv = state
    publish = fileio.write_text_exact
    other = deck_bytes + b"%% edited elsewhere\r\n"

    def publish_with_outside_edit(path, text, **kwargs):
        if path == deck.path:
            path.write_bytes(other)
        return publish(path, text, **kwargs)

    monkeypatch.setattr(fileio, "write_text_exact", publish_with_outside_edit)
    with pytest.raises(plugin_api.StaleFileError):
        host.insert_slides(deck, host.insert_positions(deck)[0], [("A", "a")], "en")
    assert_untouched(pctx, other, slides, csv)


def test_model_choices_notification_delegates(host):
    seen = []
    host.model_choices_changed("ollama")
    host.ui = type("Ui", (), {"model_choices_changed": lambda self, route: seen.append(route)})()
    host.model_choices_changed("ollama")
    assert seen == ["ollama"]


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
    monkeypatch.setattr(ai_review, "media_snapshot", lambda ctx: {"media/a.png": [1, 2]})
    monkeypatch.setattr(ai_review, "mark_media_changes", lambda *args: calls.append(args) or [slide])
    assert hook.media_snapshot() == {"media/a.png": [1, 2]}
    assert hook.mark_media_changes({}, "plugin") == [slide]
    assert calls[3] == (host.ctx, {}, "plugin")
    assert calls[0] == ((host.ctx, slide, "edit", "plugin"), {"before": "old"})
    assert calls[1] == (host.ctx, slide, "old", "new", "plugin")
    assert calls[2] == (host.ctx.root, "prompt")


class RouteWindow:
    try_start_route_task = WorkspaceWindow.try_start_route_task
    end_route_task = WorkspaceWindow.end_route_task
    acquire_route_task = WorkspaceWindow.acquire_route_task

    def __init__(self):
        self._route_tasks = {}


@pytest.fixture
def route_window(host, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(QMessageBox, "warning", lambda *args: None)
    host.ui = RouteWindow()
    return host.ui


def test_route_task_lease_shares_core_slot_and_has_ownership(host, route_window):
    window = route_window
    core = window.acquire_route_task("ollama", "drafting")
    assert core is not None
    assert host.acquire_route_task("ollama", "pulling") is None
    other = host.acquire_route_task("another", "working")
    assert other is not None
    core.release()
    lease = host.acquire_route_task("ollama", "pulling")
    assert lease is not None
    assert window.acquire_route_task("ollama", "drafting") is None
    core.release()  # cannot release another owner's lease
    assert host.acquire_route_task("ollama", "pulling") is None
    lease.release()
    lease.release()
    with other:
        assert host.acquire_route_task("another", "working") is None
    assert host.acquire_route_task("another", "working") is not None


def test_route_lease_survives_a_detached_worker_stop_until_it_exits(host, route_window, qapp):
    from PySide6.QtCore import QThread
    from slidemage.ui import background

    class Worker(QThread):
        def run(self):
            gate.wait(5)

    lease = host.acquire_route_task("ollama", "drafting")
    gate = threading.Event()
    worker = Worker()
    background.start_detached(worker)
    try:
        assert not background.stop_worker(worker, wait_ms=10, on_done=lease.release)
        assert host.acquire_route_task("ollama", "updating") is None
        other = host.acquire_route_task("plugin-local", "working")
        assert other is not None
        other.release()
    finally:
        gate.set()
        worker.wait()
    wait_until(lambda: "ollama" not in host.ui._route_tasks)
    assert host.acquire_route_task("ollama", "updating") is not None


def test_chat_surface_context_operations(host, monkeypatch):
    from slidemage.ui.workspace.chat import plugin_surface

    callback = Mock()
    change = Mock()
    scope = SimpleNamespace(current=lambda: "slide", set_current=Mock(), changed=change)
    workspace = Mock()
    sync = Mock()
    monkeypatch.setattr(plugin_surface, "GuiWorkspace", Mock(return_value=workspace))
    monkeypatch.setattr(plugin_surface, "DiskSync", Mock(return_value=sync))
    monkeypatch.setattr(plugin_surface.attachments, "place_file", lambda ctx, path, dash_spaces: "media/file")
    monkeypatch.setattr(plugin_surface.attachments, "save_image", lambda ctx, image: "media/image")
    monkeypatch.setattr(plugin_surface, "bubbles", lambda app: [])
    app = SimpleNamespace(ai_route=SimpleNamespace(open_setup=Mock()))
    state = SimpleNamespace(project=host.ctx, deck=None)
    context = plugin_surface.ChatSurfaceContext(app, state, scope, SimpleNamespace())
    assert context.project_root == host.ctx.root and context.scope() == "slide"
    context.on_scope_changed(callback)
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
    change.connect.assert_called_once_with(callback)
    change.emit.assert_called_once_with("deck")
    scope.set_current.assert_called_once_with("deck")
    app.ai_route.open_setup.assert_called_once_with()
    sync._apply.assert_called_once_with("changes")
    workspace.show_slide.assert_called_once_with(Path("slide.tex"))
    workspace.close.assert_called_once_with()


@pytest.mark.parametrize("fail", [False, True], ids=["success", "error"])
def test_progress_is_delivered_on_gui_thread_before_completion(host, qapp, fail):
    events = []
    main = threading.get_ident()
    failure = ValueError("failed")

    def work(report):
        report("one")
        report("two")
        if fail:
            raise failure
        return 42

    host.run_in_background_with_progress(
        work, lambda value: events.append((value, threading.get_ident())),
        lambda result, error: events.append(((result, error), threading.get_ident())),
    )
    wait_until(lambda: len(events) == 3)
    outcome = (None, failure) if fail else (42, None)
    assert events == [("one", main), ("two", main), (outcome, main)]


def test_tool_workspace_is_unwrapped_for_tools(host, monkeypatch):
    from slidemage.ai import agent_toolbox
    from slidemage.ui.workspace.chat import plugin_surface

    core_workspace = object()
    handle = plugin_surface.ToolWorkspace.__new__(plugin_surface.ToolWorkspace)
    handle._workspace = core_workspace
    monkeypatch.setattr(agent_toolbox, "agent_toolbox", lambda workspace, *args: workspace)
    assert host.ai_tools(workspace=handle) is core_workspace


def test_chat_reserves_the_captured_route(route_window, monkeypatch, qapp):
    from slidemage.ui.workspace.chat import session as chat_session

    monkeypatch.setattr(chat_session, "Agent", lambda *args, **kwargs: object())
    monkeypatch.setattr(chat_session, "_AgentThread", lambda *args: SimpleNamespace(start=lambda: None))
    workspace = SimpleNamespace(begin_request=lambda: None)
    session = chat_session.ChatSession(workspace, route_window)
    route = SimpleNamespace(route="plugin-local", is_local=True)
    assert session.start(object(), "hello", "slide", route)
    assert set(route_window._route_tasks) == {"plugin-local"}
    session._take_release()()
    assert route_window._route_tasks == {}


def test_chat_context_builds_fresh_tools_on_gui_and_exposes_full_focus(host, monkeypatch):
    from slidemage.ui.workspace.chat import plugin_surface

    path = host.ctx.root / "slides" / "abc.tex"
    workspace = Mock()
    workspace.on_gui.side_effect = lambda work, default: work()
    workspace.context.return_value = SimpleNamespace(path=path)
    monkeypatch.setattr(plugin_surface, "GuiWorkspace", Mock(return_value=workspace))
    app = SimpleNamespace(centre=SimpleNamespace(path=path, is_dirty=lambda path: True, shown_slide=("abc", None)))
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
    assert [call[0] for call in workspace.method_calls] == ["on_gui", "begin_request", "context"]
    state.deck.is_test_deck = True
    assert context.focus_details().deck is None
    context.close()
    workspace.close.assert_called_once_with()


def test_log_takes_a_level_and_says_whether_debug_is_on(host, caplog, monkeypatch):
    from slidemage import diagnostics

    with caplog.at_level(logging.DEBUG, logger="slidemage.plugins"):
        host.log("plain")
        host.log("detail", level="debug")
        host.log("careful", level="warning")
        host.show_message("oops", error=True)
    assert [(r.name, r.levelname, r.getMessage()) for r in caplog.records] == [
        ("slidemage.plugins.hello", "INFO", "plain"), ("slidemage.plugins.hello", "DEBUG", "detail"),
        ("slidemage.plugins.hello", "WARNING", "careful"), ("slidemage.plugins.hello", "ERROR", "oops")]
    with pytest.raises(ValueError):
        host.log("x", level="loud")
    monkeypatch.setattr(diagnostics, "debug_enabled", lambda: True)
    assert host.debug_enabled() is True
