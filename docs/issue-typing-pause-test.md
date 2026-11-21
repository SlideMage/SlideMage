# Flaky test: `test_a_typing_pause_renders_once_and_autosave_hits_the_store`

**Where:** `tests/test_workspace_window.py:529`. The test was added in `5867e5ab` ("Render store 4.3: render on a typing pause", 2026-11-10).

**Symptom:** the first render assertion fails at line 583:

```
assert len(compiled) == len(requests) == 1 and requests[0].error is None
E   assert (0 == 1)
E    +  where 0 = len([])            # compiled: preview_target.render_text was never called
E    +  and   1 = len([RenderRequest])
```

The typing pause produced one render request, but the monkeypatched `preview_target.render_text` was never called. So the request completed (`done` set, pane not busy) without compiling. It may have been served by something other than `render_text`, for example a store or cache hit, a shortcut for the unchanged saved file, or a request that ended with no PDF. Within the 10 s loop, `requests[-1].done` and `not pane._busy` became true while `compiled` was still empty.

**It is intermittent, not a regression:**
- At `5867e5ab` itself, two runs of the test alone gave one failure and one pass.
- It fails at `27803d31` (v0.16.0), at `15917c05` (#164 merged) and on today's develop (`5b6f7361`), both alone and in the full suite.

**How to reproduce** (Windows, the project venv). Run this from the repo root and repeat a few times:

```
PYTHONPATH=src QT_QPA_PLATFORM=offscreen python -m pytest -q tests/test_workspace_window.py -k typing_pause
```

**Things to check:**
- What the first request returns when `compiled` is empty: inspect `requests[0].metrics` (`cache_hit`?), `requests[0].error` and its result.
- Whether a render started before the patches take effect, for example by `open_slide_editor`, `set_mode("split")` or the `% first` keystrokes while `RENDER_ON_TYPING_PAUSE` is False. Such a render could fill the store, so the typing-pause request becomes a cache hit.
- Whether `capture` misses a request that is made through another path, or by a request made before `pane._renders.request` was wrapped.
- **Suggested fix:** wait on the specific request the pause made and assert why it completed, instead of relying on `done`, `_busy` and `qWait`. Alternatively, make the store miss deterministic: use a fresh store or a unique buffer text.
