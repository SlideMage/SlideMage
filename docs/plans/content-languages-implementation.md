# Implementation plan: content languages on develop

Status: not started (2026-11-02). Turns the design in [content-languages.md](content-languages.md) into steps
against develop at b6de8b7 (v0.13.23). Section numbers like "2.4" refer to the design plan.

Every step is its own branch off develop, pushed to the fork and merged by PR after the owner has tested it. Each
step bumps `VERSION_NUMBER` with a CHANGELOG entry and ends with `pytest -n 8` green.

**The invariant for every step:** a project without a `languages` key behaves exactly as before. That means the
same compile and preview wrappers (byte for byte), the same render keys, the same `alt-text.csv`, the same
transcript, and nothing written to `project.json`. Step 1 adds a regression test for this and every later step
keeps it passing.

## 1. Where the design plan does not match develop

Checked 2026-11-02. These corrections are part of the steps below.

1. **The image store is already at format 2.** `alt_images.FORMAT_VERSION = 2`, so the per-language store becomes
   **version 3**, and the backup is `media/alt-text.v2.json`.
2. **Older releases would destroy a newer store.** `load_store` never checks `version`. `entry_from_dict` reads
   only the fields it knows, and `save_store` writes only those. So an older SlideMage that opens a version-3 store
   shows every description as empty, and its first save deletes the `text` blocks. The existing project format
   guard (`project.PROJECT_FORMAT`, checked in `cli.check_project_format` since v4.1.0) only warns, and the user
   can open anyway. So this answers the design plan's open question (2.4): the guard is missing. It ships in
   step 0, and step 4 also raises `PROJECT_FORMAT` to 2.
3. **There are three compile lines, not one.** `compiler.py:637` and `partial_compile.py:378` use
   `deck_language.language_line`, but `slide_preview._deck_language_line` builds its own. Also,
   `preview_build._VIEW_LINES` (`^\\deck(?:version|language)\[...\]$`) decides which build folder a preview uses
   (`view_variant`). The design's single combined line (`\SMProjectLanguages{...}\SMMainLanguage{...}\SMPdfLang{...}\decklanguage[fr]`)
   would not match that regex, so previews would share build folders across languages. Instead, put the project's
   languages on **their own line**, written by one function, matched by the regex, and only written when the
   project differs from the default (step 1).
4. **The render key needs an explicit input.** `render_key.RenderKeys.fast_key` hashes the deck preamble but not
   the line after it. Add a `"languages"` field, set only for non-default projects, so existing keys stay valid.
5. **The Lua reads CSV columns by position**, not by name (`SlideMage_alt.lua:99`, `fields[7]`/`fields[8]`).
   Reading by header is new work in step 4. `render_key._alt_rows` hashes whole CSV rows, so a project without
   extra languages must not gain any columns.
6. **Callers the design plan's inventory misses:**
   - Slides and languages: `slide_usage.py:131` (a one-partner `Translation` list), `slide_snapshot.py:405-446`,
     `deck_outline.py:121` (`missing_translation`), `ui/workspace/centre.py:984`,
     `ui/workspace/preview_view.py:93-167`, `ai/tools/readability.py:47`,
     `ui/workspace/chat/gui_workspace.py:254` (calls `set_language(own_language(...))`, which can be `mult` or
     None), `ui/workspace/task_card_model.py`, `ui/dialogs/add_slide.py:55` (`LANGUAGE_LABELS`),
     `ui/dialogs/settings_prompts.py`.
   - Image descriptions: `bundled_copies._merge_image_descriptions` (`source_de`), `image_review.py`
     (`FIELDS`, `GERMAN_FIELDS`), `alt_draft.py:900-1082`, `transcript.py:1460`, `_VERSION_LABELS_BY_LANGUAGE`.
   - Plugin API: `plugin_api` exports `de_address` (lines 71, 997, 1185). It stays exported in API version 1, and
     `address` is added next to it.
   - Plugins: CampusOnline `admin_slides.py` (`LANGUAGE_NAMES`, `sessions_frame(language="de")`); Exam Forge
     `elp_document.py:59` (`<html lang="en">`), `ui/drafting.py:81`, `ui/questions_tab.py:742`; the Claude
     plugin's `images.py:82`, which asks for the `en` → `de` prompt.
7. **Not affected:** the example project's slugs. All 103 current files are tagged `EN` or `DE`, so the slug check
   (2.1) finds nothing there. Its test needs its own fixture.

## 2. Steps

### Step 0: guard the image store (small, released first)

Branch `fix/alt-store-version-guard`.

- `alt_images`: `load_store`, `_read_raw` and every save path check `raw["version"]`. If it is above
  `FORMAT_VERSION`, saving raises a `NewerStoreError` and does not write. Reading keeps returning what it can.
- The Images page, image drafting and `bundled_copies` catch the error and show one message: "This project's
  image descriptions were saved by a newer SlideMage. Update SlideMage to change them."
- Tests: a store with `version: 99` is never overwritten by `save_store`, `update_store`, `_save_slide_notes` or
  `sync_store`.

This has to be on every machine before step 4 ships, so release it as soon as it is merged.

### Step 1: language table, project languages, compile line

Branch `feat/content-languages-1-registry`. Design 2.1, 2.7.

- **`languages.py`** (new, no Qt):
  - `Language(code, english, native, pdf_tag)` and a table of about 40 languages.
  - `name(code)`, `pdf_tag(code)` (unknown code → the code itself).
  - `DEFAULT = Languages(main="en", secondary=("de",))`.
  - `project_languages(ctx) -> Languages` (reads `project.json`, cached by file mtime), with `.codes` (main
    first, upper case, for file names) and `.lower`.
  - `set_project_languages(ctx, main, secondary)` (writes the key through `project.read_project_json` /
    `write_project_json`, so other keys are kept).
  - `is_default(ctx)`.
- **Compile line:**
  - `deck_language.language_lines(ctx, language) -> str` replaces `language_line`. It returns
    `\decklanguage[xx]\n` for a default project. Otherwise it returns `\SMProjectLanguages[<main>]{EN,DE,FR}\n`
    first, plus `\SMPdfLang{fr-FR}\n` when the table's tag differs from TeX's own rule.
  - `compiler.py:637`, `partial_compile.py:378` and `slide_preview._deck_language_line` all call it. The slide
    preview needs `ctx` passed in.
  - Extend `preview_build._VIEW_LINES` to match the two new lines.
  - `render_key.fast_key`: add `"languages": <the lines>` only when the project is not default.
- **`SlideMage_base.tex`:**
  - `\SMProjectLanguages[main]{list}` stores the list (`\SM@projectlanguages`, default `EN,DE`) and the main
    language (`\SMMainLanguage`, default `en`).
  - `\setSlideLanguageFromSlug@aux` looks `#2` up in that list (`\clist_if_in`), and `mult` stays separate.
  - `\SMPdfLang{tag}` overrides `\SMPDFLanguage` after `\decklanguage`.
  - Without these lines, TeX behaves as today.
- **Settings → Languages** (new `ui/dialogs/settings_languages.py`, registered in `settings.py` in the project
  section):
  - A main-language combo and a secondary list with Add/Remove/Up/Down, listing languages by
    `languages.name()`.
  - The form-of-address control moves here from `settings_ai.py`; its store changes in step 3.
  - Removing a language that is in use warns with counts: slides from a scan of `slides/`, decks from
    `deck_scan`.
- **Slug check** (2.1): `slide_rename.untagged_slugs_matching(ctx, code)` and `tag_untagged(ctx, id_slug,
  language)`, the latter through the existing rename path. The settings page calls them when a language is added
  and shows the list sheet.
- Tests:
  - `tests/test_languages.py`: the table, reading and writing the key, the cache.
  - `tests/test_language_line.py`: a default project's wrappers are byte-identical to develop (compile, partial,
    slide preview); a non-default project's render key and `view_variant` change.
  - `tests/test_slug_collision.py`.
  - A LuaLaTeX test, marked like the existing TeX tests: with `\SMProjectLanguages{EN,DE,FR}` an `FR` slug sets
    `\slideLanguage`, and without the line it does not.

### Step 2a: slides and decks, model only

Branch `feat/content-languages-2a-groups`. Design 2.2, 2.3 (non-UI).

- **`slide_language.py`:**
  - Remove `LANGUAGES` and `TRANSLATION_LANGUAGES`.
  - `own_language(id_slug, codes)` takes the codes as a **required** argument, so no caller is missed.
  - `TranslationLinks(slides_dir, codes)` keeps its codes and offers `links.own(id_slug)`. A new
    `links_for(ctx)` builds one.
  - `LANG_TRANSLATION_RE` becomes `^%% ([A-Z]{2}|mult) translation: (\S+)`. Only listed codes count.
  - Add `group(id_slug) -> Group(original, members: dict[lang, id_slug], valid)` on `TranslationLinks`, built
    once per scan. `find()` becomes "the group's member in that language".
  - `translation_link()` becomes `translation_group() -> list[TranslationLink]`. `cross_referenced_language()`
    becomes `translated_languages()`. `LanguageBadge` gets `languages: tuple` and the `[EN + DE FR]` / `[EN +3]`
    text.
- **`slide_rename.py`:**
  - `make_original(ctx, id_slug)`.
  - `regenerate_translation_links` writes one `%% <LANG> translation:` line per member, rewrites a chain as a
    star, and reports a cycle.
- **`deck_language.py`:** `_slots` groups by `links.group()`. The owner is the original's call, else the earliest
  call. `resolve_call` uses the group, and `related_ids` lists every member.
- **The other callers:** the remaining modules of the design plan's list and of section 1, item 6 get `ctx` or
  `links` passed in.
  - "The other language" in `compiler.deck_pdfs` and `presentation/frames.candidate_jobnames` becomes every other
    project language.
  - `background_renders.deck_language_code` no longer clamps the language to EN/DE. `languages_for` starts from
    `\decklanguage` and adds the other project languages when `bg_previews_second_language` is on.
  - `compile_records`, `deck_headers`, `unused_content`, `update_all_previews`, `appendix_toc` and `alt_blocks`
    iterate over the project's codes.
  - `slide_add.can_translate` accepts any pair of project languages. The model prompt follows in step 3; until
    then, a pair without its own prompt is offered only when the route has one.
- Tests:
  - `tests/test_translation_groups.py`: groups, make original, slots by group, chain, cycle.
  - A fixture project `tests/fixtures/project_de_en_fr` (main `de`).
  - Existing EN/DE tests stay unchanged and green.

### Step 2b: slides and decks, UI

Branch `feat/content-languages-2b-ui`. Design 2.2, 2.3 (UI).

- **`ui/workspace/state.py`:**
  - `UI_LANGUAGES` becomes `state.languages` (from `project_languages`, plus the deck's own code if it is
    missing).
  - The switch follows the deck: `set_deck` always takes `\decklanguage`, and `set_language` no longer calls
    `_remember("language", ...)`. A stored `language` value is dropped on the next write.
  - The deck settings sheet's language change emits `language_changed`.
  - `chat/gui_workspace.py:254` ignores `mult`/None.
- `ui/workspace/topbar.py`: a segmented control of the codes.
- `ui/workspace/panels/language.py`: rows per project language, Translate to <language>, Make this the original,
  and a Set language menu listing the project's languages.
- `ui/dialogs/add_slide.py`: labels come from `languages.py`, and Copy as translation is offered for every
  missing language.
- `ui/dialogs/deck_settings.py`: the language combo lists the project's languages. Correct the hyphenation tooltip
  until step 5b.
- `task_bubbles.py`, `task_card_model.py`, `preview_view.py`, `centre.py`: the target language comes from the
  command or the selected row, not "the first other one".
- Tests: `tests/test_language_switch.py` (the scenarios in design section 4), badges and panel rows on the
  fixture. GUI tests run the same way as the existing ones in `tests/`.

### Step 3: AI translation

Branch `feat/content-languages-3-ai`. Design 2.5. Depends on step 1 only.

- `ai/translation_style.py`: `address(ctx) -> "formal" | "informal"` reads `address`, falling back to
  `de_address`. `set_address` writes both keys. `de_address()` stays and is derived, for plugin API version 1.
- `ai/tasks.py`:
  - `LANGUAGE_NAMES` (also in `ui/workspace/actions.py`) is replaced by `languages.name()`.
  - The `if target == "DE"` / `if language == "DE"` branches (lines 187, 204, 235) become one form-of-address
    line for every target.
  - The last-resort prompt becomes a `{source}`/`{target}` template.
- Glossary: read the Markdown table form next to the old `EN = DE` lines, and send only the rows for the pair.
- `ui/dialogs/settings_prompts.py` lists every ordered pair of project languages and marks the pairs that have
  their own prompt. `translation_prompts.json` is unchanged.
- `ai/tools/slidemage.py`: the `language` enums are built per project when the tool list is built.
- Tests: the prompts for `de → fr` and `fr → en`, the address fallback both ways, both glossary forms.

### Step 4: image descriptions per language

Branch `feat/content-languages-4-images`. Design 2.4. Depends on steps 0 (released) and 1.

- `alt_images.py`:
  - `FORMAT_VERSION = 3`. `ImageEntry.text: dict[str, LangText]` (`short`, `long`, `takeaway_default`, `source`,
    `status`, `translated_from`, `from_hash`). `SlideUse.takeaway: dict[str, str]`.
  - `text_for(lang)` follows the chain own language → `translated_from` → main language.
  - `_entry_to_dict` and `entry_from_dict` handle version 3, and `entry_from_dict` reads version 2.
  - On first load of a version-2 file: copy it to `media/alt-text.v2.json`, then convert and save. This is done
    under `_store_lock` and only once; the backup's existence marks it done.
  - `en_text_hash` becomes `text_hash(entry, lang)`. `translation_state(entry, lang)`. Source review covers every
    language's `source`.
- **The CSV:**
  - The en and de columns stay where they are, and each further project language appends `status_xx`,
    `short_alt_xx` and `source_xx`.
  - A default project's CSV must stay byte-identical.
- `SlideMage_alt.lua`: read the header row into a name → index map, keep positions 4/5/7/8 when there is no
  header, and `altText`/`recordSource` take any code with the fallback chain.
- `project.PROJECT_FORMAT = 2`, set when the store is converted. Follow `version.py`'s rule for a format change (a
  BREAKING paragraph), and say in the CHANGELOG and release notes to update every machine first.
- `image_review.py`, `alt_draft.py`, `ai/image_tasks.py` (schema `short`/`long`/`takeaway`),
  `ai/image_instructions.py`, `bundled_copies._merge_image_descriptions`, `transcript.py:1460` and
  `ui/pages/images.py` / `image_form.py` all work per language:
  - The page's switch lists the project's languages.
  - The form's German group is the selected language.
  - Translate to <language>, and batch translation defaults to the missing or stale secondary languages.
  - The review filter becomes "Missing a translation" with a language choice.
- Tests:
  - `tests/test_alt_store_v3.py`: v2 → v3 conversion with its backup; a round trip gives identical output; the
    CSV with and without `fr`.
  - A Lua test: reading by header, and an old positional read of a CSV that has `fr` appended.
  - `bundled_copies` merge.

### Step 5a: LaTeX strings, PDF language, transcript, multilingual slides

Branch `feat/content-languages-5a-texts`. Design 2.6, 2.8. Depends on step 1.

- `SlideMage_base.tex`:
  - `\SMSetLanguageStrings{code}{ImageSource=..., ImagePrefix=...}` for en, de, fr, es, it.
    `\SMImageSourceLabel` and `\SMAltImagePrefix` look the strings up, falling back to the main language, then
    English, with a log warning. `\ifSMGerman` stays.
  - The `\multilingualtext*` fallback becomes `\SMMainLanguage` instead of `l__SM_mlt_en_bool`.
- `transcript.py`:
  - `STRINGS` and `_VERSION_LABELS_BY_LANGUAGE` get fr, es and it. `deck_language_of` returns the deck's code,
    with the same fallback.
  - `_resolve_multilingual_text` also resolves `\multilingualtext*{...}`.
- `latex_edit.py:238`: in a project with more than two languages, "Both languages" inserts the keyed form with
  one key per language.
- Tests: the French automatic texts and `/Lang fr-FR` (TeX test), a missing string falling back with a warning,
  and a transcript of a keyed `mult` slide.

### Step 5b: hyphenation (spike first)

Branch `spike/hyphenation-babel`, then `feat/content-languages-5b-hyphenation`. Design 2.10.

1. **Spike** on a copy of `example/`:
   - Load `babel` (LuaLaTeX, ini-based, no shorthands, no captions) for the deck language after the preamble.
   - Check whether the patterns survive the precompiled format (`preview_format.py`, `\SMLuaOnce`). If they do
     not, check one format per language.
   - Measure the compile time of the largest deck.
   - Result as a short note in this file. Continue only if previews still meet
     `docs/PREVIEW_RENDER_EQUIVALENCE_CONTRACT.md`.
2. **Layout comparison:**
   - Compile every German deck of `example/` and of the owner's course project, with and without the change, and
     compare per page with the render store.
   - List the slides whose layout changed (overfull boxes, line counts, reveal-step height) for the owner.
3. Implement as decided in 2.10, and make the deck settings tooltip true.

### Step 6: plugin API and plugins

Branch `feat/content-languages-6-plugins` in SlideMage, then one branch in each plugin repository. Design 2.9.
Depends on steps 1 and 4 being released.

- `plugin_api.py`:
  - `Literal["de", "en"]` becomes `str` at lines 722, 741 and 757. Add `project_languages()`, and export
    `address` next to `de_address`.
  - `insert_slides` writes the requested code into the file name.
  - `plugins/slide_reader.py` accepts any project code. The `german =` branch at line 85 becomes a language
    lookup.
- `slidemage-plugin-exam-forge`: `sources.py:95`, `ui/drafting.py:81` (project languages),
  `ui/questions_tab.py:742` (fallback to the main language), `elp_document.py:59` (`lang` from the deck).
- `slidemage-plugin-campusonline`: `course_schedule.py` falls back to English; `admin_slides.py`
  `LANGUAGE_NAMES` comes from the host, and `sessions_frame` defaults to the deck language.
- `slidemage-plugin-claude`: `claude/code/images.py`, the new image schema and the source → target prompt.
- Each plugin raises `requires_slidemage`. Coordinate with the plugin UI kit's author before merging.

### Step 7: manual and docs

Branch `docs/content-languages`.

- The manual deck's slides 1vn ("Languages") and 1uw (quick reference), `README.md`, `docs/SlideMage.md`, and a
  final CHANGELOG paragraph.
- Mark the design plan and this file as done, with the versions each step shipped in.

## 3. Order and sessions

| Step | Depends on | Size | Session |
|---|---|---|---|
| 0 | none | small | together with step 1, released first |
| 1 | none | medium | 1 |
| 2a | 1 | large (about 30 modules) | 1 |
| 2b | 2a | medium | 1 |
| 3 | 1 | small | can run in parallel after step 1 |
| 4 | 0 released, 1 | large | can run in parallel after step 1 |
| 5a | 1 | medium | can run in parallel after step 1 |
| 5b | 5a | spike plus medium | after step 5a; the spike can start any time |
| 6 | 1 and 4 released | medium, four repositories | last code step |
| 7 | all | small | last |

Steps 3, 4 and 5a touch separate files from step 2a, except for `ai/tasks.py` (3) and `slide_add.py` (2a). Rebase
whichever of the two merges second.
