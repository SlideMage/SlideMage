# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""`SlideMage --plugin <id>:<name> [args...]`: run one plugin's entry point as a program of its own.

Another program (Claude Code's hook, say) runs a plugin's code by the command Host.entry_point_command() gave
the plugin. A frozen build has no `python -m`, so SlideMage's own executable takes the flag. Only the named plugin is
loaded, through the loader and its activate() like in the app but with a host that has no window, and nothing
else of the app starts: no project picker, no Qt application. The exit code is the entry point's return value;
2 means the plugin or the entry point could not be found or loaded.
"""
from __future__ import annotations

import logging
import sys

from .. import diagnostics, project
from ..version import VERSION_NUMBER
from . import loader
from .host import PluginHost

NOT_FOUND = 2


def run(spec: str, args: list[str]) -> int:
    plugin_id, _, name = spec.partition(":")
    if not plugin_id or not name:
        return _fail(f"--plugin wants <plugin id>:<entry point>, not {spec!r}")
    found = next((f for f in loader.discover() if f.id == plugin_id), None)
    if found is None:
        return _fail(f"no plugin {plugin_id!r} is installed")
    ctx = project.from_environment()
    plugin = loader._load_one(found, lambda manifest: PluginHost(manifest, ctx), VERSION_NUMBER)
    if plugin.state != "loaded":
        reason = plugin.reason.strip().splitlines()[-1] if plugin.reason.strip() else plugin.state
        return _fail(f"plugin {plugin_id!r} is {plugin.state}: {reason}")
    fn = plugin.contributions.entry_points.get(name)
    if fn is None:
        return _fail(f"plugin {plugin_id!r} has no entry point {name!r}")
    with diagnostics.timed(logging.getLogger("slidemage.plugins"), "entry point", plugin=plugin_id, name=name) as info:
        code = fn(list(args))
        info["code"] = code
    return 0 if code is None else int(code)


def _fail(message: str) -> int:
    print(f"SlideMage: {message}", file=sys.stderr)
    return NOT_FOUND
