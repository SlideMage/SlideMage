"""The chat in the right column: streaming, tool and diff cards, Apply / Reject / Undo against the real editor
buffers, Stop, closing mid-run, Local AI only, the palette row, and the Chat | Claude Code switch. The model
is scripted (agent_fakes); the project is a throwaway one, never example/."""
from __future__ import annotations

import threading
import time

import pytest
from agent_fakes import ScriptedProvider, call, reply
from conftest import SLIDE_TEXT, build_window, make_project
from PySide6.QtWidgets import QApplication, QLabel, QMessageBox

from slidemage import app_settings, compiler
from slidemage.ai import credentials, resolver
from slidemage.ai.agent_types import EDIT_ASK, EDIT_AUTO, ToolCall
from slidemage.ai.providers import Cancelled
from slidemage.deck_scan import scan_decks
from slidemage.ui.workspace.chat import assistant as assistant_module
from slidemage.ui.workspace.chat import gui_workspace
from slidemage.ui.workspace.chat.assistant import CHAT, CLAUDE_CODE, AssistantArea
from slidemage.ui.workspace.chat.cards import AssistantText, DiffCard, Notice, ToolCard, UserBubble
from slidemage.ui.workspace.chat.format import diff_rows, summarize_call
from slidemage.ui.workspace.chat.session import current_route

SLIDE = "slides/abc-EN-Hello-current.tex"
LF = SLIDE_TEXT.replace("\r\n", "\n")
EDIT = dict(path=SLIDE, old_text="First point", new_text="1st point")


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


def pump(seconds=0.0):
    end = time.time() + seconds
    QApplication.processEvents()
    while time.time() < end:
        QApplication.processEvents()
        time.sleep(0.005)


def wait_until(condition, seconds=10):
    end = time.time() + seconds
    while not condition() and time.time() < end:
        QApplication.processEvents()
        time.sleep(0.005)
    assert condition()


@pytest.fixture
def env(qapp, tmp_path, monkeypatch):
    """The main window on a throwaway project, the chat set to a Claude model with a key, and every request
    answered by the provider the test scripts."""
    root = make_project(monkeypatch, tmp_path / "project")
    monkeypatch.setattr(gui_workspace, "PROJECT_ROOT", root)
    monkeypatch.setenv(credentials.ENV_VAR, "sk-test")
    app_settings.set("chat_model", "anthropic:claude-sonnet-5-5")
    window = build_window(monkeypatch)
    window.show()
    window.state.set_mode("source")     # no Preview render thread to outlive the test
    window.state.set_deck(next(d for d in scan_decks() if d.name == "test"))
    window.state.set_focused_slide("abc")
    providers = []
    monkeypatch.setattr(resolver, "provider_for", lambda spec: providers.pop(0))

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


def test_an_ollama_model_is_reported_as_not_usable_yet(env, monkeypatch):
    from slidemage.ai.providers import OllamaProvider
    app_settings.set("chat_model", "ollama:qwen3")
    env.providers.append(OllamaProvider("qwen3"))
    assert current_route().label == "qwen3 · local"
    ask(env)
    notice = widgets(env, Notice)[0].text()
    assert "qwen3 cannot be used for the chat yet" in notice and "Claude model" in notice


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
    assert app_settings.get("chat_edit_mode") == EDIT_AUTO
    area = AssistantArea(env.window, env.window.state)
    assert area.chat.session.mode == EDIT_AUTO and area.chat.mode_picker.text() == "Edit automatically"
    area.shutdown()


# -- Stop, closing, switching -----------------------------------------------------------------------

def test_stop_ends_a_run_that_waits_for_the_model(env):
    script(env, blocked())
    env.chat.send("go")
    wait_until(lambda: env.chat.stop_button.isVisible())
    assert env.chat.status.isVisible()
    env.chat.stop_button.click()
    wait_until(lambda: not env.chat.session.running)
    pump()
    assert [n.text() for n in widgets(env, Notice)] == ["Stopped."]
    assert env.chat.send_button.isVisible()


def test_stop_rejects_an_edit_that_waits_for_an_answer(env):
    file = open_buffer(env)
    script(env, reply("", call("edit_file", **EDIT)), reply("never asked"))
    env.chat.send("go")
    card = wait_for_card(env, "asking")
    env.chat.stop()
    wait_until(lambda: not env.chat.session.running)
    pump()
    assert card.state == "rejected" and "First point" in file.editor.text()
    assert widgets(env, Notice)[-1].text() == "Stopped."


def test_closing_the_window_mid_run_does_not_hang_and_releases_a_pending_confirm(env):
    open_buffer(env)
    script(env, reply("", call("edit_file", **EDIT)), reply("never asked"))
    env.chat.send("go")
    wait_for_card(env, "asking")
    started = time.time()
    env.window.close()
    assert time.time() - started < 5 and not env.chat.session.running
    pump(0.2)


def test_closing_the_window_while_the_model_is_still_answering(env):
    script(env, blocked())
    env.chat.send("go")
    wait_until(lambda: env.chat.stop_button.isVisible())
    started = time.time()
    env.window.close()
    assert time.time() - started < 5 and not env.chat.session.running
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
    app_settings.set("local_ai_only", True)
    env.chat.refresh_route()
    route = current_route()
    assert route.problem and "Local AI only" in env.chat.route_note.text() and not env.chat.route_note.isHidden()
    env.chat.send("go")
    assert not env.chat.session.running and not widgets(env, UserBubble)   # nothing was sent
    env.chat._open_route_menu()
    menu = next(w for w in QApplication.topLevelWidgets() if type(w).__name__ == "PopoverMenu" and w.isVisible())
    assert menu._rows and not any(row.isEnabled() for row in menu._rows[:-1])   # the cloud models; "More" stays
    menu.close()


def test_the_picker_stores_the_choice_in_the_chat_assistant_setting(env):
    env.chat._set_route("anthropic:claude-opus-5-5")
    assert app_settings.default_model("chat") == "anthropic:claude-opus-5-5"
    assert env.chat.route_chip.text() == "claude-opus-5-5 · cloud"


def test_without_a_chosen_model_or_key_the_chat_says_what_to_do(env, monkeypatch):
    app_settings.set("chat_model", "")
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


# -- the switch ------------------------------------------------------------------------------------------------

def test_the_switch_is_remembered_and_claude_code_is_a_placeholder(env):
    area = env.window.assistant
    assert area.current == CHAT
    area.switch.changed.emit(CLAUDE_CODE)
    assert area.current == CLAUDE_CODE and app_settings.get(assistant_module.SETTING) == CLAUDE_CODE
    assert area._stack.currentWidget() is area._pages[CLAUDE_CODE] and not area.chat.isVisibleTo(area)
    again = AssistantArea(env.window, env.window.state)
    assert again.current == CLAUDE_CODE
    again.shutdown()
    widget = QMessageBox()      # any widget will do for 10c's terminal
    area.set_view_widget(CLAUDE_CODE, widget)
    assert area._stack.currentWidget() is widget


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


def test_the_cloud_consent_is_the_windows_question(env, monkeypatch):
    asked = []
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kw: asked.append(args[2]) or QMessageBox.StandardButton.Yes)
    from slidemage.ai.providers import AnthropicProvider
    ws = env.chat.workspace
    assert on_thread(lambda: ws.confirm_cloud(AnthropicProvider("claude-sonnet-5-5"))) is True
    assert "cloud model (claude-sonnet-5-5 · cloud)" in asked[0]
    assert "rendered previews" in asked[0] and resolver.cloud_consent_given()


def test_a_compile_runs_through_the_windows_flow_and_reports_its_rows(env, monkeypatch):
    from types import SimpleNamespace
    from slidemage.compile_status import DONE, FAILED
    started = []

    def fake_compile(jobs):
        started.append([job.jobname for job in jobs])
        env.window.signals.log.emit("==== compiling ====")
        run = SimpleNamespace(rows={"test-instructor": SimpleNamespace(state=DONE), "x": SimpleNamespace(state=FAILED)})
        env.window.signals.run_settled.emit(run)
        return True

    monkeypatch.setattr(env.window, "_compile_jobs", fake_compile)
    deck = next(d for d in scan_decks() if d.name == "test")
    log = []
    results = on_thread(lambda: env.chat.workspace.compile_deck(deck, "instructor", compiler.CancelToken(), log.append))
    assert results == {"test-instructor": True, "x": False} and started and log == ["==== compiling ===="]


def test_the_chats_stop_ends_a_compile_without_asking(env, monkeypatch):
    stopped = []
    monkeypatch.setattr(env.window, "_compile_jobs", lambda jobs: True)
    monkeypatch.setattr(env.window, "stop_compilation_now", lambda: stopped.append(True))
    deck = next(d for d in scan_decks() if d.name == "test")
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
    assert summarize_call(ToolCall("1", "x", {"a": 1, "b": "two"})) == "a=1, b=two"
    assert summarize_call(ToolCall("1", "search", {"query": "w " * 60})).endswith("…")


def test_diff_rows_show_changes_with_two_lines_of_context_and_gaps():
    before = "\n".join(f"line {i}" for i in range(12))
    after = before.replace("line 5", "LINE 5\nextra")
    rows = diff_rows(before, after)
    assert rows[0] == ("gap", "") and rows[-1] == ("gap", "")
    assert [r for r in rows if r[0] in ("add", "del")] == [("del", "line 5"), ("add", "LINE 5"), ("add", "extra")]
    assert [r[1] for r in rows if r[0] == "ctx"] == ["line 3", "line 4", "line 6", "line 7"]
    assert diff_rows("", "a\n\tb") == [("add", "a"), ("add", "  b")]      # a new file; tabs shown narrow
    assert diff_rows("same", "same") == []
