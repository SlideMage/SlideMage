# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared image-description instructions for interactive assistants and the image guide."""

IMAGE_DESCRIPTION_RULES = (
    "Image descriptions (alt text) in media/alt-text.json must use the slide's language "
    "(the EN/DE segment in its filename), or the deck's editing language for multilingual slides "
    "or deck-wide work. For German (DE), write both the short and long descriptions in German "
    "in short_de and long_de (and takeaway_de if supplied). For English (EN), use short and long "
    "(and takeaway). Preserve existing descriptions in the other language and unrelated image "
    "metadata; never put English text in the German fields. The conversation's language does "
    "not override the slide/deck language.")
