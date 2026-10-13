# AI route audit (workspace v6, step 1)

Spec: the handoff README `design_handoff_ai_switch_v6/README.md`, section 9.1: "list every AI dispatch path ... and send
each one through one resolver keyed by `ai_mode`, `cloud_conn` and `models`. The switch counts as done only when this
list has no gaps."

## The resolver

`ai/ai_profile.py` (pure, no Qt) holds the state and the one decision:

```
resolve(ctx, task, choice="") -> Route(route, task, model, effort)      # frozen; .is_local, .name, .label
```

`route` is `local` (Ollama), `claude_code` (the user's `claude`) or `api` (Anthropic API). It follows `ai_mode` (the
session's switch; `local` or `cloud`) and, in cloud, `cloud_conn`. `task` is one of the four rows of README section 2
"AI setup": `chat`, `image_description`, `translation`, `fixes_notes_transcripts`. `choice` is what a picker of that
route holds (it replaces the saved model for that one request). A request calls `resolve` once, when it starts, and
keeps the Route: flipping the mode later only changes new requests.

`ai/resolver.py` turns a Route into something that runs, or raises `RouteUnavailable` with the message to show:
`provider_for` (Local/API chat provider), `draft_backend`, `translation_backend` (the image pipeline),
`slide_translator` (slide text), `problem` (why a route cannot run its task now: no model chosen, no API key, the chat
of Claude Code), `not_offered` (the "not available on <route>" message). Nothing falls back: a Local route without a
model, an API route without a key, Claude Code without `claude`, and a task with no implementation on the route all
raise or report, and nothing is sent to another route or model ("It will not switch to another model on its own").

## Where each piece of state lives

| State | Where | Why |
|---|---|---|
| `ai_mode` | memory, `ai_profile._modes[project root]`; starts from `policy` the first time the project is asked | README: "the switch starts on this side when the project opens"; a default, not a lock |
| `policy` | `.slidemage/project.json` -> `"ai": {"policy": "local"/"cloud"}` | tracked with the project, like the old `ai.local_only`; everyone who opens a project that must stay local starts local |
| `cloud_conn` | `app_settings.json` key `cloud_conn` (default `claude_code`) | personal: it depends on what this person has installed or signed in to (Claude Code, an API key). It should not follow the project to a collaborator |
| `cloud_seen` | `app_settings.json` key `cloud_seen` (per project, the file sits in the project folder) | replaces `cloud_consent`, which reads as the same flag until the next write |
| `models[route][task]` | `app_settings.json` key `ai_models`: `{route: {task: choice}}` | choice = model name (Local, API) or `"<model>:<effort>"` (Claude Code) |

Defaults: a project without a policy is **Local** (nothing leaves the machine until someone says so; an older
`local_only: true` reads as `local`, an explicit `false` as `cloud`). `cloud_conn` defaults to Claude Code. Models:
Local has none until one is chosen (the pickers offer what is installed; translation preselects the built-in
fallback when it is installed), API defaults to `claude-sonnet-5-5`, Claude Code to `haiku:medium`
(`claude_runner.MODEL/EFFORT`, tested by the user as good enough), and the Claude Code chat has no model (it is the terminal's).

Migration, read side: the earlier `drafting_model`, `translation_model`, `chat_model` and `syntax_check_model`
("ollama:x", a bare name, or "anthropic:x") read as the Local and API models of the matching task until the first
`set_model_choice`, which moves them all into `ai_models` and deletes the old keys. Reading rewrites nothing.
`syntax_check` becomes `fixes_notes_transcripts`. The global `local_ai_only` setting is dropped (policy replaces it).

## Dispatch paths

Columns: what runs on each route today. "n/a" = no implementation on that route; invoked there it fails visibly with
"<thing> is not available on <route>: nothing was sent and no other route or model is used." (or the setup-needed
message), never silently on another route.

| # | Entry point (file:function) and UI trigger | Task | Local · Ollama | Cloud · Claude Code | Cloud · API | Resolved by |
|---|---|---|---|---|---|---|
| 1 | `ui/workspace/chat/view.py:ChatView.send` -> `ChatSession.start` -> `ai/agent.py:Agent`. Composer Send, suggestion buttons, palette "Ask the chat" (`window.ask_chat`), Source view "Ask AI" (`focus_chat`) | chat | `OllamaProvider` (tool-calling model) | n/a: the conversation is the terminal (path 2); Notice `CHAT_IN_TERMINAL`, nothing sent | `AnthropicProvider`; first use asks (`Agent._preflight`, `cloud_seen`) | `resolve(CHAT)` + `resolver.problem` + `provider_for` |
| 1b | `chat/view.py:_open_route_menu/_set_route` (model chip); palette entry label (`palette.py`) | chat | tool-calling Ollama models, saved as `models.local.chat` | disabled item "set in Claude Code" | API models, saved as `models.api.chat` | `resolve(CHAT)`, `set_model_choice(route.route, ...)` |
| 2 | `ui/workspace/terminal/view.py:ClaudeCodeView._spawn` -> `session.start`. The assistant body on Cloud · Claude Code | chat | n/a: the body is the native chat | the user's own `claude` in a terminal | n/a | shown only while `state.ai_route` is Claude Code (`assistant.py`) |
| 3 | `ui/pages/image_runs.py:_draft_slide`, `_draft_all`. Images page: Draft, Draft all | image_description | `alt_draft.ModelBackend` on Ollama (vision model) | `claude_images.ClaudeDraftBackend` (model, effort) | `ModelBackend` on `AnthropicProvider` | `picked_route(IMAGE_DESCRIPTION)` -> `resolver.draft_backend` |
| 4 | `ui/workspace/panels/images.py:_redraft`. Image descriptions panel: Redraft | image_description | as 3 | as 3 | as 3 | `task_route(IMAGE_DESCRIPTION)` -> `draft_backend` |
| 5 | `image_runs.py:_tune` -> `image_dialogs.PromptTuningSheet`. Images page: Tune prompt | image_description | `ModelBackend` with the edited system prompt | n/a: no Claude backend takes an edited prompt; dialog "not available on Cloud · Claude Code" | as 3 | `provider_from_combo` -> `provider_for` |
| 6 | `image_runs.py:_translate_image`, `_translate_all`. Images page: Translate, Translate all (the image fields) | translation | `ModelTranslationBackend` on Ollama | `claude_images.ClaudeTranslationBackend` | `ModelTranslationBackend` on the API | `picked_route(TRANSLATION)` -> `translation_backend` |
| 7 | `ui/dialogs/add_slide.py:_start_translation`. Add slide sheet "Translate the text with a model"; opened by the Language panel's Translate…, palette "Translate slide…" (`slide:translate`), the slide list's menu | translation | `slide_add.translate_body` on the Ollama provider | `claude_runner.SlideTranslator` (the Translate task, answer checked) | `translate_body` on the API provider | `picked_route(TRANSLATION)` -> `resolver.slide_translator` |
| 8 | `ui/workspace/ai_fix.py:AiFixPanel.run_check`. Source view: Ask AI to fix | fixes_notes_transcripts (was `syntax_check`) | `syntax_check.SyntaxChecker` on Ollama | n/a: its counterpart is path 9c (it edits the slide, this one lists line fixes); dialog "not available on Cloud · Claude Code" | `SyntaxChecker` on the API | `provider_from_combo(FIXES)` -> `provider_for` |
| 9a | `terminal/tasks.py:TaskRunner.start(TRANSLATE)`; bubble "Translate to German/English", deck bubble "Translate missing slides", MCP tool `translate_slide` | translation | `slide_add.translate_body` on Ollama, answer checked with `claude_tasks.check`, one at a time, Ollama slot held | `claude_runner.run_task` | as Local on the API provider | `TaskRunner.start` -> `resolve(KINDS[task])` |
| 9b | `TaskRunner.start(UPDATE_TRANSLATION)`; bubble "Update DE translation" | translation | n/a | `run_task` | n/a | `TaskRunner.refusal` |
| 9c | `TaskRunner.start(FIX_LATEX)`; bubble "Fix LaTeX errors" | fixes_notes_transcripts | n/a (the Local counterpart is path 8, a different operation) | `run_task` | n/a | `TaskRunner.refusal` |
| 9d | `TaskRunner.start(PROOFREAD / CONCISE / TITLE / NOTE / SUMMARISE)`; bubbles "Proofread", "Make more concise", "Better title", "Add speaker notes", "Summarise this deck" | fixes_notes_transcripts | n/a | `run_task` | n/a | `TaskRunner.refusal` |
| 9e | `TaskRunner.start(DESCRIBE)`; bubble "Describe images (n)" | image_description | `alt_draft.run_batch` with `ModelBackend` | `run_batch` with `ClaudeDraftBackend` | `run_batch` with `ModelBackend` (API) | `resolver.draft_backend` |
| 9f | `TaskRunner.start(claude_images.TRANSLATE)`; bubble "Translate image descriptions (n)" | translation | `run_translation_batch` with `ModelTranslationBackend` | with `ClaudeTranslationBackend` | with `ModelTranslationBackend` (API) | `resolver.translation_backend` |

Other places checked, with no AI dispatch of their own:

* Notes and transcripts: the Speaker notes and Transcript entry panels, `transcript.py` and the transcript preview send
  nothing to a model. Notes are written by path 9d (NOTE) or by the chat's tools (path 1). `draft_prompts.py` and
  `translation_prompts.py` are prompt stores read by paths 3-7; `image_review.py` and `alt_images.py` are stores.
* Palette and command registry (`ui/commands.py`, `workspace/actions.py`, `workspace/palette.py`): the only AI entries
  are "Ask the chat" (path 1) and "Translate slide…" (path 7).
* Settings -> Ollama (`settings_ollama.py`, `ai/ollama_admin.py`) lists, pulls and deletes models on the Ollama server;
  it sends no user content and is not a request on a route. The model lists of the pickers and of Settings only read
  names; the API's live list is asked only while the API is the route in use.
* `ai/mcp_server.py`, `ai/claude_hook.py`: serve the terminal of path 2; they make no model request.

## What "not available" looks like

| Where | Shown as |
|---|---|
| Chat, any route that cannot answer | a red Notice in the conversation, and the note under the composer (`resolver.problem`) |
| Pickers (Images page, Add slide, Ask AI to fix, Redraft, Tune) | a critical message box with the route's name; the picker lists only the active route's models |
| Terminal bubbles | the task row's status line (warning), also returned to Claude Code for `translate_slide` |

No path asks one route and answers from another. Consent: the first cloud request in a project (any cloud route, any
path that has a dialog parent) asks once, `ai_models.confirm_if_new`, and sets `cloud_seen`.

## Gaps

Deliberately left for later steps:

* **The Claude Code terminal (path 2)** is done (step 3): the assistant card (`ui/workspace/assistant.py`) shows it
  only while the route is Cloud · Claude Code and starts it when it is first shown there; leaving the route ends it
  (the switch's session popup asks first) and coming back starts a new one. When `claude` is missing or `claude auth
  status` says it is signed out, an amber card replaces the terminal and nothing is sent. The terminal keeps its own
  model ("Conversation model: set in Claude Code"; `build_command` passes no `--model/--effort`). The task buttons
  (paths 9a-9f) are the assistant header's two most relevant tasks the route can run, and every task is a palette
  command (`task:<scope>:<name>`); both go through `TaskRunner.refusal`, which now also refuses Claude Code tasks when
  `claude` is not installed. The terminal's own bubble strip is gone.
* **Changing the mode** is done (step 2): the top-bar switch, its popovers and AI setup (`ui/workspace/ai_switch.py`,
  `ai_route.py`, `ai_popups.py`, `ai_setup.py`). Every move, from the switch, the palette ("Use Local AI", "Use Cloud
  AI") or AI setup's cloud connection, is `AiRoute.request`: busy work (`WorkspaceWindow.running_ai_work`, built from
  `RunningWork` items of Claude Code tasks and batches, a streaming chat answer, an Images page run, Ask AI to fix,
  and the Ollama slot when none of those holds it), the Claude Code session, the policy warning, the first-use
  question, then the commit. The Add slide translation and the prompt-tuning request run inside modal sheets, so the
  switch cannot be moved while they run (their Ollama slot is still counted). Settings no longer holds a route
  selector, "Cloud means" or "This project".
* **Pickers** are refilled on every commit, default change and change of the installed models
  (`WorkspaceWindow.refresh_ai_models`: chat chip, Images page, Ask AI to fix in every open file); the Add slide
  sheet fills its picker when it opens (it is modal). The Ollama list is the cached, threaded
  `ui/ai_models.LocalModelList`. A pick that Claude Code does not offer is ignored (it falls back to Claude Code's
  saved choice), never sent to another route.
* **Per-route composer drafts and chat history** are kept in memory by the chat (`chat/route_chat.py`, swapped by
  `ChatView.show_route` on `state.ai_route_changed`); the unified assistant (step 3) shows the route's own. The chat's model chip picks a model for
  that chat only (kept per route, forgotten by New conversation); the default stays AI setup's. Task cards and
  their route label (`Route.label` is ready for them), the batch result panel and the dialog badge: steps 3-7.
* **Review marks** (`ai_review`, "Not reviewed") are written for any AI-authored change of path 9a, also from a Local
  provider, where the Add slide sheet (path 7) marks only cloud routes. More is flagged, not less.
