# Claude Code reviews, selections and structural edits

Status: follow-up plan, 2026-10-12, split from the (finished, removed) Claude Code tasks plan.
Starts after that plan's step 6. Needs the user's go per step; pause after each committed step. Costs
are estimated before each step, using the measurements from the tasks plan.

**Goal.** Rewrite selected text; check a slide's visual layout; review a deck for consistency, flow and
references; split slides and apply reviewed flow changes; adapt slides to an audience. These produce
findings or proposals the user inspects before anything changes.

Everything from the tasks plan applies: one isolated `claude -p` per task, structured output, captured
inputs, SlideMage validates and writes, nothing applied over newer user work.

## Review and approval

- Selection rewrites use the tasks plan's checked apply-and-undo flow.
- Visual checks and deck reviews return findings first. Structural changes and fixes from a deck-wide
  review show a proposal with diffs and affected slides; the user selects fixes and applies them with an
  explicit Apply action in SlideMage.
- A proposal keeps its captured inputs. Apply repeats validation and freshness checks before any
  change; a stale proposal is reported as a conflict. Receiving or displaying a proposal never changes
  files.

## Actions

| Action | Scope | Result | Priority |
| --- | --- | --- | --- |
| Rewrite selected text | nonempty editable selection | selected text + surrounding context + simplify/shorten/custom instruction → replacement for the selection only | High |
| Proofread selection | nonempty editable selection | edit list limited to the selection | High |
| Check visual layout | an editable slide that can be rendered | captured source + matching preview + compile diagnostics → findings about clipping, crowding, small text and awkward spacing, with a reviewable single-slide fix | High |
| Fix LaTeX errors from compile diagnostics | slide with TeX errors | extends the tasks plan's lint-based bubble to compile errors | High |
| Proofread selected slides / deck | deck | small prose fixes using the batch runner, with per-slide outcomes and undo information | High |
| Check deck consistency | deck | findings with slide IDs and excerpts for inconsistent terminology, abbreviations, title styles, notation and EN/DE glossary usage; optional fixes selected by the user | High |
| Review deck flow | deck | findings about repeated material, missing explanations, abrupt transitions and concepts used before introduction; a proposed order with reasons, without moving slides automatically | Medium |
| Check citations and references | deck | deterministic checks for unresolved citation keys and broken slide references, plus findings for figures without source attribution and claims that may need support; never invents bibliography entries or claims external fact verification | Medium |
| Split this slide | editable slide with content | proposal for two titled slides, distributing content, notes and citations; applied only after review | Medium |
| Adapt to audience | slide, selection or selected slides | explicit beginner/specialist/executive/custom audience chosen before generation → reviewed rewrite preserving claims, caveats and references | Later |

Show only actions relevant to the current slide, selection or deck.

## Supporting tools

These are additions to the Claude MCP surface and app services. Bubbles do not get them: SlideMage
captures selections and applies results itself. The **terminal** uses the MCP tools under its normal
edit permissions; the app services are shared by both.

| Capability | Contract and reuse | Needed by |
| --- | --- | --- |
| Read selection and context (MCP, terminal) | Return the captured path, selected range, exact selected text, surrounding text and buffer revision. Reuse `read_buffer`; reject a selection crossing protected regions. | Terminal selection work |
| Apply a checked buffer edit (MCP, terminal; app service for bubbles) | Expose the existing buffer-aware edit machinery. Require expected text/revision, enforce current-file and protected-region rules, preserve undo, fail on conflicts. Closed files keep backups. | Safe terminal edits; shared apply service |
| Read compile diagnostics | Structured errors and warnings with file/line, slide occurrence, severity and the source snapshot that produced them. Reuse compiler results and `render_preview`; distinguish static lint findings from TeX errors and layout warnings. | LaTeX fixes, visual checks, reference checks |
| Safe deck operations | Insert, move, duplicate and split through existing app services, with a reviewable proposal. SlideMage allocates IDs and maintains links, ordering, version pins, visibility conditions and reveal steps. A deck occurrence is identified separately from its slide ID. | Splitting slides and applying flow proposals |
| Apply and undo a group of changes | Capture all affected buffers, files and shared metadata; validate them together before committing. Roll back a partially failed group. Undo the group only if its affected content is still unchanged; otherwise report a conflict without overwriting later work. | Structural changes and selected fixes from deck reviews |

## Rules per area

**Selections.** Capture the selected range and its surrounding text at click. Everything outside the
range stays untouched. As in the tasks plan, any change to the target after capture blocks the apply.

**Visual checks.** SlideMage prepares the preview and diagnostics from the captured buffer before the
model runs; there is no model-driven render loop. The preview image goes inline like the tasks plan's
image descriptions. Match every image and diagnostic to the captured source; reject stale render
results. A compile failure is a diagnostic result. An unsupported visual model is reported, with no
automatic model upgrade. Findings are suggestions, not a guarantee that every layout problem was found.
Measure rendering and model time separately; deadlines are set per task after measuring.

**Deck reviews.** Respect the selected language, versions, visibility and ordering. Preserve repeated
slide occurrences when reviewing flow; deduplicate edits to a shared slide file and show which other
decks use it before applying. Frozen slide versions remain read-only. For large decks, use bounded
sections and report the review's coverage; never omit slides silently or present a partial pass as
complete.

**Splitting.** The proposal states how notes, overlays and shared-slide usage are handled.

**References.** Work against the project's bibliography and slide targets. External source research
and factual verification are separate future work.

## Acceptance checks

- Selection rewriting and proofreading leave every character outside the captured range untouched and
  refuse application after an intervening buffer edit. Already-correct text yields no edits.
- Visual checks use an unsaved buffer's matching preview, handle failed compilation, and discard a
  preview that finishes after cancellation. Fixtures include overflow, dense text and reveal steps.
- Deck findings identify the relevant slides and excerpts. Consistency checks use the configured
  glossary; reference checks distinguish missing keys from claims that merely need a source.
- Proposals do not mutate anything before Apply. Tests cover repeated slide occurrences, shared slides,
  dirty deck buffers, frozen versions and input changes while a proposal is being reviewed.
- Grouped edits and structural operations survive injected failure between writes without leaving
  partial IDs, files or links. Group undo restores the prior state and refuses to overwrite later edits.
- Audience adaptation retains numbers, qualifications, formulas and references.
- Latency and quality are reported separately for selection tasks, visual checks and deck reviews. The
  tasks plan's 15-second target does not apply to them.

## Steps

| Step | What it does | Touches |
| --- | --- | --- |
| R1 Selections | Selection capture; rewrite and proofread selection; the shared checked-apply service; the two terminal MCP tools. | tasks, `ai/tools/`, source editor, `GuiWorkspace`, terminal view |
| R2 Diagnostics and visual checks | Structured compile diagnostics; LaTeX fixes from them; preview from captured source; layout findings and a reviewable single-slide fix. | compiler diagnostics, preview integration, tasks, proposal UI |
| R3 Deck reviews and grouped changes | Batch proofreading; consistency, flow and citation/reference reports; proposal UI with selected fixes and grouped apply/undo. Flow stays a proposal until R4. | tasks, scheduler, bibliography/reference checks, proposal UI, shared apply service |
| R4 Structural operations | Safe insert/move/duplicate/split services and MCP tools; Split this slide and applying reviewed flow proposals. | `ai/tools/`, deck editor, slide creation, shared apply service |
| R5 Audience adaptation | Audience selector, adaptation of a slide or selected slides, reviewed proposals and preservation checks. | tasks, audience settings, proposal UI |
| R6 Measure | Latency and quality of the added tasks, including review and apply time. | benchmark, report |

Each step gets a cost estimate before it starts.
