# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Where SlideMage's own `logging` output goes (docs/plans/debug-log.md).

`setup(role)` runs once at the start of every SlideMage process (cli.main): the app, a Claude Code hook, a plugin
entry point, the preview rasteriser. It gives the `slidemage` logger the error log: warnings, errors and uncaught
exceptions of every process, in `logs/slidemage.log` in SlideMage's cache folder (not roaming), kept below
MAX_BYTES with BACKUPS older files (.1 is the newest). SLIDEMAGE_LOG_DIR names another folder. While the process
has a console, the same lines also go to stderr, as Python's last-resort handler did before. The windowed build
has none, which is why nothing logged reached anyone before v0.12.3.

One line per record, in fixed columns: time, seconds since the process started, level, area (the logger name
without `slidemage.`), role:pid, thread, message. A traceback follows, indented. API keys and tokens are masked
before a line is written (`redact`). No Qt here: `install_qt_message_handler` imports PySide6 only when called.

The debug log (step 2 of the plan): with debug on, the `slidemage` logger takes everything from DEBUG up and a
second file gets it all. The app writes one file per session, `logs/debug/app_<date>_<time>_<pid>.log`, starting
with a header of what produced it; a hook, a plugin entry point and the rasteriser, which start often and live
briefly, share one file per role (`hook.log`, ...). At the start of an app session the oldest files go beyond
KEEP_SESSIONS app sessions or KEEP_BYTES in all. Debug is on when SLIDEMAGE_DEBUG says so (1/0), else when the
saved setting (`diagnostics.json` in the config folder, `set_debug`) says so; `--debug` sets SLIDEMAGE_DEBUG=1
for the process and so for everything it starts. A process reads the setting when it starts: a hook follows a
change at once, a process already running only through `set_debug` in itself.
"""
from __future__ import annotations

import logging
import os
import re
import sys
import threading
import time
from contextlib import contextmanager
from functools import wraps
from pathlib import Path
from typing import Optional

LOGGER = "slidemage"
DIR_ENV = "SLIDEMAGE_LOG_DIR"
ERROR_LOG = "slidemage.log"
MAX_BYTES = 1024 * 1024
BACKUPS = 3
# Environment variables whose values never appear in a log line, wherever they turn up.
SECRET_ENV_VARS = ("ANTHROPIC_API_KEY", "SLIDEMAGE_GITHUB_TOKEN")
REDACTED = "[redacted]"
_TOKEN_SHAPES = re.compile(
    r"sk-ant-[A-Za-z0-9_\-]{8,}"                    # Anthropic API keys
    r"|\bsk-[A-Za-z0-9_\-]{16,}"                    # other sk- keys
    r"|\bgh[pousr]_[A-Za-z0-9]{20,}"                # GitHub tokens
    r"|\bgithub_pat_[A-Za-z0-9_]{20,}"              # GitHub fine-grained tokens
    r"|(?<=[Bb]earer )[A-Za-z0-9._\-~+/=]{12,}")    # an Authorization header's value
MIN_SECRET_CHARS = 8
DEBUG_ENV = "SLIDEMAGE_DEBUG"
DEBUG_FLAG = "--debug"
SETTINGS_FILE = "diagnostics.json"
DEBUG_DIR = "debug"
SESSION_MAX_BYTES = 10 * 1024 * 1024
SESSION_BACKUPS = 1
KEEP_SESSIONS = 20
KEEP_BYTES = 100 * 1024 * 1024
_TRUE, _FALSE = {"1", "true", "on", "yes"}, {"0", "false", "off", "no"}
TIMING_ENV = "SLIDEMAGE_TIMING"

_secrets: set[str] = set()
_state: Optional[dict] = None
_lock = threading.Lock()


def log_dir() -> Path:
    from . import project

    override = os.environ.get(DIR_ENV, "").strip()
    return Path(override) if override else project.cache_dir() / "logs"


def settings_path() -> Path:
    from . import project

    return project.config_dir() / SETTINGS_FILE


def forced() -> Optional[bool]:
    """What SLIDEMAGE_DEBUG says: True, False, or None when it is not set (or says nothing clear). Without it,
    SLIDEMAGE_TIMING=1 (timing.py's switch before v0.13.7) turns the debug log on."""
    value = os.environ.get(DEBUG_ENV, "").strip().lower()
    if not value and os.environ.get(TIMING_ENV) == "1":
        return True
    return True if value in _TRUE else False if value in _FALSE else None


def saved() -> bool:
    """The setting: on until it is turned off (decision D1), for this computer's SlideMage, every project."""
    import json

    try:
        return json.loads(settings_path().read_text(encoding="utf-8")).get("debug") is True
    except (OSError, ValueError, AttributeError):
        return False


def wanted() -> bool:
    on = forced()
    return saved() if on is None else on


def _field(value) -> str:
    text = str(value)
    return repr(text) if not text or " " in text else text


def event(logger: logging.Logger, message: str, **fields) -> None:
    """One debug line, `message key=value ...`, the same way everywhere; nothing is built while the log is off."""
    if logger.isEnabledFor(logging.DEBUG):
        logger.debug("%s%s", message, "".join(f" {key}={_field(value)}" for key, value in fields.items()))


@contextmanager
def timed(logger: logging.Logger, message: str, **fields):
    """An `event` when the block ends, with its seconds and, if it raised, the error (the HTTP code too). The block
    gets the fields as a dict and may add to them."""
    if not logger.isEnabledFor(logging.DEBUG):
        yield {}
        return
    started = time.monotonic()
    info = dict(fields)
    try:
        yield info
    except BaseException as exc:
        code = getattr(exc, "code", None)
        info["error"] = f"{type(exc).__name__} {code}" if code is not None else type(exc).__name__
        raise
    finally:
        event(logger, message, **info, seconds=round(time.monotonic() - started, 3))


def logged(area: str):
    """A decorator: a `timed` line in `area`, named after the function, each time it runs."""
    logger = logging.getLogger(f"{LOGGER}.{area}")

    def wrap(function):
        @wraps(function)
        def run(*args, **kwargs):
            with timed(logger, function.__name__):
                return function(*args, **kwargs)
        return run
    return wrap


def add_secret(value: str) -> None:
    """Mask `value` in every line from now on (a key read from the credential store, say)."""
    if value and len(value.strip()) >= MIN_SECRET_CHARS:
        _secrets.add(value.strip())


def redact(text: str) -> str:
    for value in sorted(_secrets, key=len, reverse=True):
        text = text.replace(value, REDACTED)
    return _TOKEN_SHAPES.sub(REDACTED, text)


class LineFormatter(logging.Formatter):
    def __init__(self, role: str) -> None:
        super().__init__()
        self.role = role

    def format(self, record: logging.LogRecord) -> str:
        stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(record.created)) + f".{int(record.msecs):03d}"
        area = record.name[len(LOGGER) + 1:] if record.name.startswith(LOGGER + ".") else record.name
        head = (f"{stamp} +{record.relativeCreated / 1000:.3f}s {record.levelname:<8} {area:<18} "
                f"{self.role}:{record.process} {record.threadName}  ")
        lines = record.getMessage().splitlines() or [""]
        if record.exc_info:
            lines += self.formatException(record.exc_info).splitlines()
        if record.stack_info:
            lines += self.formatStack(record.stack_info).splitlines()
        return redact(head + lines[0] + "".join("\n    " + line for line in lines[1:]))


class RotatingFile(logging.FileHandler):
    """A FileHandler that moves a full file to .1 (and .1 to .2, ...) before writing on. No logging.handlers: that
    module imports socket and pickle, and a Claude Code hook starts in a few dozen milliseconds. A file another
    process holds open on Windows cannot be moved; it is then written on and moved by a later write."""

    def __init__(self, path: Path, max_bytes: int = MAX_BYTES, backups: int = BACKUPS) -> None:
        super().__init__(path, mode="a", encoding="utf-8", delay=True)
        self.max_bytes = max_bytes
        self.backups = backups

    def _open(self):
        Path(self.baseFilename).parent.mkdir(parents=True, exist_ok=True)
        return super()._open()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            if self.stream is None:
                self.stream = self._open()
            if self.stream.tell() >= self.max_bytes:
                self._roll()
        except OSError:
            pass                     # a log is never a reason for SlideMage to fail
        super().emit(record)

    def _roll(self) -> None:
        self.stream.close()
        self.stream = None
        base = self.baseFilename
        try:
            for number in range(self.backups - 1, 0, -1):
                if os.path.exists(f"{base}.{number}"):
                    os.replace(f"{base}.{number}", f"{base}.{number + 1}")
            os.replace(base, f"{base}.1")
        except OSError:
            pass


class _NotUncaught(logging.Filter):
    """For the console: an uncaught exception's traceback is printed there by the previous hook already."""

    def filter(self, record: logging.LogRecord) -> bool:
        return not getattr(record, "uncaught", False)


def setup(role: str = "app", debug: Optional[bool] = None) -> None:
    """Attach the error log (and the console, if there is one) to the `slidemage` logger, catch uncaught
    exceptions, and start the debug log when it is wanted (`debug` None: `wanted()`; True: `--debug`, passed on to
    child processes). Once per process; later calls do nothing. `role` names the process in every line."""
    global _state
    with _lock:
        if _state is not None:
            return
        if debug:
            os.environ[DEBUG_ENV] = "1"
        for name in SECRET_ENV_VARS:
            add_secret(os.environ.get(name, ""))
        formatter = LineFormatter(role)
        handlers = []
        try:
            error_log = RotatingFile(log_dir() / ERROR_LOG)
        except OSError:
            error_log = None
        if error_log is not None:
            error_log.setLevel(logging.WARNING)
            handlers.append(error_log)
        if sys.stderr is not None:
            console = logging.StreamHandler(sys.stderr)
            console.setLevel(logging.WARNING)
            console.addFilter(_NotUncaught())
            handlers.append(console)
        logger = logging.getLogger(LOGGER)
        for handler in handlers:
            handler.setFormatter(formatter)
            logger.addHandler(handler)
        _state = dict(role=role, handlers=handlers, excepthook=sys.excepthook,
                      threading_excepthook=threading.excepthook, qt_handler=None, session=None)
        sys.excepthook = _excepthook
        threading.excepthook = _threading_excepthook
        if role == "app":
            remove_old_traces()
        if wanted():
            _start_session()


def remove_old_traces() -> None:
    """The files of the traces that wrote on every machine before v0.13.7 (their lines are in the debug log now):
    status-progression.log in the config folder, background-trace.log and its .1 in the cache folder."""
    from . import project

    for path in (project.config_dir() / "status-progression.log", project.cache_dir() / "background-trace.log",
                 project.cache_dir() / "background-trace.log.1"):
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


def debug_enabled() -> bool:
    """Whether the debug log is being written (cheap: ask it before building an expensive debug line)."""
    return _state is not None and _state["session"] is not None


def debug_log_path() -> Optional[Path]:
    """The debug log this process writes, or None while debug is off."""
    return Path(_state["session"].baseFilename) if debug_enabled() else None


def set_debug(on: bool, persist: bool = True) -> None:
    """Turn the debug log on or off for this process at once and, with persist, in the saved setting, which every
    SlideMage process started from now on follows (unless SLIDEMAGE_DEBUG says otherwise)."""
    if persist:
        from .fileio import write_json

        try:
            write_json(settings_path(), {"debug": bool(on)})
        except OSError:
            logging.getLogger(LOGGER + ".diagnostics").warning("could not save the debug setting to %s",
                                                               settings_path())
    if forced() is not None and forced() is not on:
        os.environ.pop(DEBUG_ENV)    # this process's --debug no longer holds for what it starts from now on
    with _lock:
        if _state is None:
            return
        if on and _state["session"] is None:
            _start_session()
        elif not on and _state["session"] is not None:
            _stop_session()


def _session_file(role: str) -> Path:
    folder = log_dir() / DEBUG_DIR
    if role != "app":
        return folder / f"{role}.log"
    return folder / f"app_{time.strftime('%Y-%m-%d_%H%M%S')}_{os.getpid()}.log"


def _start_session() -> None:
    role = _state["role"]
    path = _session_file(role)
    if role == "app":
        clean_up(path.parent)
    handler = RotatingFile(path, max_bytes=SESSION_MAX_BYTES, backups=SESSION_BACKUPS)
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(LineFormatter(role))
    logger = logging.getLogger(LOGGER)
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    _state["session"] = handler
    lines = header_lines() if role == "app" else header_lines(short=True)
    logging.getLogger(LOGGER + ".startup").info("debug log started\n%s", "\n".join(lines))


def _stop_session() -> None:
    handler = _state["session"]
    logging.getLogger(LOGGER + ".startup").info("debug log turned off")
    logger = logging.getLogger(LOGGER)
    logger.removeHandler(handler)
    logger.setLevel(logging.NOTSET)
    handler.close()
    _state["session"] = None


def clean_up(folder: Path, keep_sessions: int = KEEP_SESSIONS, keep_bytes: int = KEEP_BYTES) -> None:
    """Delete the oldest debug files: app sessions beyond keep_sessions, then anything beyond keep_bytes in all."""
    try:
        files = sorted((p for p in folder.iterdir() if p.is_file()), key=lambda p: p.stat().st_mtime, reverse=True)
    except OSError:
        return
    doomed = set([p for p in files if p.name.startswith("app_")][keep_sessions:])
    total = 0
    for path in files:
        if path in doomed:
            continue
        try:
            total += path.stat().st_size
        except OSError:
            continue
        if total > keep_bytes:
            doomed.add(path)
    for path in doomed:
        try:
            path.unlink()
        except OSError:
            pass            # open in another process: next time


def _system() -> str:
    """The operating system, without platform.platform(): on Windows that asks WMI and takes half a second."""
    if sys.platform == "win32":
        version = sys.getwindowsversion()
        return f"Windows {version.major}.{version.minor}.{version.build}"
    try:
        uname = os.uname()
        return f"{uname.sysname} {uname.release} {uname.machine}"
    except AttributeError:
        return sys.platform


def header_lines(short: bool = False) -> list[str]:
    """What produced this log: SlideMage, Python, Qt, the system, how it was started, and the TeX it finds. Short:
    only the first and the third line, for a hook or another process that starts often and shares one file."""
    import shutil

    from .version import VERSION_NUMBER

    build = "frozen" if getattr(sys, "frozen", False) else "from source"
    started = f"started as: {' '.join(sys.argv)}"
    if short:
        return [f"SlideMage {VERSION_NUMBER}, {build}", started]
    try:
        from PySide6 import __version__ as pyside
    except ImportError:
        pyside = "not installed"
    lines = [
        f"SlideMage {VERSION_NUMBER}, {build}: {sys.executable}",
        f"Python {sys.version.split()[0]}, PySide6 {pyside}, {_system()}",
        started,
        f"working folder: {os.getcwd()}",
        f"log folder: {log_dir()}",
    ]
    for tool in ("lualatex", "latexmk", "pdflatex", "xelatex"):
        lines.append(f"{tool}: {shutil.which(tool) or 'not found'}")
    for name in sorted(n for n in os.environ if n.startswith("SLIDEMAGE_") or n in SECRET_ENV_VARS):
        lines.append(f"${name} = {REDACTED if name in SECRET_ENV_VARS else os.environ[name]}")
    return lines


def reset() -> None:
    """Undo setup(): the handlers closed and the hooks put back (for the tests)."""
    global _state
    with _lock:
        if _state is None:
            return
        logger = logging.getLogger(LOGGER)
        for handler in _state["handlers"] + ([_state["session"]] if _state["session"] is not None else []):
            logger.removeHandler(handler)
            handler.close()
        logger.setLevel(logging.NOTSET)
        if sys.excepthook is _excepthook:
            sys.excepthook = _state["excepthook"]
        if threading.excepthook is _threading_excepthook:
            threading.excepthook = _state["threading_excepthook"]
        if _state["qt_handler"] is not None:
            from PySide6.QtCore import qInstallMessageHandler

            qInstallMessageHandler(_state["qt_handler"][0])
        _state = None
        _secrets.clear()


REPORT_SESSIONS = 3
COMPAT_REPORTS = (Path(".slidemage") / "compat-report.json", Path(".slidemage") / "compat-report.md")


def report_name() -> str:
    return f"SlideMage-debug-report_{time.strftime('%Y-%m-%d_%H%M%S')}.zip"


def write_report(target: Path, project_root: Optional[Path] = None, sessions: int = REPORT_SESSIONS) -> list[str]:
    """A zip for a problem report, written to `target` and nothing sent anywhere: report.txt (the header lines,
    whether the debug log is on, the project), the error log with its older files, the newest `sessions` app
    session logs and the files of the other roles, and the project's compatibility report if it has one. The logs
    are masked already when written; report.txt is masked here. Returns the names in the zip."""
    import zipfile

    folder = log_dir()
    debug = folder / DEBUG_DIR
    files: list[tuple[Path, str]] = []
    for path in sorted(folder.glob(ERROR_LOG + "*")):
        files.append((path, f"logs/{path.name}"))
    if debug.is_dir():
        apps = sorted((p for p in debug.glob("app_*.log")), key=lambda p: p.stat().st_mtime, reverse=True)
        for path in apps[:sessions]:
            files += [(q, f"debug/{q.name}") for q in (path, path.with_name(path.name + ".1")) if q.is_file()]
        files += [(p, f"debug/{p.name}") for p in sorted(debug.iterdir())
                  if p.is_file() and not p.name.startswith("app_")]
    if project_root is not None:
        files += [(project_root / rel, f"project/{rel.name}") for rel in COMPAT_REPORTS if (project_root / rel).is_file()]
    lines = header_lines() + [
        f"debug log: {'on, ' + str(debug_log_path()) if debug_enabled() else 'off'}",
        f"saved setting: {'on' if saved() else 'off'}; SLIDEMAGE_DEBUG: {os.environ.get(DEBUG_ENV, '(not set)')}",
        f"project: {project_root if project_root is not None else '(none)'}",
        f"report written: {time.strftime('%Y-%m-%d %H:%M:%S')}",
    ]
    for handler in logging.getLogger(LOGGER).handlers:
        handler.flush()
    target.parent.mkdir(parents=True, exist_ok=True)
    names = ["report.txt"]
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, strict_timestamps=False) as archive:
        archive.writestr("report.txt", redact("\n".join(lines) + "\n"))
        for path, name in files:
            try:
                archive.write(path, name)
            except OSError:
                continue              # rotated or removed meanwhile
            names.append(name)
    return names


def error_log_path() -> Optional[Path]:
    """The error log this process writes, or None before setup() or when it could not be opened."""
    if _state is None:
        return None
    files = [h for h in _state["handlers"] if isinstance(h, RotatingFile)]
    return Path(files[0].baseFilename) if files else None


def _excepthook(kind, value, tb) -> None:
    if not issubclass(kind, KeyboardInterrupt):
        logging.getLogger(LOGGER).critical("uncaught exception", exc_info=(kind, value, tb), extra={"uncaught": True})
    previous = _state["excepthook"] if _state is not None else sys.__excepthook__
    previous(kind, value, tb)


def _threading_excepthook(args) -> None:
    if args.exc_type is not SystemExit:
        name = args.thread.name if args.thread is not None else "?"
        logging.getLogger(LOGGER).critical(f"uncaught exception in thread {name}",
                                           exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
                                           extra={"uncaught": True})
    previous = _state["threading_excepthook"] if _state is not None else threading.__excepthook__
    previous(args)


def install_qt_message_handler() -> None:
    """Qt's own warnings into the log as area `qt`, with the source location Qt gives. Call it once a
    QApplication may exist; Qt's debug and info messages still go to the console, as before, when there is one."""
    if _state is None or _state["qt_handler"] is not None:
        return
    from PySide6.QtCore import QtMsgType, qInstallMessageHandler

    levels = {QtMsgType.QtDebugMsg: logging.DEBUG, QtMsgType.QtInfoMsg: logging.INFO,
              QtMsgType.QtWarningMsg: logging.WARNING, QtMsgType.QtCriticalMsg: logging.ERROR,
              QtMsgType.QtFatalMsg: logging.CRITICAL}
    log = logging.getLogger(LOGGER + ".qt")

    def handler(kind, context, message) -> None:
        level = levels.get(kind, logging.WARNING)
        if level < logging.WARNING:
            if sys.stderr is not None:
                print(message, file=sys.stderr)
            return
        where = f"  at={context.file}:{context.line}" if getattr(context, "file", None) else ""
        log.log(level, "%s%s", message, where)

    _state["qt_handler"] = (qInstallMessageHandler(handler), handler)
