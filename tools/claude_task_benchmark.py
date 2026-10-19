# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Benchmark of the Claude Code tasks (docs/CLAUDE_CODE_TASKS_PLAN.md, step 1) on a disposable copy of the
demo project: translation (EN to DE) and LaTeX fix over five representative slides, once per setup (a model
and an effort level) with the runner's isolation, a fresh process per task and edit lists for fixes.

Usage: .venv/bin/python tools/claude_task_benchmark.py [--setups NAME ... | --ui] [--work FOLDER] [--report FILE]
With --ui (step 6) the same slides go through the real window offscreen instead, with the default model: each
bubble's task from the click to the first answer, the changed buffer and the finished preview, plus one image run
and one deck batch. Runs the real `claude` (the user's login, so it uses the subscription). WORK keeps the copy and the
translations (default: a printed temp folder). The report is docs/CLAUDE_CODE_TASKS_BENCHMARK.md; its text
above "## Measurements" is kept, so the decisions written there survive a rerun.
"""
from __future__ import annotations

import argparse
import difflib
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
IMAGE_SLIDE, IMAGE = "1rb-EN-Figureframe", "media/correlation-matrix-example.png"    # a slide with a PNG
PREVIEW_WAIT_S = 90                   # for the preview after the buffer has changed

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


def unlink_partners(project: Path) -> None:
    """The demo project may hold a German partner of one of the slides, and then no translation is offered: take
    each partner and its link out of the copy."""
    for slide in SLIDES:
        path = project / "slides" / f"{slide}-current.tex"
        text = path.read_bytes().decode("utf-8")
        for partner in re.findall(r"^%% DE translation: (\S+)", text, re.MULTILINE):
            (project / "slides" / f"{partner}-current.tex").unlink()
            path.write_bytes(re.sub(rf"^%% DE translation: {partner}\r?\n%%\r?\n", "", text, flags=re.MULTILINE).encode("utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--setups", nargs="+", choices=SETUPS, default=list(SETUPS))
    parser.add_argument("--ui", action="store_true", help="through the offscreen window, default model (step 6)")
    parser.add_argument("--work", type=Path, help="folder for the project copy and the translations")
    parser.add_argument("--report", type=Path, default=REPO / "docs" / "CLAUDE_CODE_TASKS_BENCHMARK.md")
    args = parser.parse_args(argv)
    work = (args.work or Path(tempfile.mkdtemp(prefix="slidemage-claude-bench-"))).resolve()
    project = work / "project"
    print(f"Work folder: {work}", flush=True)

    sys.path.insert(0, str(REPO / "src"))
    from slidemage.project import _ignore_template_build_output

    shutil.copytree(REPO / "example", project, ignore=_ignore_template_build_output)
    (work / "translations").mkdir()
    if args.ui:
        unlink_partners(project)
    os.environ["SLIDEMASTER_PROJECT"] = str(project)
    os.environ["SLIDEMASTER_LATEX"] = str(REPO / "latex")

    from slidemage import latex_lint, slide_ids, slide_source
    from slidemage.ai import claude_launch, claude_runner, claude_tasks
    from slidemage.ai.workspace import Workspace
    from slidemage.project import ProjectContext

    claude = claude_launch.find_claude()
    if claude is None:
        print("claude not found")
        return 1
    version = subprocess.run([str(claude), "--version"], capture_output=True, text=True).stdout.strip()
    ctx = ProjectContext.at(project)
    workspace = Workspace(ctx)

    def errors(text: str) -> int:
        return sum(i.severity == latex_lint.ERROR for i in latex_lint.lint_text(ctx, text))

    paths = {s: project / "slides" / f"{s}-current.tex" for s in SLIDES}
    clean = {s: slide_source.read_slide_source(p)[0] for s, p in paths.items()}
    broken = {s: clean[s].replace(old, new, 1) for s, (old, new) in SLIDES.items()}
    eols = {s: slide_source.read_slide_source(p)[1] for s, p in paths.items()}
    translated = {s: slide_ids.slide_body(p).replace("\r\n", "\n") for s, p in paths.items()}
    for slide in SLIDES:
        assert errors(broken[slide]) > errors(clean[slide]), f"the mistake in {slide} is not an error"

    if args.ui:
        write_report(args.report, ui_report(run_ui(claude, work, paths, clean, broken, translated, errors), version))
        print(f"Report: {args.report}")
        return 0

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
                    request = claude_tasks.fix_request(captured, latex_lint.lint_text(ctx, captured))
                started = time.monotonic()
                outcome = claude_runner.run_task(ctx, claude, task, captured, request, **SETUPS[setup])
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
    write_report(args.report, runner_report(rows, version))
    print(f"Report: {args.report}")
    return 0


@dataclass
class UiRow:
    task: str
    slide: str
    status: str                           # the status line when the task was done
    first_s: float | None                 # all times from the click
    changed_s: float                      # until the busy flag ended: the buffer changed, or the batch was done
    preview_s: float | None = None        # until the first finished render after the click
    notes: list[str] = field(default_factory=list)


def run_ui(claude, work: Path, paths: dict[str, Path], clean: dict[str, str], broken: dict[str, str],
           translated: dict[str, str], errors) -> list[UiRow]:
    """The tasks through the real window, offscreen, split view: Translate to German, Fix LaTeX errors and
    Proofread on each slide, Describe images on IMAGE_SLIDE, a deck batch of Fix LaTeX errors on all slides."""
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PySide6.QtCore import QCoreApplication, Qt
    from PySide6.QtWidgets import QApplication

    from slidemage import alt_images, slide_ids, slide_source, slide_versioning
    from slidemage.ai import claude_runner, claude_tasks
    from slidemage.ai.claude_images import DESCRIBE
    from slidemage.ui import layout_settings
    from slidemage.ui.workspace.chat.gui_workspace import GuiWorkspace
    from slidemage.ui.workspace.terminal.tasks import TaskRunner, bubbles, deck_bubbles

    layout_settings.STORE_PATH = work / "layout.json"
    QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    app = QApplication([])
    from slidemage.ui.kit.fonts import load_fonts
    from slidemage.project import from_environment
    from slidemage.ui.kit.theme import ThemeManager
    from slidemage.ui.workspace.window import WorkspaceWindow

    load_fonts()
    theme = ThemeManager(dark=False)
    theme.apply()
    window = WorkspaceWindow(theme, from_environment())
    window.resize(1600, 900)
    window.show()
    window.state.set_deck(next(d for d in window.decks if d.name == "slidemage-manual"))
    window.state.set_mode("split")
    preview, centre = window.centre.preview, window.centre
    runner = TaskRunner(window, claude, GuiWorkspace(window))
    marks: dict[str, object] = {}                                   # what the signals saw since the click
    outcomes: list = []
    runner.busy_changed.connect(lambda busy: busy or marks.setdefault("changed", time.monotonic()))
    runner.status.connect(lambda text, _tone: marks.update(status=text))
    preview.rendered.connect(lambda: marks.setdefault("preview", time.monotonic()))
    done = runner._on_done                                          # the Outcomes, for the first answer
    runner._on_done = lambda worker, outcome: (outcomes.append(outcome), done(worker, outcome))

    def wait(condition, seconds: float) -> bool:
        end = time.monotonic() + seconds
        while not condition() and time.monotonic() < end:
            app.processEvents()
            time.sleep(0.005)
        return condition()

    def show(path: Path, text: str) -> None:
        """Open the slide with `text` in the buffer (typed, not saved) and let the preview rest."""
        window.open_slide_editor(path)
        centre.source.current.editor.replace_all_text(text)
        wait(lambda: False, 1.5)
        wait(lambda: not preview._busy, 120)

    def click(name: str, slide: str, task, offered, preview_expected: bool = True) -> UiRow:
        """Click the bubble of `task` among those `offered()` lists, and time what follows. The preview of a new
        translation is not rendered by the app (a slide shown for the first time waits for Render), so it is
        asked for when the task is done."""
        bubble = next(b for b in offered() if b.task is task)
        marks.clear()
        outcomes.clear()
        start = marks["start"] = time.monotonic()
        runner.start(bubble.task, claude_runner.MODEL, claude_runner.EFFORT, bubble.paths)
        wait(lambda: "changed" in marks, 600)
        if preview_expected and str(marks.get("status", "")).startswith("Done"):
            if task is claude_tasks.TRANSLATE:
                preview.render_buffer()
            wait(lambda: "preview" in marks, PREVIEW_WAIT_S)
        row = UiRow(name, slide, str(marks.get("status", "")), getattr(outcomes[0], "first_s", None) if outcomes else None,
                    marks.get("changed", time.monotonic()) - start,
                    marks["preview"] - start if "preview" in marks else None)
        if outcomes and getattr(outcomes[0], "attempts", 1) > 1:
            row.notes.append("repair attempt")
        print(f"{name:10} {slide} {row.changed_s:5.1f} s "
              f"{'-' if row.preview_s is None else f'{row.preview_s:.1f}'} s  {row.status}", flush=True)
        return row

    rows: list[UiRow] = []
    (work / "ui").mkdir()
    for task_name, task in (("translate", claude_tasks.TRANSLATE), ("fix_latex", claude_tasks.FIX_LATEX),
                            ("proofread", claude_tasks.PROOFREAD)):
        for slide, path in paths.items():
            known = set(path.parent.glob("*-current.tex"))
            show(path, broken[slide] if task_name == "fix_latex" else clean[slide])
            row = click(task_name, slide[:3], task, lambda: bubbles(window))
            after = centre.slide_text(path)
            if task_name == "translate":
                if partners := set(path.parent.glob("*-current.tex")) - known:
                    partner = next(iter(partners))
                    text = slide_ids.slide_body(partner).replace("\r\n", "\n")
                    (work / "translations" / f"ui-{slide}-DE.tex").write_text(text, encoding="utf-8")
                    row.notes += translation_notes(slide_versioning.strip_marker(translated[slide]), text)
            elif task_name == "fix_latex":
                row.notes.append("exactly the original slide" if after == clean[slide] else
                                 f"{errors(after)} error(s) left" if errors(after) else
                                 "no error left, differs from the original slide")
            else:
                diff = list(difflib.unified_diff(clean[slide].splitlines(), after.splitlines(), lineterm="", n=0))[2:]
                (work / "ui" / f"proofread-{slide[:3]}.diff").write_text("\n".join(diff), encoding="utf-8")
                row.notes.append(f"{sum(line[0] in '+-' for line in diff)} changed line(s)")
            rows.append(row)
            show(path, clean[slide])

    def forget(entries) -> bool:                  # the image is described in the demo project: take that away
        entries[IMAGE].short = entries[IMAGE].long = ""
        entries[IMAGE].role = alt_images.ROLE_INFORMATIVE
        return True

    path = next(iter(paths.values())).parent / f"{IMAGE_SLIDE}-current.tex"
    alt_images.update_store(window.project, forget)
    show(path, slide_source.read_slide_source(path)[0])
    row = click("describe", IMAGE_SLIDE[:3], DESCRIBE, lambda: bubbles(window), preview_expected=False)
    entry = alt_images.load_store(window.project)[IMAGE]
    row.notes.append(f"short: {entry.short[:120]}")
    (work / "ui" / "image.txt").write_text(f"{entry.short}\n\n{entry.long}\n", encoding="utf-8")
    rows.append(row)

    for slide, path in paths.items():
        show(path, broken[slide])
    row = click("fix_batch", f"{len(paths)} slides", claude_tasks.FIX_LATEX, lambda: deck_bubbles(window), preview_expected=False)
    row.notes.append(f"the slides' processes took {sum(o.elapsed_s for o in outcomes):.1f} s together")
    row.notes.append(f"{sum(centre.slide_text(p) == clean[s] for s, p in paths.items())} of {len(paths)} exactly the original")
    rows.append(row)
    runner.shutdown()
    window.hide()
    return rows


def seconds(values: list[float]) -> tuple[str, str]:
    """Median and slowest of `values`, as table cells."""
    return (f"{statistics.median(values):.1f}", f"{max(values):.1f}") if values else ("-", "-")


def write_report(path: Path, body: list[str]) -> None:
    """Replace what stands below MARKER with `body` (lines), keeping the text above it."""
    old = path.read_text(encoding="utf-8") if path.is_file() else ""
    before, found, _ = old.rpartition("\n" + MARKER)       # the heading, not a mention of it in the text above
    head = before + "\n" if found else "# Claude Code tasks: benchmark\n\n"
    path.write_text(head + "\n".join([f"{MARKER}\n", *body]), encoding="utf-8", newline="\n")


def runner_report(rows: list[Row], version: str) -> list[str]:
    out = [f"Run on {date.today()} with Claude Code {version}, tools/claude_task_benchmark.py: five slides, one "
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
    return out + [""]


def ui_report(rows: list[UiRow], version: str) -> list[str]:
    out = [f"Run on {date.today()} with Claude Code {version}, tools/claude_task_benchmark.py --ui: the bubbles of "
           "the Claude Code tab clicked offscreen on a disposable copy (Split view, default model and effort): "
           "three tasks over five slides, one image run, one deck batch of Fix LaTeX errors over the five slides. "
           "Times are seconds from the click: *first* the first answer event, *changed* the buffer changed (status "
           "\"Done\"; a batch: all slides done), *preview* the first finished render after the click (waited for only "
           "after a \"Done\" of a slide task). Medians.\n",
           "| Task | Runs | Done | Nothing | First (median) | Changed (median) | Changed (slowest) | Preview (median) "
           "| Preview (slowest) |",
           "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    groups: dict[str, list[UiRow]] = {}
    for row in rows:
        groups.setdefault(row.task, []).append(row)
    for task, group in groups.items():
        changed, preview = seconds([r.changed_s for r in group]), seconds([r.preview_s for r in group if r.preview_s is not None])
        out.append(f"| {task} | {len(group)} | {sum(r.status.startswith('Done') for r in group)} "
                   f"| {sum(r.status == 'Nothing to change' for r in group)} "
                   f"| {seconds([r.first_s for r in group if r.first_s is not None])[0]} | {changed[0]} | {changed[1]} "
                   f"| {preview[0]} | {preview[1]} |")
    out += ["", "## Per run", "", "| Task | Slide | Status | First (s) | Changed (s) | Preview (s) | Notes |",
            "| --- | --- | --- | --- | --- | --- | --- |"]
    for r in rows:
        out.append(f"| {r.task} | {r.slide} | {r.status} | {'-' if r.first_s is None else f'{r.first_s:.1f}'} "
                   f"| {r.changed_s:.1f} | {'-' if r.preview_s is None else f'{r.preview_s:.1f}'} | {'; '.join(r.notes)} |")
    return out + [""]


if __name__ == "__main__":
    sys.exit(main())
