# Plan: SlideMage's own UI in other languages

Status: draft (2026-11-02), not started. Decided 2026-11-02: gettext (2.1); a change takes effect after a restart
(2.2); German is the only language shipped at first (2.4); plugins get translation support in this task (2.6); a
German manual is a later task (section 5). Asked for: "the user should be able to switch the app language itself to
another language." Split off from the content-language work ([content-languages.md](content-languages.md)) on the
owner's suggestion: the two are independent. The only shared piece is the language table `languages.py`
(content-languages.md, 2.1); whichever task comes first creates it.

## 1. Today

- There is no translation layer: no `tr()`, no `QTranslator`, no gettext. Every string is an English literal in
  the code: labels, tooltips, menus, dialogs, task cards, status lines, error messages.
- Size: about 37,000 lines in `ui/` (83,000 in the package); a rough count finds several thousand English sentence
  literals, most of them in `ui/`, many as f-strings (`f"Translating {n} images to German"`) and many as module
  constants evaluated at import (`LANGUAGE_LABELS`, `TRANSLATION_TEXT`, tooltips assembled at class level).
- Plurals are formed by `ui/text.plural()`, which appends "s" (19 calls) and cannot work in another language.
- Qt's own texts (QMessageBox buttons, QFileDialog, context menus of text fields) follow the Qt translations that
  are loaded, which today is none: they are English.
- Some text is not UI text and stays out of this task: the debug log and diagnostics (support reads them), LaTeX
  output, the CLI's machine-readable output, and everything a deck produces (that follows the deck's language).

**UI language ≠ content language.** The UI language is the user's, per machine; the main and secondary languages are
the project's. A German-speaking user can run a German UI on an English-main project and vice versa. Names of
languages in the UI appear in the UI language ("Französisch" in a German UI), from `languages.py` through the same
translation catalogue.

## 2. Design

### 2.1 Mechanism: gettext, plus Qt's own catalogue

Decided: Python's `gettext` with `.po`/`.mo` files, not Qt's `tr()`/`.ts`.

- Many strings live outside `QObject` subclasses (module constants, `transcript.py`, `compat_*` findings,
  `plugins/host.py`, core modules marked "No Qt"), which `tr()` handles badly; `_()` works everywhere.
- `.po` is what translators and tools know (Poedit, Weblate, `pybabel`/`xgettext` for extraction) and has proper
  plural forms (`ngettext`).
- Plugins can use the same mechanism with their own domain.
- In addition, `QTranslator` loads Qt's own `qtbase_<lang>.qm` (shipped with PySide6) so the standard dialogs
  match.

New module `slidemage/i18n.py`:

```python
_ = gettext                       # "Open pdf"
ngettext(singular, plural, n)     # "{n} slide" / "{n} slides"
N_("...")                         # marks a module constant; translated where it is shown
pgettext(context, text)           # same English word, different meaning ("Open" a file vs. "Open" state)
install(language)                 # once, at start-up, before any window is built
```

Catalogues in `src/slidemage/locale/<lang>/LC_MESSAGES/slidemage.po` (and the compiled `.mo`, built at release
time by the build script, not committed by hand). English is the source language; there is no `en` catalogue.

### 2.2 Choosing the language

- Settings → General: **Language of SlideMage** (combo: "System default" plus each shipped language, shown in its
  own name: English, Deutsch, ...). Stored per machine in `config_dir()/ui_settings.json` (like the AI settings),
  not in the project, because it belongs to the person, not the project.
- "System default" takes the OS locale when a catalogue for it exists, else English.
- **A change takes effect after a restart** (decided; the sheet says so and offers "Restart now"). Live retranslation would
  need every widget to rebuild its texts on a language-change event, which for this many widgets is a large,
  permanent cost for a setting changed once.
- The Presenter app (`presenter_app.py`) and the CLI's interactive messages use the same setting.

### 2.3 Rules for strings in code

These go into the contributor notes and are checked by a test (2.5):

- Every user-visible string goes through `_()`, `ngettext()` or `N_()`. f-strings become format strings with named
  placeholders: `_("Translating {count} images to {language}").format(...)`, so a translation can move the
  placeholder.
- No sentences assembled from pieces (`"Translate to " + name`); one string per sentence.
- `ui/text.plural()` is replaced by `ngettext`.
- Strings shown before the language is installed (splash, very early errors) stay English.
- Keyboard shortcuts in labels (`&File`) are part of the string; a translation chooses its own letter, and the
  shortcut-collision test (2.5) runs per language.
- Width: German runs about 30 % longer than English. Fixed-width buttons, segmented controls and compact topbar
  labels are the likely places to break; the German screenshots (step 4) check them.

### 2.4 German first

The first catalogue is German, translated with AI help using a UI glossary (`locale/glossary.md`: SlideMage's own
terms — Deck, Folie, Vorschau, Reveal-Schritt, ...) and reviewed by the owner. Terms that are names of SlideMage
features or LaTeX commands (`\slide`, Workdeck) stay as they are. Decided: German is the only UI language in the
first release; further languages are a `.po` file each, with no code change, added when someone can review them.

### 2.6 Plugins translate their own texts

Decided: in this task. The plugin API (`plugin_api.py`) gains translation for plugins, coordinated with the plugin
UI kit's author before it is merged:

- A plugin ships its catalogues in its own folder (`locale/<lang>/LC_MESSAGES/<plugin id>.mo`) and gets its own
  gettext domain, so its strings never collide with SlideMage's or another plugin's.
- The host gives each plugin `translator()` → an object with `_`, `ngettext`, `pgettext` bound to that domain and
  to the UI language SlideMage was started with. A plugin without catalogues gets the identity (English).
- The plugin UI kit's own widgets (buttons, fields) translate their built-in texts through SlideMage's domain, so
  a plugin built from the kit is in the UI language without doing anything.
- The manifest may declare `"languages": ["de"]`; the plugin manager shows it.
- `plugins/selftest.py` checks a plugin's catalogues the way 2.5 checks SlideMage's (placeholders, `.mo` matches
  `.po`).
- This is additive: an API-1 plugin keeps working, in English. It is an optional part of version 1, as is the
  content-language plan's plugin change (its 2.9), so `API_VERSION` stays 1.

### 2.5 Tests

- Extraction test: running the extractor over the package produces no string that the catalogue lacks
  (`msgmerge --check`-style), so a new English string without a German entry fails CI with its location.
- A lint test (AST) flags string literals passed to `setText`, `setToolTip`, `setWindowTitle`, `QMessageBox.*`,
  `Button(...)`, `Field(...)`, etc. that are not wrapped, with an allow-list for non-text arguments.
- A placeholder test: every translated `msgstr` has the same `{named}` placeholders as its `msgid`.
- Smoke test: start the main window and the Presenter with `de` installed; no English left in menus of a fixture
  (sampled by walking the widget tree for texts equal to their `msgid` where the catalogue has a different
  `msgstr`).
- The existing UI tests keep running in English (the default), so their string assertions need no change.

## 3. Steps

1. **Infrastructure** — `i18n.py`, `install()` in `ui/app.py`, `cli.py` and `presenter_app.py` before the first
   window, Qt's `qtbase` catalogue, the setting and its Settings row, `.mo` building in the release build, the
   extraction and placeholder tests (initially reporting, not failing).
2. **Wrap the strings**, by area, each its own commit and reviewable alone: (a) `ui/kit` and `ui/dialogs`,
   (b) `ui/workspace` (topbar, menus, panels, task cards), (c) `ui/pages` (Images, AI pages), (d) `ui/presentation`
   and the Presenter, (e) non-UI modules whose messages the UI shows (`compat_*` findings, `plugins/host.py`,
   `slide_add`, error messages raised for the user). Mechanical, so these can run in parallel sessions on a cheaper
   model, one area each, since the areas do not share files; `i18n.py` must be merged first.
3. **German catalogue** — generate, translate with the glossary, owner review in Poedit or as a table.
4. **Check the German UI** — screenshots of every page and sheet in German (the manual's screenshot tool can take
   them with the language set), fix truncation and layout; then switch the lint and extraction tests to failing.
5. **Plugins** — the plugin translator, the kit's own texts, manifest field, selftest checks (2.6); after step 1,
   independent of step 2.
6. **Docs** — manual slide on choosing the UI language, README, contributor notes on the string rules (also for
   plugin authors), CHANGELOG.

## 4. Open questions for the owner

All answered 2026-11-02: gettext; restart to switch; German only at first; plugins in this task; the manual later.

## 5. Later: a German manual

Noted at the owner's request (2026-11-02), not part of this task. The manual deck is English with a few German
slides. Once the content-language work (content-languages.md) is in, the manual can become a translation group
per slide (EN original, DE translation), and Help → Manual opens the deck in the UI language when the manual has
it, else in English. Needs: translating the manual slides, the manual's screenshots taken in German (the
screenshot tool with the UI language set), and a rule in the release checklist that both languages are updated
together.
