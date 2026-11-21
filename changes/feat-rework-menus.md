kind: new
reason: direct request: the menus are far too crowded, so the user cannot find what they need

Rework of the menus (docs/handover.md, task rework-menus). menus.py: MENU_BAR is re-laid-out (new Project and Present menus, Housekeeping folded into Project, Build starts with a "Compile PDF" section, Deck and Slide menus with headings), `Item` shows a command under a shorter title than the registry's, build_compile_menu shares COMPILE_PDF and TRANSCRIPTS with Build, the pinned deck group is headed "Pinned". New commands: slide:section_after, section:slide_start, section:section_after, transcript:both; slide commands renamed (Slide before/after, Section before/after, Translated slide...). Slide list menus (one slide, several, section) use headings and Visibility / Move to section flyouts. Tab menu: Duplicate tab, platform wording of the reveal entry (open_path.REVEAL_TEXT). Deck settings gets a Tags tab (GroupPicker, deck_actions._save_tags). The preview menu is Open / Render only; the selection-as-frame / selection-as-element render and the reveal step are removed all the way down (preview_view, preview_requests.RenderOptions, preview_target, slide_preview, preview_cli). Tests updated.

NEW: The menus are shorter and grouped under headings, so the common actions are one or two clicks away.
- New Project menu (image descriptions, library, log, .bib and test-slides files, housekeeping) and Present menu.
- Build starts with the PDFs; Deck and Slide menus have headings; Tags moved into the Deck settings.
- The slide list's right-click menus have headings and fold Visibility and Move to section into sub-menus.
- Right-clicking a tab offers Duplicate tab.
- The preview menu is shorter; rendering a selection as a frame or element and showing a single reveal step were removed.
