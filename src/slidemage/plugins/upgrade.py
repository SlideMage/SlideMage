# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""What a SlideMage that still had the features built in was used for, and the flag of the first-start sheet.

Upgrading from a release with built-in AI and CAMPUSonline features matters most: without a check, the update that
removes a feature would silently take it from people who use it. used_features() finds the features this machine
and this project use, as plugin id -> the reason the sheet shows; preselect() turns that into the sheet's ticks.

Not wired into the sheet yet: PRESELECT_ON_UPGRADE stays False until the release that removes a feature from core.
No Qt: reads files and settings only.
"""
from __future__ import annotations

import logging
from collections.abc import Iterable

from .. import app_settings, deck_scan
from ..ai import ai_profile, credentials
from ..project import ProjectContext
from . import session
from .catalogue import Catalogue, CataloguePlugin, best_release
from .loader import discover, plugins_dir

log = logging.getLogger(__name__)

# The release that removes a feature from core turns this on, so the first start preselects the plugins of the
# features in use (with the reason). Until then the sheet preselects nothing.
PRESELECT_ON_UPGRADE = False

CLAUDE, OLLAMA, CAMPUSONLINE = "claude", "ollama", "campusonline"
OFFER_SEEN_NAME = "offer_seen"


def _routes_with_models(ctx: ProjectContext) -> set[str]:
    """The AI routes (local, claude_code, api) that have a model chosen in the settings."""
    stored = app_settings.get(ctx, ai_profile.MODELS_KEY)
    if not isinstance(stored, dict):
        return set()
    return {route for route, tasks in stored.items() if isinstance(tasks, dict) and any(tasks.values())}


def used_features(ctx: ProjectContext) -> dict[str, str]:
    """Plugin id -> why it is suggested, for each built-in feature this machine or project uses."""
    used: dict[str, str] = {}
    routes = _routes_with_models(ctx)
    if credentials.get_api_key(ctx) is not None:
        used[CLAUDE] = "You have an Anthropic API key"
    elif app_settings.get(ctx, ai_profile.CONNECTION_KEY) in ai_profile.CONNECTIONS:
        used[CLAUDE] = "You chose Claude Code or the API for cloud AI"
    elif routes & {ai_profile.CLAUDE_CODE, ai_profile.API}:
        used[CLAUDE] = "You chose Claude models in the AI settings"
    if ai_profile.LOCAL in routes or str(app_settings.get(ctx, app_settings.OLLAMA_HOST_SETTING_KEY) or "").strip():
        used[OLLAMA] = "You chose Ollama models"
    try:
        linked = [deck for deck in deck_scan.scan_decks(ctx) if deck.course_url]
    except OSError:
        log.exception("could not scan the decks for course links")
        linked = []
    if linked:
        used[CAMPUSONLINE] = ("A deck of this project has a CAMPUSonline course link" if len(linked) == 1
                              else f"{len(linked)} decks of this project have CAMPUSonline course links")
    return used


def preselect(catalogue_plugins: Iterable[CataloguePlugin], used: dict[str, str]) -> set[str]:
    """The ids to tick: the catalogue's plugins whose feature is in use."""
    return {plugin.id for plugin in catalogue_plugins if plugin.id in used}


# -- the flag: the sheet is offered once per machine ---------------------------------------------

def offer_seen() -> bool:
    return (plugins_dir() / OFFER_SEEN_NAME).exists()


def mark_offer_seen() -> None:
    """Remember that the sheet was shown. A folder that cannot be written is only logged: the sheet then comes
    again at the next start, which is better than an error on the first one."""
    try:
        folder = plugins_dir()
        folder.mkdir(parents=True, exist_ok=True)
        (folder / OFFER_SEEN_NAME).write_text("1\n", encoding="utf-8")
    except OSError:
        log.exception("could not write %s", OFFER_SEEN_NAME)


def offerable(catalogue: Catalogue) -> list[CataloguePlugin]:
    """The catalogue's plugins the first-start sheet can offer: not installed, with a release this SlideMage runs."""
    present = {p.id for p in session.loaded()} | {f.id for f in discover()}
    return [c for c in catalogue.plugins if c.id not in present and best_release(c) is not None]
