"""Repeated real-title-edit benchmark on a frozen manual corpus.

Use --label before with frozen source imports, then --label after with new code.
The project must be a scratch copy: title edits are restored after each call.
"""

from __future__ import annotations

import argparse
from contextlib import nullcontext
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import time
import uuid

from experiment import (SCHEMA, EDIT_VERSION, atomic_json, bind, digest,
                        implementation_identity, observations, phases,
                        tree_hashes, validate_record, observed_rules)

import pymupdf
from slidemage import deck_editor, deck_scan, project, slide_preview, slide_language, slide_snapshot
from slidemage.preview_build import build_lock


def signature(pdf):
    with pymupdf.open(pdf) as doc:
        return [
            (
                p.rect.width,
                p.rect.height,
                hashlib.sha256(p.get_pixmap().samples).hexdigest(),
            )
            for p in doc
        ]


def edited(source, revision, id_slug=None):
    if revision == 0:
        return source, "original"
    if revision == 2:
        recipes = {
            "1sv-EN-Lists-and-Formulas": (r"{\sigma}", r"{2\sigma}", "formula"),
            "1c9-EN-Placing-Figures": ("height=4.2cm", "height=3.9cm", "graphic size"),
            "1mu-EN-Slidestep-Demo": ("Step 1, in every", "Revised step 1, in every", "overlay body"),
            "2v9-EN-Itemize-Spacing-Reference": ("First level-1 item", "Revised level-1 item", "list body"),
        }
        if id_slug in recipes:
            text, _ = edited(source, 1, id_slug)
            old, new, kind = recipes[id_slug]
            if old not in text:
                raise ValueError(f"Edit recipe no longer matches {id_slug}")
            return text.replace(old, new, 1), kind
    # Only commands whose first argument is a title; never change a media path.
    match = re.search(
        r"^\\(?:begin\{(?:standardframe|sectionframe|figureframe|sideimageframe|highlightframe|frame)\}|titleframe|quoteframe)"
        r"(?:\[[^\]\n]*\])?\{",
        source,
        re.M,
    )
    if match:
        if source.startswith(r"\quoteframe", match.start()):
            # Edit before the quote's pause so overlay 1 also visibly changes.
            return (
                source[: match.end()] + f"Edit {revision}: " + source[match.end() :],
                "quote text",
            )
        depth = 1
        pos = match.end()
        while pos < len(source) and depth:
            if source[pos] in "{}":
                depth += 1 if source[pos] == "{" else -1
            pos += 1
        if depth == 0:
            return source[: pos - 1] + f" {revision}" + source[pos - 1 :], "title text"
    if re.search(r"^\\fullbleedframe\{", source, re.M):
        # A full-bleed frame has neither title nor visible footer. Add a visible
        # graphic annotation without replacing its original image or engine.
        annotation = (
            "\\let\\SMBenchmarkFullBleedImage\\SMFullBleedImage\n"
            "\\renewcommand{\\SMFullBleedImage}[1]{\\SMBenchmarkFullBleedImage{#1}"
            "\\begin{tikzpicture}[overlay,remember picture]"
            "\\node[anchor=north west,fill=white,text=black,inner sep=4pt]"
            f" at (current page.north west) {{Preview edit {revision}}};"
            "\\end{tikzpicture}}\n"
        )
        return annotation + source, "graphic annotation"
    frame = re.search(
        r"^\\begin\{frame\}(?:\[[^\]\n]*\])?\r?\n[\t ]*[^\r\n]+", source, re.M
    )
    if frame:
        return source[: frame.end()] + f" {revision}" + source[
            frame.end() :
        ], "body text"
    raise ValueError("Cannot find a visible edit for this source")


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--label", required=True)
    parser.add_argument(
        "--configs", nargs="+", default=["saved", "buffer", "overlay", "buffer-overlay"]
    )
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--limit", type=int)
    parser.add_argument(
        "--indices",
        nargs="+",
        type=int,
        help="Remeasure selected call numbers, keeping the full manifest",
    )
    parser.add_argument("--subset-indices", nargs="+", type=int,
                        help="Immutable declared subset, including other invocations in this run")
    parser.add_argument("--time-budget", type=float, default=600)
    parser.add_argument("--deadline", type=float, help="Shared orchestrator wall-clock deadline")
    parser.add_argument("--order-seed", type=int, default=0)
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument("--no-images", action="store_true")
    parser.add_argument(
        "--defer-images",
        action="store_true",
        help="Use the new GUI prepare/publish path",
    )
    args = parser.parse_args()
    if args.repeats < 1 or args.time_budget <= 0:
        parser.error("Positive edit count and time budget required")
    if not set(args.configs) <= {"saved", "buffer", "overlay", "buffer-overlay"}:
        parser.error("Unknown preview scope")
    ctx = project.from_environment()
    root = ctx.root
    # /tmp, or the temp folder (Windows and macOS have their own)
    scratch = [Path("/tmp"), Path(tempfile.gettempdir())] + [
        Path(os.environ[name]) for name in ("TMPDIR", "TEMP", "TMP") if os.environ.get(name)]
    assert any(root.is_relative_to(folder) for folder in scratch), (
        "Use a scratch project under /tmp (or the temp folder); this benchmark makes temporary source edits"
    )
    args.output.mkdir(parents=True, exist_ok=True)
    deck = next(d for d in deck_scan.scan_decks(ctx) if d.name == "slidemage-manual")
    calls = [
        c
        for c in deck_editor.parse_slide_calls(deck)
        if not deck_editor.is_commented_out(deck.text, c)
    ][: args.limit]
    selected = sorted(set(args.subset_indices or args.indices or range(1, len(calls) + 1)))
    execution = set(args.indices or selected)
    if not execution <= set(selected) or not set(selected) <= set(range(1, len(calls) + 1)):
        parser.error("Requested indices must belong to the declared corpus subset")
    manifest = dict(
        schema=SCHEMA, selected_indices=selected, edit_version=EDIT_VERSION,
        project_inputs=tree_hashes(root),
        framework_inputs=tree_hashes(Path(slide_preview.build_env(ctx)["SLIDEMASTER_LATEX"]))
        if slide_preview.build_env(ctx).get("SLIDEMASTER_LATEX") else {},
        preamble_hash=hashlib.sha256(deck.preamble_text.encode()).hexdigest(),
        calls=[
            dict(
                slide=c.id_slug,
                macro=c.macro,
                version=c.version,
                steps=c.steps,
                sha256=hashlib.sha256(
                    (root / "slides" / c.source_filename).read_bytes()
                ).hexdigest(),
            )
            for c in calls
        ],
    )
    identity = implementation_identity(Path(slide_preview.__file__).parent,
        dict(configs=args.configs, repeats=args.repeats, no_cache=args.no_cache,
             no_images=args.no_images, defer_images=args.defer_images, order_seed=args.order_seed),
        slide_preview.build_env(ctx))
    identity["pymupdf"] = pymupdf.VersionBind
    experiment_id = digest(dict(manifest=manifest, implementation=identity))
    deadline = time.monotonic() + args.time_budget

    def stopped():
        return ((args.output / "STOP").exists() or time.monotonic() >= deadline
                or (args.deadline is not None and time.time() >= args.deadline))
    original_compile = slide_preview.compile_and_extract

    def frozen_compile(ctx, wrapper, *a, **kw):
        wrapper = wrapper.replace(
            r"\begin{document}",
            r"\begin{document}"
            + "\n"
            + slide_preview._preview_timestamp_line(True, "2026-10-11 12:00"),
            1,
        )
        if args.no_images:
            kw["snapshot_template"] = None
        return original_compile(ctx, wrapper, *a, **kw)

    slide_preview.compile_and_extract = frozen_compile
    try:
        from slidemage.preview_metrics import PreviewMetrics
    except ImportError:
        PreviewMetrics = None
    with build_lock(args.output / "benchmark.lock"):
        bind(args.output / "manifest.json", manifest)
        bind(args.output / args.label / "identity.json", identity)
        for i, call in enumerate(calls, 1):
            if i not in execution:
                continue
            configs = args.configs if (selected.index(i) + args.order_seed) % 2 == 0 else list(reversed(args.configs))
            path = root / "slides" / call.source_filename
            original = path.read_bytes()
            source = original.decode()
            try:
                for config in configs:
                    out = args.output / args.label / config / f"{i:03}"
                    if (out / "result.json").exists():
                        validate_record(json.loads((out / "result.json").read_text()),
                                        experiment_id, phases(args.repeats))
                        continue
                    if stopped():
                        return
                    attempt = uuid.uuid4().hex
                    attempt_out = out / "attempts" / attempt
                    attempt_out.mkdir(parents=True)
                    ctx = project.ProjectContext(root, root / ".build" / "benchmark-attempts" / attempt)
                    rows = []
                    previous_signature = None
                    for phase, revision in (
                        [("cold", 0)]
                        + [(f"edit-{r}", r) for r in range(1, args.repeats + 1)]
                        + [("unchanged", args.repeats)]
                    ):
                        if stopped():
                            atomic_json(attempt_out / "attempt.json", dict(
                                experiment_id=experiment_id, attempt=attempt,
                                complete=False, samples=rows))
                            return
                        body, edit_kind = edited(source, revision, call.id_slug)
                        if path.read_bytes() != body.encode():
                            path.write_bytes(body.encode())
                        logs = []
                        events = []

                        def log_line(line):
                            logs.append(line)
                            events.append((time.perf_counter(), line))
                        trace = PreviewMetrics() if PreviewMetrics else nullcontext()
                        common = dict(
                            preamble_text=deck.preamble_text,
                            frame_number=i,
                            footer_timestamp=False,
                            reuse_build=not args.no_cache,
                            overlay=1 if "overlay" in config else None,
                            log=log_line,
                        )
                        if args.defer_images:
                            common["capture_snapshot"] = False
                        start = time.perf_counter()
                        try:
                            with trace:
                                if "region" in config or "buffer" in config:
                                    text = (
                                        f"\\gdef\\SMSlideSteps{{{call.steps}}}\n"
                                        if call.steps
                                        else ""
                                    ) + body
                                    pdf = slide_preview.render_slide_text_to_pdf(ctx,
                                        call.id_slug,
                                        text,
                                        preview_mode="region"
                                        if "region" in config
                                        else "slide",
                                        **common,
                                    )
                                else:
                                    pdf = slide_preview.render_slide_to_pdf(ctx,
                                        call.macro,
                                        call.id_slug,
                                        call.version,
                                        call.conditions,
                                        steps=call.steps,
                                        **common,
                                    )
                                # The GUI includes this additional rasterization; measure it explicitly.
                                if not args.no_images:
                                    png_start = time.perf_counter()
                                    if args.defer_images:
                                        canonical = config in ("saved", "buffer")
                                        _, images = slide_snapshot.prepare_preview(
                                            pdf, canonical
                                        )
                                        if images:
                                            slide_snapshot.publish_preview(ctx,
                                                images,
                                                slide_language.bare_id(call.id_slug),
                                                slide_snapshot.detect_template(
                                                    deck.preamble_text
                                                ),
                                            )
                                    else:
                                        slide_snapshot.page_png(pdf)
                                    png_seconds = time.perf_counter() - png_start
                                else:
                                    png_seconds = 0
                            row = dict(
                                phase=phase,
                                seconds=time.perf_counter() - start,
                                gui_png_seconds=png_seconds,
                                ok=True,
                                edit_kind=edit_kind,
                                trace=trace.to_dict() if PreviewMetrics else {},
                            )
                            if not PreviewMetrics:
                                row["trace"] = dict(stages={}, rules=observed_rules(events, time.perf_counter()))
                            row["machine"] = observations()
                            shutil.copy2(pdf, attempt_out / f"{phase}.pdf")
                            shutil.copy2(pdf, out / f"{phase}.pdf")
                            shutil.rmtree(pdf.parent)
                            sig = signature(out / f"{phase}.pdf")
                            row["signature"] = sig
                            if phase.startswith("edit-"):
                                row["visible_edit"] = previous_signature is not None and sig != previous_signature
                            previous_signature = sig
                            row["pages"] = len(sig)
                            reference = (
                                args.output
                                / "before"
                                / "saved"
                                / f"{i:03}"
                                / f"{phase}.pdf"
                            )
                            if reference.exists() and args.label != "before":
                                base = signature(reference)
                                row["pixel_match"] = sig == (
                                    base[:1] if "overlay" in config else base
                                )
                                if "overlay" in config and call.steps == "3":
                                    row["pixel_match"] = None
                        except Exception as exc:
                            row = dict(
                                phase=phase,
                                seconds=time.perf_counter() - start,
                                ok=False,
                                error=str(exc),
                            )
                        (out / f"{phase}.log").write_text("\n".join(logs))
                        (attempt_out / f"{phase}.log").write_text("\n".join(logs))
                        rows.append(row)
                        atomic_json(attempt_out / "attempt.json", dict(
                            experiment_id=experiment_id, attempt=attempt,
                            complete=False, samples=rows))
                        print(
                            json.dumps(
                                dict(
                                    label=args.label,
                                    config=config,
                                    index=i,
                                    slide=call.id_slug,
                                    **row,
                                )
                            ),
                            flush=True,
                        )
                    result = dict(
                        experiment_id=experiment_id, attempt=attempt,
                        index=i, slide=call.id_slug, config=config, samples=rows
                    )
                    atomic_json(attempt_out / "attempt.json", dict(result, complete=True))
                    atomic_json(out / "result.json", result)
            finally:
                path.write_bytes(original)


if __name__ == "__main__":
    main()
