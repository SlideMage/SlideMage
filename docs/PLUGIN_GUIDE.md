# Plugin guide

Plugins use the public `slidemage.plugin_api` contract and the host passed to `activate(host)`.

## Looking like SlideMage

Build your UI with the host's themed widgets, such as `host.Card`, `host.Chip`, `host.Label` and
`host.IconButton`. They follow the app theme automatically. Use `host.Chip("1-0-0", mono=True)`
for micro-size monospace metadata. `host.IconButton("more_vert", "More", faint=True)` dims a glyph;
call its public `set_faint(bool)` when your row's hover or keyboard focus changes. The plugin owns
that interaction logic. These options are additive (SlideMage v0.14.36); existing calls keep their look.

Use `host.icon("check", host.theme().ok, px=16)` for a `QIcon` on a text button or other Qt control
(SlideMage v0.14.36). Names are Material Icons ligatures, just like `host.IconLabel` and
`host.IconButton`; the returned icon includes 1x and 2x pixmaps. Rebuild icons whose colours come
from the theme in your `on_theme_changed` callback.

For your own widgets, read sizes and colours from `host.theme()` (expanded in SlideMage v0.14.36):
`font_body` and the other `font_*` sizes are pixels; `font_sans` and `font_mono` are font families.
Spacing steps are `space_2xs`, `space_xs`, `space_sm`, `space_md`, `space_lg`, `space_xl` and
`space_2xl` (2, 4, 6, 8, 10, 12 and 16 px); use literal zero for no gap.
Use `radius_xs`, `radius_sm` and `radius_md` for corners, and `theme.pill(height)` for round shapes.
Use semantic colours such as `text`, `surface`, `ok` and `warning`, with their matching tint
backgrounds and foregrounds. `accents["teal"]` and the other named accents are categorical colours;
red and amber are reserved for errors and warnings. `link`, `selection` and the `syntax_*` colours
are also available.

Register `host.on_theme_changed(callback)` to refresh your own QSS and redraw painted parts with
the callback's new tokens. Call the returned unsubscribe function when your widget closes.
Target only your own object names in QSS; the kit's internal object names and selectors are not
public API. `host.theme_color("info")` is deprecated: use `host.theme().info` instead. The old call
continues to work quietly.
