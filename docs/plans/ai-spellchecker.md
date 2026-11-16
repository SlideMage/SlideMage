# Plan: a spellchecker that only touches regular text

Status: **design for review, revision 2 (2026-11-16), nothing built.** Handover task `ai-spellchecker`. The
decisions for the user are S1 to S7 (section 8).

* **Request (user, 2026-11-14):** add an AI-driven spellchecker. It must be scoped carefully so that it only checks
  or touches regular text: no LaTeX commands, no URLs, and so on.
* **Revision 2 (user, 2026-11-16):** check against dictionaries instead of a model: faster and cheaper.
  * Use **pyspellchecker** for every language but German, and **spylls** (Hunspell) for German.
  * Make it a **plugin** that downloads a language's dictionary the first time that language is used in a project.
  * AI stays as an optional later extra (section 7).

## 1. Where things stand (develop, v0.18.10)

* **An AI proofread task exists.** `ai/tasks.py` has `PROOFREAD` and `PROOFREAD_SELECTION`.
  * Both send the raw LaTeX source and keep the model on the text only through the prompt (`_TEXT`, `_MARKUP`).
  * `check()` rejects an answer only when it changes a protected `%%` line (`ai/tools/edits.protected_problem`) or
    adds a lint error. A "fix" inside a URL, a `\label` or `\SMCode{…}` gets through.
  * The span extractor below closes that gap too (S7).
* **Lexers already there** (Qt-free, tested):
  * `tex_source.py`: `COMMENT_RE`, `VERBATIM_ENV_RE`, `VERB_RE`, `IFFALSE_RE`, `masked_same_length()`,
    `blanked_verbatim()` and `braced_argument()`.
  * `alt_blocks.py`: `iter_tex_commands()` (a control-sequence tokenizer that skips comments, `\verb` and
    `\string`), `delimited_group_end()`, `extract_note_calls()` and `INCLUDEGRAPHICS_RE`.
  * `latex_lint.py`: `_mask_comments_and_verbatim()` and `_citations()`.
  * `protected_regions.protected_spans()` and `slide_source.title_span()`.
  * `latex_help._COMMANDS`: the catalogue of SlideMage's public commands, kept in step with `SlideMage_base.tex`
    by a test.
* **Language:**
  * `slide_language.own_language()` gives a slide's language; EN and DE partner slides are separate files.
  * Text in several languages inside one file uses `\multilingualtext{EN}{DE}` or `\multilingualtext*{EN={…}, …}`.
  * `Host.project_languages()` gives a plugin the project's languages.
* **Plugins** (`plugins/`, `plugin_api.py`, the build script of each plugin repository):
  * **Code:** a plugin is a zip of Python source. No compiled files are allowed. It may import only the standard
    library, PySide6 and its own package, and it is loaded from its folder, not through `sys.path`.
  * **Limits:** a member may be at most 20 MB, and the whole plugin at most 50 MB.
  * **Background work and messages:** `activate()` must not use the network. Background work goes through
    `run_in_background(_with_progress)`, and `show_message` reports to the user.
  * **Storage:** `cache_dir()` is per plugin and **per project**. There is no per-user data folder yet.
  * **No editor hook:** the plugin API has no way to underline text in the editor, so a spellcheck plugin needs a
    small API addition (section 4).
* **UI to reuse:**
  * the editor's `ExtraSelections` (`source_editor.py`);
  * its UTF-16 helpers (`latex_edit.utf16_len/utf16_units`);
  * the hover tooltip machinery of the LaTeX help;
  * the issue rows of `ui/workspace/ai_fix.py`.

## 2. The split: SlideMage decides *where*, the plugin decides *what is a word*

All the safety lives in SlideMage, where it is tested once: which characters may be checked, and how a correction is
written. The plugin never sees the LaTeX source. It gets words and a language, and answers which words are unknown
and, when asked, suggestions for one word. That keeps the plugin small and replaceable; an AI checker later is a
second checker behind the same interface.

```
slide source ──prose_spans()──▶ spans ──words()──▶ unique words per language ──plugin──▶ unknown words
     ▲                                                                                     │
     └──────────── apply_span_edits() ◀── user picks a suggestion ◀── underline in editor ◀─┘
```

## 3. Prose spans (SlideMage core, `prose_spans.py`, Qt-free)

**What counts as prose: an allow-list, deny by default.** Text is checked only if a rule below names it. Anything
the extractor does not understand is left out, so the cost of an unclear case is a missed typo, never a broken
slide.

* **Prose:**
  * body text, `\item` text and table cells (between `&` and `\\`);
  * the frame title and block titles;
  * `\footnote`, `\caption` and `\note`;
  * the text argument of the commands in the table `PROSE_ARGS`: `\emph`, `\textbf`, `\textit`, `\underline`,
    `\alert`, `\structure`, `\textcolor{…}{TEXT}`, `\href{…}{TEXT}`, and SlideMage's own text-taking commands. A
    test fails if a command in `latex_help._COMMANDS` is in neither `PROSE_ARGS` nor `NO_PROSE`.
* **Never prose:**
  * command names and the arguments of every command not in `PROSE_ARGS`: `\label`, `\ref`, the `\cite` family,
    `\includegraphics`, `\input`, `\url`, `\href`'s URL, colour and theme names, `\SMCode`, `\SMCmd`, unknown
    project macros;
  * optional arguments `[…]`, overlay specifications `<…>` and environment names;
  * math (`$…$`, `\(…\)`, `\[…\]`, `equation`/`align`/`tikzpicture` bodies), verbatim (`verbatim`,
    `lstlisting`, `minted`, `\verb`) and `\iffalse…\fi`;
  * comments, the protected `%%` header and `\setSlideVersion`;
  * inside prose: URLs, e-mail addresses and file-like tokens (`name.ext`).
* **The character invariant.** A span never contains any of `\ { } $ % & # ^ _ ~ [ ]`. Each of them ends a span.
  An edit that stays inside one span and whose replacement has none of them cannot touch a command, a group, math
  or a comment.

**API:**

```python
@dataclass(frozen=True)
class Span:
    start: int; end: int     # str offsets into the file text
    kind: str                # "title" | "body" | "item" | "cell" | "footnote" | "note" | "caption" | "arg"
    language: str            # the file's language, or the key of a \multilingualtext argument

def prose_spans(text: str, codes: tuple[str, ...], file_language: str) -> list[Span]
def words(text: str, spans: list[Span]) -> list[Word]   # Word: start, end, text, language
def apply_span_edits(text: str, spans: list[Span], edits: list[SpanEdit]) -> tuple[str, list[str]]
```

**How `prose_spans` works:**

1. Blank whatever is never prose, keeping offsets. This uses `tex_source`, `protected_spans`, and math and
   `IFFALSE_RE`.
2. Walk the tokens with `iter_tex_commands`. A `PROSE_ARGS` command opens its text argument
   (`braced_argument`, with `delimited_group_end` stepping over `<…>` and `[…]`); every other command's arguments
   are skipped.
3. Cut at the special characters, URLs, e-mail addresses and file tokens.
4. Trim each span and drop those with no letter.

**Words, edits and the developer view:**

* `words()` splits spans into words: letters, including umlauts and ß, with an inner apostrophe; a hyphen splits.
  It drops tokens with digits and all-capital abbreviations of up to 5 letters.
* `apply_span_edits()` is the only write path. It accepts an edit only if all of these hold:
  * it lies inside one span;
  * the span still reads as it did when it was checked;
  * the replacement has no special character, URL or line break.
* A developer view lets the scope be checked on real slides before any checker exists:
  `slidemage spans <file>` prints the source with the spans marked.

## 4. The checker interface (SlideMage core, plugin API addition)

These additions keep API version 1. They need a SlideMage version that has them (`requires_slidemage`).

```python
class SpellChecker(Protocol):
    name: str                                            # "Dictionaries", later "AI"
    def languages(self) -> set[str]: ...                 # codes it can check now or after a download
    def prepare(self, language: str, report) -> bool: ...  # on a worker: download/load; False = not available
    def unknown(self, language: str, words: list[str]) -> set[str]: ...   # on a worker, fast
    def suggest(self, language: str, word: str) -> list[str]: ...         # on a worker, may be slow

Host.add_spell_checker(checker: SpellChecker) -> None    # activate() only
Host.data_dir() -> Path    # new: the plugin's per-user folder, kept across projects (dictionaries live here)
Host.download(url: str, sha256: str, dest: Path, report) -> None   # new: worker-only, SlideMage's TLS trust
                                                                   # (tls_trust.py), size cap, hash check
```

**What SlideMage does with a checker:**

* **When it checks:** after typing pauses (debounced, about 400 ms), on a worker. Only the unique words of the
  open file are sent, and results are cached per `(checker, language, word)` for the session. A slide of 100
  words is one call.
* **First use of a language:** if the language has no dictionary yet, SlideMage calls `prepare()` once, with
  progress in the status line, e.g. "Downloading the German dictionary (4 MB)…". Without a network, the status
  says so and offers Retry; nothing is underlined.
* **Underlines:** a red wavy underline (`ExtraSelection`) on each unknown word.
* **Fixing a word:** right-click or Ctrl+. on an underlined word shows the suggestions (from `suggest()`, on a
  worker), **Ignore**, and **Add to word list**. Picking a suggestion goes through `apply_span_edits` as one undo
  step.
* **Word list (S2):** words on it are never sent and never underlined.
* **Switching it off:** a toggle in the Source view's toolbar ("Check spelling"), remembered per user.

## 5. The plugin `slidemage-plugin-spellcheck` (new repository, built from `slidemage-plugin-template`)

* **Libraries, vendored as source** inside the package (the plugin rules allow only its own package):
  * `spellcheck/_vendor/spellchecker/` (pyspellchecker 0.9.1, MIT);
  * `spellcheck/_vendor/spylls/` (spylls 0.1.7, MPL-2.0).

  Both are pure Python with no dependencies of their own. The build script copies them from pinned wheels and
  rewrites their absolute imports to the vendored package path; a test imports each one through the plugin
  loader. Their licence files ship in `_vendor/`. MPL-2.0 and MIT both fit a GPL-3 plugin.
* **Which library checks which language:**
  * **German:** spylls with a Hunspell dictionary (`de_DE`, `de_AT` or `de_CH`; S5). Hunspell handles
    compounds and word endings, which a word list cannot.
  * **Every other language pyspellchecker has a list for** (its documentation lists en, es, fr, it, pt, nl, ru,
    ar, lv, eu, fa besides de; to be confirmed against 0.9.1 in step 3): pyspellchecker. Its list does not tell en-GB from en-US; both spellings pass.
  * **A project language neither covers:** that text is not checked, and the toolbar toggle says so.
* **Dictionaries are downloaded on first use, not shipped.**
  * A `dictionaries.json` inside the plugin lists, per language, the URL, size and SHA-256 of each file (S6).
  * `prepare()` downloads the missing files through `Host.download` into `data_dir()/dictionaries/<lang>/`, checks
    the hash, then loads them.
  * A dictionary is downloaded once per user, not once per project.
* **Speed:**
  * Lookups are fast in both libraries.
  * Suggestions are slow in pure-Python spylls, up to a second per German word, so they are computed only when
    the user opens an underlined word.
  * Loading the German dictionary in spylls takes a few seconds. It happens once per session, on a worker. If it
    turns out too slow, the loaded dictionary is pickled into `data_dir()` (to be measured in step 3).
* **Tests** (with `fake_host.py`, as in the Ollama plugin):
  * known and unknown words in English and German, including compounds ("Nachfrageüberhang") and inflections;
  * the download path with a fake server: a wrong hash is refused and leaves nothing behind, and an interrupted
    download resumes cleanly;
  * the import rule: no imports outside the package.

## 6. Tests in SlideMage core

1. **Golden cases** for `prose_spans`:
   * `\href{https://x.org}{the site}` → `["the site"]`
   * `see \cite{smith2020}.` → `["see"]`
   * `$a+b$ is small` → `["is small"]`
   * `\SMCode{teh}` → `[]`
   * `\textcolor{red}{word}` → `["word"]`
   * `\begin{block}{Titel}` → `["Titel"]`
   * `\cornerfigure[width=.3]{img.png}` → `[]`
   * `% teh` → `[]`
   * `Visit www.uni-graz.at today` → `["Visit", "today"]`
   * `\multilingualtext{Hello}{Hallo}` → `[("Hello","EN"), ("Hallo","DE")]`
2. **Corpus property**, over every slide in `example/` and the fixtures:
   * no span holds a special character;
   * no span overlaps an independent oracle: `VERBATIM_ENV_RE`, `VERB_RE`, `INCLUDEGRAPHICS_RE`,
     `latex_lint._citations`, a `\label`/`\ref` regex, a URL regex, math delimiters, `protected_spans`, or any
     command token from `iter_tex_commands`.
3. **Edits never leak:**
   * Seeded random edits go through `apply_span_edits`. For every accepted one, everything outside the edited
     ranges is byte-identical; for every rejected one, the whole text is identical.
   * Replacing every span's letters leaves `latex_lint.lint_text` with no new error and the spans in the same
     places.
4. **Catalogue sync:** every command in `latex_help._COMMANDS` is in `PROSE_ARGS` or `NO_PROSE`.
5. **The editor with a fake checker** (a fixed word set), offscreen:
   * underlines land exactly on the unknown words, also after non-ASCII text (UTF-16 offsets);
   * Accept writes one undo step, and the text outside the word is unchanged;
   * a word on the word list is not underlined.

## 7. AI as an optional extra (later)

The same spans can go to a model for what a dictionary cannot catch: real-word errors ("form/from", "das/dass") and
grammar. This is a second checker, or a "Check with AI" button on a slide or deck.

* It sends the span texts only, never the LaTeX source.
* It answers with per-span fixes (`{"span", "before", "after"}`), which go through `apply_span_edits`.
* It uses the active AI route.

This was the core of revision 1; it moves to the last step.

## 8. Decisions for the user

* **S1 When it checks:**
  * (a) as you type, debounced, with underlines in the editor (recommended; a dictionary is cheap enough);
  * (b) only on a "Check spelling" click.
* **S2 Word list:**
  * (a) one per project and language, a plain `spelling-words-<lang>.txt` in the project, shared with co-authors
    (recommended);
  * (b) per user in the app settings;
  * (c) both.
* **S3 Alt texts:**
  * (a) check them too, in the Images panel, in a later step (recommended);
  * (b) slides only.
* **S4 Words with TeX inside** (`Gr\"o\ss e`, `\-`):
  * (a) leave them out (recommended; LuaLaTeX takes umlauts directly);
  * (b) treat a small list of accent and hyphenation commands as part of the word.
* **S5 German variant:**
  * (a) a plugin setting with de-AT, de-DE or de-CH, default de-AT;
  * (b) the same setting, default de-DE.
* **S6 Where dictionaries are downloaded from:**
  * (a) release assets of the plugin's own repository, pinned by SHA-256 (recommended: one host we control, files
    reviewed once, licences next to them);
  * (b) straight from upstream (pyspellchecker's GitHub, the LibreOffice dictionaries repository), pinned by
    SHA-256.

  The German Hunspell files (frami) are under GPL-2.0, GPL-3.0 or OASIS terms; to be confirmed when they are
  fetched.
* **S7 The existing PROOFREAD:**
  * (a) once step 1 lands, make its `check()` reject edits outside prose spans, so the AI proofread gets the same
    guarantee (recommended);
  * (b) leave it.

## 9. Steps (each one a small PR)

1. **Core:** `prose_spans.py` (spans, words, `apply_span_edits`), `PROSE_ARGS`/`NO_PROSE`, the tests of section 6
   (items 1 to 4), and `slidemage spans <file>`. No checker, no UI.
2. **Core:** the checker interface (`add_spell_checker`, `data_dir`, `download`), the editor underlines, the
   suggestion menu, the word list and the toolbar toggle. Tested with a fake checker (section 6, item 5). A
   SlideMage version and CHANGELOG entry.
3. **Plugin:** the new repository with vendored libraries, `dictionaries.json`, download on first use, the
   checker, its tests, and a catalogue entry.
4. **Core:** a deck-wide spelling list (every unknown word of the deck, grouped, with "Add to word list" for many at
   once).
5. **Optional:** the AI checker (section 7), the S7 guard on PROOFREAD, and alt texts (S3).
