# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Pack a theme folder into its release asset (docs/THEME_PACKAGE.md).

    python tools/make_theme_package.py <theme folder> --out <dir>

The folder holds theme.toml, SlideMage_template_<key>.tex, README.md, CHANGELOG.md, LICENSE and, as the theme has
them, schemes/scheme_<key>/, its own SlideMage_layout_<name>.tex, preview.png and LICENSES/; what starts with a dot
(.git/, .github/, .gitignore) is left out. It is checked with the
rules SlideMage's "Install from file…" applies (slidemage.themes.check_folder), so a package this writes installs.
Written to <dir>: <key>-<version>.smtheme (a zip, theme.toml at its top) and <key>-<version>.smtheme.sha256 in the
`sha256sum` format ("<64 hex>  <file name>"). Files are stored in name order with a fixed date, so the same folder
gives the same bytes and the same checksum.

--app-version checks requires_slidemage against another SlideMage than this checkout's (default: version.py).
Exit 0 and the asset's path on success; exit 1 and the reason on stderr when a rule is broken.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

from slidemage import themes  # noqa: E402
from slidemage.theme_export import FIXED_DATE, pack  # noqa: E402,F401  (the app's Export uses the same packer)
from slidemage.version import VERSION_NUMBER  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("folder", type=Path, help="the theme folder (with theme.toml)")
    parser.add_argument("--out", type=Path, required=True, help="where the .smtheme and its .sha256 go")
    parser.add_argument("--app-version", default=VERSION_NUMBER,
                        help=f"the SlideMage version requires_slidemage must accept (default {VERSION_NUMBER})")
    args = parser.parse_args(argv)
    try:
        asset = pack(args.folder, args.out, args.app_version)
    except themes.ThemeError as e:
        print(f"make_theme_package: {e}", file=sys.stderr)
        return 1
    print(asset)
    return 0


if __name__ == "__main__":
    sys.exit(main())
