# PR #146: the Preview flickers to "Checking…" every 5 seconds

Findings for Jürgen, from testing a Windows build of PR #146 (head `e519f713`, v0.15.0). Written 2026-11-10.

## Symptom

A slide shown in the Preview (here `tth`, "Introductory Matter", through its `tth-mult-…` temporary render) flickers to "Checking current source and settings…" every few seconds, then returns to the "Temporary preview" view. "Render now" shows "Rendering…" and then falls back to the same loop.

## What the debug log shows

Debug log on, one window, a slide that is open and not changing. The new `slidemage.preview` lines (added to a scratchpad copy, not to the PR) show a repeating cycle, about every 5 seconds:

```
poll: stored state=missing checking=False
image: tth-mult-… stored_here=True state=missing checking=True adhoc_here=True    <- "Checking…" shown
image: tth-mult-… stored_here=True state=missing checking=False adhoc_here=True   <- "Temporary preview" again
```

`state=missing` never changes: the render store has no entry for this slide, so every lookup returns the same answer.

## Cause

1. **The validation poll clears the last lookup even when nothing changed.** `_validation_poll` (5 s, `ui/workspace/preview_view.py:477–480`) calls `_poll_selection` (line 643), which sets `self._stored_asked = None` (line 645). The next `_image` call therefore starts a new `_look_up('page', …)`.
2. **While that lookup runs, the view shows "Checking…".** `_checking()` (line 953) is true while `'page' in self._lookups`, so the stored-result branch in `_image` (line 693, `and not self._checking()`) is skipped and `CHECKING` is returned. This is the flicker.
3. **The lookup never becomes "current" for a slide rendered without its deck.** The store returns `missing`, the code falls back to the temporary render, and the cycle repeats on the next poll.

On develop the same 5-second poll exists (`_poll_selection` also clears `_stored_asked`). The difference is that in the PR the lookup for this slide keeps coming back `missing`, so the "Checking…" state appears on every poll.

## Suggested fix (not written into the PR)

- In `_image`, when the stored result has the same identity (`self._stored[0] == ident`) and only a re-check is pending, keep showing the stored result and replace it when the lookup returns. Show "Checking…" only when the content (`ident`) has changed.
- Optionally, don't clear `_stored_asked` in `_poll_selection` when the slide's identity is unchanged and the last result was `missing`.

## Not verified

- Only the one slide was observed, and only on Windows. The cause comes from the log and the code, not from a test that reproduces it.
- The same debug log has no entries for the "Render now" path.

## Also seen on the PR head (for the same run)

Full suite on `e519f713`: 4478 passed, 77 skipped, 5 failed.

- Fail every time, new in the PR:
  - `tests/test_background_renders.py::test_a_compile_with_an_input_changed_during_it_imports_nothing`: a compile record is written where the test expects none.
  - `tests/test_background_renders.py::test_a_dependency_edited_during_the_render_is_never_stored`: a render result is returned where the test expects none.
  - `tests/test_render_evidence.py::test_inventory_stays_current_only_when_changed_names_cannot_affect_its_inputs`: `media/` is missing from the inventory.
- Flaky: `tests/test_presentation_gui.py` eraser and projector tests. They pass when run alone, on develop and on the PR head, and fail only in the parallel run (`-n 4`).
