# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""`slidemage --self-test`: what the release workflow runs on every build before it is published."""
from __future__ import annotations

import subprocess
import sys


def test_self_test_imports_the_window_modules_and_exits_cleanly():
    done = subprocess.run([sys.executable, "-c", "from slidemage.cli import main; main(['--self-test'])"],
                          capture_output=True, text=True, timeout=300)
    assert done.returncode == 0, done.stderr[-2000:]
    assert "SlideMage self-test: ok" in done.stdout
