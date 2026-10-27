# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The shape of an agent tool: a spec the model sees, a function that runs it, and
the context every function gets (2026-10-10, UI redesign step 10a)."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from ... import compiler, timing
from ...project import ProjectContext
from ..claude_scope import deck_problem, scope_problem
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
    scope: str | None = None             # None leaves tools unrestricted
    focus_slide: Path | None = None

    @property
    def root(self) -> Path:
        """The project folder, resolved."""
        return self.project.root.resolve()

    def check_scope(self, path: Path | None = None) -> None:
        """ToolError if writing `path` (None: changing the deck) is outside the scope."""
        problem = deck_problem(self.scope) if path is None else scope_problem(self.scope, self.root, self.focus_slide, path)
        if problem:
            raise ToolError(problem)


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


_JSON_TYPES = {"string": str, "integer": int, "number": (int, float), "boolean": bool, "object": dict, "array": list}


def check_arguments(spec: ToolSpec, args: object) -> None:
    """Raise ToolError unless `args` fits the tool's schema (required, types, enums, minLength, minItems, and
    the same for array items and nested objects). The model's input is untrusted: a tool function can rely on this much."""
    if not isinstance(args, dict):
        raise ToolError("The arguments must be a JSON object.")

    def check(value: object, schema: dict, path: str) -> None:
        wanted = schema.get("type")
        python_type = _JSON_TYPES.get(wanted)
        if python_type is not None and (
                not isinstance(value, python_type) or (wanted in ("integer", "number") and isinstance(value, bool))):
            raise ToolError(f"Argument '{path}' must be of type {wanted}.")
        if "enum" in schema and value not in schema["enum"]:
            raise ToolError(f"Argument '{path}' must be one of: {', '.join(str(v) for v in schema['enum'])}.")
        if isinstance(value, str) and "minLength" in schema and len(value) < schema["minLength"]:
            minimum = schema["minLength"]
            raise ToolError(f"Argument '{path}' needs at least {minimum} character{'s' if minimum != 1 else ''}.")
        if isinstance(value, list):
            if "minItems" in schema and len(value) < schema["minItems"]:
                minimum = schema["minItems"]
                raise ToolError(f"Argument '{path}' needs at least {minimum} item{'s' if minimum != 1 else ''}.")
            if "items" in schema:
                for index, item in enumerate(value):
                    check(item, schema["items"], f"{path}[{index}]")
        if isinstance(value, dict):
            properties = schema.get("properties", {})
            for name in schema.get("required", []):
                if name not in value:
                    child = f"{path}.{name}" if path else name
                    raise ToolError(f"Missing required argument '{child}'.")
            for name, item in value.items():
                child = f"{path}.{name}" if path else name
                if name in properties:
                    check(item, properties[name], child)
                else:
                    additional = schema.get("additionalProperties", True)
                    if additional is False:
                        raise ToolError(f"Unknown argument '{child}'. Known: {', '.join(properties)}.")
                    if isinstance(additional, dict):
                        check(item, additional, child)

    check(args, spec.schema, "")


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
        timing.event(self.ctx.root, "tool_start", tool=call.name)
        try:
            check_arguments(found.spec, call.input)
            output = found.run(self.ctx, call.input)
        except ToolError as exc:
            return ToolResult(call.id, str(exc), True)
        except Exception as exc:  # noqa: BLE001 -- a bug in a tool must not end the chat
            return ToolResult(call.id, f"{call.name} failed unexpectedly: {type(exc).__name__}: {exc}", True)
        text, images = (output, []) if isinstance(output, str) else output
        timing.event(self.ctx.root, "tool_end", tool=call.name)
        return ToolResult(call.id, text, False, images)
