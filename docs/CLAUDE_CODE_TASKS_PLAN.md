# Claude Code does SlideMage's AI tasks, fast

Status: plan, 2026-10-12, revised after review. Needs the user's go per step; pause after each committed
step. Scope: SlideMage's **Claude Code tab**, using the user's installed `claude` and subscription.
Selection rewriting, visual checks, deck reviews, structural edits and audience adaptation moved to
[CLAUDE_CODE_REVIEWS_PLAN.md](CLAUDE_CODE_REVIEWS_PLAN.md), which starts after step 6 here.

Cost figures are rough estimates from the usage calibration (~5% of a 5-hour window per ~100k agent
tokens); re-estimate after step 1.

**Goal.** Translate, update a translation, fix LaTeX errors, describe images, proofread, shorten,
retitle and add speaker notes with one click on a suggestion bubble. The tasks need no exploration by
the model or questions back, and return a short result. Correct edits, no lost user work and good
translations count as much as speed.

## Decisions

| Decision | Value |
| --- | --- |
| Model | **Sonnet, effort medium** by default (`--model sonnet --effort medium`), chosen by the step-1 benchmark: fastest (translation median 6.5 s, fix 2.5 s) and at least as good as Haiku. A picker in the tab switches model and effort, remembered per user, applied to the next task. |
| How a bubble runs | A separate **`claude -p` process per task**, not text typed into the terminal: the app knows when it is ready, done, failed or cancelled. Every task starts with a fresh context. |
| Isolation | A task loads nothing it does not need: `--system-prompt` with the task's rules **replaces** Claude Code's default system prompt; `--setting-sources ""` skips the user's and project's settings, hooks and plugins; `--disable-slash-commands`; the process runs in a neutral working directory so no CLAUDE.md or memory is loaded. Step 1 confirmed it: login and structured output work, about 24x fewer input tokens and faster than a default `claude -p`. |
| Result format | **Structured output** with `--json-schema`, no tools. Translations, shortening, titles and notes return the new body or part (`{"body": "..."}`). Proofreading and LaTeX fixes return an **edit list** (`{"edits": [{"before": "...", "after": "..."}]}`; empty means nothing to change), so a long slide is not echoed back for three small fixes. Each `before` must occur exactly once in the captured text, otherwise the result is invalid. Step 1 confirmed the edit list: faster than a full body, which changed unrelated text in 3 of 5 slides. |
| Images | Image descriptions also return structured output (`{"images": [{"path", "short", "long"}]}`); SlideMage saves them. The images go **inline as image blocks** through `--input-format stream-json` (step 1 confirmed the model receives them); no MCP tool reads or writes them. |
| Terminal | Stays for free-form work and follow-ups with its own conversation. It does not see the bubbles' tasks. |
| Progress | A status line in the tab while a task runs: "Translating 1f8 … 6 s", then "Done in 9.2 s" or the failure. Stop ends the task. |
| Deadlines | Text tasks 60 s (step 1's slowest run: 13 s), image descriptions 120 s per slide until step 4 measures them. |
| German address | **Sie**, project setting `de_address: "Sie" \| "du"` in `.slidemage/project.json` (the existing DE slides use Sie). Put into every translation request; never left to the model. |
| Terminology | Optional `.slidemage/glossary.md` (`EN = DE` lines), put into translation requests as-is. |
| Edits | SlideMage applies them with its existing code (`ai/tools/edits.py` `write_text`, `GuiWorkspace.apply_to_buffer`): open files change in the buffer (Ctrl+Z undoes), closed files are saved with a backup, protected parts (header, `\setSlideVersion`, overlay blocks) are checked. |
| Permissions | Bubbles need no Claude permission prompts: the model has no write tools. Claude Code's normal prompts stay for edits typed in the terminal; no global `acceptEdits`. |
| Previews | SlideMage renders the slide after a change it applied; there is no model-driven render loop. |
| Batches | Two workers, only after step 5's conflict and rate-limit tests pass. |
| Not used | `--bare`: it skips subscription (OAuth) login and needs an API key. |

## Why it should be faster

The 37-second "add that this is windows only" run spent its time on a focus lookup, reading the file,
4 shell commands, a failed built-in Edit (Claude Code refuses an Edit of a file not Read in the session),
a retry, lint, a render and a long answer. A bubble task removes that model-driven work:

- The request carries everything: the slide text from the buffer (unsaved edits included), its path,
  the lint errors, the rules. No lookup, no Read, no exploration.
- No tools, so no tool round trips: one model turn returns the result.
- No default system prompt, user settings, hooks or plugins to load (see Isolation).
- Edit lists keep the output short where only a few words change.
- SlideMage lints the result before applying it and renders afterwards.
- The answer is the JSON result; SlideMage writes the one-line status itself.

What each lever actually saves (isolation, model choice, effort, output format, process start-up) is
measured in step 1, not assumed.

## A task, start to finish

1. **Capture** on the GUI thread when the bubble is clicked: task, target path, the target's text as
   the buffer has it, model/effort, rules. Later focus changes do not change the task.
2. **Run** `claude -p --model … --effort … --tools "" --strict-mcp-config --setting-sources ""
   --disable-slash-commands --system-prompt … --no-session-persistence --output-format stream-json
   --verbose --json-schema …` in a neutral working directory, the request on stdin (an image task sends it
   as stream-json with `--input-format stream-json`). The flags were confirmed against the installed CLI
   in step 1.
3. **Validate** the result: valid JSON, every edit's `before` found exactly once, protected parts
   unchanged, no new lint errors. One repair attempt at most, with the errors in the request.
4. **Apply** only if the target still has the captured text. The whole target is compared, on purpose:
   typing anywhere in the slide meanwhile counts as a change. Nothing is overwritten; the status says
   "The slide changed while Claude worked" and offers to show the result, which the user can copy in
   by hand.
5. **Render** the preview and show "Done in N s".

Outcomes: done, nothing to change, failed (login missing, process error, bad output, timeout),
conflict, cancelled. Stop or the deadline ends the process; a late result is dropped. One foreground task
at a time.

## Translation

- **Create the partner only after the translation succeeded:** run the task on the source text, validate
  it, then create the DE slide (`slide_add` with `translation_of`, placed right after the source: the
  placement fix of UI plan section 2) and link both headers in one step. A failed task creates nothing,
  so no English copy is ever shown as the German translation.
- **The source header** is written through `apply_to_buffer` with the same freshness check as any other
  edit: if the source is open with unsaved edits, the link goes into the buffer; if the source changed
  since capture, the partner is not created and the task ends as a conflict.
- **Update:** the request has the current source and translation; the result replaces the translation's
  body if the translation is unchanged since capture.
- **Outdated** stays as `slide_language.translation_link()` computes it today (timestamps). Recording
  which source version a translation was made from belongs to the version-graph plan (UI plan
  section 5, step G2) and is not part of this plan.

## Bubbles

SlideMage computes which bubbles apply from the focus and checks again on click. Bubbles are hidden while
a task runs.

| Slide bubble | Shown when | Request and result | Step |
| --- | --- | --- | --- |
| Translate to German / English | no partner in the other language | source text + rules → translated body | 2 (DE), 3 (EN) |
| Update German / English translation | the partner is outdated | source + translation → updated body | 3 |
| Fix LaTeX errors | lint reports errors | text + errors → edit list | 2 |
| Proofread | slide has prose | text + language rules → edit list of spelling, grammar, punctuation and capitalization fixes, preserving meaning, formulas, citations and LaTeX | 3 |
| Make more concise | slide has text | text → shorter body, same structure | 3 |
| Better title | the frame has a title | text → new title only | 3 |
| Add speaker notes | no `\note` yet | text → one `\note{...}` | 3 |
| Describe images | images without a description | slide context (`alt_draft.build_context`) + the images → short/long description per image | 4 |
| Translate image descriptions | DE descriptions missing | EN descriptions + glossary → DE descriptions | 4 |

Deck bubbles (step 5): Translate missing slides (n), Update outdated translations (n), Fix LaTeX errors
(n slides), Describe images (n), Summarise this deck. Counts count each slide and each shared image once.

## Benchmark

On a **disposable copy** of the demo project (never the working example), with 5–6 representative
slides: short and long text, formulas, citations, overlays.

- Setups: isolated (see Isolation) vs. default `claude -p`; Haiku low / Haiku medium / Sonnet medium;
  full body vs. edit list for LaTeX fixes and proofreading; a fresh `claude -p` per task vs. one
  long-running `claude -p --input-format stream-json` process (to learn what process start-up costs).
- One check, not a setup: an inline image block through stream-json input reaches the model.
- About **5 runs per setup and task**; report the median and the slowest run, failures, turns, tokens.
- Times from click: first output, result validated, buffer changed, preview ready.
- Goal (not a promise): median click-to-buffer-changed **≤ 15 s** for one slide.
- Quality check per run: German with Sie and the glossary terms, nothing left out, LaTeX and protected
  parts intact, no new lint errors; proofreading of already-correct text yields no edits.

Lifecycle tests use a fake `claude` (the one in `tests/fake_claude.py`), so they are fast and fixed:
focus change during a task, typing in the target, Stop, late result, bad JSON, an edit whose `before`
is missing or ambiguous, failed login, failed translation creates nothing, source changed before the
partner is linked.

## Steps

| Step | What it does | Touches | Cost (estimate) |
| --- | --- | --- | --- |
| 0 Commit what exists | Commit the Source/Preview divider and the Slide/Deck scope switch (only those files; the working tree has unrelated edits). | `centre.py`, `kit_qss.py`, terminal view/session, `claude_scope.py`, hooks, tests | ~5k, <1% |
| 1 Prototype and measure | Task runner (`claude -p` with isolation, capture, validate, apply-if-unchanged, Stop, deadline), translation and lint fix as the first two tasks, run from a command-line tool on the disposable copy; the benchmark above; pick the defaults (model, effort, isolation, output format, deadlines, image input). | new `ai/claude_tasks.py` (pure: request text, schema, validation, edit lists), new `ai/claude_runner.py`, `tools/claude_task_benchmark.py`, report | ~80-120k, 4-6% |
| 2 Bubbles in the tab | Bubble row, status line with Stop, model/effort picker, Sie and glossary settings, preview after apply; the two tasks from step 1, translation creating the partner only on success. | `terminal/view.py`, runner, `slide_add.py`, Settings -> AI models | ~60-90k, 3-5% |
| 3 More slide tasks | Update translation, Translate to English, proofread, concise, title, speaker notes. | `ai/claude_tasks.py` | ~35-55k, 2-3% |
| 4 Image descriptions | Describe and translate bubbles with inline images; SlideMage saves the descriptions; the Images panel refreshes. | `ai/claude_tasks.py`, runner, `alt_images.py`, `alt_draft.py`, Images panel | ~40-70k, 2-4% |
| 5 Deck batches | Two workers on the same runner, writes one at a time per file and for shared data (ids, links, `alt-text.json`), progress and Stop in the job panel. Tests: two workers, user typing, duplicate partner prevented, the subscription's rate-limit and concurrency errors (back off to one worker, report it). | new scheduler, job panel | ~70-100k, 4-5% |
| 6 Measure again | The step-1 benchmark through the real UI; update defaults and the report. | benchmark, report | ~20-30k, 1-2% |

Total: about 310-470k agent tokens, 16-24% of a window, before re-estimating after step 1. Execute the
steps in table order; each still needs the user's go as stated above.

## Not doing

- No `/clear` or prompt typing into the terminal for bubbles.
- No write tools for the model in bubble tasks; SlideMage validates and writes.
- No replacement of the Ollama paths (Images page, Translate dialog, chat); they stay.
- No API key, no global edit permission, no automatic switch to a bigger model.
- Selection tasks, visual checks, deck reviews, structural edits and audience adaptation: see
  [CLAUDE_CODE_REVIEWS_PLAN.md](CLAUDE_CODE_REVIEWS_PLAN.md).

## References

- [Headless mode and structured output](https://code.claude.com/docs/en/headless)
- [Hooks](https://code.claude.com/docs/en/hooks): why a Stop hook is not a reliable "done" signal
- [CLI reference](https://code.claude.com/docs/en/cli-reference); check flags against the installed
  version (2.1.296 on 2026-10-12)
