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


@pytest.fixture(autouse=True)
def _backup_root(tmp_path, monkeypatch):
    from slidemage import slide_source
    monkeypatch.setattr(slide_source, "PROJECT_ROOT", tmp_path)


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


def test_restore_archives_current_and_bumps_the_version(tmp_path):
    slides = _slide(tmp_path, HEADER + "\\setSlideVersion{1-1-0}\nnew text\n",
                    {"1-0-0": "%% Included in decks: stale\n%%\n\nold text\n"})
    current = slides / "abc-EN-Demo-current.tex"
    archived, version = sv.restore_version(current, "abc-EN-Demo", slides / "abc-EN-Demo-v1-0-0.tex")

    assert version == (1, 2, 0)                       # 1.1.0 is not reused
    assert archived == slides / "abc-EN-Demo-v1-1-0.tex"
    assert "new text" in archived.read_text(encoding="utf-8")
    text, _ = read_slide_source(current)
    assert "old text" in text and "new text" not in text
    assert "\\setSlideVersion{1-2-0}" in text
    assert text.startswith("%% Included in decks: talk\n")   # the current header is kept
    assert (slides / "abc-EN-Demo-v1-0-0.tex").read_text(encoding="utf-8").endswith("old text\n")


def test_restore_refuses_identical_content_and_taken_archive_name(tmp_path):
    slides = _slide(tmp_path, HEADER + "\\setSlideVersion{1-1-0}\nsame\n",
                    {"1-0-0": HEADER + "same\n"})
    current = slides / "abc-EN-Demo-current.tex"
    with pytest.raises(sv.RestoreError):
        sv.restore_version(current, "abc-EN-Demo", slides / "abc-EN-Demo-v1-0-0.tex")

    slides = _slide(tmp_path, HEADER + "\\setSlideVersion{1-1-0}\nnew\n",
                    {"1-0-0": "old\n", "1-1-0": "something else\n"})
    with pytest.raises(sv.RestoreError):
        sv.restore_version(current, "abc-EN-Demo", slides / "abc-EN-Demo-v1-0-0.tex")
    assert "new" in current.read_text(encoding="utf-8")        # nothing changed


def test_freeze_current_keeps_the_content_and_moves_the_slide_on(tmp_path):
    slides = _slide(tmp_path, HEADER + "\\setSlideVersion{1-1-0}\ntext\n", {})
    current = slides / "abc-EN-Demo-current.tex"
    frozen, version = sv.freeze_current(current, "abc-EN-Demo", "major")

    assert version == (2, 0, 0) and frozen == slides / "abc-EN-Demo-v1-1-0.tex"
    assert "\\setSlideVersion{1-1-0}" in frozen.read_text(encoding="utf-8")
    text, _ = read_slide_source(current)
    assert "\\setSlideVersion{2-0-0}" in text and text.startswith("%% Included in decks: talk\n") and "text\n" in text


def test_freeze_current_treats_an_untracked_slide_as_1_0_0_and_refuses_a_taken_version(tmp_path):
    slides = _slide(tmp_path, "plain\n", {})
    current = slides / "abc-EN-Demo-current.tex"
    assert sv.freeze_current(current, "abc-EN-Demo", "minor")[1] == (1, 1, 0)
    (slides / "abc-EN-Demo-v1-1-0.tex").write_text("taken", encoding="utf-8")
    with pytest.raises(ValueError, match="already frozen"):
        sv.freeze_current(current, "abc-EN-Demo", "patch")
