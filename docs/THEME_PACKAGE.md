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
                                          # fira, lmsans or lmroman (SlideMage's), or <name> with SlideMage_layout_<name>.tex
```

Rules (the app and the packing tool apply the same ones; a broken rule is refused with a sentence saying which):

- Every field is required and text. `api_version`, `needs` and `network` are refused: they belong to `plugin.toml`,
  and a theme runs no Python.
- The `id` is the template key, hyphens and all (`uni-graz`), unlike a plugin's package folder.
- The `id` may not be the key of a template SlideMage ships (today `slidemage` and, since v10.18.0, `greyscale`): a
  theme cannot replace a bundled template.
- `requires_slidemage` must accept the running SlideMage, or the theme is not installed.
- The template file `SlideMage_template_<id>.tex`, `README.md`, `CHANGELOG.md` and `LICENSE` must be there, and
  the scheme folder, if any, must be `schemes/scheme_<id with _>/`.
- A `layout` other than `fira`, `lmsans` or `lmroman` needs the package's own `SlideMage_layout_<layout>.tex`; a
  package with one of those three names must **not** ship that file (it would replace SlideMage's profile for every
  deck, since installed themes are on TEXINPUTS ahead of the framework), and is refused.
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

- **Add from file…** (Settings → Extensions → Themes) takes a `.smtheme`. It shows the
  theme's name, version, key, author and licence first. A `.sha256` file next to it is checked before that; a
  mismatch installs nothing. Then the archive members pass the plugin installer's zip checks, and the unpacked
  folder every rule above. Nothing is changed when a check fails.
- **Where:** unpacked in `config_dir()/themes/<key>/` (Windows `%APPDATA%\SlideMage\themes\<key>\`). Installing a
  key that is installed replaces it. A theme takes effect at once, no restart.
- **Removing:** Settings → Extensions → Themes → Remove. Decks using the key then need a project copy of the template.
- **From GitHub:** Settings → Extensions → Themes → **Add from GitHub…** (below), since v10.17.0. A theme
  installed from a file is never updated.

## From a (private) GitHub repository

Since v10.17.0 (step 17 of the plan; `src/slidemage/theme_sources.py`). **Add from GitHub…** takes the
repository as `owner/name` (a `https://github.com/owner/name` address works too) and reads it with the GitHub token
SlideMage keeps for its own updates: Settings → General → Updates, stored as `github_token` in `config_dir()`, never
in a project; `$SLIDEMAGE_GITHUB_TOKEN` wins. There is no second token setting: one token covers SlideMage and every
theme repository it can read.

- **Which release:** SlideMage lists `/repos/{owner}/{name}/releases`, never `/releases/latest` (GitHub can mark a
  broken or withdrawn release "Latest"), and installs the newest **eligible** one. Eligible: published (not a draft,
  not a pre-release), carrying `<key>-<version>.smtheme` and `<key>-<version>.smtheme.sha256` with `<version>` its
  tag without the `v`, the download matching the hash, the `theme.toml` version equal to the tag, and its
  `requires_slidemage` accepting the running SlideMage. A release failing one of these is passed over for the next
  older one (the message says which and why). A release its owner withdraws (deletes, or turns into a pre-release)
  is no longer eligible. The SHA-256 only guards against a damaged download; trust comes from choosing the
  repository. Before installing, SlideMage shows the theme's name, version, key, author, licence and repository.
- **Downloads** use the API address of each asset with `Accept: application/octet-stream` (a private repository's
  files are not on the public download address); GitHub answers with a redirect to the file.
- **Where it came from:** `config_dir()/themes/<key>/source.json` records the repository, version, release id and
  install time (and the last update check's time and failure, and a version you skipped). A package cannot contain
  a `source.json`, so installing from a file over it drops it: that theme is then never updated.
- **Updates:** at every start, as the app's own update check, and only when the update setting (Settings → General →
  Updates) is not "Don't check": then nothing goes to the network. Each theme from GitHub is checked for a newer
  eligible release, which is offered with its release notes: **Install now** / **Not now** (asked again next start) /
  **Skip this version** (a later version is offered). It is never installed silently, also not in the automatic
  update mode. A higher major version says it may change how slides look. **Check for update** on the theme's row
  asks at once.
- **After an install,** only the previews of decks using that key are rendered again: their renders read the
  theme's files, which changed, so the background previews do them again; the open deck's slide renders at once.
- **Failures are quiet and harmless.** No token, an expired token, lost access or no network leave the installed
  version working; the log gets a line and the theme's row in Settings says why the last check failed. GitHub's
  404 means no access or no release (a private repository is invisible without access); 401 or 403 means the token
  was refused, and the message names the permission it needs.
- **A project's own copy** of the template still wins, so a project can freeze a version.

### The token a private theme needs

From GitHub's documentation (checked 2026-10-31: "Managing your personal access tokens", "Setting a personal access
token policy for your organization", "Permissions required for fine-grained personal access tokens", "REST API
endpoints for releases"):

- A **fine-grained token** reaches the resources of **one resource owner**, a user or an organization, chosen when
  the token is made. A repository of another user where you are only a collaborator cannot be selected, so private
  theme repositories live in a GitHub **organization** (the Uni Graz theme: `SlideMage/slidemage-theme-uni-graz`).
- Make it at GitHub → Settings → Developer settings → Personal access tokens → Fine-grained tokens:
  **Resource owner** = the repository's owner (e.g. `SlideMage`); **Repository access** = Only select repositories,
  with the theme repository (and `SlideMage/SlideMage` if SlideMage's own updates need it); **Repository
  permissions → Contents: Read-only** (GitHub lists `GET /repos/{owner}/{repo}/releases` and
  `GET /repos/{owner}/{repo}/releases/assets/{asset_id}` under Contents: read; Metadata: Read-only comes with it).
  Nothing else. Fine-grained tokens expire (366 days at most by default): renew it when the row says the token
  was refused.
- You must be able to read the repository yourself: a member of the organization whose base permission is read,
  or someone given read access to that repository.
- **The organization decides whether such tokens work.** An organization can block fine-grained tokens altogether,
  and by default it **requires an administrator's approval** for each fine-grained token that reaches it ("Require
  administrator approval" is the default; tokens of organization owners are approved at once). Until an owner
  approves it, the token is *pending* and reads only public resources: SlideMage then gets a 404 and says no access.
  The owner approves it under the organization's Settings → Personal access tokens → Pending requests.
- A **classic token** with the `repo` scope also works, but grants write access to every repository you can reach;
  prefer the fine-grained token.

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
LPPL-1.3c+. Such a theme is installed from its private repository with the user's own token (above), or from a file.
Changes to it come as pull requests from a fork; on GitHub's free plan a private repository has no branch protection,
so readers get read access and the organization allows forking of private repositories.

## For the website side

The catalogue's `"themes"` list (beside `"plugins"`) can now use this definition: the entry's id is the template key,
the asset `<key>-<version>.smtheme` with its `.sha256`, the manifest `theme.toml` with the fields above, `preview.png`
as the icon source. The first real theme packages are private (installed from private repositories), so a theme
repository should follow the same release rules whether or not it is listed.
