"""Benchmark of the Claude Code tasks (docs/CLAUDE_CODE_TASKS_PLAN.md, step 1) on a disposable copy of the
demo project: translation (EN to DE) and LaTeX fix over five representative slides, once per setup (a model
and an effort level) with the runner's isolation, a fresh process per task and edit lists for fixes.

Usage: .venv/bin/python tools/claude_task_benchmark.py [--setups NAME ...] [--work FOLDER] [--report FILE]
Runs the real `claude` (the user's login, so it uses the subscription). WORK keeps the copy and the
translations (default: a printed temp folder). The report is docs/CLAUDE_CODE_TASKS_BENCHMARK.md; its text
above "## Measurements" is kept, so the decisions written there survive a rerun.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
MARKER = "## Measurements"

# slide -> (text, text with a mistake the lint reports as an error): short with a table, citations and
# footnotes, formulas and overlays, a table and overlays, long with TikZ.
SLIDES = {
    "1bb-EN-What-You-Need": ("\\SMCode{ollama.com}", "\\SMCode{ollama.com"),
    "1nz-EN-Footnotes-Sources-Citations": ("\t\\end{itemize}\n\t\\source", "\t\\source"),
    "1t2-EN-Reveals-That-Do-Not-Jump": ("c$ \\quad (\\emph{c} moves)", "c \\quad (\\emph{c} moves)"),
    "1th-EN-Version-Dependent-Reveals": ("{\\small A reveal often hides", "{\\small A reveal & often hides"),
    "1nt-EN-Inside-a-Slide-File": ("\t\\end{columns}\n", ""),
}
SETUPS = {
    "sonnet-medium": {"model": "sonnet", "effort": "medium"},
    "haiku-medium": {"model": "haiku", "effort": "medium"},
    "haiku-low": {"model": "haiku", "effort": "low"},
}
DU_FORMS = re.compile(r"\b(du|dich|dir|dein\w*)\b", re.IGNORECASE)
ENGLISH_WORDS = re.compile(r"\b(the|(?<!pt )and|of|is|with|for|you|your|are|this|that)\b")


@dataclass
class Row:
    setup: str
    task: str
    slide: str
    outcome: object                       # a claude_runner.Outcome
    file_s: float | None = None           # until the fixed slide file had changed
    notes: list[str] = field(default_factory=list)


def commands(text: str) -> Counter:
    return Counter(re.findall(r"\\[a-zA-Z@]+", text))


def translation_notes(source: str, new: str) -> list[str]:
    notes = []
    if found := sorted(set(DU_FORMS.findall(new))):
        notes.append(f"informal address: {', '.join(found)}")
    if commands(source) != commands(new):
        notes.append(f"LaTeX commands differ: -{sum((commands(source) - commands(new)).values())} "
                     f"+{sum((commands(new) - commands(source)).values())}")
    prose = re.sub(r"(?m)^\s*%.*$|\\SM(?:Code|Cmd)\{[^}]*\}", "", new)
    if english := Counter(ENGLISH_WORDS.findall(prose)):
        notes.append("English words left: " + ", ".join(f"{w} x{n}" for w, n in english.most_common(4)))
    if not 0.7 < len(new) / len(source) < 1.8:
        notes.append(f"length {len(new) / len(source):.2f} x the source")
    return notes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--setups", nargs="+", choices=SETUPS, default=list(SETUPS))
    parser.add_argument("--work", type=Path, help="folder for the project copy and the translations")
    parser.add_argument("--report", type=Path, default=REPO / "docs" / "CLAUDE_CODE_TASKS_BENCHMARK.md")
    args = parser.parse_args(argv)
    work = (args.work or Path(tempfile.mkdtemp(prefix="slidemage-claude-bench-"))).resolve()
    project = work / "project"
    print(f"Work folder: {work}", flush=True)

    sys.path.insert(0, str(REPO / "src"))
    # project imports nothing that fixes PROJECT_ROOT at import time
    from slidemage.project import _ignore_template_build_output

    shutil.copytree(REPO / "example", project, ignore=_ignore_template_build_output)
    (work / "translations").mkdir()
    os.environ["SLIDEMASTER_PROJECT"] = str(project)
    os.environ["SLIDEMASTER_LATEX"] = str(REPO / "latex")

    from slidemage import latex_lint, slide_ids, slide_source
    from slidemage.ai import claude_launch, claude_runner, claude_tasks
    from slidemage.ai.workspace import Workspace

    claude = claude_launch.find_claude()
    if claude is None:
        print("claude not found")
        return 1
    version = subprocess.run([str(claude), "--version"], capture_output=True, text=True).stdout.strip()
    workspace = Workspace(project)

    def errors(text: str) -> int:
        return sum(i.severity == latex_lint.ERROR for i in latex_lint.lint_text(text))

    paths = {s: project / "slides" / f"{s}-current.tex" for s in SLIDES}
    clean = {s: slide_source.read_slide_source(p)[0] for s, p in paths.items()}
    broken = {s: clean[s].replace(old, new, 1) for s, (old, new) in SLIDES.items()}
    eols = {s: slide_source.read_slide_source(p)[1] for s, p in paths.items()}
    translated = {s: slide_ids.slide_body(p).replace("\r\n", "\n") for s, p in paths.items()}
    for slide in SLIDES:
        assert errors(broken[slide]) > errors(clean[slide]), f"the mistake in {slide} is not an error"

    rows: list[Row] = []
    for setup in args.setups:
        for task_name, task in (("translate", claude_tasks.TRANSLATE), ("fix_latex", claude_tasks.FIX_LATEX)):
            for slide, path in paths.items():
                path.write_bytes(broken[slide].replace("\n", eols[slide]).encode("utf-8"))
                if task_name == "translate":
                    captured = translated[slide]
                    request = claude_tasks.translate_request(captured, "EN", "DE", "Sie")
                else:
                    captured = broken[slide]
                    request = claude_tasks.fix_request(captured, latex_lint.lint_text(captured))
                started = time.monotonic()
                outcome = claude_runner.run_task(claude, task, captured, request, **SETUPS[setup])
                row = Row(setup, task_name, slide, outcome)
                if task_name == "translate" and outcome.status == claude_runner.DONE:
                    (work / "translations" / f"{setup}-{slide}-DE.tex").write_text(outcome.text, encoding="utf-8")
                    row.notes = translation_notes(captured, outcome.text)
                elif task_name == "fix_latex":
                    if outcome.status == claude_runner.DONE:
                        if problem := claude_runner.apply_result(workspace, path, captured, outcome.text):
                            row.notes.append(problem)
                        row.file_s = time.monotonic() - started
                    after = slide_source.read_slide_source(path)[0]
                    row.notes.append("exactly the original slide" if after == clean[slide] else
                                     f"{errors(after)} error(s) left" if errors(after) else
                                     "no error left, differs from the original slide")
                rows.append(row)
                print(f"{setup:14} {task_name:9} {slide[:3]} {outcome.status:17} {outcome.elapsed_s:5.1f} s "
                      f"{'; '.join(row.notes + [outcome.message])}", flush=True)
    write_report(args.report, rows, version)
    print(f"Report: {args.report}")
    return 0


def seconds(values: list[float]) -> tuple[str, str]:
    """Median and slowest of `values`, as table cells."""
    return (f"{statistics.median(values):.1f}", f"{max(values):.1f}") if values else ("-", "-")


def write_report(path: Path, rows: list[Row], version: str) -> None:
    old = path.read_text(encoding="utf-8") if path.is_file() else ""
    head = old.split(MARKER)[0] if MARKER in old else "# Claude Code tasks: benchmark\n\n"
    out = [f"{MARKER}\n",
           f"Run on {date.today()} with Claude Code {version}, tools/claude_task_benchmark.py: five slides, one "
           "run each per setup and task. Times are seconds from the start of the task: *first* the first answer "
           "event, *valid* the answer checked (a repair attempt included), *file* the fix written to the slide "
           "file. Turns and tokens (input with cached ones / output) are means per run.\n",
           "| Setup | Task | Done | Nothing | Failed | Repairs | First (median) | Valid (median) | Valid (slowest) "
           "| File (median) | Turns | Tokens |",
           "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    groups: dict[tuple[str, str], list[Row]] = {}
    for row in rows:
        groups.setdefault((row.setup, row.task), []).append(row)
    for (setup, task), group in groups.items():
        outs = [r.outcome for r in group]
        status = Counter(o.status for o in outs)
        valid = seconds([o.elapsed_s for o in outs])
        out.append(f"| {setup} | {task} | {status['done']} | {status['nothing to change']} "
                   f"| {status['failed'] + status['cancelled']} | {sum(o.attempts > 1 for o in outs)} "
                   f"| {seconds([o.first_s for o in outs if o.first_s is not None])[0]} | {valid[0]} | {valid[1]} "
                   f"| {seconds([r.file_s for r in group if r.file_s is not None])[0]} "
                   f"| {sum(o.turns for o in outs) / len(outs):.1f} "
                   f"| {sum(o.tokens_in for o in outs) // len(outs)} / {sum(o.tokens_out for o in outs) // len(outs)} |")
    out += ["", "## Per run", "", "| Setup | Task | Slide | Result | Valid (s) | Notes |",
            "| --- | --- | --- | --- | --- | --- |"]
    for r in rows:
        notes = "; ".join(r.notes + ([r.outcome.message] if r.outcome.message else []))
        out.append(f"| {r.setup} | {r.task} | {r.slide[:3]} | {r.outcome.status} | {r.outcome.elapsed_s:.1f} | {notes} |")
    out.append("")
    path.write_text(head + "\n".join(out), encoding="utf-8", newline="\n")


if __name__ == "__main__":
    sys.exit(main())
