# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Print the FILES table of src/slidemage/spelling/catalogue.py: download every dictionary file at the pinned
commits and give its size and SHA-256. Run it after changing a commit below, and paste the output into
catalogue.py.

    python tools/spelling_pins.py

The commits:
- pyspellchecker: the commit of the tag of the version pyproject.toml pins (its word lists are left out of the
  build and downloaded instead; they are byte-identical to the ones in the PyPI wheel).
- LibreOffice dictionaries: any commit of https://github.com/LibreOffice/dictionaries; the German frami and the
  English en_GB / en_US files.
"""
from __future__ import annotations

import hashlib
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from slidemage import tls_trust  # noqa: E402
from slidemage.spelling.catalogue import (  # noqa: E402
    LIBREOFFICE_COMMIT, PYSPELLCHECKER_COMMIT, PYSPELLCHECKER_LANGUAGES, file_url, hunspell_files)


def main() -> int:
    tls_trust.inject()
    names = [f"{code}.json.gz" for code in PYSPELLCHECKER_LANGUAGES] + hunspell_files()
    print(f"# pyspellchecker {PYSPELLCHECKER_COMMIT}, LibreOffice dictionaries {LIBREOFFICE_COMMIT}")
    print("FILES: dict[str, tuple[int, str]] = {")
    for name in names:
        with urllib.request.urlopen(file_url(name), timeout=60) as response:
            data = response.read()
        print(f'    "{name}": ({len(data)}, "{hashlib.sha256(data).hexdigest()}"),')
    print("}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
