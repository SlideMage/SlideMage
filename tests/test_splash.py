# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The one-file build's splash screen must not stay in front of other windows."""
from __future__ import annotations

import sys

from slidemage import splash


def test_releasing_the_splash_is_a_no_op_without_a_splash(monkeypatch):
    monkeypatch.delitem(sys.modules, "pyi_splash", raising=False)
    splash.release_topmost()  # from source there is no pyi_splash; nothing to do, nothing raised


def test_releasing_the_splash_never_touches_windows_off_windows(monkeypatch):
    monkeypatch.setattr(splash.sys, "platform", "linux")
    splash.release_topmost()
