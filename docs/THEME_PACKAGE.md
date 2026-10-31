# Theme packages

A **theme package** is a SlideMage slide template packaged on its own, so it can be installed on a computer instead
of being copied into every project. It is defined here since v10.16.0 (step 16 of
`docs/plans/template-owned-layout-and-own-theme.md`, user decision 2026-10-31, as proposed in that plan's section 8).
The code is `src/slidemage/themes.py`; `tools/make_theme_package.py` packs one.

## The word clash

A catalogue "theme" is what the framework calls a **template**: the institution layer
`SlideMage_template_<key>.tex`, its `schemes/scheme_<key>/` folder and at most its own layout profile. It is **never
the beamer theme**: `latex/beamerthemeSlideMage.sty` is part of the framework and never ships separately. A deck
uses a theme exactly as it uses a template, by its key: `\input{SlideMage_template_<key>}`.

## Files

```
slidemage-theme-<key>/                    its own repository (or any folder)
  theme.toml                              the manifest (below)
  SlideMage_template_<key>.tex            the template; the file name carries the key
  schemes/scheme_<key_>/                  logos and other pictures; <key_> is the key with "-" as "_"
                                          (key uni-graz: schemes/scheme_uni_graz/)
  SlideMage_layout_<name>.tex             optional: an own layout profile, when theme.toml's layout names one
  preview.png                             optional: the picture the catalogue shows
  LICENSE, README.md, CHANGELOG.md        required
  LICENSES/                               optional: licence texts (REUSE style)
```

Nothing else. In particular:

- Only the template and its own layout profile may be TeX code (`.tex .sty .cls .lua .def .cfg .fd .clo .ltx .dtx
  .ins`). An installed theme sits on TeX's search path ahead of the TeX distribution, so a `.sty` in it would
  replace a package of the same name for every deck.
- No compiled files (`.pyc .pyo .so .pyd .dll .dylib .exe`), no symbolic links, no paths outside the package
  (absolute paths, drive letters, `..`, backslashes).
- A template must stay self-contained: nothing of it may assume it sits in a project root, so a logo is named
  `schemes/scheme_<key_>/logo.pdf`, found on the search path wherever the theme is.
- Files and folders starting with a dot (`.git/`, `.github/`, `.gitignore`) are not packed.

## theme.toml

```toml
id = "sample-theme"                       # the template key: 2-32 characters, a lowercase letter, then a-z 0-9 -
name = "Sample Theme"                     # 1-40 characters
version = "1.0.0"                         # MAJOR.MINOR.PATCH; equals the release tag without its "v"
requires_slidemage = ">=10.16"            # comparisons joined by commas: ">=10.16, <11"
summary = "A test theme: the SlideMage look with a green title bar."   # 1-120 characters
author = "Jane Doe"
homepage = "https://github.com/jdoe/slidemage-theme-sample"             # http(s)
license = "LPPL-1.3c-or-later"            # what LICENSE says; see "Private themes" for logos
layout = "fira"                           # the layout profile the template sets with \SMLayoutProfile:
                                          # fira or lmsans (SlideMage's), or <name> with SlideMage_layout_<name>.tex
```

Rules (the app and the packing tool apply the same ones; a broken rule is refused with a sentence saying which):

- Every field is required and text. `api_version`, `needs` and `network` are refused: they belong to `plugin.toml`,
  and a theme runs no Python.
- The `id` is the template key, hyphens and all (`uni-graz`), unlike a plugin's package folder.
- The `id` may not be the key of a template SlideMage ships (today `slidemage`): a theme cannot replace a bundled
  template.
- `requires_slidemage` must accept the running SlideMage, or the theme is not installed.
- The template file `SlideMage_template_<id>.tex`, `README.md`, `CHANGELOG.md` and `LICENSE` must be there, and
  the scheme folder, if any, must be `schemes/scheme_<id with _>/`.
- A `layout` other than `fira` or `lmsans` needs the package's own `SlideMage_layout_<layout>.tex`.
- Optional in the template: a `% SlideMage template name: <label>` line in its first 30 lines names it in the
  dialogs (as for any template).

## The release asset

A release is a zip named `<key>-<version>.smtheme` with `theme.toml` at its top level (not inside a folder), plus
`<key>-<version>.smtheme.sha256` in the `sha256sum` format: `<64 lowercase hex>  <file name>` and a newline. It is
attached to the theme repository's GitHub release for tag `v<version>`, which carries `README.md` and
`CHANGELOG.md` at that tag (the website's release rules, so a public theme can be listed unchanged).

```bash
python tools/make_theme_package.py path/to/slidemage-theme-sample --out dist
```

checks the folder with the installer's rules and writes both files; the same folder always gives the same bytes
(files in name order, a fixed date), so the checksum is reproducible. `--app-version` checks `requires_slidemage`
against another SlideMage than the checkout's.

## Installing

- **Install from file…** (Settings → Plugins; the same button as for a `.smplugin`) takes a `.smtheme`. It shows the
  theme's name, version, key, author and licence first. A `.sha256` file next to it is checked before that; a
  mismatch installs nothing. Then the archive members pass the plugin installer's zip checks, and the unpacked
  folder every rule above. Nothing is changed when a check fails.
- **Where:** unpacked in `config_dir()/themes/<key>/` (Windows `%APPDATA%\SlideMage\themes\<key>\`). Installing a
  key that is installed replaces it. A theme takes effect at once, no restart.
- **Removing:** Settings → Plugins → Themes → Remove. Decks using the key then need a project copy of the template.
- **Not yet (step 17 of the plan):** installing from a theme's GitHub repository with the user's token, update
  checks and offers, and `source.json` (where a theme came from). A theme installed from a file is never updated.

## Where TeX finds it, and who wins

SlideMage puts every installed theme folder on `TEXINPUTS` for every compile and every preview
(`compiler.build_env`), with a trailing separator so the TeX distribution's own path stays. The project's
`.latexmkrc` puts the project root and the framework in front, so TeX searches:

1. the **project's own copy** (`SlideMage_template_<key>.tex` in the project root): it wins, which also lets a user
   freeze a version of a theme;
2. the **framework** (`latex/`, the bundled templates; a theme cannot take a bundled key anyway);
3. the **installed themes**, in key order.

The template pickers (a deck's settings, Settings → General's render template, New deck) list installed themes
beside the project's and the bundled templates, in that same order (`slide_snapshot.template_dirs`).

- **Previews:** the same `TEXINPUTS`, so a preview renders what a compile renders. Preview equivalence
  (`docs/PREVIEW_RENDER_EQUIVALENCE_CONTRACT.md`) accepts exactly the theme folders on `TEXINPUTS` (anything else
  there is a custom search path) and treats a theme's template like a project template: shared between views only
  when its digest is audited, otherwise rendered on its own.
- **Deck snapshots** compile with their own copies only (no `TEXINPUTS`): the files a compile read from an installed
  theme are copied into the snapshot's project root, where a project's own template would be.
- **Export LaTeX** brings a theme's template, scheme files and layout profile into the exported folder's root, as
  it does a project template's.

## Private themes stay out of the catalogue

A theme carrying a university's logo and corporate design is not ours to publish: its repository is private, it is
never listed in the catalogue (not even `hidden: true`, which would publish its URL in the test catalogue), and the
SlideMage repository ships no institution template (since v10.16.0). Its `LICENSE` and `README.md` say that the logo
files are the institution's, used with its permission, and must not be passed on; the TeX file can still be
LPPL-1.3c+. Such a theme is installed from a file today and from its private repository once step 17 exists.

## For the website side

The catalogue's `"themes"` list (beside `"plugins"`) can now use this definition: the entry's id is the template key,
the asset `<key>-<version>.smtheme` with its `.sha256`, the manifest `theme.toml` with the fields above, `preview.png`
as the icon source. The first real theme packages are private (installed from private repositories), so a theme
repository should follow the same release rules whether or not it is listed.
