# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The core never imports a plugin, and plugin_api stays cheap to import."""
from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).parent.parent / "src" / "slidemage"
HEAVY = {"slidemage", "PySide6"}
FORBIDDEN = {"hello", "campusonline", "claude", "ollama", "slidemage_plugins"}


def imports(path: Path):
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            for a in node.names:
                yield a.name, 0
        elif isinstance(node, ast.ImportFrom):
            yield node.module or "", node.level


def test_core_does_not_import_plugin_packages():
    bad = []
    for path in SRC.rglob("*.py"):
        for module, level in imports(path):
            if level == 0 and module.split(".")[0] in FORBIDDEN:
                bad.append(f"{path.relative_to(SRC)}: {module}")
    assert not bad


def test_plugin_api_imports_nothing_from_slidemage_or_qt():
    tree = ast.parse((SRC / "plugin_api.py").read_text(encoding="utf-8"))
    type_checking = {id(n) for top in ast.walk(tree) if isinstance(top, ast.If)
                     and "TYPE_CHECKING" in ast.dump(top.test) for n in ast.walk(top)}
    bad = []
    for node in ast.walk(tree):
        if id(node) in type_checking:
            continue
        if isinstance(node, ast.ImportFrom) and (node.level or (node.module or "").split(".")[0] in HEAVY):
            bad.append(node.module)
        if isinstance(node, ast.Import) and any(a.name.split(".")[0] in HEAVY for a in node.names):
            bad.append(node.names[0].name)
    assert not bad
