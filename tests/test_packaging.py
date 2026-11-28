# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The release build carries what the app starts at run time (packaging/slidemage.spec)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

SPEC = Path(__file__).resolve().parents[1] / "packaging" / "slidemage.spec"


@pytest.mark.skipif(sys.platform != "win32", reason="pywinpty is the Windows terminal")
def test_the_windows_build_bundles_pywinpty_s_helpers():
    """Without OpenConsole.exe the Claude Code terminal's program got a console closed at once and ended before
    printing anything, exit code -1073741510 (v8.58.0)."""
    hooks = pytest.importorskip("PyInstaller.utils.hooks")
    names = {Path(source).name for source, _dest in hooks.collect_data_files("winpty", includes=["*.exe"])}
    assert {"OpenConsole.exe", "winpty-agent.exe"} <= names
    spec = SPEC.read_text(encoding="utf-8")
    assert 'collect_data_files("winpty", includes=["*.exe"])' in spec and "*WINPTY_HELPERS," in spec
