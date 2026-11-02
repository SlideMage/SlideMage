# Plan: any main language, any number of secondary languages

Status: draft (2026-11-02), not started. Decided 2026-11-02: languages are per project (2.1); multilingual slides
are kept and extended lightly (2.8); hyphenation by deck language is part of this task (2.10); old untagged slugs
get a light check (2.1); the image store is converted automatically (2.4). Asked for: "generalizing the language treatment in SlideMage. [...] retain
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
- A project without the key behaves as today: `main: "en"`, `secondary: ["de"]`. Nothing is written until the
  user changes the languages.
- New module `languages.py` (no Qt): a table of about 40 languages with code, English name, native name, default
  PDF tag (`en-US`, `de-DE`, `fr-FR`, ...) and, where the language has one, the choice of form of address (de: Sie/du,
  fr: vous/tu, es: usted/tú, it: Lei/tu, nl: u/jij, ...). The UI translation plan uses the same table for its
  language picker. `project_languages(ctx)` returns the ordered list, main first.
- **What "main" means**: the default language of a new slide and a new deck, the default source of a translation,
  the first entry of every language selector, the fallback of `\multilingualtext*` and of image descriptions, and
  the language the AI writes new drafts in. Changing the main language renames nothing and moves no text; with the
  per-language image store (2.4) it is safe at any time.
- Settings gets a **Languages** page (project section): main language (combo), secondary languages (a list with
  Add/Remove/reorder), and per language the PDF tag (so `en-GB` is possible) and, where it has one, the form of
  address. Removing a language that slides or decks still use is allowed but warns with the count ("12 slides and
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
- A slide's **translation group** is the set of slides connected by those links: one original (the slide that is
  nobody's translation) and its translations. A translation may be made from another translation (DE → FR when the
  original is EN); its `Translation of:` names the slide it was made from, and the group is still found through
  it. `TranslationLinks.find(id_slug, language)` already resolves "the slide of that language for this slot"; it
  is extended from "partner" to "member of the group", with the same rule that conflicting links pick none.
- `translation_link()` becomes `translation_group()` → a list of `TranslationLink` (one per other language), each
  with its own `outdated` (measured against the slide it was made from, as now).
- `LanguageBadge`: `[EN]`, `[EN + DE]`, `[EN + DE FR]`; at four or more languages `[EN +3]` with the full list in
  the tooltip. `both` becomes "has at least one translation".
- **Language panel**: one row per project language: the slide (own), each existing translation (open, outdated
  mark), and for each missing language "No translation yet" with **Translate to <language>**. The Set language menu
  lists the project's languages and Multilingual.
- **Add slide** sheet: "Copy as translation" offers every project language the group does not have yet.

### 2.3 Decks, compiles and previews

- `\decklanguage[xx]` is unchanged. The deck settings sheet offers the project's languages (plus the deck's own,
  should it be another).
- "The other language" becomes "the other project languages": `compiler.deck_pdfs` and
  `frames.candidate_jobnames` look for the PDFs of every project language.
- The topbar language switch lists the project's languages, main first; a segmented control up to three, a
  dropdown above that. `state.language` remembers the last one per deck as now.
- Background previews: `bg_previews_second_language` (bool) becomes `bg_previews_languages` (a list, default empty,
  the old `true` read as "all secondary languages"); the setting says how many more renders each language costs.
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
- The CSV for LuaLaTeX gets a header row naming its columns (`image,role,short@en,source@en,short@de,...`);
  `SlideMage_alt.lua` reads columns by name, and `altText`/`recordSource` take any code with the same fallback chain.
  A CSV without a header row is still read by position.
- Images page: the EN | DE switch lists the project's languages; the form's "German" group becomes "<language>"
  for the one selected; **Translate to <language>** and the batch "Translate descriptions" ask for the target
  (default: every secondary language that is missing or stale). Review filter "No German" becomes "Missing a
  translation" with a language choice.
- `ai/image_instructions.py`: the German rule becomes "write the fields of the requested language in that
  language", with the language's name filled in.

### 2.5 AI translation to any language

- `can_translate()` allows any pair of project languages. The last-resort prompt is a template with
  `{source}`/`{target}` names from `languages.py`; `translation_prompts.json` needs no change, and the Settings
  prompt page lists every pair of project languages instead of en → de only. A local MT model that cannot handle a
  pair is the user's call; the prompt page shows which pairs have their own prompt.
- `ai/tasks.py`: `LANGUAGE_NAMES` comes from `languages.py`; the form-of-address line is added for every target
  language that has a setting, not only `DE`; proofreading uses the same per-language rule.
- `translation_style.py`: `de_address` becomes `addresses: {"de": "Sie", "fr": "vous"}` in `project.json`, with
  `de_address` still read (and written as long as only German has one, so an older SlideMage keeps working).
- Glossary: `.slidemage/glossary.md` may hold a Markdown table with one column per language (`| EN | DE | FR |`);
  the old `EN = DE` lines are still read. Each request carries the rows for its pair only.
- `ai/tools/slidemage.py`: the `language` enums come from the project's languages.

### 2.6 Automatic texts, PDF language, transcript

- `SlideMage_base.tex` gets a string table instead of `\ifSMGerman` branches:
  `\SMSetLanguageStrings{de}{ImageSource={Bildquelle(n)}, ImagePrefix={Bild:}}`, shipped for en, de, fr, es, it;
  a project adds or overrides entries in `SlideMage_project_macros.tex`. A missing entry falls back to the main
  language, then to English, with a warning in the log. `\ifSMGerman` stays defined (true for `de`), because
  templates and slides may test it.
- PDF `/Lang` comes from the project's per-language PDF tag (written into the compile, see 2.7); the built-in table
  is the default.
- `\multilingualtext*` falls back to the main language (`\SMMainLanguage`) instead of `EN`.
- `transcript.STRINGS` gets the same languages as the LaTeX table; `deck_language_of()` returns the deck's code,
  and the strings fall back to the main language, then English.

### 2.7 How LaTeX learns the project's languages

`\setSlideLanguageFromSlug` must recognise the same codes as Python (section 2.1, old slugs). SlideMage writes a
generated file `SlideMage_languages.tex` at the project root whenever the languages change (`\SMProjectLanguages{EN,
DE,FR}`, `\SMMainLanguage{en}`, the PDF tags); `SlideMage_base.tex` loads it when present, like the project
macros. Without it TeX keeps today's `EN, DE, mult`, so a project that never changes its languages and a deck
compiled by hand outside SlideMage behave as now. The file is committed with the project.

### 2.8 Multilingual slides

Decided: keep `mult` slides as they are and make them work with N languages, but do not add new machinery.

- `\multilingualtext*{...}` (keyed) is already N-language; the two-argument form stays exactly EN/DE (documented
  as the old form). New multilingual slides from SlideMage templates use the keyed form.
- Fallback to the main language instead of English (2.6).
- The Language panel of a `mult` slide lists, per project language, whether every `\multilingualtext*` on it has a
  key for it ("FR: 2 of 3 texts missing, shown in English"). This is a scan of the source, no compile.
- Not in this task: AI translation of a multilingual slide (adding a key to each call). It is a natural follow-up
  once the panel shows what is missing.

The alternative, converting `mult` slides into a translation group, is what the user can already do by hand
(Copy as translation); forcing it would break decks that rely on one file.

### 2.9 Plugins

`plugin_api` version 2: languages are `str` (a project code, lowercase) instead of `Literal["de", "en"]`;
`deck_language()` may return any code; new `project_languages()` on the host. Version-1 plugins keep working: the
host maps a code other than en/de to the main language for them. `plugins/slide_reader.py` takes any project code.
Coordinate with the plugin UI kit's author before merging, since the manifest versions change. The UI translation
plan adds plugin translation to the API (ui-translation.md, 2.6); both should land in the same API version.

### 2.10 Hyphenation by deck language

Decided: in this task. Today every deck hyphenates with the format's default US English patterns, whatever its
`\decklanguage`.

- `SlideMage_base.tex` loads `babel` for LuaLaTeX with the ini-based setup: `\babelprovide[import]{<language>}` for
  each language of `SlideMage_languages.tex` (English and German without it), no shorthands (so `"` in German
  slides keeps meaning what it does now), and no babel captions or date formats (beamer's own texts and the
  string table of 2.6 stay in charge).
- `\decklanguage[xx]` selects the language for the document body (`\AtBeginDocument{\selectlanguage{...}}`), so
  the line SlideMage appends after the preamble (`deck_language.language_line`) still decides.
- `\multilingualtext*` and `mult` slides hyphenate in the deck's language, which is the language they print.
- Places that switch hyphenation off on purpose (titles, quotes: `\hyphenpenalty=10000`) are unaffected.

Risks, checked before anything else in step 5 (a spike on a copy of the example project):

- **Preview formats.** babel's LuaTeX pattern loading keeps state in Lua, which a precompiled format loses
  (`preview_format.py`). It may need its own replay through `\SMLuaOnce`, or the patterns must be loaded at format
  build time. The preview must still typeset exactly like the final compile (the equivalence contract,
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
   Languages settings page, `SlideMage_languages.tex` generation and loading in `SlideMage_base.tex`.
2. **Slides and decks** — `own_language(…, codes)`, removal of the constants across the 24 modules, translation
   groups, badges, Language panel, Add slide, slug-collision check and rename, deck settings, topbar switch,
   compiler/frames/background previews/compile records.
3. **AI translation** — prompts for any pair, per-language address, glossary table, AI tool enums.
4. **Image descriptions** — store version 2 with automatic conversion and backup, CSV header and Lua, Images page and form,
   review filters, image instructions.
5. **LaTeX texts, PDF language, transcript, multilingual slides, hyphenation** — string table, PDF tags, fallback
   to main language, transcript strings, the `mult` coverage display; then the hyphenation spike (preview formats,
   layout comparison, compile time) and, once it holds, `babel` per deck language (2.10).
6. **Plugin API version 2.**
7. **Manual and docs** — the manual deck's language slides (1vn "Languages" and the quick reference 1uw), README,
   `docs/SlideMage.md`, CHANGELOG.

Steps 3, 4 and 6 depend only on step 1 and touch separate files, so they can run in their own sessions after step 1
is merged. Step 2 is the large one and should be one session. The UI translation task is independent of all of
them.

## 4. Tests

- A fixture project with main `de` and secondary `en, fr`: slide list badges, Language panel rows, translation of a
  translation, deck PDFs found for all three languages, background preview languages.
- A legacy fixture with no `languages` key and version-1 image store: identical output to today (compile, CSV,
  transcript, badges).
- Slug collision: adding `it` to a project with `x7k-IT-Governance` lists it and renames it correctly; without `it`
  in the list, the slug is not a language in Python or in TeX.
- Image store: a version-1 store is converted on first open, with its backup, and reads back identically; the Lua
  reads both CSV forms and picks `fr` with the fallback chain.
- LaTeX: a French deck shows the French automatic texts and `/Lang fr-FR`; a language missing from the string table
  falls back to the main language with a warning.
- Plugin API: a version-1 plugin on a French deck gets the main language.

## 5. Open questions for the owner

All answered 2026-11-02: multilingual slides kept and extended lightly (2.8); language list per project only
(2.1); hyphenation in this task (2.10); a light check for old untagged slugs (2.1); the image store converted
automatically (2.4).

Still to find out during implementation (no decision needed): whether the current release already refuses to
overwrite an image store of a newer format (2.4), and whether babel survives the preview formats (2.10).
