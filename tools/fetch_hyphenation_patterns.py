# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Fetch the hyphenation patterns SlideMage ships in latex/hyphenation/ (v0.13.37).

A slide hyphenates in its language (SlideMage_base.tex, \\SM@hyphenation@load), with the hyph-utf8 patterns found
first in latex/hyphenation/ and only then in the TeX installation: shipped, they work without the distribution's
language packages and break the same on every machine. This tool downloads the .pat.txt and .hyp.txt files of the
languages in SlideMage_base.tex's table from one tagged release of hyph-utf8 (TAG), and writes NOTICES.txt with
each file's original header (its copyright and licence; the .txt files carry none, and MIT and the custom licences
ask for the notice to travel with the file).

LICENCES is the licence SlideMage distributes each file under, one of the file's own: where a file offers a choice,
MIT, else LPPL 1.3c through the file's "or later". Romanian is left out: its header says "licence: [None]". A new
language needs its row here, in SlideMage_base.tex's table and in REUSE.toml.

usage: python tools/fetch_hyphenation_patterns.py [--out latex/hyphenation]
"""
from __future__ import annotations

import argparse
import urllib.error
import urllib.request
from pathlib import Path

TAG = "CTAN-2024.12.31"
BASE = f"https://raw.githubusercontent.com/hyphenation/tex-hyphen/{TAG}/hyph-utf8/tex/generic/hyph-utf8/patterns"

LICENCES = {
    "de-1996": "MIT", "fr": "MIT", "es": "MIT", "nl": "MIT", "lt": "MIT", "da": "MIT", "el-monoton": "MIT",
    "it": "MIT", "sl": "MIT", "uk": "MIT", "pl": "MIT", "ga": "MIT", "hi": "MIT", "et": "MIT",
    "ca": "LPPL-1.3c+", "hr": "LPPL-1.3c+", "sh-cyrl": "LPPL-1.3c+", "tr": "LPPL-1.3c+", "ru": "LPPL-1.3c+",
    "sv": "LPPL-1.3c+", "is": "LPPL-1.3c+", "th": "LPPL-1.3c+",
    "cs": "GPL-2.0-or-later", "sk": "GPL-2.0-or-later", "lv": "GPL-2.0-or-later",
    "id": "GPL-2.0-only", "hu": "GPL-2.0-only",
    "pt": "BSD-3-Clause", "gl": "Unlicense",
    "bg": "LicenseRef-hyph-bg", "eu": "LicenseRef-hyph-eu", "fi": "LicenseRef-hyph-fi", "nb": "LicenseRef-hyph-nb",
}


def fetch(url: str) -> bytes | None:
    try:
        with urllib.request.urlopen(url, timeout=60) as response:
            return response.read()
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return None
        raise


def header(tex: str) -> str:
    """The leading comment block of a hyph-*.tex file, without the comment signs."""
    lines = []
    for line in tex.splitlines():
        if not line.startswith("%"):
            break
        lines.append(line[1:].rstrip())
    return "\n".join(lines).strip("\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=Path(__file__).resolve().parents[1] / "latex" / "hyphenation")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    notices = [f"Hyphenation patterns from hyph-utf8 ({TAG}, https://github.com/hyphenation/tex-hyphen), as SlideMage\n"
               "ships them in this folder. Each file is distributed under the licence named before its notice; the\n"
               "notice is the original file's header, unchanged.\n"]
    for name, licence in LICENCES.items():
        patterns = fetch(f"{BASE}/txt/hyph-{name}.pat.txt")
        tex = fetch(f"{BASE}/tex/hyph-{name}.tex")
        if patterns is None or tex is None:
            raise SystemExit(f"hyph-{name}: not in {TAG}")
        (args.out / f"hyph-{name}.pat.txt").write_bytes(patterns)
        files = [f"hyph-{name}.pat.txt"]
        exceptions = fetch(f"{BASE}/txt/hyph-{name}.hyp.txt")
        if exceptions is not None:
            (args.out / f"hyph-{name}.hyp.txt").write_bytes(exceptions)
            files.append(f"hyph-{name}.hyp.txt")
        notices.append(f"{'=' * 100}\n{', '.join(files)}: {licence}\n{'=' * 100}\n{header(tex.decode('utf-8'))}\n")
        print(f"{', '.join(files)}: {licence}")
    (args.out / "NOTICES.txt").write_text("\n".join(notices), encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
