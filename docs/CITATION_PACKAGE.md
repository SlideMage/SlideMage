# Citation format packages

A **citation format** is how references look: the biblatex options and the bibliography drivers a deck's
`\SMUseBibliography` applies. Since v0.13.0 (step 18c of `docs/plans/template-owned-layout-and-own-theme.md`, user
decision 2026-10-31) it is a third category beside plugins and themes (`docs/THEME_PACKAGE.md`): a format can be
packaged on its own and installed on a computer, instead of being copied into every project. The code is
`src/slidemage/citations.py` (check, install, remove, TeX path), `src/slidemage/citation_sources.py` (GitHub
repositories and update offers) and `tools/make_citation_package.py` (packs one).

## How a format is chosen

- A format is the file `SlideMage_citation_<key>.tex`. It only redefines the two macros `\SMBiblatexOptions` and
  `\SMBibliographyStyle` (the biblatex options, and the code that runs after biblatex is loaded: name formats and
  `\DeclareBibliographyDriver`s). `latex/SlideMage_citation_default.tex` is the house format and the model; its key is
  `default`.
- The catalog (`SlideMage_setup.tex`) has the setting `\SMCitationFormat`, default `default`. A **template** sets
  another one between `\input{SlideMage_setup}` and `\input{SlideMage_base}`:

  ```tex
  \renewcommand{\SMCitationFormat}{apa}
  ```

  The base loads `SlideMage_citation_apa` at its very end, where templates used to `\input` the house format, so a
  template needs no line for the format at all.
- A **deck** may override the choice before `\SMUseBibliography`: set `\SMCitationFormat` (the call then loads that
  file), or redefine `\SMBiblatexOptions` / `\SMBibliographyStyle` (these win over the template's format, as before).
- A format that cannot be found is a TeX error naming the key (`The citation format "apa" is not available`), not a
  silent fall-back to another look.
- **Old names keep working.** `latex/SlideMage_bibliography_default.tex` stays as a one-line file that loads
  `SlideMage_citation_default`, so a template or a theme package with `\input{SlideMage_bibliography_default}`
  (such as the private Graz theme) renders as before; the format is then read twice, which only repeats two
  `\renewcommand`s of the same text. The compatibility entry `citation-format-by-the-framework` (optional) removes
  that line from a project's templates when their format is the default.

## Files

```
slidemage-citation-<key>/                 its own repository (or any folder)
  citation.toml                           the manifest (below)
  SlideMage_citation_<key>.tex            the format; the file name carries the key
  SlideMage_citation_<key>_<name>.tex     optional extra files (also .bbx .cbx .dbx .lbx): biblatex styles it loads,
                                          named after the format so they never shadow a stock style
  preview.png                             optional: the picture the catalogue shows
  LICENSE, README.md, CHANGELOG.md        required
  LICENSES/                               optional: licence texts (REUSE style)
```

Nothing else. In particular:

- TeX code is only the format file and files named `SlideMage_citation_<key>_*`. An installed package sits on TeX's
  search path, so any other `.sty`, `.bbx`, `.cbx`, `.bst` or `.lua` could replace a stock file for every deck.
- No file named like one of SlideMage's own framework files (anything in `latex/`, `SlideMage_citation_default.tex`
  included): installed packages sit on TEXINPUTS ahead of the framework and would replace it for every deck.
- No compiled files (`.pyc .pyo .so .pyd .dll .dylib .exe`), no symbolic links, no paths outside the package
  (absolute paths, drive letters, `..`, backslashes), no other folder than `LICENSES/`.
- Files and folders starting with a dot (`.git/`, `.github/`, `.gitignore`) are not packed.

## citation.toml

```toml
id = "apa"                                # the format key: 2-32 characters, a lowercase letter, then a-z 0-9 -
name = "APA 7"                            # 1-40 characters
version = "1.0.0"                         # MAJOR.MINOR.PATCH; equals the release tag without its "v"
requires_slidemage = ">=0.13.0"           # comparisons joined by commas: ">=0.13.0, <0.15"
summary = "Author-year citations and a reference list after APA 7."   # 1-120 characters
author = "Jane Doe"
homepage = "https://github.com/jdoe/slidemage-citation-apa"           # http(s)
license = "LPPL-1.3c-or-later"            # what LICENSE says
```

Rules (the app and the packing tool apply the same ones; a broken rule is refused with a sentence saying which):

- Every field is required and text. `api_version`, `needs`, `network` and `layout` are refused: a citation format
  runs no Python and has no layout profile.
- The `id` may not be the key of a format SlideMage ships (today `default`): a package cannot replace it.
- `requires_slidemage` must accept the running SlideMage, or the package is not installed.
- `SlideMage_citation_<id>.tex`, `README.md`, `CHANGELOG.md` and `LICENSE` must be there.

## The release asset

A release is a zip named `<key>-<version>.smcite` with `citation.toml` at its top level (not inside a folder), plus
`<key>-<version>.smcite.sha256` in the `sha256sum` format: `<64 lowercase hex>  <file name>` and a newline. It is
attached to the repository's GitHub release for tag `v<version>`, which carries `README.md` and `CHANGELOG.md` at
that tag.

```bash
python tools/make_citation_package.py path/to/slidemage-citation-apa --out dist
```

checks the folder with the installer's rules and writes both files; the same folder always gives the same bytes
(files in name order, a fixed date), so the checksum is reproducible.

## Installing, and where TeX finds it

- **Install from file…** (Settings → Plugins; the same button as for plugins and themes) takes a `.smcite`: its
  `citation.toml` is shown first, a `.sha256` next to it is checked, then the archive passes the plugin installer's
  zip checks and the unpacked folder every rule above. It is unpacked in `config_dir()/citations/<key>/` (Windows
  `%APPDATA%\SlideMage\citations\<key>\`), replacing an installed version of the key; it takes effect at once.
- **Removing:** Settings → Plugins → Citation formats → Remove. Decks that choose the key then need a copy of the file
  in their project.
- **From GitHub:** Settings → Plugins → Citation formats → **Add citation format from GitHub…** takes
  `owner/name`, reads the repository's releases with the GitHub token of Settings → General and installs the newest
  eligible one: published, with `<key>-<version>.smcite` and its `.sha256`, a matching download, a `citation.toml`
  whose version equals the tag and whose `requires_slidemage` accepts this SlideMage (the same rules and failure
  messages as for themes, `docs/THEME_PACKAGE.md`, "From a (private) GitHub repository"). `source.json` in the
  package's folder records where it came from. At every start (unless the update setting is "Don't check") each
  GitHub-installed format is checked and a newer release is **offered**, never installed silently: Install now / Not
  now / Skip this version; **Check for update** on the row asks at once. A format installed from a file is never
  updated.
- **Search order**, as for themes: `compiler.build_env` puts every installed format folder on `TEXINPUTS` (with a
  trailing separator, in front of the installed themes), after the project root and the framework that the project's
  `.latexmkrc` puts first. So TeX finds **(1)** the project's own copy of `SlideMage_citation_<key>.tex`, which wins and
  lets a project freeze a version, **(2)** the framework's (`latex/`, the bundled `default`), **(3)** the installed
  packages.
- **Previews, snapshots, export:** previews use the same `TEXINPUTS`; a deck snapshot copies the files a compile read from
  an installed format into its project root; Export LaTeX brings them into the exported folder's root.

## For the website side

See `docs/Handover_2026-10-31-Citation-Formats-For-Website.md`.
