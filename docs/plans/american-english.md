# American English in the app's text: inventory

Status: **groups 1 done (2026-11-12): the theme form in v0.16.24, the rest of the app's visible text and the AI's prompts in v0.16.25 (branch `fix/american-english`). Open: the shown name of Grayscale, and group 3 (CHANGELOG history, LaTeX comments, docs).** The table below is kept as the record of what was changed.

The app's default is American English ("color", "center", "canceled", "gray"). An inventory of British spellings in
the string literals of `src/slidemage/**/*.py` (docstrings and comments left out) found 199 strings; about 50 of them
were the theme form's and are changed. What is left falls into three groups.

How it was found: every string token that is not a docstring, matched against colour, grey, centre, licence,
millimetre, behaviour, neighbour, favour, labelled, cancelled, and the -ise/-yse verbs. The app already writes "color"
385 times in `ui/` and "center" 12 times, so the British forms are the exception.

## 1. Text the user reads: to change

| Where | Text |
|---|---|
| `ui/dialogs/deck_settings.py:176-180` | "The colour mode of this deck's slides…", field label "Colours", "A template declares its colour modes (light, dark, grey ...)…" |
| `ui/workspace/compile_actions.py:104-105` | "Compile in another colour mode", "Colour mode for this PDF…" |
| `ui/workspace/actions.py:71` | "another colour mode…" (the Compile menu's entry; `tests/test_compile_flow_gui.py:378` asserts it) |
| `ui/workspace/source_view.py:586` | "Follows the colour mode" (Color menu header; `tests/test_source_view_gui.py:618`) |
| `ui/workspace/menus.py:162` | View menu: "Centre" (the submenu of the centre column's modes) |
| `ui/presentation/controller.py:254, 260, 297, 316` | pen and laser tooltips ("the pen's colour and width"), the "Colour" button, "… colour" |
| `ui/presentation/settings_page.py:61-65, 103, 142` | "Laser pointer colour", "Pen colour", "… change their colour and size…", "Timer behaviour", "Colour" |
| `ui/pages/image_runs.py:65`, `ui/workspace/task_bubbles.py:593, 598` | "Pending images are cancelled, not moved…", "Slides not started are cancelled…" |
| `updater.py:373` | "Download cancelled." |
| `background_renders.py:810, 902`, `batch_render.py:140, 198`, `filelock.py:103`, `preview_format.py:244`, `preview_requests.py:210-224`, `step_renders.py:132` | "Preview cancelled" (one message in ten places; some places compare it, so all change together) |
| `compiler.py:207` | job label "· dark colours" |
| `deck_settings.py:269` | "This deck has no institution template input for a colour mode." |
| `readability.py:414-415` | the contrast finding: "between the text colour and its background…", "text colour or a lighter background." |
| `compat_color_cut.py:139-145`, `compat_color_roles.py:318-443`, `compat_hooks.py:77` | the Update project notes ("Dark slides are a colour mode…", "colours rewritten to roles: …") |

Text only the AI reads (prompts and tool descriptions), same spelling rule for consistency: `ai/guides.py:84, 108`
("[c] centres a frame"), `ai/tasks.py:80, 171` ("neighbouring text"), `ai/tools/slidemage.py:177` ("labelled images"),
`alt_draft.py:100`.

Search keywords (`ui/workspace/actions.py:252`, "dark light colours mode handout"): add "colors", keep "colours", so
both spellings find the command.

## 2. Internal names: to leave

These are ids in code, settings files or projects, not text: changing them breaks stored data or is churn without a
visible effect.

- `"cancelled"`: the status value of a render or task result (`ai/task_result.py`, `batch_result.py`,
  `batch_render.py`, `ai/tools/*.py`, `ui/workspace/compile_*.py`, `preview_view.py`).
- `"centre"`: the centre column's id in layout and reload calls (17 places), `"centre_tabs"`, the module
  `ui/workspace/centre.py`.
- `"colour-roles-in-slides"` (`compat_color_roles.py:43`): the id of a compat change, recorded in projects.
- In the theme code: the kinds `"colour"`, `"modecolour"`, `"optional_colour"`, the mode and preset id `grey` (a TeX
  id: `\SMDeclareMode{grey}{grey}`, shown as "gray"), `colorblind`, and the TeX macro `\SM@rolecolour`.
- Done in v0.16.26: the shipped theme Greyscale is **Grayscale** throughout (key `grayscale`, file
  `SlideMage_template_grayscale.tex`); no deck used the old key, so there is no migration.
- Python names (`own_colours`, `CODE_COLOURS`, `_colour_dialog`, `_neighbours_cache`), docstrings and comments.

## 3. Other text, not in the inventory's count

- `src/slidemage/CHANGELOG.md`: 170 lines with a British spelling. The "NEW:" paragraphs are shown to users after an
  update. Old entries are history; the rule should hold for new entries from now on.
- `latex/SlideMage_setup.tex` (61 lines), `SlideMage_base.tex` (27), `beamerthemeSlideMage.sty` (26), the shipped
  templates: comments, read by theme authors. The section title "Colour modes and role colours" is cited by name from
  Python docstrings and tests.
- `docs/` (THEME_PACKAGE.md, PLUGIN_GUIDE.md, SlideMageCommands.md, the plans) and the website repository: not counted.

## Suggested order

1. Group 1 in one change, with its tests (two assert the text; the "Preview cancelled" message is compared in code).
2. Done: Grayscale (v0.16.26). Decided 2026-11-12: British spellings stay in the CHANGELOG and in comments.
