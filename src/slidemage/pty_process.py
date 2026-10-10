"""A child process on a pseudo-terminal, for the terminal of the Claude Code view
(UI redesign step 10c). No Qt: the owner passes plain callbacks.

POSIX uses `ptyprocess`, Windows `pywinpty` (ConPTY); both spawn the program with a controlling terminal
of a given size and hand back its output as it appears. The output is read on a thread of its own,
`on_output(bytes)` and finally `on_exit(code)` are called on that thread, so a caller that owns widgets
must hop to its own thread (a Qt signal does). `stop()` ends the process politely first (SIGTERM to its
process group; Windows terminates), then by force, and returns once it is over.
"""
from __future__ import annotations

import contextlib
import os
import signal
import sys
import threading
import time
import warnings
from collections.abc import Callable, Sequence
from pathlib import Path

WINDOWS = sys.platform == "win32"
READ_SIZE = 65536
POLL_S = 0.02
REAP_WAIT_S = 5.0       # how long a process may outlive the closing of its terminal


@contextlib.contextmanager
def _few_file_descriptors(limit: int = 4096):
    """ptyprocess's child closes every descriptor up to the soft limit before it runs the program; with the
    half-million limit many systems have, that takes a quarter of a second. So the soft limit is lowered for
    the moment of the spawn and put back in this process afterwards. The program started keeps the lowered
    limit (4096, still above the 1024 many Linux terminals give)."""
    if WINDOWS:
        yield
        return
    import resource
    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    lowered = soft == resource.RLIM_INFINITY or soft > limit
    if lowered:
        resource.setrlimit(resource.RLIMIT_NOFILE, (limit, hard))
    try:
        yield
    finally:
        if lowered:
            resource.setrlimit(resource.RLIMIT_NOFILE, (soft, hard))


class PtyProcess:
    def __init__(
        self, argv: Sequence[str], cwd: Path, env: dict[str, str], on_output: Callable[[bytes], None],
        on_exit: Callable[[int], None], cols: int = 80, rows: int = 24,
    ) -> None:
        """Start `argv` in `cwd`. `on_exit(code)` gets the exit code, or -N for a process killed by
        signal N."""
        self._on_output, self._on_exit = on_output, on_exit
        self._done = threading.Event()
        self._signalled = False
        self.exit_code: int | None = None
        if WINDOWS:
            import winpty
            self._proc = winpty.PtyProcess.spawn(list(argv), cwd=str(cwd), env=env, dimensions=(rows, cols))
        else:
            import ptyprocess
            with _few_file_descriptors(), warnings.catch_warnings():
                # Python 3.12+ warns that forkpty() in a process with threads (Qt has many) may deadlock the child.
                # Between the fork and the exec ptyprocess runs only a few lines, and no other way gives a child
                # a controlling terminal; the risk is the same as for every Python terminal widget.
                warnings.simplefilter("ignore", DeprecationWarning)
                self._proc = ptyprocess.PtyProcess.spawn(list(argv), cwd=str(cwd), env=env, dimensions=(rows, cols))
        self._pgid = getattr(self._proc, "pid", 0)      # the child leads its own session and process group
        self._reader = threading.Thread(target=self._read_loop, name="pty-reader", daemon=True)
        self._reader.start()

    @property
    def alive(self) -> bool:
        return not self._done.is_set()

    def write(self, data: bytes) -> None:
        if self._done.is_set():
            return
        try:
            self._proc.write(data.decode("utf-8", "replace") if WINDOWS else data)
        except (OSError, EOFError):
            pass          # the process is going away; on_exit tells the owner

    def resize(self, cols: int, rows: int) -> None:
        if not self._done.is_set() and cols > 0 and rows > 0:
            try:
                self._proc.setwinsize(rows, cols)
            except (OSError, ValueError):
                pass

    def stop(self, grace: float = 1.0) -> None:
        """End the process (and what it started) and wait until the reader has seen it go. The wait is on
        the caller's thread, the GUI's, hence short."""
        if not self._done.is_set():
            self._signal(signal.SIGTERM)
            if not self._done.wait(grace):
                self._signal(signal.SIGKILL if not WINDOWS else signal.SIGTERM, force=True)
                if not self._done.wait(grace):
                    self._close()
        elif not self._signalled:
            self._signal(signal.SIGTERM)    # the leader ended by itself; what it started may not have
        self._reader.join(grace)

    def _signal(self, number: int, force: bool = False) -> None:
        self._signalled = True
        try:
            if WINDOWS:
                self._proc.terminate(force=force)
            else:
                os.killpg(self._pgid, number)
        except (OSError, ProcessLookupError):
            pass

    def _close(self) -> None:
        try:
            self._proc.close(force=True)
        except Exception:  # noqa: BLE001 -- closing a dead terminal may fail in any number of ways
            pass

    def _read_loop(self) -> None:
        try:
            while True:
                try:
                    data = self._proc.read(READ_SIZE)
                except (EOFError, OSError):
                    break
                if data:
                    self._on_output(data.encode("utf-8", "replace") if WINDOWS else data)
        finally:
            self.exit_code = self._reap()
            self._done.set()
            self._on_exit(self.exit_code)

    def _reap(self) -> int:
        """The exit code, once the process has ended (it can outlive the closing of its terminal by
        a moment). One that still runs after that is killed with what it started: nobody is left to
        read its output."""
        end = time.time() + REAP_WAIT_S
        while self._proc.isalive() and time.time() < end:
            time.sleep(POLL_S)
        if self._proc.isalive():
            self._signal(signal.SIGKILL if not WINDOWS else signal.SIGTERM, force=True)
            self._close()
            return -1
        if WINDOWS:
            return self._proc.exitstatus or 0
        self._proc.wait()
        status = self._proc.exitstatus
        return status if status is not None else -(self._proc.signalstatus or 0)
