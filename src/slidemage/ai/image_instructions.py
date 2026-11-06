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
    "language's code. The conversation's language does not override the slide/deck language. "
    # v0.14.25, direct request: a new tikz diagram on slide wum was not an image for SlideMage.
    "A tikz drawing is an image for SlideMage (listed on the Images page, described, read out by screen readers) "
    "only inside \\begin{tikzillustration}[options]{ID} ... \\end{tikzillustration}, whose options are "
    "tikzpicture's. When you draw a new tikzpicture that shows content a reader learns from (a chart, a diagram, a "
    "timeline), first ask the user whether SlideMage should treat it as an image. If yes, write it as a "
    "tikzillustration whose ID is the slide's id followed by -tikz (the id is the start of the file name: "
    "wum-...-current.tex gives wum-tikz; a second one on the same slide gets -tikz2, and so on), and tell the user to "
    "describe it with Draft... on the Images page. Never wrap a tikzpicture that is an overlay at page positions "
    "(overlay, remember picture), one nested in another tikzpicture's node, or one that only draws a border around "
    "an \\includegraphics.")
