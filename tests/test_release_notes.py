# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
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


def test_bundled_versions_are_all_listed_and_checked(capsys):
    # v5.4.0 is the first release after v4.1.0: v5.0.0 .. v5.4.0 all go into
    # the notes, and their BREAKING: paragraphs satisfy the major-bump check
    entries = release_notes.entries_since("v5.4.0", "v4.1.0")
    assert [v for v, _ in entries] == ["v5.4.0", "v5.3.0", "v5.2.0", "v5.1.0", "v5.0.0"]
    assert release_notes.main(["v5.4.0", "--previous", "v4.1.0"]) == 0
    out = capsys.readouterr().out
    assert "## v5.0.0" in out and "## v5.4.0" in out and "BREAKING:" in out


def _entry(v, paragraphs, summary="", news=()):
    from slidemage import version
    return version.HistoryEntry(version=v, meta="", description=" ".join(paragraphs),
                                paragraphs=list(paragraphs), summary=summary, news=list(news))


def test_new_paragraph_gives_summary_and_bullets():
    # v5.35.4: a NEW: paragraph -- summary on its line, "- " bullets, wrapped
    # lines continue the bullet before them
    from slidemage import version
    summary, news = version._parse_news(
        "NEW: Faster compiles.\n- Only some pages\n  can be compiled.\n- A fix.")
    assert summary == "Faster compiles."
    assert news == ["Only some pages can be compiled.", "A fix."]


def test_release_lists_every_versions_bullets_then_breaking_then_changelog():
    from slidemage import updater
    entries = [
        _entry("v6.1.0", ["Technical.", "NEW: Two things.", "BREAKING: decks need X."],
               summary="Two things.", news=["Feature B."]),
        _entry("v6.0.1", ["Technical."], news=["Fix A."]),
    ]
    out = release_notes.render("v6.1.0", "v6.0.0", entries)
    assert out == (
        "Two things.\n\n"
        "*This release covers v6.0.1 and v6.1.0.*\n\n"
        "- Feature B.\n- Fix A.\n\n"
        "## Breaking changes\n\n- **v6.1.0:** decks need X.\n\n"
        "## Full changelog\n\nhttps://github.com/stpalan/SlideMage/compare/v6.0.0...v6.1.0\n"
    )
    # the updater sees exactly the breaking change, not the changelog link
    release = updater.Release(tag="v6.1.0", body=out, **{
        k: None for k in updater.Release.__dataclass_fields__ if k not in ("tag", "body")})
    assert updater.breaking_notes(release) == ["- **v6.1.0:** decks need X."]


def test_release_without_new_paragraph_is_refused(capsys, monkeypatch):
    # only versions after v8.2.1 need the paragraph; 5.35.4 .. 8.2.1 are exempt
    entries = [_entry("v8.3.1", ["Technical only."])]
    assert release_notes.missing_news(entries) == ["v8.3.1"]
    for old in ("v5.35.3", "v5.36.0", "v6.0.0", "v8.2.1"):
        assert release_notes.missing_news([_entry(old, ["Old style."])]) == []
    monkeypatch.setattr(release_notes, "history_since", lambda tag, prev: entries)
    monkeypatch.setattr(release_notes, "notes_for", lambda tag: ["Technical only."])
    assert release_notes.main(["v8.3.1", "--previous", "v8.3.0"]) == 3
    assert "no NEW: paragraph" in capsys.readouterr().err


def test_current_release_has_a_new_paragraph():
    # the running version's own entry carries the NEW: paragraph (v8.3.0 on)
    from slidemage import version
    entry = next(e for e in version.parse_history() if e.version == version.VERSION_NUMBER)
    assert entry.news and entry.summary
