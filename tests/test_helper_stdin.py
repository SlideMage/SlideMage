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
