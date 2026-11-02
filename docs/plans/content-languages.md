# Plan: any main language, any number of secondary languages

Status: draft (2026-11-02), not started. Decided 2026-11-02: languages are per project (2.1); multilingual slides
are kept and extended lightly (2.8); hyphenation by deck language is part of this task (2.10); old untagged slugs
get a light check (2.1); the image store is converted automatically (2.4); the main window's language switch
follows the deck's language (2.3); any translation can be made the group's original (2.2); a translation group
is a star, every translation naming the original (2.2); one formal or informal form of address per project (2.5);
the plugin API stays at version 1 (2.9). Asked for: "generalizing the language treatment in SlideMage. [...] retain
one language as a main language, but [...] leave the choice of main language up to the user. Furthermore, they
should be able to use multiple secondary languages, so that where SlideMage for example offers to translate to
German, it should offer to translate to any language of the user's choosing. The language selector then should
for example list all languages the user uses." Single-language slides keep their files as they are.

The app's own UI language is a separate task: [ui-translation.md](ui-translation.md). The two share only the table
of language names (section 2.1) and can be built in either order.

## 1. Today

English and German are wired in as a fixed pair in four places that have to move together.

**Slide files and translation links** (`slide_language.py`, `deck_language.py`, `slide_rename.py`, `slide_ids.py`,
`slide_add.py`):

- `LANGUAGES = ("EN", "DE", "mult")`, `TRANSLATION_LANGUAGES = ("EN", "DE")`. `own_language()` reads the id-slug's
  second segment and accepts only those three, which is also what keeps an old slug such as `xyz-IT-Governance` or
  `abc-AI-Tools` from being read as a language.
- Header comments `%% Translation of: <id-slug>` and `%% <LANG> translation: <id-slug>`; the regex allows only
  `EN|DE|mult`.
- `translation_link()` and `cross_referenced_language()` return *one* partner; `LanguageBadge` shows `[EN + DE]`;
  the Language panel has `OTHER = {"EN": "DE", "DE": "EN"}`.
- `slide_add.can_translate()`: only EN → DE, because the last-resort model prompt says "into German".
- `appendix_toc.py` and `alt_blocks.py` repeat `("EN", "DE", "mult")`.

**Decks and compiles** (`deck_settings.py`, `compiler.py`, `presentation/frames.py`, `background_renders.py`,
`render_key.py`, `compile_records.py`, `deck_headers.py`, `unused_content.py`, `update_all_previews.py`):

- A deck is single-language via `\decklanguage[xx]` (any code is already accepted there).
- "The other language" is computed as `"DE" if deck is en else "EN"` (`compiler.deck_pdfs`,
  `frames.candidate_jobnames`).
- Background previews: setting `bg_previews_second_language` adds "the other one".
- The topbar language switch and the workspace state use `UI_LANGUAGES = TRANSLATION_LANGUAGES`.
- The deck settings sheet offers `{"en": "English", "de": "Deutsch"}` plus whatever the deck already has.

**LaTeX** (`latex/SlideMage_base.tex`, `latex/SlideMage_alt.lua`):

- `\setSlideLanguageFromSlug@aux` recognises the fixed keywords `EN`, `DE`, `mult`.
- `\ifSMGerman` (true for `de`) drives the automatic texts "Bildquelle(n)"/"Image source(s)", "Bild:"/"Image:",
  and the two-argument `\multilingualtext{EN}{DE}`. PDF `/Lang`: `en` → `en-US`, `de` → `de-DE`, anything else
  the code itself.
- `\multilingualtext*{EN=..., DE=..., FR=...}` already takes any number of languages; it falls back to `EN`, then
  to the first key.
- No `babel`/`polyglossia`: hyphenation is the format's default (US English) in every deck, although the deck
  settings tooltip says the language sets hyphenation.

**Image descriptions** (`alt_images.py`, `alt_draft.py`, `image_review.py`, the Images page and form, the Lua):

- The store has English fields (`short`, `long`, `takeaway_default`, `source`, `status`) and German counterparts
  with a `_de` suffix, plus `translated_from_hash` of the English text. `SlideUse` has `takeaway` and `takeaway_de`.
- The CSV that LuaLaTeX reads has fixed positional columns (4/5 English, 7/8 German).
- The Images page has an EN | DE switch; "Translate to German"; the review filter "No German".

**AI** (`ai/tasks.py`, `ai/translation_style.py`, `translation_prompts.py`, `ai/image_instructions.py`,
`ai/tools/slidemage.py`, Settings → AI):

- `LANGUAGE_NAMES = {"EN": "English", "DE": "German"}` (twice: `ai/tasks.py`, `ui/workspace/actions.py`).
- The German form of address (`de_address`: Sie/du) and a glossary of `EN = DE` lines.
- `translation_prompts.json` is already keyed by model → source → target, so it needs no format change.

**Transcript and plugins**: `transcript.STRINGS` has `en` and `de`; `deck_language_of()` maps any other code to
`en`. `plugin_api.py` (API version 1) types languages as `Literal["de", "en"]`; `plugins/slide_reader.py` accepts
only those two.

In all: about 24 modules and 42 calls of `own_language()`.

## 2. Design

### 2.1 Languages are project data

The project's languages live in `.slidemage/project.json` (shared and versioned with the project, like
`de_address`); there is no machine-wide default list (decided):

```json
"languages": {"main": "en", "secondary": ["de", "fr"]}
```

- Codes are ISO 639-1, two letters, stored lowercase; in slide file names they are uppercase (`FR`), as now.
  `mult` stays reserved.
- Every project states its languages (decided 2026-11-02, replacing "nothing is written until the user changes
  the languages"). When a new SlideMage first opens a project without the key, it writes the key once, worked out
  from the project: `main: "en"`, and `secondary: ["de"]` if the project uses German anywhere (slides, decks, image
  descriptions, `de_address`), else `[]`. New projects get the key at creation. There is no implicit EN + DE
  default and no special case for it; the one-time cost is that every preview renders once more.
- New module `languages.py` (no Qt): a table of about 40 languages with code, English name, native name, default
  PDF tag (`en-US`, `de-DE`, `fr-FR`, ...), which is not settable per project. The UI translation plan uses the same table for its language picker. `project_languages(ctx)` returns the ordered list, main first.
- **What "main" means**: the default language of a new slide and a new deck, the default source of a translation,
  the first entry of every language selector, the fallback of `\multilingualtext*` and of image descriptions, and
  the language the AI writes new drafts in. Changing the main language renames nothing and moves no text; with the
  per-language image store (2.4) it is safe at any time.
- Settings gets a **Languages** page (project section): main language (combo), secondary languages (a list with
  Add/Remove/reorder) and the project's form of address (2.5). Removing a language that slides or decks still use is allowed but warns with the count ("12 slides and
  1 deck are in French; they stay as they are, but SlideMage no longer offers French").

**Old slugs that look like a language** (decided: a light check). SlideMage itself always writes a language segment
(new slide, copy, import and rename all require one), so the only slides at risk are untagged files from before the
language feature (2026-08) or made outside SlideMage, whose slug starts with a two-letter capital word, e.g.
`x7k-IT-Governance` when Italian is added. A tagged slide (`x7k-EN-IT-Governance`) is never at risk. When a
language is added, SlideMage scans `slides/` for untagged id-slugs whose second segment equals the new code. It
usually finds none and shows nothing; if it finds any, the sheet lists them and offers to rename them through
`slide_rename` (which already repairs deck calls and links), inserting the slide's actual language, or to cancel.
Only listed codes are ever read as a language, so a code the project does not use can never misread a slug.

### 2.2 Slides: translation groups instead of pairs

- `own_language(id_slug, codes)`: accepts the project's codes plus `mult`. Callers that have a `ProjectContext`
  pass `project_languages(ctx)`; `TRANSLATION_LANGUAGES` and `LANGUAGES` become functions of the context. The
  constants are removed, so every one of the 24 modules is found by the tests and by grep rather than left behind.
- Header comments keep their form and allow any code: `%% FR translation: <id-slug>`. No migration.
- A slide's **translation group** is a star: one original (the slide that is nobody's translation) and its
  translations, each of which names the original in its `Translation of:` line. That holds also for a translation
  made from another translation (DE → FR when the original is EN): FR names EN, not DE. Which member a translation
  was made from is not recorded. The original has one `%% <LANG> translation:` line per language
  (`regenerate_translation_links` already tolerates several). `TranslationLinks.find(id_slug, language)` already
  resolves "the slide of that language for this slot"; it is extended from "partner" to "member of the group", with
  the same rule that conflicting links pick none.
- `translation_link()` becomes `translation_group()` → a list of `TranslationLink` (one per other language), each
  with its own `outdated` (measured against the original, as now).
- `LanguageBadge`: `[EN]`, `[EN + DE]`, `[EN + DE FR]`; at four or more languages `[EN +3]` with the full list in
  the tooltip. `both` becomes "has at least one translation".
- **Language panel**: one row per project language: the slide (own), each existing translation (open, outdated
  mark), and for each missing language "No translation yet" with **Translate to <language>**. The Set language menu
  lists the project's languages and Multilingual. A translation also shows **Make this the original**.
- **Make this the original** (decided 2026-11-02), for when the author starts writing in another language:
  `slide_rename.make_original(ctx, id_slug)` removes this slide's `Translation of:` line and points every other
  member's at this slide, the old original included. `regenerate_translation_links` then rewrites the
  `%% <LANG> translation:` lines. Allowed only while the files it rewrites have no unsaved edits, as for Set
  language. Rewriting the headers counts as writing, so right afterwards no member is outdated: making a slide the
  original declares the group in step.
- **Deck slots fold by group, not by direct link.** `deck_language._slots` folds a deck's calls into one slot only
  along a direct `Translation of:` or `<LANG> translation:` link today, so a deck that calls DE and FR of a group
  whose original is EN would show the slide twice. Instead:
  - `_slots` groups the deck's calls by translation group. If the deck calls the original, that call owns the slot;
    otherwise the earliest call into the group does. The others are folded into it, as today, and keep their
    visibility and reveal steps only through the owner, as today. After Make this the original, the slot moves to
    the new original's call where the deck has one.
  - `resolve_call(owner, language)` picks the group's member in `language` through `find()`; `related_ids` lists
    every member of the group.
  - A group is valid only when every translation names the same original. A chain (FR names DE, DE names EN, as a
    hand-edited header could leave it) is rewritten as a star by **Reestablish broken translation links**. A cycle
    (A names B, B names A) has no original: each call stays its own slot, as the existing rule for malformed
    reciprocal links does today, and Reestablish broken translation links reports it instead of rewriting it.
  - `deck_headers` and `compile_records`, which call `slots()` per language, need no change of their own.
- **Add slide** sheet: "Copy as translation" offers every project language the group does not have yet.
- The AI task card's translation (`ui/workspace/task_bubbles.py`, today `next(code ...)`, the first other language)
  takes its target from the command, with one offer per missing project language.

### 2.3 Decks, compiles and previews

- `\decklanguage[xx]` is unchanged. The deck settings sheet offers the project's languages (plus the deck's own,
  should it be another).
- "The other language" becomes "the other project languages": `compiler.deck_pdfs` and
  `frames.candidate_jobnames` look for the PDFs of every project language.
- The topbar language switch lists the project's languages, main first, as a segmented control of their codes.
  Since the switch follows the deck (below), picking another language is only a short look, and a dropdown for
  long lists waits until a project has more languages than fit.
- **The switch follows the deck** (decided 2026-11-02). Today `WorkspaceState.set_deck` restores the language last
  chosen for that deck (`_remember("language", ...)` in `app_settings`) and uses the deck's `\decklanguage` only
  while nothing was chosen. Instead: opening a deck or switching to another one always sets the switch to that
  deck's `\decklanguage`; changing the deck's language in its settings sheet moves the switch along; picking
  another language on the switch is a temporary look at the translations, kept only until the next deck switch or
  restart, and no longer remembered per deck (`set_language` stops writing it; a stored value is ignored and
  dropped). A deck whose language is not one of the project's still shows it, as an extra entry on the switch.
- Background previews take the deck's language as their first language (`languages_for` uses `\decklanguage`
  instead of the usage record's `last_language`).
- Background previews: `bg_previews_second_language` stays a yes/no setting, with its key; it now means "also
  render the deck's slides in the other project languages they exist in". The cost is bounded by the translations
  that exist, so there is no list setting and nothing to convert.
- `compile_records`, `deck_headers`, `unused_content`, `update_all_previews`, `render_key`: iterate over the
  project's languages instead of the constant. No change to the render store's keys, which already carry the code.

### 2.4 Image descriptions per language

The store becomes language-explicit (format version 2):

```json
"text": {
  "en": {"short": "...", "long": "...", "takeaway_default": "...", "source": "...", "status": "reviewed"},
  "de": {"short": "...", "long": "...", "source": "", "status": "auto",
         "translated_from": "en", "from_hash": "a1b2c3d4e5f6"}
}
```

and `used_on[slide].takeaway` becomes a `{lang: text}` map. The role, the hint, `drafted_by` and the reviewed stamp
stay shared, as now.

- Reading: a version-1 entry is read as `en` (plain fields) and `de` (`_de` fields, `translated_from: "en"`). The
  in-memory `ImageEntry` only has the new shape; every reader goes through `entry.text_for(lang)` with the
  fallback chain own language → `translated_from` → main language (the source field keeps its current "empty means
  same citation" rule).
- Decided: the store is converted automatically, the first time the new SlideMage opens the project (a backup of
  the version-1 file is kept next to it as `media/alt-text.v1.json`). An older
  SlideMage cannot read version 2, so the CHANGELOG and the release notes say to update every machine before
  opening the project; an older SlideMage that meets a version-2 store must refuse to write it rather than
  overwrite it with version 1 (check what the current release does and, if needed, ship that guard in a release
  before this one).
- The CSV for LuaLaTeX already has a header row naming its columns (`image,role,status_en,short_alt_en,source_en,
  status_de,short_alt_de,source_de`). The en and de columns stay where they are and each further language appends
  `status_xx,short_alt_xx,source_xx`, so an older framework copy that reads columns 4, 5, 7 and 8 by position keeps
  working. `SlideMage_alt.lua` reads columns by name, and `altText`/`recordSource` take any code with the same
  fallback chain.
- Images page: the EN | DE switch lists the project's languages; the form's "German" group becomes "<language>"
  for the one selected; **Translate to <language>** and the batch "Translate descriptions" ask for the target
  (default: every secondary language that is missing or stale). Review filter "No German" becomes "Missing a
  translation" with a language choice.
- `ai/image_instructions.py`: the German rule becomes "write the fields of the requested language in that
  language", with the language's name filled in. The answer schema in `ai/image_tasks.py` (`short_de`, `long_de`,
  `takeaway_de`) becomes `short`, `long`, `takeaway` for the requested language.
- The Claude plugin (`claude/code/images.py`) uses the same `_de` schema and fields; it is updated and released
  together with this step.

### 2.5 AI translation to any language

- `can_translate()` allows any pair of project languages. The last-resort prompt is a template with
  `{source}`/`{target}` names from `languages.py`; `translation_prompts.json` needs no change, and the Settings
  prompt page lists every pair of project languages instead of en → de only. A local MT model that cannot handle a
  pair is the user's call; the prompt page shows which pairs have their own prompt.
- `ai/tasks.py`: `LANGUAGE_NAMES` comes from `languages.py`; the form-of-address line is added for every target
  language, not only `DE`; proofreading uses the same rule.
- **Form of address**: one setting per project, formal or informal, for every language and every deck (slides are
  shared between decks, so a per-deck setting could not hold for a shared slide). The prompt says "address the
  reader formally" (or informally) and leaves it to the model what that means in the target language (Sie, vous,
  usted, ...); a language without the distinction, such as English, is unaffected. `languages.py` needs no address
  words. `translation_style.py`: `de_address` becomes `address: "formal" | "informal"` in `project.json`, read from
  `de_address` when missing (Sie = formal, du = informal), and `de_address` is still written alongside it, so an
  older SlideMage keeps working.
- Glossary: `.slidemage/glossary.md` may hold a Markdown table with one column per language (`| EN | DE | FR |`);
  the old `EN = DE` lines are still read. Each request carries the rows for its pair only.
- `ai/tools/slidemage.py`: the `language` enums come from the project's languages.

### 2.6 Automatic texts, PDF language, transcript

- `SlideMage_base.tex` gets a string table instead of `\ifSMGerman` branches:
  `\SMSetLanguageStrings{de}{ImageSource={Bildquelle(n)}, ImagePrefix={Bild:}}`, shipped for en, de, fr, es, it;
  a project adds or overrides entries in `SlideMage_project_macros.tex`. A missing entry falls back to the main
  language, then to English, with a warning in the log. `\ifSMGerman` stays defined (true for `de`), because
  templates and slides may test it.
- PDF `/Lang` is the deck language's tag from the table in `languages.py`, passed into the compile (2.7). A deck
  compiled outside SlideMage keeps today's rule (`en-US`, `de-DE`, anything else the code itself).
- `\multilingualtext*` falls back to the main language (`\SMMainLanguage`) instead of `EN`.
- `transcript.STRINGS` gets the same languages as the LaTeX table; `deck_language_of()` returns the deck's code,
  and the strings fall back to the main language, then English.
- `transcript._resolve_multilingual_text` today finds only `\multilingualtext{`; it also resolves the keyed
  `\multilingualtext*{...}`, with the same fallback as TeX.

### 2.7 How LaTeX learns the project's languages

`\setSlideLanguageFromSlug` must recognise the same codes as Python (section 2.1, old slugs). SlideMage already adds
one line to every compile and preview after the deck preamble (`deck_language.language_line`, used by
`compiler.py`, `partial_compile.py` and `slide_preview.py`), which today is `\decklanguage[xx]`. That line also
carries the project's languages, its main language and the deck language's PDF tag:
`\SMProjectLanguages{EN,DE,FR}\SMMainLanguage{en}\SMPdfLang{fr-FR}\decklanguage[fr]`.

- No generated file: nothing to write when the languages change, to commit, or to find stale on another machine.
- `render_key` must include the project's languages and main language, because they change how a slide's
  language is read and what `\multilingualtext*` falls back to. The line's text is the natural input.
- Without the line (a deck compiled outside SlideMage) TeX keeps today's `EN, DE, mult` and falls back to `EN`, so
  a project that never changes its languages behaves as now. In a project with further languages, such a compile
  still runs, but slides in those languages count as untagged, so their footer language is wrong.

### 2.8 Multilingual slides

Decided: keep `mult` slides as they are and make them work with N languages, but do not add new machinery.

- `\multilingualtext*{...}` (keyed) is already N-language; the two-argument form stays exactly EN/DE (documented
  as the old form). New multilingual slides from SlideMage templates use the keyed form, and so does the editor's
  "Both languages" insertion (`latex_edit.py`) in a project with more than two languages, one key per language.
- Fallback to the main language instead of English (2.6).
- Not in this task: showing on a `mult` slide which languages its `\multilingualtext*` calls lack ("FR: 2 of 3
  texts missing, shown in English"), and AI translation of a multilingual slide (adding a key to each call). They
  are a natural follow-up together.

The alternative, converting `mult` slides into a translation group, is what the user can already do by hand
(Copy as translation); forcing it would break decks that rely on one file.

### 2.9 Plugins

`plugin_api` stays at version 1: languages become `str` (a project code, lowercase) instead of
`Literal["de", "en"]`, `deck_language()` may return any code, and the host gets a new `project_languages()`. Both
keep existing plugin code working, so there is no version bump and no mapping of codes for older plugins. The
plugins that assume en/de are the risk, and they are updated in the same release (below); until then a French deck
reaches them as `fr`. `plugins/slide_reader.py` takes any project code. `insert_slides` writes the requested code into the file name (today anything but `en`
becomes `DE`).

The plugins that assume en/de are updated with this step:

- **Exam Forge**: source links accept any project code (`sources.py`), the drafting dialog lists the project's
  languages, the fallback is the main language instead of `en`, and the exam HTML gets the deck's `lang`.
- **CampusOnline**: an unknown language falls back to English everywhere (`course_schedule.py` falls back to German
  today, `course_box.py` to English).
- **Claude**: the image description schema, with step 4 (2.4).

Coordinate with the plugin UI kit's author before merging, since each updated plugin raises its
`requires_slidemage`. The UI translation plan adds plugin translation to the API (ui-translation.md, 2.6), also as an
addition to version 1.

### 2.10 Hyphenation by deck language

Decided: in this task. Today every deck hyphenates with the format's default US English patterns, whatever its
`\decklanguage`.

- A deck hyphenates in one language, so only that language is loaded. `SlideMage_base.tex` loads `babel` for
  LuaLaTeX with the ini-based setup, no shorthands (so `"` in German slides keeps meaning what it does now), and no
  babel captions or date formats (beamer's own texts and the string table of 2.6 stay in charge).
- `\decklanguage[xx]` only records the code, and the deck's one language is set up and selected for the document
  body when the preamble ends (`\babelprovide[import]{xx}`, English and German without it). So the last
  `\decklanguage` wins, as now, and the line SlideMage appends after the preamble (`deck_language.language_line`)
  still decides. Babel needs no list of the project's languages.
- `\multilingualtext*` and `mult` slides hyphenate in the deck's language, which is the language they print.
- Places that switch hyphenation off on purpose (titles, quotes: `\hyphenpenalty=10000`) are unaffected.

Risks, checked before anything else in step 5 (a spike on a copy of the example project):

- **Preview formats.** babel's LuaTeX pattern loading keeps state in Lua, which a precompiled format loses
  (`preview_format.py`). It may need its own replay through `\SMLuaOnce`, or the patterns must be loaded at format
  build time; since a compile loads only its deck's language, that means one format per language. The preview must still typeset exactly like the final compile (the equivalence contract,
  `docs/PREVIEW_RENDER_EQUIVALENCE_CONTRACT.md`).
- **Changed line breaks in existing decks.** German decks will hyphenate differently, and a slide that fitted may
  now break a line elsewhere, or the reverse. Before merging: compile every non-English deck of the example
  project and of the owner's course project with and without the change, compare per page with the render store,
  and list the slides whose layout changed (overfull boxes, more lines, different reveal-step height). The owner
  reviews that list; the change ships with it in the CHANGELOG.
- **Compile time**: measured on a large deck before and after.

The deck settings tooltip ("hyphenation, automatic texts, ...") becomes true; until then it is corrected.

## 3. Steps

Each step ends with the test suite green (`pytest -n 8`) and nothing changed for a project that keeps EN + DE.

1. **Language registry and settings** — `languages.py`, `project_languages(ctx)`, the `project.json` key, the
   Languages settings page, the project's languages on the compile line and their reading in `SlideMage_base.tex`
   (2.7).
2. **Slides and decks** — `own_language(…, codes)`, removal of the constants across the 24 modules, translation
   groups, Make this the original, badges, Language panel, Add slide, slug-collision check and rename, deck
   settings, topbar switch,
   compiler/frames/background previews/compile records.
3. **AI translation** — prompts for any pair, formal or informal address, glossary table, AI tool enums.
4. **Image descriptions** — store version 2 with automatic conversion and backup, CSV header and Lua, Images page and form,
   review filters, image instructions.
5. **LaTeX texts, PDF language, transcript, multilingual slides, hyphenation** — string table, PDF tag, fallback
   to main language, transcript strings; then the hyphenation spike (preview formats,
   layout comparison, compile time) and, once it holds, `babel` per deck language (2.10).
6. **Plugin API and plugins** — `str` languages and `project_languages()` in version 1, Exam Forge,
   CampusOnline, Claude.
7. **Manual and docs** — the manual deck's language slides (1vn "Languages" and the quick reference 1uw), README,
   `docs/SlideMage.md`, CHANGELOG.

Steps 3, 4 and 6 depend only on step 1 and touch separate files, so they can run in their own sessions after step 1
is merged. Step 2 is the large one and should be one session. The UI translation task is independent of all of
them.

## 4. Tests

- A fixture project with main `de` and secondary `en, fr`: slide list badges, Language panel rows, translation of a
  translation, deck PDFs found for all three languages, background preview languages.
- Make this the original: in a group with original EN and translations DE, FR and IT, making FR the original
  leaves EN, DE and IT all naming FR, FR naming none, and no member outdated right after; a deck listing EN and FR
  separately has its slot at FR's call afterwards.
- Deck slots by group: a deck that calls EN and FR of a group with original EN shows one slot, at EN's call, and
  shows FR's file when compiled in French; a deck that calls DE and IT of that group shows one slot, at the earlier
  call; a chain (FR names DE, DE names EN) is rewritten as a star by Reestablish broken translation links; a cycle
  of two slides gives two slots and a report.
- Language switch: switching from an English deck to a German one shows DE, back shows EN, also after picking FR
  on the first deck; changing a deck's language in its settings moves the switch; a stored per-deck language from
  an older version is ignored.
- A legacy fixture with no `languages` key and version-1 image store: identical output to today (compile, CSV,
  transcript, badges).
- Slug collision: adding `it` to a project with `x7k-IT-Governance` lists it and renames it correctly; without `it`
  in the list, the slug is not a language in Python or in TeX.
- Image store: a version-1 store is converted on first open, with its backup, and reads back identically; the Lua
  reads the CSV by column name and picks `fr` with the fallback chain, and an older framework copy still reads en
  and de from a CSV with an appended `fr`.
- LaTeX: a French deck shows the French automatic texts and `/Lang fr-FR`; a language missing from the string table
  falls back to the main language with a warning.
- Compile line: a preview's render key changes when the project's languages or main language change; a deck
  compiled without the line reads only EN, DE and mult.
- Plugin API: on a French deck `deck_language()` returns `fr`, and `insert_slides` with `fr` writes an `FR` file.
- Transcript: a `mult` slide with `\multilingualtext*{EN=..., FR=...}` shows only the deck language's text.

## 5. Open questions for the owner

All answered 2026-11-02: multilingual slides kept and extended lightly (2.8); language list per project only
(2.1); hyphenation in this task (2.10); a light check for old untagged slugs (2.1); the image store converted
automatically (2.4).

Also decided 2026-11-02 (left to the plan's author): LaTeX learns the project's languages from the compile line,
not from a generated file (2.7); background previews keep their yes/no setting (2.3); PDF tags come only from the
built-in table (2.1, 2.6).

Still to find out during implementation (no decision needed): whether the current release already refuses to
overwrite an image store of a newer format (2.4), and whether babel survives the preview formats (2.10).

## 6. Status (2026-11-02)

The branches are stacked, each on the one before, in this order; each ends with the suite green apart from three
failures that `develop` has too or that come from the worktree path (the zip fixtures of `test_citations.py` and
`test_theme_sources.py`, and the LuaTeX log line `test_the_default_is_loaded_...` searches for, which a longer path
wraps):

| Version | Branch | Step |
|---|---|---|
| v0.13.24 | `fix/alt-store-version-guard` (on `develop`) | an older SlideMage never overwrites a newer image store |
| v0.13.25 | `feat/content-languages-1-registry` | 1 and 1b |
| v0.13.26 | `feat/content-languages-2a-groups` | 2a, and a test commit: a test project without the key is EN + DE (`infer_languages` marks the tests of the inference) |
| v0.13.27 | `feat/content-languages-3-ai` | 3 |
| v0.13.28 | `feat/content-languages-5a-texts` | 5a |
| v0.13.29 | `feat/content-languages-2b-ui` | 2b (tried in the app) |
| v0.13.30 | `feat/content-languages-4-images` | a fix (a new project no longer copies the example's `.slidemage` state), then 4 |
| v0.13.31 | `feat/content-languages-6-plugin-api` | 6, SlideMage's part |

Worktrees: `.worktrees/cl-1`, `cl-2a`, `cl-3`, `cl-5a`, `cl-2b`, `cl-4`, `cl-6` (and the empty `cl-5b-spike`).

Decided while implementing, differing from the text above:

- The image store's new format is **version 3** (version 2 was the current one); the backup is
  `media/alt-text.v2.json`. The v0.13.24 guard refuses to write anything above 2. Step 4's CHANGELOG has a
  BREAKING paragraph and a `compat.CHANGES` entry: every machine needs the new version before it opens the project.
- The short alt text has **no fallback** in the PDF (an untranslated language has none, as German today); only the
  source follows the chain. The transcript and `slide_reader` use the language's own text.
- `alt_draft.TranslationResult` keeps its `short_de`/`long_de`/`takeaway_de` names and has a `language`; a backend
  without `target_lang` (the Claude plugin today) translates into German only and says so for another language.
  Core's `image_tasks.TRANSLATE` schema has `short`, `long`, `takeaway` since step 6.
- `insert_slides` refuses a language the project does not have.
- The Images page builds its language list when it is built; a language added in Settings shows after the page is
  built again.

Next:

1. **5b**, the hyphenation spike (2.10), in `cl-5b-spike`.
2. **6, the plugins** (Exam Forge done as 0.9.0 on `feature/any-language`, on top of `feature/ui-redesign`, pushed to
   JuergenFleiss/slidemage-plugin-exam-forge) in their own repositories, each raising `requires_slidemage` to v0.13.31: Exam Forge (sources
   with any project code, the drafting dialog's languages, the main language as fallback, the exam HTML's `lang`),
   CampusOnline (done as CampusOnline 1.0.2, committed only locally on branch `feature/any-language` in
   `~/github/slidemage-plugin-campusonline-langs`; no new API, so its requires_slidemage stays), Claude (done as Claude 1.2.0, committed only locally on branch
   `feature/any-language-images` in the worktree `~/github/slidemage-plugin-claude-langs`, from `origin/main`; its
   suite has 15 failures against `develop` too, from drift between the plugin and SlideMage). Coordinate with the
   plugin UI kit's author first.
3. **7**, the manual and docs.
4. PRs into `develop` in the order of the table, after testing.
