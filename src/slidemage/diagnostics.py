# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Where SlideMage's own `logging` output goes (docs/plans/debug-log.md).

`setup(role)` runs once at the start of every SlideMage process (cli.main): the app, a Claude Code hook, a plugin
entry point, the preview rasteriser. It gives the `slidemage` logger the error log: warnings, errors and uncaught
exceptions of every process, in `logs/slidemage.log` in SlideMage's cache folder (not roaming), kept below
MAX_BYTES with BACKUPS older files (.1 is the newest). SLIDEMAGE_LOG_DIR names another folder. While the process
has a console, the same lines also go to stderr, as Python's last-resort handler did before. The windowed build
has none, which is why nothing logged reached anyone before v0.12.2.

One line per record, in fixed columns: time, seconds since the process started, level, area (the logger name
without `slidemage.`), role:pid, thread, message. A traceback follows, indented. API keys and tokens are masked
before a line is written (`redact`). No Qt here: `install_qt_message_handler` imports PySide6 only when called.
"""
from __future__ import annotations

import logging
import os
import re
import sys
import threading
import time
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

_secrets: set[str] = set()
_state: Optional[dict] = None
_lock = threading.Lock()


def log_dir() -> Path:
    from . import project

    override = os.environ.get(DIR_ENV, "").strip()
    return Path(override) if override else project.cache_dir() / "logs"


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


def setup(role: str = "app") -> None:
    """Attach the error log (and the console, if there is one) to the `slidemage` logger and catch uncaught
    exceptions. Once per process; later calls do nothing. `role` names the process in every line."""
    global _state
    with _lock:
        if _state is not None:
            return
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
                      threading_excepthook=threading.excepthook, qt_handler=None)
        sys.excepthook = _excepthook
        threading.excepthook = _threading_excepthook


def reset() -> None:
    """Undo setup(): the handlers closed and the hooks put back (for the tests)."""
    global _state
    with _lock:
        if _state is None:
            return
        logger = logging.getLogger(LOGGER)
        for handler in _state["handlers"]:
            logger.removeHandler(handler)
            handler.close()
        if sys.excepthook is _excepthook:
            sys.excepthook = _state["excepthook"]
        if threading.excepthook is _threading_excepthook:
            threading.excepthook = _state["threading_excepthook"]
        if _state["qt_handler"] is not None:
            from PySide6.QtCore import qInstallMessageHandler

            qInstallMessageHandler(_state["qt_handler"][0])
        _state = None
        _secrets.clear()


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
