# Handover: citation formats as a third category on the website

For whoever works on the website repository (separate from this one). Decided 2026-10-31, built in SlideMage v0.13.0
(step 18c). The full definition is `docs/CITATION_PACKAGE.md` in the SlideMage repository; this note is what the
website needs from it.

## What it is

Plugins add features, themes (`docs/THEME_PACKAGE.md`) add slide templates, and now **citation formats** add ways
references look (biblatex options and bibliography drivers: "Author, Initials., year. "Title", ..."). A deck or
template chooses one by its key with the catalog setting `\SMCitationFormat`; the format file is
`SlideMage_citation_<key>.tex`. The built-in house format is `default` and is not a package.

## What a package contains

A zip named `<key>-<version>.smcite` with `citation.toml` at its top level, plus `<key>-<version>.smcite.sha256`
(`sha256sum` format: `<64 lowercase hex>  <file name>`). Both are attached to a GitHub release with tag
`v<version>`. Inside:

```
citation.toml                         manifest
SlideMage_citation_<key>.tex          the format
SlideMage_citation_<key>_<name>.*     optional extra TeX files (.tex .bbx .cbx .dbx .lbx)
README.md, CHANGELOG.md, LICENSE      required
preview.png                           optional: sample of a reference list, for the catalogue
LICENSES/                             optional
```

`citation.toml` fields (all required text): `id` (the key, `^[a-z][a-z0-9-]{1,31}$`, never `default`), `name` (1-40
characters), `version` (`1.2.3`, equal to the tag without `v`), `requires_slidemage` (`">=0.13.0"`, comma-joined
comparisons), `summary` (1-120), `author`, `homepage` (http/https), `license`. No `api_version`, `needs`, `network` or
`layout`: a format runs no code but TeX. A package is checked by `tools/make_citation_package.py` (it also builds
the two release files); the website can run the same checks on a submitted repository.

## How the catalogue lists it

Beside `"plugins"` and `"themes"`, a third list, `"citations"`:

| catalogue entry field | taken from |
|---|---|
| `id` | the key (`citation.toml` `id`; also the asset prefix) |
| `name`, `summary`, `author`, `license`, `homepage`, `requires_slidemage` | `citation.toml` |
| `version`, release notes | the newest eligible release: tag `v<version>`, `CHANGELOG.md` at that tag |
| download, checksum | `<key>-<version>.smcite` and its `.sha256` |
| icon / image | `preview.png`, if present |

Release rules are the plugins' and themes': published (not draft, not pre-release), both assets present with
`<version>` equal to the tag without `v`, the zip's `citation.toml` carrying that version, the download matching the
hash. A page for the category can say "A citation format changes how references look; it contains a TeX file and no
program", and how to use one: install from the catalogue or from a file in Settings → Plugins → Citation formats,
then in a template `\renewcommand{\SMCitationFormat}{<key>}` (before `\input{SlideMage_base}`) or in a deck the same
before `\SMUseBibliography`.

## What the app does not do (yet)

The app installs from a file and from a GitHub repository (with update offers) like for themes. It does not read the
catalogue's `"citations"` list yet: that comes with the website side, mirroring how `"themes"` is meant to work, and
needs a decision on the catalogue's schema version (the app reads a catalogue it does not know as too new).
