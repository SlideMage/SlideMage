# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""What a SlideMage that still had the features built in was used for, and the flag of the first-start sheet.

Upgrading from a release with built-in AI and CAMPUSonline features matters most: without a check, the update that
removes a feature would silently take it from people who use it. used_features() finds the features this machine
and this project use, as plugin id -> the reason the sheet shows; preselect() turns that into the sheet's ticks.

Onboarding and migration are separate: offer_seen() is the first-start sheet's flag and nothing else. A feature
that a release removes from core is a Migration (feature id + that release) with its own seen flag in
plugins/migrations_seen.json, so a user who dismissed the first-start sheet long ago is still told, once, about
the plugin that now replaces a feature they use (migrations_due()). No feature is removed yet: MIGRATIONS is empty.
No Qt: reads files and settings only.
"""
from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from dataclasses import dataclass

from .. import app_settings, deck_scan
from ..ai import ai_profile
from ..project import ProjectContext
from . import session
from .migrate import legacy_anthropic_key
from .catalogue import Catalogue, CataloguePlugin, best_release
from .loader import discover, plugins_dir
from .manifest import parse_version
from ..version import VERSION_NUMBER

log = logging.getLogger(__name__)

CLAUDE, OLLAMA, CAMPUSONLINE = "claude", "ollama", "campusonline"
OFFER_SEEN_NAME = "offer_seen"
MIGRATIONS_SEEN_NAME = "migrations_seen.json"


@dataclass(frozen=True)
class Migration:
    """A feature that `release` removed from core: `feature` is the id of the plugin that now provides it."""
    feature: str
    release: str


# Each removed feature gets a one-time offer in the release that removes it.
MIGRATIONS: list[Migration] = [Migration(CLAUDE, "v10.0.0"), Migration(OLLAMA, "v10.0.0")]


def _routes_with_models(ctx: ProjectContext) -> set[str]:
    """The AI routes (ollama, claude_code, anthropic_api) that have a model chosen in the settings."""
    stored = app_settings.peek(ctx, ai_profile.MODELS_KEY)
    found = ({ai_profile.route_id(route) for route, tasks in stored.items()
              if isinstance(tasks, dict) and any(tasks.values())} if isinstance(stored, dict) else set())
    for key in ("chat_model", "drafting_model", "translation_model", "syntax_check_model", "ai_draft_model"):
        value = app_settings.peek(ctx, key)
        if isinstance(value, str) and value.strip():
            found.add(ai_profile.ANTHROPIC_API if value.startswith("anthropic:") else ai_profile.OLLAMA)
    return found


def used_features(ctx: ProjectContext) -> dict[str, str]:
    """Plugin id -> why it is suggested, for each built-in feature this machine or project uses."""
    used: dict[str, str] = {}
    routes = _routes_with_models(ctx)
    if legacy_anthropic_key(ctx) is not None:
        used[CLAUDE] = "You have an Anthropic API key"
    elif ai_profile.route_id(app_settings.peek(ctx, ai_profile.CONNECTION_KEY)) in ai_profile.CONNECTIONS:
        used[CLAUDE] = "You chose Claude Code or the API for cloud AI"
    elif routes & {ai_profile.CLAUDE_CODE, ai_profile.ANTHROPIC_API}:
        used[CLAUDE] = "You chose Claude models in the AI settings"
    if ai_profile.OLLAMA in routes or str(app_settings.peek(ctx, app_settings.OLLAMA_HOST_SETTING_KEY) or "").strip():
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


# -- migrations: a removed feature is announced once, whatever happened to the first-start sheet ----

def migrations_seen() -> set[str]:
    try:
        data = json.loads((plugins_dir() / MIGRATIONS_SEEN_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    return {i for i in data if isinstance(i, str)} if isinstance(data, list) else set()


def mark_migrations_seen(ids: Iterable[str]) -> None:
    """Remember that the notice for these feature ids was shown. Unwritable: only logged, so it comes again."""
    ids = set(ids)
    if not ids:
        return
    try:
        folder = plugins_dir()
        folder.mkdir(parents=True, exist_ok=True)
        (folder / MIGRATIONS_SEEN_NAME).write_text(json.dumps(sorted(migrations_seen() | ids)) + "\n",
                                                   encoding="utf-8")
    except OSError:
        log.exception("could not write %s", MIGRATIONS_SEEN_NAME)


def migrations_due(ctx: ProjectContext, app_version: str = VERSION_NUMBER) -> dict[str, str]:
    """Feature id -> reason, for each migration to announce now: the release is not newer than this app, the
    feature was used here, its plugin is not installed, and the notice was not shown yet."""
    if not MIGRATIONS:
        return {}
    seen = migrations_seen()
    pending = []
    for migration in MIGRATIONS:
        try:
            if migration.feature not in seen and parse_version(migration.release) <= parse_version(app_version):
                pending.append(migration.feature)
        except ValueError:
            log.error("bad migration release %r", migration.release)
    if not pending:
        return {}
    present = {p.id for p in session.loaded()} | {f.id for f in discover()}
    used = used_features(ctx)
    return {feature: used[feature] for feature in pending if feature in used and feature not in present}
