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
import sys
from pathlib import Path

# This script moved into .scripts/ (2026-09-18) but the SlideMage/ package
# it imports from still lives at the project root -- when Python runs a
# script directly, it adds only that script's own directory to sys.path,
# not the invoking cwd, so the plain "from SlideMage..." import below would
# otherwise fail to find the package once this file no longer sits next to
# it.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from SlideMage.deck_headers import regenerate_headers


def main() -> None:
    changed, n_decks = regenerate_headers()
    print(f"Updated {changed} slide file(s) across {n_decks} deck(s).")


if __name__ == "__main__":
    main()
