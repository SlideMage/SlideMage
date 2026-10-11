"""External viewers must not inherit PyInstaller's private Linux libraries."""
import sys
from pathlib import Path

import pytest

from slidemage import open_path


pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux-only launcher")


@pytest.mark.parametrize("frozen, original, expected", [
    (True, None, None),
    (True, "/system/lib", "/system/lib"),
    (False, None, "/custom/lib"),
], ids=["frozen-unset", "frozen-restored", "source"])
def test_linux_open_uses_system_libraries_without_changing_the_parent(monkeypatch, frozen, original, expected):
    """Regression: packaged viewers must not inherit PyInstaller's private libraries."""
    calls = []
    monkeypatch.setattr(open_path.subprocess, "Popen", lambda *a, **kw: calls.append((a, kw)))
    if frozen:
        monkeypatch.setattr(open_path.sys, "frozen", True, raising=False)
    else:
        monkeypatch.delattr(open_path.sys, "frozen", raising=False)
    library_path = "/tmp/_MEI_private" if frozen else "/custom/lib"
    monkeypatch.setenv("LD_LIBRARY_PATH", library_path)
    if original is None:
        monkeypatch.delenv("LD_LIBRARY_PATH_ORIG", raising=False)
    else:
        monkeypatch.setenv("LD_LIBRARY_PATH_ORIG", original)

    path = Path("example.pdf")
    open_path.open_in_default_app(path)
    args, kwargs = calls[0]
    assert args == (["xdg-open", str(path)],)
    assert kwargs["env"].get("LD_LIBRARY_PATH") == expected
    assert open_path.os.environ["LD_LIBRARY_PATH"] == library_path
