"""Summarize compare.py data with cold/edit/unchanged columns and p95."""

import argparse
import json
import math
from pathlib import Path
from statistics import mean, median

from experiment import digest, phases, subset_indices, validate_record


def load_results(directory):
    manifest = json.loads((directory / "manifest.json").read_text())
    identities = {path.parent.name: json.loads(path.read_text())
                  for path in directory.glob("*/identity.json")}
    groups, raw = {}, []
    for path in sorted(directory.glob("*/*/*/result.json")):
        label, config = path.parts[-4:-2]
        record = json.loads(path.read_text())
        if manifest.get("schema", 1) >= 2:
            identity = identities[label]
            validate_record(record, digest(dict(manifest=manifest, implementation=identity)),
                            phases(identity["options"]["repeats"]))
            if record["config"] != config or record["index"] != int(path.parent.name):
                raise ValueError("Record path and identity differ")
        raw.append(dict(label=label, **record))
        groups.setdefault((label, config), []).append(record)
    # Reconcile after-first records once their adjacent baseline exists.
    references = {(r["index"], s["phase"]): s for r in raw if r["label"] == "before"
                  and r["config"] == "saved" for s in r["samples"]}
    if manifest.get("schema", 1) >= 2:
        for record in raw:
            if record["label"] == "before":
                continue
            for sample in record["samples"]:
                if not sample["ok"]:
                    continue
                reference = references.get((record["index"], sample["phase"]))
                if not reference or not reference["ok"]:
                    sample["reference_missing"] = True
                    continue
                baseline = reference["signature"]
                if "overlay" in record["config"]:
                    baseline = baseline[:1]
                sample["pixel_match"] = sample["signature"] == baseline
                if ("overlay" in record["config"] and
                    manifest["calls"][record["index"] - 1]["steps"] == "3"):
                    sample["pixel_match"] = None
    selected = set(subset_indices(manifest))
    expected = {("before", "saved")} | {
        ("after", config) for config in ("saved", "buffer", "overlay", "buffer-overlay")
    }
    incomplete = expected - groups.keys()
    for key, records in groups.items():
        indices = [record["index"] for record in records]
        expected_phases = phases(identities[key[0]]["options"]["repeats"]) if identities else phases(2)
        if set(indices) != selected or len(indices) != len(selected) or any(
            [s["phase"] for s in r["samples"]] != expected_phases for r in records
        ):
            incomplete.add(key)
    failures = sum(not s["ok"] or s.get("pixel_match") is False
                   or s.get("visible_edit") is False or s.get("reference_missing", False)
                   for r in raw for s in r["samples"])
    return manifest, identities, groups, raw, incomplete, failures


def statistics(values):
    return dict(
        mean=mean(values) if values else None,
        median=median(values) if values else None,
        p95=sorted(values)[math.ceil(0.95 * len(values)) - 1] if values else None,
        total=sum(values),
    )


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--allow-incomplete", action="store_true")
    args = parser.parse_args()
    manifest, identities, groups, raw, incomplete, failures = load_results(args.input)
    if (incomplete or failures) and not args.allow_incomplete:
        parser.error(f"Incomplete or failed comparison: missing={sorted(incomplete)}, failed={failures}")
    summaries = []
    lines = [
        "# BIG CHANGE 2 preview benchmark — 11 October 2026",
        "",
        f"Frozen subset: **{len(subset_indices(manifest))} of {len(manifest['calls'])} active manual calls**. "
        "Each includes a cold build, two actual visible text/graphic edits, and an unchanged request. "
        "The GUI image preparation is included; opening an external viewer and Qt painting are excluded.",
        "",
        "| Configuration | Calls | Cold median, s | Edit mean, s | Edit median, s | Edit maximum, s | Edit total, s | Unchanged median, s | Failures | PDF mismatches |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    order = ("saved", "buffer", "overlay", "buffer-overlay")
    for label, config in sorted(
        groups, key=lambda key: (key[0] != "before", order.index(key[1]))
    ):
        records = groups[(label, config)]
        samples = [s for r in records for s in r["samples"]]
        successful = [s for s in samples if s["ok"]]
        edits = [s["seconds"] for s in successful if s["phase"].startswith("edit-")]
        cold = [s["seconds"] for s in successful if s["phase"] == "cold"]
        hits = [s["seconds"] for s in successful if s["phase"] == "unchanged"]
        mismatches = sum(s.get("pixel_match") is False for s in samples)
        phase_statistics = dict(
            cold=statistics(cold), edits=statistics(edits), unchanged=statistics(hits)
        )
        stage_medians = {}
        rule_counts = {}
        for phase in ("cold", "edits", "unchanged"):
            selected = [
                s
                for s in successful
                if (
                    s["phase"].startswith("edit-")
                    if phase == "edits"
                    else s["phase"] == phase
                )
            ]
            names = {name for s in selected for name in s["trace"].get("stages", {})}
            stage_medians[phase] = {
                name: median(
                    s["trace"].get("stages", {}).get(name, 0) for s in selected
                )
                for name in sorted(names)
            }
            counts = {}
            for s in selected:
                for rule in s["trace"].get("rules", []):
                    # Bibliography rule names contain a job-specific absolute path.
                    name = rule["rule"].split(" ", 1)[0]
                    counts[name] = counts.get(name, 0) + 1
            rule_counts[phase] = counts
        summary = dict(
            label=label,
            config=config,
            calls=len(records),
            failures=sum(not s["ok"] for s in samples),
            mismatches=mismatches,
            compared=sum(s.get("pixel_match") is not None for s in samples),
            not_comparable=sum(
                "pixel_match" in s and s["pixel_match"] is None for s in samples
            ),
            cold_median=median(cold) if cold else None,
            edit_mean=mean(edits) if edits else None,
            edit_median=median(edits) if edits else None,
            edit_p95=sorted(edits)[math.ceil(0.95 * len(edits)) - 1] if edits else None,
            edit_total=sum(edits),
            unchanged_median=median(hits) if hits else None,
            phase_statistics=phase_statistics,
            stage_medians=stage_medians,
            rule_counts=rule_counts,
        )
        summaries.append(summary)
        if edits and cold and hits:
            lines.append(
                f"| {label}: {config} | {len(records)} | {median(cold):.3f} | {mean(edits):.3f} | "
                f"{median(edits):.3f} | {max(edits):.3f} | {sum(edits):.2f} | {median(hits):.3f} | {summary['failures']} | {mismatches} |"
            )
    lines += [
        "",
        "| Configuration | Cold mean, s | Cold p95, s | Cold total, s | Unchanged mean, s | Unchanged p95, s | Unchanged total, s | Comparable PDFs | Not comparable |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for summary in summaries:
        cold, hits = (
            summary["phase_statistics"][phase] for phase in ("cold", "unchanged")
        )
        if cold["mean"] is not None and hits["mean"] is not None:
            lines.append(
                f"| {summary['label']}: {summary['config']} | {cold['mean']:.3f} | {cold['p95']:.3f} | "
                f"{cold['total']:.2f} | {hits['mean']:.3f} | {hits['p95']:.3f} | {hits['total']:.2f} | "
                f"{summary['compared']} | {summary['not_comparable']} |"
            )
    lines += [
        "",
        "Edit totals cover both edits per call. Cold means a new slide build cache, with the existing TeX "
        "font cache warm. Raw p95 is descriptive only; this subset is too small to establish a stable tail estimate. Configurations alternate order by call; "
        "two different edits are repeated workloads, not identical-edit repetitions. "
        "The manual has changed since the 77-call benchmark on 9 October; these totals cannot be "
        "compared directly to that older corpus.",
        "",
        "Selected-overlay comparisons use the corresponding first baseline page. A call restricted to "
        "overlay 3 has no overlay-1 reference and is marked not comparable. Full-slide PDF identity is "
        "to the standalone-preview baseline, not a whole-deck build.",
        "",
        "Raw timings, per-rule traces, corpus hashes, comparison results and failures are in the companion JSON.",
    ]
    lines += ["", f"Declared call indices: {subset_indices(manifest)}. "
              f"Passing completeness gate: **{not incomplete and not failures}**.", ""]
    if identities:
        lines += ["Implementation, tools, dependencies, options and edit recipes are bound to immutable identities. "
                  "Resumes reject changes; unfinished records restart with a new empty cache. "
                  "The checked-in subset orchestrator alternates before/after order by call.", ""]
    lines += ["| Call | Before saved edit mean, s | After saved edit mean, s | Difference |", "| --- | ---: | ---: | ---: |"]
    for index in subset_indices(manifest):
        pair = {}
        for label in ("before", "after"):
            values = [s["seconds"] for r in groups.get((label, "saved"), []) if r["index"] == index
                      for s in r["samples"] if s["ok"] and s["phase"].startswith("edit-")]
            if values:
                pair[label] = mean(values)
        if len(pair) == 2:
            difference = pair["after"] / pair["before"] - 1
            lines.append(f"| {index}: {manifest['calls'][index-1]['slide']} | {pair['before']:.3f} | {pair['after']:.3f} | {difference:+.1%} |")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(("\n".join(lines) + "\n").replace("\n", "\r\n").encode())
    args.output.with_suffix(".json").write_text(
        json.dumps(
            dict(
                complete=not incomplete and not failures,
                manifest=manifest,
                implementations=identities,
                incomplete=[list(key) for key in sorted(incomplete)],
                failed_checks=failures,
                ordering=json.loads((args.input / "orchestration.json").read_text())
                if (args.input / "orchestration.json").exists() else None,
                summary=summaries,
                records=raw,
            ),
            indent=2,
        )
        + "\n"
    )


if __name__ == "__main__":
    main()
