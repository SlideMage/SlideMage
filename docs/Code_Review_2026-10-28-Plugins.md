**Plugin system, Anthropic client, and CampusOnline code review — 2026-10-28**

**Recommendation: request changes before merging the host or releasing CampusOnline.** The separation into a small public API, a contribution registry, an installer, and plugin-owned feature code is reasonable. However, successful plugin edits currently bypass the application's edit lifecycle, updates replace files still used by running plugins, and the advertised insertion transaction can damage the deck on a write failure. The Anthropic replacement also has cancellation and proxy compatibility gaps.

This review contains **11 findings: three P1 and eight P2**. P1 means a fix is needed before shipping because a normal workflow breaks or user data can be damaged. P2 means a concrete defect with a narrower trigger. Existing defects carried into the extracted code are identified explicitly.

Reviewed local revisions:

| Component | Revision | Location |
| --- | --- | --- |
| Plugin host, proposed PR #21 | `e8f1c44`, `feature/plugin-host` | `/home/juergen/github/SlideMage/.worktrees/plugin-host` |
| Anthropic stdlib client, proposed PR #20 | `bacfb31`, `feature/anthropic-stdlib` | `/home/juergen/github/SlideMage` |
| CampusOnline | `6f965ca`, `plugin-campusonline` | `/home/juergen/github/slidemage-plugin-campusonline` |
| Core comparison base | `bbff820`, `develop` | Same SlideMage repository |

The Claude/Anthropic **plugin itself is not implemented at these revisions**. PR #20 replaces the built-in API client; the AI route registration, credentials boundary, terminal integration, and Claude plugin lifecycle remain future work. Findings below distinguish that scope from the implemented CampusOnline plugin. The existing modification to `uv.lock` and the existing `output/` contents were left alone. No implementation files were changed.

**Findings, in priority order**

1. **[P1] Notify the window and record history after successful plugin deck edits.**

   Locations: [host.py:189](/home/juergen/github/SlideMage/.worktrees/plugin-host/src/slidemage/plugins/host.py:189), also the return from `insert_slides()` at line 187. The existing integration to use is [window.py:697](/home/juergen/github/SlideMage/.worktrees/plugin-host/src/slidemage/ui/workspace/window.py:697).

   Both mutation methods write files and return without rescanning the deck, refreshing open editors, regenerating slide headers, or recording the previous text through `after_deck_edit()`. A successful write therefore leaves `window.decks` and `window.state.deck` holding the old text. `WindowHostUi.open_deck_settings()` looks up that same old deck, so CampusOnline's instruction to reopen Deck settings does not resolve the problem.

   **Reproduced with the real host and CampusOnline:** save a course link on a deck that previously had none, close the sheet, and reopen it from the window's current deck. The file contains the link, but the reopened Course tab still has an empty link. The slide-list Undo stack is empty. Insertion has the same missing post-edit path: new calls are on disk without the corresponding application refresh/history.

   Route both host mutation methods through a GUI post-edit callback, passing the previous text. Keep the existing snapshots immutable in meaning, but ensure the next snapshot comes from the newly scanned deck. Add an end-to-end save → close → reopen → fetch/insert → undo test; constructing the tab and checking that it exists does not cover this.

2. **[P1] Keep the running plugin's files stable until restart.**

   Locations: [installer.py:244](/home/juergen/github/SlideMage/.worktrees/plugin-host/src/slidemage/plugins/installer.py:244), [installer.py:274](/home/juergen/github/SlideMage/.worktrees/plugin-host/src/slidemage/plugins/installer.py:274), and [loader.py:182](/home/juergen/github/SlideMage/.worktrees/plugin-host/src/slidemage/plugins/loader.py:182).

   Updating immediately renames `plugins/<id>` into `.old` and puts the new version at the original path. Loaded modules still have `__path__`, `__file__`, and import specs pointing to the original path. Later relative imports therefore read the new release, while already imported modules remain the old release. Removing the plugin makes its lazy imports and resource reads fail immediately. Moving the old directory aside does not update those Python references.

   **Reproduced:** load version 1, install version 2, then call a version-1 function that imports a previously unused submodule. It returns versions `('1.0.0', '2.0.0')`. Removing the plugin then makes a resource lookup from the running module raise `FileNotFoundError`. CampusOnline explicitly imports its UI modules lazily inside its registered factories, so this is relevant to the proposed plugin, including automatic updates shortly after startup.

   Stage replacements/removals for the next process start, or load from immutable version directories and retain every directory used by a running process. Test both lazy imports and resource reads after update/remove, before restart.

3. **[P1] Make insertion failure preserve the deck and remove partially written slides.**

   Location: [host.py:171](/home/juergen/github/SlideMage/.worktrees/plugin-host/src/slidemage/plugins/host.py:171), continuing through the rollback at line 186. Underlying writer: [fileio.py:60](/home/juergen/github/SlideMage/.worktrees/plugin-host/src/slidemage/fileio.py:60).

   The promised “all or nothing” operation has two holes. A newly opened slide is added to `created` only after writing and closing it succeeds, so a partial write or failed flush leaves an untracked file behind. The final deck edit delegates to `deck_editor.apply()`, which uses `write_text_exact()` and opens the existing deck with mode `w`. Failure after truncation does not restore the deck; the exception handler only removes tracked slides and restores the ID CSV.

   **Fault-injection reproductions:** a failing slide write left a seven-byte slide file behind. A failure after the deck's first nine characters left only those nine characters in the deck, even though the generated slides were removed. The unsafe underlying deck writer predates the plugin work, but the new host advertises and depends on a stronger transaction guarantee.

   Stage slide content and publish it safely; track newly created files as soon as creation succeeds. Replace the deck atomically with an expected-text check at commit. Exercise failures during slide write/close and during deck commit, rather than only failure while minting the next ID.

4. **[P2] Reserve the settings directory or move it outside the plugin-ID namespace.**

   Locations: [installer.py:241](/home/juergen/github/SlideMage/.worktrees/plugin-host/src/slidemage/plugins/installer.py:241) and [host.py:112](/home/juergen/github/SlideMage/.worktrees/plugin-host/src/slidemage/plugins/host.py:112).

   `settings` is a valid plugin ID, while every plugin's persistent settings live in `plugins/settings/<id>.json`. Installing a valid archive with ID `settings` treats that shared directory as an existing plugin and moves it into `.old`. Startup cleanup subsequently deletes it, losing other plugins' preferences. This happens during installation even if loading the new plugin later fails.

   **Reproduced:** create `plugins/settings/other.json`, install a `settings` plugin, then run startup cleanup. The other plugin's settings file is gone, including the backup copy. Put host metadata in a separate/reserved namespace and reject collisions consistently in discovery, catalogue handling, and installation.

5. **[P2] Protect unsaved core settings from plugin edits in the same sheet.**

   Location: [deck_settings.py:290](/home/juergen/github/SlideMage/.worktrees/plugin-host/src/slidemage/ui/dialogs/deck_settings.py:290).

   The built-in Admin slides action is disabled while General/PDF settings are dirty. The plugin footer action lacks this condition and also hides Save. A user can change the footer or language, switch to Course, and insert slides. Insertion changes the underlying file while the settings form retains its earlier snapshot. Returning to General and saving closes the form, then fails the stale-file check, losing the pending form changes. CampusOnline's separate Save link button can create the same conflict.

   **Reproduced with the real Course controller:** change the footer, insert through the enabled plugin button, and try to save the form; `StaleFileError` is raised. Coordinate plugin mutations with the sheet's dirty state. Disabling the footer alone is insufficient because plugins also have their own edit buttons; the API needs a consistent commit/refuse/refresh policy for those writes.

6. **[P2] Make Anthropic connection setup cancellable, including TLS.**

   Location: [anthropic_provider.py:228](/home/juergen/github/SlideMage/src/slidemage/ai/anthropic_provider.py:228).

   `_sock` is published only after `conn.connect()` returns. For HTTPS, that call includes the TLS handshake. While it is blocked, `abort()` sees no socket and setting `_wake` only interrupts retry backoff. The cancellation check after connect cannot interrupt the operation already in progress. Chat defaults to a 300-second timeout, so Stop can leave a worker running for minutes during connection trouble.

   **Reproduced with a localhost server that accepts TCP and stalls TLS:** after `abort()`, the request worker is still blocked and `_sock is None`; it becomes `Cancelled` only after the server closes the connection. Use cancellable connection/handshake stages or bounded polling with an exposed transport. Keep the current blocked-read and backoff tests, and add connection/TLS cancellation coverage.

7. **[P2] Preserve environment-proxy support when replacing the SDK.**

   Locations: [anthropic_provider.py:227](/home/juergen/github/SlideMage/src/slidemage/ai/anthropic_provider.py:227) and [providers.py:131](/home/juergen/github/SlideMage/src/slidemage/ai/providers.py:131).

   The replacement always opens a direct `HTTPConnection`/`HTTPSConnection` to the API hostname. It never resolves proxy environment variables or establishes an HTTPS CONNECT tunnel. The previous dependency explicitly constructs proxy transports from the environment; see the pinned [Anthropic SDK v1.13.0 implementation](https://github.com/anthropics/anthropic-sdk-python/blob/v1.13.0/src/anthropic/_base_client.py). Users behind a required university or corporate proxy will lose API access after the update, even though their configuration worked previously.

   **Reproduced without contacting the API:** set a temporary `HTTPS_PROXY`; the SDK's resolver selects it, while the new connection still targets `api.anthropic.com` with no tunnel. Implement proxy selection, bypass rules, and CONNECT support, with local-proxy tests. This is a compatibility regression, distinct from the intentional certificate-store change.

8. **[P2] Refresh the Course box when its cached data changes.**

   Locations: [plugin_box.py:49](/home/juergen/github/SlideMage/.worktrees/plugin-host/src/slidemage/ui/workspace/panels/plugin_box.py:49) and [CampusOnline box.py:16](/home/juergen/github/slidemage-plugin-campusonline/campusonline/ui/box.py:16).

   The host caches the built widget solely by `(deck.path, deck.text)`, while CampusOnline computes labels once from its schedule cache. Loading the course in the Course tab changes that cache without changing the deck. The box continues to show “No session dates cached yet” or an obsolete title/session, even when `refresh()` is called. The plugin has no public invalidation method. The same static widget can retain yesterday's next-session label across a date change.

   **Reproduced:** build the box, store a new title in the cache, call panel refresh, and inspect the labels: they remain unchanged. The new title appears only after explicitly invalidating the panel, as reselecting it in the picker does. Add a public refresh/invalidation mechanism or make the plugin's widget update from a cache-change signal; handle date rollover as well.

9. **[P2] Key CampusOnline cache entries by installation and course, not course number alone.**

   Location: [course_schedule.py:182](/home/juergen/github/slidemage-plugin-campusonline/campusonline/course_schedule.py:182), with matching readers at lines 228 and 266.

   The URL parser supports different CAMPUSonline hosts/instances, but the cache key is only `pStpSpNr`. The host supplies a machine-wide cache directory. Two unrelated installations can use the same course number, so fetching one overwrites the other's title, dates, and rooms; the Course box then confidently presents the wrong course data. The number-only schedule key is inherited from core, and the new cached-title/box functionality extends its visible impact.

   **Reproduced:** store titles for `https://one.example/instance/course?pStpSpNr=123` and `https://two.example/instance/course?pStpSpNr=123`; reading either returns the second title. Use a canonical origin/instance/course key in every writer and reader, with a conservative migration strategy for legacy entries whose origin was never recorded.

10. **[P2] Serialize CampusOnline cache updates and publish complete files atomically.**

    Location: [course_schedule.py:175](/home/juergen/github/slidemage-plugin-campusonline/campusonline/course_schedule.py:175).

    `_update_entry()` performs an unlocked read/modify/write of the entire cache with `Path.write_text()`. Closing a Course tab does not cancel its network work, so opening another tab can overlap updates; multiple application processes also share this directory. One update can overwrite another update's new entry or fields. Readers on the render worker can also encounter a truncated/incomplete JSON file and temporarily treat every course as uncached. Swallowing exceptions prevents a crash but does not preserve the data. The earlier schedule cache had similar weaknesses; adding separate title updates increases the number of read/modify/write operations.

    **Reproduced deterministically:** pause one writer after it reads an empty cache, complete a second course's write, then resume the first. The second course disappears. Serialize the read/modify/write operation and use a temporary file plus atomic replacement. Account for more than one application process, or store independent entries separately; atomic replacement alone does not prevent lost updates.

11. **[P2] Isolate the update-mode setting in the new tests.**

    Locations: [test_plugin_updates.py:122](/home/juergen/github/SlideMage/.worktrees/plugin-host/tests/test_plugin_updates.py:122) and its imported [fixture at test_plugin_settings_tab.py:37](/home/juergen/github/SlideMage/.worktrees/plugin-host/tests/test_plugin_settings_tab.py:37).

    The fixture patches `loader.project.config_dir`, but `updater.py` imported `config_dir` directly, so it retains the original callable. Calls to `updater.set_update_mode()` therefore write the developer's real setting instead of the test directory. An unrestricted run changes application update preferences; a filesystem-restricted run fails.

    **Observed:** ten tests tried to write `/home/juergen/.config/slidemage/update_mode` and were stopped by the sandbox. Redirecting `XDG_CONFIG_HOME` to a temporary directory made them pass. Patch `updater.config_dir` or its settings-path function in the fixture, so correctness does not depend on the caller remembering an environment override.

**Validation and limits**

| Check | Result |
| --- | --- |
| Host `tests/test_plugin_*.py`, with the real CampusOnline checkout enabled | **245 passed, 2 skipped**; the two skips require the unavailable `jsonschema` package |
| Anthropic/client/agent/provider-task/packaging subset | **69 passed, 1 skipped**; Windows-only pywinpty packaging check skipped |
| CampusOnline complete test suite, including bridge tests | **113 passed** |
| CampusOnline `build.py --check` | Passed |
| Host source-mode plugin self-test | Passed |
| Additional real-host GUI reproductions | **3 passed**, asserting the observed stale snapshot, dirty-form conflict, and stale box behavior |
| Focused failure/transport/cache reproductions | Confirmed the remaining findings as described above |

The 427 passing existing tests do not cover the failing workflows above. The first restricted test attempt could not create loopback sockets and exposed finding 11. The successful reruns used temporary configuration/cache directories and permitted local HTTP test servers. No real Anthropic request or live CampusOnline request was made.

Reproduction scripts are retained in [/tmp/slidemage-plugin-review](/tmp/slidemage-plugin-review): `probe_host.py`, `probe_anthropic.py`, `probe_campus.py`, and `test_gui_probes.py`. They use temporary projects and dummy credentials. `probe_host.py` and the GUI probes need the host checkout's `src` on `PYTHONPATH`; the Anthropic probe needs the main checkout's `src`; the CampusOnline probe needs its repository root. The Anthropic probe requires loopback socket access. These are review evidence, not production regression tests.

The transport review also checked the documented event sequence, cumulative usage, tool-input deltas, thinking signatures, and unknown-event handling against [Anthropic's streaming documentation](https://platform.claude.com/docs/en/build-with-claude/streaming). The current tests cover these main cases. A Linux/Windows frozen release, real certificate handling, the two branches merged together, and the full application test suite were **not** validated in this review. The handover's baseline GUI-failure explanation has therefore not been independently reconfirmed.

**API and release decisions that still need resolution**

- Keep `edit_deck_text()` rather than introducing a marker-specific host API. The plugin owns the comment syntax naturally. Fix its atomic-write, history, and refresh semantics before calling API 1 stable; the current abstraction is reasonable but its promised behavior is incomplete.
- `enabled(None)`, activation-only registration, and render-priority callbacks on a worker thread are sensible contracts. The cache implementation must meet the concurrency contract. Define how plugin widgets are notified when data changes; deck snapshots alone do not cover a changing schedule or future AI task state.
- Complete CampusOnline's planned `slidemage.plugin_api` migration before release. Its private `StaleFileError` is a different class from the exception the real host raises, so its current handlers do not catch that host exception. This is an already acknowledged step-5 dependency, not an additional numbered finding. Test stale and failed writes against the real facade after migration.
- Reconcile `requires_slidemage = ">=9.0"` with the 8.68 host. Existing E2E tests override the app version and only check activation/widget construction; they neither prove installation on 8.68 nor drive a successful course fetch and insertion. Use an installable release artifact and supported course-URL fixture in the acceptance test.
- Version the upgrade offer by migration/feature before removing built-ins. The current global `offer_seen` flag suppresses the sheet forever after an earlier host-release offer. Merely turning on `PRESELECT_ON_UPGRADE` later will not offer CampusOnline or Claude to users who already dismissed that earlier sheet. Keep first-start onboarding separate from migration notices.
- The plugin self-test verifies top-level stdlib imports and a trivial plugin, but does not explicitly import all five promised PySide6 modules or exercise a plugin UI in the frozen executable. Add those checks before relying on it as proof of the complete runtime contract. Preserve the handover's merge requirement to remove the Anthropic hidden-import line, and include the intended lockfile change in the final PR.
- Review the future Claude plugin when the route/terminal/credential implementation exists. In particular, verify cancellation and restart of chat surfaces, lifetime of background tasks, capability reporting for missing Claude Code, and preservation of existing consent behavior. These cannot be certified from a stdlib HTTP client alone.

The installer correctly treats plugins as code with the user's privileges; manifest network declarations and archive checks do not constitute a runtime sandbox. The current in-process trust model is explicit. The findings above concern concrete lifecycle, persistence, and compatibility behavior within that model, rather than a hypothetical promise to isolate malicious Python.
