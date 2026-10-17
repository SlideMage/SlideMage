"""The shared placing of attached files (ui/workspace/attachments.py)."""
from __future__ import annotations

from types import SimpleNamespace

from PySide6.QtGui import QColor, QImage

from slidemage.ui.workspace.attachments import place_file, save_image, unique_path


def project(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    return SimpleNamespace(root=root, sources_dir=root / "sources")


def test_unique_path_counts_up_before_the_suffix(tmp_path):
    (tmp_path / "a.pdf").write_bytes(b"x")
    (tmp_path / "a-2.pdf").write_bytes(b"x")
    assert unique_path(tmp_path, "a.pdf") == tmp_path / "a-3.pdf" and unique_path(tmp_path, "b.pdf") == tmp_path / "b.pdf"


def test_place_file_copies_outside_files_and_keeps_inside_ones(tmp_path):
    p = project(tmp_path)
    outside = tmp_path / "out" / "my paper.pdf"
    outside.parent.mkdir()
    outside.write_bytes(b"one")
    inside = p.root / "slides" / "s.tex"
    inside.parent.mkdir()
    inside.write_text("x")
    assert place_file(p, outside) == "sources/my paper.pdf"
    assert place_file(p, outside, dash_spaces=True) == "sources/my-paper.pdf"
    assert place_file(p, outside, dash_spaces=True) == "sources/my-paper-2.pdf"
    assert place_file(p, inside) == "slides/s.tex"
    assert place_file(p, tmp_path / "missing.pdf") is None


def test_save_image_writes_numbered_pngs(tmp_path):
    p = project(tmp_path)
    image = QImage(4, 4, QImage.Format.Format_RGB32)
    image.fill(QColor("red"))
    assert save_image(p, image) == "sources/pasted-image.png"
    assert save_image(p, image) == "sources/pasted-image-2.png"
    assert save_image(p, QImage()) is None
