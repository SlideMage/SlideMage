# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The Preview's width does not depend on what it shows."""

from slidemage.ui.kit.tokens import LIGHT
from slidemage.ui.workspace.preview_view import PAGE_MIN_WIDTH, TITLE_MAX, PageView, shortened


def test_the_preview_has_a_minimum_width_and_shortens_long_titles(qapp):
    assert PageView(lambda: LIGHT).minimumWidth() == PAGE_MIN_WIDTH
    cut = shortened("Long preview title " * TITLE_MAX)
    assert len(cut) <= TITLE_MAX and cut.endswith("…")
    assert shortened("Main results") == "Main results"
