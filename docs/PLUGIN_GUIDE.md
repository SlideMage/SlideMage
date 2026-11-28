# Plugin guide

Plugins use the public `slidemage.plugin_api` contract and the host passed to `activate(host)`.
How the contract changes between releases is in [Versioning](#versioning).

## Telling SlideMage which slides you use

If your plugin stores slide IDs outside the project's `.slidemage/` folder (questions that cite a slide, say),
register `host.add_slide_reference_check(check)` in `activate()`. Before SlideMage retires a slide ID (replacing an
exact copy by its original), it calls `check(ids)` on a worker thread with a `frozenset` of bare IDs. Return one
readable line per reference found, or `[]`. Raise `plugin_api.ReferenceCheckUnavailable` with a message for the
user when you cannot tell (an offline folder); any other exception counts the same. SlideMage then refuses the
action. `host.settings().get()` and `host.project_root()` may be called from the check.

## Looking like SlideMage

The [design handbook deck](design-handbook/decks/design-handbook.tex) shows the
color roles, scales and widgets in both themes. See its [compile instructions](design-handbook/README.md)
for the local PDF at `design-handbook/build/design-handbook.pdf`; compiled decks are not committed.

Build your UI with the host's themed widgets, such as `host.Card`, `host.Chip`, `host.Label` and
`host.IconButton`. They follow the app theme automatically. Use `host.Chip("1-0-0", mono=True)`
for micro-size monospace metadata. `host.IconButton("more_vert", "More", faint=True)` dims a glyph;
call its public `set_faint(bool)` when your row's hover or keyboard focus changes. The plugin owns
that interaction logic. Existing calls keep their look when you leave these options off.

Use `host.icon("check", host.theme().ok, px=16)` for a `QIcon` on a text button or other Qt control.
Names are Material Icons ligatures, just like `host.IconLabel` and
`host.IconButton`; the returned icon includes 1x and 2x pixmaps. Rebuild icons whose colors come
from the theme in your `on_theme_changed` callback.

For your own widgets, read sizes and colors from `host.theme()` (colors, radii, the type and spacing scales):
`font_body` and the other `font_*` sizes are pixels; `font_sans` and `font_mono` are font families.
Spacing steps are `space_2xs`, `space_xs`, `space_sm`, `space_md`, `space_lg`, `space_xl` and
`space_2xl` (2, 4, 6, 8, 10, 12 and 16 px); use literal zero for no gap.
Use `radius_xs`, `radius_sm` and `radius_md` for corners, and `theme.pill(height)` for round shapes.
Use semantic colors such as `text`, `surface`, `ok` and `warning`, with their matching tint
backgrounds and foregrounds. `accents["teal"]` and the other named accents are categorical colors;
red and amber are reserved for errors and warnings. `link`, `selection` and the `syntax_*` colors
are also available.

Register `host.on_theme_changed(callback)` to refresh your own QSS and redraw painted parts with
the callback's new tokens. Call the returned unsubscribe function when your widget closes.
Target only your own object names in QSS; the kit's internal object names and selectors are not
public API. `host.theme_color("info")` is deprecated: use `host.theme().info` instead. The old call
continues to work quietly.

## Versioning

**API 1 is what SlideMage 1.0 ships.** `plugin_api.API_VERSION` is 1, and a plugin whose `plugin.toml` says
`api_version = 1` and `requires_slidemage = ">=1.0"` can rely on every name, parameter and behavior the module
documents; nothing in it needs probing at run time (no `getattr(plugin_api, ...)`, no `hasattr(host, ...)`). The
docstrings do not repeat per name which release introduced it, except for additions made after 1.0 (below).
Until SlideMage 1.0 is released, a plugin that targets it cannot install yet, because `">=1.0"` does not match a
0.x version: develop against the current 0.x release with `requires_slidemage = ">=0.17"` or whichever release you
test with, and change it to `">=1.0"` when 1.0 is out.

**What is an addition** (API stays 1): a new function, class, constant, `Host` method or dataclass field with a
default; a new optional parameter (with a default that keeps the old behavior); a wider set of accepted values.

**What is breaking** (API goes up): removing or renaming a public name; changing a signature incompatibly (a new
required parameter, a removed or reordered parameter, a different return type); changing documented behavior, such as
a default, a threading rule or what an error is raised for. A breaking change raises `API_VERSION` to the next whole
number. For a transition period `SUPPORTED_API_VERSIONS` lists both (`{1, 2}`) and the host keeps API 1 working next
to API 2; a later release drops the old one, and a plugin that still declares it is then listed as "written for
plugin API 1" and not loaded.

**Marking and requiring an addition.** A name, parameter or field added after 1.0 ends its docstring with a line
`Since SlideMage 1.x.` (the release that first has it; for a parameter, say which: "Since SlideMage 1.x:
parameter foo."). A plugin that uses it declares `requires_slidemage = ">=1.x"`. Do not probe for it.

**How a too-old SlideMage reacts.** The same check runs when a plugin is loaded, installed and chosen from the
catalogue, and it is by `requires_slidemage` and `api_version` only:

- loading: the plugin is listed but not run, with the reason "needs SlideMage >=1.x" (or "written for plugin API 2");
- installing from a file or from the catalogue: refused with "The plugin needs SlideMage >=1.x; this is 1.0.3." (or
  "The plugin uses plugin interface 2, which this SlideMage does not support.");
- the catalogue offers the newest release this SlideMage can run and skips the rest.

`requires_slidemage` takes comparisons joined by commas, such as `">=1.2"` or `">=1.0, <2"`. Write it in the
current numbering (SlideMage 1.0 and later: `>=1.0`); the old `>=9.0` style is read as 0.9 for plugins that still have it.
