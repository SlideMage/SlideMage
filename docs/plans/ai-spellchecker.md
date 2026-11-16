# Plan: a spellchecker that only touches regular text

Status: **design, revision 3 (2026-11-16). The user decided S1 to S7 (section 8). Step 1 is built in v0.18.12
(`prose_spans.py`, its tests, the PROOFREAD guard); steps 2 to 5 are open.** Handover task `ai-spellchecker`.

History of the request:
* **2026-11-14:** the user asked for an AI-driven spellchecker, scoped carefully so that it only checks or touches
  regular text: no LaTeX commands, no URLs, and so on.
* **2026-11-16, revision 2:** check against dictionaries instead of a model, because that is faster and cheaper.
  pyspellchecker is used for every language but German, and spylls (Hunspell) for German. A language's dictionary
  is downloaded the first time that language is used in a project.
* **2026-11-16, revision 3:** **built into SlideMage, not a plugin.** A plugin would have needed three additions to
  the plugin API (registering a checker, a per-user folder, a download helper) and both libraries copied into it
  with rewritten imports. Built in, the libraries are ordinary dependencies, and the per-user folder, TLS trust and
  editor are already there. AI stays an optional later extra (section 7).

## 1. Where things stand (develop, v0.18.10)

* **An AI proofread task exists.** `ai/tasks.py` has `PROOFREAD` and `PROOFREAD_SELECTION`.
  * Both send the raw LaTeX source. The prompt (`_TEXT`, `_MARKUP`) is all that keeps the model on the text.
  * `check()` rejects an answer only when it changes a protected `%%` line (`ai/tools/edits.protected_problem`) or
    adds a lint error. A "fix" inside a URL, a `\label` or `\SMCode{…}` gets through.
  * The span guard below closes that gap too (S7).
* **Lexers already there** (Qt-free, tested):
  * `tex_source.py`: `COMMENT_RE`, `VERBATIM_ENV_RE`, `VERB_RE`, `IFFALSE_RE`, `masked_same_length()`,
    `blanked_verbatim()`, `braced_argument()`.
  * `alt_blocks.py`: `iter_tex_commands()` (a control-sequence tokenizer that skips comments, `\verb` and
    `\string`), `delimited_group_end()`, `extract_note_calls()`, `INCLUDEGRAPHICS_RE`.
  * `latex_lint.py`: `_mask_comments_and_verbatim()`, `_citations()`.
  * `protected_regions.protected_spans()` and `slide_source.title_span()`.
  * `latex_help._COMMANDS`: the catalogue of SlideMage's public commands, kept in step with `SlideMage_base.tex`
    by a test.
* **Language:**
  * `slide_language.own_language()` gives a slide's language; EN and DE partner slides are separate files.
  * One file can hold several languages: `\multilingualtext{EN}{DE}` or `\multilingualtext*{EN={…}, …}`.
* **Infrastructure to reuse:**
  * `tls_trust.py`: the operating system's certificate store for HTTPS.
  * The updater's download pattern (`plugins/installer.py`: size caps, SHA-256 check before anything is written).
  * The app's per-user config folder.
  * The editor's `ExtraSelections` and the UTF-16 helpers (`latex_edit.utf16_len/utf16_units`).
  * The hover tooltip of the LaTeX help.
  * The background workers (`ui/background.py`).

## 2. How it fits together

```
slide source ──prose_spans()──▶ spans ──words()──▶ unique words per language ──Checker──▶ unknown words
     ▲                                                                                       │
     └──────────── apply_span_edits() ◀── user picks a suggestion ◀── underline in editor ◀───┘
```

* **The safety rules** live in `prose_spans.py`, tested once: which characters may be checked, and how a correction
  is written.
* **The checkers** never see LaTeX. They get words and a language, and answer which words are unknown and, when
  asked, suggestions for one word.
* **A small internal `Checker` protocol** keeps the dictionary checker and a later AI checker interchangeable. If
  someone ever needs a plugin hook, it can be opened on top of this.

## 3. Prose spans (`prose_spans.py`, Qt-free)

**Allow-list, deny by default.** Text is checked only if a rule below names it. Anything the extractor does not
understand is left out, so an unclear case costs a missed typo, never a broken slide.

* **Prose:**
  * body text, `\item` text and table cells (between `&` and `\\`);
  * the frame title and block titles;
  * `\footnote`, `\caption` and `\note`;
  * the text argument of the commands in the table `PROSE_ARGS`: `\emph`, `\textbf`, `\textit`, `\underline`,
    `\alert`, `\structure`, `\textcolor{…}{TEXT}`, `\href{…}{TEXT}`, and SlideMage's own text-taking commands. A
    test fails if a command in `latex_help._COMMANDS` is in neither `PROSE_ARGS` nor `NO_PROSE`.
* **Never prose:**
  * command names, and the arguments of every command not in `PROSE_ARGS`: `\label`, `\ref`, the `\cite` family,
    `\includegraphics`, `\input`, `\url`, the URL of `\href`, colour and theme names, `\SMCode`, `\SMCmd` and
    unknown project macros;
  * optional arguments `[…]`, overlay specifications `<…>` and environment names;
  * math (`$…$`, `\(…\)`, `\[…\]`, `equation`/`align`/`tikzpicture` bodies), verbatim (`verbatim`,
    `lstlisting`, `minted`, `\verb`) and `\iffalse…\fi`;
  * comments, the protected `%%` header and `\setSlideVersion`;
  * inside prose: URLs, e-mail addresses and file-like tokens (`name.ext`);
  * **words with TeX inside** (`Gr\"o\ss e`, `\-`; S4): left out entirely, because LuaLaTeX takes umlauts
    directly.
* **The character invariant.** A span never contains any of `\ { } $ % & # ^ _ ~ [ ]`. Each of them ends a span.
  An edit that stays inside one span and whose replacement has none of them cannot touch a command, a group, math
  or a comment.

```python
@dataclass(frozen=True)
class Span:
    start: int; end: int     # str offsets into the file text
    kind: str                # "title" | "body" | "item" | "cell" | "footnote" | "note" | "caption" | "arg"
    language: str            # the file's language, or the key of a \multilingualtext argument

def prose_spans(text: str, language: str = "") -> list[Span]    # language: the file's own
def words(text: str, spans: list[Span]) -> list[Word]           # Word: start, end, text, language
def apply_span_edits(text: str, edits: list[SpanEdit], language: str = "") -> tuple[str, list[str]]
def outside_prose(old: str, new: str) -> str | None             # the PROOFREAD guard (S7)
```

As built (v0.18.12), `apply_span_edits` computes the spans of the current text itself. Each `SpanEdit` carries
`before`, the text it expects at its offsets.

**How `prose_spans` works:**

1. Blank what is never prose, keeping offsets: `tex_source`, `protected_spans`, math, `IFFALSE_RE`.
2. Walk the tokens with `iter_tex_commands`. A `PROSE_ARGS` command opens its text argument (`braced_argument`,
   with `delimited_group_end` stepping over `<…>` and `[…]`); every other command's arguments are skipped.
3. Cut at special characters, URLs, e-mail addresses and file tokens.
4. Trim each span and drop those with no letter.

**`words()`** takes letters, including umlauts and ß, with an inner apostrophe. A hyphen splits a word. Tokens with
digits are dropped, and so are all-capital abbreviations of up to 5 letters.

**`apply_span_edits()`** is the only write path. It accepts an edit only if all of these hold:
* the edit lies inside one span;
* the span still reads as it did when it was checked;
* the replacement has no special character, URL or line break.

**Developer view:** `python -m slidemage.prose_spans FILE...` prints the source with the spans marked between ⟦ and
⟧, so the scope can be checked on real slides before any checker exists. It is a module entry point, not a
`slidemage` subcommand, because the app's command line starts the window.

**Learned while building step 1.** Besides the rules above, these are also never prose:
* TeX definitions and boxes (`\def…{…}`, `\vbox to 0pt{…}`), up to their brace group;
* `\let` lines;
* register assignments (`\prevdepth=0pt`).

An insertion at the very start of a span is refused when the character before it is a letter, so that "\ldots."
cannot become `\ldotsx.`. Across the 198 slide files of `example/` and the fixtures there are 2371 spans and about
13,900 words.

## 4. Checking and the editor

```python
class Checker(Protocol):                   # spelling/checker.py
    name: str
    def languages(self) -> set[str]: ...   # what it can check now or after a download
    def prepare(self, language: str, report) -> bool: ...   # worker: download/load; False = not available
    def unknown(self, language: str, words: list[str]) -> set[str]: ...    # worker, fast
    def suggest(self, language: str, word: str) -> list[str]: ...          # worker, may be slow
```

* **When it checks (S1 a):** as you type, after a pause of about 400 ms, on a worker. Only the unique words of the
  open file go to the checker, and results are cached per `(checker, language, word)` for the session. A slide of
  100 words is one call.
* **First use of a language:** `prepare()` runs once, with progress in the status line, e.g. "Downloading the German
  dictionary (4 MB)…". Without a network, the status says so and offers Retry; nothing is underlined meanwhile.
* **Underlines:** a red wavy underline (`ExtraSelection`) on each unknown word.
* **Fixing a word:** right-click or Ctrl+. on an underlined word shows the suggestions (from `suggest()`, on a
  worker), **Ignore** (for the session) and **Add to word list**. Picking a suggestion goes through
  `apply_span_edits` as one undo step.
* **Word list (S2 a):** one plain file per project and language, `spelling-words-<lang>.txt` in the project folder,
  one word per line, so co-authors share it through the project. Its words are never sent and never underlined.
* **Switching it off:** a toggle in the Source view's toolbar ("Check spelling"), remembered per user.
* **Unsupported language:** if neither library covers a project language, that text is not checked, and the toggle
  says so.

## 5. The dictionary checker (`spelling/`, built in)

* **Dependencies:** `pyspellchecker==0.9.1` (MIT) and `spylls==0.1.7` (MPL-2.0) go into `pyproject.toml`. Both are
  pure Python with no dependencies of their own, and both licences fit GPL-3. The PyInstaller build bundles their
  code but **not** pyspellchecker's word lists: those are downloaded like the German dictionary, so the app does
  not grow by a list for every language (step 2 measures the size). spylls has had no release since 2022. That is
  low risk for a pure-Python library, and it sits behind `Checker`, so it can be replaced.
* **Which library checks which language:**
  * **German:** spylls with a Hunspell dictionary. Hunspell handles compounds and word endings, which a word list
    cannot.
    * **Variant (S5 a):** a setting with de-AT, de-DE or de-CH, **default de-AT**.
  * **Every other language with a pyspellchecker list:** pyspellchecker. Its documentation lists en, es, fr, it,
    pt, nl, ru, ar, lv, eu and fa besides de; step 2 confirms this against 0.9.1. Its English list does not tell
    en-GB from en-US: both spellings pass.
* **Downloads (S6 b): straight from upstream, pinned.** `spelling/dictionaries.json` lists, per language, the URL,
  size and SHA-256 of each file:
  * the German Hunspell files (`de_AT_frami`, `de_DE_frami`, `de_CH_frami`) at a fixed commit of the LibreOffice
    dictionaries repository;
  * pyspellchecker's `resources/<lang>.json.gz` at the tag of the pinned version.

  A file is fetched with `tls_trust` and the installer's checks (size cap, hash checked before it is moved into
  place, nothing left behind on failure) into `<user config>/dictionaries/<lang>/`: once per user, not per project.
  If upstream ever moves a file, the hash or the URL fails, the status line says so, and a SlideMage release with a
  new pin fixes it. The frami files are under GPL-2.0, GPL-3.0 or OASIS terms; step 2 records the licence next to
  the pin.
* **Speed:**
  * Lookups are fast in both libraries.
  * Suggestions in spylls are pure Python and can take up to about a second for a German word, so they are computed
    only when an underlined word is opened.
  * Loading the German dictionary takes a few seconds, once per session, on a worker. If step 2 measures it too
    slow, the loaded dictionary is pickled next to the downloaded files.

## 6. Tests

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
   * `Gr\"o\ss e` → no word
2. **Corpus property:** over every slide in `example/` and the fixtures, no span holds a special character, and no
   span overlaps an independent oracle. The oracle is `VERBATIM_ENV_RE`, `VERB_RE`, `INCLUDEGRAPHICS_RE`,
   `latex_lint._citations`, a `\label`/`\ref` regex, a URL regex, math delimiters, `protected_spans`, and every
   command token from `iter_tex_commands`.
3. **Edits never leak:**
   * Seeded random edits go through `apply_span_edits`. For every accepted one, everything outside the edited
     ranges is byte-identical; for every rejected one, the whole text is identical.
   * Replacing every span's letters leaves `latex_lint.lint_text` with no new error, and the spans in the same
     places.
4. **Catalogue sync:** every command in `latex_help._COMMANDS` is in `PROSE_ARGS` or `NO_PROSE`.
5. **Checker:**
   * known and unknown words in English and German, including compounds ("Nachfrageüberhang") and inflections, with
     small test dictionaries in `tests/fixtures/`, so no download is needed;
   * the download with a fake server: a wrong hash is refused and leaves nothing behind, and a retry after an
     interruption works.
6. **Editor, offscreen, with a fake checker** (a fixed word set):
   * underlines land exactly on the unknown words, also after non-ASCII text (UTF-16 offsets);
   * Accept is one undo step and leaves the text outside the word unchanged;
   * a word on the word list is not underlined.

## 7. AI as an optional extra (later)

The same spans can go to a model for what a dictionary cannot catch: real-word errors ("form/from", "das/dass") and
grammar. This would be a second `Checker`, or a "Check with AI" button on a slide or deck.

* It sends span texts only, never the LaTeX source.
* It answers with per-span fixes (`{"span", "before", "after"}`), which go through `apply_span_edits`.
* It uses the active AI route.

## 8. Decisions (the user, 2026-11-16)

The user answered against the numbering of revision 2. Revision 3 keeps that numbering.

* **S1 a:** check as you type (debounced), with underlines in the editor.
* **S2 a:** the word list is one file per project and language, `spelling-words-<lang>.txt`, shared with
  co-authors.
* **S3 a:** alt texts are checked too, in the Images panel, in a later step (step 4).
* **S4 a:** words with TeX inside are left out.
* **S5 a:** the German variant is a setting (de-AT, de-DE, de-CH), default de-AT.
* **S6 b:** dictionaries come straight from upstream (the LibreOffice dictionaries repository, pyspellchecker's
  GitHub), pinned by SHA-256.
* **S7 a:** once step 1 lands, `PROOFREAD`'s `check()` also rejects edits outside prose spans (step 1 includes
  this).

## 9. Steps (each one a small PR with its version and CHANGELOG entry)

1. **Built in v0.18.12.** `prose_spans.py`: spans, words, `apply_span_edits` and `outside_prose`; the tables
   `PROSE_COMMANDS`, `NO_PROSE`, `ENVIRONMENTS` and `SKIPPED_BODIES`. Also tests 1 to 4 (`tests/test_prose_spans.py`),
   `python -m slidemage.prose_spans`, and the S7 guard (`Task.prose_only` on `PROOFREAD` and
   `PROOFREAD_SELECTION`). No checker, no new UI.
2. **The dictionary checker** (`spelling/`: `Checker`, pyspellchecker and spylls, `dictionaries.json`, download,
   the German variant setting), the build change that leaves pyspellchecker's lists out, and test 5.
3. **The editor:** underlines as you type, the suggestion menu, Ignore, the word list, the toolbar toggle, and
   test 6.
4. **More places:** a deck-wide spelling list (every unknown word of a deck, grouped, with "Add to word list" for
   many at once), and alt texts in the Images panel (S3).
5. **Optional:** the AI checker (section 7).
