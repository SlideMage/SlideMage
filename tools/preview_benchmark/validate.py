"""Live TeX correctness checks on a scratch project, outside timed benchmarks."""

import argparse
import json
from pathlib import Path
import shutil

import pymupdf
from slidemage import deck_scan, project, slide_preview
from slidemage.preview_metrics import PreviewMetrics


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    ctx = project.from_environment()
    root = ctx.root
    assert root.is_relative_to(Path("/tmp")), "Use a scratch project"
    args.output.mkdir(parents=True, exist_ok=True)
    deck = next(d for d in deck_scan.scan_decks(ctx) if d.name == "slidemage-manual")
    ctx = project.ProjectContext(root, root / ".build" / "validation")
    results = []

    def render(name, body, preamble=None, **options):
        logs = []
        with PreviewMetrics() as trace:
            pdf = slide_preview.render_slide_text_to_pdf(ctx,
                "zz1-EN-PreviewValidation",
                body,
                preamble_text=preamble or deck.preamble_text,
                footer_timestamp=options.pop("footer_timestamp", False),
                log=logs.append,
                capture_snapshot=False,
                **options,
            )
        (args.output / (name + ".log")).write_text("\n".join(logs))
        with pymupdf.open(pdf) as doc:
            text = " ".join(page.get_text() for page in doc)
        shutil.copy2(pdf, args.output / (name + ".pdf"))
        inputs = json.loads(pdf.with_suffix(".inputs.json").read_text())
        shutil.rmtree(pdf.parent)
        results.append(dict(check=name, ok=True, trace=trace.to_dict()))
        return text, inputs

    def rejects(name, body, **options):
        try:
            render(name, body, **options)
        except RuntimeError as exc:
            results.append(dict(check=name, ok=True, error=str(exc)))
        else:
            raise AssertionError(name + " was not rejected")

    frame = lambda text: (
        "\\begin{standardframe}{Preview validation}\n" + text + "\n\\end{standardframe}"
    )
    render("initial", frame("Original text"))
    text, _ = render("word-edit", frame("Edited words"))
    assert "Edited words" in text
    rejects("broken-edit", frame(r"\DefinitelyUndefinedPreviewCommand"))
    text, _ = render("recovery", frame("Recovered text"))
    assert "Recovered text" in text

    original_timestamp = slide_preview._preview_timestamp_line
    try:
        for stamp in ("2026-10-11 12:01", "2026-10-11 12:02"):
            slide_preview._preview_timestamp_line = lambda enabled, *a: (
                original_timestamp(enabled, stamp)
            )
            text, _ = render(
                "timestamp-" + stamp[-2:],
                frame("Timestamp validation"),
                footer_timestamp=True,
            )
            assert stamp in text, repr(text)
    finally:
        slide_preview._preview_timestamp_line = original_timestamp

    dependency = root / "preview-check-input.tex"
    bibliography = root / "preview-check-reference.bib"
    try:
        body = frame(r"\input{../preview-check-input.tex}")
        for value in ("A", "B"):
            dependency.write_text("Dependency " + value)
            text, inputs = render("dependency-" + value, body)
            assert "Dependency " + value in text and str(dependency) in inputs
        preamble = deck.preamble_text.replace(
            r"\begin{document}",
            r"\addbibresource{../preview-check-reference.bib}"
            + "\n"
            + r"\begin{document}",
        )
        for value in ("A", "B"):
            bibliography.write_text(
                "@article{previewvalidation, author={Author, Test}, title={Bibliography "
                + value
                + "}, journaltitle={Preview Journal}, year={2026}}\n"
            )
            text, inputs = render(
                "bibliography-" + value,
                frame(r"\fullcite{previewvalidation}"),
                preamble,
            )
            assert (
                "Bibliography " + value in text.replace("\n", " ")
                and str(bibliography) in inputs
            )
    finally:
        dependency.unlink(missing_ok=True)
        bibliography.unlink(missing_ok=True)
    rejects(
        "autobreak-overlay",
        r"\begin{frame}[allowframebreaks]{Auto breaks}Text\end{frame}",
        overlay=1,
    )
    cache = root / ".build" / "validation"
    assert not list(cache.rglob("*.synctex.gz")), (
        "Cached scratch previews still generated SyncTeX"
    )
    (args.output / "checks.json").write_text(json.dumps(results, indent=2))
    print(
        json.dumps(dict(passed=len(results), checks=[r["check"] for r in results])),
        flush=True,
    )


if __name__ == "__main__":
    main()
