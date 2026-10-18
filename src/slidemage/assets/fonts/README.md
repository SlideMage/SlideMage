# Bundled fonts

Loaded at startup by `slidemage/ui/kit/fonts.py`. Each family keeps its own
license text next to the files.

| Family | Files | Source | License |
|---|---|---|---|
| Roboto 3 (classic) v3.016 | every static file: Roboto-{Thin,Light,Regular,Medium,Bold,Black} with their italics, RobotoCondensed-*, and the variable Roboto[ital,wdth,wght].ttf | github.com/googlefonts/roboto-3-classic (release `Roboto_v3.016.zip`, `android/static` and `android/`) | SIL Open Font License 1.1 (`LICENSE-Roboto-OFL.txt`) |
| Roboto Mono v3.001 | every static file: RobotoMono-{Thin,Light,Regular,Medium,Bold} with their italics, and the variable RobotoMono[wght].ttf and RobotoMono-Italic[wght].ttf | github.com/googlefonts/RobotoMono (`fonts/ttf`, `fonts/variable`) | SIL Open Font License 1.1 (`LICENSE-RobotoMono-OFL.txt`) |
| Material Icons | MaterialIcons-Regular.ttf | github.com/google/material-design-icons (`font/`) | Apache License 2.0 (`LICENSE-MaterialIcons-Apache-2.0.txt`) |

Every weight from 100 to 900, upright and italic, has a real face: a static file or the variable font
(`ui/kit/fonts.py` loads every `.ttf` here, the static ones first). Without one, Qt thickens or slants a
neighbouring style itself, and on Windows the overlapping strokes of letters such as w and W then show dark
gaps (v8.27.3). Qt may take a style from the variable font even where a static file exists (Roboto Mono
Regular, for one); both are the same design.

Note: the UI redesign plan assumed Apache 2.0 for all three. Roboto has been
OFL since the Roboto 3 relicensing (google/fonts lists both families under
`ofl/`); only Material Icons is Apache 2.0. Both licenses allow bundling and
redistribution with the application.
