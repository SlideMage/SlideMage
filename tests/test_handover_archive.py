# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""docs/handover_archive.py: done TASKS lines go inside the archive's task-lines block, run after run."""
from __future__ import annotations

import importlib.util
from pathlib import Path

_PATH = Path(__file__).resolve().parents[1] / "docs" / "handover_archive.py"
_spec = importlib.util.spec_from_file_location("handover_archive", _PATH)
handover_archive = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(handover_archive)


def handover(path: Path, *tasks: str, section: str = "") -> Path:
    lines = "\n".join(tasks)
    path.write_text(f"# Handover\n\n<!-- TASKS:BEGIN -->\n{lines}\n<!-- TASKS:END -->\n{section}", encoding="utf-8")
    return path


def test_task_lines_land_inside_the_block_on_every_run(tmp_path):
    archive = tmp_path / "handover-archive.md"
    archive.write_text("# Archive\n", encoding="utf-8")
    one = '{"id": "one", "status": "done"}'
    two = '{"id": "two", "status": "done"}'
    section = "\n---\n\n# Second task\n\nStatus: **done.** Finished.\n"

    handover_archive.archive(handover(tmp_path / "handover.md", one))
    # the second run also archives a section, which lands after the block
    handover_archive.archive(handover(tmp_path / "handover.md", two, '{"id": "open", "status": "open"}',
                                      section=section))
    left = (tmp_path / "handover.md").read_text(encoding="utf-8")
    assert '"open"' in left and "# Second task" not in left
    handover_archive.archive(handover(tmp_path / "handover.md", '{"id": "three", "status": "archived"}'))

    text = archive.read_text(encoding="utf-8")
    block = text[text.index(handover_archive.TASK_LINES_TITLE):]
    opening = block.index("```\n") + 4
    inside = block[opening:block.index("```\n", opening)]
    assert inside.splitlines() == [one, two, '{"id": "three", "status": "archived"}']
    assert text.count("```") == 2
    assert text.index("# Second task") > text.index(handover_archive.TASK_LINES_TITLE)
