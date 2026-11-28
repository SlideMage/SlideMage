# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The terminal page (assets/terminal/terminal.js) pastes once: its key handler cancels the browser's own paste, which
xterm's listener would insert a second time (every Ctrl+V pasted twice). The page cannot run here, so the script's
source is checked."""
from __future__ import annotations

import re
from pathlib import Path

import slidemage

SCRIPT = (Path(slidemage.__file__).parent / "assets" / "terminal" / "terminal.js").read_text(encoding="utf-8")


def test_the_key_handler_cancels_the_browsers_own_paste_when_it_pastes_through_the_bridge():
    handler = SCRIPT[SCRIPT.index("function keyHandler"):SCRIPT.index("function screenLines") if "function screenLines" in SCRIPT else None]
    assert re.search(r"if \(paste\) \{\s*event\.preventDefault\(\);\s*bridge\.paste_requested\(\);\s*return false;", handler)


def test_a_paste_event_of_the_browser_never_reaches_xterm():
    line = next(line for line in SCRIPT.splitlines() if 'document.addEventListener("paste"' in line)
    assert "preventDefault()" in line and "stopPropagation()" in line and line.rstrip().endswith("true);")     # capture phase
