"""What a compile read, so a later deck snapshot can tell whether that PDF is
still current (v5.34.0, direct instruction: "Is there a way to check whether
there were any changes since the last time a particular version was compiled,
like a hash? That would avoid re-creating everything when fresh copies are
already available.").

After every successful whole-deck compile (compiler.py), SlideMage keeps a
record of it in .build/compile-records/<jobname>.json:

- the SHA-256 of every file the compile read -- latexmk's -recorder list
  (.fls: deck, slides, snippets, media, image descriptions, template,
  framework, TeX packages) plus the .bib files biber read (.blg);
- the SHA-256 of the wrapper file the compile ran (deck version, presenter
  mode, footer timestamp and appendix choices, the generated appendix);
- the TeX engine's version line;
- the footer timestamp the compile printed, the time it started, and the
  published PDF's path and SHA-256.

deck_snapshot.py asks fresh_output() for each version it needs: when every
recorded file still has its hash, the wrapper and engine are the same, and
the PDF is unchanged where it was published, that PDF is used as the
snapshot's reference instead of compiling the version again.

Not recorded (the record is simply not written): a compile during which one
of the files it read changed (its PDF may show the older or the newer
content), and one whose bibliography wasn't built. luaotfload's font caches
are left out of the hashes: they are derived files, rewritten by other
compiles. A file a compile looked for but didn't find is not in the .fls;
if it appears later, the record doesn't notice -- the snapshot then freezes
the deck as of that compile, consistently.

The records hold machine-specific paths (the TeX installation), so they live
in .build/ ("Remove temp files" deletes them; the next snapshot then compiles
every version again). Free of Qt and of compiler.py (which imports this).
"""
from __future__ import annotations

import functools
import hashlib
import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

RECORD_FORMAT = 1
RECORDS_DIRNAME = "compile-records"
# The auxiliary files kept with a record (aux_dir()).
DECK_COPY_NAME = "deck.tex"
AUX_EXTENSIONS = (".aux", ".nav", ".toc", ".snm", ".out", ".bbl", ".top", ".ovl", ".timestamp")

# Matches the .log's "Package: beamer 2025/06/02 v3.75 ..." family of lines.
LOG_FILE_LINE_RE = re.compile(
    r"^(?:Package|Document Class|File): (\S+) (\d{4}[/-]\d\d[/-]\d\d)\s*(.*)$", re.MULTILINE)
LOG_FORMAT_RE = re.compile(r"^(LaTeX2e <[^>]+>.*|L3 programming layer <[^>]+>.*)$", re.MULTILINE)
BLG_SOURCE_RE = re.compile(r"Found BibTeX data source '([^']+)'")
# biblatex's final-pass log says this when the .bbl is missing or stale, i.e.
# biber failed -- the PDF then shows citation keys instead of references.
BIBER_NEEDED_RE = re.compile(r"Package biblatex Warning: Please \(re\)run Biber")
# Derived caches the engine may rewrite at any time -- never part of a hash.
_SKIPPED_INPUT_PARTS = ("luatex-cache",)
# Files derived from the deck's own slides (the slide previews a generated
# appendix shows): copied into the record (DERIVED_DIRNAME) as read, not
# compared -- they change with every compile of a slide that shows a time.
_DERIVED_INPUT_PARTS = (".previews",)
DERIVED_DIRNAME = "derived"


# --------------------------------------------------------------------------
# Paths, hashes, .fls

def norm(path: Path | str) -> str:
    return os.path.normcase(os.path.normpath(str(path)))


def is_within(path: Path | str, root: Path | str) -> bool:
    """`path` is `root` or below it, compared the way the OS does (case-
    insensitive on Windows, where .fls paths also mix "d:" and "D:")."""
    p, r = norm(path), norm(root)
    return p == r or p.startswith(r.rstrip("\\/") + os.sep)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------
# The compile run a PDF belongs to (2026-10-08, direct instruction)

RUN_INFO_KEY = "SlideMageRun"
_RUN_LINE_RE = re.compile(r"^\\pdfextension info\{/" + RUN_INFO_KEY + r" \([^)]*\)\}\r?\n?",
                          re.MULTILINE)


def run_id_line(run_id: str) -> str:
    """The wrapper line that puts `run_id` (the moment the compile was
    started) into the PDF's info dictionary."""
    return f"\\pdfextension info{{/{RUN_INFO_KEY} ({run_id})}}"


def wrapper_sha256(wrapper_text: str) -> str:
    """The hash a record keeps of a wrapper: without the run line, which
    differs on every click but doesn't change the output."""
    return text_sha256(_RUN_LINE_RE.sub("", wrapper_text))


def read_run_id(pdf: Path) -> Optional[str]:
    """The /SlideMageRun of a PDF's info dictionary, or None (a PDF from
    before v5.34.0, or not made by SlideMage)."""
    import pymupdf as fitz
    try:
        with fitz.open(pdf) as doc:
            kind, ref = doc.xref_get_key(-1, "Info")
            if kind != "xref":
                return None
            kind, value = doc.xref_get_key(int(ref.split()[0]), RUN_INFO_KEY)
    except Exception:  # noqa: BLE001 -- an unreadable PDF just has no run
        return None
    return value if kind == "string" and value else None


def stamp_run_id(doc, run_id: str) -> None:
    """Set /SlideMageRun in an open PyMuPDF document's info dictionary (a
    page compile patching a PDF makes it part of its own run)."""
    kind, ref = doc.xref_get_key(-1, "Info")
    if kind != "xref":
        doc.set_metadata(doc.metadata or {})
        kind, ref = doc.xref_get_key(-1, "Info")
    xref = int(ref.split()[0])
    doc.xref_set_key(xref, RUN_INFO_KEY, "(" + run_id.replace("(", "").replace(")", "") + ")")


def parse_fls(fls: Path) -> list[Path]:
    """Every file a compile read (INPUT lines of latexmk's -recorder .fls),
    absolute and normalized, in first-read order, without duplicates.
    Relative entries are relative to the .fls's own PWD line."""
    pwd: Optional[Path] = None
    seen: dict[str, Path] = {}
    for line in fls.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("PWD "):
            pwd = Path(line[4:].strip())
        elif line.startswith("INPUT "):
            raw = Path(line[6:].strip())
            if not raw.is_absolute():
                raw = (pwd or fls.parent) / raw
            path = Path(os.path.normpath(str(raw)))
            seen.setdefault(norm(path), path)
    return list(seen.values())


def parse_blg_sources(blg: Path) -> list[Path]:
    """The .bib files biber read (its .blg log names them)."""
    try:
        text = blg.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    return [Path(os.path.normpath(m.group(1))) for m in BLG_SOURCE_RE.finditer(text)]


def version_lines(log_text: str) -> str:
    """The lines of a .log that name the LaTeX format and the package
    versions -- what a snapshot records about the TeX distribution."""
    lines = [m.group(0) for m in LOG_FORMAT_RE.finditer(log_text)]
    lines += [m.group(0) for m in LOG_FILE_LINE_RE.finditer(log_text)]
    return "\n".join(lines) + ("\n" if lines else "")


def _popen_kwargs() -> dict:
    return {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}


@functools.lru_cache(maxsize=1)
def engine_version() -> str:
    """lualatex's version line ("This is LuaHBTeX, Version 1.22.0 (MiKTeX
    25.4)"), once per run of SlideMage; "" if it can't be run."""
    try:
        result = subprocess.run(["lualatex", "--version"], capture_output=True, text=True,
                                errors="replace", timeout=30, **_popen_kwargs())
    except (OSError, subprocess.SubprocessError):
        return ""
    lines = result.stdout.splitlines() if result.returncode == 0 else []
    return lines[0].strip() if lines else ""


# --------------------------------------------------------------------------
# Records

@dataclass
class FreshOutput:
    """A recorded compile that is still current."""
    jobname: str
    pdf: Path
    inputs: list[Path]
    bib_sources: list[Path]
    log_text: str            # the format and package lines of its .log
    timestamp: Optional[str]  # the .timestamp file's text
    started: int              # Unix time the compile started
    created: str              # ISO time the record was written
    # norm(original path) -> the copy kept in the record (slide previews):
    # what a snapshot must use instead of the current file
    copies: dict[str, Path] = field(default_factory=dict)


@dataclass
class Staleness:
    """Why a record can't be used (for the log)."""
    reasons: list[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.reasons)


def records_dir(build_dir: Path) -> Path:
    return build_dir / RECORDS_DIRNAME


def record_path(build_dir: Path, jobname: str) -> Path:
    return records_dir(build_dir) / f"{jobname}.json"


def aux_dir(build_dir: Path, jobname: str) -> Path:
    """Where a recorded compile's auxiliary files are kept."""
    return records_dir(build_dir) / jobname


def write_record(
    build_dir: Path, jobname: str, invocation_dir: Path, wrapper_path: Path, wrapper_text: str,
    pdf: Path, started: float, log: Optional[Callable[[str], None]] = None,
    deck_path: Optional[Path] = None,
) -> Optional[Path]:
    """Record a successful compile whose output sits in `invocation_dir` and
    whose PDF was published as `pdf`. Returns the record's path, or None when
    it isn't recorded (see the module docstring); an old record of the same
    job is removed then, so it can't vouch for a PDF it doesn't describe."""
    log = log or (lambda _line: None)
    target = record_path(build_dir, jobname)
    try:
        fls = invocation_dir / f"{jobname}.fls"
        log_file = invocation_dir / f"{jobname}.log"
        log_text = log_file.read_text(encoding="utf-8", errors="replace")
        if not fls.is_file() or BIBER_NEEDED_RE.search(log_text):
            target.unlink(missing_ok=True)
            return None
        bib_sources = parse_blg_sources(invocation_dir / f"{jobname}.blg")
        aux = aux_dir(build_dir, jobname)
        shutil.rmtree(aux, ignore_errors=True)
        aux.mkdir(parents=True)
        entries = []
        seen: set[str] = set()
        inline_inputs = [deck_path] if deck_path is not None else []
        if deck_path is not None and deck_path.is_file():
            from . import deck_language, deck_scan
            deck = next((d for d in deck_scan._scan_dir(deck_path.parent, False) if d.path == deck_path), None)
            if deck is not None:
                # Include dependencies in either language: the wrapper can inline
                # a shared slide list instead of having TeX open its original file.
                for language in ("EN", "DE"):
                    _resolved, inputs = deck_language.compile_deck(deck, language)
                    inline_inputs.extend(inputs)
        for path in [*parse_fls(fls), *bib_sources, *inline_inputs]:
            key = norm(path)
            if key in seen or is_within(path, invocation_dir) or key == norm(wrapper_path):
                continue
            seen.add(key)
            if any(part in key for part in _SKIPPED_INPUT_PARTS) or not path.is_file():
                continue
            if any(part in Path(key).parts for part in _DERIVED_INPUT_PARTS):
                # A slide preview (the generated appendix's thumbnails): kept as
                # this compile read it, never a reason to call the PDF stale.
                copy = Path(DERIVED_DIRNAME) / f"{len(entries)}-{path.name}"
                (aux / copy).parent.mkdir(exist_ok=True)
                shutil.copy2(path, aux / copy)
                entries.append({"path": str(path), "sha256": sha256(aux / copy),
                                "copy": copy.as_posix()})
                continue
            if path.stat().st_mtime > started:
                log(f"    (compile not recorded for snapshots: {path.name} changed during it)")
                shutil.rmtree(aux, ignore_errors=True)
                target.unlink(missing_ok=True)
                return None
            entries.append({"path": str(path), "sha256": sha256(path)})
        stamp = invocation_dir / f"{jobname}.timestamp"
        record = {
            "format": RECORD_FORMAT,
            "jobname": jobname,
            "created": datetime.now().astimezone().isoformat(timespec="seconds"),
            "started": int(started),
            "engine": engine_version(),
            "wrapper_sha256": wrapper_sha256(wrapper_text),
            "pdf": str(pdf),
            "pdf_sha256": sha256(pdf),
            "timestamp": stamp.read_text(encoding="utf-8") if stamp.is_file() else None,
            "bib_sources": [str(p) for p in bib_sources],
            "log_lines": version_lines(log_text),
            "inputs": entries,
        }
        target.parent.mkdir(parents=True, exist_ok=True)
        # The compile's auxiliary files, for page-range compiles (partial_compile.py):
        # cross-references, contents, the frame/page map, citations, layout fixes.
        for ext in AUX_EXTENSIONS:
            src = invocation_dir / f"{jobname}{ext}"
            if src.is_file():
                shutil.copy2(src, aux / src.name)
        # the deck file as compiled: a page compile may go ahead when the deck
        # changed only after the slides it compiles (partial_compile.plan)
        if deck_path is not None and deck_path.is_file():
            shutil.copy2(deck_path, aux / DECK_COPY_NAME)
        tmp = target.with_name(target.name + ".tmp")
        tmp.write_text(json.dumps(record, indent=1) + "\n", encoding="utf-8")
        os.replace(tmp, target)
        return target
    except (OSError, ValueError) as exc:
        log(f"    (compile not recorded for snapshots: {exc})")
        try:
            target.unlink(missing_ok=True)
        except OSError:
            pass
        return None


def read_record(build_dir: Path, jobname: str) -> Optional[dict]:
    try:
        data = json.loads(record_path(build_dir, jobname).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("format") != RECORD_FORMAT:
        return None
    return data


def check_record(record: dict, wrapper_text: str, aux: Optional[Path] = None) -> Staleness:
    """Why `record` no longer describes what a compile with `wrapper_text`
    would produce now (empty when it still does). `aux`: the record's folder,
    holding the copies of derived inputs."""
    stale = Staleness()
    if record.get("wrapper_sha256") != wrapper_sha256(wrapper_text):
        stale.reasons.append("the deck's version settings changed")
    current_engine = engine_version()
    if current_engine and record.get("engine") != current_engine:
        stale.reasons.append("the TeX engine changed")
    pdf = Path(record.get("pdf", ""))
    if not pdf.is_file():
        stale.reasons.append(f"{pdf.name} is gone")
    elif sha256(pdf) != record.get("pdf_sha256"):
        stale.reasons.append(f"{pdf.name} was replaced")
    if stale:
        return stale
    for entry in record.get("inputs", []):
        path = Path(entry["path"])
        if entry.get("copy"):
            copy = (aux / entry["copy"]) if aux is not None else None
            if copy is None or not copy.is_file() or sha256(copy) != entry["sha256"]:
                stale.reasons.append(f"the kept copy of {path.name} is missing")
        elif not path.is_file():
            stale.reasons.append(f"{path.name} is gone")
        elif sha256(path) != entry["sha256"]:
            stale.reasons.append(f"{path.name} changed")
        if len(stale.reasons) >= 3:
            break
    return stale


def fresh_output(build_dir: Path, jobname: str, wrapper_text: str
                 ) -> tuple[Optional[FreshOutput], str]:
    """The recorded compile of `jobname` if it is still current, else None,
    with a short reason for the log ("no record", "slide x changed", ...)."""
    record = read_record(build_dir, jobname)
    if record is None:
        return None, "no compile on record"
    aux = aux_dir(build_dir, jobname)
    stale = check_record(record, wrapper_text, aux)
    if stale:
        return None, ", ".join(stale.reasons)
    return FreshOutput(
        jobname=jobname, pdf=Path(record["pdf"]),
        inputs=[Path(e["path"]) for e in record["inputs"]],
        bib_sources=[Path(p) for p in record.get("bib_sources", [])],
        log_text=record.get("log_lines", ""), timestamp=record.get("timestamp"),
        started=int(record.get("started", 0)), created=str(record.get("created", "")),
        copies={norm(e["path"]): aux / e["copy"] for e in record["inputs"] if e.get("copy")},
    ), ""
