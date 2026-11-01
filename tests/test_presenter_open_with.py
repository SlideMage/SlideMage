# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""SlideMage Presenter under "Open with" for PDFs (docs/plans/presenter-app.md, step 5a). Never touches the real
registry or the real ~/.local/share/applications: a fake registry, XDG_DATA_HOME in tmp_path and fake runners."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import pytest

import slidemage
from slidemage.presentation import open_with
from slidemage.ui.presentation.presenter_window import PresenterStartWindow

ROOT = Path(slidemage.__file__).resolve().parents[2]
EXE = "C:\\Tools\\SlideMagePresenter\\SlideMagePresenter.exe"
OTHER_PDF = open_with.OPEN_WITH_KEY      # .pdf\OpenWithProgids


class FakeRegistry:
    """A dict-backed stand-in for the HKCU calls open_with makes: values by (key, name), plus the set of keys."""

    def __init__(self) -> None:
        self.values: dict[tuple[str, str], tuple[str, Optional[str]]] = {}     # (kind, text)

    def keys(self) -> set[str]:
        return {key for key, _name in self.values}

    def set_value(self, key, name, value):
        self.values[(key, name)] = ("REG_SZ", value)

    def set_empty_value(self, key, name):
        self.values[(key, name)] = ("REG_NONE", None)

    def get_value(self, key, name):
        kind, value = self.values.get((key, name), (None, None))
        return value if kind == "REG_SZ" else None

    def delete_value(self, key, name):
        self.values.pop((key, name), None)

    def delete_tree(self, key):
        for stored in [k for k in self.values if k[0] == key or k[0].startswith(key + "\\")]:
            del self.values[stored]


@pytest.fixture
def windows(monkeypatch):
    monkeypatch.setattr(open_with, "_windows", lambda: True)
    registry = FakeRegistry()
    registry.set_empty_value(OTHER_PDF, "AcroExch.Document")      # someone else's entry, must survive
    registry.set_value("Software\\Classes\\Applications\\Other.exe\\shell\\open\\command", "", '"x" "%1"')
    return registry


@pytest.fixture
def linux(monkeypatch, tmp_path):
    monkeypatch.setattr(open_with, "_windows", lambda: False)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "share"))
    calls: list[Path] = []
    return calls


# -- supported() ------------------------------------------------------------------------------

def test_not_supported_in_a_source_checkout():
    assert open_with.supported() is False


@pytest.mark.parametrize("platform, expected", [("win32", True), ("linux", True), ("darwin", False)])
def test_supported_only_when_frozen_on_windows_or_linux(monkeypatch, platform, expected):
    monkeypatch.setattr(open_with.sys, "frozen", True, raising=False)
    monkeypatch.setattr(open_with.sys, "platform", platform)
    assert open_with.supported() is expected


# -- Windows ----------------------------------------------------------------------------------

def test_register_writes_the_per_user_keys(windows):
    notified = []
    open_with.register(EXE, registry=windows, notify=lambda: notified.append(1))
    prog = "Software\\Classes\\SlideMage.Presenter.pdf"
    app = "Software\\Classes\\Applications\\SlideMagePresenter.exe"
    command = f'"{EXE}" "%1"'
    assert windows.values[(prog, "")] == ("REG_SZ", "PDF document (SlideMage Presenter)")
    assert windows.values[(prog + "\\DefaultIcon", "")] == ("REG_SZ", f'"{EXE}",0')
    assert windows.values[(prog + "\\shell\\open", "FriendlyAppName")] == ("REG_SZ", "SlideMage Presenter")
    assert windows.values[(prog + "\\shell\\open\\command", "")] == ("REG_SZ", command)
    assert windows.values[(OTHER_PDF, "SlideMage.Presenter.pdf")] == ("REG_NONE", None)
    assert windows.values[(app, "FriendlyAppName")] == ("REG_SZ", "SlideMage Presenter")
    assert windows.values[(app + "\\shell\\open\\command", "")] == ("REG_SZ", command)
    assert windows.values[(app + "\\SupportedTypes", ".pdf")] == ("REG_SZ", "")
    assert notified == [1]
    # nothing else was written: the default PDF program (...\FileExts, .pdf's own default value) is untouched
    assert len(windows.values) == 8 + 2
    assert (("Software\\Classes\\.pdf", "")) not in windows.values


def test_status_off_on_moved(windows):
    assert open_with.status(EXE, registry=windows) == "off"
    open_with.register(EXE, registry=windows, notify=lambda: None)
    assert open_with.status(EXE, registry=windows) == "on"
    assert open_with.status(EXE.lower().replace("\\", "/"), registry=windows) == "on"      # case, separators
    assert open_with.status("D:\\Elsewhere\\SlideMagePresenter.exe", registry=windows) == "moved"


def test_a_path_with_spaces_round_trips(windows):
    exe = "C:\\Program Files\\Slide Mage\\SlideMagePresenter.exe"
    open_with.register(exe, registry=windows, notify=lambda: None)
    assert open_with.status(exe, registry=windows) == "on"


def test_unregister_removes_exactly_what_register_added(windows):
    before = dict(windows.values)
    open_with.register(EXE, registry=windows, notify=lambda: None)
    notified = []
    open_with.unregister(registry=windows, notify=lambda: notified.append(1))
    assert windows.values == before
    assert notified == [1]
    assert open_with.status(EXE, registry=windows) == "off"
    open_with.unregister(registry=windows, notify=lambda: None)      # nothing left to remove is fine
    assert windows.values == before


# -- Linux ------------------------------------------------------------------------------------

def test_register_writes_the_desktop_file(linux, tmp_path):
    exe = "/opt/slide mage/SlideMagePresenter"
    open_with.register(exe, runner=linux.append)
    path = tmp_path / "share" / "applications" / "slidemage-presenter.desktop"
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "[Desktop Entry]"
    assert 'Exec="/opt/slide mage/SlideMagePresenter" %f' in lines
    assert "Icon=" + str(Path(exe).parent / "presenter-icon-256.png") in lines
    assert "MimeType=application/pdf;" in lines
    assert "NoDisplay=false" in lines
    assert linux == [path.parent]                      # update-desktop-database ran on that folder


def test_linux_status_and_unregister(linux, tmp_path):
    exe = "/opt/slide mage/SlideMagePresenter"
    assert open_with.status(exe) == "off"
    open_with.register(exe, runner=linux.append)
    assert open_with.status(exe) == "on"
    assert open_with.status("/home/me/SlideMagePresenter") == "moved"
    open_with.unregister(runner=linux.append)
    assert not (tmp_path / "share" / "applications" / "slidemage-presenter.desktop").exists()
    assert open_with.status(exe) == "off"
    assert len(linux) == 2
    open_with.unregister(runner=linux.append)          # already gone: fine, and nothing to refresh
    assert len(linux) == 2


def test_the_default_applications_folder(monkeypatch):
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    assert open_with.applications_dir() == Path.home() / ".local" / "share" / "applications"


def test_the_packaging_template_agrees_with_the_embedded_entry():
    def keys(text: str) -> dict[str, str]:
        found = {}
        for line in text.splitlines():
            if "=" in line and not line.startswith("#"):
                key, _sep, value = line.partition("=")
                found[key] = value
        return found

    template = keys((ROOT / "packaging" / "slidemage-presenter.desktop.template").read_text(encoding="utf-8"))
    embedded = keys(open_with.desktop_text("/x/SlideMagePresenter"))
    for key in ("Type", "Name", "Comment", "Terminal", "Categories", "MimeType", "StartupWMClass"):
        assert template[key] == embedded[key], key
    assert template["Exec"].endswith(" %f") and embedded["Exec"].endswith(" %f")
    assert embedded["MimeType"] == "application/pdf;"


# -- the start window -------------------------------------------------------------------------

def test_the_row_is_hidden_when_not_supported(qapp):
    win = PresenterStartWindow()
    assert win.open_with_bar.isHidden()


@pytest.fixture
def fake_backend(monkeypatch):
    state = {"value": "off", "calls": [], "fail": None}

    def register(executable):
        state["calls"].append(("register", executable))
        if state["fail"]:
            raise PermissionError(state["fail"])
        state["value"] = "on"

    def unregister():
        state["calls"].append(("unregister",))
        state["value"] = "off"

    monkeypatch.setattr(open_with, "supported", lambda: True)
    monkeypatch.setattr(open_with, "status", lambda executable: state["value"])
    monkeypatch.setattr(open_with, "register", register)
    monkeypatch.setattr(open_with, "unregister", unregister)
    return state


def test_the_button_follows_the_status(qapp, fake_backend):
    win = PresenterStartWindow()
    assert not win.open_with_bar.isHidden()
    assert win.open_with_button.text() == "Add"
    assert "Open with" in win.open_with_label.text()
    assert "never changes" in win.open_with_button.toolTip()
    win.open_with_button.click()
    assert fake_backend["calls"][0][0] == "register"
    assert win.open_with_button.text() == "Remove"
    win.open_with_button.click()
    assert fake_backend["calls"][1] == ("unregister",)
    assert win.open_with_button.text() == "Add"


def test_a_moved_copy_offers_an_update(qapp, fake_backend):
    fake_backend["value"] = "moved"
    win = PresenterStartWindow()
    assert win.open_with_button.text() == "Update"
    assert "another copy" in win.open_with_label.text()
    win.open_with_button.click()
    assert fake_backend["calls"][0][0] == "register"       # registers this copy
    assert win.open_with_button.text() == "Remove"


def test_an_error_is_shown_not_raised(qapp, fake_backend):
    fake_backend["fail"] = "access denied"
    win = PresenterStartWindow()
    win.open_with_button.click()
    assert "access denied" in win.open_with_label.text()
    assert win.open_with_button.text() == "Add"
