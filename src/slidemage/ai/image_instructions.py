# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared image-description instructions for interactive assistants and the image guide."""

IMAGE_DESCRIPTION_RULES = (
    "Image descriptions (alt text) in media/alt-text.json must use the slide's language "
    "(the language segment in its filename, such as EN, DE or FR), or the deck's editing language for "
    "multilingual slides or deck-wide work. Each image keeps its text per language under \"text\", keyed by "
    "the language code in lower case: write the short and long descriptions (and the takeaway_default, if "
    "supplied) of that language in that language, in text.<code>.short, text.<code>.long and "
    "text.<code>.takeaway_default; a slide's own takeaway goes in used_on.<slide>.takeaway.<code>. Preserve the "
    "texts of the other languages and unrelated image metadata; never put text of one language under another "
    "language's code. The conversation's language does not override the slide/deck language.")
