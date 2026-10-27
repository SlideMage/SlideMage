# SlideMage's AI tools

The tools are how an AI model acts on a SlideMage project: read slides, change them, preview them and manage
the deck. The same tools serve two assistants:

- **The built-in chat** (Anthropic or a local Ollama model). SlideMage runs the agent loop itself.
- **The embedded Claude Code** in the terminal pane. It gets SlideMage's tools over MCP and uses its own
  Read/Edit/Write for plain files.

Code: `src/slidemage/ai/tools/`. Each tool is a thin layer over a backend module the rest of the app already
uses (deck_outline, latex_lint, slide_add, preview_batch, bibliography, qr_code, compiler...). The tools do not
parse or write file formats themselves.

## How a tool is built

```python
@tool("lint", "Check a file with SlideMage's static LaTeX check ...",
      {"path": {"type": "string", "description": "A slide id (1y8) or a project path ..."}})
def lint(ctx: ToolContext, args: dict) -> str: ...
```

- **Spec.** A name, a description (what the model reads; it owns the details of arguments, defaults and
  results) and a JSON schema. `tools/base.py`.
- **Context.** `ToolContext` carries the project, the workspace (the window's state, or a headless one), an
  event callback, the user's Stop, the edit mode (ask/auto), the scope (Slide/Deck) and the focused slide.
  Each call gets its own copy.
- **Result.** Text for the model, optionally with images (PNG previews, PDF pages).
- **Errors.** A tool raises `ToolError` with a message that says what to do instead. `ToolBox.execute`
  never raises: argument errors, tool errors and bugs all come back to the model as an error result.
- **Argument check.** `check_arguments` validates the input recursively against the schema (types, enums,
  required, minLength, minItems, nested objects) before the tool runs. Model input is untrusted.

## Running a call

**Chat:** `ai/agent.py` sends the history and tool specs to the provider, runs the requested tools one after
another, appends the results and repeats, up to 25 turns. Events (`TextDelta`, `ToolStarted`, `EditProposed`,
`EditApplied`, `Done` ...) drive the chat UI. Stop cancels the model request and any running compile.

**Claude Code:** `ai/mcp_server.py` is a small loopback HTTP server (MCP, JSON-RPC). It binds to 127.0.0.1
only, uses a random port and a per-session bearer token, and checks the Host header. Each `tools/call` builds a
fresh toolbox from the window's current focus and scope (`ui/workspace/terminal/session.py`).

## The rules every write follows

- **Project only.** Paths are resolved (symlinks included) and must stay inside the project. Hidden folders
  (`.slidemage/`, `.build/`, `.git/` ...) and `pdf/` do not exist for the model. `tools/files.py`
- **Protected parts.** A slide's header comment, its `\setSlideVersion` line and `\vbox to 0pt{...}` blocks
  cannot be edited. Frozen versions (`-vX-Y-Z.tex`) are read-only.
- **Scope.** In "This slide" scope, writes to any other slide or deck file are refused, and so is adding a
  slide to the deck. The model is pointed to `switch_to_deck_mode`, which asks the user. One rule
  (`claude_scope.scope_problem`) serves both the tools and the Claude Code hook.
- **Buffer first.** A file open in the editor is read with its unsaved edits and changed in the buffer, as one
  undo step that the user saves. Other files are written with a backup and refused if they changed since
  they were read.
- **Review.** Every AI change marks the slide "Not reviewed" (`ai_review`).
- **Approval.** In the chat's "ask" mode each change is shown as a diff and waits for Apply. Claude Code asks
  through its own permission prompt for every tool that is not pre-approved.

For Claude Code's native Edit/Write/MultiEdit, `ai/claude_hook.py` (PreToolUse/PostToolUse) enforces the
protected parts and the scope, and records review marks. It cannot see what a Bash command does.

## Tool overview

Chat = built-in chat, CC = Claude Code. "Pre" = Claude Code runs it without asking
(`CLAUDE_CODE_PRE_APPROVED`).

### Reading and finding

| Tool | Chat | CC | What it does |
|---|:-:|:-:|---|
| `read_file` | ✓ | | Reads text with line numbers (editor buffer if open), a PDF as text or page images, or an image |
| `find_files` | ✓ | | Lists project files matching a glob |
| `search` | ✓ | | Finds text in slides, decks and the bibliography |
| `list_slides` | ✓ | Pre | Deck outline: sections, ids, titles, how each slide is called, lint and translation flags |
| `read_guide` | ✓ | Pre | Short guides on SlideMage's conventions (frames, layout, reveals, citations ...) |
| `get_focus` | | Pre | What the user is looking at: deck, slide, view, language, unsaved edits, lint errors |
| `read_buffer` | | Pre | A file as the editor has it, unsaved edits included |
| `read_selection` | | Pre | The text selected in the editor, with surrounding context |

### Checking and previewing

| Tool | Chat | CC | What it does |
|---|:-:|:-:|---|
| `lint` | ✓ | Pre | Static LaTeX check of a slide (braces, escapes, missing images or keys, layout rules) |
| `render_preview` | ✓ | Pre | Typesets a slide in one or all views and returns the images |
| `check_readability` | ✓ | Pre | Measures text size, contrast, overflow and density of a slide or a compiled deck. Changes nothing |
| `refresh_preview` | ✓ | Pre | Rerenders a slide's cached previews from the saved source, without returning images |
| `refresh_deck_previews` | ✓ | ✓ | Rerenders the cached previews of a whole deck (slow) |
| `compile_deck` | ✓ | | Builds the deck PDF and reports LaTeX errors with file and line (slow) |

### Changing slides and the deck

| Tool | Chat | CC | What it does |
|---|:-:|:-:|---|
| `modify_slide` | ✓ | ✓ | Changes a slide with exact replacements or full text. Checks, writes, marks for review, renders and shows it. A bare id follows the EN/DE switch; a path is used as given |
| `create_slide` | ✓ | ✓ | Creates a slide from a complete draft, inserts it into the open deck, renders and shows it. Rolls back on failure |
| `add_slide` | ✓ | ✓ | Creates a skeleton slide, or a linked translation copy to translate in place |
| `insert_slide` | ✓ | ✓ | Puts an existing slide into the open deck (after a given slide, or after its translation source) |
| `translate_slide` | | ✓ | Runs SlideMage's own translation (glossary, form of address, linked slide) |
| `make_qr_code` | ✓ | ✓ | Makes a QR code PDF in `media/` and returns the `\SMQRCode` call to put on a slide |
| `add_bib_entry` | ✓ | | Adds a sorted entry to `Slidemaster.bib` |
| `edit_file` | ✓ | | Replaces one exact piece of text in any project text file (Claude Code uses its own Edit) |
| `write_file` | ✓ | | Creates a new text file, never a slide and never overwriting (Claude Code uses its own Write) |

### Steering SlideMage

| Tool | Chat | CC | What it does |
|---|:-:|:-:|---|
| `show_slide` | | Pre | Brings a slide into focus so the user sees its preview and source |
| `switch_to_deck_mode` | | ✓ | Asks the user to widen the scope from "This slide" to the whole deck |

## Prompts

The tool descriptions say what each tool does. The prompts only describe the workflow: read before changing,
which tool for which job, what is slow, protected parts and answer style.

- Chat: `agent_context.SYSTEM_PROMPT`, plus a per-request context block with the focused slide or the deck
  outline.
- Claude Code: `claude_launch.ORIENTATION`, plus a `[SlideMage scope: ...]` line that the UserPromptSubmit
  hook adds before each prompt.

`tests/test_tool_guidance.py` fails when a prompt names a tool its assistant does not have.

## Adding a tool

1. Write the function with `@tool(...)` in the module that fits (`files`, `edits`, `slidemage`, `previews`,
   `readability`, `focus`), with a description that stands on its own.
2. Raise `ToolError` with an actionable message. Call `ctx.check_scope(path)` (or `ctx.check_scope()` for a
   deck change) before writing, and go through `propose()` and `write_text()` for changes.
3. Register it in `TOOLS` and/or `CLAUDE_CODE_TOOLS` in `tools/__init__.py`. Add it to
   `CLAUDE_CODE_PRE_APPROVED` only if it changes no project files.
4. Mention it in a prompt only if the workflow needs it. Add tests in `tests/test_agent_tools.py`, and
   `tests/test_mcp_server.py` if Claude Code gets it.
