# SlideMage — UI redesign brief for Claude Design

**Prepared:** 13 October 2026

**Deliverable requested:** a coherent desktop UI design and interactive prototype, followed by an implementation-ready design specification.

**Scope:** redesign the existing application while preserving all features. This document is self-contained; repository access and earlier conversations are not required.

## 1. Your assignment

Design a substantially clearer and more usable SlideMage desktop application. Start with the assistant experience, then make the surrounding editing, translation, accessibility, compilation, and project-management workflows consistent with it.

The central requirement is **one Assistant area and a prominent app-wide Local / Cloud switch in the persistent workspace header**. The switch changes every AI task together: **Local restores the user's existing per-task Ollama setup; Cloud uses Claude Code by default**, including image descriptions, translations, and AI-assisted transcript content. Cloud mode must remain visibly marked by an amber warning area beside the switch. The current app has separate Chat and Claude Code views with duplicated controls. Replace that distinction with a single assistant shell, without two chat windows or competing composers. Do not put the only mode switch inside the assistant.

Also design **how task steps appear in the UI**: preparing a request, generating a result, reviewing changes, applying them, checking the preview, and recovering from errors. Make these real interactions, not just decorative progress indicators.

Preserve the existing capabilities. Simplify navigation, hierarchy, shared controls, and feedback. Do not achieve simplicity by deleting features or moving them into external tools.

Produce a thoughtful recommended design. You may improve the suggested layout in this brief as long as the required behavior remains intact. Distinguish design recommendations from existing application behavior and from new implementation work.

## 2. Product and users

SlideMage is a desktop application for researchers and teachers who create LaTeX/Beamer slide decks. A project contains reusable slide source files, decks that assemble those slides, media, bibliography, image descriptions, and version information.

Users frequently work in English and German. They need to edit source, inspect the rendered slide, manage translations, generate accessible descriptions and transcripts, and compile different outputs. Some users are comfortable with LaTeX and terminals; others rely on the UI and AI assistance.

Important product concepts:

| Concept | Meaning |
| --- | --- |
| Project | A folder containing decks, reusable slides, media, bibliography, and settings. |
| Deck | An ordered collection of slide references and sections. A slide can appear in several decks. |
| Audience | Instructor, During course, or After course. This affects slide visibility and compiled output. |
| Language | Primarily EN/DE. Selecting a language displays an existing translation; it must not automatically create one. |
| Source | Editable LaTeX. It may contain unsaved changes that differ from the saved file. |
| Preview | A rendered representation of the source. It can be current, older than the buffer, updating, or failed. |
| Current/frozen version | Editable current slide versus a preserved historical version. |
| Image description | Accessibility content with draft/review status, attribution, and potentially translated fields. |
| Snapshot | A reproducible deck archive with captured dependencies and verification; more than a ZIP of source files. |

This is a working desktop editor, not a marketing website, a generic chat client, or a dashboard with decorative metrics.

## 3. Current problems to solve

- “Chat” versus “Claude Code” describes implementation rather than the user's local/cloud choice. The Chat view already supports both local and cloud providers.
- Scope, models, suggestions, edit permissions, and status appear in different places in the two assistant views.
- An inspector stacked above the assistant consumes the space needed for a useful conversation, terminal, or diff.
- The top bar mixes project navigation, audience, language, save status, editor modes, compilation, and utility actions.
- Many useful commands are buried in a long compile menu or a broad overflow menu.
- AI tasks often report progress in a small status line; users need clearer results, review, and recovery actions.
- “Saved,” “applied,” “rendered,” and “reviewed” describe different states, but the UI must make those distinctions easier to understand.

## 4. Non-negotiable design requirements

1. One Assistant area and one prominent **Local / Cloud** selector above the workspace columns, visible on every main page even when the assistant is hidden. It switches the complete AI task-model profile, not just chat.
2. Preserve native AI chat, the embedded Claude Code terminal, focused AI tasks, Ollama, and direct Anthropic API support.
3. Show which connection/model is used, what content is targeted, and how edits are approved. Cloud mode has a persistent amber surface, warning/cloud icon, and explicit text beside the selector; colour alone is insufficient.
4. Only one visible text-input surface for the active assistant interaction.
5. Retain all four centre modes: **Preview, Split, Source, Details**.
6. Preserve all application features listed in the workflow inventory below, including advanced and infrequent ones.
7. Keep the editor useful while AI, rendering, or compilation is running.
8. Make unavailable, waiting, failed, partial-success, and conflicting states actionable.
9. Do not silently move conversations or drafts between local and cloud providers.
10. Do not make promises the underlying operation cannot support: universal Undo, exact model progress, global batch rollback, or guaranteed terminal session resumption.

“Claude Code” means the existing embedded CLI/terminal feature. Do not add an OpenAI Codex integration. “Claude Design” is the tool receiving this brief, not a new provider inside SlideMage.

## 5. Suggested information architecture

Keep a familiar three-column editing workspace with adjustable dividers:

- **Left:** deck outline, sections, slide search, selection, and Add slide.
- **Centre:** source and/or rendered slide, editor modes, preview controls, and expanded comparisons/results when needed.
- **Right:** one Assistant area and the existing slide inspector. Let users collapse the inspector and focus the assistant without losing their previous layout.
- **Bottom:** a compact Activity strip for current work, expandable into job details and results.

Suggested control placement:

```text
Project / Deck                    Find commands                Compile PDF ▾
AI for all tasks  [Local | Cloud]  ⚠ Cloud mode · Claude Code   AI setup ▾
                                  AI requests send content to the cloud
Audience: Instructor ▾            Language: EN ▾               Saved

Slides                  Preview | Split | Source | Details     Assistant
Search / + Add          Source or rendered slide               Active connection
Sections and slides                                           Task model / effort
                                                              Scope and target
                        Render preview / Overlay controls      Conversation or task
                                                              One input surface

Activity: compile / AI / image batch status                     Stop / Details
```

This is a hierarchy sketch, not a prescribed pixel layout. You may use a quieter or more compact arrangement. Avoid adding permanent toolbars for every option.

The global AI mode area stays outside panel scrolling and survives assistant focus mode, hidden sidebars, and the full Images page. On smaller desktops, wrap its explanation beneath the switch rather than moving the switch into a menu. Dialogs obscuring the header repeat a read-only active-mode badge, not an independent route selector.

The inspector must retain panels for: Used in decks, Versions, Visibility, Citations, Language, Image descriptions, Transcript entry, and Speaker notes. Group these sensibly without removing them. Preserve direct editing of image descriptions both in the inspector and the full Images page.

Include **Focus assistant / Restore layout**. Do not open a second assistant window as the default way to gain space. Preserve movable dividers and the user's remembered layout.

## 6. The unified assistant

### Location, connection, model, scope, editing policy

These are separate concepts and need distinct labels:

| Control | Required behavior |
| --- | --- |
| Local / Cloud | Authoritative app-wide profile for every new AI action in the active project. Always in the workspace header; the assistant reflects it. |
| Connection | Local: configured Ollama endpoint. Cloud: Claude Code by default. Preserve Anthropic API as an explicit advanced cloud-profile option under global AI setup, never an automatic fallback. |
| Model | Compatible models within the active profile. Restore the user's separate Ollama task models on return to Local; Cloud activates Claude Code task model/effort settings together. |
| Scope | This slide / Whole deck initially. Include a design for Selected slides (n), clearly identified as requiring additional implementation. |
| Target | Actual slide title/ID or deck and count. Indicate unsaved source. During a task, keep the captured task target visible even if the user navigates elsewhere. |
| Editing policy | Review changes / Apply automatically for application-managed edits. For the interactive terminal, show that permissions are handled in Claude Code. |

Claude Code belongs under **Cloud**, even though its executable runs locally. Ollama may be on this computer or a self-hosted remote machine: display the actual endpoint accurately. Do not label a remote endpoint as “on this computer” or imply that it works offline.

### Global profile and persistent Cloud warning

Design the selector as a visible **AI for all tasks** area, not a small chat setting. Use these states:

| Mode | Appearance and wording |
| --- | --- |
| Local | Neutral background, restrained green accent, computer icon, **Local mode · Ollama** and **All AI tasks use your Ollama setup**. Identify a remote endpoint as self-hosted/remote. |
| Cloud, including idle | Amber-tinted area with visible warning accent/border, cloud/warning icon, **Cloud mode · Claude Code** and **AI requests send content to the cloud**. Accent the selected Cloud segment too. The warning persists until the switch to Local completes. |
| Cloud running or stopping | Keep amber; show **Cloud task running** or **Cloud mode · stopping…**. Do not claim a transmission is occurring without a real request event, or show Local while cloud activity continues. |
| Policy blocks Cloud | Disabled Cloud choice and **Cloud disabled for this project**. The switch cannot weaken policy. |
| Setup required | Keep the selected mode visible and add a specific setup action. Missing local models, Claude CLI, or sign-in cannot silently substitute another provider. |

Use accessible light/dark warning colours, text, icon, selected state, and keyboard focus together; announce committed changes. Reserve red for failures. Keep the warning visible at 1024 × 640 and increased scaling. It complements the existing first-cloud-use notice rather than creating repeated task confirmations.

The switch exchanges the whole task-model profile:

| AI work | Local | Cloud default |
| --- | --- | --- |
| Chat and supported agent tasks | Configured Ollama chat/tool model | Real Claude Code terminal and native conversation model |
| Image description, redraft/tune, single/batch, inspector and Images page | Configured Ollama vision model | Claude Code image-task adapter with actual image input |
| Slide/deck translation, linked-translation updates, image-description translation | Configured Ollama translation model | Claude Code translation tasks with existing language/style/glossary rules |
| AI-assisted transcript content, summaries, notes, accessibility drafting | Configured compatible Ollama text model | Claude Code structured task adapter |
| LaTeX fixes, proofreading, concise rewrite, titles, other AI commands | Corresponding configured Ollama model | Claude Code structured task adapter |

Every entry point follows this profile: assistant, page, inspector, palette, dialog, batch, and nested app-managed tool call. Refresh open task/model controls together. Per-task pickers may change a model within the profile; no dialog may quietly retain a cross-route override. Preserve all Ollama defaults and endpoint while in Cloud, then restore them exactly on return. Keep prompt, glossary, review, and image-protection behavior.

Ordinary transcript generation/export, compilation, and rendering remain deterministic local operations; Cloud mode does not introduce AI or upload their content. Only their explicit AI-assistance actions use the selected profile. Missing Claude Code or Ollama task adapters are implementation work, not a reason to show a misleading successful switch. Unsupported actions need an explicit unavailable state and setup explanation.

Direct Anthropic API remains available through advanced global cloud setup. If explicitly selected, change the global label to **Cloud mode · Anthropic API**, use that profile for all supported AI actions, and explain unsupported actions. Never silently mix API, Claude Code, and Ollama across tasks.

### One shell; the correct body for each connection

- **Local/Ollama:** native message history and composer.
- **Cloud/Anthropic API:** the same native chat presentation, using that route's own history and draft.
- **Cloud/Claude Code:** the real embedded terminal inside the same assistant shell, retaining its input, keyboard interaction, copy/paste, resizing, context integration, and permissions. Do not place another message composer under the terminal.

The terminal is a required capability. Do not replace it with fake chat bubbles or assume its screen output can be reliably converted into structured chat events. Shared task buttons can open a structured task card in the same area; **Return to conversation** restores the appropriate body.

The Claude Code conversation model and the model/effort for task buttons may be different. Label these honestly. Unless integrated control has been implemented, use “Conversation model: controlled in Claude Code” and a separate task model/effort setting.

### Switching and policy states

Design each of these states:

| Situation | Expected interaction |
| --- | --- |
| Switch while idle | Restore that route's draft, model, and available conversation state. Merely switching sends no request. |
| Switch during any AI work | Summarize affected assistant, image, translation, transcript, and batch tasks. Offer **Stop and switch / Keep running**. Commit the mode change only after all affected cancellations settle; do not interrupt an in-progress file commit. |
| Queued batch items | Capture one profile for the entire run. Stop and switch cancels pending items; do not transfer the remainder to another provider. Retry is a new run with a visible, newly captured profile. |
| Switch with a proposal awaiting review | Preserve the proposal and its provider/target identity. It remains reachable through Activity and still requires a freshness check before applying. |
| Switch away from an active Claude Code session | **End session and switch / Stay**. Do not assume a live terminal process is idle. Do not promise session continuity unless resume behavior is supported. |
| Local-only project policy | Cloud unavailable, with “Cloud disabled for this project” and a relevant settings link. The mode selector cannot override policy. |
| Missing model, disconnected Ollama, missing API key, missing CLI, or failed sign-in | Inline explanation and a specific setup/retry action. Preserve the draft and keep editing available. |
| Unsupported capability | Explain, for example, that a selected model cannot describe images or use tools. Offer a compatible choice; never silently switch to cloud. |

Keep route-specific histories separate internally. The UI must not suggest that all providers share the same conversation. New conversation affects the current route only. Cross-restart conversation persistence is not assumed.

Preserve the existing first-cloud-use disclosure before actual transmission. Summarize the selected scope and types of content involved; do not claim an exact file list for a general agent that can explore within scope. Show setup/privacy information when relevant, not as a repeated modal for every request.

## 7. Task steps as UI

Design a reusable task card with:

- Task title, captured target, provider/model, and current state.
- One primary action appropriate to that state.
- Expandable steps and details rather than a permanently large stepper.
- A compact result with links to affected slides, files, or images.

Typical structured-edit sequence:

**Prepare → Generate → Review → Apply → Check preview**

This is not a mandatory five-screen wizard. A simple action can begin immediately if all inputs are known. Only ask for missing options. Display relevant phases as the task executes.

| State | What the user sees | Actions |
| --- | --- | --- |
| Prepare | Scope, target, route, relevant options; affected-item count for a batch | Start or Cancel when options are needed |
| Generate | Specific work description and elapsed time; known item counts for batches | Stop |
| Review | Before/after comparison; expand into the centre for long source; selectable batch proposals | Apply, Reject, View full diff |
| Apply | Exact targets being changed | Clear non-interruptible commit state where necessary |
| Check preview | Updated source being rendered; old preview marked as older | Show result or View log on failure |
| Done | What changed, what remained unchanged, and where to inspect it | View changes; Undo only when supported |
| Conflict | “The slide changed while this task ran”; proposal retained | Compare with current, Run again, Dismiss |
| Failed/stopped/partly done | Separate completed, failed, skipped, and cancelled items | Retry failed, View results |

Important distinctions:

- A single model request has no reliable percentage: use an indeterminate indicator and elapsed time.
- A batch can show “3 of 8 processed,” with truthful per-item states.
- Existing detailed compilation percentage/pass progress stays available.
- “Changes applied; preview failed” is different from “No changes applied.” Do not imply rollback.
- Stop does not undo changes already applied.
- With Apply automatically, skip the review wait visibly; preserve the existing supported Undo path.
- Arbitrary agent conversations may repeat tools and review cycles. Show expandable action rows within the turn rather than forcing a linear task pipeline.
- Arbitrary terminal activity retains the terminal's own feedback and approvals. Only host-managed tasks receive these structured cards.

Keep at most two prominent contextual actions plus **All actions…**. Suggested priority: fix an actual LaTeX error, address a missing/outdated translation, then an image-description gap. Do not continually reorder buttons under the pointer.

Retain translate/update translation, proofread, shorten, improve title, add speaker notes, describe/translate images, deck summary, and supported deck batches. Use identical names wherever an action is available.

## 8. Whole-application workflow inventory

Every row must have a clear home in the redesigned navigation. Infrequent features can use grouped menus or advanced sections; they must remain discoverable and searchable.

| Workflow | Design requirement |
| --- | --- |
| Open/create project | Recent folders, Open, Create, templates, compatibility messages, and framework/manual update handling. |
| Navigate slides and sections | Search, drag/drop, multiselect, keyboard movement, add/rename/reorder/remove sections, and visible insertion position. |
| Add/duplicate slides | Template choice, destination, duplicate and translation as distinct actions; retain source-editing safeguards. |
| Edit source | Preview/Split/Source/Details, explicit save, syntax feedback, insert helpers, citation insertion, find/replace, and keyboard shortcuts. Do not silently introduce autosave. |
| Preview | Saved or unsaved source, overlay navigation, existing render scopes, timestamp/audience/language options, stale/update/error states. |
| Languages | Display translated partner; missing/outdated states with explicit Translate/Update actions; translation style and glossary; broken-link repair. Selecting a language does not modify files. |
| Audience and visibility | Instructor/During course/After course, per-slide visibility controls, and clear distinction between viewing and changing visibility. |
| AI chat and tasks | Both assistant bodies, all providers, structured tasks, edit review/automatic editing, scope, Stop, and appropriate recovery. |
| Image descriptions | Full Images page and inspector form; image preview, role, short/long description, takeaway, source, translation, replacement, and batch drafting. Draft and human-reviewed are separate states. |
| Accessibility and notes | Transcript entries and previews, Markdown/HTML transcript export, speaker notes, and image review status. |
| Bibliography | Search/insert citations and edit bibliography. |
| Slide versions and usage | Current/frozen versions, compare/restore, backups, translation links, and cross-deck usage. Keep existing version semantics; a new version graph is not required. |
| Compile | Current/all audiences, chapters, presenter, selected slides/pages, several/all decks, options, detailed progress, Stop, retries, logs, error-to-source navigation, latest PDF and output folder. |
| Partial compilation | Preserve fast selected-page recompilation and patching of the existing PDF, including supported links and overlays. Full rebuild plus extraction is not equivalent. |
| Import/export | PPTX and ODP import, PPTX export with supported reveal behavior, and transcript output. Show destination and actionable conversion warnings. |
| Reproducible snapshots | Capture options, dependency/environment/font/application inclusion, creation, verification, existing snapshots, manifests, and render scripts. Do not reduce this to ordinary backup. |
| Deck management | Settings, tags/groups, duplicate, archive, deck source, and archived decks. Clarify removal from a deck versus deletion of a shared slide file. |
| Course/admin slides | Course configuration, schedule/API-driven generation, supported options, and clear missing-configuration states. |
| Maintenance | PDF/temp cleanup, archive unused slides/media, regenerate previews, repair links, compatibility, and backups. Show affected items before destructive actions. |
| AI management | Connection setup, API credentials, task model defaults, prompts/style, local-only policy, and Ollama installation/model update/delete controls. |
| App management | Appearance/layout, manual/automatic updates, breaking-release handling, bundled-copy updates, version history, and help. |
| Command search | Keep Ctrl+K as the common home for commands, slide navigation, and full-text search. Preserve existing shortcut behavior and searchable aliases for renamed commands. |

Suggested consolidation: one compact Activity strip and expandable job view, with linked detail in the assistant or relevant page. Represent the same run consistently rather than creating independent status counters. Existing resource/concurrency limits remain; this does not require a new universal scheduler or persistent job database.

## 9. Required screens and prototype paths

### Design these representative screens/states

1. Main editing workspace: wide layout, global Local mode, split source/preview, collapsed and expanded inspector; repeat with the assistant hidden.
2. Global Cloud mode using Claude Code, with persistent amber header warning, terminal input, and clearly labelled task settings; include idle, running, and stopping states.
3. Cloud assistant using Anthropic API, with the native composer.
4. Focus-assistant layout and restoration to the previous workspace.
5. Structured translation task: options where needed, generating, review, applying, preview, and success.
6. Conflict and partial-success states, including applied changes with a failed preview.
7. Deck batch task with per-slide outcomes and retry-failed controls.
8. Images review page and inspector form using consistent field/action design; retain the global mode switch and Cloud warning while the assistant is hidden.
9. Compile/output selection, compact Activity, expanded jobs, and error navigation.
10. Settings for AI connections, task defaults, local-only policy, and actionable connection failures.
11. Advanced workflow sheets: reproducible snapshot, import/export, and maintenance. These can share components, but show their distinguishing options and results.
12. Small desktop layout and light/dark appearance.

### Make these paths clickable using simulated data

- Local with different configured Ollama models for vision, translation, chat, and text → Cloud/Claude Code once → show all task summaries using Claude Code → back to Local once → restore every original model and endpoint. Preserve route-specific drafts.
- Show the amber Cloud warning on the full Images page, with hidden sidebars, in transcript AI tools, and in a task dialog. Demonstrate the advanced API profile separately with its correct global label.
- Attempt to switch during a task or live terminal session; exercise the cancellation/end-session choice.
- Translate one slide → review diff → apply → inspect updated preview.
- Automatic-edit variant of the same task, with honest supported Undo.
- Change the source while a proposal is pending → conflict → compare or rerun.
- Translate a deck → mixed results → retry only failed items.
- Draft an image description → edit → mark reviewed.
- Compile → progress → failure → jump to source → retry → open result.
- Local-only policy and a missing-model/connection state.
- Expand and restore the assistant without creating another assistant window.

Do not contact real AI services, read project files, request real credentials, install software, or perform real file writes in the prototype. Use clearly simulated task results and connection states. All clickable controls in the main demonstration path should have meaningful behavior. Mark unsupported secondary interactions as specification-only.

## 10. Visual direction and accessibility

Aim for a calm, compact, professional research tool. Keep the slide and source visually dominant. Use restrained surfaces, clear hierarchy, readable typography, short labels, and contextual detail. Avoid oversized chat bubbles, excessive pill controls, decorative gradients, nested cards everywhere, and consumer-dashboard styling.

The existing desktop app uses Roboto for UI text, Roboto Mono for source/terminal, roughly 4-pixel control corners and 8-pixel panel corners, neutral surfaces, and restrained status/accent colours. You may refine this language; do not copy the earlier sketch mechanically or make the redesign depend on elaborate web-only effects.

Use English UI labels and realistic EN/DE content. Allow for longer labels and future localisation. Status must use text/icons as well as colour. Keep visible keyboard focus, sensible tab order, accessible names, and sufficient contrast in both themes. Essential actions cannot require hover.

Design desktop canvases at **1600 × 1000**, **1280 × 800**, and **1024 × 640**. Account for 125%, 150%, and 200% UI scaling by allowing layouts to reflow. The smallest target is a desktop window, not a request to invent a separate mobile app. A shareable browser prototype should still avoid clipping when viewed in a narrower container.

Keep the active input and Stop action reachable without scrolling through an entire conversation. Use independent content scrolling where needed in the real desktop layout. Do not compress text into unreadable sizes to fit more controls.

## 11. Implementation constraints and scope boundaries

The production app is **Python/PySide6 (Qt Widgets)**, with LuaLaTeX for compilation and xterm.js in QtWebEngine for the embedded terminal. The prototype may use web technologies for presentation, but the proposed components must translate sensibly into Qt. This brief does not authorize a Rust, Electron, or other platform rewrite.

Existing building blocks include a command registry, workspace state, source editor, diff cards, image forms, job panels, and background worker handling. Prefer reusing their behavior behind improved presentation. Do not specify a new universal task engine, plugin architecture, transcript database, or redesigned file format as a prerequisite.

Separate the following in your handoff:

- **Existing behavior, new presentation:** unified shell, relocated controls, focus layout, existing provider/session surfaces, current commands and progress.
- **Additional implementation needed:** authoritative global task-model profiles and app-wide switching, missing Claude Code/Ollama task adapters (including image input and structured transcript assistance), shared task-phase events, review-before-apply for structured paths that currently apply immediately, and selected-slide AI scope. The complete profile switch must cover every existing AI dispatch path before it is presented as complete.
- **Not assumed:** automatic terminal-to-chat conversion, shared provider conversation memory, universal terminal Undo, exact model progress, cross-restart conversation/job persistence, or feature parity that a particular model does not support.

Preserve safeguards for unsaved buffers, frozen versions, protected source regions, existing backups, image review concurrent with AI work, and stale preview results. A visual simplification must not remove these checks.

## 12. Sample content for the prototype

Use a fictional project named **Research methods**, with 24 slides:

- Sections: Introduction, Study design, Data collection, Interpretation.
- Selected slide: **Research questions**, ID `rqs`, English, current editable version.
- Body: “Start with a focused question.” / “Choose evidence that can answer it.” / “Explain the limits of your study.”
- Suggested German first bullet: “Beginnen Sie mit einer klar eingegrenzten Frage.”
- Missing German partner before translation; linked current partner after successful application.
- Example conflict: the user changes the first bullet to “Begin with a precise research question” while translation runs.
- Example batch: 8 eligible slides; 5 updated, 1 unchanged, 1 conflict, 1 failed.
- Example image: interview study diagram, informative, English draft available, not yet reviewed.
- Example compile: Instructor output, pass 2, 54%; show a separate failed run with an actionable source location.

Use generic configured-model labels where exact model names are not relevant. Do not invent prices, performance guarantees, account access, or unverified provider capabilities.

## 13. Requested handoff

Return:

1. **Recommended design:** the interactive prototype and representative high-fidelity screens, including the critical error and switching states.
2. **Navigation map:** where every workflow family in section 8 lives; highlight any item not yet represented.
3. **Component specification:** assistant shell, route/connection controls, scope/target indicator, task card, step display, diff review, batch results, Activity strip, inspector, and connection/error states. Include normal, focused, disabled, busy, and failure states as applicable.
4. **Interaction specification:** transitions, cancellation, preserved state, keyboard behavior, and the exact meaning of primary actions.
5. **Design tokens:** typography, spacing, colour roles, sizing, dividers, focus treatment, and light/dark variants suitable for implementation in Qt.
6. **Implementation sequence:** each stage must deliver a coherent user-visible improvement. Suggested order: global AI profiles/switch/warning and unified shell → responsive layout → task steps → review/recovery → consistent actions → surrounding workflows → settings/accessibility polish. Global routing coverage belongs in the first stage, not a later cosmetic follow-up.
7. **Assumptions and implementation gaps:** identify them explicitly instead of presenting unimplemented behavior as current capability.

Start with a short interpretation of the brief, then create the design. Do not stop at a generic advice list or a single static chat screenshot. Make reasonable design decisions without blocking on minor preferences; raise only contradictions that materially affect feature preservation or user control.

## 14. Acceptance checklist

- [ ] One Assistant area, one global Local / Cloud selector above the columns, and one visible input for the active connection.
- [ ] Cloud mode is persistently amber with an icon and explicit warning text, including idle, hidden-assistant, full Images page, narrow desktop, dark theme, and stopping states.
- [ ] One switch changes every AI task to Claude Code or restores its original Ollama model/endpoint; no stale dialog, batch, or nested task can bypass the profile.
- [ ] Deterministic transcript export and compilation do not gain AI calls; missing task capability is explicit, with no fallback to another route.
- [ ] Native local chat, cloud API chat, and the real Claude Code terminal all have a clear place.
- [ ] Users can identify the active connection/model, target, and editing policy without visiting Settings.
- [ ] Local-only policy and route switching have truthful, actionable states.
- [ ] Switching does not silently transmit local history, lose drafts, discard proposals, or hide ongoing cloud work.
- [ ] Task steps represent actual operation phases; simple actions do not become unnecessary wizards.
- [ ] Review, automatic application, conflict, Stop, partial success, retry, and preview failure are designed.
- [ ] Language browsing, translation, saving, applying, rendering, and human review are distinguishable.
- [ ] All workflow families remain accessible; advanced options are grouped, not deleted.
- [ ] The design works at the required desktop sizes and with keyboard navigation and increased UI scaling.
- [ ] Prototype simulation and backend implementation gaps are clearly identified.
- [ ] The result is practical to implement incrementally in the existing PySide6 application.
