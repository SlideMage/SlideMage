"""Helper processes get an empty stdin of their own (WinError 6 in a windowed app, v0.14.46)."""
import subprocess
import sys

from slidemage import compiler, processes


def test_run_streamed_gives_the_child_an_empty_stdin(tmp_path):
    lines = []
    code = compiler.run_streamed(
        [sys.executable, "-c", "import sys; print(repr(sys.stdin.read()))"],
        cwd=tmp_path, env=dict(__import__("os").environ), log=lines.append)
    assert code == 0 and lines == ["''"]


def test_command_output_does_not_inherit_stdin(monkeypatch):
    seen = {}

    def fake_run(cmd, **kwargs):
        seen.update(kwargs)
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    monkeypatch.setattr(processes.subprocess, "run", fake_run)
    assert processes.command_output(["x"]) == "ok"
    assert seen["stdin"] is subprocess.DEVNULL


def test_a_stopped_process_whose_output_pipe_stays_open_does_not_hang_run_streamed(tmp_path, monkeypatch):
    import threading
    import time

    monkeypatch.setattr(compiler, "STOP_GRACE_SECONDS", 1.0)
    cancel = compiler.CancelToken()
    spawned = []
    cancel._kill = lambda proc: spawned.append(proc)             # the kill that misses
    threading.Timer(0.5, cancel.request_stop, kwargs={"wait": True}).start()
    started = time.monotonic()
    try:
        code = compiler.run_streamed([sys.executable, "-c", "import time; print('x', flush=True); time.sleep(30)"],
                                     cwd=tmp_path, env=None, log=lambda line: None, cancel=cancel)
    finally:
        for proc in spawned:
            proc.kill()
    assert time.monotonic() - started < 10
    assert spawned and code == -1
