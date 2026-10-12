# Claude Code tasks: benchmark

Step 1 of [CLAUDE_CODE_TASKS_PLAN.md](CLAUDE_CODE_TASKS_PLAN.md). Written by `tools/claude_task_benchmark.py`
(the text above "## Measurements" is hand-written and survives a rerun; the tool now runs the setups
`sonnet-medium`, `haiku-medium` and `haiku-low` only). Setup: a disposable copy of `example/`,
five EN slides (1bb short with a table, 1nz citations and footnotes, 1t2 formulas and overlays, 1th table and
overlays, 1nt long with TikZ), translation EN to DE with Sie, and a LaTeX fix on each slide after one
lint-detected mistake was put in (an unclosed brace, a missing `\end{itemize}` or `\end{columns}`, a missing
`$`, a stray `&`). Each setup changes one thing from the baseline (isolated, Haiku, effort medium, a fresh
process per task, edit list; the baseline is `haiku-medium` of the tool). One run per slide, so five runs per setup and
task: the medians below are indicative, not statistics.

## Decisions

| Decision | Value | Evidence |
| --- | --- | --- |
| Model | **Sonnet, effort medium** (`MODEL`, `EFFORT` in `ai/claude_runner.py`), replacing the plan's Haiku default | Median translation 6.5 s against 10.3 s (Haiku medium), fix 2.5 s against 4.6 s; Sonnet writes about half the output tokens (no extra thinking) and its German is at least as good (no mistakes found in either). Haiku medium also meets the 15 s goal (translation slowest 13.1 s); the picker keeps it available. Haiku low saves little (9.1 s / 3.1 s): effort is not the lever, the model is. |
| Isolation | **Keep it** (`ISOLATION`, `--system-prompt`, empty working folder) | A default `claude -p` (only `--tools ""`) sends about 55k input tokens against 2.3k, and is 1.4 s slower in the median (both tasks) and 4.7 s slower in the slowest translation (17.8 s against 13.1 s). Login, the structured result and the subscription all work with the isolation flags (`apiKeySource` is `none`, no API key involved). |
| Output format of fixes | **Edit list** | Median 4.6 s against 8.0 s for the full body, 837 against 1854 output tokens; the edit list restored the original slide in 4 of 5 runs (the fifth removed the stray `&` instead of escaping it, which no tool can decide), the full body differed from it in 3 of 5. A full body also has to keep the protected parts; a first attempt even echoed the `<slide>` tags (rules now say not to). |
| Process | **A fresh `claude -p` per task** | One long-running stream-json process saves about 3 s (translation 7.5 s against 10.3 s, fix 4.1 s against 4.6 s) by skipping start-up, but its context grows with every request (input tokens 3x), tasks are no longer independent, and Stop would have to restart it. With Sonnet a fresh process is already at 6.5 s. Revisit only if the start-up matters in the UI. |
| Deadline | **60 s** for text tasks (`TEXT_DEADLINE_S`), covering the repair attempt too | The slowest run of any isolated setup was 13.1 s; a repair doubles a run. 60 s is for a service that has stalled, not for slow answers. Image descriptions (120 s) are not measured yet. |
| Inline images | **Yes**: an image content block in `--input-format stream-json` reaches the model | A 7.9 kB PNG of the demo project came back with its text quoted correctly (see the end of this file). No MCP read-image fallback needed. |

## What the flags did

All of these work with the installed 2.1.296 and the subscription login: `-p --model --effort --tools ""
--strict-mcp-config --setting-sources "" --disable-slash-commands --system-prompt --no-session-persistence
--output-format stream-json --verbose --json-schema`. None had to be dropped. The result event carries the
answer as `structured_output` (an object), the usage and `num_turns` (2: the model's `StructuredOutput` call
and the end). A missing login comes as a result event with `is_error` true and `result` "Not logged in".
`--tools ""` leaves one tool, `StructuredOutput`, which is how the schema is delivered.
Without login the process exits with code 1 after about one second.

## Findings

- Every run of every setup produced a valid answer; no repair attempt was needed. Translations kept Sie, all
  LaTeX commands (same command multiset), protected parts, citations and overlays; nothing was left in
  English (the check's "English words left" notes are false positives: the name "Git for Windows" and
  TeX's `\the`).
- The edit list needs a model that copies `before` exactly (tabs included): all 25 runs did.
- First answer event arrives at about 70 % of the translation time: the answer is one JSON object, so
  streaming it to the user would only show the end of the wait.
- The stray-`&` fix is ambiguous (remove or escape); the model chose differently from the original slide, and
  the lint is satisfied either way.

## Step 1 record, 2026-10-12

The measurements behind the decisions. The comparisons that are settled (default `claude -p`, full body, one
long-running process, the inline image check) were run by an earlier version of the tool and are not in it any
more; the tool now runs the model and effort setups only.

Run on 2026-10-12 with Claude Code 2.1.296 (Claude Code), tools/claude_task_benchmark.py: five slides, one run each per setup and task. Times are seconds from the start of the task: *first* the first answer event, *valid* the answer checked (a repair attempt included), *file* the fix written to the slide file. Turns and tokens (input with cached ones / output) are means per run.

| Setup | Task | Done | Nothing | Failed | Repairs | First (median) | Valid (median) | Valid (slowest) | File (median) | Turns | Tokens |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| baseline | translate | 5 | 0 | 0 | 0 | 7.3 | 10.3 | 13.1 | - | 2.0 | 2321 / 2465 |
| baseline | fix_latex | 5 | 0 | 0 | 0 | 4.3 | 4.6 | 6.8 | 4.6 | 2.0 | 2344 / 837 |
| default-claude | translate | 5 | 0 | 0 | 0 | 9.1 | 11.7 | 17.8 | - | 2.0 | 54803 / 2879 |
| default-claude | fix_latex | 5 | 0 | 0 | 0 | 5.5 | 6.0 | 7.8 | 6.0 | 2.0 | 35027 / 900 |
| haiku-low | translate | 5 | 0 | 0 | 0 | 5.9 | 9.1 | 11.0 | - | 2.0 | 2321 / 2196 |
| haiku-low | fix_latex | 5 | 0 | 0 | 0 | 2.8 | 3.1 | 4.2 | 3.1 | 2.0 | 2345 / 434 |
| sonnet-medium | translate | 5 | 0 | 0 | 0 | 6.0 | 6.5 | 11.6 | - | 2.0 | 2322 / 1167 |
| sonnet-medium | fix_latex | 5 | 0 | 0 | 0 | 2.3 | 2.5 | 2.7 | 2.5 | 2.0 | 2347 / 115 |
| full-body | translate | 5 | 0 | 0 | 0 | 5.7 | 10.4 | 10.7 | - | 2.0 | 2321 / 2346 |
| full-body | fix_latex | 5 | 0 | 0 | 0 | 5.4 | 8.0 | 10.0 | 8.0 | 2.0 | 2210 / 1854 |
| one-process | translate | 5 | 0 | 0 | 0 | 4.5 | 7.5 | 8.1 | - | 2.0 | 7659 / 2103 |
| one-process | fix_latex | 5 | 0 | 0 | 0 | 3.8 | 4.1 | 5.7 | 4.1 | 2.0 | 5291 / 670 |

### Per run

| Setup | Task | Slide | Result | Valid (s) | Notes |
| --- | --- | --- | --- | --- | --- |
| baseline | translate | 1bb | done | 6.7 | English words left: for x1 |
| baseline | translate | 1nz | done | 12.1 |  |
| baseline | translate | 1t2 | done | 8.3 |  |
| baseline | translate | 1th | done | 10.3 |  |
| baseline | translate | 1nt | done | 13.1 | English words left: the x1 |
| baseline | fix_latex | 1bb | done | 4.3 | exactly the original slide |
| baseline | fix_latex | 1nz | done | 4.6 | exactly the original slide |
| baseline | fix_latex | 1t2 | done | 6.8 | exactly the original slide |
| baseline | fix_latex | 1th | done | 3.6 | no error left, differs from the original slide |
| baseline | fix_latex | 1nt | done | 5.6 | exactly the original slide |
| default-claude | translate | 1bb | done | 11.0 |  |
| default-claude | translate | 1nz | done | 11.7 |  |
| default-claude | translate | 1t2 | done | 10.6 |  |
| default-claude | translate | 1th | done | 12.4 |  |
| default-claude | translate | 1nt | done | 17.8 | English words left: the x1 |
| default-claude | fix_latex | 1bb | done | 3.2 | exactly the original slide |
| default-claude | fix_latex | 1nz | done | 7.4 | no error left, differs from the original slide |
| default-claude | fix_latex | 1t2 | done | 7.8 | exactly the original slide |
| default-claude | fix_latex | 1th | done | 4.7 | no error left, differs from the original slide |
| default-claude | fix_latex | 1nt | done | 6.0 | exactly the original slide |
| haiku-low | translate | 1bb | done | 6.5 | English words left: for x1, and x1 |
| haiku-low | translate | 1nz | done | 9.7 |  |
| haiku-low | translate | 1t2 | done | 7.6 |  |
| haiku-low | translate | 1th | done | 9.1 |  |
| haiku-low | translate | 1nt | done | 11.0 | English words left: the x1 |
| haiku-low | fix_latex | 1bb | done | 2.3 | exactly the original slide |
| haiku-low | fix_latex | 1nz | done | 3.1 | exactly the original slide |
| haiku-low | fix_latex | 1t2 | done | 4.2 | exactly the original slide |
| haiku-low | fix_latex | 1th | done | 2.8 | no error left, differs from the original slide |
| haiku-low | fix_latex | 1nt | done | 4.2 | exactly the original slide |
| sonnet-medium | translate | 1bb | done | 5.0 | English words left: for x1 |
| sonnet-medium | translate | 1nz | done | 6.1 |  |
| sonnet-medium | translate | 1t2 | done | 6.5 |  |
| sonnet-medium | translate | 1th | done | 7.6 |  |
| sonnet-medium | translate | 1nt | done | 11.6 | English words left: the x1 |
| sonnet-medium | fix_latex | 1bb | done | 2.5 | exactly the original slide |
| sonnet-medium | fix_latex | 1nz | done | 2.1 | exactly the original slide |
| sonnet-medium | fix_latex | 1t2 | done | 2.6 | exactly the original slide |
| sonnet-medium | fix_latex | 1th | done | 2.3 | no error left, differs from the original slide |
| sonnet-medium | fix_latex | 1nt | done | 2.7 | exactly the original slide |
| full-body | translate | 1bb | done | 7.4 | English words left: for x1 |
| full-body | translate | 1nz | done | 10.4 |  |
| full-body | translate | 1t2 | done | 7.9 |  |
| full-body | translate | 1th | done | 10.7 |  |
| full-body | translate | 1nt | done | 10.4 | English words left: the x1 |
| full-body | fix_latex | 1bb | done | 8.0 | no error left, differs from the original slide |
| full-body | fix_latex | 1nz | done | 4.5 | exactly the original slide |
| full-body | fix_latex | 1t2 | done | 10.0 | exactly the original slide |
| full-body | fix_latex | 1th | done | 8.1 | no error left, differs from the original slide |
| full-body | fix_latex | 1nt | done | 7.6 | no error left, differs from the original slide |
| one-process | translate | 1bb | done | 7.2 |  |
| one-process | translate | 1nz | done | 7.6 |  |
| one-process | translate | 1t2 | done | 5.6 |  |
| one-process | translate | 1th | done | 7.5 |  |
| one-process | translate | 1nt | done | 8.1 | English words left: the x1 |
| one-process | fix_latex | 1bb | done | 5.7 | exactly the original slide |
| one-process | fix_latex | 1nz | done | 2.6 | exactly the original slide |
| one-process | fix_latex | 1t2 | done | 4.1 | exactly the original slide |
| one-process | fix_latex | 1th | done | 2.7 | no error left, differs from the original slide |
| one-process | fix_latex | 1nt | done | 4.2 | exactly the original slide |

### Inline image through stream-json input

Claude's reply to the image block: 'This is a screenshot of a visibility settings panel, likely from a presentation or slide-sharing tool.\n\nReadable text, quoted:\n\n- "Visibility"\n- "Instructor highlighted"\n- "Instructor"\n- "During"\n- "After"\n- "Whole slide"\n- "\\slide · #44"\n\nThe grid shows "Whole slide" (\\slide · #44) with checked boxes under Instructor (blue), During (green), and After (orange).'

## Measurements

Not run with the reduced tool yet; `tools/claude_task_benchmark.py` writes its tables here (step 6).
