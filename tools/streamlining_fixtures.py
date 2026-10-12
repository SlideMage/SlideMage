"""Output fixtures for the streamlining plan (docs/STREAMLINING_BASELINE.md).

Compiles part of example/ (in a disposable copy) through the app's own compile and preview
paths and records per-page text and image hashes of each PDF in a small manifest.

    python tools/streamlining_fixtures.py            # write tests/fixtures/streamlining/manifest.json
    python tools/streamlining_fixtures.py --check    # recompile, compare with the manifest

Text hashes must match (mismatch: exit 1); image hashes are warnings. Needs TeX and PyMuPDF.
Footer timestamps are switched off in every render (footer_timestamp=False), which is what
makes the image hashes stable. Run with PYTHONPATH=src.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MANIFEST = REPO / "tests" / "fixtures" / "streamlining" / "manifest.json"
DECK = "slidemage-manual-copy"
DPI = 30
SLIDES = ["1jh-EN-Title-Slide", "tnb-DE-Title-Slide", "1ym-EN-Framework-Project-App", "1bb-EN-What-You-Need"]


def page_hashes(pdf: Path) -> dict:
    import pymupdf as fitz

    texts, images = [], []
    with fitz.open(pdf) as doc:
        for page in doc:
            texts.append(hashlib.sha256(page.get_text().encode("utf-8")).hexdigest()[:16])
            pix = page.get_pixmap(dpi=DPI, colorspace=fitz.csGRAY)
            images.append(hashlib.sha256(pix.samples).hexdigest()[:16])
    return {"pages": len(texts), "text": texts, "image": images}


def produce(copy: Path) -> dict:
    os.environ["SLIDEMASTER_PROJECT"] = str(copy)
    os.chdir(copy)
    sys.path.insert(0, str(REPO / "src"))
    from slidemage import compiler, deck_scan, slide_preview

    out: dict[str, dict] = {}
    deck = next(d for d in deck_scan.scan_decks() if d.name == DECK)
    jobs = compiler.build_jobs(deck, "instructor")
    for job in jobs:
        job.footer_timestamp = False
    log: list[str] = []
    results = compiler.run_jobs(jobs, log.append)
    if not all(results.values()):
        raise SystemExit("deck compile failed:\n" + "\n".join(log[-40:]))
    # run_job publishes the PDF in the background; wait for it to appear
    for job in jobs:
        dest = Path(*compiler.resolve_output_location(job)).with_suffix(".pdf")
        for _ in range(120):
            if dest.exists():
                break
            time.sleep(0.5)
        out[f"deck:{job.jobname}"] = page_hashes(dest)
        if os.environ.get("STREAMLINING_KEEP"):   # debugging: keep the deck PDF
            shutil.copy(dest, os.environ["STREAMLINING_KEEP"])
        if os.environ.get("STREAMLINING_KEEP"):
            shutil.copy(dest, os.environ["STREAMLINING_KEEP"])
    for slug in SLIDES:
        for reuse in (True, False):
            pdf = slide_preview.render_slide_to_pdf(
                "slide", slug, footer_timestamp=False, reuse_build=reuse, capture_snapshot=False)
            out[f"preview:{slug}:{'cached' if reuse else 'fresh'}"] = page_hashes(pdf)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    start = time.time()
    with tempfile.TemporaryDirectory(prefix="slidemage-fixture-") as tmp:
        copy = Path(tmp) / "project"
        shutil.copytree(REPO / "example", copy, ignore=shutil.ignore_patterns("*.aux", ".build", "pdf"))
        shutil.copytree(REPO / "latex", Path(tmp) / "latex")   # the framework is a sibling of the project
        result = produce(copy)
        os.chdir(tmp)
    print(f"produced {len(result)} outputs in {time.time() - start:.0f}s")
    if not args.check:
        MANIFEST.write_text(json.dumps(result, indent=1, sort_keys=True) + "\n")
        print(f"wrote {MANIFEST}")
        return 0
    expected = json.loads(MANIFEST.read_text())
    failures = 0
    for key in sorted(set(expected) | set(result)):
        old, new = expected.get(key), result.get(key)
        if old is None or new is None:
            print(f"MISSING {key}: {'not in manifest' if old is None else 'not produced'}")
            failures += 1
        elif old["pages"] != new["pages"] or old["text"] != new["text"]:
            print(f"FAIL {key}: pages {old['pages']} -> {new['pages']}, text differs")
            failures += 1
        elif old["image"] != new["image"]:
            bad = [i + 1 for i, (a, b) in enumerate(zip(old["image"], new["image"])) if a != b]
            print(f"WARN {key}: image hash differs on pages {bad}")
    print("OK" if not failures else f"{failures} mismatch(es)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
