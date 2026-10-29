# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Window-independent operations for plugin hooks."""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path

from .. import ai_review, alt_images, fileio, project, timing
from ..project import ProjectContext
from ..slide_protection import slide_kind


class HookContext:
    def __init__(self, ctx: ProjectContext) -> None:
        self._ctx = ctx

    @property
    def root(self) -> Path:
        return self._ctx.root

    def slide_kind(self, path: Path) -> str | None:
        return slide_kind(self._ctx, path)

    def read_text(self, path: Path) -> str:
        return fileio.read_text_exact(path)

    def read_snapshot(self, identity: str) -> dict:
        return fileio.read_json(self._snapshot(identity))

    def write_snapshot(self, identity: str, data: dict) -> None:
        fileio.write_json(self._snapshot(identity), data)

    def delete_snapshot(self, identity: str) -> None:
        self._snapshot(identity).unlink(missing_ok=True)

    def _snapshot(self, identity: str) -> Path:
        return self._ctx.claude_hook_dir / (sha256(identity.encode()).hexdigest() + ".json")

    def is_image_store(self, path: Path) -> bool:
        return alt_images.is_store(self._ctx, path)

    def flag_edited_sources(self, path: Path, before: str) -> bool:
        return alt_images.flag_edited_sources(self._ctx, path, before)

    def is_deck(self, path: Path) -> bool:
        return path.suffix == ".tex" and path.resolve().is_relative_to(self._ctx.decks_dir.resolve())

    def mark_review(self, path: Path, kind: str, source: str, *, before: str | None = None) -> None:
        ai_review.mark(self._ctx, path, kind, source, before=before)

    def record_inserted_slides(self, path: Path, before: str, after: str, source: str) -> None:
        ai_review.inserted_slides(self._ctx, path, before, after, source)

    def timing_event(self, name: str) -> None:
        timing.event(self.root, name)


def from_environment() -> HookContext:
    return HookContext(project.from_environment())
