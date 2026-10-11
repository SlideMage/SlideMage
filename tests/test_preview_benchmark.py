"""Experiment provenance, cold restarts, subset gates and durable evidence."""

import hashlib
import importlib
import json
from pathlib import Path
import sys
import tarfile
from types import SimpleNamespace

import pytest


@pytest.fixture
def modules(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "tools" / "preview_benchmark"))
    return SimpleNamespace(**{name: importlib.import_module(name)
                              for name in ("experiment", "compare", "summarize", "run_subset", "user_edits")})


@pytest.mark.parametrize("defect", ["invisible_second_edit", "mismatched_output", "missing_phase"])
def test_typical_edit_report_rejects_invalid_examples(tmp_path, modules, defect):
    samples = [dict(phase=phase, ok=True, seconds=1.0,
                    signature=[str(min(i, 2))], display_signature=[str(min(i, 2))], visible_edit=True)
               for i, phase in enumerate(modules.experiment.phases(2))]
    records = {case: dict(complete=True, pdf_matches=4, display_matches=4, visible_edits=4,
                         records={label: json.loads(json.dumps(samples))
                                  for label in ("original-fresh", "optimized")})
               for case in ("bullet", "title", "formula", "figure")}
    target = records["formula"]["records"]
    if defect == "invisible_second_edit":
        for values in target.values():
            values[2]["signature"] = values[1]["signature"]
            values[2]["display_signature"] = values[1]["display_signature"]
    elif defect == "mismatched_output":
        target["optimized"][1]["signature"] = ["wrong pixels"]
    else:
        target["optimized"].pop()
    with pytest.raises(AssertionError):
        modules.user_edits.write_report(records, tmp_path / "report.md", 1.0)
    assert not (tmp_path / "report.md").exists()


def test_immutable_identity_rejects_option_or_implementation_changes(tmp_path, modules):
    experiment = modules.experiment
    path = tmp_path / "identity.json"
    value = dict(source="one", options={"images": True})
    experiment.bind(path, value)
    experiment.bind(path, value)
    for changed in (dict(value, source="two"), dict(value, options={"images": False})):
        with pytest.raises(ValueError, match="Incompatible"):
            experiment.bind(path, changed)
    assert json.loads(path.read_text()) == value
    assert not list(tmp_path.glob(".record-*"))


@pytest.mark.parametrize("invisible_second_edit", [False, True])
def test_interrupted_attempt_restarts_cold_and_restores_source(tmp_path, modules, monkeypatch, invisible_second_edit):
    compare = modules.compare
    root, output = tmp_path / "project", tmp_path / "results"
    (root / "slides").mkdir(parents=True)
    (root / "decks").mkdir()
    source = root / "slides" / "abc-EN-Test-current.tex"
    original = b"\\begin{standardframe}{Title}Body\\end{standardframe}"
    source.write_bytes(original)
    call = SimpleNamespace(id_slug="abc-EN-Test", macro="slide", version=None, steps=None,
                           conditions=None, source_filename=source.name)
    deck = SimpleNamespace(name="slidemage-manual", text="deck", preamble_text=r"\begin{document}")
    monkeypatch.setattr(compare.deck_scan, "PROJECT_ROOT", root)
    monkeypatch.setattr(compare.deck_scan, "scan_decks", lambda: [deck])
    monkeypatch.setattr(compare.deck_editor, "parse_slide_calls", lambda _: [call])
    monkeypatch.setattr(compare.deck_editor, "is_commented_out", lambda *a: False)
    monkeypatch.setattr(compare.slide_preview, "_build_env", lambda: {})
    monkeypatch.setattr(compare, "implementation_identity", lambda package, options, env: dict(source="fixed", options=options))
    monkeypatch.setattr(compare, "signature", lambda path: [(320, 180, hashlib.sha256(path.read_bytes()).hexdigest())])
    caches, stop_once = [], [True]

    def render(*args, **kwargs):
        cache = compare.slide_preview.BUILD_DIR
        if cache not in caches:
            assert not cache.exists(), "cold attempt reused prior state"
            caches.append(cache)
            cache.mkdir(parents=True)
        folder = tmp_path / f"rendered-{len(list(tmp_path.glob('rendered-*')))}"
        folder.mkdir()
        pdf = folder / "preview.pdf"
        body = source.read_bytes()
        if invisible_second_edit and b"Title 2" in body:
            body = body.replace(b"Title 2", b"Title 1")
        pdf.write_bytes(body)
        if stop_once[0]:
            stop_once[0] = False
            (output / "STOP").touch()
        return pdf

    monkeypatch.setattr(compare.slide_preview, "render_slide_to_pdf", render)
    argv = ["compare", "--output", str(output), "--label", "before", "--configs", "saved", "--indices", "1", "--no-images"]
    monkeypatch.setattr(sys, "argv", argv)
    compare.main()
    assert source.read_bytes() == original and not list(output.glob("*/*/*/result.json"))
    (output / "STOP").unlink()
    compare.main()
    assert source.read_bytes() == original and len(caches) == 2
    records = list(output.glob("*/*/*/result.json"))
    assert len(records) == 1
    samples = json.loads(records[0].read_text())["samples"]
    assert [s["phase"] for s in samples] == modules.experiment.phases(2)
    assert samples[1]["visible_edit"]
    assert samples[2]["visible_edit"] is (not invisible_second_edit)
    if invisible_second_edit:
        assert samples[2]["signature"] != samples[0]["signature"]
        assert samples[2]["signature"] == samples[1]["signature"]
    assert len(list(output.glob("*/*/*/attempts/*/attempt.json"))) == 2
    # Completed results cannot silently resume under different image options.
    monkeypatch.setattr(sys, "argv", argv[:-1])
    with pytest.raises(ValueError, match="Incompatible"):
        compare.main()


def write_subset(tmp_path, modules):
    experiment = modules.experiment
    manifest = dict(schema=2, selected_indices=[2], calls=[dict(slide="one", steps=None), dict(slide="two", steps=None)])
    experiment.atomic_json(tmp_path / "manifest.json", manifest)
    for label in ("before", "after"):
        identity = dict(source=label, options=dict(repeats=2))
        experiment.atomic_json(tmp_path / label / "identity.json", identity)
        experiment_id = experiment.digest(dict(manifest=manifest, implementation=identity))
        for config in (["saved"] if label == "before" else experiment.CONFIGS):
            samples = [dict(phase=phase, ok=True, seconds=1.0, signature=[[320, 180, str(min(i, 2))]],
                            trace={"stages": {}, "rules": []}, visible_edit=True)
                       for i, phase in enumerate(experiment.phases(2))]
            record = dict(experiment_id=experiment_id, index=2, slide="two", config=config, samples=samples)
            experiment.atomic_json(tmp_path / label / config / "002" / "result.json", record)
    return tmp_path


def test_subset_completeness_and_after_first_comparison_reconciliation(tmp_path, modules):
    directory = write_subset(tmp_path, modules)
    manifest, _, _, raw, incomplete, failures = modules.summarize.load_results(directory)
    assert manifest["selected_indices"] == [2] and not incomplete and not failures
    assert len(raw) == 5
    assert all(s["pixel_match"] for r in raw if r["label"] == "after" for s in r["samples"])


@pytest.mark.parametrize("defect", ["duplicate", "missing_phase", "failed", "invisible", "mismatch", "identity"])
def test_bad_subset_cannot_be_a_passing_report(tmp_path, modules, defect):
    write_subset(tmp_path, modules)
    path = tmp_path / "after" / "saved" / "002" / "result.json"
    record = json.loads(path.read_text())
    if defect == "duplicate":
        modules.experiment.atomic_json(path.parent.parent / "0002" / "result.json", record)
    elif defect == "missing_phase":
        record["samples"].pop()
    elif defect == "failed":
        record["samples"][1]["ok"] = False
    elif defect == "invisible":
        record["samples"][1]["visible_edit"] = False
    elif defect == "mismatch":
        record["samples"][1]["signature"] = [[320, 180, "changed"]]
    else:
        record["experiment_id"] = "wrong implementation"
    modules.experiment.atomic_json(path, record)
    if defect in {"missing_phase", "identity"}:
        with pytest.raises(ValueError):
            modules.summarize.load_results(tmp_path)
    else:
        *_, incomplete, failures = modules.summarize.load_results(tmp_path)
        assert incomplete or failures


def test_evidence_archive_contains_checksummed_inputs_without_project_settings(tmp_path, modules):
    base = tmp_path / "scratch"
    (base / "project").mkdir(parents=True)
    (base / "project" / "slide.tex").write_text("source")
    (base / "project" / "settings.json").write_text('secret settings')
    (base / "results").mkdir()
    (base / "results" / "manifest.json").write_text('{}')
    (base / "tools").mkdir()
    (base / "tools" / "compare.py").write_text('frozen benchmark tool')
    artifact = modules.run_subset.archive(base, tmp_path / "evidence.tar.gz")
    with tarfile.open(artifact["path"]) as archive:
        assert "project/settings.json" not in archive.getnames()
        manifest = json.load(archive.extractfile("artifact-checksums.json"))
        assert "project/slide.tex" in manifest
        assert "tools/compare.py" in manifest
        for name, expected in manifest.items():
            assert hashlib.sha256(archive.extractfile(name).read()).hexdigest() == expected
