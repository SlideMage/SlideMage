# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Claude Code as the backend of the image pipeline in alt_draft.py (Claude Code tasks plan, step 4).

ClaudeDraftBackend and ClaudeTranslationBackend are the DraftBackend and TranslationBackend of the Ollama and
API backends, but each image is one `claude -p` process (ai/claude_runner.run_json), so run_batch /
run_translation_batch, apply_one_draft / apply_one_translation and their checks (the value-ramp detection, the
reviewed and stale checks) are the same. The prompts and the schema of the description are alt_draft's own; the
image goes inline as an image block. A result is a draft like any other, labelled "Claude <model>". No Qt.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field, replace
from pathlib import Path

from .. import alt_draft, alt_images, translation_prompts
from ..project import ProjectContext
from . import claude_runner, claude_tasks

# The tasks of the bubbles. Their rules are the user's own prompts, which the backends put in at each call.
DESCRIBE = claude_tasks.Task("describe_images", "", alt_draft.RESPONSE_SCHEMA)
TRANSLATE = claude_tasks.Task("translate_images", "", {
    "type": "object", "properties": {key: {"type": "string"} for key in ("short_de", "long_de", "takeaway_de")},
    "required": ["short_de", "long_de", "takeaway_de"], "additionalProperties": False})


@dataclass
class _ClaudeBackend:
    ctx: ProjectContext
    claude: Path
    model: str = claude_runner.MODEL
    effort: str = claude_runner.EFFORT
    cancel: threading.Event = field(default_factory=threading.Event)    # set: the running process is ended
    is_local = False        # takes no Ollama slot

    @property
    def label(self) -> str:
        return f"Claude {self.model}"

    @property
    def provider(self) -> "_ClaudeBackend":
        """What a run of the Images page holds, as it holds the provider of a ModelBackend: it says whether
        the run needs the Ollama slot (never) and abort() ends it."""
        return self

    def abort(self) -> None:
        self.cancel.set()

    def _ask(self, task: claude_tasks.Task, request: str, deadline_s: float,
             images: tuple[Path, ...] = ()) -> tuple[dict, str]:
        """(the answer, "") or ({}, why there is none)."""
        run = claude_runner.run_json(self.claude, task, request, self.model, self.effort,
                                     time.monotonic() + deadline_s, self.cancel, images)
        return ({}, "Cancelled") if run.cancelled else (run.answer or {}, run.error)


class ClaudeDraftBackend(_ClaudeBackend):
    def draft(self, image_path: Path, context: alt_draft.SlideContext) -> alt_draft.DraftResult:
        started = time.monotonic()
        if image_path.suffix.lower() not in claude_runner.MEDIA_TYPES:
            return alt_draft.DraftResult(model=self.label, error=f"Claude cannot read {image_path.suffix} images")
        answer, error = self._ask(replace(DESCRIBE, rules=alt_draft.effective_system_prompt(self.ctx)),
                                  alt_draft.build_prompt(context), claude_runner.IMAGE_DEADLINE_S, (image_path,))
        elapsed = time.monotonic() - started
        if error:
            return alt_draft.DraftResult(model=self.label, elapsed_s=elapsed, error=error)
        return alt_draft.draft_from_fields(answer, self.label, elapsed)


class ClaudeTranslationBackend(_ClaudeBackend):
    """Translates the three English fields of an image into German in one process; the prompt is the one
    configured for the translations (translation_prompts), the fields go in the request."""

    def translate(self, entry: alt_images.ImageEntry) -> alt_draft.TranslationResult:
        started = time.monotonic()
        source_hash = alt_images.en_text_hash(entry)       # of the text translated, as in ModelTranslationBackend
        prompt = translation_prompts.get_effective_prompt(self.ctx, self.model, "en", "de").prompt
        request = "\n\n".join(("Translate the fields of this image description. A field that is empty stays empty.",
                               f"short:\n{entry.short}", f"long:\n{entry.long}", f"takeaway:\n{entry.takeaway_default}"))
        answer, error = self._ask(replace(TRANSLATE, rules=prompt), request, claude_runner.TEXT_DEADLINE_S)
        text = {key: str(answer.get(key) or "").strip() for key in TRANSLATE.schema["required"]}
        return alt_draft.TranslationResult(
            short_de=text["short_de"], long_de=text["long_de"], takeaway_de=text["takeaway_de"], model=self.label,
            elapsed_s=time.monotonic() - started, error=error or None, source_hash=source_hash)
