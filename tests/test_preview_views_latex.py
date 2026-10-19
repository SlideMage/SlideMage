# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Opt-in real engine gate; regular tests cover the same branches without TeX."""
import os
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.skipif(os.environ.get('SLIDEMAGE_REAL_LATEX') != '1',
                    reason='set SLIDEMAGE_REAL_LATEX=1 to run real LuaLaTeX acceptance fixtures')
def test_real_latex_views_and_invalidation(tmp_path):
    script = Path(__file__).resolve().parents[1] / 'tools' / 'preview_benchmark' / 'views.py'
    result = subprocess.run([sys.executable, str(script), '--output', str(tmp_path / 'evidence')],
                            capture_output=True, text=True, timeout=600)
    assert result.returncode == 0, result.stdout + result.stderr
