"""packaging/release_notes.py: the BREAKING: marker is required for a major bump."""
from __future__ import annotations

import importlib.util
from pathlib import Path

_PATH = Path(__file__).resolve().parents[1] / "packaging" / "release_notes.py"
_spec = importlib.util.spec_from_file_location("release_notes", _PATH)
release_notes = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(release_notes)


def test_major_bump_needs_a_breaking_paragraph():
    plain = ["New feature."]
    marked = ["New feature.", "BREAKING: projects need a new format."]
    assert release_notes.check("v5.0.0", "v4.3.1", plain)
    assert release_notes.check("v5.0.0", "v4.3.1", marked) == []
    assert release_notes.check("v4.4.0", "v4.3.1", plain) == []
    assert release_notes.check("v4.4.0", None, plain) == []  # first release


def test_notes_come_from_the_version_history(capsys):
    assert release_notes.main(["v3.41.1", "--previous", "v3.41.0"]) == 0
    assert "BANNED_WORDS" in capsys.readouterr().out
    assert release_notes.main(["v0.0.1", "--previous", "v0.0.0"]) == 1
