kind: fixed
reason: direct request: American spelling of color

The British spelling "colour" (and Colour, colours, coloured, COLOUR) became "color" in the app's text, comments, docstrings, identifiers (theme_fields kind, MACRO_COLOURS, _COLOUR_RE and the like), tests, README, docs, the LaTeX files' comments and the example deck. Left as they are: the CHANGELOG history, the handover, changes/, the spelling checker's own word lists and tests (they must still accept "colour" as British English), and the TeX macro \SM@rolecolour, which saved themes may call.

NEW: The app's text now spells "color" the American way throughout.
- Menus, dialogs, notes and the documentation say "color", not "colour".
