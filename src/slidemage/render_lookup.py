# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Qt-free selection of stored whole-slide renders, without reading their artifacts.

A request is a dict with an existing ``resolver`` and ``unit``, and optionally a captured
PreviewRequest (``spec``) and a shared ValidationPass (``validation``). Omitting ``spec``
asks about the saved unit. Selection reads no artifacts; RenderStore supplies the readers.
``state_only`` returns the sweep's Lookup, including numbering and failure state, without selecting fallbacks.
"""
from __future__ import annotations

from . import render_evidence
from .render_key import KIND_PROJECT, Lookup


def select(request: dict, *, strict=False) -> tuple[str, dict | None] | Lookup:
    """Return (current, previous, reference, missing or hidden; record), or a state-only Lookup."""
    resolver, unit = request["resolver"], request["unit"]
    spec = request.get("spec")
    if spec is not None:
        if spec.target.hidden:
            return "hidden", None
        if not spec.complete:
            return "missing", None
    validation = request.get("validation") or render_evidence.ValidationPass()
    if request.get("state_only"):
        return resolver.lookup(unit, strict=strict, validation=validation)
    key = resolver.fast_key(unit, spec.revision.text if spec is not None else None,
                            strict=strict, validation=validation)
    if key is None:
        return "missing", None
    found = resolver.lookup(unit, key, strict=strict, validation=validation)
    if found.usable:
        return "current", found.record
    if (spec is not None and resolver.hashes.hash(unit.source_path, verify=strict) != spec.revision.content_hash
            and resolver.store.find(key) is None):
        return "missing", None
    previous = found.record or resolver.store.latest_for_unit(unit.label)
    if previous is not None:
        return "previous", previous
    reference = instructor_reference(request, strict=strict)
    return ("reference", reference) if reference is not None else ("missing", None)


def instructor_reference(request: dict, *, strict=False) -> dict | None:
    """The newest complete, stably published Instructor result matching the saved source and template.

    References need not be current in this deck. Publication establishes stability; find checks
    completeness. The manifest's source hash establishes which saved text the result depicts.
    """
    resolver, unit = request["resolver"], request["unit"]
    sha = resolver.hashes.hash(unit.source_path, verify=strict)
    spec = request.get("spec")
    if sha is None or (spec is not None and spec.revision.content_hash != sha):
        return None
    source = [KIND_PROJECT, unit.source_path.relative_to(resolver.ctx.root).as_posix(), sha]
    suffix = f":{unit.id_slug}:instructor:{unit.language}"
    store = resolver.store
    with store.lock:
        rows = store.db.execute("SELECT name FROM renders WHERE substr(unit, -?)=? ORDER BY rendered_at DESC, name DESC",
                                (len(suffix), suffix)).fetchall()
    for (key,) in rows:
        record = store.find(key)
        if (record is not None and record.get("template") == unit.template
                and record.get("inventory") is not None and source in record["manifest"]):
            return record
    return None
