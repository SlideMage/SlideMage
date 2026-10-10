"""Stand-ins for the agent tests: a workspace with editor buffers and a scripted model."""
from __future__ import annotations

import itertools
from pathlib import Path

from slidemage.ai.agent_types import AssistantMessage, ToolCall
from slidemage.ai.providers import Cancelled, ProviderError
from slidemage.ai.workspace import Workspace, WorkspaceContext

_ids = itertools.count(1)


def call(name: str, **arguments) -> ToolCall:
    return ToolCall(f"toolu_{next(_ids)}", name, arguments)


def reply(text: str = "", *calls: ToolCall, stop: str | None = None) -> AssistantMessage:
    return AssistantMessage(text=text, tool_calls=list(calls),
                            stop=stop or ("tool_use" if calls else "end_turn"),
                            usage={"input": 100, "output": 10})


class FakeWorkspace(Workspace):
    """Editor buffers in a dict; answers `confirm_edit` as `approve` says; records what it was told."""

    def __init__(self, root: Path, context: WorkspaceContext | None = None, approve: bool = True) -> None:
        super().__init__(root, context)
        self.buffers: dict[Path, str] = {}
        self.dirty: set[Path] = set()
        self.read_only: set[Path] = set()
        self.approve = approve
        self.asked: list[tuple[Path, str, str]] = []
        self.changed: list[tuple[Path, str | None]] = []
        self.compiled: list[tuple[str, str]] = []
        self.compile_results = {"test": True}
        self.compile_log: list[str] = []
        self.consent = False
        self.before_confirm = None      # a hook run while an edit waits for the user

    def open(self, path: Path, text: str, dirty: bool = False) -> None:
        self.buffers[path] = text
        if dirty:
            self.dirty.add(path)

    def is_open(self, path):
        return path in self.buffers

    def is_dirty(self, path):
        return path in self.dirty

    def buffer_text(self, path):
        return self.buffers[path]

    def apply_to_buffer(self, path, expected_text, new_text):
        if path in self.read_only:
            return "it is read-only"
        if self.buffers[path] != expected_text:
            return "it changed while the edit waited"
        self.buffers[path] = new_text
        self.dirty.add(path)
        return None

    def confirm_edit(self, path, before, after):
        self.asked.append((path, before, after))
        if self.before_confirm:
            self.before_confirm()
        return self.approve

    def confirm_cloud(self, provider):
        return self.consent

    def file_changed(self, path, previous_text):
        self.changed.append((path, previous_text))

    def compile_deck(self, deck, kind, cancel, log):
        self.compiled.append((deck.name, kind))
        for line in self.compile_log:
            log(line)
        return self.compile_results


class ScriptedProvider:
    """A model that answers with the next scripted turn (an AssistantMessage, an exception to raise, or a
    function of the provider that returns one) and keeps what it was sent."""

    is_local = True
    model = "scripted"
    label = "scripted"

    def __init__(self, *script) -> None:
        self.script = list(script)
        self.sent: list[list] = []
        self.systems: list[str] = []
        self.tool_names: list[list[str]] = []
        self.aborted = False

    def stream_turn(self, system, messages, tools, on_text, *, max_tokens=0):
        self.sent.append(list(messages))
        self.systems.append(system)
        self.tool_names.append([t.name for t in tools])
        if self.aborted:
            raise Cancelled("Aborted.")
        step = self.script.pop(0)
        if callable(step):
            step = step(self)
        if isinstance(step, Exception):
            raise step
        for piece in (step.text[:len(step.text) // 2], step.text[len(step.text) // 2:]):
            if piece:
                on_text(piece)
        return step

    def abort(self):
        self.aborted = True

    def chat(self, *args, **kwargs):
        raise ProviderError("not used")
