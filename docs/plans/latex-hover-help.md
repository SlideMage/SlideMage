# Plan: help tooltips on LaTeX commands in the source editor

Status: **built in v0.16.51 (2026-11-16), steps 1 to 3.** The user chose H1 (a), H2 SlideMage's own commands,
H3 the whole help with the hovered key in bold, H4 a switch in Settings -> General (on by default). F1 already opens
the manual, so the keyboard path is **Shift+F1**. "Public" in the sync test (2.3) is what the manual's Quick
Reference slides (1uw, 1d7) name: SlideMage_base.tex defines about 180 commands, most of them internal. Step 4
(standard LaTeX/beamer commands, help from theme packages) is not built.

Request (user, 2026-11-16): hovering over LaTeX code in the editor shows a tooltip. Hovering over `\cornerfigure`,
for example, explains how to use it and what its options are.

## 1. Where things stand (develop, v0.16.41)

* **The editor** is `LatexPlainTextEdit` (`ui/workspace/source_editor.py`), a `QPlainTextEdit` behind the
  `SourceEditor` protocol. It has no tooltips. It already overrides `event()` for Tab and Shift+Tab. The text logic
  lives in Qt-free `latex_edit.py`, which has unit tests. Qt positions count UTF-16 units; `utf16_units()` and
  `utf16_len()` convert them.
* **Where the commands are documented:** SlideMage's own commands are defined in `latex/SlideMage_base.tex`
  (about 15 public `\NewDocumentCommand`/`\NewDocumentEnvironment`, plus older `\newcommand`s). Most have a long
  comment block above them. For `\cornerfigure` it lists every key (`width`, `height`, `border`, `corner=ne|nw|se|sw|e|w`,
  `block`, `xshift`, `yshift`, `node`). These comments are written for the people maintaining the code. They record
  where each request came from ("direct instruction: …"), the implementation, and the TikZ construct the command
  replaced, so they can't be shown to users as they are.
* **User-facing text already exists in parts:** `docs/SlideMageCommands.md`, `README.md`, the Quick Reference slides
  (`example/slides/1uw-…`, `1d7-…`) and the condensed AI guide (`ai/guides.py`).

## 2. Approach

**A curated help catalogue, Qt-free, kept in step with `SlideMage_base.tex` by a test.**

### 2.1 `src/slidemage/latex_help.py` (new, Qt-free)

```python
@dataclass(frozen=True)
class KeyHelp:
    name: str            # "corner"
    values: str          # "ne | nw | se | sw | e | w"  ("" for a flag such as border)
    text: str            # "Which corner of the content area (default ne)."

@dataclass(frozen=True)
class CommandHelp:
    name: str            # "cornerfigure" (environments: "besidefigure", kind="env")
    kind: str            # "command" | "env"
    signature: str       # r"\cornerfigure[keys]{image file or content}"
    summary: str         # one or two sentences
    keys: tuple[KeyHelp, ...] = ()
    example: str = ""    # r"\cornerfigure[height=5.6cm, border]{media/chart-x.png}"

COMMANDS: dict[str, CommandHelp]

def help_at(text: str, offset: int) -> HelpHit | None
```

`help_at` finds what is under the pointer. It returns `HelpHit(command, key)`, where `key` is set when the pointer
is on a key in the command's `[...]`:

* on `\cornerfigure` (including the backslash), or on the name in `\begin{besidefigure}` or `\end{besidefigure}`:
  the command's help;
* inside the optional argument of a known command, on `corner=se`: the same tooltip with that key's row
  highlighted (H3);
* in a comment (`COMMENT_RE`), in plain text, or on an unknown command: `None`.

### 2.2 Hovering in the editor (`source_editor.py`)

* Override `viewportEvent()` for `QEvent.ToolTip`. The event is a `QHelpEvent`, and in a `QPlainTextEdit` it arrives
  at the viewport. `cursorForPosition(event.pos())` gives the position, which is converted from UTF-16 to a character
  offset. Then `latex_help.help_at(self.toPlainText(), offset)`. If there is a hit, `QToolTip.showText(globalPos,
  html, viewport, rect)`, where `rect` is the token's rectangle so the tooltip goes away once the pointer leaves the
  word. With no hit, `QToolTip.hideText()` and `event.ignore()`.
* `format_help_html(hit, theme)`: the signature in the monospace font, the summary, a two-column table of keys
  (the hovered key in bold), and the example. The colours come from the kit theme tokens, so it works in light and
  dark. Its width is capped at about 60 characters.
* The `SourceEditor` protocol is unchanged, because the hover belongs to this implementation. A different editor
  (EMBEDDED_EDITOR_PLAN.md) can reuse `latex_help` as it is.
* **Keyboard:** F1 (or Ctrl+Shift+Space, H4) shows the same tooltip for the command at the text cursor, so the help
  also works without a mouse.

### 2.3 Keeping the catalogue in step: `tests/test_latex_help.py`

* Parse `SlideMage_base.tex` for its public `\NewDocumentCommand{\X}`, `\NewDocumentEnvironment{X}` and
  `\newcommand{\X}` (names without `@`). Every one has a `COMMANDS` entry or appears in a short `UNDOCUMENTED` set
  with a reason, such as an internal command or a theme setter. A new command added to the base without help then
  fails the test.
* For commands that take keys, the catalogue's key names match the `pgfqkeys` keys in the base (for `\cornerfigure`,
  the `/SMCorner` keys). So a key that is renamed or added can't go unnoticed.
* Tests for `help_at` cover: on the backslash, in the middle of the name, past the end, on a key, on a key's value,
  inside a comment, `\begin{…}`, nested braces in the `[...]`, and non-BMP characters before the command (the
  UTF-16 trap).

## 3. Steps

1. **`latex_help.py` with `help_at()` and its tests, plus entries for the figure commands** (`\cornerfigure`,
   `besidefigure`, `\fitfigure`, `\sectionfigure`, `\SMQRCode`). Their text is condensed from the base comments and
   `SlideMageCommands.md`, with the provenance and implementation notes left out.
2. **The hover and F1 in `LatexPlainTextEdit`**, `format_help_html`, and a GUI test (`pytest-qt`): send a
   `QHelpEvent` at the position of `\cornerfigure` and check the text from `QToolTip.text()`. Bump the version and
   add a CHANGELOG entry. This is the first PR the user can try.
3. **The rest of the base commands:** reveal steps (`\deckreveal`, `\deckrevealfinal`, `\slidestep`), versions,
   `\multilingualtext`, `SMTable`, the floating blocks, `\SMCodeFile` and the remaining commands, until the sync test
   passes without a growing `UNDOCUMENTED` set. Second PR.
4. **Optional (H2):** common standard LaTeX/beamer commands (`\includegraphics` keys, `\pause`, `\only`, `\uncover`,
   `frame` options), and help that theme packages add for their own commands (H1).

## 4. Risks and details

* **A tooltip on every pause of the mouse can get in the way while reading.** It appears only over a known command
  or key, never over plain text, and after Qt's usual tooltip delay. A setting (H4) can turn it off.
* **Performance:** `help_at` scans only the current line and the lines just around it (an optional argument can run
  over a line break), not the whole file. It runs only when Qt sends a ToolTip event.
* **Two sources for the same text** (the base comments and the catalogue): the sync test catches commands and keys
  that are missing, but not a description that has gone out of date. When a command's key changes, the CHANGELOG
  habit extends to `latex_help.py`.

## 5. Decisions for the user

* **H1 Where the help text lives.** (a) Hand-written catalogue in `latex_help.py` with a sync test *(recommended)*.
  (b) Structured `%: help` lines in `SlideMage_base.tex` above each command, parsed when the app starts. This keeps
  one source, but it adds a parser for comments in the `.tex` file, and theme packages could write the same lines in
  their templates. (c) Both: (a) now, and later (b) only for theme packages.
* **H2 Scope.** SlideMage's own commands only *(recommended for steps 1 to 3)*, or also a selection of standard
  LaTeX/beamer commands.
* **H3 Hovering over a key.** Show the whole command help with that key highlighted *(recommended)*, or only that
  key's line.
* **H4 Keyboard and setting.** F1 for the command at the cursor, and a "Show LaTeX help on hover" switch (on by
  default) in Preferences → Editor. Or no switch.
