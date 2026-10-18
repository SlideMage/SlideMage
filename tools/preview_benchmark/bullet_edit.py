"""Compare a real editing workflow with original fresh jobs and retained state."""

from __future__ import annotations

import argparse
from contextlib import nullcontext
import hashlib
import json
import os
from pathlib import Path
import shutil
from statistics import mean
import subprocess
import sys
import time

import pymupdf

from experiment import atomic_json, implementation_identity, observed_rules, tree_hashes
from run_subset import archive, freeze

CASES = {
    "bullet": dict(index=54, slide="1sv-EN-Lists-and-Formulas", title="Edit one bullet",
        token=r"\item First level", replacements=(r"\item Edited level", r"\item Final level"),
        description="Only the first bullet text changes; the frame title stays unchanged."),
    "title": dict(index=54, slide="1sv-EN-Lists-and-Formulas", title="Change the slide title",
        token="{Lists and formulas}", replacements=("{Lists and equations}", "{Lists and symbols}"),
        description="Only the frame title changes; the bullets, formula and other content stay unchanged."),
    "formula": dict(index=54, slide="1sv-EN-Lists-and-Formulas", title="Edit a formula",
        token=r"{\sigma}", replacements=(r"{2\sigma}", r"{3\sigma}"),
        description="Only the formula denominator changes; the frame title and other content stay unchanged."),
    "figure": dict(index=58, slide="1c9-EN-Placing-Figures", title="Resize a figure",
        token="height=4.2cm", replacements=("height=3.9cm", "height=3.7cm"),
        description="Only the figure height changes; the frame title and source text stay unchanged."),
}


def revisions(case):
    return (("cold", case["token"]), ("edit-1", case["replacements"][0]),
            ("edit-2", case["replacements"][1]), ("unchanged", case["replacements"][1]))


def signature(path, width=None):
    with pymupdf.open(path) as document:
        return [(page.rect.width, page.rect.height, hashlib.sha256(page.get_pixmap(
            matrix=pymupdf.Matrix(width / page.rect.width, width / page.rect.width)
            if width else pymupdf.Matrix(1, 1)).samples).hexdigest()) for page in document]


def child(base, label, deadline, case_name):
    from slidemage import deck_editor, deck_scan, project, slide_preview, slide_language, slide_snapshot
    try:
        from slidemage.preview_metrics import PreviewMetrics
    except ImportError:
        PreviewMetrics = None
    ctx = project.from_environment()
    root = ctx.root
    deck = next(d for d in deck_scan.scan_decks(ctx) if d.name == "slidemage-manual")
    calls = [c for c in deck_editor.parse_slide_calls(deck)
             if not deck_editor.is_commented_out(deck.text, c)]
    case = CASES[case_name]
    call = calls[case["index"] - 1]
    assert call.id_slug == case["slide"], "Selected manual call identity changed"
    source = root / "slides" / call.source_filename
    original = source.read_bytes()
    assert original.count(case["token"].encode()) == 1, "Edit recipe no longer matches"
    out = base / "results" / label
    out.mkdir(parents=True)
    cached = label == "optimized"
    # The original fresh renderer requires outdir to match the project's
    # fixed latexmk aux_dir; cached builds override both directories.
    ctx = project.ProjectContext(root, root / ".build" / label if cached else root / ".build")
    identity = implementation_identity(Path(slide_preview.__file__).parent,
        dict(reuse_build=cached, deferred_images=cached, case=case_name,
             edit="typical-user-edit-v1", recipe=case), slide_preview.build_env(ctx))
    identity["pymupdf"] = pymupdf.VersionBind
    atomic_json(out / "identity.json", identity)
    compile_original = slide_preview.compile_and_extract

    def frozen_compile(wrapper, *args, **kwargs):
        return compile_original(wrapper, *args, **kwargs)

    slide_preview.compile_and_extract = frozen_compile
    samples, previous = [], None
    try:
        for phase, text in revisions(case):
            if time.time() >= deadline or (base / "results" / "STOP").exists():
                raise RuntimeError("Stopped between requests; incomplete experiment")
            body = original.replace(case["token"].encode(), text.encode())
            if source.read_bytes() != body:
                source.write_bytes(body)
            logs, events = [], []

            def log(line):
                logs.append(line)
                events.append((time.perf_counter(), line))

            trace = PreviewMetrics() if PreviewMetrics else nullcontext()
            pdf = None
            start = time.perf_counter()
            try:
                with trace:
                    pdf = slide_preview.render_slide_to_pdf(ctx, call.macro, call.id_slug,
                        call.version, call.conditions, steps=call.steps,
                        preamble_text=deck.preamble_text, frame_number=case["index"],
                        reuse_build=cached,
                        capture_snapshot=not cached, log=log)
                    if cached:
                        _, images = slide_snapshot.prepare_preview(pdf, True)
                        slide_snapshot.publish_preview(ctx, images, slide_language.bare_id(case["slide"]),
                            slide_snapshot.detect_template(deck.preamble_text))
                    else:
                        slide_snapshot.page_png(pdf)
                end = time.perf_counter()
                destination = out / f"{phase}.pdf"
                shutil.copy2(pdf, destination)
                sig = signature(destination)
                row = dict(phase=phase, seconds=end-start, ok=True,
                    signature=sig, display_signature=signature(destination, 1920),
                    trace=trace.to_dict() if PreviewMetrics else
                    dict(stages={}, rules=observed_rules(events, end)))
                if phase.startswith("edit-"):
                    row["visible_edit"] = sig != previous
                    assert row["visible_edit"], "Edit did not change pixels"
                previous = sig
                samples.append(row)
                atomic_json(out / "samples.json", samples)
                print(json.dumps(dict(label=label, phase=phase, seconds=row["seconds"])), flush=True)
            finally:
                (out / f"{phase}.log").write_text("\n".join(logs))
                if pdf is not None:
                    shutil.rmtree(pdf.parent, ignore_errors=True)
    finally:
        source.write_bytes(original)


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("--before-source", type=Path)
    parser.add_argument("--after-source", type=Path, default=Path("src"))
    parser.add_argument("--project", type=Path, default=Path("example"))
    parser.add_argument("--framework", type=Path, default=Path("latex"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--time-budget", type=float, default=90)
    parser.add_argument("--case", choices=CASES, default="bullet")
    parser.add_argument("--order", choices=("original-first", "optimized-first"), default="original-first")
    parser.add_argument("--child", choices=("original-fresh", "optimized"))
    parser.add_argument("--deadline", type=float)
    args = parser.parse_args()
    base = args.output.resolve()
    if not base.is_relative_to(Path("/tmp")):
        parser.error("Use a scratch output under /tmp")
    if args.child:
        child(base, args.child, args.deadline, args.case)
        return
    if not args.before_source or not args.report or not args.archive or args.time_budget <= 0:
        parser.error("Provide source, report, archive and a positive budget")
    if base.exists():
        parser.error("Use a new experiment directory; this short experiment does not resume")
    base.mkdir(parents=True)
    freeze(args.project, base / "project")
    freeze(args.framework, base / "framework")
    for label, source in (("original-fresh", args.before_source), ("optimized", args.after_source)):
        freeze(source, base / "sources" / label)
    freeze(Path(__file__).parent, base / "tools")
    case = CASES[args.case]
    labels = ["original-fresh", "optimized"]
    if args.order == "optimized-first":
        labels.reverse()
    atomic_json(base / "results" / "manifest.json", dict(case=args.case, recipe=case,
        revisions=revisions(case), project=tree_hashes(args.project), framework=tree_hashes(args.framework),
        order=labels, time_budget=args.time_budget))
    start = time.time()
    deadline = min(start + args.time_budget, args.deadline or float("inf"))
    for label in labels:
        env = dict(os.environ, PYTHONPATH=str(base / "sources" / label),
            SLIDEMASTER_PROJECT=str(base / "project"), SLIDEMASTER_LATEX=str(base / "framework"))
        subprocess.check_call([sys.executable, str(Path(__file__).resolve()), "--output", str(base),
            "--child", label, "--case", args.case, "--deadline", str(deadline)], env=env)
    records = {label: json.loads((base / "results" / label / "samples.json").read_text())
               for label in ("original-fresh", "optimized")}
    lines = [f"# {case['title']} — 11 October 2026", "",
        f"One frozen manual call ({case['index']}, `{case['slide']}`). {case['description']} "
        "Original fresh jobs use the preserved pre-BIG-CHANGE-2 code "
        "with build reuse disabled and its original snapshot/GUI PNG path. The current path "
        "retains latexmk state and shares prepared images. Both use the same project, framework, "
        "fixed footer annotation, warm TeX font cache and interpreter. "
        f"Ordering: {args.order}. The optimized image helper stays alive between requests.", "",
        "| Request | Original fresh job, s | Optimized, s | Speedup | Time saved |",
        "| --- | ---: | ---: | ---: | ---: |"]
    for before, after in zip(records["original-fresh"], records["optimized"], strict=True):
        assert before["phase"] == after["phase"]
        assert before["signature"] == after["signature"]
        assert before["display_signature"] == after["display_signature"]
        seconds, optimized = before["seconds"], after["seconds"]
        lines.append(f"| {before['phase']} | {seconds:.3f} | {optimized:.3f} | "
                     f"{seconds/optimized:.2f}× | {1-optimized/seconds:.1%} |")
    edits = {label: mean(s["seconds"] for s in samples if s["phase"].startswith("edit-"))
             for label, samples in records.items()}
    lines += ["", f"Mean of the two real edits: **{edits['original-fresh']:.3f} s → "
              f"{edits['optimized']:.3f} s**, **{edits['original-fresh']/edits['optimized']:.2f}×** "
              f"or **{1-edits['optimized']/edits['original-fresh']:.1%} less time**.", "",
              "All four matching PDFs pass at 72 dpi and 1920-pixel display width; all four "
              "edited PDFs visibly differ from their preceding phase. Timings include GUI image "
              "preparation and allowed snapshot writes, exclude lint/debounce/Qt paint, and represent "
              "one slide and two different edits. They do not establish a universal editing speedup. "
              "Initial builds and difficult slides with fresh fallback remain slower."]
    data = dict(complete=True, case=args.case, recipe=case, order=labels,
                records=records, edit_means=edits, wall_seconds=time.time()-start,
                pdf_matches=4, display_matches=4, visible_edits=4)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_bytes(("\n".join(lines)+"\n").replace("\n", "\r\n").encode())
    atomic_json(args.report.with_suffix(".json"), data)
    shutil.copy2(args.report, base / "results" / "summary.md")
    shutil.copy2(args.report.with_suffix(".json"), base / "results" / "summary.json")
    data["artifact"] = archive(base, args.archive)
    atomic_json(args.report.with_suffix(".json"), data)
    print(json.dumps(dict(edit_means=edits, seconds=data["wall_seconds"], complete=True)), flush=True)


if __name__ == "__main__":
    main()
