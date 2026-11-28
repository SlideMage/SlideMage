# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The Preview's version buttons: the version each makes, the signals, the hints."""

from slidemage.ui.kit.tokens import LIGHT
from slidemage.ui.workspace.version_bar import ARROW, VersionBar, VersionState


def test_the_buttons_show_versions_emit_requests_and_follow_state(qapp):
    bar = VersionBar(lambda: LIGHT)
    got = []
    bar.revert_requested.connect(lambda s: got.append(("revert", s)))
    bar.overwrite_requested.connect(lambda s: got.append(("overwrite", s)))
    bar.level_requested.connect(lambda s, level: got.append((level, s)))
    bar.new_slide_requested.connect(lambda s: got.append(("new", s)))
    bar.set_state(VersionState("aaa-EN-x", "1.2.3", True))
    buttons = bar._revert, bar._overwrite, *bar._levels.values(), bar._new
    for button in buttons:
        assert button.toolTip()
        button.click()
    assert got == [("revert", "aaa-EN-x"), ("overwrite", "aaa-EN-x"), ("patch", "aaa-EN-x"),
                   ("minor", "aaa-EN-x"), ("major", "aaa-EN-x"), ("new", "aaa-EN-x")]
    for (level, button), (version, digit) in zip(bar._levels.items(),
                                                 [("1.2.4", "4"), ("1.3.0", "3"), ("2.0.0", "2")], strict=True):
        assert f"v{version}" in button.toolTip(), level
        assert f'<span style="color:{LIGHT.info}">{digit}{ARROW}</span>' in button._label.text()
    bar.set_state(VersionState("aaa-EN-x", "1.0.0", False, "No changes since v1.0.0."))
    assert all(not button.isEnabled() for button in buttons)
    assert bar._overwrite.toolTip() == "No changes since v1.0.0."
    bar.set_state(None)
    assert bar.isHidden()
