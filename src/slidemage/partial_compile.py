"""Compile only some slides of a deck, numbered as in the whole deck, and
optionally swap them into the deck's existing PDF (v5.35.0, direct
instruction: "compile individual pages or page ranges of pages of a deck,
retaining the page numbers the slides would have in the full deck (e.g.,
using a specification like '4, 5, 7-10, 15') ... Ideally, SlideMage would
even allow automatically replacing these slides in the full deck").

The numbers in a page spec are the ones in the slide footers
(\\insertframenumber -- the frame number, which the student versions keep in
step with the instructor version). Everything needed comes from the last
whole-deck compile of the same version, kept by compile_records.py: its PDF
(each page's footer says which slide and frame it is) and its auxiliary files
(contents, chapter agendas, citations, cross-references, layout corrections).

How a page compile works:

1. plan(): the requested frames are looked up in the full PDF and matched to
   the deck's slide calls (in order, by slide id). A slide is always compiled
   whole: asking for one page of a slide with reveal steps compiles all of
   them. The deck file itself must be unchanged since that compile -- a slide
   added, moved or removed changes every number after it.
2. wrapper_text(): the deck with every other slide call removed, and before
   each kept one \\setcounter{framenumber}/{page} to the values it had in the
   full deck.
3. run(): two passes of lualatex (latexmk, one run each, no biber) on top of
   the full compile's auxiliary files, so contents, agendas, links and
   citations are those of the whole deck. Between the passes the full files
   are restored, keeping only what the kept slides need from the first pass:
   their layout corrections (.top) and tikz positions.
4. patch(): each new page is drawn onto the corresponding page of the full
   PDF (its old content and links removed, the page object kept, so links
   and bookmarks pointing at it stay valid); the new page's links are
   re-targeted into the full PDF. A slide whose page count changed (an
   added \\pause) can't be swapped in place: it is reported, and its pages
   are written to a separate PDF instead.

What a page compile does not update: other pages that show something of the
changed slides (a new title in the contents slide, a thumbnail in the
generated appendix), and slides that changed but weren't asked for -- the
result lists those.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from . import compile_records, compiler, latex_lint
from .compiler import FATAL_ERROR_RE, CancelToken, CompileJob
from .deck_editor import SlideCall

LogCallback = Callable[[str], None]

# "(slide id: 1nz | v1.0.0EN | ... )" then the frame number, in every footer.
_FOOTER_RE = re.compile(r"\(slide id: ([0-9A-Za-z]{3})\b[^)]*\)\s*(\d+)")
_SPEC_PART_RE = re.compile(r"^(\d+)\s*(?:[-\u2013\u2014]\s*(\d+))?$")
# What the second pass keeps from the first (see the module docstring).
_PGF_MARK_RE = re.compile(r"^\\pgfsyspdfmark .*$", re.MULTILINE)
# The full compile's files restored before the second pass.
_RESTORED_EXTENSIONS = (".aux", ".toc", ".nav", ".snm", ".out", ".bbl", ".ovl")


class PartialError(Exception):
    """A page compile can't be done; the message says why."""


def parse_page_spec(spec: str) -> list[int]:
    """"4, 5, 7-10, 15" -> [4, 5, 7, 8, 9, 10, 15] (sorted, without repeats).
    Commas, semicolons or spaces separate; a range may use - or a dash."""
    numbers: set[int] = set()
    parts = [p for p in re.split(r"[,;]|\s+(?=\d)", spec.strip()) if p.strip()]
    if not parts:
        raise PartialError("No pages given.")
    for part in parts:
        m = _SPEC_PART_RE.match(part.strip())
        if not m:
            raise PartialError(f"Not a page or page range: {part.strip()!r} "
                               "(write e.g. 4, 5, 7-10, 15).")
        first = int(m.group(1))
        last = int(m.group(2)) if m.group(2) else first
        if first < 1 or last < first:
            raise PartialError(f"Not a valid range: {part.strip()!r}.")
        numbers.update(range(first, last + 1))
    return sorted(numbers)


def format_page_spec(numbers: list[int]) -> str:
    """[4, 5, 7, 8, 9, 10, 15] -> "4-5, 7-10, 15"."""
    out: list[str] = []
    start = prev = None
    for n in sorted(numbers):
        if start is None:
            start = prev = n
        elif n == prev + 1:
            prev = n
        else:
            out.append(str(start) if start == prev else f"{start}-{prev}")
            start = prev = n
    if start is not None:
        out.append(str(start) if start == prev else f"{start}-{prev}")
    return ", ".join(out)


# --------------------------------------------------------------------------
# Reading a compiled PDF

@dataclass
class PageInfo:
    index: int                   # 0-based page index in the PDF
    frame: Optional[int]         # the footer's frame number
    slide_id: Optional[str]


@dataclass
class FrameGroup:
    """Consecutive frames of one slide call (a slide file may hold several
    frames; usually it is one)."""
    slide_id: str
    frames: list[int]
    pages: dict[int, list[int]]  # frame -> its page indices


def page_infos(pdf: Path) -> list[PageInfo]:
    import pymupdf as fitz
    infos = []
    with fitz.open(pdf) as doc:
        for i, page in enumerate(doc):
            m = _FOOTER_RE.search(page.get_text())
            infos.append(PageInfo(i, int(m.group(2)) if m else None,
                                  m.group(1) if m else None))
    return infos


def frame_groups(infos: list[PageInfo]) -> list[FrameGroup]:
    groups: list[FrameGroup] = []
    for info in infos:
        if info.frame is None or info.slide_id is None:
            continue
        last = groups[-1] if groups else None
        if last is not None and info.frame in last.pages:
            last.pages[info.frame].append(info.index)
        elif last is not None and last.slide_id.lower() == info.slide_id.lower() \
                and info.frame == last.frames[-1] + 1:
            last.frames.append(info.frame)
            last.pages[info.frame] = [info.index]
        else:
            groups.append(FrameGroup(info.slide_id, [info.frame], {info.frame: [info.index]}))
    return groups


# --------------------------------------------------------------------------
# Planning

@dataclass
class KeptSlide:
    call: SlideCall
    group: FrameGroup

    @property
    def first_frame(self) -> int:
        return self.group.frames[0]

    @property
    def first_page(self) -> int:     # 1-based, as LaTeX's page counter
        return self.group.pages[self.first_frame][0] + 1


@dataclass
class PartialPlan:
    job: CompileJob
    requested: list[int]
    kept: list[KeptSlide]
    missing: list[int]              # requested numbers no slide of this version has
    full_pdf: Path
    aux: Path
    record: dict
    other_changed: list[str] = field(default_factory=list)  # slide ids changed, not asked for

    @property
    def frames(self) -> list[int]:
        return sorted(f for k in self.kept for f in k.group.frames)

    @property
    def added(self) -> list[int]:
        """Frames compiled because they belong to an asked-for slide."""
        return [f for f in self.frames if f not in self.requested]


def _deck_calls(job: CompileJob) -> list[SlideCall]:
    return list(latex_lint._calls_in(job.deck.text, job.deck.chapters))


def plan(job: CompileJob, spec: str | list[int], build_dir: Optional[Path] = None) -> PartialPlan:
    build_dir = build_dir or compiler.BUILD_DIR
    if job.chapter is not None:
        raise PartialError("Page compiles work on whole-deck versions, not per-chapter PDFs.")
    requested = parse_page_spec(spec) if isinstance(spec, str) else sorted(set(spec))
    record = compile_records.read_record(build_dir, job.jobname)
    aux = compile_records.aux_dir(build_dir, job.jobname)
    if record is None or not (aux / f"{job.jobname}.aux").is_file():
        raise PartialError(f"{job.jobname} has no whole-deck compile on record yet -- compile "
                           "the whole deck once (SlideMage v5.35.0 or later), then pages.")
    full_pdf = Path(record["pdf"])
    if not full_pdf.is_file():
        raise PartialError(f"The full PDF {full_pdf} is gone -- compile the whole deck.")
    if compile_records.sha256(full_pdf) != record.get("pdf_sha256"):
        raise PartialError(f"{full_pdf.name} was changed since it was compiled -- compile "
                           "the whole deck.")
    deck_key = compile_records.norm(job.deck.path)
    for entry in record.get("inputs", []):
        if compile_records.norm(entry["path"]) == deck_key:
            if compile_records.sha256(job.deck.path) != entry["sha256"]:
                raise PartialError(f"{job.deck.path.name} changed since its last whole-deck "
                                   "compile (a slide added, moved or removed changes the "
                                   "numbers after it) -- compile the whole deck.")
            break

    groups = frame_groups(page_infos(full_pdf))
    calls = [c for c in _deck_calls(job) if latex_lint._slide_included(c, job.version)]
    matched: list[tuple[FrameGroup, SlideCall]] = []
    unmatched: list[FrameGroup] = []   # frames not from a slide call (the generated appendix)
    ptr = 0
    for group in groups:
        found = next((i for i in range(ptr, len(calls))
                      if calls[i].id.lower() == group.slide_id.lower()), None)
        if found is None:
            unmatched.append(group)
            continue
        matched.append((group, calls[found]))
        ptr = found + 1
    by_frame = {f: (g, c) for g, c in matched for f in g.frames}
    not_slides = sorted(f for g in unmatched for f in g.frames if f in requested)
    if not_slides:
        raise PartialError(f"Page(s) {format_page_spec(not_slides)} don't come from a slide of "
                           "the deck's list (e.g. the generated appendix) -- compile the whole deck.")
    kept: list[KeptSlide] = []
    seen: set[int] = set()
    for number in requested:
        if number in by_frame:
            group, call = by_frame[number]
            if id(group) not in seen:
                seen.add(id(group))
                kept.append(KeptSlide(call, group))
    kept.sort(key=lambda k: k.first_frame)
    missing = [n for n in requested if n not in by_frame]
    if not kept:
        raise PartialError(f"No slide of {job.jobname} has the page number(s) "
                           f"{format_page_spec(requested)}.")
    result = PartialPlan(job, requested, kept, missing, full_pdf, aux, record)
    kept_ids = {k.call.id.lower() for k in kept}
    patched = record.get("patched_inputs", {})
    changed = []
    for entry in record.get("inputs", []):
        path = Path(entry["path"])
        if path.parent.name != "slides" or not path.is_file():
            continue
        slide_id = path.name.split("-", 1)[0]
        if slide_id.lower() in kept_ids:
            continue
        current = compile_records.sha256(path)
        if current != entry["sha256"] and current != patched.get(entry["path"]):
            changed.append(slide_id)
    result.other_changed = sorted(set(changed))
    return result


# --------------------------------------------------------------------------
# The wrapper

def wrapper_text(plan: PartialPlan) -> str:
    """The deck with only the kept slide calls, each preceded by the frame
    and page counters it had in the full deck. Same version settings as a
    whole-deck compile, without the generated appendix."""
    job = plan.job
    deck = job.deck
    lines: list[str] = []
    if job.version:
        lines.append(f"\\def\\deckversionoverride{{{job.version}}}")
    if not job.footer_timestamp:
        lines.append("\\def\\SMFooterTimestampOverride{0}")
    if job.presenter:
        lines.append("\\def\\SMPresenterModeOverride{1}")
    if job._appendix_applies:
        # the appendix itself isn't generated (its pages stay as they are),
        # but the footers' "Slide previews" link to it must be there
        lines.append("\\def\\SMAppendixTocOverride{1}")
    if job.run_id:
        lines.append(compile_records.run_id_line(job.run_id))
    text = deck.text
    if deck.preamble_end is None:
        raise PartialError(f"{deck.name}: no \\begin{{document}}")
    end = compiler.DOCUMENT_END_RE.search(text, deck.preamble_end)
    body_end = end.start() if end else len(text)
    kept = {k.call.line_start: k for k in plan.kept}
    out: list[str] = [text[:deck.preamble_end]]
    pos = deck.preamble_end
    for call in sorted(_deck_calls(job), key=lambda c: c.line_start):
        if call.line_start < pos or call.line_start >= body_end:
            continue
        out.append(text[pos:call.line_start])
        keep = kept.get(call.line_start)
        if keep is not None:
            out.append(f"\\setcounter{{framenumber}}{{{keep.first_frame - 1}}}"
                       f"\\setcounter{{page}}{{{keep.first_page}}}%\n")
            out.append(text[call.line_start:call.line_end])
        pos = call.line_end
    out.append(text[pos:body_end])
    out.append("\\end{document}\n")
    return "\n".join(lines) + ("\n" if lines else "") + "".join(out)


# --------------------------------------------------------------------------
# Compiling

@dataclass
class PartialOutput:
    pdf: Path
    build_dir: Path
    infos: list[PageInfo]


def _restore_full_aux(plan: PartialPlan, build: Path, first_pass: Optional[Path]) -> None:
    jobname = plan.job.jobname
    marks = ""
    tops = ""
    if first_pass is not None:
        aux = build / f"{jobname}.aux"
        if aux.is_file():
            marks = "\n".join(_PGF_MARK_RE.findall(aux.read_text(encoding="utf-8", errors="replace")))
        top = build / f"{jobname}.top"
        if top.is_file():
            tops = top.read_text(encoding="utf-8", errors="replace")
    for ext in _RESTORED_EXTENSIONS:
        src = plan.aux / f"{jobname}{ext}"
        if src.is_file():
            shutil.copy2(src, build / src.name)
    if marks:
        with open(build / f"{jobname}.aux", "a", encoding="utf-8") as f:
            f.write("\n" + marks + "\n")
    full_top = plan.aux / f"{jobname}.top"
    merged = full_top.read_text(encoding="utf-8", errors="replace") if full_top.is_file() else ""
    (build / f"{jobname}.top").write_text(merged + ("\n" + tops if tops else ""), encoding="utf-8")


def run(plan: PartialPlan, log: LogCallback, cancel: Optional[CancelToken] = None,
        build_root: Optional[Path] = None, project_root: Optional[Path] = None) -> PartialOutput:
    """Two passes over the page wrapper on top of the full compile's
    auxiliary files (see the module docstring). Raises PartialError."""
    build_root = build_root or compiler.BUILD_DIR
    project_root = project_root or compiler.PROJECT_ROOT
    job = plan.job
    jobname = job.jobname
    invocation = uuid.uuid4().hex
    build = build_root / f"pages-{jobname}-{invocation}"
    build.mkdir(parents=True)
    compiler._set_build_dir_active(build, True)
    wrapper = job.deck.path.parent / f"_slidemage_{jobname}-pages_{invocation}.tex"
    wrapper.write_text(wrapper_text(plan), encoding="utf-8", newline="")
    try:
        _restore_full_aux(plan, build, None)
        out = build.resolve().as_posix()
        cmd = ["latexmk", "-g", "-f", "-e", "$max_repeat=1", "-e", "$bibtex_use=0",
               f"-jobname={jobname}", f"-auxdir={out}", f"-outdir={out}",
               os.path.relpath(wrapper, project_root)]
        env = compiler._build_env()
        kwargs = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
        for number in (1, 2):
            if number == 2:
                _restore_full_aux(plan, build, build)
            log(f"    (page compile of {jobname}: pass {number} of 2)")
            try:
                proc = subprocess.Popen(cmd, cwd=project_root, env=env, stdout=subprocess.PIPE,
                                        stderr=subprocess.STDOUT, text=True, errors="replace",
                                        bufsize=1, **kwargs)
            except FileNotFoundError as exc:
                raise PartialError("latexmk not found on PATH") from exc
            if cancel is not None:
                cancel._set_process(proc)
            try:
                assert proc.stdout is not None
                for line in proc.stdout:
                    log(line.rstrip("\n"))
                proc.wait()
            finally:
                if cancel is not None:
                    cancel._set_process(None)
            if cancel is not None and cancel.is_set():
                raise PartialError("stopped by user")
        pdf = build / f"{jobname}.pdf"
        log_path = build / f"{jobname}.log"
        log_text = log_path.read_text(encoding="utf-8", errors="replace") if log_path.is_file() else ""
        if not pdf.is_file() or not log_text or FATAL_ERROR_RE.search(log_text):
            raise PartialError(f"{jobname} (pages) did not compile -- see {log_path}")
        return PartialOutput(pdf, build, page_infos(pdf))
    finally:
        wrapper.unlink(missing_ok=True)
        compiler._set_build_dir_active(build, False)


# --------------------------------------------------------------------------
# Putting the pages into the full PDF

@dataclass
class PatchResult:
    replaced: list[int] = field(default_factory=list)      # frames swapped in
    mismatched: list[int] = field(default_factory=list)    # page count changed
    separate_pdf: Optional[Path] = None


def new_pages_of(plan: PartialPlan, output: PartialOutput) -> list[list[int]]:
    """Per kept slide (plan.kept order), its pages in the page compile's PDF:
    those with its slide id from its first frame up to the next kept slide's
    (other pages -- frames written directly in the deck file -- don't count)."""
    result = []
    for i, keep in enumerate(plan.kept):
        upper = plan.kept[i + 1].first_frame if i + 1 < len(plan.kept) else None
        result.append([info.index for info in output.infos
                       if info.slide_id and info.slide_id.lower() == keep.call.id.lower()
                       and info.frame is not None and info.frame >= keep.first_frame
                       and (upper is None or info.frame < upper)])
    return result


def page_mapping(plan: PartialPlan, output: PartialOutput
                 ) -> tuple[dict[int, int], list[int]]:
    """{page compile's page index: full PDF page index} for every kept slide
    whose number of pages is unchanged, and the frames of the slides whose
    number changed (they can't be swapped in place)."""
    mapping: dict[int, int] = {}
    mismatched: list[int] = []
    for keep, new_pages in zip(plan.kept, new_pages_of(plan, output)):
        old_pages = [i for f in keep.group.frames for i in keep.group.pages[f]]
        if len(old_pages) != len(new_pages):
            mismatched.extend(keep.group.frames)
            continue
        mapping.update(zip(new_pages, old_pages))
    return mapping, sorted(mismatched)


def _retarget_link(link: dict, mapping: dict[int, int], names: dict) -> Optional[dict]:
    import pymupdf as fitz
    new = {k: v for k, v in link.items() if k not in ("xref", "id", "zoom")}
    kind = link.get("kind")
    if kind == fitz.LINK_URI:
        return new
    if kind == fitz.LINK_GOTO and link.get("page", -1) in mapping:
        new["page"] = mapping[link["page"]]
        return new
    name = link.get("nameddest") or link.get("name")
    if name and name in names and names[name].get("page", -1) >= 0:
        target = {"kind": fitz.LINK_GOTO, "from": link["from"], "page": names[name]["page"]}
        if "to" in names[name]:
            target["to"] = fitz.Point(names[name]["to"])
        return target
    return None


def write_pages(src: Path, pages: list[int], target: Path) -> Path:
    import pymupdf as fitz
    with fitz.open(src) as doc, fitz.open() as out:
        for index in pages:
            out.insert_pdf(doc, from_page=index, to_page=index)
        out.save(target, garbage=3, deflate=True)
    return target


def patch(plan: PartialPlan, output: PartialOutput, log: LogCallback) -> PatchResult:
    """Swap the new pages into the full PDF (see the module docstring)."""
    import pymupdf as fitz
    result = PatchResult()
    mapping, mismatched = page_mapping(plan, output)
    result.mismatched = mismatched
    full_pdf = plan.full_pdf
    if mapping:
        tmp = full_pdf.with_name(f".{full_pdf.name}.slidemage-{uuid.uuid4().hex}.tmp")
        try:
            with fitz.open(full_pdf) as full, fitz.open(output.pdf) as part:
                names = full.resolve_names()
                for new_index, old_index in sorted(mapping.items()):
                    page = full[old_index]
                    for link in page.get_links():
                        page.delete_link(link)
                    for xref in page.get_contents():
                        full.update_stream(xref, b"")
                    page.show_pdf_page(page.rect, part, new_index)
                    for link in part[new_index].get_links():
                        target = _retarget_link(link, mapping, names)
                        if target is not None:
                            page.insert_link(target)
                if plan.job.run_id:
                    # the patched PDF now belongs to this compile run ("Open pdf")
                    compile_records.stamp_run_id(full, plan.job.run_id)
                full.save(tmp, garbage=3, deflate=True)
            from .deck_snapshot import replace_with_retry
            replace_with_retry(tmp, full_pdf)
        finally:
            tmp.unlink(missing_ok=True)
        result.replaced = sorted({f for k in plan.kept for f in k.group.frames} - set(mismatched))
        _note_patch(plan, result)
    if mismatched:
        pages = sorted(i for keep, new_pages in zip(plan.kept, new_pages_of(plan, output))
                       if keep.first_frame in mismatched for i in new_pages)
        if pages:
            target = full_pdf.with_name(f"{full_pdf.stem}-pages-"
                                        f"{format_page_spec(mismatched).replace(', ', '_')}.pdf")
            result.separate_pdf = write_pages(output.pdf, pages, target)
    return result


def _note_patch(plan: PartialPlan, result: PatchResult) -> None:
    """The record keeps vouching for the full PDF's identity (its new hash),
    so another page compile can follow; its input hashes stay those of the
    whole-deck compile, so the PDF no longer counts as unchanged."""
    import json
    from datetime import datetime
    record = dict(plan.record)
    record["pdf_sha256"] = compile_records.sha256(plan.full_pdf)
    record.setdefault("patched", []).append({
        "frames": result.replaced,
        "time": datetime.now().astimezone().isoformat(timespec="seconds")})
    # the slide files whose pages are now in the PDF, as they were swapped in
    # (only for the "changed but not recompiled" list -- the input hashes stay
    # those of the whole-deck compile)
    swapped = {k.call.source_filename for k in plan.kept
               if set(k.group.frames) <= set(result.replaced)}
    patched_inputs = record.setdefault("patched_inputs", {})
    for entry in record.get("inputs", []):
        path = Path(entry["path"])
        if path.name in swapped and path.is_file():
            patched_inputs[entry["path"]] = compile_records.sha256(path)
    path = compile_records.record_path(compiler.BUILD_DIR, plan.job.jobname)
    path.write_text(json.dumps(record, indent=1) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------
# One page job, end to end (compiler.run_job calls this for job.pages)

def run_page_job(job: CompileJob, log: LogCallback, cancel: Optional[CancelToken] = None) -> bool:
    """Compile `job.pages` of `job` and put them into the full PDF (or, with
    job.replace_pages False, into <full pdf>-pages-<spec>.pdf). Logs the
    usual "==== Compiling ... ====" / PASS / FAIL lines."""
    jobname = job.jobname
    log(f"==== Compiling {job.deck.name} -> {jobname} ====")
    try:
        the_plan = plan(job, job.pages or [])
        if the_plan.missing:
            log(f"    (no slide of this version has the number(s) "
                f"{format_page_spec(the_plan.missing)})")
        if the_plan.added:
            log(f"    (also compiled, as part of the same slides: "
                f"{format_page_spec(the_plan.added)})")
        log(f"    (compiling pages {format_page_spec(the_plan.frames)} of {jobname}: "
            f"{', '.join(k.call.id for k in the_plan.kept)})")
        output = run(the_plan, log, cancel)
        try:
            if job.replace_pages:
                result = patch(the_plan, output, log)
                where = the_plan.full_pdf
                if result.replaced:
                    log(f"    (replaced pages {format_page_spec(result.replaced)} in {where.name})")
                if result.mismatched:
                    log(f"    *** pages {format_page_spec(result.mismatched)}: the slide now has a "
                        "different number of pages, so it can't be swapped in -- see "
                        f"{result.separate_pdf.name if result.separate_pdf else 'the log'}; "
                        "compile the whole deck to include it ***")
            else:
                pages = sorted(i for g in frame_groups(output.infos)
                               for f, idx in g.pages.items() if f in the_plan.frames for i in idx)
                where = the_plan.full_pdf.with_name(
                    f"{the_plan.full_pdf.stem}-pages-"
                    f"{format_page_spec(the_plan.frames).replace(', ', '_')}.pdf")
                write_pages(output.pdf, pages, where)
        finally:
            shutil.rmtree(output.build_dir, ignore_errors=True)
        if the_plan.other_changed:
            log(f"    (not recompiled, but changed since the whole-deck compile: "
                f"{', '.join(the_plan.other_changed)})")
        log(f"==== PASS: {jobname} -> {compiler._display_path(where)} ====")
        return True
    except PartialError as exc:
        log(f"*** FAIL: {jobname} -- {exc} ***")
        return False
