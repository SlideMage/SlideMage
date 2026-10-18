# Assistant and workflow UI overhaul

13 October 2026. Planning and interaction design only; no application behavior has been changed. “Codex window” means the existing **Claude Code** panel, as clarified by the user. This plan adds no Codex integration.

## Product decision

Use **one Assistant area and one prominent, app-wide Local / Cloud switch in the workspace header**. Remove the outer Chat / Claude Code tabs. The mode controls every AI workflow, including image descriptions, translations, AI-assisted transcript content, and assistant tasks; it is not an assistant-only preference. **Local restores the existing per-task Ollama setup; Cloud selects Claude Code for all AI tasks by default.** Preserve native agent chat, the complete Claude Code terminal, structured tasks, all providers, and the other application features listed in `STREAMLINING_PLAN.md`.

Revision, 13 October: move the selector out of the assistant into a persistent global AI area, switch the complete task-model profile together, and show an amber Cloud-mode warning beside the selector. This supersedes the earlier assistant-header placement and per-dialog route overrides.

The switch chooses where AI work runs. Connection and model are secondary choices. Scope says what content the next request can use. Editing policy says how changes are applied. These four concepts must have separate, consistent labels.

This is a UI consolidation, not a backend replacement. One visible assistant does not require merging provider histories or pretending the terminal is a native chat protocol.

## Findings in the current application

- `chat/assistant.py` builds separate `ChatView` and `ClaudeCodeView` children. Its tabs describe implementations, although Chat can already use local Ollama or the cloud Anthropic API.
- Each child owns scope, suggestions, controls, and lifecycle independently. The chat model choice is below the composer; terminal task model/effort is a separate picker. It is easy to miss which setting affects which operation.
- `side_panels.py` stacks an inspector above the assistant, with minimum heights of 128 and 416 pixels. Their controls compete for vertical space, particularly at 1024 × 640.
- The terminal is a real xterm.js/PTY session, with input, resize, copy/paste, hooks, MCP context, and disk synchronization. Scraping its screen into chat bubbles would be unreliable and would lose behavior.
- Structured Claude tasks already capture targets, validate results, handle conflicts, and report batch outcomes. However, their status is mostly a line of text and some results open a separate text sheet.
- The top bar combines deck, audience, language, editor mode, save status, compile, images, and panel visibility. The compile menu and project overflow contain many unrelated operations.
- There is already a command registry, shared workspace state, reusable diff cards, image forms, and build/job UI. The redesign should compose these rather than create a second action system.

## The workspace layout

Keep the three-column workspace and movable dividers. Keep project/output controls separate from a persistent, full-width AI mode row:

```text
SlideMage   [Deck ▾]                            [Find… Ctrl+K] [Compile PDF ▾] [Project ▾]
AI for all tasks  [Local | Cloud]  ⚠ Cloud mode · Claude Code   [AI setup ▾]
                                   AI requests send content to the cloud
            Audience [Instructor ▾]  Language [EN ▾]             Saved
┌ Slides ───────────┬ Preview / Split / Source / Details ┬ Assistant ──────────────────┐
│ Find slides       │                                  │ Claude Code           [⤢]   │
│ + Add ▾           │ Source and/or slide preview        │ Task model / effort ▾       │
│ Section           │                                  │ Scope: This slide ▾         │
│   Selected slide  │ Render preview     Overlay 2/4    │ Slide title · unsaved       │
│   …               │                                  │                             │
│                   │                                  │ Conversation / task / CLI   │
│                   │                                  │                             │
│                   │                                  │ Context actions             │
│                   │                                  │ Input + Send / Stop         │
├───────────────────┴──────────────────────────────────┴─────────────────────────────┤
│ Activity: Compiling Instructor · pass 2 · 54%                      Stop   Details ▾ │
└────────────────────────────────────────────────────────────────────────────────────┘
```

The inspector remains in the right column as a collapsible section, with a clear **Slide details** heading and the existing panel picker. Keep its present split layout as an available remembered layout; offer **Focus assistant** to temporarily collapse the inspector and expand the assistant, then **Restore layout**. Keep the separate centre Details mode and all inspector editing entry points.

Move editor mode selection beside the editor it controls. Keep all four modes and their shortcuts. Use a labelled Audience dropdown for Instructor / During course / After course; language selection remains separate and never initiates translation. The compile button always states the target in its accessible label and menu summary.

At 1600+ pixels, expose common controls inline. At 1250–1599, compact the project controls into labelled menus while retaining the dedicated AI mode row; allow audience/language controls to wrap as needed. At 1024 × 640, keep the assistant usable by collapsing the inspector on explicit focus-assistant action, wrapping controls, and using scrollable content with a fixed composer. Do not force three minimum-width columns onto an expanded assistant. Restore the user's previous divider sizes when focus mode ends. Test 100%, 125%, 150%, and 200% scaling as well as window dimensions.

The AI mode row is above the columns and outside their scrolling areas. It remains visible when the assistant or both sidebars are hidden, in focus-assistant mode, and on the full Images page. At smaller sizes, wrap the explanation beneath the switch; keep both Local / Cloud labels and the active-mode warning visible. Reduce or move secondary toolbar actions before hiding this control. Task sheets that obscure the row repeat its active-mode status as a read-only badge; they do not introduce independent switches.

### Persistent mode warning

| State | Switch-area treatment and exact meaning |
| --- | --- |
| Local | Neutral surface with a restrained green accent, local-computer icon, and **Local mode · Ollama**. Supporting text: **All AI tasks use your Ollama setup**. Show the host in setup; a non-loopback endpoint is labelled **Self-hosted Ollama · remote host** rather than “On this computer.” |
| Cloud selected, idle | Amber-tinted background across the AI mode area, visible amber border/accent, cloud/warning icon, and **Cloud mode · Claude Code**. Persistent text: **AI requests send content to the cloud**. The selected Cloud segment also uses the warning accent. Keep this visible even when nothing is running; it describes the enabled mode, not a transmission already in progress. |
| Cloud task running | Retain the amber warning. Add **Cloud task running** and its task name in Activity; indicate transmission only when a real request event establishes it. |
| Switching away from Cloud | Retain amber and **Cloud mode · stopping…** until all affected cloud work and sessions have settled. Do not show Local/green while cloud work remains active. |
| Cloud unavailable under policy | Disabled Cloud choice with **Cloud disabled for this project**. No cloud request can start. A mode change never alters the policy. |
| Selected profile needs setup | Keep its selected-mode treatment and show **Setup required** with a specific action. Missing Claude Code sign-in or a local vision model never causes a hidden change of route. |

Use theme-specific semantic warning colours with readable text and visible focus in light and dark themes. The icon, explicit wording, and selected state carry the meaning without colour; never rely on a coloured dot alone. Announce committed mode changes accessibly. Reserve red for failures or blocked actions; amber communicates that Cloud is engaged. The persistent warning complements the existing first-cloud-use disclosure and does not add a repeated confirmation for every task.

## One assistant, two execution choices

### Header and input

The stable header contains:

1. **Active connection** label reflecting the global AI mode row. The assistant has no second Local / Cloud selector.
2. **Model / task settings** menu, restricted to the active profile. Local: the configured Ollama chat model and task-specific defaults. Cloud: Claude Code task model/effort; retain direct Anthropic API as an explicit advanced cloud-profile option under global **AI setup**, never an automatic fallback. Remember profiles separately.
3. **Scope** dropdown: This slide / Selected slides (n) / Whole deck. Selection scope is new UI wiring and must use the actual captured selection; disable it with an explanation until the backend supports it. Existing slide/deck scopes ship first.
4. A compact target line: slide title and ID, or deck name and count; indicate unsaved source. Show “Task target: …” while work runs so browsing elsewhere cannot imply that the task changed target.
5. **Expand** and **More**. More contains New conversation, connection settings, copy conversation where supported, and terminal restart when applicable. Keep history persistence at its current guarantee; cross-restart conversation storage is not silently added by this UI plan.

Use one visible input surface. Local and Anthropic API use the existing native composer. Cloud → Claude Code uses the actual terminal with its own input; do not leave a second native composer beneath it. Shared context actions and task results occupy the same assistant area above or in place of the conversation body. A **Return to conversation** action restores that surface without creating another window.

For Claude Code, distinguish **Conversation model: controlled in Claude Code** from **Task model / effort**, unless an existing supported mechanism can read and control both. Never show a task model as if it governs the terminal session. Do not parse ANSI output to infer provider events, approvals, or model state.

### Meaning of Local and Cloud

Local means the configured local/self-hosted Ollama route, not “this process was launched locally.” Claude Code belongs under Cloud even though its executable is on the user's machine. Show the actual Ollama host in connection details; only label it “On this computer” when it is a loopback endpoint. A remote Ollama host must be identified as remote/self-hosted, with the existing project's policy semantics made explicit rather than advertised as offline.

The selection activates a complete model profile for **every new AI action in the active project**, wherever it is launched. It is authoritative, not merely a default that old task pickers can override. Preserve task-specific choices **within** each profile. All open task pickers, image forms, transcript tools, assistant actions, batch dialogs, and settings summaries refresh together. Per-task controls choose a compatible model within that profile or open global AI setup; they cannot secretly select a different route. No silent cloud fallback when a local model is absent or lacks vision/tool capability.

### Switch all task models together

Maintain two independent profiles. **Local / Ollama** contains the user's current endpoint, image/vision model, translation model, chat model, syntax-fix model, and any other configured task defaults. Activating Cloud must not overwrite them. **Cloud / Claude Code** uses the existing Claude Code sign-in and structured task runner, with appropriate task model/effort settings; every app-managed AI task uses that route. Returning to Local restores the exact Ollama choices. Preserve prompt/style/glossary and review settings across profile changes unless they are explicitly provider-specific.

| Workflow / entry points | Local profile | Default Cloud profile |
| --- | --- | --- |
| Assistant conversation and supported agent tools | Configured Ollama chat/tool model | Existing Claude Code terminal and its native conversation model/permissions |
| Image descriptions, redraft/tune, single image and batches, page and inspector | Existing configured Ollama vision model | Claude Code image-task adapter with the actual image supplied; retain per-image draft/review protection |
| Slide/deck translation, update translation, image-description translation, selected/batch actions | Existing configured Ollama translation model | Claude Code translation tasks with the same language, address, glossary, linking, and validation rules |
| AI-assisted transcript text, summaries, speaker notes, accessibility drafting/rewrite | Configured Ollama model appropriate to the task | Claude Code structured task adapter for the same action |
| LaTeX fixes, proofreading, concise rewrite, titles, other existing AI actions | Configured compatible Ollama task model | Claude Code structured task adapter for the same action |

Inventory all actual AI dispatch paths, including commands invoked through the palette, inspector, task dialogs, and app-managed MCP actions. Nested task calls must inherit the captured profile, not a stale saved model or current widget value. Interactive Claude Code retains its own tools and approvals and cannot stay live under Local. Ordinary transcript generation/export, LaTeX compilation, previews, and other deterministic operations continue to run locally; selecting Cloud does not add AI or uploads to those operations.

The cloud route is **Claude Code**, not an Anthropic API key substituted behind a cloud label. Keep direct Anthropic API support as an advanced, explicitly selected cloud connection; if chosen, show **Cloud mode · Anthropic API** globally and resolve every supported task through that profile. Unsupported tasks show a specific explanation rather than quietly mixing Claude Code, API, and Ollama. Retain the separate conversation-versus-task model distinction for Claude Code.

Some task adapters will require implementation: this is more than changing picker labels. Preserve existing task prompts, inputs (including images), structured output validation, cancellation, apply/review, and batch recovery when adapting them. Missing capability blocks only the affected action and offers setup; it must not silently use the previous profile. The complete-switch feature is ready only when every existing AI entry point is covered or explicitly and truthfully unavailable for that profile.

Keep the existing **Local AI only** project policy separate from the selection. When policy forbids cloud, Cloud is unavailable with “Cloud disabled for this project” and a settings link; clicking the selector must not weaken that policy. Apply the same resolver checks to native chat, terminal launch/input, structured tasks, image workflows, and queued work. Audit the current terminal paths rather than assuming API-provider checks already cover them.

The existing first-cloud-use notice appears before the first actual transmission, not merely when choosing Cloud. State the active scope and the kinds of content sent; do not promise a precise file list for a general agent that may read additional files in scope. Preserve the existing consent controls and credentials storage.

### Switching behavior

| State | Local / Cloud or connection switch |
| --- | --- |
| Idle | Restore that route's prior surface, draft, scroll position, and model choice. No request is sent. First visit shows a contextual empty state. |
| Any AI task running anywhere in the app | Keep current route and warning selected; summarize affected chat, image, translation, transcript, and batch work. Offer **Stop and switch** / **Keep running**. Switch only after all affected cancellations settle; never kill midway through applying a file change. Already completed results stay available. |
| Queued batch work | A run captures one immutable profile. On Stop and switch, cancel its not-yet-started items; do not move the remainder to another provider. A later retry is a new run that shows and captures the then-active profile. |
| Results awaiting review | Retain the review card and its provenance in Activity. Switching does not approve or discard it; applying later still checks target freshness. |
| Claude terminal active | PTY liveness is not proof of idleness. For a live session, explain that switching routes ends the session; offer **End session and switch** / **Stay**. Re-entering restores scrollback as a transcript and starts a new session unless supported session-resume behavior has been verified. Never display a cloud session as still alive under Local. |
| Local-only policy enabled while cloud work exists | Stop or settle cloud activity before acknowledging the policy as active; prevent new cloud work, including terminal input. Keep completed results viewable. |
| Missing model/key/CLI or offline | Inline connection state and specific repair action; keep the editor usable and the unsent draft intact. |

Route-specific backend history remains separate, behind the single shell. Do not automatically send a local conversation to the cloud or manufacture a common terminal/API history. A neutral line such as “Cloud conversation resumed” makes the change clear. Drafts also remain route-specific unless the user explicitly copies them. New conversation affects the current route only.

## Tasks as visible UI steps

Use one reusable **task card** for explicit actions, in the conversation region. Each card has a title, captured target, provider/model provenance, current state, and one primary action. It can expand to show steps, changed files, and logs. These are actual operation states, not invented model reasoning or progress inferred from terminal text.

Common sequence for structured edits:

```text
Prepare → Generate → Review → Apply → Check preview
```

Only show relevant steps. A question has Read/Respond; image descriptions have Draft/Review/Save; a summary ends at Result. Small actions start from their context button immediately when all inputs are known. Do not force users through a five-screen wizard to fix one error. The steps show execution and recovery, not mandatory clicks.

| Step/state | Visible UI | Action / completion rule |
| --- | --- | --- |
| Prepare | Inline task summary: target, language/options, route; batch lists affected items and skipped reasons | **Start** only when options are needed; otherwise enter Generate directly. Capture source and selection at dispatch. |
| Generate | “Translating slide …” and elapsed time; batch count where known | **Stop**. Indeterminate progress for one model request; never invent a percentage. |
| Review | Compact before/after; expand into centre comparison for long source; file/slide checklist for batch | **Apply** / **Reject**. Preserve the existing automatic-edit option. Applied automatically: mark Review skipped and provide the existing supported Undo behavior. |
| Apply | “Applying 3 changes”; show exact destinations | Commit each change only if captured source still matches and protections pass. Batch is not claimed to be globally atomic. |
| Check preview | “Checking updated preview”; old preview clearly marked while building | Success links to affected slide. Render failure says **Changes applied; preview failed**, with Fix errors / View log. Never imply rollback occurred. |
| Done | “Updated 3 slides; 1 unchanged”; compact result and Undo when supported | **View changes** and existing undo/backup route. Do not promise terminal-wide undo or transactional batch undo that does not exist. |
| Conflict | “Slide changed while this task ran”; retain proposal | **Compare with current** / **Run again** / **Dismiss**. No blind Apply. |
| Failed / stopped / partly done | Completed, failed, skipped, and cancelled counts; exact affected items | **Retry failed** / **View results**. Stop preserves already applied changes. Retry recaptures current inputs and rechecks policy. |

Natural agent conversations can have repeated tool/review cycles; represent them as expandable action rows inside a turn, not a fake linear five-step workflow. The terminal retains its own approvals and feedback. Host-managed structured tasks get the step card; arbitrary terminal activity gets only truthful process/session status and the native screen.

An editing-policy menu reads **Review changes** / **Apply automatically** for app-managed edits. Keep existing defaults on migration and make the chosen policy visible before tasks run. Adding review to structured tasks requires separating generation from application; do not claim the existing immediate-apply runner already supports it. For interactive Claude Code, show **Permissions handled in Claude Code** rather than offering a nonfunctional policy control.

## Context actions and discoverability

Show at most two relevant suggestions plus **All actions…**. Prioritize Fix LaTeX errors, then a missing/outdated translation, then image-description gaps. Suggestions must not jump under the pointer or change while a task is being launched. Keep unavailable actions discoverable in All actions with the reason and a relevant setup link.

All actions are commands from the existing registry, shared by assistant suggestions, slide menu, inspector, and Ctrl+K. Keep the full current set: translate/update translation, proofread, concise, better title, notes, image descriptions/translation, deck summary, and existing deck batches. Unsupported local task capabilities remain visibly unavailable; implementing missing local task adapters is an explicit delivery item, not hidden provider substitution.

Avoid a new top-level “Steps” tab. A task's steps belong to that task. The app's development milestones below are not screens shown to end users.

## Other workflows: exact UI changes

| Workflow | Entry and proposed UI | Result / feature preservation |
| --- | --- | --- |
| Open/create project | Deck/project menu → Open project; recent folders and Create project remain in one chooser. Show required paths and compatibility status inline. | Existing project detection, templates, bundled-copy updates, and migration safeguards remain. |
| Navigate/add slides | Slide list retains search, sections, drag/drop, and multiselect. One **+ Add** menu opens existing slide templates, duplicate, and import actions. Keep keyboard move commands. | Insertion point is visible: “After slide … in section …”. Duplicate does not silently translate. |
| Edit/save/render | Centre toolbar owns Preview/Split/Source/Details. Save status uses Saved / Unsaved / Saving / Save failed where supported. Keep explicit Save and render shortcuts. | Do not introduce autosave or save-on-navigation changes as part of a visual overhaul. Render uses the captured buffer; dirty-switch prompts remain. |
| Switch language | Language chooser browses the translated partner. Missing translation shows inline **Translate to DE**; outdated partner shows **Update translation**. | Selecting DE never creates content. Existing link repair is accessible from the language inspector/Project maintenance. |
| Translate a slide | Action opens only needed language/style controls inline; run becomes a task card with source/target identity and diff. | Create/link partner only after successful generation, validation, and approval when enabled; preserve source buffer conflicts and frozen versions. |
| Translate/fix a deck | Scope Whole deck → action with count → compact affected-item list with skips → Start. Results become a table in the centre when expanded. | Preserve existing workers/rate-limit handling. Clear per-item state; Stop, Retry failed, review/apply where supported. |
| Compile PDF | Primary click still compiles current audience. Arrow shows Current / All audiences / Presenter / More outputs… and contextual Selected slides. | More outputs contains chapters, page ranges, partial patching, several/all decks, transcripts, and build options. Keep command aliases/shortcuts for direct access. |
| Inspect compile failures | Single Activity strip shows job, stage, existing percentage, and Stop. Expand to job list; select failure to jump to source. | Detailed logs, retry, output folder, and latest PDF remain available. Keep stale/latest PDF status explicit. |
| Image descriptions | Images page has slide/image navigation, preview, and shared form; filters All / Needs description / Needs review. Inspector uses the same form logic. | Separate Draft from Reviewed status. Drafting never marks human review complete. Preserve role, descriptions, takeaway, source, translations, and replacement actions. |
| Image batch work | Select images or choose missing descriptions → route/model summary → Start; individual results link back to image. | Existing per-image persistence, resumability, concurrency locks, and reviewed-during-run protection remain. |
| Citations/notes/transcripts | Existing inspector picker gains sensible groups: Content, Accessibility, Versions & usage; search only if needed. Insert citation stays near source. | All eight panels and transcript preview/export remain. Grouping must not hide errors or unsaved form state. |
| Versions/restore | Version list with Current/Frozen labels, Compare and Restore actions; show translations and deck usage alongside the selected version. | Existing file version semantics and backups stay. No new version-graph backend is required. |
| Visibility/deck organisation | Audience visibility remains explicit per slide; deck tags/settings live under the Deck menu. Clarify **Remove from deck** versus **Delete slide file**. | Keep cross-deck usage checks, archive behavior, duplicate, rename, and administrative slides. |
| Import PPTX/ODP | Compact sheet: choose file → inspect destination/options → Import. Progress and conversion warnings in Activity; Open imported slides on success. | Preserve current supported content and options. Do not promise a visual conversion preview without implementing it. |
| Export PPTX/transcripts | More outputs/Export sheet with format, audience, destination, and advanced options collapsed. | Preserve overlay behavior and Markdown/HTML transcript output; Open output on completion. |
| Reproducible snapshots | Deck → Snapshot opens Options → Create → Verify/Result. Advanced environment/app/font choices are grouped but retained. | Verification is a visible step with real outcome; old snapshots, manifests, scripts, and all capture options remain. |
| Course/admin slides | Deck → Course tools shows source/course URL, supported generation options, and resulting changes. | Keep scheduling/API automation; unavailable configuration explains why and links to the relevant setting. |
| Housekeeping | Project → Maintenance is one sheet with previews of affected items and existing actions. | Keep temporary cleanup, PDF cleanup, archive-unused, preview rebuild, link repair, compatibility and backups. Destructive operations show scope before execution. |
| Settings | Sections: Appearance & layout; AI connections; Task defaults; Prompts & translation style; Project policy; Updates & maintenance. | Keep Ollama installation/model management, API credentials, local-only policy, automatic updates, and breaking-release handling. Links from errors land on the relevant section. |
| Search/help | Ctrl+K remains the one command/slide/source search. Visible Find control improves discovery. Tooltips supplement labels. | Keep old command names as searchable aliases when labels move. All moved actions have one obvious home and remain searchable. |

The Activity strip is a shared **view of existing jobs**, not a new scheduler. Compile and AI keep their current resource limits. The assistant shows its active task in detail; Activity shows a compact linked entry for the same run ID, not a second independent progress state. Hide the strip when idle with no relevant result; retain a way to reopen recent session results. Cross-restart job history/resumption is not implied.

## Implementation boundaries

| Existing area | Concrete change |
| --- | --- |
| `chat/assistant.py` | Becomes the single shell: observes the global route, shows shared header/target identity, expand/restore, and one content stack. Preserve a compatibility reference for existing callers only during migration. |
| `chat/view.py`, `chat/session.py` | Separate reusable conversation body/composer from duplicate route/scope chrome. Accept an explicit route; keep local and API session histories separate. |
| `terminal/view.py`, `session.py`, `web.py` | Embed the existing terminal in the shell, retaining PTY, hooks, MCP, focus sync, copy/paste and resize. Move shared chrome out. Implement explicit end-session switching and truthful session status. |
| `terminal/tasks.py`, `ai/claude_runner.py`, `ai/claude_tasks.py`, `ai/claude_images.py` | Emit typed task phase/result events at existing boundaries; separate validated proposal from apply where needed for review. Keep operation-specific logic and existing batch recovery. Move shared task UI out of the terminal package. |
| `ai/resolver.py`, `ui/ai_models.py`, settings, Claude task/image adapters | One authoritative active profile and policy check at every dispatch. Separate Ollama and Claude Code task-model maps, plus preserved advanced API settings. Refresh all task pickers together; route every task family through a compatible adapter. Capture profile identity in nested tasks and batches. Audit task and terminal policy coverage. |
| `chat/cards.py`, existing image forms | Reuse diff rendering and shared editing forms. Add a task card only once, with expandable phase rows and result actions. |
| `side_panels.py`, `layout_settings.py` | Collapsible inspector, assistant focus mode, resize rules, restore geometry and remembered split. |
| `topbar.py`, workspace state, `centre.py`, `actions.py`, `menus.py` | Own the always-visible global AI mode row and amber Cloud warning; synchronize all entry points. Relocate remaining controls, simplify menus through shared commands, preserve command IDs and shortcuts. |
| `job_panel.py`, `compile_jobs.py`, `image_jobs.py`, `image_runs.py` | Present existing jobs through small status adapters and stable run IDs. Keep scheduling/cancellation ownership in existing systems. |

Use a small shared AI configuration state owned by the workspace: active profile, connection/models per profile, policy, and switch-pending state. Assistant scope, task identity, and presentation state remain separate. A captured request contains project/target paths, source revision or captured text, profile identity/revision, provider/model, editing policy, and scope. Workers must not read changing widgets. Observe existing workers to settle a profile switch across all workflows; do not introduce an event bus, plugin registry, universal scheduler/workflow graph, or full transcript database.

Migrate settings without discarding preferences: preserve every existing Ollama task model/endpoint in the Local profile and existing Claude task settings in the Cloud/Claude Code profile; retain API defaults in advanced cloud setup. A fresh configuration starts Local, and selecting Cloud uses Claude Code by default. For existing users, adopt a clearly established active route (including an explicitly configured API connection), but never infer Cloud solely from one old task-model field. Mixed legacy defaults require a visible profile summary; retain them for their respective profiles rather than continuing hidden cross-route dispatch. A legacy cloud preference cannot override local-only project policy. Keep machine geometry separate from portable project preferences and credentials.

## Delivery steps, each with visible UI value

| Step | User-visible result | Implementation / acceptance |
| --- | --- | --- |
| 1. Global AI mode and one shell | Prominent header switch and persistent amber Cloud warning; all task-model profiles change together; one assistant/input | Reuse current bodies. Wire every existing AI entry point and required Claude/Ollama adapters before calling the switch complete. Test profile migration/restoration, all task families, policy, no history/draft transfer, and app-wide task/session switching. |
| 2. Usable layout | Assistant expands/restores; inspector collapses; controls fit at 1024 × 640 | Real Qt layout checks, keyboard/focus and font scaling. Keep all editor/inspector modes. |
| 3. Visible task steps | Existing Claude actions get Prepare/Generate/Apply/Preview outcomes and clear partial failures | Typed events from current runner; no fictitious Review state until step 4. Reuse existing operation ordering and task defaults. |
| 4. Review and recovery | Review changes/automatic policy for app-managed tasks; diff, Apply/Reject, conflict compare, retry failed | Generation/apply separation; shared validations; no orphan translations; no overwritten edited buffers; honest Undo availability. |
| 5. Consistent actions | Same task names, scope, and route across assistant, image page, inspector, transcript tools, and palette | Consolidate action presentation after step 1's routing coverage; implement any newly added task capabilities explicitly. Capability/vision/model errors never fall back silently. |
| 6. Navigation and outputs | Clear toolbars/menus, one Activity view, streamlined compile/export/snapshot/course flows | Preserve every command; shared job presentation without changing resource concurrency or output semantics. |
| 7. Settings and polish | Direct setup links, connection/policy clarity, coherent empty/loading/error states | Verify all provider/account/model-management/update paths, contrast, tab order, screen-reader names, translations, and existing shortcuts. |

Steps 1–3 give the first usable increment. Do not wait for a full application redesign before shipping the single assistant area. Do not claim code-size savings from this UI work until old chrome and duplicate state paths have actually been removed; new review states and capability adapters may add code initially.

## Verification and usability acceptance

- Every current command is mapped to a new visible home and remains searchable. Use the command registry as the inventory; test missing mappings rather than maintaining another hardcoded action list.
- From every main page, including Images and with the assistant hidden, a user can see and change the global Local / Cloud mode without opening Settings. Cloud is unmistakable through an amber area, icon, and explicit text in both themes, including at 1024 × 640 and increased scaling. Task surfaces show actual connection/model, target, and editing policy; distinguish Claude terminal permissions/model from task settings.
- Configure distinct Ollama models for chat, vision, translation, and text fixes. Switch to Cloud once: every image, translation, AI-assisted transcript, assistant, inspector, palette, and batch action must dispatch through Claude Code. Switch back once: all original Ollama models and endpoint are restored. Repeat with open dialogs and queued tasks; no stale picker or nested task may bypass the active profile.
- With fake providers/CLI, assert no cloud calls under Local, no Ollama task fallback under Cloud, no request merely from switching, and no AI calls during ordinary deterministic transcript export/compile. Exercise the advanced API profile separately and make its provider name visible.
- A user can translate a slide, fix an error, describe an image, and review an edit without navigating between two assistant windows.
- Switching route does not transmit content, restart a task on another provider, lose a draft, silently discard proposals, or leave hidden cloud work under Local.
- Changing slide/deck/language during a task never retargets captured work. Unsaved edits, frozen versions, protected content, and reviewed images remain protected.
- Step/status labels come from real events. Generation and compilation percentages are shown only when the backend supplies meaningful measurements. Stop and failed-preview states accurately describe changes already made.
- Test keyboard-only navigation, screen-reader labels/live updates, colour-independent status, long titles, narrow panes, scaling, and dark/light themes. Preserve terminal keyboard handling; application shortcuts must not unexpectedly consume terminal input.
- Reuse `test_chat_gui.py`, `test_claude_code_gui.py`, `test_claude_tasks_gui.py`, `test_ai_models_gui.py`, `test_side_panels_gui.py`, `test_workspace_window.py`, `test_compile_flow_gui.py`, `test_images_page_gui.py`, and lifecycle/provider tests. Add coverage only for new contracts. Use fake providers/CLI, disposable project copies, and no real cloud calls for UI tests.
- Compare fixed representative outputs for compile, transcript, conversion, partial patch, and snapshot flows after navigation changes. Test frozen Linux/Windows builds for terminal lifecycle and resizing; report unavailable platform checks.

The accompanying interaction mockup uses simulated results. It is a design aid, not a replacement implementation or evidence that backend review/local-task parity already exists. **The existing HTML mockup predates this global-switch revision**: its assistant-local selector and the checks below do not validate the new placement, profile-wide routing, or warning treatment. Update those prototype states before using it as an implementation reference; the requirements above and the synchronized design brief take precedence.

Design validation performed: JavaScript syntax check; headless browser interaction checks for route switching, terminal end-session confirmation, draft restoration, review/apply/preview, undo, focus mode, stop-and-switch, retained results, and source conflicts. All 13 checks passed at both 1100- and 320-pixel browser widths; desktop and narrow screenshots were inspected, with no horizontal overflow in either run. Application Qt integration, real provider behavior, and platform builds remain implementation acceptance work, not completed tests. Mockup source: `docs/ui/assistant-workflows.html`.
