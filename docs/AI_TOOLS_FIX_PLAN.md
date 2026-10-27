# AI tools: fixes from the 2026-10-27 review

Status: plan, 2026-10-27. Needs the user's go per step; pause after each committed step.

Covers the agent tools in `src/slidemage/ai/tools/` and how the two front ends use them: the built-in chat
(`ai/agent.py`, `TOOLS`) and the embedded Claude Code (`ai/mcp_server.py`, `CLAUDE_CODE_TOOLS`, hooks in
`ai/claude_hook.py`). Each step is one commit with its tests; behaviour the user can see gets the usual
version bump and changelog line.

## Step 0 -- test environment (no commit)

The AI test modules do not import: `.venv` lacks `segno` (declared in pyproject.toml since the QR feature;
`tools/slidemage.py` imports `qr_code` at the top). Sync the venv, then record a baseline:

    .venv/bin/python -m pytest -q tests/test_agent_tools.py tests/test_mcp_server.py tests/test_claude_hook.py \
        tests/test_claude_scope.py tests/test_agent.py tests/test_readability_tool.py tests/test_claude_launch.py

## Step 1 -- enforce the Slide scope in the tools (review #1, high)

Today only the PreToolUse hook enforces "This slide", and only for Claude Code's native Edit/Write/MultiEdit.
Over MCP, `modify_slide`, `create_slide`, `add_slide` (and `make_qr_code`, which only writes media/) reach any
slide or deck; the built-in chat's scope is context text only.

- `ToolContext` gets `scope: str | None` and `focus_slide: Path | None` (None = no restriction, the default,
  so headless tasks and existing tests keep working).
- One rule, shared with the hook: move the decision of `claude_scope.edit_problem` into a function that takes
  (scope, root, focused slide, path) and returns the refusal text; the hook and the tools both call it.
- Tools that write check it before `propose`: `edit_file`, `write_file`, `modify_slide` (after the partner
  lookup, on the file actually written), `add_slide` and `create_slide` (a deck insert is outside Slide scope,
  so both refuse and point to `switch_to_deck_mode`).
- Wiring: `Agent.run(..., scope)` sets `ctx.scope`/`ctx.focus_slide` for the run; the terminal session's
  `_toolbox()` sets them from `self.scope` and the window's focus (as `publish_focus` does).
- Tests: each writing tool refused in Slide scope for another slide and allowed for the focused one; allowed in
  Deck scope; MCP end-to-end refusal through `tests/mcp_client.py`; hook behaviour unchanged.

## Step 2 -- `modify_slide` edits only the file it was given (review #2, high)

`modify_slide` follows the EN/DE switch to the linked partner even for an explicit path, so an edit meant for
`…-DE-…-current.tex` can land on the EN slide, and `expected` then fails with a misleading "changed since".

- Follow the partner only for a bare id (`1y8`); an explicit path is used as given.
- When the partner is followed, the result says so ("1y8 is shown in EN: changed its EN partner 2ab-EN-…").
- Update the `slide` argument description; tests for bare id, explicit path in either language, and `expected`
  against the redirected file.

## Step 3 -- one source of tool guidance (review #3, medium)

The system prompt (`agent_context.SYSTEM_PROMPT`) and the Claude Code `ORIENTATION` both re-describe tools and
have drifted from the tool descriptions (`refresh_deck_previews`: "all course views" in the tool, "legacy
Instructor snapshots (only)" in both prompts).

- Tool descriptions own what a tool does and its arguments; the prompts keep only workflow (read before you
  change, which tool for which job, when not to compile) and name tools without re-specifying them.
- Fix the `refresh_deck_previews` wording to what the code does (default `scope='all'`).
- Test: every `snake_case` tool name mentioned in either prompt exists in the matching tool list, so a renamed
  or removed tool cannot linger in a prompt.

## Step 4 -- argument checking one level deeper (review #4, medium)

`check_arguments` checks top-level types and enums only.

- Add `number` (int or float, not bool), `minLength`, `minItems`, and `items`/nested `properties`/`required`/
  `additionalProperties` for arrays of objects and objects (one recursive function; no new dependency).
- Remove the hand checks it replaces (`modify_slide`'s edit loop, `make_qr_code`'s height type); keep
  domain checks (height range, field names per kind).
- `add_bib_entry`/`make_qr_code` `fields`: values must be strings (`additionalProperties: {"type": "string"}`).
- Tests in `test_agent_tools.py` for each new rule and the error text the model sees.

## Step 5 -- one preview path (review #5, medium; investigate first)

After a write, `apply_slide` renders through `_render_preview` (slide's own language, single image, shows the
slide); `render_preview` goes through `preview_batch_output` (workspace language unless `saved`). The same
slide can be previewed differently.

- First check what `_render_preview` gives that the batch path does not (the `show_slide`, the occurrence key,
  the RuntimeError message); write it down in this step before changing code.
- Then give `preview_batch_output` an explicit `language` argument and a `show` flag, use it in `apply_slide`
  for the selected view, and delete `_render_preview`.
- Tests: the image after `modify_slide` and `render_preview` of the same slide use the same view and language.

## Step 6 -- slide-creation ergonomics (review #6, low; one decision for the user)

- `create_slide`: `deck` becomes optional (default: the open deck); a given name that is not the open deck is
  still refused.
- `add_slide` has three jobs (skeleton, translation copy, insert an existing slide). **Decision for the user:**
  split the insert job into its own `insert_slide(slide, after)` tool (clearer for the model; changes tool
  names in prompts, tests and the Claude Code permission list), or keep `add_slide` as is and only tighten its
  description.

## Step 7 -- small cleanups (review #7, low)

- Move `CLAUDE_CODE_READ_ONLY` to a name that says what it is (`CLAUDE_CODE_PRE_APPROVED`): it includes
  `refresh_preview`, which writes `.previews/`.
- `ToolBox.execute` logs `tool_end` for failed calls too (with `error=True`).
- `edits._not_frozen` becomes public (`not_frozen`); `slidemage.py` imports `protected_problem`/`slide_kind`
  from `slide_protection` directly, not via `edits`.
- `ToolBox.execute` passes the call id instead of mutating the shared `ctx.call_id` (a copy of the context per
  call), so parallel tool calls stay possible later.
