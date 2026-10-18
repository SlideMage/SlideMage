# Bundled fonts

Loaded at startup by `slidemage/ui/kit/fonts.py`. Each family keeps its own
license text next to the files.

| Family | Files | Source | License |
|---|---|---|---|
| Roboto 3 (classic) v3.016 | Roboto-Regular/Medium/Bold.ttf | github.com/googlefonts/roboto-3-classic (release `android/static`) | SIL Open Font License 1.1 (`LICENSE-Roboto-OFL.txt`) |
| Roboto 3 (classic) v3.016, variable | Roboto[ital,wdth,wght].ttf (weight 600, which has no static file) | github.com/googlefonts/roboto-3-classic (release `Roboto_v3.016.zip`, `android/`) | SIL Open Font License 1.1 (`LICENSE-Roboto-OFL.txt`) |
| Roboto Mono | RobotoMono-Regular/Medium.ttf | github.com/googlefonts/RobotoMono (`fonts/ttf`) | SIL Open Font License 1.1 (`LICENSE-RobotoMono-OFL.txt`) |
| Material Icons | MaterialIcons-Regular.ttf | github.com/google/material-design-icons (`font/`) | Apache License 2.0 (`LICENSE-MaterialIcons-Apache-2.0.txt`) |

Note: the UI redesign plan assumed Apache 2.0 for all three. Roboto has been
OFL since the Roboto 3 relicensing (google/fonts lists both families under
`ofl/`); only Material Icons is Apache 2.0. Both licenses allow bundling and
redistribution with the application.
