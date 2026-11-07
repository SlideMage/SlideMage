# Plugin guide

Plugins use the public `slidemage.plugin_api` contract and the host passed to `activate(host)`.

## Looking like SlideMage

Build your UI with the host's themed widgets, such as `host.Card`, `host.Chip`, `host.Label` and
`host.IconButton`. They follow the app theme automatically.

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
