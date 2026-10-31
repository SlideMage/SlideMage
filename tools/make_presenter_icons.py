# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Render assets/presenter-icon.svg into the icon files of SlideMage Presenter's builds (docs/plans/presenter-app.md,
step 3): presenter-icon.ico (Windows, 16-256 px), presenter-icon.icns (macOS) and presenter-icon-256.png (the Linux
.desktop file). Re-run after the SVG changes; the outputs are committed:

    python tools/make_presenter_icons.py

The SVG is 392x310, so it is centred vertically on a square canvas, transparent around it. QSvgRenderer ignores
the SVG's dark-mode @media block, so the light-mode colours as written are what is drawn.
Pass --keep-pngs DIR to also keep the PNG set (16, 24, 32, 48, 64, 128, 256, 512, 1024 px) in DIR."""
from __future__ import annotations

import argparse
import io
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image  # noqa: E402
from PySide6.QtCore import QBuffer, QIODevice, QRectF, Qt  # noqa: E402
from PySide6.QtGui import QGuiApplication, QImage, QPainter  # noqa: E402
from PySide6.QtSvg import QSvgRenderer  # noqa: E402

ASSETS = Path(__file__).resolve().parents[1] / "src" / "slidemage" / "assets"
SVG = ASSETS / "presenter-icon.svg"
SIZES = (16, 24, 32, 48, 64, 128, 256, 512, 1024)
ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)
ICNS_SIZES = (16, 32, 64, 128, 256, 512, 1024)


def render(renderer: QSvgRenderer, size: int) -> Image.Image:
    """The icon on a transparent `size` x `size` canvas, aspect kept, centred."""
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    view = renderer.viewBoxF()
    scale = size / max(view.width(), view.height())
    w, h = view.width() * scale, view.height() * scale
    painter = QPainter(image)
    painter.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
    renderer.render(painter, QRectF((size - w) / 2, (size - h) / 2, w, h))
    painter.end()
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buf, "PNG")
    return Image.open(io.BytesIO(bytes(buf.data()))).convert("RGBA")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--keep-pngs", type=Path, default=None, help="also write the PNG set to this folder")
    args = parser.parse_args()
    _app = QGuiApplication.instance() or QGuiApplication(sys.argv[:1])
    renderer = QSvgRenderer(str(SVG))
    if not renderer.isValid():
        print(f"cannot read {SVG}", file=sys.stderr)
        return 1
    pngs = {size: render(renderer, size) for size in SIZES}
    if args.keep_pngs:
        args.keep_pngs.mkdir(parents=True, exist_ok=True)
        for size, image in pngs.items():
            image.save(args.keep_pngs / f"presenter-icon-{size}.png")
    pngs[256].save(ASSETS / "presenter-icon-256.png", optimize=True)
    pngs[256].save(ASSETS / "presenter-icon.ico", format="ICO", sizes=[(s, s) for s in ICO_SIZES],
                   append_images=[pngs[s] for s in ICO_SIZES if s != 256])
    pngs[1024].save(ASSETS / "presenter-icon.icns", format="ICNS",
                    append_images=[pngs[s] for s in ICNS_SIZES if s != 1024])
    for name in ("presenter-icon-256.png", "presenter-icon.ico", "presenter-icon.icns"):
        print(f"{name}: {(ASSETS / name).stat().st_size} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
