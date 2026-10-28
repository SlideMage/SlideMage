# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The agent loop of the chat (2026-10-10, UI redesign step 10a): send the conversation to a model,
stream its answer, run the tools it calls, send the results back, and repeat until it is done.

    agent = Agent(provider, workspace, on_event=ui_queue.put)
    agent.run(history, "Shorten the bullets on this slide", scope=SCOPE_SLIDE)   # on a worker thread
    agent.stop()                                                                  # from any thread

The loop knows no vendor and no widget. A provider (AgentProvider) turns the neutral history into
one streamed model turn; the tools (tools/) do the work; everything the UI needs arrives as events
(agent_types: TextDelta, ToolStarted, ToolFinished, EditProposed, EditApplied, EditRejected, and
Done last). Events and Workspace calls happen on the thread that runs run().

`history` belongs to the caller (the chat) and is extended in place, so a conversation continues by
calling run() again with the same list. It always stays valid for the API: a model turn that asked
for tools is followed by their results, even when Stop or an error ended the run in between, and a
request that got no answer at all is taken out again. One Agent per request: Stop is one-shot, like
the provider's abort().
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from .. import compiler
from . import agent_context, ai_profile, claude_scope
from .agent_types import (
    EDIT_ASK,
    AgentEvent,
    AgentMessage,
    AssistantMessage,
    Done,
    TextDelta,
    ToolFinished,
    ToolResult,
    ToolResultsMessage,
    ToolSpec,
    ToolStarted,
    UserMessage,
)
from .providers import Cancelled, ChatProvider, ProviderError
from .tools import Tool, ToolBox, build_toolbox
from .workspace import Workspace

MAX_TURNS = 25           # model turns per request: a runaway loop of tool calls ends here
MAX_TOKENS = 16000       # per model turn


class AgentProvider(ChatProvider, Protocol):
    """A provider that can run an agent turn (AnthropicProvider, OllamaProvider)."""

    def stream_turn(
        self, system: str, messages: list[AgentMessage], tools: list[ToolSpec],
        on_text: Callable[[str], None], *, max_tokens: int = ...,
    ) -> AssistantMessage:
        """One model turn over the neutral history: `on_text` gets the answer as it streams, the
        result holds the finished turn (text, tool calls, stop reason). Raises ProviderError;
        Cancelled once abort() was called."""


class Agent:
    def __init__(
        self, provider: AgentProvider, workspace: Workspace, *,
        on_event: Callable[[AgentEvent], None] = lambda _event: None,
        mode: str = EDIT_ASK, max_turns: int = MAX_TURNS, tools: list[Tool] | None = None,
    ) -> None:
        self.provider = provider
        self.workspace = workspace
        self.max_turns = max_turns
        self._on_event = on_event
        self._cancel = compiler.CancelToken()   # also what a compile_deck tool call is stopped by
        self._tools: ToolBox = build_toolbox(workspace, on_event, self._cancel, mode, tools=tools)
        self._usage: dict[str, int] = {}
        self._turns = 0

    @property
    def mode(self) -> str:
        return self._tools.ctx.mode

    @mode.setter
    def mode(self, value: str) -> None:
        """"ask" / "auto"; takes effect for the next edit, even in a run that is under way."""
        self._tools.ctx.mode = value

    def stop(self) -> None:
        """End the run as soon as possible, from any thread: the model request is cut off, a
        compile is killed, and run() finishes with Done("stopped"). A user's answer to an
        edit that waits for them is the workspace's to give (reject it when Stop is pressed)."""
        self._cancel.request_stop()
        self.provider.abort()

    def run(self, history: list[AgentMessage], request: str, scope: str = agent_context.SCOPE_SLIDE) -> Done:
        """Answer `request` (history is extended in place). Never raises: the last event, which
        is also the return value, says how it ended."""
        reason, message = "error", "The run was interrupted."      # what a BaseException leaves behind
        try:
            self._tools.ctx.scope = {agent_context.SCOPE_SLIDE: claude_scope.SLIDE,
                                     agent_context.SCOPE_DECK: claude_scope.DECK}.get(scope)
            self._tools.ctx.focus_slide = claude_scope.slide_focus(self._tools.ctx.root, self.workspace.context().path)
            reason, message = self._run(history, request, scope)
        except Cancelled:
            reason, message = "stopped", ""
        except ProviderError as exc:
            message = str(exc)
        except Exception as exc:  # noqa: BLE001 -- the chat must survive a bug in the loop
            message = f"Unexpected error: {type(exc).__name__}: {exc}"
        finally:        # the chat waits for Done to take the composer out of "running", whatever happened
            done = Done(reason, message, self._turns, dict(self._usage))
            self._on_event(done)
        return done

    # -- the loop -------------------------------------------------------------------------------

    def _run(self, history: list[AgentMessage], request: str, scope: str) -> tuple[str, str]:
        """(reason, message) of the end of the run; provider errors and Stop leave as exceptions."""
        self._preflight()
        asked = UserMessage(f"{agent_context.build_context(self.workspace, scope)}\n\n{request}", request)
        history.append(asked)
        try:
            return self._loop(history)
        finally:
            if history[-1] is asked:    # no answer was kept: a later request must not resend this one
                history.pop()

    def _loop(self, history: list[AgentMessage]) -> tuple[str, str]:
        while self._turns < self.max_turns:
            if self._cancel.is_set():
                return "stopped", ""
            self._turns += 1
            reply = self.provider.stream_turn(
                agent_context.SYSTEM_PROMPT, history, self._tools.specs,
                lambda text: self._on_event(TextDelta(text)), max_tokens=MAX_TOKENS)
            for name, value in reply.usage.items():
                self._usage[name] = self._usage.get(name, 0) + value
            if self._cancel.is_set():       # Stop came while the answer was streaming: its tools do not run
                return "stopped", ""
            if reply.stop == "max_tokens":
                return "error", "The answer was cut off at the model's length limit. Ask for a smaller step."
            if reply.stop == "refusal":
                return "error", "The model declined to answer this request."
            history.append(reply)
            if not reply.tool_calls:
                return "end_turn", ""
            results: list[ToolResult] = []
            history.append(ToolResultsMessage(results))
            try:
                self._run_tools(reply, results)
            finally:        # every tool call needs its result in the history, even if reporting one failed
                results += [ToolResult(call.id, "Not run: the request failed.", True)
                            for call in reply.tool_calls[len(results):]]
        return "max_turns", f"Stopped after {self.max_turns} steps without finishing. Say 'continue' to go on."

    def _run_tools(self, reply: AssistantMessage, results: list[ToolResult]) -> None:
        """Run the calls of `reply`, adding each result to `results` as soon as it exists."""
        for call in reply.tool_calls:
            if self._cancel.is_set():
                results.append(ToolResult(call.id, "Stopped by the user before this ran.", True))
                continue
            self._on_event(ToolStarted(call))
            result = self._tools.execute(call)
            results.append(result)
            self._on_event(ToolFinished(call, result))

    def _preflight(self) -> None:
        """Whether this provider may be used: the first cloud request in a project is confirmed once. Which
        provider answers was decided when the request was made (ai_profile.resolve); it never changes here."""
        if self.provider.is_local or ai_profile.cloud_seen(self.workspace.project):
            return
        if not self.workspace.confirm_cloud(self.provider):
            raise ProviderError("Nothing was sent: using a cloud model was not confirmed.")
        ai_profile.mark_cloud_seen(self.workspace.project)
