# Terminal page

The page of the Claude Code view (`ui/workspace/terminal/web.py`), loaded from disk by a Qt web view: no
network, no CDN. Vendored files are unmodified copies from the npm packages; `terminal.html` and
`terminal.js` are SlideMage's own glue.

| File | Source | License |
|---|---|---|
| xterm.js, xterm.css | `@xterm/xterm` 6.0.0 (`lib/xterm.js`, `css/xterm.css`) | MIT (`LICENSE-xterm-MIT.txt`) |
| addon-fit.js | `@xterm/addon-fit` 0.11.0 (`lib/addon-fit.js`) | MIT (`LICENSE-addon-fit-MIT.txt`) |

To update: `npm pack @xterm/xterm@<version> @xterm/addon-fit@<version>`, copy the same files over, and check
that the two versions are compatible (the fit addon's release notes say which xterm it targets).
The font is `../fonts/RobotoMono-*.ttf` (see the README there).
