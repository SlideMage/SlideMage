# develop v0.15.2: step renders of a slide that needs its deck never stop

For Jürgen. Found on 2026-11-10 while testing the Windows build of develop at v0.15.2 (`2e1380cf`, which includes PR #146 and PR #148). Related to the flicker notes in `docs/pr146-preview-flicker.md`.

## Symptom

- The slide `tth-mult-Introductory-Matter-Section-Overview` ("Introductory Matter", a `mult` slide) keeps being re-rendered in the background, every 6 to 10 seconds, with no clicks needed.
- This continues while the user is on another slide. The app has shown `slide id=ejm` since 13:21:26, and the step renders for `tth` continued at 13:29:14, 13:29:24 and 13:29:34.
- Each step render starts a `latexmk` run of about 3.7 seconds. The background renders show "waiting for a compile", so other previews wait behind them.
- The IA2 deck compile (instructor, during-course and after-course, 397 slides) also stalled in the app: its progress line has read "PASS: render of tth-mult-Introductory-Matter-Section-Overview" since 13:22:19. Its TeX log kept advancing (page 253 at 13:27), so the job was running, not stuck.

## What the log shows

In the debug log of the session that started at 08:11 (`%LOCALAPPDATA%\SlideMage\logs\debug`), there are 65 `preview requested … step-renders` lines, all for `tth-mult-Introductory-Matter-Section-Overview`. Each one is followed by a `process started cmd='latexmk …'` and a `preview.delivered`.

## Likely cause (code on develop, `src/slidemage/ui/workspace/preview_view.py`)

Not confirmed by a test.

1. `_probe_steps` (lines 1214–1224) asks for a slide's steps when its key is not in `_step_pages` and not in `_step_failed`.
2. `_poll_selection` (lines 643–648), which runs every 5 seconds from `_validation_poll`, empties `_step_pages` except the draft entries.
3. So after every poll, the probe finds `tth`'s steps missing and renders them again. The render's result is never stored for this slide, so the cycle does not end.

Why this slide: it needs its deck (`needs_context`, see `preview_target.py`). Rendered on its own, its steps can't reach a stored `current` state (see `docs/pr146-preview-flicker.md`). Its failure is not recorded in `_step_failed` either, so it counts as "missing" again on each probe.

Still open: why the requests continue while `ejm` is selected. Either `tth` is still the Preview's target, or a neighbour of `ejm` is `tth` and the probe's neighbour loop (lines 1228 onward) asks for it. The log does not say which.

## Suggested fix

- Remember the keys for which steps were requested in this session, not only the ones stored, and don't request them again unless the slide's text or mtime changed.
- Keep `_step_pages` across polls unless the slide's identity changed. `_poll_selection` should not clear it on every 5-second tick.
- For a slide that needs its deck, either render its steps in the deck (`render_in_deck`) or record it in `_step_failed` when standalone steps can't be verified.
- Check which slide the neighbour loop in `_probe_steps` asks for, and stop it from asking for slides that are not visible.

## How to reproduce

1. Open the deck with the slide `tth` and select it. Wait about a minute; the Preview shows "Temporary preview".
2. Select `ejm` or another slide.
3. Watch `%LOCALAPPDATA%\SlideMage\logs\debug\app_*.log` for `step-renders preview requested target='('slide', 'tth-mult-Introductory-Matter-Section-Overview'`. Requests keep appearing about every 10 seconds.

## Update: after a restart (2026-11-10, 13:40)

- SlideMage was restarted at about 13:33. The new debug log is `app_2026-11-10_133256_35164.log`.
- The first slide shown was `ejm` (13:36:04). No `tth` step render was requested before that.
- From 13:36:10, the same step renders for `tth-mult-Introductory-Matter-Section-Overview` came back every 10 seconds: 4 requests in 13:36, 6 each in 13:37, 13:38 and 13:39.
- A deck compile (`t-Uni-IA2-2026w`, instructor, during-course, after-course) was started in this session. Its progress line reached "PASS: render of tth-mult-Introductory-Matter-Section-Introduct…" at 13:36:38, the same stall as before.
- The user did not select `tth` in this session. The requests start once `ejm` is shown, which points to the neighbour loop in `_probe_steps` or to the compile's own pass, not to a click.

## Update: the neighbour loop is the trigger (2026-11-10, 13:45)

- `tth` is the slide before `ejm` in the deck, so it is one of the neighbours of `ejm`.
- `_probe_steps` asks for the steps of up to `NEIGHBOURS` (4) slides around the one on show (`preview_view.py`, lines 75 and 1228–1231), in the current view and language. `centre.py:142` supplies them from the deck order.
- `_poll_selection` empties `_step_pages` every 5 seconds, so every neighbour whose steps are not stored is asked for again. For `tth` the steps can never be stored standalone (it needs its deck), so the request repeats on each poll.
- All of the requests are for language EN, instructor view. The German side is not involved.

## Update: why tth is treated as needing its deck (2026-11-10, 13:50)

- `deck_context.reasons()` marks a slide as needing its deck when its source matches one of the patterns in `_REASON_PATTERNS` (`src/slidemage/deck_context.py`, lines 47–59).
- `tth` matches the `section` pattern through `\begin{sectionframe}` on line 13 of its source. That pattern includes `\begin\s*\{sectionframe\}`, so any section-divider slide is flagged.
- The environment itself (`latex/SlideMage_base.tex`, line 5421) takes its title from its argument and doesn't read section data from the deck. From what was read, `tth`'s own text doesn't need the deck. This was not verified by rendering `tth` on its own.
- So the flag looks like a false positive. Because the slide is flagged, its steps can never be stored standalone, which starts the loop described above.
- Suggested fix: match only the real section-number and section-title macros in the `section` pattern, not the environment name. Check that a standalone render of `tth` looks the same before and after.
