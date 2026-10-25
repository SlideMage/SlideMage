# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Pixel-regression harness for the LaTeX framework (latex/).

Compiles a configured list of decks the way the app does (latexmk + LuaLaTeX, one wrapper file per deck version that
sets \\deckversionoverride), renders every PDF page with PyMuPDF at a fixed resolution, and stores per-page pixel
hashes plus each PDF's font list. `compare` repeats the run and reports every difference.

Usage (run with the SlideMage venv):

    python tools/framework_regression.py record  CONFIG.json --out DIR [--jobs 4] [--only STEM,...]
    python tools/framework_regression.py compare CONFIG.json --out DIR [--jobs 4] [--only STEM,...]

    record   compiles everything, keeps the PDFs in DIR/baseline/ and writes DIR/baseline.json.
    compare  compiles into DIR/current/, checks against baseline.json and prints, per deck/version, failed
             compiles, page-count changes, font-list changes and the differing pages. Differing pages are
             written as DIR/diff/<key>/p<N>.png (baseline | current | highlighted difference). Exit code 1 on
             any difference, 0 when everything is identical. `--only` restricts both modes to some entries
             (matched against the entry key, e.g. "slidemage-manual@uni-graz", or its deck stem).

CONFIG.json (relative paths are relative to the config file):

    {
      "project":   "../example",        project folder (decks/, slides/, ...)
      "framework": "../latex",          framework folder, handed to the project as $SLIDEMAGE_LATEX
      "copy":      true,                compile in a copy under DIR/work/ so the source is never touched
      "copy_exclude": ["pdf", ".git"],  top-level names left out of the copy
      "versions":  ["instructor", "during-course", "after-course"],
      "dpi":       72,
      "decks": [
        {"deck": "decks/slidemage-manual.tex"},                          compiled under its own template
        {"deck": "decks/slidemage-manual.tex", "template": "uni-graz"}   \\input{SlideMage_template_<key>} swapped
      ]
    }

In-repo set (tools/framework_regression_repo.json: the manual and its sibling deck, own template and uni-graz):

    python tools/framework_regression.py record tools/framework_regression_repo.json --out <DIR>

A private project needs only its own config (absolute paths are fine) and an output folder outside the repository;
point "framework" at this checkout's latex/ folder. A project that finds the framework through ../SlideMage/latex
works unchanged, because $SLIDEMAGE_LATEX is set for every compile. $SLIDEMASTER_LATEX is set too, and a deck
that still names its template \\input{Slidemaster_preamble_<key>} is swapped the same way: that is how a project from
before the rename to SlideMage is compared with baselines recorded then.

A template override is made in the wrapper file inside the work copy; the source deck is never edited. Compiles
run in parallel (--jobs), each in its own output folder with a fixed SOURCE_DATE_EPOCH. Images, not PDF bytes,
are compared, so creation dates, ids and subset-font tags do not matter.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pymupdf

DEFAULT_VERSIONS = ("instructor", "during-course", "after-course")
DEFAULT_DPI = 72
COMPILE_TIMEOUT_SECONDS = 30 * 60
SOURCE_DATE_EPOCH = "1760000000"
FATAL_ERROR_RE = re.compile(r"^!|^\S.*:[0-9]+: ", re.MULTILINE)
# The template file names of today and of before the rename to SlideMage (when the base file shared the prefix).
TEMPLATE_INPUT_RE = re.compile(r"\\input\{(SlideMage_template_|Slidemaster_preamble_)([^}]+)\}")
OLD_NOT_TEMPLATES = {"base"}
SUBSET_TAG_RE = re.compile(r"^[A-Z]{6}\+")


# ---------------------------------------------------------------- comparison logic (no TeX needed)

def font_list(doc) -> list[str]:
    """Sorted unique "name (type)" of every font in the document, subset tags removed."""
    names = set()
    for page in doc:
        for font in page.get_fonts():
            names.add(f"{SUBSET_TAG_RE.sub('', font[3])} ({font[2]})")
    return sorted(names)


def page_hash(page, dpi: int) -> str:
    pix = page.get_pixmap(dpi=dpi, alpha=False)
    digest = hashlib.sha256(pix.samples)
    digest.update(f"{pix.width}x{pix.height}".encode())
    return digest.hexdigest()


def describe_pdf(path: Path, dpi: int) -> dict:
    with pymupdf.open(path) as doc:
        return {"pages": [page_hash(p, dpi) for p in doc], "fonts": font_list(doc)}


def compare_entry(old: dict, new: dict) -> list[str]:
    """Differences between two records of one deck/version (see describe_pdf, plus "ok"). Empty = identical."""
    if not old.get("ok") and not new.get("ok"):
        return []                      # failed before and now: nothing to compare
    if old.get("ok") != new.get("ok"):
        return [f"compile ok: {old.get('ok')} -> {new.get('ok')}"]
    problems = []
    old_pages, new_pages = old["pages"], new["pages"]
    if len(old_pages) != len(new_pages):
        problems.append(f"page count {len(old_pages)} -> {len(new_pages)}")
    if old["fonts"] != new["fonts"]:
        gone = sorted(set(old["fonts"]) - set(new["fonts"]))
        added = sorted(set(new["fonts"]) - set(old["fonts"]))
        problems.append(f"fonts changed: -{gone} +{added}")
    changed = differing_pages(old_pages, new_pages)
    if changed:
        problems.append("pages differ: " + ", ".join(map(str, changed)))
    return problems


def differing_pages(old_pages: list[str], new_pages: list[str]) -> list[int]:
    """1-based numbers of the pages present in both whose hashes differ."""
    return [i + 1 for i, (a, b) in enumerate(zip(old_pages, new_pages)) if a != b]


# ---------------------------------------------------------------- configuration

class Entry:
    def __init__(self, deck: Path, template: str | None, version: str):
        self.deck, self.template, self.version = deck, template, version
        self.group = f"{deck.stem}@{template}" if template else deck.stem
        self.key = f"{self.group}-{version}"

    def matches(self, only: set[str] | None) -> bool:
        return not only or self.group in only or self.deck.stem in only


def load_config(path: Path) -> dict:
    cfg = json.loads(path.read_text(encoding="utf-8"))
    base = path.parent
    cfg["project"] = (base / cfg["project"]).resolve()
    cfg["framework"] = (base / cfg["framework"]).resolve()
    cfg.setdefault("copy", False)
    cfg.setdefault("copy_exclude", [])
    cfg.setdefault("versions", list(DEFAULT_VERSIONS))
    cfg.setdefault("dpi", DEFAULT_DPI)
    return cfg


def entries_of(cfg: dict, project: Path, only: set[str] | None) -> list[Entry]:
    out = []
    for item in cfg["decks"]:
        for version in cfg["versions"]:
            entry = Entry(project / item["deck"], item.get("template"), version)
            if entry.matches(only):
                out.append(entry)
    return out


def prepare_project(cfg: dict, out: Path) -> Path:
    """The folder to compile in: the project itself, or a refreshed copy under out/work."""
    if not cfg["copy"]:
        return cfg["project"]
    work = out / "work" / cfg["project"].name
    skip = set(cfg["copy_exclude"])
    work.mkdir(parents=True, exist_ok=True)
    for src in cfg["project"].iterdir():
        if src.name in skip:
            continue
        dst = work / src.name
        if src.is_dir():
            shutil.copytree(src, dst, dirs_exist_ok=True,
                            ignore=lambda d, names: [n for n in names if n == "__pycache__"])
        else:
            shutil.copy2(src, dst)
    return work


# ---------------------------------------------------------------- compiling

def wrapper_text(entry: Entry, deck_text: str | None) -> str:
    lines = [f"\\def\\deckversionoverride{{{entry.version}}}"]
    if deck_text is None:
        lines.append(f"\\input{{{entry.deck.name}}}")
    else:
        lines.append(deck_text)
    return "\n".join(lines) + "\n"


def swapped_deck_text(entry: Entry) -> str | None:
    if not entry.template:
        return None
    text = entry.deck.read_text(encoding="utf-8", errors="replace")
    for match in TEMPLATE_INPUT_RE.finditer(text):
        prefix, key = match.groups()
        if prefix == "SlideMage_template_" or key not in OLD_NOT_TEMPLATES:
            return text[:match.start()] + f"\\input{{{prefix}{entry.template}}}" + text[match.end():]
    raise ValueError(f"{entry.deck.name}: no \\input{{SlideMage_template_<template>}} to swap")


def compile_entry(entry: Entry, project: Path, framework: Path, run_dir: Path) -> dict:
    """Compile one deck/version; leave the PDF as run_dir/<key>.pdf. Returns {"ok", "seconds", ...}."""
    started = time.time()
    build = run_dir / "build" / entry.key
    shutil.rmtree(build, ignore_errors=True)
    build.mkdir(parents=True)
    jobname = f"regr-{entry.key}".replace("@", "_").replace("#", "_")
    wrapper = entry.deck.parent / f"_regr_{jobname}.tex"
    try:
        text = swapped_deck_text(entry)
    except ValueError as error:
        return {"ok": False, "error": str(error), "seconds": 0}
    wrapper.write_text(wrapper_text(entry, text), encoding="utf-8", newline="")
    env = dict(os.environ, SLIDEMAGE_LATEX=str(framework), SLIDEMASTER_LATEX=str(framework),
               SOURCE_DATE_EPOCH=SOURCE_DATE_EPOCH,
               FORCE_SOURCE_DATE="1")
    out = build.as_posix()
    cmd = ["latexmk", "-f", f"-jobname={jobname}", f"-outdir={out}", f"-auxdir={out}",
           wrapper.relative_to(project).as_posix()]
    timed_out, passes = False, 0
    try:
        proc = subprocess.run(cmd, cwd=project, env=env, capture_output=True, text=True, errors="replace",
                              timeout=COMPILE_TIMEOUT_SECONDS)
        passes = len(re.findall(r"Run number \d+ of rule 'lualatex'", proc.stdout + proc.stderr))
    except subprocess.TimeoutExpired:
        timed_out = True
    finally:
        wrapper.unlink(missing_ok=True)
    log, pdf = build / f"{jobname}.log", build / f"{jobname}.pdf"
    log_text = log.read_text(encoding="utf-8", errors="replace") if log.is_file() else ""
    fatal = not log_text or bool(FATAL_ERROR_RE.search(log_text))
    ok = pdf.is_file() and pdf.stat().st_size > 0 and not fatal and not timed_out
    result = {"ok": ok, "seconds": round(time.time() - started, 1), "passes": passes}
    if timed_out:
        result["error"] = "timed out"
    if pdf.is_file() and pdf.stat().st_size > 0:
        shutil.copy2(pdf, run_dir / f"{entry.key}.pdf")
    if not ok:
        shutil.copy2(log, run_dir / f"{entry.key}.log") if log.is_file() else None
    shutil.rmtree(build, ignore_errors=True)
    return result


def run_all(entries: list[Entry], project: Path, framework: Path, run_dir: Path, dpi: int, jobs: int) -> dict:
    run_dir.mkdir(parents=True, exist_ok=True)
    results: dict[str, dict] = {}
    started = time.time()
    print(f"Compiling {len(entries)} deck/version pairs, {jobs} at a time...", flush=True)

    def work(entry: Entry) -> tuple[str, dict]:
        result = compile_entry(entry, project, framework, run_dir)
        pdf = run_dir / f"{entry.key}.pdf"
        if result["ok"]:
            try:
                result.update(describe_pdf(pdf, dpi))
            except Exception as error:      # unreadable PDF counts as a failed compile
                result.update(ok=False, error=f"unreadable PDF: {error}")
        return entry.key, result

    with ThreadPoolExecutor(jobs) as pool:
        futures = [pool.submit(work, e) for e in entries]
        for done, future in enumerate(as_completed(futures), 1):
            key, result = future.result()
            results[key] = result
            pages = f", {len(result['pages'])} pp" if result.get("ok") else ""
            print(f"  [{done}/{len(entries)}] {'OK  ' if result['ok'] else 'FAIL'} {key}{pages} "
                  f"({result['seconds']}s, {time.time() - started:.0f}s elapsed)", flush=True)
    return results


# ---------------------------------------------------------------- diff images

def write_diff_images(old_pdf: Path, new_pdf: Path, pages: list[int], dest: Path, dpi: int) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    with pymupdf.open(old_pdf) as old, pymupdf.open(new_pdf) as new:
        for number in pages:
            a = old[number - 1].get_pixmap(dpi=dpi, alpha=False)
            b = new[number - 1].get_pixmap(dpi=dpi, alpha=False)
            width, height = min(a.width, b.width), min(a.height, b.height)
            marked = bytearray(b"\xff" * (width * height * 3))
            pa, pb, n = a.samples, b.samples, 3
            for y in range(height):
                for x in range(width):
                    i, j = (y * a.width + x) * n, (y * b.width + x) * n
                    if pa[i:i + n] != pb[j:j + n]:
                        k = (y * width + x) * n
                        marked[k:k + n] = b"\xff\x00\x00"
            diff = pymupdf.Pixmap(pymupdf.csRGB, width, height, bytes(marked), False)
            sheet = pymupdf.open()
            page = sheet.new_page(width=width * 3, height=height)
            for slot, pix in enumerate((a, b, diff)):
                page.insert_image(pymupdf.Rect(slot * width, 0, (slot + 1) * width, height), pixmap=pix)
            sheet[0].get_pixmap(dpi=72).save(dest / f"p{number}.png")
            sheet.close()


# ---------------------------------------------------------------- main

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Framework pixel regression: record a baseline, compare against it.")
    parser.add_argument("mode", choices=("record", "compare"))
    parser.add_argument("config", type=Path)
    parser.add_argument("--out", type=Path, required=True, help="folder for baseline, current run and diffs")
    parser.add_argument("--jobs", type=int, default=4)
    parser.add_argument("--only", help="comma-separated entry keys or deck stems")
    args = parser.parse_args(argv)

    cfg = load_config(args.config)
    out = args.out.resolve()
    only = set(args.only.split(",")) if args.only else None
    project = prepare_project(cfg, out)
    entries = entries_of(cfg, project, only)
    started = time.time()
    baseline_path = out / "baseline.json"

    if args.mode == "record":
        run_dir = out / "baseline"
        results = run_all(entries, project, cfg["framework"], run_dir, cfg["dpi"], args.jobs)
        data = json.loads(baseline_path.read_text()) if baseline_path.is_file() else {"entries": {}}
        data.update(dpi=cfg["dpi"])
        data["entries"].update(results)
        baseline_path.write_text(json.dumps(data, indent=1, sort_keys=True), encoding="utf-8")
        failed = [k for k, r in results.items() if not r["ok"]]
        pages = sum(len(r.get("pages", [])) for r in results.values())
        print(f"Recorded {len(results)} entries, {pages} pages, {len(failed)} failed compiles "
              f"in {time.time() - started:.0f}s -> {baseline_path}")
        for key in failed:
            print(f"  FAILED (recorded as failed): {key}: {results[key].get('error', 'see log')}")
        return 0

    if not baseline_path.is_file():
        print(f"No baseline at {baseline_path}; run record first.", file=sys.stderr)
        return 2
    baseline = json.loads(baseline_path.read_text())
    dpi = baseline.get("dpi", cfg["dpi"])
    run_dir = out / "current"
    results = run_all(entries, project, cfg["framework"], run_dir, dpi, args.jobs)
    shutil.rmtree(out / "diff", ignore_errors=True)
    # Compiles that run side by side now and then come out different from the same input (seen in 2 of 5 full
    # private-set runs, always test-after-course: the Top Margin / biber reruns settle differently under load).
    # A difference only counts when it also shows in a rerun of that entry alone.
    suspects = [e for e in entries if e.key in baseline["entries"]
                and compare_entry(baseline["entries"][e.key], results[e.key])]
    if suspects:
        print(f"\n{len(suspects)} entries differ; recompiling them one at a time to rule out a load-dependent compile.")
        results.update(run_all(suspects, project, cfg["framework"], run_dir, dpi, 1))
    print("\nComparing against baseline:")
    different = 0
    for entry in entries:
        old, new = baseline["entries"].get(entry.key), results[entry.key]
        if old is None:
            print(f"  NEW   {entry.key}: not in the baseline")
            different += 1
            continue
        problems = compare_entry(old, new)
        if not problems:
            if entry in suspects:
                print(f"  FLAKY {entry.key}: differed in the parallel run, identical when recompiled alone")
            continue
        different += 1
        print(f"  DIFF  {entry.key}: " + "; ".join(problems))
        pages = differing_pages(old.get("pages", []), new.get("pages", []))
        if pages:
            write_diff_images(out / "baseline" / f"{entry.key}.pdf", run_dir / f"{entry.key}.pdf",
                              pages[:40], out / "diff" / entry.key, dpi)
    total_pages = sum(len(r.get("pages", [])) for r in results.values())
    print(f"\n{len(entries)} entries, {total_pages} pages, {different} with differences, "
          f"{time.time() - started:.0f}s." + (f" Diff images in {out / 'diff'}" if different else " All identical."))
    return 1 if different else 0


if __name__ == "__main__":
    sys.exit(main())
