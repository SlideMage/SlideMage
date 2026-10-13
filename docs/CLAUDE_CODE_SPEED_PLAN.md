# Claude Code free-form tasks: speed and reliability plan

Status: plan, 13 October 2026. Based on the Codex review (gpt-6-astra, xhigh) of v8.3.8 on branch
`streamlining`: a free-form request such as "draft a slide about X and insert it after slide Y" takes
an estimated 15–50 s in about six model turns (skeleton → read → edit → lint/render → show), and a new
slide is not guaranteed to reach the preview pane. Implementation by Codex (gpt-6.1-sol, high), one
step at a time; the orchestrator verifies and commits each step; pause for the user's go after each.

Not adopted: separate model/effort pickers for the terminal and the tasks (the user chose on
12 October that the picker sets both).

## Rules for every step

- Work only in `/home/juergen/github/SlideMage-streamlining`; no commits (the orchestrator commits).
- Tests: `QT_QPA_PLATFORM=offscreen PYTHONPATH=$PWD/src /home/juergen/github/SlideMage/.venv/bin/python -m pytest -q -p no:cacheprovider`
  (v8.3.8: 1,877 passed, 8 skipped). Lint: `/home/juergen/github/SlideMage/.venv/bin/ruff check src tests tools`.
- Each step patch-bumps `VERSION_NUMBER` in `src/slidemage/version.py` and appends a
  `src/slidemage/CHANGELOG.md` entry ending with a `NEW:` paragraph (format as v8.3.8).
- Goals stay as in the streamlining run: clean structure, fewer lines, no feature loss. Every
  correctness fix gets a regression test. No paid API calls in tests (fake Claude/MCP clients).

## Steps

| Step | Work | Expected effect |
| --- | --- | --- |
| C1 | **Cheap correctness and instruction fixes.** `add_slide`: an insertion failure after the slide file exists returns `isError` with the existing slide id and an idempotent way to insert it (no second slide on retry); recheck the deck's dirty state at commit. `ORIENTATION` and the scope context agree on `get_focus`; terminal-facing tool descriptions/results name only tools the terminal has (no `edit_file`); recommend batching independent reads. `publish_focus` sets `_published` only after a successful write. Project watch ignores `_slidemage_preview-*.tex` wrappers. | 1–2 fewer model turns; no duplicate slides |
| C2 | **Freshness.** MCP reads (`current_text`: lint, render, read_buffer) reload a clean open buffer whose file changed on disk before using it, and report which revision was checked. Background "Included in decks" header regeneration writes with an expected-text check (retry on change) so it cannot restore an older slide body. | No stale lint/preview; no lost edits |
| CR | **"Not reviewed" label for every change by Claude** (user, 13 October). A slide file that Claude created or changed — drafts (`add_slide`, later `create_slide`), translations (headless translate task, translation partners), headless rewrite/title/other tasks, the chat agent's edits and the terminal's native Edit/Write/MultiEdit — is marked *Not reviewed* until the user marks it reviewed. Stored per project in `.slidemage/` (JSON via `fileio`; path → who/what/when and the text hash at marking), not in the slide source. Terminal native edits are recorded by a PostToolUse hook (or equivalent) without racing the app's own writes. Shown as a chip in the slide list and on the Details pane / inspector, with a *Mark reviewed* action (command registry, also for several slides) and a slide-list filter. A later user edit does not clear the mark by itself; frozen versions are never marked. Deck files changed by Claude (inserted calls) are noted in the slide's mark, not labelled separately. | The user sees what Claude wrote and still has to check |
| C3 | **`create_slide` composite tool** for the terminal (marks the new slide *Not reviewed*, step CR): `create_slide(title, slug, body, deck, after, …)` — Claude passes the full LaTeX body; the tool checks it (lint, protected regions, structure), creates id/file and inserts the deck call as one operation with explicit deck identity (rollback on failure), renders once, shows the slide and returns path, status, lint findings and the preview image. Orientation and guides point free-form creation at it; `add_slide` stays for skeletons. | 3–4 fewer model turns (est. 6–25 s) |
| C4 | **One render for Claude and the pane.** MCP `render_preview` goes through the preview pane's request path (same acceptance checks: generation, target, view, language, source revision) and publishes the accepted image to the pane; matching in-flight requests are shared. Stopping or restarting the terminal cancels its pending render (cancel token through build-lock wait and latexmk). | One preview build instead of two (est. 2–15 s); preview always shown |
| C5 | **Light hooks and timing.** `claude_hook` dispatches `UserPromptSubmit` without importing the tools package; protection helpers move to a small dependency-light module (measured ~213 ms per hook now, ~30 ms possible). Optional timestamps (prompt, tool start/end, write, render done, pane published) behind a debug setting, so prompt-to-preview time can be measured. | ~0.3–0.4 s per request; measurable latency |
