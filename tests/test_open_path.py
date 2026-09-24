"""External viewers must not inherit PyInstaller's private Linux libraries."""
import sys
from pathlib import Path

import pytest

from slidemage import open_path


pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux-only launcher")


@pytest.mark.parametrize("original", [None, "/system/lib"])
def test_frozen_linux_open_restores_library_path(monkeypatch, original):
    calls = []
    monkeypatch.setattr(open_path.subprocess, "Popen", lambda *a, **kw: calls.append((a, kw)))
    monkeypatch.setattr(open_path.sys, "frozen", True, raising=False)
    monkeypatch.setenv("LD_LIBRARY_PATH", "/tmp/_MEI_private")
    if original is None:
        monkeypatch.delenv("LD_LIBRARY_PATH_ORIG", raising=False)
    else:
        monkeypatch.setenv("LD_LIBRARY_PATH_ORIG", original)

    path = Path("example.pdf")
    open_path.open_in_default_app(path)

    args, kwargs = calls[0]
    assert args == (["xdg-open", str(path)],)
    assert kwargs["env"].get("LD_LIBRARY_PATH") == original
    assert open_path.os.environ["LD_LIBRARY_PATH"] == "/tmp/_MEI_private"


def test_source_linux_open_keeps_library_path(monkeypatch):
    calls = []
    monkeypatch.setattr(open_path.subprocess, "Popen", lambda *a, **kw: calls.append((a, kw)))
    monkeypatch.delattr(open_path.sys, "frozen", raising=False)
    monkeypatch.setenv("LD_LIBRARY_PATH", "/custom/lib")

    open_path.open_in_default_app(Path("example.pdf"))

    assert calls[0][1]["env"]["LD_LIBRARY_PATH"] == "/custom/lib"
