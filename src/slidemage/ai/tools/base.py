"""The shape of an agent tool: a spec the model sees, a function that runs it, and
the context every function gets (2026-10-10, UI redesign step 10a)."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from ... import compiler
from ...project import ProjectContext
from ..agent_types import EDIT_ASK, AgentEvent, ToolCall, ToolResult, ToolSpec
from ..workspace import Workspace


class ToolError(Exception):
    """A tool cannot do what was asked; str(exc) goes back to the model as the (error) result,
    so it says what to do instead."""


@dataclass
class ToolContext:
    project: ProjectContext
    workspace: Workspace
    emit: Callable[[AgentEvent], None]
    cancel: compiler.CancelToken         # set by the user's Stop
    mode: str = EDIT_ASK                 # EDIT_ASK / EDIT_AUTO; the chat may flip it between calls
    call_id: str = ""                    # of the tool call being run

    @property
    def root(self) -> Path:
        """The project folder, resolved."""
        return self.project.root.resolve()


# What a tool function returns: the text for the model, or text plus images to look at.
ToolOutput = str | tuple[str, list[bytes]]


@dataclass(frozen=True)
class Tool:
    spec: ToolSpec
    run: Callable[[ToolContext, dict], ToolOutput]


def tool(name: str, description: str, properties: dict, required: tuple[str, ...] = ()):
    """Decorator: a `(ctx, args)` function becomes a Tool. `properties` maps an argument name to
    its JSON schema ({"type": "string", "description": ...})."""
    schema = {"type": "object", "properties": properties, "required": list(required),
              "additionalProperties": False}

    def wrap(function: Callable[[ToolContext, dict], ToolOutput]) -> Tool:
        return Tool(ToolSpec(name, description, schema), function)

    return wrap


_JSON_TYPES = {"string": str, "integer": int, "boolean": bool, "object": dict, "array": list}


def check_arguments(spec: ToolSpec, args: object) -> None:
    """Raise ToolError unless `args` fits the tool's schema (required, types, enums). The model's
    input is untrusted: a tool function can rely on this much."""
    if not isinstance(args, dict):
        raise ToolError("The arguments must be a JSON object.")
    properties = spec.schema["properties"]
    for name in spec.schema["required"]:
        if name not in args:
            raise ToolError(f"Missing required argument '{name}'.")
    for name, value in args.items():
        if name not in properties:
            raise ToolError(f"Unknown argument '{name}'. Known: {', '.join(properties)}.")
        wanted = properties[name].get("type")
        python_type = _JSON_TYPES.get(wanted)
        if python_type is not None and (
                not isinstance(value, python_type) or (wanted == "integer" and isinstance(value, bool))):
            raise ToolError(f"Argument '{name}' must be of type {wanted}.")
        if "enum" in properties[name] and value not in properties[name]["enum"]:
            raise ToolError(f"Argument '{name}' must be one of: {', '.join(properties[name]['enum'])}.")


class ToolBox:
    """The tools of one agent run, and what runs them."""

    def __init__(self, tools: list[Tool], ctx: ToolContext) -> None:
        self.ctx = ctx
        self._tools = {t.spec.name: t for t in tools}

    @property
    def specs(self) -> list[ToolSpec]:
        return [t.spec for t in self._tools.values()]

    def execute(self, call: ToolCall) -> ToolResult:
        """Run one call. Never raises: every failure is a result the model can read."""
        found = self._tools.get(call.name)
        if found is None:
            return ToolResult(call.id, f"There is no tool '{call.name}'. Tools: {', '.join(self._tools)}.", True)
        self.ctx.call_id = call.id
        try:
            check_arguments(found.spec, call.input)
            output = found.run(self.ctx, call.input)
        except ToolError as exc:
            return ToolResult(call.id, str(exc), True)
        except Exception as exc:  # noqa: BLE001 -- a bug in a tool must not end the chat
            return ToolResult(call.id, f"{call.name} failed unexpectedly: {type(exc).__name__}: {exc}", True)
        text, images = (output, []) if isinstance(output, str) else output
        return ToolResult(call.id, text, False, images)
