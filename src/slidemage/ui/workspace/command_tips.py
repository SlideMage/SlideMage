# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The hover text of every command of the workspace (actions.py), shown in the menu bar, the top bar's menus and
the slide list's context menus (2026-11-24, direct request: "hover texts to all menu item entries").

A tip says what the command does, in a sentence the label has no room for. TIPS holds the commands by id; the
families that actions.py generates (one per view, language, panel, task, ...) have one text each in FAMILIES, keyed
by the id's prefix, where "{}" is the rest of the id. tip_for() picks the text; tests/test_command_tips.py makes sure
every command of the registry has one.
"""
from __future__ import annotations

from ...languages import name as language_name
from .menus import VIEW_LABELS

TIPS: dict[str, str] = {
    # View & build
    "preview:all-saved": "Render the focused slide in every view (instructor, during and after course) from the "
                         "saved file.",
    "preview:all-buffer": "Render the focused slide in every view from the text in the editor, saved or not.",
    "preview:force": "Render the preview again even when a finished render of the same slide is cached.",
    "column:left": "Show or hide the slide list on the left.",
    "column:right": "Show or hide the side panel on the right.",
    "compile:current": "Compile the deck's PDF for the view shown now.",
    "compile:all": "Choose which PDFs and transcripts of this deck to make, then make them in one run.",
    "compile:mode": "Compile the current view once in another color mode of its template (for example a light "
                    "handout of a dark projection), into its own PDF.",
    "compile:chapters": "Compile the after-course version as one PDF per chapter.",
    "compile:presenter": "Compile the PDF for presenting with speaker notes.",
    "compile:slides": "Compile a PDF of only the selected slides.",
    "compile:pages": "Compile a PDF of chosen pages, by number (for example 4, 7-10).",
    "compile:several": "Choose several decks and compile them one after the other.",
    "compile:everything": "Compile every view of every deck that is not archived.",
    "transcript:both": "Write the accessible transcript (Markdown and HTML) of both student versions.",
    "stop": "Stop the compilation that is running.",
    "build_options": "Settings for compiling: engine runs, output folder, what to keep.",
    "log": "Show or hide the compile log.",
    "render_buffer": "Render the preview from the text in the editor, without saving it.",
    "tab:next": "Go to the tab used most recently before this one.",
    "tab:previous": "Go back through the tabs, least recently used first.",
    "tab:next_in_order": "Go to the next tab in the tab strip.",
    "tab:previous_in_order": "Go to the previous tab in the tab strip.",
    "tab:close": "Close the active tab (the slide tab stays).",
    "save": "Save the file open in the Source view.",
    "find": "Find text in the file open in the Source view.",
    "replace": "Find and replace text in the file open in the Source view.",
    # Slide
    "slide:open": "Open the slide's LaTeX source.",
    "slide:preview": "Show the slide's preview.",
    "slide:open_tab": "Open the slide in a tab of its own.",
    "slide:images": "Open the slide's images on the Image descriptions page.",
    "slide:reviewed": "Mark the slide as reviewed after an AI edit.",
    "slide:review_mark": "Put a REVIEW watermark on the slide in this deck, or take it away (\\SMReview); the "
                         "compiled PDF is not changed.",
    "slide:compare": "Show the slide as rendered before and after the last AI edit, side by side.",
    "slide:readability": "Check this slide for text that is too small, too long or too dense (no AI).",
    "slide:readable": "Check this slide's readability, then let the AI fix what the check found.",
    "selection:rewrite": "Let the AI rewrite the text selected in the Source view; you choose how.",
    "selection:proofread": "Let the AI proofread the text selected in the Source view.",
    "slides:unreviewed": "Show only the slides that still wait for a review after an AI edit.",
    "slide:duplicate": "Make a copy of the slide under a new id and put it into the deck after this one.",
    "slide:translate": "Make a translation of the slide in another language of the project.",
    "slide:before": "Add a new slide before this one.",
    "slide:after": "Add a new slide after this one.",
    "slide:section_before": "Start a new section before this slide.",
    "slide:section_after": "Start a new section after this slide.",
    "slide:rename": "Change the slide's descriptive slug; the id and language stay, and every deck call follows.",
    "slide:delete": "Permanently delete the slide's files and its calls in all decks, after a check.",
    "slide:remove": "Take the selected slides out of this deck; their files stay in the project.",
    "slide:update_versions": "Give the selected changed slides a new version number.",
    "slide:clear": "Clear the selection of slides.",
    # Section
    "section:rename": "Rename this section.",
    "section:slide_start": "Add a new slide at the start of this section.",
    "section:add_slide": "Add a new slide at the end of this section.",
    "section:section_before": "Add a new section before this one.",
    "section:section_after": "Add a new section after this one.",
    "section:section_up": "Move this section, with its slides, above the previous one.",
    "section:section_down": "Move this section, with its slides, below the next one.",
    "section:remove_section": "Remove this section from the deck; you choose what happens to its slides.",
    # Deck
    "present": "Present the deck full-screen, with speaker notes on the second screen.",
    "present_here": "Present the deck from the selected slide on.",
    "open_pdf": "Open the deck's most recent PDF in the PDF viewer.",
    "deck_settings": "Settings of this deck: title, versions, language, template and more.",
    "deck_source": "Open the deck's LaTeX file, the list of its slides and sections.",
    "deck_tags": "The deck's tags, which decide its group in the deck switcher.",
    "new_deck": "Create a new deck.",
    "duplicate_deck": "Make a copy of this deck under a new name.",
    "export_pptx": "Export the deck as a PowerPoint file.",
    "export_latex": "Export the deck as a folder that compiles on its own, with its media.",
    "archive_deck": "Archive this deck: it leaves the deck switcher and the project-wide compiles.",
    "create_snapshot": "Save a frozen, self-contained copy of decks that compiles later exactly as today.",
    "rerender_deck_previews": "Render the previews of this deck's slides again.",
    "update_deck_versions": "Give every changed slide of this deck a new version number.",
    "deck:readability": "Check every slide of this deck for text that is too small, too long or too dense (no AI).",
    "deck:spelling": "Check the spelling of every slide of this deck (no AI).",
    "add_slide": "Add a slide to this deck: a new one or one the project already has.",
    "import_presentation": "Turn a PowerPoint or LibreOffice presentation into a new deck.",
    "refresh_decks": "Read the decks folder again, for decks changed outside SlideMage.",
    "archived_decks": "Open one of the archived decks.",
    "switch_deck": "Open another deck of the project.",
    # Project
    "palette": "Search commands, slides, decks and text in one box.",
    "autosave": "Save edits as you type; when it is off, Ctrl+S saves.",
    "images": "The page with every slide's images and their descriptions for the transcript.",
    "library": "Browse the project's slides and find similar ones.",
    "edit_bib": "Open the project's bibliography, SlideMage.bib, in the Source view.",
    "edit_test_slides": "Open test-slides.tex, the deck for trying out slides.",
    "open_project": "Open another SlideMage project.",
    "settings": "SlideMage's settings: general, AI, presentation, project, plugins.",
    "housekeeping": "Tidy the project: the pdf folder, temporary files, unused slides and media, previews.",
    "empty_pdf": "Delete every file in the project's pdf folder (asks first).",
    "remove_temp": "Delete LaTeX's temporary files (asks first).",
    "archive_unused": "List the slides and media no deck uses, then move the ones you keep ticked to the archive.",
    "update_previews": "Render every preview that is missing or out of date now, instead of in the background.",
    "sync_links": "Read every slide again and repair the links between slides and their translations.",
    "version_history": "What changed in each version of SlideMage.",
    "check_updates": "Look for a newer SlideMage and newer themes, citation formats and plugins now.",
    "plugins": "Install, update and remove plugins, themes and citation formats.",
    "project_compat": "Check whether this project needs changes for this version of SlideMage.",
    "debug_log": "Turn the detailed log of what SlideMage does on or off, for finding problems.",
    "debug_report": "Save the logs in one zip file, to send with a problem report.",
    "open_logs": "Open the folder with SlideMage's log files.",
    "exit": "Close SlideMage.",
    "open_manual": "Open the SlideMage manual as a deck.",
    "shortcuts": "The list of keyboard shortcuts.",
    # AI
    "ai:local": "Use the AI models that run on this computer.",
    "ai:cloud": "Use the cloud AI models.",
    "ai:setup": "Choose the AI models per task, the cloud connection and the project's AI setting.",
}

# Prefix -> text for the commands actions.py generates; "{}" is the rest of the id, through the formatter.
FAMILIES: dict[str, object] = {
    "view:": lambda v: f"Show the slides as the {VIEW_LABELS.get(v, v)} version shows them.",
    "language:": lambda code: f"Show the deck's slides in {language_name(code)}.",
    "mode:": {"preview": "Show only the slide's preview.", "split": "Show the source and the preview side by side.",
              "source": "Show only the slide's LaTeX source.",
              "details": "Show the slide's details: versions, decks, images, citations."},
    "compile:": lambda v: f"Compile the deck's PDF in the {VIEW_LABELS.get(v, v)} version.",
    "transcript:": lambda v: f"Write the accessible transcript (Markdown and HTML) of the {VIEW_LABELS.get(v, v)} "
                             f"version.",
    "selection:rewrite:": {"Simplify": "Let the AI rewrite the text selected in the Source view in simpler words.",
                           "Shorten": "Let the AI rewrite the text selected in the Source view shorter.",
                           "Custom…": "Tell the AI how to rewrite the text selected in the Source view."},
    "slide:visible:": lambda v: f"Show or hide the selected slides in the {VIEW_LABELS.get(v, v)} version of this "
                                f"deck.",
    "panel:": {"used": "The panel listing the decks that use this slide.",
               "versions": "The panel with this slide's versions: compare, restore, freeze.",
               "visibility": "The panel saying in which versions of the deck this slide shows.",
               "citations": "The panel with the slide's citations and their references.",
               "language": "The panel with the slide's language and its translations.",
               "images": "The panel with the descriptions of the slide's images.",
               "transcript": "The panel with the slide's entry in the accessible transcript.",
               "notes": "The panel with the slide's speaker notes."},
    "task:slide:": {"update_translation": "Let the AI bring this translated slide up to date with its original.",
                    "translate": "Let the AI translate this slide into another language of the project.",
                    "fix_latex": "Let the AI fix the LaTeX errors of this slide.",
                    "concise": "Let the AI make this slide's text shorter.",
                    "proofread": "Let the AI proofread this slide.",
                    "title": "Let the AI suggest a better title for this slide.",
                    "note": "Let the AI write speaker notes for this slide.",
                    "describe_images": "Let the AI describe the slide's images for the transcript.",
                    "translate_images": "Let the AI translate the descriptions of the slide's images."},
    "task:deck:": {"translate": "Let the AI translate the deck's slides into another language of the project.",
                   "update_translation": "Let the AI bring the deck's translated slides up to date with their "
                                         "originals.",
                   "fix_latex": "Let the AI fix the LaTeX errors of the deck's slides.",
                   "describe_images": "Let the AI describe the images of the deck that have no description.",
                   "summarise": "Let the AI summarise the deck; the summary is shown, not written anywhere."},
}


def tip_for(command_id: str) -> str:
    """The hover text of `command_id`, "" when there is none."""
    if command_id in TIPS:
        return TIPS[command_id]
    for prefix in sorted(FAMILIES, key=len, reverse=True):      # selection:rewrite: before any shorter prefix
        if command_id.startswith(prefix):
            rest, text = command_id[len(prefix):], FAMILIES[prefix]
            return text.get(rest, "") if isinstance(text, dict) else text(rest)
    return ""
