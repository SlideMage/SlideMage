"""The assistant card of the right column (workspace v6, step 3): the body that follows the route, the header's four
rows (route, scope and target, the two task buttons, the running pill), New conversation for one route only, the
card that replaces the terminal while Claude Code cannot be used, and the caption under the terminal. The terminal runs
a stand-in for `claude` (fake_claude.py) and no model is called; the project is a throwaway one."""
from __future__ import annotations

import sys

import pytest
from agent_fakes import ScriptedProvider, reply
from test_claude_code_gui import env as claude_env, pump, use_claude_code, wait_until  # noqa: F401 -- a fixture
from test_claude_tasks_gui import BROKEN, LF, slide_file

from slidemage import app_settings
from slidemage.ai import ai_profile, claude_launch, credentials, resolver
from slidemage.ui.kit.widgets import Button
from slidemage.ui.workspace.terminal import view as view_module

pytest.importorskip("PySide6.QtWebEngineWidgets")
pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="the stand-in for claude is a POSIX script")

LOCAL, CLAUDE_CODE, API, CLOUD = ai_profile.LOCAL, ai_profile.CLAUDE_CODE, ai_profile.API, ai_profile.CLOUD
PROSE = LF.replace("First point", "This first point explains the main idea of the slide with enough ordinary words")


@pytest.fixture
def env(claude_env):  # noqa: F811
    """The window on a throwaway project, on Local, with the stand-in for `claude` found."""
    return claude_env


def area(env):
    return env.window.assistant


def header(env):
    return env.window.assistant.header


def shown(env) -> list[str]:
    """The labels of the task buttons on show, and All actions… last."""
    row = header(env)._actions
    return [row.itemAt(i).widget().text() for i in range(row.count()) if row.itemAt(i).widget().isVisibleTo(header(env))]


def go(env, mode, conn=None):
    ai_profile.mark_cloud_seen(env.window.project)
    env.window.state.set_ai_route(mode, conn)
    pump(0.05)


def refreshed(env):
    header(env).refresh_content()
    return header(env)


# -- the body ------------------------------------------------------------------------------------------------------

def test_the_body_follows_the_route_and_the_terminal_starts_only_on_claude_code(env):
    a = area(env)
    pump(0.2)
    assert a._stack.currentWidget() is a.chat and env.view.session is None and not env.log.exists()
    go(env, CLOUD, CLAUDE_CODE)
    assert a._stack.currentWidget() is a.claude_code
    wait_until(lambda: env.view.session is not None and env.view.session.running)
    go(env, CLOUD, API)
    assert a._stack.currentWidget() is a.chat
    go(env, LOCAL)
    assert a._stack.currentWidget() is a.chat
    assert env.view.session.running                  # the switch's session popup is what ends it (ai_route.py)


def test_leaving_claude_code_ends_the_session_and_coming_back_starts_a_new_one(env):
    go(env, CLOUD, CLAUDE_CODE)
    wait_until(lambda: env.view.session is not None and env.view.session.running)
    first = env.view.session._process
    env.window.ai_route.request(LOCAL)
    assert env.window.ai_route.popover_kind == "session"
    env.window.ai_route._popover.spec.actions[-1][2]()           # End session and switch
    assert env.window.state.ai_route == LOCAL and not env.view.session_live and not first.alive
    assert env.window.assistant._stack.currentWidget() is env.window.assistant.chat
    go(env, CLOUD, CLAUDE_CODE)
    wait_until(lambda: env.view.session_live and env.view.session._process is not first)
    assert env.view.status.text() == "Running"


def test_the_chat_has_no_scope_or_new_button_of_its_own(env):
    chat = area(env).chat
    assert chat.scope is area(env).scope and not hasattr(chat, "new_button")
    assert not any(b.toolTip().startswith("New chat") for b in chat.findChildren(Button))


# -- row 1: the route ----------------------------------------------------------------------------------------------

def test_the_header_names_each_route_and_what_its_conversation_runs_on(env, monkeypatch):
    monkeypatch.setenv(credentials.ENV_VAR, "sk-test")
    head = header(env)
    ai_profile.set_model_choice(env.window.project, LOCAL, ai_profile.CHAT, "qwen3:8b")
    ai_profile.set_model_choice(env.window.project, API, ai_profile.CHAT, "claude-sonnet-5-5")
    env.window.refresh_ai_models()
    assert head.title.text() == "Local · Ollama"
    assert head.subtitle.full_text() == "Chat with qwen3:8b · localhost:11434"
    assert head.route_icon.text() == "computer" and head.route_icon.property("tone") == "local"
    assert head.title.property("cloud") is False
    go(env, CLOUD, CLAUDE_CODE)
    assert head.title.text() == "Cloud · Claude Code"
    assert head.subtitle.full_text() == "Terminal · permissions are handled in Claude Code"
    assert head.route_icon.text() == "cloud" and head.route_icon.property("tone") == "cloud"
    assert head.title.property("cloud") is True
    go(env, CLOUD, API)
    assert head.title.text() == "Cloud · Anthropic API" and head.subtitle.full_text() == "Chat with claude-sonnet-5-5"
    go(env, LOCAL)
    assert head.subtitle.full_text().startswith("Chat with qwen3:8b")


def test_the_subtitle_without_a_chosen_local_model_and_with_another_host(env):
    app_settings.set_ollama_host(env.window.project, "http://ollama.test:8080/")
    env.window.refresh_ai_models()
    assert header(env).subtitle.full_text() == "Chat with no model chosen · ollama.test:8080"


def test_new_conversation_clears_the_chat_of_the_route_on_show_and_no_other(env, monkeypatch):
    monkeypatch.setenv(credentials.ENV_VAR, "sk-test")
    providers = [ScriptedProvider(reply("From the API.")), ScriptedProvider(reply("From Ollama."))]
    monkeypatch.setattr(resolver, "provider_for", lambda _ctx, _route: providers.pop(0))
    ai_profile.set_model_choice(env.window.project, LOCAL, ai_profile.CHAT, "qwen3:8b")
    chat = area(env).chat
    go(env, CLOUD, API)
    chat.send("one")
    wait_until(lambda: not chat.session.running)
    go(env, LOCAL)
    assert chat.session.history == []                            # nothing came over from the API chat
    chat.send("two")
    wait_until(lambda: not chat.session.running)
    assert len(chat.session.history) == 2
    header(env).new_button.click()                               # Local only
    assert chat.session.history == [] and not chat._empty.isHidden()
    go(env, CLOUD, API)
    assert len(chat.session.history) == 2 and chat._empty.isHidden()
    header(env).new_button.click()
    assert chat.session.history == []


def test_new_conversation_on_claude_code_starts_a_new_session(env):
    go(env, CLOUD, CLAUDE_CODE)
    wait_until(lambda: env.view.session is not None and env.view.session.running)
    first = env.view.session._process
    header(env).new_button.click()
    wait_until(lambda: env.view.session._process is not first and env.view.session.running)
    assert not first.alive


# -- row 2: the scope and its target ------------------------------------------------------------------------------

def test_the_scope_names_the_slide_with_its_title_and_the_not_saved_state_or_the_deck(env):
    head = refreshed(env)
    assert head.target.full_text() == "abc · Hello"
    area(env).scope._buttons["deck"].click()
    assert head.target.full_text() == "test · 2 slides"
    area(env).scope._buttons["slide"].click()
    slide_file(env).editor.set_read_only(True)                       # edits that cannot be written
    slide_file(env).editor.replace_all_text(LF + "% typed\n")
    wait_until(lambda: head.target.full_text() == "abc · Hello · not saved")
    slide_file(env).editor.undo()                                    # back to what is saved
    slide_file(env).editor.set_read_only(False)
    wait_until(lambda: head.target.full_text() == "abc · Hello")
    env.window.centre.open_file(env.root / "decks" / "test.tex")      # not a slide: the file's name
    wait_until(lambda: head.target.full_text() == "test.tex")
    env.window.state.set_focused_slide("abd")
    wait_until(lambda: head.target.full_text() == "abd · Second")


def test_the_scope_is_the_chats_and_the_terminals(env):
    a = area(env)
    a.scope._buttons["deck"].click()
    assert a.chat.scope.current() == "deck" and "whole deck" in a.chat._suggestion_widgets[0].text()
    go(env, CLOUD, CLAUDE_CODE)
    wait_until(lambda: env.view.session is not None and env.view.session.running)
    assert env.view.session.scope == "deck"
    a.scope._buttons["slide"].click()
    assert env.view.session.scope == "slide"


# -- row 3: the two task buttons and All actions… -----------------------------------------------------------------

def break_slide(env):
    slide_file(env).editor.replace_all_text(BROKEN)
    wait_until(lambda: "Fix LaTeX errors" in [b.label for b in header(env).offers("slide")])


def test_at_most_the_two_most_relevant_tasks_show_with_all_actions_last(env):
    go(env, CLOUD, CLAUDE_CODE)
    break_slide(env)
    wait_until(lambda: shown(env) == ["Translate to German", "Fix LaTeX errors", "All actions…"])
    assert len(header(env).offers("slide")) == 3                      # the title task is offered, but not shown
    slide_file(env).editor.replace_all_text(PROSE)
    wait_until(lambda: shown(env) == ["Translate to German", "Make more concise", "All actions…"])
    area(env).scope._buttons["deck"].click()
    wait_until(lambda: shown(env) == ["Translate missing slides (2)", "Summarise this deck", "All actions…"])


def test_only_the_tasks_the_route_can_run_are_offered(env):
    ai_profile.set_model_choice(env.window.project, LOCAL, ai_profile.TRANSLATION, "translategemma:12b")
    break_slide(env)
    wait_until(lambda: shown(env) == ["Translate to German", "All actions…"])         # Local cannot fix LaTeX
    ai_profile.set_model_choice(env.window.project, LOCAL, ai_profile.TRANSLATION, "")
    env.window.refresh_ai_models()
    wait_until(lambda: shown(env) == ["Check readability", "All actions…"])             # no translation model chosen: only the check
    go(env, CLOUD, CLAUDE_CODE)
    wait_until(lambda: shown(env) == ["Translate to German", "Fix LaTeX errors", "All actions…"])


def test_a_button_runs_the_task_through_the_task_runner(env, monkeypatch):
    go(env, CLOUD, CLAUDE_CODE)
    started = []
    monkeypatch.setattr(area(env).tasks, "start", lambda task, paths=(), title="": started.append((task.name, paths)))
    refreshed(env)
    next(b for b in header(env).findChildren(Button) if b.text() == "Translate to German").click()
    assert started == [("translate", ())]


def test_all_actions_opens_the_command_palette(env):
    palette = env.window.palette
    assert not palette.isVisible()
    next(b for b in header(env).findChildren(Button) if b.text() == "All actions…").click()
    assert palette.isVisible()
    palette.hide()


def test_every_offered_task_is_a_palette_command_and_a_refused_one_says_why(env, monkeypatch):
    shown_messages = []
    env.window.toast.show_message = shown_messages.append
    break_slide(env)
    commands = env.window.commands
    visible = [c.id for c in commands if c.id.startswith("task:slide:") and c.visible(env.window)]
    assert visible == ["task:slide:translate", "task:slide:fix_latex", "task:slide:title"]
    assert {c.title(env.window) for c in commands if c.id in visible} == {"Translate to German", "Fix LaTeX errors", "Better title"}
    fix = next(c for c in commands if c.id in visible and c.title(env.window) == "Fix LaTeX errors")
    assert commands.run(fix.id, env.window)                                # Local cannot run it: the card asks for setup
    card = area(env).tasks.card
    assert card.phase == "setup_needed" and "is not available on Local · Ollama" in card.note
    assert area(env)._stack.currentWidget() is area(env).task_card
    assert not area(env).tasks.busy and not shown_messages
    area(env).scope._buttons["deck"].click()
    assert [c.title(env.window) for c in commands if c.id.startswith("task:deck:") and c.visible(env.window)] \
        == ["Translate missing slides (2)", "Fix LaTeX errors (1 slides)", "Summarise this deck"]


# -- row 4: the running pill ----------------------------------------------------------------------------------------

def test_a_running_task_shows_its_pill_with_open_and_the_buttons_wait(env, tmp_path, monkeypatch):
    import json

    monkeypatch.setenv("FAKE_CLAUDE_LOG", str(tmp_path / "tasks.jsonl"))
    monkeypatch.setenv("FAKE_CLAUDE_REPLIES", json.dumps([{"answer": {"title": "T"}, "delay": 1.5}]))
    go(env, CLOUD, CLAUDE_CODE)
    head = refreshed(env)
    assert not head.pill.isVisibleTo(head)
    bubble = next(b for b in head.offers("slide") if b.label == "Better title")
    area(env).run_task(bubble)
    assert area(env)._stack.currentWidget() is area(env).task_card and not head.pill.isVisibleTo(head)
    assert shown(env) == ["All actions…"]
    area(env).task_card.back.click()                                  # Back to conversation: the card goes, its pill stays
    assert area(env)._stack.currentWidget() is area(env).claude_code
    assert head.pill.isVisibleTo(head) and head.pill.label.full_text() == "Better title · generating"
    assert shown(env) == ["All actions…"]
    head.pill.clicked.emit()                                          # Open
    assert area(env)._stack.currentWidget() is area(env).task_card and not head.pill.isVisibleTo(head)
    next(b for b in area(env).task_card.findChildren(Button) if b.text() == "Stop").click()
    wait_until(lambda: not area(env).tasks.busy)
    pump(0.1)
    assert area(env).tasks.card.phase == "stopped" and not head.pill.isVisibleTo(head)
    area(env).tasks.close_card()
    pump(0.1)
    assert "Translate to German" in shown(env)


# -- Claude Code: the card, the caption --------------------------------------------------------------------------------

def test_when_not_signed_in_an_amber_card_replaces_the_terminal_until_sign_in(env, monkeypatch):
    monkeypatch.setattr(claude_launch, "signed_in", lambda claude: False)
    go(env, CLOUD, CLAUDE_CODE)
    wait_until(lambda: env.view._stack.currentIndex() == view_module.SETUP)
    assert env.view.session is None and env.view.terminal is None and env.view.needs_setup
    assert env.view.setup_title.text() == "Claude Code is not signed in"
    assert env.view.setup_text.text() == ("Cloud stays selected. Nothing is sent and no other model is used until "
                                          "you sign in.")
    assert env.view.setup_button.text() == "Sign in…" and env.window.state.ai_route == CLAUDE_CODE
    refreshed(env)
    assert shown(env) == ["Check readability", "All actions…"]         # no task can run meanwhile (the check needs no AI)
    env.view.setup_button.click()                                      # Claude Code asks for its login in the terminal
    wait_until(lambda: env.view.session is not None and env.view.session.running)
    assert env.view._stack.currentIndex() == view_module.TERMINAL and not env.view.needs_setup


def test_an_unclear_answer_about_the_login_starts_the_terminal(env, monkeypatch):
    monkeypatch.setattr(claude_launch, "signed_in", lambda claude: None)          # an older Claude Code
    go(env, CLOUD, CLAUDE_CODE)
    wait_until(lambda: env.view.session is not None and env.view.session.running)


def test_without_the_claude_cli_the_card_says_so_and_offers_to_check_again(env, monkeypatch):
    monkeypatch.setattr(claude_launch, "find_claude", lambda: None)
    go(env, CLOUD, CLAUDE_CODE)
    wait_until(lambda: env.view.needs_setup)
    assert env.view.setup_title.text() == "Claude Code is not installed"
    assert "Nothing is sent and no other model is used" in env.view.setup_text.text()
    assert claude_launch.INSTALL_URL in env.view.setup_steps.text() and env.view.setup_button.text() == "Check again"
    monkeypatch.setattr(claude_launch, "find_claude", lambda: env.fake)
    env.view.setup_button.click()
    wait_until(lambda: env.view.session is not None and env.view.session.running)


def test_the_caption_under_the_terminal_names_the_models_of_the_task_buttons(env, monkeypatch):
    go(env, CLOUD, CLAUDE_CODE)
    caption = env.view.caption
    assert caption.text().startswith("Permissions are handled in Claude Code. Conversation model: set in Claude Code. "
                                     "Task buttons: Haiku · effort medium (")
    assert caption.text().endswith('<a href="setup">AI setup</a>).')
    opened = []
    monkeypatch.setattr(env.window.ai_route, "open_setup", lambda: opened.append(True))
    caption.linkActivated.emit("setup")
    assert opened == [True]
    ai_profile.set_model_choice(env.window.project, CLAUDE_CODE, ai_profile.FIXES, "sonnet:high")
    env.window.refresh_ai_models()
    assert "Task buttons: Sonnet · effort high (" in caption.text()


def test_the_terminal_has_no_bubble_strip_or_scope_of_its_own(env):
    assert not hasattr(env.view, "_bubble_row") and not hasattr(env.view, "more")
    assert env.view.scope is area(env).scope
