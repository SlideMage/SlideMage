"""The chat in the right column: streaming, tool and diff cards, Apply / Reject / Undo against the real editor
buffers, Stop, closing mid-run, Local AI only, the palette row, and the Chat | Claude Code switch. The model
is scripted (agent_fakes); the project is a throwaway one, never example/."""
from __future__ import annotations

import threading
import time
from functools import partial

import pytest
from agent_fakes import ScriptedProvider, call, reply
from conftest import build_window, make_project, wait_until as _wait_until
from PySide6.QtCore import QPoint, QRect
from PySide6.QtWidgets import QApplication, QLabel, QMessageBox

from slidemage import app_settings, compiler
from slidemage.ai import credentials, resolver
from slidemage.ai.agent_types import EDIT_ASK, EDIT_AUTO, ToolCall
from slidemage.ai.providers import Cancelled
from slidemage.deck_scan import scan_decks
from slidemage.ui import layout_settings
from slidemage.ui.kit.widgets import PopoverMenu
from slidemage.ui.workspace import compile_actions
from slidemage.ui.workspace.chat import assistant as assistant_module
from slidemage.ui.workspace.chat import view as chat_view
from slidemage.ui.workspace.chat.assistant import CHAT, CLAUDE_CODE, AssistantArea
from slidemage.ui.workspace.chat.cards import AssistantText, DiffCard, Notice, ToolCard, UserBubble
from slidemage.ui.workspace.chat.format import diff_rows, summarize_call
from slidemage.ui.workspace.chat.session import current_route
from slidemage.ui.workspace.side_panels import PANEL_MIN_HEIGHT, SPLIT_SETTING
from slidemage.project import ProjectContext

SLIDE = "slides/abc-EN-Hello-current.tex"
EDIT = dict(path=SLIDE, old_text="First point", new_text="1st point")


wait_until = partial(_wait_until, seconds=10)


def pump(seconds=0.0):
    end = time.time() + seconds
    QApplication.processEvents()
    while time.time() < end:
        QApplication.processEvents()
        time.sleep(0.005)


@pytest.fixture
def env(qapp, tmp_path, monkeypatch):
    """The main window on a throwaway project, the chat set to a Claude model with a key, and every request
    answered by the provider the test scripts."""
    root = make_project(monkeypatch, tmp_path / "project")
    context = ProjectContext.at(root)
    monkeypatch.setenv(credentials.ENV_VAR, "sk-test")
    app_settings.set(context, "chat_model", "anthropic:claude-sonnet-5-5")
    window = build_window(monkeypatch, context)
    window.show()
    window.state.set_mode("source")     # no Preview render thread to outlive the test
    window.state.set_deck(next(d for d in scan_decks(window.project) if d.name == "test"))
    window.state.set_focused_slide("abc")
    providers = []
    monkeypatch.setattr(resolver, "provider_for", lambda _ctx, spec: providers.pop(0))

    class Env:
        pass

    e = Env()
    e.window, e.root, e.chat, e.providers = window, root, window.assistant.chat, providers
    e.path = root / SLIDE
    yield e
    e.chat.shutdown()


def script(env, *steps, label="scripted"):
    provider = ScriptedProvider(*steps)
    provider.label = label
    env.providers.append(provider)
    return provider


def ask(env, text="Do it"):
    env.chat.send(text)
    wait_until(lambda: not env.chat.session.running)
    pump()


def widgets(env, kind):
    layout = env.chat._messages
    return [w for i in range(layout.count()) if isinstance(w := layout.itemAt(i).widget(), kind)]


def open_buffer(env, dirty=False):
    env.window.open_slide_editor(env.path)
    file = env.window.centre.source.file_for(env.path)
    if dirty:
        file.editor.replace_selection("% typed\n")
    return file


def wait_for_card(env, state):
    wait_until(lambda: any(c.state == state for c in widgets(env, DiffCard)))
    pump()      # a widget added to a shown layout is shown a moment later
    return next(c for c in widgets(env, DiffCard) if c.state == state)


def blocked(_provider=None):
    """A model step that waits until the user presses Stop."""
    def step(p):
        while not p.aborted:
            time.sleep(0.005)
        raise Cancelled("Aborted.")
    return step


def test_the_right_column_split_is_saved_on_drag_and_restored_by_a_new_window(env, monkeypatch):
    env.window.resize(1280, 1000)
    pump()
    panels = env.window.side_panels
    panels.moveSplitter(400, 1)
    panel, assistant = panels.sizes()
    ratio = panel / (panel + assistant)
    assert layout_settings.get(SPLIT_SETTING) == ratio
    assert app_settings.get(env.window.project, SPLIT_SETTING) is None

    again = build_window(monkeypatch)
    again.resize(1280, 800)
    again.show()
    pump()
    sizes = again.side_panels.sizes()
    expected = max(PANEL_MIN_HEIGHT, min(sum(sizes) * ratio, sum(sizes) - again.assistant.minimumHeight()))
    assert sizes[0] == pytest.approx(expected, abs=1)
    again.resize(1280, 1000)
    pump()
    sizes = again.side_panels.sizes()
    assert sizes[0] == pytest.approx(sum(sizes) * ratio, abs=1)
    assert layout_settings.get(SPLIT_SETTING) == ratio


@pytest.mark.parametrize("theme", [None, False, True], ids=["native", "light", "dark"])
@pytest.mark.parametrize("scope", ["slide", "deck"])
@pytest.mark.parametrize("lines", [2, 6])
def test_at_640px_every_suggestion_is_reachable_without_scrolling_and_the_controls_fit(env, monkeypatch, theme, scope, lines):
    if theme is not None:
        env.window.theme.set_dark(theme)
        env.window.theme.apply()
    env.window.state.set_lint_errors(1)
    env.chat.scope.set_current(scope)
    env.chat._fill_empty()
    env.chat.composer.setPlainText("\n".join(["A line of the message"] * lines))
    env.window.resize(1280, 640)
    pump()
    chat, panels = env.chat, env.window.side_panels
    assert env.window.height() == 640
    assert panels.sizes()[0] >= PANEL_MIN_HEIGHT
    for control in (chat.scope, chat.composer, chat.mode_picker, chat.send_button):
        assert control.isVisible() and chat.rect().contains(control.geometry())
    assert chat._scroll.verticalScrollBar().maximum() == 0

    asked = []
    monkeypatch.setattr(chat, "ask", asked.append)
    expected = list(chat_view.SUGGESTIONS[scope])
    if scope == "slide":
        expected.insert(0, chat_view.FIX_SUGGESTION)
    if lines == 6 and scope == "slide":
        assert chat._suggestion_picker.isVisible()
    if chat._suggestion_picker.isVisible():
        assert chat._scroll.viewport().rect().contains(
            QRect(chat._suggestion_picker.mapTo(chat._scroll.viewport(), QPoint()), chat._suggestion_picker.size()))
        chat._suggestion_picker.clicked.emit()
        menu = next(m for m in chat.findChildren(PopoverMenu) if m.isVisible())
        assert [e[1] for e in menu._entries if e[0] == "item"] == expected
        menu.triggered.emit(expected[-1])
        menu.close()
    else:
        assert all(w.isVisible() for w in chat._suggestion_widgets)
        chat._suggestion_widgets[-1].click()
    assert asked == [expected[-1]]

    env.window.resize(1280, 1000)
    pump()
    assert not chat._suggestion_picker.isVisible()
    assert all(w.isVisible() for w in chat._suggestion_widgets)
    assert chat._scroll.verticalScrollBar().maximum() == 0


def test_a_six_line_input_and_send_row_fit_at_640px(env):
    env.window.resize(1280, 640)
    env.chat.route_note.setText("Choose a model before sending a message.")
    env.chat.route_note.show()
    env.chat.composer.setPlainText("\n".join(["A line of the message"] * 6))
    wait_until(lambda: env.chat.composer.geometry().bottom() < env.chat.mode_picker.geometry().top())
    chat, panels = env.chat, env.window.side_panels
    assert panels.sizes()[0] >= PANEL_MIN_HEIGHT
    assert chat.composer.isVisible() and chat.send_button.isVisible()
    assert chat.rect().contains(chat.composer.geometry()) and chat.rect().contains(chat.send_button.geometry())
    assert chat.composer.geometry().bottom() < chat.mode_picker.geometry().top()
    assert chat.composer.geometry().bottom() < chat.send_button.geometry().top()
    height = chat.composer.height()
    chat.composer.clear()
    wait_until(lambda: chat.composer.height() < height)


# -- the text of an answer, and the cards ---------------------------------------------------------

def test_the_answer_streams_into_the_list_with_the_provider_label(env):
    script(env, reply("All good, nothing to change."), label="claude-sonnet-5-5 · cloud")
    ask(env, "Check this slide")
    assert [w.raw for w in widgets(env, AssistantText)] == ["All good, nothing to change."]
    assert len(widgets(env, UserBubble)) == 1
    assert env.chat._empty.isHidden() and not env.chat.status.isVisible()
    assert env.chat.send_button.isVisible() and not env.chat.stop_button.isVisible()
    assert any(w.text() == "claude-sonnet-5-5 · cloud" for w in widgets(env, QLabel))     # who answers
    assert len(env.chat.session.history) == 2                                           # the request and the answer
    assert slot(env) is None


def test_tool_calls_become_cards_with_their_result_and_failures_open(env):
    script(env, reply("Looking.", call("read_file", path=SLIDE), call("read_file", path="nope.tex")), reply("Done."))
    ask(env)
    ok, bad = widgets(env, ToolCard)
    assert ok.call.name == "read_file" and "abc-EN-Hello" in summarize_call(ok.call)
    assert ok.result is not None and not ok.result.is_error and not ok.expanded
    ok.set_expanded(True)
    assert ok.expanded and "First point" in ok._body.text()
    assert bad.result.is_error and bad.expanded                  # a failure is shown at once
    assert [type(w).__name__ for w in widgets(env, (AssistantText, ToolCard))] == [
        "AssistantText", "ToolCard", "ToolCard", "AssistantText"]


def test_a_failed_request_ends_in_a_notice_not_a_crash(env):
    from slidemage.ai.providers import ProviderError
    script(env, ProviderError("Anthropic unreachable: boom"))
    ask(env)
    assert [n.text() for n in widgets(env, Notice)] == ["Anthropic unreachable: boom"]
    assert not env.chat.session.running


def test_a_local_model_answers_through_ollama_and_holds_the_slot(env):
    from fake_http import Server, ollama_ndjson

    from slidemage.ai.providers import OllamaProvider
    server = Server()
    server.content_type = "application/x-ndjson"
    server.script = [ollama_ndjson(["Looking."], [("read_file", {"path": SLIDE})]), ollama_ndjson(["Fine as is."])]
    try:
        app_settings.set(env.window.project, "chat_model", "ollama:qwen3")
        env.providers.append(OllamaProvider("qwen3", host=server.url))
        assert current_route(env.window.project).label == "qwen3 · local"
        ask(env)
        assert [type(w).__name__ for w in widgets(env, (AssistantText, ToolCard))] == [
            "AssistantText", "ToolCard", "AssistantText"]
        assert widgets(env, AssistantText)[-1].raw == "Fine as is." and not widgets(env, Notice)
        assert env.window._ollama_task_label is None
    finally:
        server.close()


# -- edits against the real buffers ---------------------------------------------------------------

def test_ask_mode_apply_edits_the_open_buffer_unsaved_and_undoably(env):
    file = open_buffer(env)
    script(env, reply("", call("edit_file", **EDIT)), reply("Changed."))
    env.chat.send("Rename the first point")
    card = wait_for_card(env, "asking")
    assert card.apply_button.isVisible() and card.reject_button.isVisible()
    assert "First point" in file.editor.text()                   # nothing happens before the answer
    card.apply_button.click()
    wait_until(lambda: not env.chat.session.running)
    pump()
    assert card.state == "applied" and card.undo_button.isVisible()
    assert "1st point" in file.editor.text() and file.dirty
    assert "First point" in env.path.read_text()                 # unsaved: the file on disk is as it was
    file.editor.undo()                                           # the user's own Ctrl+Z is one step
    assert "First point" in file.editor.text() and not file.dirty


def test_reject_leaves_the_buffer_and_tells_the_model(env):
    file = open_buffer(env)
    provider = script(env, reply("", call("edit_file", **EDIT)), reply("Understood."))
    env.chat.send("Rename the first point")
    wait_for_card(env, "asking").reject_button.click()
    wait_until(lambda: not env.chat.session.running)
    pump()
    card = widgets(env, DiffCard)[0]
    assert card.state == "rejected" and not card.undo_button.isVisible()
    assert "First point" in file.editor.text() and not file.dirty
    results = provider.sent[1][-1].results
    assert results[0].is_error and "rejected" in results[0].text


def test_auto_mode_applies_at_once_and_undo_takes_the_edit_back_from_the_buffer(env):
    file = open_buffer(env)
    env.chat._set_mode(EDIT_AUTO)
    script(env, reply("", call("edit_file", **EDIT)), reply("Changed."))
    ask(env)
    card = widgets(env, DiffCard)[0]
    assert card.state == "applied" and "1st point" in file.editor.text()
    card.undo_button.click()
    assert card.state == "undone" and "First point" in file.editor.text() and not file.dirty


def test_undo_refuses_when_the_text_changed_since(env):
    file = open_buffer(env)
    env.chat._set_mode(EDIT_AUTO)
    script(env, reply("", call("edit_file", **EDIT)), reply("Changed."))
    ask(env)
    file.editor.replace_selection("typed after")
    card = widgets(env, DiffCard)[0]
    card.undo_button.click()
    assert card.state == "applied" and "changed since" in card._caption.text()
    assert "1st point" in file.editor.text()


def test_a_closed_file_is_edited_on_disk_and_undone_there(env):
    other = env.root / "slides" / "abd-EN-Second-current.tex"      # not the slide shown: no buffer
    assert env.window.centre.source.file_for(other) is None
    env.chat._set_mode(EDIT_AUTO)
    script(env, reply("", call("edit_file", **{**EDIT, "path": "slides/abd-EN-Second-current.tex"})), reply("Changed."))
    ask(env)
    card = widgets(env, DiffCard)[0]
    assert "1st point" in other.read_text() and "Saved to the file" in card._caption.text()
    assert (env.root / "slides" / ".backups").is_dir()
    card.undo_button.click()
    assert card.state == "undone" and "First point" in other.read_text()


def test_a_new_file_has_no_undo(env):
    env.chat._set_mode(EDIT_AUTO)
    script(env, reply("", call("write_file", path="notes.txt", content="hello\n")), reply("Created."))
    ask(env)
    card = widgets(env, DiffCard)[0]
    assert (env.root / "notes.txt").read_text() == "hello\n"
    assert card._caption.text() == "Created" and not card.undo_button.isVisible()


def test_changing_the_permission_mid_run_reaches_the_agent(env):
    open_buffer(env)
    script(env, reply("", call("edit_file", **EDIT)), reply("Changed."))
    env.chat.send("go")
    wait_for_card(env, "asking")
    env.chat._set_mode(EDIT_AUTO)                               # takes effect for the next edit
    assert env.chat.session._agent.mode == EDIT_AUTO
    env.chat.stop()
    wait_until(lambda: not env.chat.session.running)


def test_the_permission_is_remembered(env):
    assert env.chat.session.mode == EDIT_ASK
    env.chat._set_mode(EDIT_AUTO)
    assert app_settings.get(env.window.project, "chat_edit_mode") == EDIT_AUTO
    area = AssistantArea(env.window, env.window.state)
    assert area.chat.session.mode == EDIT_AUTO and area.chat.mode_picker.text() == "Edit automatically"
    area.shutdown()


# -- Stop, closing, switching -----------------------------------------------------------------------

@pytest.mark.parametrize("local", [True, False], ids=["local", "cloud"])
def test_stop_ends_a_run_that_waits_for_the_model(env, monkeypatch, local):
    if not local:
        monkeypatch.setattr(resolver, "cloud_consent_given", lambda _ctx: True)
    script(env, blocked()).is_local = local
    env.chat.send("go")
    assert slot(env) == ("answering in the chat" if local else None)
    wait_until(lambda: env.chat.stop_button.isVisible())
    assert env.chat.status.isVisible()
    env.chat.stop_button.click()
    wait_until(lambda: not env.chat.session.running)
    pump()
    assert [n.text() for n in widgets(env, Notice)] == ["Stopped."]
    assert env.chat.send_button.isVisible()
    assert slot(env) is None


def test_stop_rejects_an_edit_that_waits_for_an_answer(env):
    file = open_buffer(env)
    script(env, reply("", call("edit_file", **EDIT)), reply("never asked"))
    env.chat.send("go")
    card = wait_for_card(env, "asking")
    env.chat.stop()
    # Regression (1c7e047): Stop settles the card immediately and rejects asks already on their way.
    assert card.state == "rejected" and not card.apply_button.isVisible() and not card.reject_button.isVisible()
    assert env.chat.workspace.confirm_edit("late", env.path, "a", "b") is False
    wait_until(lambda: not env.chat.session.running)
    pump()
    assert card.state == "rejected" and "First point" in file.editor.text()
    assert widgets(env, Notice)[-1].text() == "Stopped."
    env.chat.workspace.begin_request()                       # the next request asks again
    assert env.chat.workspace._stopping is False


def test_an_apply_that_cannot_be_carried_out_ends_the_card_and_tells_the_model(env):
    file = open_buffer(env)
    provider = script(env, reply("", call("edit_file", **EDIT)), reply("Understood."))
    env.chat.send("go")
    card = wait_for_card(env, "asking")
    file.editor.replace_selection("% typed while the edit waited\n")      # the buffer is not what the edit was made on
    card.apply_button.click()
    assert card.state == "working" and not card.apply_button.isVisible()
    wait_until(lambda: not env.chat.session.running)
    pump()
    assert card.state == "rejected" and "typed while" in file.editor.text()
    assert "was not changed" in provider.sent[1][-1].results[0].text


@pytest.mark.parametrize("waiting_for", ["edit", "model"])
def test_closing_the_window_mid_run_does_not_hang_and_releases_the_slot(env, waiting_for):
    if waiting_for == "edit":
        open_buffer(env)
        script(env, reply("", call("edit_file", **EDIT)), reply("never asked"))
    else:
        script(env, blocked())
    env.chat.send("go")
    if waiting_for == "edit":
        wait_for_card(env, "asking")
    else:
        wait_until(lambda: env.chat.stop_button.isVisible())
    started = time.time()
    env.window.close()
    assert time.time() - started < 5 and not env.chat.session.running
    assert slot(env) is None
    pump(0.2)


def test_switching_the_deck_stops_the_run(env):
    script(env, blocked())
    env.chat.send("go")
    wait_until(lambda: env.chat.stop_button.isVisible())
    env.window.state.set_deck(None)
    wait_until(lambda: not env.chat.session.running)
    pump()
    assert widgets(env, Notice)[-1].text() == "Stopped."


def test_new_chat_forgets_the_conversation(env):
    script(env, reply("One."))
    ask(env)
    assert env.chat.session.history and widgets(env, AssistantText)
    env.chat.new_chat()
    assert not env.chat.session.history and not widgets(env, AssistantText) and not env.chat._empty.isHidden()


# -- the model and Local AI only -------------------------------------------------------------------------

def test_local_ai_only_disables_the_cloud_model_with_a_hint(env):
    app_settings.set(env.window.project, "local_ai_only", True)
    env.chat.refresh_route()
    route = current_route(env.window.project)
    assert route.problem and "Local AI only" in env.chat.route_note.text() and not env.chat.route_note.isHidden()
    env.chat.send("go")
    assert not env.chat.session.running and not widgets(env, UserBubble)   # nothing was sent
    env.chat._open_route_menu()
    menu = next(w for w in QApplication.topLevelWidgets() if type(w).__name__ == "PopoverMenu" and w.isVisible())
    assert menu._rows and not any(row.isEnabled() for row in menu._rows[:-1])   # the cloud models; "More" stays
    menu.close()


def test_the_picker_lists_the_local_models_that_call_tools(env):
    env.chat._local_models = ["qwen3:8b", "llama3.1:8b"]
    app_settings.set(env.window.project, "chat_model", "ollama:old-model:7b")
    env.chat._open_route_menu()
    menu = next(w for w in QApplication.topLevelWidgets() if type(w).__name__ == "PopoverMenu" and w.isVisible())
    keys = [entry[1] for entry in menu._entries if entry[0] == "item"]
    assert keys[-4:] == ["ollama:old-model:7b", "ollama:qwen3:8b", "ollama:llama3.1:8b", "settings"]
    chosen = next(entry for entry in menu._entries if entry[1] == "ollama:old-model:7b")
    assert "cannot call tools" in chosen[3] and chosen[4] == "check"
    menu.close()
    env.chat._set_route("ollama:qwen3:8b")
    assert app_settings.default_model(env.window.project, "chat") == "ollama:qwen3:8b" and env.chat.route_chip.text() == "qwen3:8b · local"
    env.chat._set_route("anthropic:claude-opus-5-5")
    assert app_settings.default_model(env.window.project, "chat") == "anthropic:claude-opus-5-5"
    assert env.chat.route_chip.text() == "claude-opus-5-5 · cloud"


def test_while_a_run_is_going_the_model_and_the_scope_stay_as_they_are(env):
    script(env, blocked())
    env.chat.send("go")
    assert not env.chat.route_chip.isEnabled()
    env.chat.ask("Which slides have errors?", "deck")
    assert env.chat.scope.current() == "slide" and env.chat.composer.toPlainText() == "Which slides have errors?"
    env.chat.stop()
    wait_until(lambda: not env.chat.session.running)
    pump()
    assert env.chat.route_chip.isEnabled()


def test_only_one_question_to_ollama_about_local_models_is_out_at_a_time(env, monkeypatch):
    started = []
    monkeypatch.setattr(chat_view.background, "start_detached", started.append)
    env.chat._local_loader = None
    env.chat._load_local_models()
    env.chat._load_local_models()
    assert len(started) == 1
    env.chat._on_local_models(["qwen3:8b"])
    assert env.chat._local_models == ["qwen3:8b"]
    env.chat._load_local_models()
    assert len(started) == 2


def test_without_a_chosen_model_or_key_the_chat_says_what_to_do(env, monkeypatch):
    app_settings.save(env.window.project, {})       # no model, and no key in the settings file either
    monkeypatch.delenv(credentials.ENV_VAR)
    env.chat.refresh_route()
    assert "Chat assistant" in env.chat.route_note.text()
    env.chat.send("go")
    assert not env.chat.session.running


# -- the palette -------------------------------------------------------------------------------------------

def test_the_palette_row_opens_the_chat_and_sends_the_text(env):
    env.window.assistant.show_view(CLAUDE_CODE)
    script(env, reply("On it."))
    palette = env.window.palette
    palette.open()
    palette.input.setText("shorten the bullets")
    entry = palette._entries[-1]
    assert entry.label == "Ask the chat: “shorten the bullets”" and entry.enabled and entry.run is not None
    palette._run(len(palette._entries) - 1)
    wait_until(lambda: not env.chat.session.running)
    pump()
    assert env.window.assistant.current == CHAT and env.chat.scope.current() == "slide"
    assert len(widgets(env, UserBubble)) == 1 and widgets(env, AssistantText)[0].raw == "On it."


# -- the Ollama slot -------------------------------------------------------------------------------------

def slot(env):
    return env.window._ollama_task_label


@pytest.mark.parametrize("entry, text", [
    ("send", "go"), ("ask", "Make this slide more concise"),
], ids=["message", "suggestion"])
def test_a_busy_ollama_slot_keeps_the_chat_from_starting(env, monkeypatch, entry, text):
    warned = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warned.append(args[2]))
    assert env.window.try_start_ollama_task("drafting descriptions", ScriptedProvider())
    script(env, reply("never"))
    getattr(env.chat, entry)(text)
    assert not env.chat.session.running and not widgets(env, UserBubble) and env.chat.composer.toPlainText() == text
    assert "Drafting descriptions is already running" in warned[0]
    env.window.end_ollama_task()


def test_a_start_that_fails_gives_the_slot_back_and_leaves_the_chat_idle(env, monkeypatch):
    script(env, reply("never"))

    def broken():
        raise RuntimeError("no focus")

    monkeypatch.setattr(env.chat.workspace, "begin_request", broken)
    with pytest.raises(RuntimeError):
        env.chat.send("go")
    assert slot(env) is None and not env.chat.session.running and not env.chat.stop_button.isVisible()


def test_the_tools_menu_entry_opens_the_chat_on_this_slide_ready_to_type(env):
    env.window.assistant.show_view(CLAUDE_CODE)
    env.chat.scope.set_current("deck")
    env.window.focus_chat()
    assert env.window.assistant.current == CHAT and env.chat.scope.current() == "slide"
    assert not env.chat.session.running and not widgets(env, UserBubble)


# -- the switch ------------------------------------------------------------------------------------------------

def test_the_switch_is_remembered(env):
    area = env.window.assistant
    assert area.current == CHAT
    area.switch.changed.emit(CLAUDE_CODE)
    assert area.current == CLAUDE_CODE and app_settings.get(env.window.project, assistant_module.SETTING) == CLAUDE_CODE
    assert area._stack.currentWidget() is area._pages[CLAUDE_CODE] and not area.chat.isVisibleTo(area)
    again = AssistantArea(env.window, env.window.state)
    assert again.current == CLAUDE_CODE
    again.shutdown()


# -- the workspace of the window ----------------------------------------------------------------------------------

def on_thread(function):
    """Run `function` on a thread (like the agent) while the test keeps the GUI going."""
    box = {}
    thread = threading.Thread(target=lambda: box.update(result=function()), daemon=True)
    thread.start()
    wait_until(lambda: not thread.is_alive())
    return box["result"]


def test_the_workspace_answers_from_the_buffers(env):
    ws = env.chat.workspace
    file = open_buffer(env, dirty=True)
    assert on_thread(lambda: (ws.is_open(env.path), ws.is_dirty(env.path))) == (True, True)
    text = on_thread(lambda: ws.buffer_text(env.path))
    assert text == file.editor.text() and "typed" in text
    assert on_thread(lambda: ws.apply_to_buffer(env.path, "stale", "x")) == "it changed while the edit waited for your answer"
    assert on_thread(lambda: ws.apply_to_buffer(env.path, text, text + "% more\n")) is None
    assert file.editor.text().endswith("% more\n")
    other = env.root / "slides" / "abd-EN-Second-current.tex"
    assert on_thread(lambda: (ws.is_open(other), ws.apply_to_buffer(other, "", "x"))) == (False, "it is not open for editing")


@pytest.mark.parametrize("tool", ["read_buffer", "lint", "render_preview", "get_focus"])
@pytest.mark.parametrize("dirty", [False, True])
def test_mcp_checks_current_revision_before_disk_sync_polls(env, monkeypatch, tool, dirty):
    from conftest import SLIDE_TEXT
    from mcp_client import Client
    from slidemage import latex_lint, preview_target, slide_snapshot
    from slidemage.ai.mcp_server import McpServer
    from slidemage.ai.tools import CLAUDE_CODE_TOOLS, build_toolbox

    # Use the MCP handler directly: no terminal or DiskSync poll can absorb the write first.
    ws = env.chat.workspace

    def toolbox():
        ws.on_gui(ws.begin_request)
        return build_toolbox(ws, lambda _event: None, compiler.CancelToken(), tools=CLAUDE_CODE_TOOLS)

    file = open_buffer(env, dirty=dirty)
    before = file.editor.text()
    disk_text = SLIDE_TEXT.replace("\r\n", "\n").replace("First point", "Claude's new point") + "\\begin{itemize}\n"
    env.path.write_bytes(disk_text.replace("\n", "\r\n").encode())
    checked, reloaded = [], []
    real_lint, real_reload = latex_lint.lint_text, env.window.centre.disk_changed

    def lint(ctx, text, *args):
        checked.append(text)
        return real_lint(ctx, text, *args)

    def reload(path):
        assert threading.current_thread() is threading.main_thread()
        reloaded.append(path)
        return real_reload(path)

    monkeypatch.setattr(latex_lint, "lint_text", lint)
    monkeypatch.setattr(env.window.centre, "disk_changed", reload)
    monkeypatch.setattr(preview_target, "render_text", lambda target, text, *a, **k:
                        checked.append(text) or env.root / "fake.pdf")
    monkeypatch.setattr(slide_snapshot, "page_png", lambda *_args: b"PNG")
    server = McpServer(toolbox)
    client = Client(server)
    monkeypatch.setattr(client, "raw", lambda body: (200, server.handle(body)))
    args = {"path": SLIDE} if tool in ("read_buffer", "lint") else {}
    result = on_thread(lambda: client.call(tool, **args))
    assert not result.get("isError"), result
    text = result["content"][0]["text"]
    expected = before if dirty else disk_text
    assert file.editor.text() == expected and file.dirty == dirty
    assert env.path.read_bytes() == disk_text.replace("\n", "\r\n").encode()
    assert reloaded == ([] if dirty else [env.path])
    assert "editor (unsaved)" in text if dirty else "file" in text and "unsaved" not in text
    if tool == "read_buffer":
        assert "% typed" in text if dirty else "Claude's new point" in text
    else:
        assert expected in checked
    if tool in ("lint", "get_focus"):
        assert "never closed" in text if not dirty else "never closed" not in text


def test_the_context_is_the_focus_when_the_request_starts(env):
    open_buffer(env)
    env.chat.workspace.begin_request()
    context = env.chat.workspace.context()
    assert context.slide_id == "abc" and context.deck.name == "test" and context.path == env.path
    assert context.language == "EN" and context.view == "instructor"


def test_a_deck_the_agent_changed_goes_through_the_headers_and_the_slide_list(env, monkeypatch):
    edits = []
    monkeypatch.setattr(env.window, "after_deck_edit", lambda path, summary, previous_text=None: edits.append((path, summary)))
    deck = env.root / "decks" / "test.tex"
    on_thread(lambda: env.chat.workspace.file_changed(deck, "old"))
    assert edits and edits[0][0] == deck


def test_the_cloud_consent_is_the_windows_question(ctx, env, monkeypatch):
    asked = []
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kw: asked.append(args[2]) or QMessageBox.StandardButton.Yes)
    from slidemage.ai.providers import AnthropicProvider
    ws = env.chat.workspace
    assert on_thread(lambda: ws.confirm_cloud(AnthropicProvider("claude-sonnet-5-5"))) is True
    assert "cloud model (claude-sonnet-5-5 · cloud)" in asked[0]
    assert "rendered previews" in asked[0] and resolver.cloud_consent_given(env.window.project)


def test_a_compile_runs_through_the_windows_flow_and_reports_its_rows(env, monkeypatch):
    from types import SimpleNamespace
    from slidemage.compile_status import DONE, FAILED
    started = []

    def fake_compile(_window, jobs):
        started.append([job.jobname for job in jobs])
        env.window.log("==== compiling ====")
        run = SimpleNamespace(rows={"test-instructor": SimpleNamespace(state=DONE), "x": SimpleNamespace(state=FAILED)})
        env.window.compile.settled.emit(run)
        return True

    monkeypatch.setattr(compile_actions, "compile_jobs", fake_compile)
    deck = next(d for d in scan_decks(env.window.project) if d.name == "test")
    log = []
    results = on_thread(lambda: env.chat.workspace.compile_deck(deck, "instructor", compiler.CancelToken(), log.append))
    assert results == {"test-instructor": True, "x": False} and started and log == ["==== compiling ===="]


def test_the_chats_stop_ends_a_compile_without_asking(env, monkeypatch):
    stopped = []
    monkeypatch.setattr(compile_actions, "compile_jobs", lambda _window, jobs: True)
    monkeypatch.setattr(compile_actions, "stop_now", lambda _window: stopped.append(True))
    deck = next(d for d in scan_decks(env.window.project) if d.name == "test")
    cancel = compiler.CancelToken()
    box = {}
    thread = threading.Thread(target=lambda: box.update(r=env.chat.workspace.compile_deck(deck, "instructor", cancel, print)),
                              daemon=True)
    thread.start()
    pump(0.2)
    cancel.request_stop()
    wait_until(lambda: stopped)
    env.chat.workspace.close()                                  # the run never settles: the window closes
    wait_until(lambda: not thread.is_alive())
    assert box["r"] == {}


def test_a_tool_call_is_summarised_in_a_few_words():
    assert summarize_call(ToolCall("1", "read_file", {"path": "slides/a.tex"})) == "slides/a.tex"
    assert summarize_call(ToolCall("1", "list_slides", {})) == ""


def test_diff_rows_show_changes_with_two_lines_of_context_and_gaps(ctx):
    before = "\n".join(f"line {i}" for i in range(12))
    after = before.replace("line 5", "LINE 5\nextra")
    rows = diff_rows(before, after)
    assert rows[0] == ("gap", "") and rows[-1] == ("gap", "")
    assert [r for r in rows if r[0] in ("add", "del")] == [("del", "line 5"), ("add", "LINE 5"), ("add", "extra")]
    assert [r[1] for r in rows if r[0] == "ctx"] == ["line 3", "line 4", "line 6", "line 7"]
    assert diff_rows("", "a\n\tb") == [("add", "a"), ("add", "  b")]      # a new file; tabs shown narrow


@pytest.mark.parametrize("language", ["EN", "DE"])
@pytest.mark.parametrize("view", ["instructor", "after-course"])
def test_create_slide_shows_its_returned_preview_in_the_real_window(env, monkeypatch, language, view):
    import pymupdf
    from slidemage import preview_target
    from slidemage.ai.tools import build_toolbox

    env.window.state.set_view(view)
    workspace = env.chat.workspace
    workspace.begin_request()
    rendered = []
    def render(target, text, *args, **kwargs):
        rendered.append(target)
        pdf = env.root / "fake.pdf"
        with pymupdf.open() as doc:
            page = doc.new_page(width=320, height=180)
            page.insert_text((30, 30), "Created slide")
            doc.save(pdf)
        return pdf
    monkeypatch.setattr(preview_target, "render_text", render)
    box = build_toolbox(workspace, lambda _event: None, compiler.CancelToken(), EDIT_AUTO)
    result = on_thread(lambda: box.execute(call("create_slide", title="New", slug="New", deck="test",
        language=language, body="\\begin{standardframe}{New}\nContent.\n\\end{standardframe}\n")))
    assert not result.is_error, result.text
    path, = (env.root / "slides").glob(f"*-{language}-New-current.tex")
    pane = env.window.centre.preview
    assert env.window.state.focused_slide == path.name[:3]
    assert env.window.state.mode == "split" and env.window.state.language == language
    assert env.window.centre.path == path and pane._target.source_path == path
    assert not pane._page.pixmap.isNull() and pane._page.message == ""
    assert len(rendered) == 1 and result.images


@pytest.mark.parametrize("dirty", [False, True])
def test_modify_slide_uses_fresh_real_editor_snapshot(env, monkeypatch, dirty):
    from slidemage import ai_review, preview_target, slide_snapshot
    from slidemage.ai.tools import build_toolbox

    ws = env.chat.workspace
    file = open_buffer(env, dirty=dirty)
    before = file.editor.text()
    disk_text = env.path.read_text().replace("First point", "New disk point")
    env.path.write_bytes(disk_text.replace("\n", "\r\n").encode())
    rendered, published = [], []
    monkeypatch.setattr(preview_target, "render_text", lambda target, text, *a, **k:
                        rendered.append(text) or env.root / "fake.pdf")
    monkeypatch.setattr(slide_snapshot, "page_png", lambda *a: b"PNG")
    monkeypatch.setattr(ws, "show_slide", lambda path: None)
    monkeypatch.setattr(ws, "show_preview", lambda *args: published.append(args))
    expected = before if dirty else disk_text

    def run():
        ws.begin_request()
        box = build_toolbox(ws, lambda event: None, compiler.CancelToken(), EDIT_AUTO)
        return box.execute(call("modify_slide", slide="abc", expected=expected,
                                edits=[{"old": "Hello", "new": "Changed title"}]))

    result = on_thread(run)
    after = expected.replace("Hello", "Changed title")
    assert not result.is_error, result.text
    assert ("base: editor (unsaved)" if dirty else "base: file") in result.text
    assert file.editor.text() == after and file.dirty
    assert env.path.read_text() == disk_text
    assert rendered == [after] and published[0][1:3] == (after, b"PNG")
    assert ai_review.is_unreviewed(env.window.project, env.path)
    file.editor.undo()
    assert file.editor.text() == expected
