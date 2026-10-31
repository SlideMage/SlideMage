# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Pack a citation format folder into its release asset (docs/CITATION_PACKAGE.md).

    python tools/make_citation_package.py <format folder> --out <dir>

The folder holds citation.toml, SlideMage_citation_<key>.tex, README.md, CHANGELOG.md, LICENSE and, as the format has
them, extra TeX files named SlideMage_citation_<key>_*, preview.png and LICENSES/; what starts with a dot (.git/,
.github/, .gitignore) is left out. It is checked with the rules SlideMage's "Install from file…" applies
(slidemage.citations.check_folder), so a package this writes installs. Written to <dir>: <key>-<version>.smcite (a
zip, citation.toml at its top) and <key>-<version>.smcite.sha256 in the `sha256sum` format. Files are stored in name
order with a fixed date, so the same folder gives the same bytes and the same checksum.

--app-version checks requires_slidemage against another SlideMage than this checkout's (default: version.py).
Exit 0 and the asset's path on success; exit 1 and the reason on stderr when a rule is broken.
"""
from __future__ import annotations

import argparse
import hashlib
import sys
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

from slidemage import citations  # noqa: E402
from slidemage.version import VERSION_NUMBER  # noqa: E402

FIXED_DATE = (2026, 1, 1, 0, 0, 0)


def pack(folder: Path, out_dir: Path, app_version: str = VERSION_NUMBER) -> Path:
    """Check `folder` and write its .smcite and .sha256 into `out_dir`; the .smcite's path. Raises CitationError."""
    folder = Path(folder)
    if not folder.is_dir():
        raise citations.CitationError(f"{folder} is not a folder.")
    manifest = citations.check_folder(folder, app_version, skip_hidden=True)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    asset = out_dir / citations.package_name(manifest)
    files = [name for name in citations.folder_names(folder, skip_hidden=True) if not name.endswith("/")]
    with zipfile.ZipFile(asset, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name in sorted(files, key=lambda n: (n != citations.MANIFEST_NAME, n)):     # citation.toml first
            info = zipfile.ZipInfo(name, date_time=FIXED_DATE)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            zf.writestr(info, (folder / name).read_bytes())
    digest = hashlib.sha256(asset.read_bytes()).hexdigest()
    Path(str(asset) + ".sha256").write_text(f"{digest}  {asset.name}\n", encoding="utf-8", newline="\n")
    return asset


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("folder", type=Path, help="the citation format folder (with citation.toml)")
    parser.add_argument("--out", type=Path, required=True, help="where the .smcite and its .sha256 go")
    parser.add_argument("--app-version", default=VERSION_NUMBER,
                        help=f"the SlideMage version requires_slidemage must accept (default {VERSION_NUMBER})")
    args = parser.parse_args(argv)
    try:
        asset = pack(args.folder, args.out, args.app_version)
    except citations.CitationError as e:
        print(f"make_citation_package: {e}", file=sys.stderr)
        return 1
    print(asset)
    return 0


if __name__ == "__main__":
    sys.exit(main())
