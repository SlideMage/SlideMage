---
name: finish
description: End a work session cleanly. Mid-work - stop and write the handover so another session can continue. Work done - commit, push, open and merge the PR (with --admin if needed), clean up, then update the handover, recording any cleanup that failed. Use when the user types /finish, or says to wrap up, finish, or end the session.
---

# /finish: leave the work so the next session can continue

The handover lives in `docs/handover.md` of the SlideMage **main checkout** (`D:\Dropbox\repos\SlideMage`, the first entry of
`git worktree list`; the file is not in git). It covers the plugin, theme and website repositories under `D:\Dropbox\repos\`
too, so update that file whichever repository you worked in. Read its top part (up to the end of the TASKS block and the
"Working rule") and the section of your task (grep for the heading); never the whole file. Re-read the lines right before each
edit: other sessions write to it too.

## 0. Decide which case this is

Stop starting anything new. Look at what you were doing: `git status`, `git log origin/develop..HEAD` (or the repo's
default branch) in every worktree you touched, your task list, background commands and sessions you started.

- **Mid-work**: the task is not done, tests fail or were not run, the user still owes a decision, or a step is half built. Go to A.
- **Done**: the latest work is finished and checked (tests run and passing). Go to B.

If unsure, treat it as mid-work: a clean handover is never wrong; a merge of unfinished work is.
Say in one line which case you take.

## A. Mid-work: stop and hand over

1. Stop running work: cancel background commands you started (`TaskStop`), do not wait for them. Leave sessions you started
   running unless the user says otherwise; name them in the handover.
2. Save the work without merging: commit what exists on the work branch as a WIP commit (`WIP: <what>`; no version bump
   needed for WIP) and push the branch, so nothing lives only in a worktree. Never commit on develop or main. If committing is
   not possible (conflicts, broken state), leave the files and say exactly where they are.
3. Update the handover (see "Writing the handover" below) with status **in progress**: what is done, what is half done,
   the exact next step, the branch, worktree path, last commit, PR number if any, failing tests with their names, open
   questions for the user, and anything you learned that is not obvious from the code.
4. Do not remove the worktree. Report in a few lines: branch, where the handover entry is, the next step.

## B. Done: ship it, clean up, hand over

1. **Commit.** All changes of the task, on its branch (never on develop/main; branch first if you are on one). App-code
   commits bump the version and append the CHANGELOG entry, as "How to work" in the handover says. End commit messages with
   the attribution line the system gives.
2. **Sync and push.** `git fetch origin`; if `origin/develop` moved, merge it in, renumber the version if it was taken, and
   rerun the tests that matter (`tests/test_preview_equivalence.py` after any renumbering). A failing test stops here: switch
   to case A.
3. **PR.** Open one against `develop` (the repo's default branch for other repositories) if none exists, with the attribution
   line the system gives. Bind it with the ccd_pr tools.
4. **Merge.** `/finish` is the user's go to merge. Run, as a bare command, `gh pr merge <n> --admin --merge` (plain
   `gh pr merge <n> --merge` first only where no ruleset blocks it). If the merge fails (conflict, required check, missing
   rights), do not force anything else: note it as a leftover and go on with cleanup of what is safe.
   Do not tag or release unless the task says so.
5. **Clean up**, each step on its own so one failure does not stop the rest. Run each deletion as its own single command, so
   the user can approve it with one click if a safety check asks (the Cleanup section's standing rule):
   - `git worktree remove <path>` for the task's worktree (from the main checkout; not the one you are standing in, cd out first;
     on Windows a locked folder may fail: note it).
   - Delete the merged branch locally (`git branch -d`) and remotely if GitHub did not (`git push origin --delete <branch>`).
   - Update the main checkout: `git -C D:\Dropbox\repos\SlideMage pull --ff-only` on develop (only if it is on develop and clean).
   - Close panes you opened (picker page, browser preview) and stop dev servers you started.
   - Remove your scratch files in the repository (not the user's untracked files: list those instead of deleting).
6. **Update the handover** (below) with status **done**: PR number, merge commit, version, what was verified and what was not
   (e.g. "not checked in the real app").
7. **Failed cleanup goes to the handover's standing "Cleanup" section** (`# Cleanup`, between its `<!-- task:cleanup -->`
   markers, under "Pending items (newest last)"), not into the task's section: one item per failed step, appended at the end,
   with the date, the exact path or branch name, the error, and the single command that finishes it. In the task's own
   section write only "cleanup left: see Cleanup". Never delete the Cleanup section or its `cleanup` line in the TASKS block.
   If a step finishes an item already listed there, remove that item and say so in the line it came from.
8. Report in a few lines: what was merged, version, what went to Cleanup.

## Writing the handover

- The task's line in the TASKS block: `status` (`open` while in progress, `done`, or `blocked`), and `desc` rewritten so it
  alone says where things stand and what is next. A task you worked on that has no line gets one (stable new `id`, a `run`
  recommendation, no `pin`) and `<!-- task:ID -->` / `<!-- /task:ID -->` markers around its text.
- The task's section: its status line and a dated paragraph (`**2026-..-.. (finish):**`) with the facts from A3 or B6. Absolute
  dates, full paths, branch names, PR links as `SlideMage/<repo>#<n>`.
- Section 13's overview (the cross-section summary), as the working rule asks.
- Follow-ups you found go in as new TASKS lines, not as loose prose.
- Write for a session that has none of this conversation: no "as discussed", no pronouns pointing at the chat.
