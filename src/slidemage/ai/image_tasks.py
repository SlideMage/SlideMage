# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Route-independent image description and translation task definitions."""
from .. import alt_draft
from . import tasks as ai_tasks

# The tasks of the bubbles. Their rules are the user's own prompts, which the backends put in at each call.
DESCRIBE = ai_tasks.Task("describe_images", "", alt_draft.RESPONSE_SCHEMA)
# A translation's answer: the short, long and takeaway text in the language asked for.
TRANSLATE = ai_tasks.Task("translate_images", "", {
    "type": "object", "properties": {key: {"type": "string"} for key in ("short", "long", "takeaway")},
    "required": ["short", "long", "takeaway"], "additionalProperties": False})

