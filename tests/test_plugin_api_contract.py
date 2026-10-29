# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Freeze the public plugin API. Regenerate after compatible additions with:

    python tests/test_plugin_api_contract.py --update

An incompatible change needs a higher API_VERSION and a new snapshot; keep the old
snapshot as a record of the contract offered to existing plugins.
"""
from __future__ import annotations

import inspect
import json
from pathlib import Path
import sys

import pytest

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from slidemage import plugin_api


_FIXTURES = Path(__file__).parent / "fixtures"
_UPDATE = "python tests/test_plugin_api_contract.py --update"


def _parameters(callable_):
    return [
        {"name": p.name, "kind": p.kind.name, "required": p.default is inspect.Parameter.empty
         and p.kind not in (p.VAR_POSITIONAL, p.VAR_KEYWORD)}
        for p in inspect.signature(callable_).parameters.values()
    ]


def _contract():
    # The lazy re-exports are public whether or not something has loaded them yet (a load caches them in the module).
    names = sorted(name for name in {*vars(plugin_api), *plugin_api._LAZY} if not name.startswith("_"))
    classes = {}
    for name in names:
        cls = getattr(plugin_api, name)
        if not inspect.isclass(cls) or cls.__module__ != plugin_api.__name__:
            continue
        methods = {key: _parameters(value) for key, value in vars(cls).items()
                   if not key.startswith("_") and inspect.isfunction(value)}
        # Dataclass constructors are public even though their implementation is __init__.
        if "__dataclass_fields__" in vars(cls):
            methods["__init__"] = _parameters(cls)
        classes[name] = {
            "attributes": sorted(key for key in vars(cls).get("__annotations__", {})
                                 if not key.startswith("_")),
            "methods": dict(sorted(methods.items())),
        }
    return {"api_version": plugin_api.API_VERSION, "names": names, "classes": classes}


def _incompatibilities(old, new):
    problems = []
    for name in sorted(set(old["names"]) - set(new["names"])):
        problems.append(f"removed public name {name}")
    for name, previous in old["classes"].items():
        current = new["classes"].get(name)
        if current is None:
            problems.append(f"removed public class {name}")
            continue
        for attr in sorted(set(previous["attributes"]) - set(current["attributes"])):
            problems.append(f"removed {name}.{attr}")
        for method, params in previous["methods"].items():
            updated = current["methods"].get(method)
            if updated is None:
                problems.append(f"removed {name}.{method}")
                continue
            old_by_name = {p["name"]: p for p in params}
            new_by_name = {p["name"]: p for p in updated}
            for param in params:
                after = new_by_name.get(param["name"])
                if (after is None or after["kind"] != param["kind"]
                        or (not param["required"] and after["required"])):
                    problems.append(f"changed parameter {name}.{method}: {param['name']}")
            for param in updated:
                if param["name"] not in old_by_name and param["required"]:
                    problems.append(f"added required parameter {name}.{method}: {param['name']}")
            positional = {"POSITIONAL_ONLY", "POSITIONAL_OR_KEYWORD"}
            before_pos = [p["name"] for p in params if p["kind"] in positional]
            after_pos = [p["name"] for p in updated if p["kind"] in positional]
            if after_pos[:len(before_pos)] != before_pos:
                problems.append(f"changed positional parameter order in {name}.{method}")
            if any(p["kind"] == "VAR_POSITIONAL" for p in params) and before_pos != after_pos:
                problems.append(f"changed positional arguments accepted by {name}.{method}")
    return problems


def _snapshot_path():
    return _FIXTURES / f"plugin_api_{plugin_api.API_VERSION}.json"


def test_plugin_api_contract():
    path = _snapshot_path()
    assert path.exists(), f"Missing API {plugin_api.API_VERSION} snapshot; run {_UPDATE}"
    expected = json.loads(path.read_text(encoding="utf-8"))
    actual = _contract()
    assert expected["api_version"] == plugin_api.API_VERSION
    problems = _incompatibilities(expected, actual)
    assert not problems, "Incompatible plugin API changes require raising API_VERSION:\n" + "\n".join(problems)
    assert expected == actual, f"Plugin API additions must be recorded; run {_UPDATE}"


def test_contract_compatibility_rules():
    def parameter(name, kind="POSITIONAL_OR_KEYWORD", required=True):
        return {"name": name, "kind": kind, "required": required}

    def contract(params):
        return {"names": ["Host"], "classes": {"Host": {
            "attributes": [], "methods": {"call": params}}}}

    baseline = contract([parameter("self"), parameter("deck"), parameter("flag", required=False)])
    assert not _incompatibilities(baseline, contract([
        parameter("self"), parameter("deck"), parameter("flag", required=False),
        parameter("extra", "KEYWORD_ONLY", required=False)]))
    for changed in (
        contract([parameter("self"), parameter("renamed"), parameter("flag", required=False)]),
        contract([parameter("self"), parameter("flag", required=False), parameter("deck")]),
        contract([parameter("self"), parameter("deck"), parameter("flag")]),
        contract([parameter("self"), parameter("deck"), parameter("flag", required=False),
                  parameter("extra", "KEYWORD_ONLY")]),
        contract([parameter("self"), parameter("deck", "POSITIONAL_ONLY"),
                  parameter("flag", required=False)]),
        {"names": [], "classes": {}},
    ):
        assert _incompatibilities(baseline, changed)


def test_update_records_additions_but_refuses_incompatible_changes(tmp_path, monkeypatch):
    baseline = _contract()
    path = tmp_path / "plugin_api.json"
    path.write_text(json.dumps(baseline), encoding="utf-8")
    monkeypatch.setattr(sys.modules[__name__], "_snapshot_path", lambda: path)
    monkeypatch.setattr(plugin_api, "new_public_name", object(), raising=False)
    with pytest.raises(AssertionError, match="additions must be recorded"):
        test_plugin_api_contract()
    _update()
    test_plugin_api_contract()

    saved = path.read_text(encoding="utf-8")
    monkeypatch.delattr(plugin_api, "new_public_name")
    with pytest.raises(SystemExit, match="Raise API_VERSION"):
        _update()
    assert path.read_text(encoding="utf-8") == saved


def _update():
    path = _snapshot_path()
    current = _contract()
    if path.exists():
        old = json.loads(path.read_text(encoding="utf-8"))
        if old["api_version"] != plugin_api.API_VERSION:
            raise SystemExit("Snapshot version does not match API_VERSION")
        problems = _incompatibilities(old, current)
        if problems:
            raise SystemExit("Raise API_VERSION before recording incompatible changes:\n" + "\n".join(problems))
    path.write_text(json.dumps(current, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Updated {path}")


if __name__ == "__main__":
    if sys.argv[1:] != ["--update"]:
        raise SystemExit(f"Usage: {_UPDATE}")
    _update()
