---
name: handover
description: Propose what to do next from docs/handover.md as a checklist page the user can tick, reorder and annotate, then work on the chosen tasks in that order. Use when the user types /handover, or asks what to work on next, or to "go through the handover".
---

# /handover: pick the next tasks, then do them

The project's open work is tracked in `docs/handover.md` (not in git; it lives in the main checkout only). Its top holds a
machine-readable **Task list** block. Do not read the whole file: it is thousands of lines.

## 1. Build and publish the picker page

1. Find the main checkout (the first entry of `git worktree list`) and the file `docs/handover.md` in it.
2. Build the page into your scratchpad directory, with the script (standard library only, any Python 3):

   ```
   python <repo>/docs/handover_list.py <scratchpad>/handover-next.html --handover <main checkout>/docs/handover.md
   ```

   From a worktree whose branch lacks the script, call the script of the main checkout. It prints the number of tasks and
   their ids, and the ids that have no "Details" text (add `<!-- task:ID -->` markers around that task's text in handover.md; the
   page's Details button shows what stands between them). A "missing key" or "duplicate id" error means the block needs fixing first: fix that line, then rerun.
3. Publish the file with the `Artifact` tool: `icon: "checklist"`, `capabilities: {"artifact": {}, "comments": {}}` (artifact stores the picks, comments is what wakes this session), a one-sentence
   `description`. **Do not edit the HTML by hand**; change the task block or the template and rerun the script. Keep the page's
   URL (same file path) for later publishes in this conversation.
4. Open the page for the user with the `Artifact` tool, `action: "open"` and the URL (publishing does not always open it). Do not
   also call `show_pane`. Give the user the link in one or two lines. Say the page lets them tick tasks, drag them into order, add notes, and click
   "Start tasks". Then stop and wait: nothing starts before that click.

## 2. When the picks or an update arrive

"Start tasks" makes the page republish itself, with the picks stored in its state as `"sent":{"ids":[...],"picked":[{"rank","task","note"}]}`.
The page has two buttons. **Update** sends only the changed notes (a comment starting "UPDATE ONLY"): do not start any task. Write each
note into that task's `notes` field in the TASKS block of `docs/handover.md` (the next page build preloads it) and, where it fits,
into its section; close the picker pane as in step 0 below only if the user is done, otherwise leave it; answer in one line.
**Start tasks** sends the picks (steps 0 to 6 below). A republish alone starts no turn. The page therefore also sends the picks to this session as a comment ("Send to Claude",
editors only; the user may be asked to allow it once), which wakes the session with the picks in the comment text. If the page
says it could not notify Claude, the user tells you in chat. Either way, then:

0. Close the picker for the user: `mcp__ccd_view__close_pane` with `pane: "artifact"` (load it with ToolSearch if it is deferred).
   A page cannot close its own pane. Do this first, before reading or working.
1. `Artifact` action `read` on the URL, and take `sent.picked`: it is in the user's order, each with its note. If `sent` is
   `null`, nothing was sent yet.
2. Say in one line which tasks you start and in what order.
3. For each picked task, in that order: read only the handover section its `src` points to (grep for the heading), plus the
   "Working rule" and "How to work" parts of the section it sits in. The user's note refines or overrides the task text.
4. Do the task. Apply the file's standing rules (a worktree and branch per step from `origin/develop`; bump the version with
   app-code commits; merge only on the user's go; never touch the main checkout's `latex/`). If the note leaves a decision the
   task text says to ask about open, ask before building.
5. After each step, update `docs/handover.md`: the task's line in the TASKS block (`status`: `done` or `blocked`, and a
   changed `desc` if the scope moved) and its section, as the working rule says. Re-read the lines right before editing:
   other sessions append to this file.
6. Independent tasks may go to their own sessions or subagents where the session rules allow it; tasks that touch the same
   files go one after another.

## 3. Keeping the list useful

- New work the user names: add a line to the TASKS block (stable `id`, never reused) and wrap its text in task markers before starting it.
- Finished sections move to `docs/handover-archive.md`, unedited; ask the user first.
- The page template is `docs/handover_list.template.html`. Its script keeps the `/*S*/ ... /*E*/` markers around the state
  and `__STATE__` is the placeholder the script fills: keep both when changing it.
