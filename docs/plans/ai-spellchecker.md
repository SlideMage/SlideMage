# Plan: an AI spellchecker that only touches regular text

Status: **design for review (2026-11-16), nothing built.** Handover task `ai-spellchecker`. The decisions for the
user are S1 to S6 (section 7).

Request (user, 2026-11-14): add an AI-driven spellchecker. It must be scoped carefully so that it only checks or
touches regular text: no LaTeX commands, no URLs, and so on.

## 1. Where things stand (develop, v0.18.10)

* **A proofread task already exists.** `ai/tasks.py` has `PROOFREAD` (whole slide) and `PROOFREAD_SELECTION`. Both
  send the **raw LaTeX source**. The scope is only a sentence in the prompt (`_TEXT`, `_MARKUP`: "never change
  LaTeX commands … citation keys, file names, URLs …"). The model answers with an edit list (`before`/`after`), which
  `check()` applies. `check()` rejects an answer only when it changes a protected `%%` line
  (`ai/tools/edits.protected_problem`) or adds a lint error. Nothing stops a "spelling fix" inside a URL, a `\label`,
  a colour name or `\SMCode{…}`, because none of those changes adds a lint error. **This gap is what the spellchecker
  closes.**
* **Lexers that are already there** (all Qt-free, all tested):
  * `tex_source.py`: `COMMENT_RE`, `VERBATIM_ENV_RE`, `VERB_RE`, `IFFALSE_RE`, `masked_same_length()`,
    `blanked_verbatim()` and `braced_argument()`. They blank text but keep offsets.
  * `alt_blocks.py`: `iter_tex_commands()`, a real control-sequence tokenizer that skips comments, `\verb` and
    `\string`. Also `delimited_group_end()` for `<…>`/`[…]`, `extract_note_calls(mask=True)` and
    `INCLUDEGRAPHICS_RE`.
  * `latex_lint.py`: `_mask_comments_and_verbatim()`, `_citations()`, and a brace and environment stack in `_Lexer`.
  * `protected_regions.protected_spans()`: the `%%` header and `\setSlideVersion`.
  * `slide_source.title_span()`: the frame title.
  * `latex_help._COMMANDS` / `_ENVIRONMENTS`: a catalogue of SlideMage's public commands, kept in step with
    `SlideMage_base.tex` by a test (hover help, v0.16.51).
* **Language:** `slide_language.own_language(id_slug, codes)` gives a slide's language (EN/DE partners are separate
  files). Text inside the same file in several languages uses `\multilingualtext{EN}{DE}` or the keyed
  `\multilingualtext*{EN={…}, DE={…}}` (`latex_edit.insert_multilingual*`).
* **Alt texts** are not in the slide source. They live in the per-image JSON store (`alt_images.ImageText`, one
  field per language).
* **UI patterns to reuse:**
  * `ui/workspace/ai_fix.py`: inline issue rows above the editor. Apply happens only if the line still reads as
    the model saw it (`SyntaxIssue.fix_is_safe()`), with one undo step per fix.
  * The editor's `ExtraSelections` (`source_editor.py`, brace matching) and its UTF-16 helpers
    (`latex_edit.utf16_len/utf16_units`).
  * The AI routes (`ai_profile`, `resolver`, `ui/ai_models.picked_route`), JSON answers
    (`ai/providers.parse_json_object`) and the deck batch runner (`task_bubbles.deck_bubbles`).

## 2. What counts as prose

**Allow-list, deny by default.** A character is prose only if a rule below says so. Anything the extractor does not
understand is left out. The cost of that is a missed typo, never a broken slide.

Prose (checked):
* Body text at the top level of the frame, list items (`\item …`) and table cells (between `&` and `\\`).
* The frame title, block titles (`\begin{block}{Title}`), `\footnote{…}`, `\caption{…}` and `\note{…}`.
* The text argument of a fixed table of commands, `PROSE_ARGS`, that names which argument is text:
  * standard commands: `\emph`, `\textbf`, `\textit`, `\underline`, `\alert`, `\structure`, `\textcolor{…}{TEXT}`,
    `\href{…}{TEXT}`;
  * SlideMage's public commands that take text, listed explicitly. A test fails when a command in
    `latex_help._COMMANDS` is neither in `PROSE_ARGS` nor in `NO_PROSE`, so a new macro has to be classified
    before it ships.
* Alt texts (S4): each field is one span, and its language is that field's language.

Never prose (never checked or changed):
* Command names, and the arguments of any command not in `PROSE_ARGS`. That covers `\label`, `\ref`, the `\cite`
  family, `\includegraphics`, `\input`, `\url`, the first argument of `\href`, colour and theme names, `\SMCode`,
  `\SMCmd` and unknown project macros.
* Optional arguments `[…]`, overlay specifications `<…>` and environment names.
* Math: `$…$`, `$$…$$`, `\(…\)`, `\[…\]`, and the `equation`, `align`, `gather` and `tikzpicture` bodies.
* Verbatim: `verbatim`, `lstlisting`, `minted`, `\verb`, and `\iffalse…\fi`.
* Comments, the protected `%%` header and `\setSlideVersion`.
* **Inside** a prose run: bare URLs (`https?://…`, `www.…`), e-mail addresses and file-like tokens (`name.ext`).
  They split the run and are never part of a span.

**The character invariant.** A span never contains any of `\ { } $ % & # ^ _ ~ [ ]`. Every TeX special character
ends a span (so `Gr\"o\ss e` is three small spans, or none; see S5). That makes the safety argument simple: an edit
that stays inside one span and whose replacement contains none of those characters cannot create, remove or change
a command, a group, math or a comment.

## 3. How the scope is computed: `prose_spans.py` (new, Qt-free, no AI)

```python
@dataclass(frozen=True)
class Span:
    start: int; end: int          # str offsets into the file text (the editor converts to UTF-16)
    kind: str                     # "title" | "body" | "item" | "cell" | "footnote" | "note" | "caption" | "arg"
    language: str                 # own_language() of the file, or the key of a \multilingualtext argument

def prose_spans(text: str, codes: tuple[str, ...], file_language: str) -> list[Span]
def apply_span_edits(text: str, spans: list[Span], edits: list[SpanEdit]) -> tuple[str, list[str]]
```

* **Steps:**
  1. Blank everything that is never prose, keeping offsets. This uses `tex_source.masked_same_length` and
     `blanked_verbatim`, `protected_regions.protected_spans`, plus math and `IFFALSE_RE`.
  2. Walk the tokens with `alt_blocks.iter_tex_commands`. A command in `PROSE_ARGS` opens its text argument as a
     prose region (via `tex_source.braced_argument`, with `delimited_group_end` stepping over `<…>`/`[…]`). Any
     other command's arguments are skipped whole.
  3. Cut the remaining top-level and prose-argument text at every special character, URL, e-mail address or file
     token.
  4. Trim whitespace and drop spans with no letters.
* **`apply_span_edits`** accepts an edit only if all of these hold:
  * its range lies inside one span;
  * the span still reads as it did when it was sent;
  * `after` contains no special character, no URL and no line break;
  * edits do not overlap.

  Anything else is rejected with a message, and the text is left unchanged. This is the only way a spellcheck
  answer gets written.
* **A developer view** (step 1) helps the user check the scope on real slides before any AI runs: one of
  * `slidemage spans <file>`, which prints the source with spans marked; or
  * a hidden "Show prose spans" toggle in the editor that underlines them.

## 4. Tests (step 1, before any AI)

`tests/test_prose_spans.py`:

1. **Golden cases** (a table of snippets and their expected span texts), for example:
   * `\href{https://x.org}{the site}` → `["the site"]`
   * `see \cite{smith2020}.` → `["see"]` (the `.` alone has no letters)
   * `$a+b$ is small` → `["is small"]`
   * `\SMCode{teh}` → `[]`
   * `\textcolor{red}{word}` → `["word"]`
   * `\begin{block}{Titel}` → `["Titel"]`
   * `\cornerfigure[width=.3]{img.png}` → `[]`
   * `% teh` → `[]`
   * `Visit www.uni-graz.at today` → `["Visit", "today"]`
   * `\multilingualtext{Hello}{Hallo}` → `[("Hello","EN"), ("Hallo","DE")]`
2. **Corpus property, over every slide in `example/` and the test fixtures:**
   * no span contains a special character;
   * no span overlaps a match of an independent oracle: the regexes already in the app (`VERBATIM_ENV_RE`,
     `VERB_RE`, `INCLUDEGRAPHICS_RE`, `latex_lint._citations`, a `\label`/`\ref` regex, a URL regex, math
     delimiters, `protected_spans`) or any command token from `iter_tex_commands`.
3. **Edits never leak outside a span:**
   * Seeded random edits (in-span, straddling, outside, with forbidden characters) go through `apply_span_edits`.
     For every accepted result, the text outside the edited ranges is byte-identical to the original. For every
     rejected one, the whole text is identical.
   * On the corpus, replacing every span's letters with other letters leaves `latex_lint.lint_text` with no new
     errors, and `prose_spans` of the result finds the same number of spans in the same places.
4. **Catalogue sync:** every public command in `latex_help._COMMANDS` is classified in `PROSE_ARGS` or `NO_PROSE`.

## 5. The AI part

* **A new task `SPELLCHECK` in `ai/tasks.py`.**
  * The request carries the **span texts only**, numbered, one language per request, never the LaTeX source:
    `{"spans": [{"id": 3, "text": "Teh market clears"}], "language": "EN"}`.
  * The answer schema is `{"fixes": [{"span": 3, "before": "Teh", "after": "The", "kind": "spelling"}]}`. `before`
    must occur exactly once in its span; this reuses the `_once` rule of `_apply_edits`. Each fix becomes a
    `SpanEdit`, which goes through `apply_span_edits`, so a whole-file rewrite is impossible by construction.
  * A refused fix gets one `repair_request` round, as for the other tasks.
* **Model:** the active route for "Fixes, notes, transcripts": Local (Ollama), API, or Claude Code,
  run through `ai/provider_tasks.run_task` like the other tasks, with the existing cloud-consent prompt. The prompt says: spelling, plus obvious typos
  and capitalization; keep the variant of the language (en-GB/en-US, de-AT/de-DE) the text already uses; leave
  technical terms, names and words in the personal word list alone.
* **Language:** every span carries its language. EN and DE partner slides are separate files, each checked only in
  its own language; a `\multilingualtext` argument is checked in its key's language. Spans of two languages never
  share a request.
* **Cost:** results are cached by `(hash of span text, language, word-list version)` in `.slidemage/spellcheck.json`.
  A re-check sends only spans that changed.

## 6. UX

* **Where it runs (S1):**
  * **Single slide:** a "Check spelling" entry in the assistant header (`task_bubbles`) and the Source view. It runs
    on demand on the current buffer. Not as-you-type: that would mean one model call per keystroke pause.
  * **Whole deck:** the same task as a deck bubble, collected into one review list.
* **Showing suggestions:** a wavy underline (`ExtraSelections`) on each word with a suggestion, and a row per
  suggestion in an `ai_fix.py`-style panel above the editor: "Teh → The", with **Accept**, **Ignore** and **Add to
  word list**.
  * Accept edits the buffer as one undo step, only if the span still reads as it was sent (the `fix_is_safe`
    pattern). If it does not, the row says the text changed and offers Check again.
  * Accept all applies all the fixes of one slide as one undo step.
* **Personal word list (S3):** words added there are left out of requests and filtered out of answers.

## 7. Decisions for the user

* **S1 Where:** (a) single slide in the editor first, then a deck-wide review list (recommended); (b) only a
  deck-wide review page; (c) editor only.
* **S2 What it fixes:** (a) spelling and obvious typos only (recommended; that is what "spellchecker" says);
  (b) also grammar and punctuation, like the current PROOFREAD.
* **S3 Word list:** (a) one per project and language, a plain `spelling-words-<LANG>.txt` in the project, so
  co-authors share it (recommended); (b) per user in the app settings; (c) both.
* **S4 Alt texts:** (a) check them too, from the Images panel, in a later step (recommended); (b) slides only.
* **S5 Words with TeX inside** (`Gr\"o\ss e`, `\-` hyphenation hints): (a) leave them out entirely (recommended;
  LuaLaTeX lets authors write umlauts directly); (b) handle a small list of accent and hyphenation commands as
  part of the word.
* **S6 The existing PROOFREAD:** (a) once step 1 lands, make its `check()` also reject edits outside prose spans,
  so it gets the same guarantee (recommended); (b) leave it as is.

## 8. Steps (each one a small PR)

1. `prose_spans.py`, `PROSE_ARGS`/`NO_PROSE` and the tests of section 4, plus the developer span view. No AI, no
   user-facing UI.
2. The `SPELLCHECK` task, request and answer validation through `apply_span_edits`, the cache, and tests with
   canned answers (as `tests/test_ai_tasks.py` does).
3. The single-slide editor UI: underlines, suggestion rows, Accept, Ignore, Accept all.
4. The personal word list.
5. The deck-wide run and review list.
6. Optional: the S6 guard on PROOFREAD; alt texts (S4).
