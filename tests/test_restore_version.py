# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Making a frozen version the current one again (slide_versioning.restore_version)."""
import pytest

from slidemage import slide_versioning as sv
from slidemage.slide_source import read_slide_source

HEADER = "%% Included in decks: talk\n%%\n\n"


def _slide(tmp_path, current, frozen):
    slides = tmp_path / "slides"
    (slides / ".backups").mkdir(parents=True, exist_ok=True)
    (slides / "abc-EN-Demo-current.tex").write_text(current, encoding="utf-8")
    for version, text in frozen.items():
        (slides / f"abc-EN-Demo-v{version}.tex").write_text(text, encoding="utf-8")
    return slides


@pytest.mark.parametrize("text, expected", [
    ("% \\setSlideVersion{9-9-9}\n\\setSlideVersion{1-2-3}\n", (1, 2, 3)),
    ("text % \\setSlideVersion{9-9-9}\n\\setSlideVersion{1-2-3}\n", (1, 2, 3)),
    ("% \\setSlideVersion{9-9-9}\n", None),
    ("\\% \\setSlideVersion{1-2-3}\n\\setSlideVersion{4-5-6}\n", (1, 2, 3)),
])
def test_parse_version_returns_the_first_uncommented_marker(text, expected):
    assert sv.parse_version(text) == expected


def test_marker_edits_replace_all_live_markers_and_preserve_comments():
    text = "% \\setSlideVersion{9-9-9}\n\\setSlideVersion{1-2-3}\nbody\n\\setSlideVersion{4-5-6}\n"
    assert sv.strip_marker(text) == "% \\setSlideVersion{9-9-9}\nbody\n"
    assert sv.set_marker(text, (2, 0, 0)) == "% \\setSlideVersion{9-9-9}\n\\setSlideVersion{2-0-0}\nbody\n"


def test_restore_archives_current_and_bumps_the_version(ctx, tmp_path):
    slides = _slide(tmp_path, HEADER + "\\setSlideVersion{1-1-0}\nnew text\n",
                    {"1-0-0": "%% Included in decks: stale\n%%\n\nold text\n"})
    current = slides / "abc-EN-Demo-current.tex"
    archived, version = sv.restore_version(ctx, current, "abc-EN-Demo", slides / "abc-EN-Demo-v1-0-0.tex")

    assert version == (1, 2, 0)                       # 1.1.0 is not reused
    assert archived == slides / "abc-EN-Demo-v1-1-0.tex"
    assert "new text" in archived.read_text(encoding="utf-8")
    text, _ = read_slide_source(current)
    assert "old text" in text and "new text" not in text
    assert "\\setSlideVersion{1-2-0}" in text
    assert text.startswith("%% Included in decks: talk\n")   # the current header is kept
    assert (slides / "abc-EN-Demo-v1-0-0.tex").read_text(encoding="utf-8").endswith("old text\n")


def test_restore_refuses_identical_content_and_taken_archive_name(ctx, tmp_path):
    slides = _slide(tmp_path, HEADER + "\\setSlideVersion{1-1-0}\nsame\n",
                    {"1-0-0": HEADER + "same\n"})
    current = slides / "abc-EN-Demo-current.tex"
    with pytest.raises(sv.RestoreError):
        sv.restore_version(ctx, current, "abc-EN-Demo", slides / "abc-EN-Demo-v1-0-0.tex")

    slides = _slide(tmp_path, HEADER + "\\setSlideVersion{1-1-0}\nnew\n",
                    {"1-0-0": "old\n", "1-1-0": "something else\n"})
    with pytest.raises(sv.RestoreError):
        sv.restore_version(ctx, current, "abc-EN-Demo", slides / "abc-EN-Demo-v1-0-0.tex")
    assert "new" in current.read_text(encoding="utf-8")        # nothing changed


def test_update_version_freezes_the_changed_content_as_the_next_version(ctx, tmp_path):
    slides = _slide(tmp_path, HEADER + "\\setSlideVersion{1-1-0+}\ntext\n", {"1-1-0": HEADER + "old\n"})
    current = slides / "abc-EN-Demo-current.tex"
    frozen, version, base = sv.update_version(ctx, current, "abc-EN-Demo", "major")

    assert (version, base) == ((2, 0, 0), (1, 1, 0)) and frozen == slides / "abc-EN-Demo-v2-0-0.tex"
    assert "\\setSlideVersion{2-0-0}\n" in frozen.read_text(encoding="utf-8")
    text, _ = read_slide_source(current)
    assert text == frozen.read_text(encoding="utf-8")
    assert text.startswith("%% Included in decks: talk\n") and "text\n" in text


def test_update_version_of_a_version_not_frozen_yet_freezes_it_as_it_is(ctx, tmp_path):
    slides = _slide(tmp_path, HEADER + "\\setSlideVersion{1-1-0}\ntext\n", {})
    current = slides / "abc-EN-Demo-current.tex"
    frozen, version, base = sv.update_version(ctx, current, "abc-EN-Demo", "major")
    assert version == base == (1, 1, 0) and frozen == slides / "abc-EN-Demo-v1-1-0.tex"
    with pytest.raises(ValueError, match="not changed since v1.1.0"):
        sv.update_version(ctx, current, "abc-EN-Demo", "major")


def test_update_version_treats_an_untracked_slide_as_1_0_0_and_refuses_a_taken_version(ctx, tmp_path):
    slides = _slide(tmp_path, "plain\n", {})
    current = slides / "abc-EN-Demo-current.tex"
    assert sv.update_version(ctx, current, "abc-EN-Demo", "minor")[1] == (1, 0, 0)
    assert "\\setSlideVersion{1-0-0}" in current.read_text(encoding="utf-8")
    current.write_text("\\setSlideVersion{1-0-0+}\nplain, changed\n", encoding="utf-8")
    (slides / "abc-EN-Demo-v1-0-1.tex").write_text("taken", encoding="utf-8")
    with pytest.raises(ValueError, match="frozen already"):
        sv.update_version(ctx, current, "abc-EN-Demo", "patch")


def test_save_slide_freezes_the_version_first_and_marks_the_change(ctx, tmp_path):
    slides = _slide(tmp_path, HEADER + "\\setSlideVersion{1-2-0}\nsaved the old way\n", {})
    current = slides / "abc-EN-Demo-current.tex"
    before = read_slide_source(current)[0]
    written, backup, frozen = sv.save_slide(ctx, current, before.replace("old way", "new way"), "\n", before)

    assert frozen == slides / "abc-EN-Demo-v1-2-0.tex"
    assert frozen.read_text(encoding="utf-8") == before            # the version's content is kept
    assert "\\setSlideVersion{1-2-0+}\n" in written and current.read_text(encoding="utf-8") == written
    assert backup is not None

    # Already "+": nothing more is frozen, and an edit expecting the text without the "+" still applies.
    expected = sv.without_plus(written)
    again, backup, frozen = sv.save_slide(ctx, current, expected.replace("new way", "third way"), "\n", expected,
                                          backup=False)
    assert frozen is None and backup is None and "\\setSlideVersion{1-2-0+}" in again and "third way" in again


def test_save_slide_marks_an_untracked_slide_and_leaves_other_files_alone(ctx, tmp_path):
    slides = _slide(tmp_path, "plain\n", {})
    current = slides / "abc-EN-Demo-current.tex"
    written = sv.save_slide(ctx, current, "plain, changed\n", "\n", "plain\n")[0]
    assert written == "\\setSlideVersion{1-0-0+}\nplain, changed\n"
    assert (slides / "abc-EN-Demo-v1-0-0.tex").read_text(encoding="utf-8") == "plain\n"

    deck = tmp_path / "talk.tex"
    deck.write_text("deck\n", encoding="utf-8")
    assert sv.save_slide(ctx, deck, "deck, changed\n", "\n", "deck\n")[0] == "deck, changed\n"


def test_save_slide_refuses_a_stale_file(ctx, tmp_path):
    from slidemage.slide_source import StaleFileError
    slides = _slide(tmp_path, "\\setSlideVersion{1-0-0+}\nsomeone else's\n", {})
    with pytest.raises(StaleFileError):
        sv.save_slide(ctx, slides / "abc-EN-Demo-current.tex", "mine\n", "\n", "\\setSlideVersion{1-0-0}\nmine\n")


def test_plus_helpers():
    plus, clean = "\\setSlideVersion{1-2-0+}\nx\n", "\\setSlideVersion{1-2-0}\ny\n"
    assert sv.parse_marker(plus) == ((1, 2, 0), True) and sv.version_text(plus) == "1.2.0+"
    assert sv.without_plus(plus) == "\\setSlideVersion{1-2-0}\nx\n"
    assert sv.carry_plus(plus, clean) == "\\setSlideVersion{1-2-0+}\ny\n"
    assert sv.carry_plus(clean, plus) == plus
    assert sv.strip_marker(plus) == "x\n"


def test_restore_of_a_changed_slide_archives_it_as_the_next_patch(ctx, tmp_path):
    slides = _slide(tmp_path, HEADER + "\\setSlideVersion{1-1-0+}\nnew text\n",
                    {"1-0-0": "old text\n", "1-1-0": HEADER + "\\setSlideVersion{1-1-0}\nmiddle\n"})
    current = slides / "abc-EN-Demo-current.tex"
    archived, version = sv.restore_version(ctx, current, "abc-EN-Demo", slides / "abc-EN-Demo-v1-0-0.tex")
    assert archived == slides / "abc-EN-Demo-v1-1-1.tex" and version == (1, 2, 0)
    assert "\\setSlideVersion{1-1-1}\nnew text" in archived.read_text(encoding="utf-8")
    assert "\\setSlideVersion{1-2-0}\nold text" in read_slide_source(current)[0]


def test_last_saved_sees_a_save_without_backup(ctx, tmp_path):
    from slidemage import slide_source
    slides = _slide(tmp_path, "a\n", {})
    current = slides / "abc-EN-Demo-current.tex"
    slide_source.save_slide_source(ctx, current, "b\n", "\n", expected_text="a\n", backup=False)
    assert not list((ctx.slide_backups_dir / current.name).glob("*.tex"))
    assert slide_source.last_saved(ctx, current) is not None
