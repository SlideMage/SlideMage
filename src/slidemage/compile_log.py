"""SlideMage's status-line protocol: exact log text and its recognizers.

Patterns deliberately keep the existing parsers' groups and prefix matching.
TeX and latexmk output are external to this protocol.
"""
from __future__ import annotations

import re
from pathlib import Path


COMPILING_RE = re.compile(r"^==== Compiling \S+ -> (\S+) ====")


def compiling(deck_name: str, jobname: str) -> str:
    return f"==== Compiling {deck_name} -> {jobname} ===="


MOVING_RE = re.compile(r"^==== MOVING: (\S+) ->")


def moving(jobname: str, dest: str | Path, suffix: str = "") -> str:
    return f"==== MOVING: {jobname} -> {dest} ===={suffix}"


# A job's PASS line ends it as well: a page compile (partial_compile.py)
# patches its PDF itself and never logs "MOVING" (v5.35.1 -- its busy bar
# kept running after the compile). A whole-deck job's PASS comes after its
# MOVING line, when the job is no longer the current one: no effect.
PASS_RE = re.compile(r"^==== PASS: (\S+) ->")


def passed(jobname: str, dest: str | Path, suffix: str = "") -> str:
    return f"==== PASS: {jobname} -> {dest}{suffix} ===="


# Status needs the reason; progress also ends a job whose reason spans lines.
FAIL_RE = re.compile(r"^\*\*\* FAIL: (\S+) -- (.*?)(?: \*\*\*)?$")
FAIL_PREFIX_RE = re.compile(r"^\*\*\* FAIL: (\S+) --")


def failed(jobname: str, reason: str) -> str:
    return f"*** FAIL: {jobname} -- {reason} ***"


# A job that ends without publishing a PDF (deck_snapshot's reference and
# verification compiles) says so explicitly.
FINISHED_RE = re.compile(r"^==== Finished: (\S+) ====")


def finished(jobname: str) -> str:
    return f"==== Finished: {jobname} ===="


# A queued job the user took out of the run.
SKIPPED_RE = re.compile(r"^==== Skipped: (\S+) ====")


def skipped(jobname: str) -> str:
    return f"==== Skipped: {jobname} ===="


# Status stops queued rows on the summary; progress also handles the request.
STOPPED_ALL_RE = re.compile(r"^==== Stopped: ")
STOPPED_RE = re.compile(r"^==== (Stopped:|Stop requested)")


def stopped(count: int) -> str:
    return f"==== Stopped: {count} job(s) skipped ===="


def stop_requested() -> str:
    return "==== Stop requested -- killing current job and skipping the rest ===="


RENDERING_RE = re.compile(r"^==== Rendering (\S+) -> (\S+) ====")


def rendering(id_slug: str, jobname: str) -> str:
    return f"==== Rendering {id_slug} -> {jobname} ===="


RENDER_PASS_RE = re.compile(r"^==== PASS: render of (\S+) ->")


def render_passed(id_slug: str, dest: str | Path) -> str:
    return f"==== PASS: render of {id_slug} -> {dest} ===="


RENDER_FAIL_RE = re.compile(r"^\*\*\* FAIL: render of (\S+) --")


def render_failed(id_slug: str, reason: str) -> str:
    return f"*** FAIL: render of {id_slug} -- {reason} ***"


TIKZ_RENDERING_RE = re.compile(r"^==== Rendering tikz illustration (\S+) \(from (.*?)\) ====")


def tikz_rendering(illustration_id: str, source_name: str) -> str:
    return f"==== Rendering tikz illustration {illustration_id} (from {source_name}) ===="


TIKZ_PASS_RE = re.compile(r"^==== PASS: tikz illustration (\S+) ->")


def tikz_passed(illustration_id: str, dest: str | Path) -> str:
    return f"==== PASS: tikz illustration {illustration_id} -> {dest} ===="
