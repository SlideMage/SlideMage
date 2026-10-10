"""One chat conversation: its history, the agent thread that answers a request, and which model answers.

`ChatSession.start()` runs one `Agent` (ai/agent.py) on a worker thread; everything the agent reports
arrives as the `event` signal on the GUI thread, `Done` last. The history list is extended by the agent
in place and stays valid after Stop or an error, so the conversation goes on with the next request.
"""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QObject, QThread, Signal

from .... import app_settings
from ....ai import credentials, resolver
from ....ai.agent import Agent
from ....ai.agent_types import EDIT_ASK, AgentEvent, AgentMessage, Done
from ....ai.providers import DEFAULT_ANTHROPIC_MODEL, ChatProvider
from ... import background
from .gui_workspace import GuiWorkspace

CLOUD = "anthropic"
LOCAL_ONLY_HINT = ("Local AI only is on, so the cloud model is off. Switch it off under Settings → Cloud, "
                   "or choose a local model.")
NO_KEY_HINT = "No Anthropic API key yet. Add one under Settings → Cloud."
NO_MODEL_HINT = "Choose a model for the chat under Settings → AI models → Chat assistant."


@dataclass(frozen=True)
class Route:
    """The model that answers the next request: its stored spec, the label to show, and why it cannot be
    used right now ("" if it can)."""
    spec: str
    label: str
    problem: str = ""


def current_route() -> Route:
    """Settings → AI models → "Chat assistant"; Claude while nothing is chosen but an API key is set."""
    spec = app_settings.default_model("chat")
    if not spec and credentials.get_api_key() is not None and not resolver.local_only():
        spec = f"{CLOUD}:{DEFAULT_ANTHROPIC_MODEL}"
    if not spec:
        return Route("", "no model chosen", NO_MODEL_HINT)
    name, model = app_settings.split_spec(spec)
    if name != CLOUD:
        return Route(spec, f"{model} · local")
    problem = LOCAL_ONLY_HINT if resolver.local_only() else NO_KEY_HINT if credentials.get_api_key() is None else ""
    return Route(spec, f"{model} · cloud", problem)


class _AgentThread(QThread):
    def __init__(self, agent: Agent, history: list[AgentMessage], request: str, scope: str) -> None:
        super().__init__()
        self.agent, self.history, self.request, self.scope = agent, history, request, scope

    def run(self) -> None:
        self.agent.run(self.history, self.request, self.scope)      # never raises; Done is its last event


class ChatSession(QObject):
    event = Signal(object)      # an AgentEvent, on the GUI thread

    def __init__(self, workspace: GuiWorkspace, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.workspace = workspace
        self.history: list[AgentMessage] = []
        self.mode = EDIT_ASK
        self._agent: Agent | None = None
        self._thread: _AgentThread | None = None
        self._closed = False
        self.event.connect(self._watch)     # first in line: the thread is released before the chat hears Done

    @property
    def running(self) -> bool:
        return self._thread is not None

    def start(self, provider: ChatProvider, request: str, scope: str) -> None:
        self.workspace.begin_request()
        self._agent = Agent(provider, self.workspace, on_event=self._emit, mode=self.mode)
        self._thread = _AgentThread(self._agent, self.history, request, scope)
        self._thread.start()

    def set_mode(self, mode: str) -> None:
        """"ask" / "auto"; a run under way takes it for its next edit."""
        self.mode = mode
        if self._agent is not None:
            self._agent.mode = mode

    def stop(self) -> None:
        """Stop the run; an edit that waits for the user is rejected."""
        if self._agent is not None:
            self._agent.stop()
        self.workspace.reject_pending()

    def new_chat(self) -> None:
        if not self.running:
            self.history.clear()

    def shutdown(self) -> None:
        """The window closes: end the run, release what waits for the GUI, and let the thread finish
        (background.stop_worker keeps it until it has, and the application waits for it at quit)."""
        self._closed = True
        self.workspace.close()
        thread, agent = self._thread, self._agent
        self._thread = self._agent = None
        if thread is not None:
            background.stop_worker(thread, agent.stop, wait_ms=500)

    def _emit(self, event: AgentEvent) -> None:
        """The agent's callback, on its thread."""
        if not self._closed:
            try:
                self.event.emit(event)
            except RuntimeError:       # this object is gone with the window
                pass

    def _watch(self, event: AgentEvent) -> None:
        if isinstance(event, Done) and self._thread is not None:
            thread, self._thread, self._agent = self._thread, None, None
            background.stop_worker(thread, wait_ms=500)
