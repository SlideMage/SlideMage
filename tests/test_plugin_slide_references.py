# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Plugins report slide references before an exact copy is replaced; the Exam Forge fallback for old releases."""
import json
from pathlib import Path

import pytest

from slidemage import plugin_api, project, slide_similarity
from slidemage.plugins import session
from slidemage.plugins.loader import LoadedPlugin
from slidemage.plugins.registry import Contributions
from slidemage.project import ProjectContext


@pytest.fixture
def ctx(tmp_path, monkeypatch):
    monkeypatch.setattr(project, "config_dir", lambda: tmp_path / "config")
    monkeypatch.setattr(project, "cache_dir", lambda: tmp_path / "cache")
    ctx = ProjectContext.at(tmp_path / "project")
    for folder in (ctx.slides_dir, ctx.decks_dir, ctx.blocks_dir, ctx.settings_dir):
        folder.mkdir(parents=True)
    (ctx.settings_dir / "project.json").write_text(json.dumps({"languages": {"main": "en", "secondary": []}}))
    for slide_id in ("aaa", "bbb"):
        (ctx.slides_dir / f"{slide_id}-EN-Demo-current.tex").write_text(
            r"\begin{standardframe}{Demo} An exact copy with distinctive words.\end{standardframe}")
    (ctx.decks_dir / "replace.tex").write_text("\\slide{bbb-EN-Demo}\n")
    monkeypatch.setattr(session, "_loaded", [])
    return ctx


def install(monkeypatch, plugin_id, *checks):
    plugin = LoadedPlugin(Path("."), "dev", plugin_id, None, "loaded",
                          contributions=Contributions(slide_reference_checks=list(checks)))
    monkeypatch.setattr(session, "_loaded", [*session._loaded, plugin])


def replace(ctx):
    """Replace bbb by aaa from a snapshot taken before any plugin spoke, as the Library does after approval."""
    return slide_similarity.replace_exact_copy(ctx, "aaa", "bbb", slide_similarity.replacement_files(ctx, "aaa", "bbb"))


def test_found_reference_blocks_replacement(ctx, monkeypatch):
    deck = ctx.decks_dir / "replace.tex"
    seen = []
    install(monkeypatch, "bank", lambda ids: seen.append(ids) or ["Bank 'Finance 1', question 12 uses bbb"])
    with pytest.raises(ValueError, match=r"bbb is still used: bank: Bank 'Finance 1', question 12 uses bbb"):
        replace(ctx)
    assert seen == [frozenset({"bbb"})] and deck.read_text() == "\\slide{bbb-EN-Demo}\n"


@pytest.mark.parametrize("error", [plugin_api.ReferenceCheckUnavailable("bank folder is offline"),
                                   RuntimeError("boom")])
def test_check_that_cannot_tell_blocks_replacement(ctx, monkeypatch, error):
    def check(ids):
        raise error

    install(monkeypatch, "bank", check)
    with pytest.raises(ValueError, match=f"bank cannot tell.*{error}"):
        replace(ctx)
    assert (ctx.decks_dir / "replace.tex").read_text() == "\\slide{bbb-EN-Demo}\n"


def test_exam_forge_fallback_only_without_a_check(ctx, tmp_path, monkeypatch):
    bank = tmp_path / "bank"
    bank.mkdir()
    (bank / "question.json").write_text(json.dumps({"sources": [{"slide_id": "bbb"}]}))
    settings = project.config_dir() / "plugins" / "settings" / "exam-forge.json"
    settings.parent.mkdir(parents=True)
    settings.write_text(json.dumps({"bank_folders": {"deck": str(bank)}}))
    deck = ctx.decks_dir / "replace.tex"
    # Exam Forge is not loaded (disabled, failed) but its remembered bank folders are there: the old search refuses
    with pytest.raises(ValueError, match="unregistered external banks cannot be verified"):
        replace(ctx)
    assert deck.read_text() == "\\slide{bbb-EN-Demo}\n"
    install(monkeypatch, "other")                   # another plugin's check does not answer for Exam Forge's banks
    with pytest.raises(ValueError, match="unregistered external banks cannot be verified"):
        replace(ctx)
    session._loaded.pop()
    settings.unlink()                               # no remembered banks: nothing to check, it goes through
    replace(ctx)
    assert deck.read_text() == "\\slide{aaa-EN-Demo}\n"
    settings.write_text(json.dumps({"bank_folders": {"deck": str(bank)}}))
    deck.write_text("\\slide{bbb-EN-Demo}\n")
    install(monkeypatch, "exam-forge")              # Exam Forge without the check: the old search refuses
    with pytest.raises(ValueError, match="unregistered external banks cannot be verified"):
        replace(ctx)
    bank.rename(tmp_path / "gone")                  # an offline bank refuses too
    with pytest.raises(ValueError, match="Remembered bank is unavailable"):
        replace(ctx)
    assert deck.read_text() == "\\slide{bbb-EN-Demo}\n"
    session._loaded.pop()
    install(monkeypatch, "exam-forge", lambda ids: [])          # with a check the fallback is not used
    replace(ctx)
    assert deck.read_text() == "\\slide{aaa-EN-Demo}\n"


def test_a_check_that_hangs_refuses_after_the_timeout(ctx, monkeypatch):
    import threading
    from slidemage.plugins import host
    monkeypatch.setattr(host, "REFERENCE_CHECK_TIMEOUT_S", 0.2)
    release = threading.Event()
    install(monkeypatch, "bank", lambda ids: release.wait(10) or [])
    try:
        with pytest.raises(ValueError, match="bank cannot tell.*did not answer within"):
            replace(ctx)
    finally:
        release.set()
    assert (ctx.decks_dir / "replace.tex").read_text() == "\\slide{bbb-EN-Demo}\n"
