# Theme form writes `\colorlet` for macro-valued color hooks: title bar renders dark gray

Status: fixed in the app 2026-11-13, not committed: branch `fix/theme-form-hook-macro-colorlet`, worktree `D:\Dropbox\repos\SlideMage\.claude\worktrees\hook-macro-colorlet`, v0.16.40 (suggested fix 1 to 5 all done; a real compile confirmed the cause: the stale line gives a #1e1e1e bar, the `\renewcommand` the blue). **Still open: line 103 of the user's `D:\uniCLOUD\Slidemaster\SlideMage_template_uni-ibk.tex` is unchanged** (the session's edit of that file was refused by the permission check). With the fixed app, setting the title bar again in the form rewrites the line; or change it by hand.

## Symptom

In the University of Innsbruck theme edit form (Colors tab), the user set the title bar (role `title_fill`, macro
`\SMTitleBoxColor`) to `c_secondary_blue` (the theme's `#003360`). The form's swatch shows the blue, but the compiled
slide's title bar is dark gray. The footer box, set the same way, renders correctly. The lint says "No problems found".

## Cause

The user's theme, `D:\uniCLOUD\Slidemaster\SlideMage_template_uni-ibk.tex`, line 103, inside the
`% --- SlideMage theme editor: begin/end ---` block, holds:

```tex
\colorlet{SMTitleBoxColor}{c_secondary_blue}
```

But `\SMTitleBoxColor` is a macro holding a color name: `latex/SlideMage_setup.tex:233` has
`\newcommand{\SMTitleBoxColor}{c_primary_dark}`, and `\SMApplyColorRoles` in `latex/beamerthemeSlideMage.sty` (~line 220)
does `\colorlet{SMColorA}{\SMTitleBoxColor}`. `\colorlet{SMTitleBoxColor}{...}` defines a color named `SMTitleBoxColor`
and leaves the macro untouched, so LaTeX still uses `c_primary_dark` (dark gray). The title slide's box
(`latex/SlideMage_base.tex` ~4968 and ~5628, `fill=\SMTitleBoxColor`) is affected the same way.

The footer works because the theme has `\renewcommand{\SMFooterBoxColorDefault}{c_secondary_blue}` (line 82), which is
the right form.

## Where the form goes wrong

`ThemeFile._line_for` in `src/slidemage/theme_file.py` (~line 334):

```python
if (field.kind == "colour") if field else (not key.startswith("SM") or key.endswith("Color")):
    ...
    return f"\\colorlet{{{key}}}{{{value.strip()}}}"   # or \definecolor
```

`theme_fields.BY_NAME` has no entry for the hook macro names, so `field` is None and the fallback treats any `SM...Color`
key as a palette color. That is meant for names like `SMCodeKeywordColor`. It also catches the macro-valued hooks
`SMTitleBoxColor`, `SMTitleTextColor` and `SMBulletColor`. `SMFooterBoxColorDefault` escapes only because its name ends
in "Default".

Call path: `ThemeModel.set_role(role, base mode, value)` in `src/slidemage/theme_form_model.py:289` calls
`self.file.set(hook, value)`, then `ThemeFile.set` → `_add` → `_line_for`.

Related: the macro names are listed as `CATALOG_MACROS` in `src/slidemage/compat_setup.py:32` and as `ROLE_OF_HOOK` /
`hook` in `src/slidemage/theme_fields.py` (~lines 38 and 64).

Why nothing flagged it: the form reads the `\colorlet` line back, so the swatch resolves to blue. The sample-slide
preview does not show the gray, only the real LaTeX compile does. The lint does not check that a hook macro is set with
`\renewcommand`.

## Suggested fix

1. In `_line_for`, write `\renewcommand{\Key}{value}` for the hook macros (every macro in `theme_fields.ROLE_OF_HOOK`
   and the catalog macros `SMBulletColor`, `SMTitleBoxColor`, `SMTitleTextColor`; check `SlideMage_setup.tex` for any
   other `\newcommand{\SM...Color}` color-name macro) instead of `\colorlet` / `\definecolor`. The value can be a
   color name or an xcolor expression, as for `SMFooterBoxColorDefault`. Better: decide by whether the catalog says
   the name is a macro, not by the name's suffix.
2. Make `ThemeFile.find`/`value` and `_replace` handle a stale `\colorlet{SMTitleBoxColor}` already in a theme: when
   the form edits a hook macro and finds a `\colorlet` of that name, rewrite it as `\renewcommand` in place.
3. Consider a lint warning (`latex_lint.py`) for `\colorlet` / `\definecolor` of a name that is a catalog macro.
4. Add a regression test in `tests/test_theme_form_model.py` or `tests/test_theme_file.py`:
   `set_role("title_fill", base, "c_secondary_blue")` on a theme without the line must write
   `\renewcommand{\SMTitleBoxColor}{c_secondary_blue}`. Another case: a file with the stale `\colorlet` line gets
   converted. `test_theme_form_model.py:99` already calls `modeshape.set_role("title_fill", "light", ...)` and may
   currently assert the wrong line.
5. Add a CHANGELOG entry in `src/slidemage/CHANGELOG.md` with a version bump, following the repo's habit.

Also fix the user's file: replace line 103 of `D:\uniCLOUD\Slidemaster\SlideMage_template_uni-ibk.tex` with
`\renewcommand{\SMTitleBoxColor}{c_secondary_blue}`. It sits inside the editor-managed block, so check that the form
keeps it after a reload. Then recompile a sample to confirm the bar is `#003360`.

## Not yet verified

- That the compile really gives `c_primary_dark` for the bar. This is inferred from the LaTeX source and the screenshot's
  gray, not from a log or PDF.
- Whether the form's color field showed `_secondary_blue` (no leading `c`) in the screenshot because of clipping or a
  real typo. The file itself has `c_secondary_blue`, so it is most likely clipping.
- Which other hook macros hit the same path in practice (`SMTitleTextColor`, `SMBulletColor`).
