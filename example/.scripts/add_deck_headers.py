#!/usr/bin/env python3
"""Maintain each slides/*-current.tex file's own "Included in decks: ..."
header comment, from what actually \\slide{}s/\\slidefinal{}s/\\slideversion{}s/
\\omitslide{}s/\\omitslideversion{}s it across every decks/*.tex file.

Referenced from README.md and CONVERSION_NOTES.md as "the next run of
add_deck_headers.py" since before this script actually existed; this is
that script. Run from the project root: `python3 .scripts/add_deck_headers.py`.

Thin wrapper over SlideMage/deck_headers.py's regenerate_headers() (the
actual logic lives there, 2026-07-23, so SlideMage's GUI can share it
too) -- see that module's own docstring for the full attribution/exclusion
rules this script follows.
"""
import os
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
# Operate on the project this script belongs to, whatever the cwd.
os.environ.setdefault("SLIDEMASTER_PROJECT", str(PROJECT))
try:
    from slidemage.deck_headers import regenerate_headers
except ImportError:
    # Not pip-installed: fall back to the package in this repo's src/.
    sys.path.insert(0, str(PROJECT.parent / "src"))
    from slidemage.deck_headers import regenerate_headers


def main() -> None:
    changed, n_decks = regenerate_headers()
    print(f"Updated {changed} slide file(s) across {n_decks} deck(s).")


if __name__ == "__main__":
    main()
