kind: new
reason: direct request: images on notes pages

\SMNoteImage[keys]{file} in latex/SlideMage_base.tex puts an image inside \note{...}, scaled to fit 90% of the note's width and 45% of the page height (keepaspectratio), because beamer's note page does not break: an image taller than the notes area was cut off and pushed the note's text off the page (checked with a tall image in a plain beamer presenter compile; not in a full SlideMage presenter compile). Keys are \includegraphics keys and override the limits. The help catalogue (latex_help.py) and docs/SlideMageCommands.md describe it. The unused-media scan reads the slide source, so an image used only in a note counts as used; notes are typeset only in the presenter compile, so no alt text is involved.

NEW: Notes pages can show images.
- Write \SMNoteImage{media/picture.png} inside a \note{...}; the image is scaled to fit the notes page, so a tall one no longer pushes the note's text off it.
