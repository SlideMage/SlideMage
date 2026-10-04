"""Compile tools/manual/illustrations.tex and split its pages into the
SlideMage manual's media files (example/media/). Rerun after editing the
illustrations; vector PDFs, one page each. Name files to write only those
(the others keep their bytes, so their image descriptions stay current).

    python tools/manual/make_illustrations.py [illustration-bar-chart.pdf ...]
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

import fitz  # PyMuPDF

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
MEDIA = REPO / "example" / "media"
PAGES = [
    "illustration-slidemage-splash.pdf",
    "illustration-slide-stack-portrait.pdf",
    "chapter-logo-building-blocks.pdf",
    "illustration-bar-chart.pdf",
]


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        env = dict(os.environ)
        env["TEXINPUTS"] = os.pathsep.join([str(REPO / "latex"), env.get("TEXINPUTS", "")])
        result = subprocess.run(
            ["lualatex", "-interaction=nonstopmode", "-halt-on-error",
             f"-output-directory={tmp}", str(HERE / "illustrations.tex")],
            cwd=HERE, env=env, capture_output=True, text=True, errors="replace")
        pdf = Path(tmp) / "illustrations.pdf"
        if result.returncode != 0 or not pdf.is_file():
            print(result.stdout[-3000:])
            return 1
        doc = fitz.open(pdf)
        if len(doc) != len(PAGES):
            print(f"expected {len(PAGES)} pages, got {len(doc)}")
            return 1
        MEDIA.mkdir(parents=True, exist_ok=True)
        wanted = set(sys.argv[1:]) or set(PAGES)
        for index, name in enumerate(PAGES):
            if name not in wanted:
                continue
            out = fitz.open()
            out.insert_pdf(doc, from_page=index, to_page=index)
            out.save(MEDIA / name, garbage=4, deflate=True)
            out.close()
            print(MEDIA / name)
        doc.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
