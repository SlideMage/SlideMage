# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Bundled fonts (Roboto, Roboto Mono, Material Icons), registered with Qt.

They ship inside the app (assets/fonts/, see README.md there for sources and
licenses) so that the look does not depend on what the machine has
installed, and so icons are plain text: Material Icons is a ligature font, so
the string "expand_more" draws the chevron glyph (verified under Qt's
offscreen platform; tests/test_ui_kit_gui.py keeps checking it).

assets/ is already copied wholesale by packaging/slidemage.spec and included
in the wheel, so nothing extra is needed for packaging.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QFontDatabase

FONT_DIR = Path(__file__).resolve().parents[2] / "assets" / "fonts"


def _font_files() -> tuple[str, ...]:
    """Every bundled font file: the static ones first, then the variable ones (named like `Roboto[wght].ttf`).
    Qt then takes a weight or style that has a static file from it, and only the others (SemiBold, ExtraLight, ...)
    from the variable font, instead of thickening or slanting a neighbouring style itself (whose overlapping
    strokes, as in w and W, then show dark gaps on Windows). A new file in the folder is picked up by itself."""
    files = sorted(path.name for path in FONT_DIR.glob("*.ttf"))
    return tuple([name for name in files if "[" not in name] + [name for name in files if "[" in name])


_FONT_FILES = _font_files()

_loaded = False


def load_fonts() -> bool:
    """Register the bundled fonts with QFontDatabase; call once after the
    QApplication exists. Safe to call again (does nothing). Returns False if
    any file failed to load, in which case Qt falls back to system fonts
    and icons show as their names."""
    global _loaded
    if _loaded:
        return True
    ok = True
    for name in _FONT_FILES:
        if QFontDatabase.addApplicationFont(str(FONT_DIR / name)) < 0:
            ok = False
    _loaded = ok
    return ok
