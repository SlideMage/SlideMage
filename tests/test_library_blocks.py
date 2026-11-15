# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Block metadata edits leave the physical call list untouched."""
import pytest

from slidemage.fileio import StaleFileError
from slidemage.topic_blocks import update_metadata


def test_edit_topics_changes_only_its_header_line(tmp_path):
    path = tmp_path / "Research.tex"
    before = (b"% User note\r\n%% SlideMage block: Research\r\n"
              b"%% Topics: Old topic\r\n%% Description: Keep this text.\r\n"
              b"\r\n\\slide{abc-First} % keep comment\r\n"
              b"\\slideversion{def-Second}{1-2-0}")
    path.write_bytes(before)

    update_metadata(path, "Topics", "Literature search, Academic writing")

    assert path.read_bytes() == before.replace(
        b"%% Topics: Old topic", b"%% Topics: Literature search, Academic writing")

    with pytest.raises(StaleFileError, match="Topics changed"):
        update_metadata(path, "Topics", "Old topic, Local", expected="Old topic")
    assert b"Literature search, Academic writing" in path.read_bytes()
