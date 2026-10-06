"""SlideMage's own version string, shown in the main window's title bar and
the Info menu's version-history dialog (formerly gui.py's own toolbar,
back when that was the only display for it). Renamed from "SlideManager"
to "SlideMage" in v3.20.0 (see that entry below) -- older history entries
below intentionally still say "SlideManager"/"slidemanager", since they're
a dated record of what was true at each past release, not living
documentation.

VERSION_NUMBER below is hand-maintained, not derived -- a semantic-looking
"v2.9.0" says a lot more at a glance than a bare git hash ever did, but
only as long as it's kept current. IMPORTANT, standing instruction: bump it
in the same commit as any change to this app's code (SlideMage/ and
add_deck_headers.py) -- patch for a small fix, minor for a new feature or
UI change, major for a breaking/structural change. Never leave it stale;
a version number nobody trusts is worse than none at all.

Breaking releases (v4.1.0): a release that breaks with the past -- a
project, deck, setting or workflow that worked before no longer does, or
now behaves differently -- raises the major number AND its history entry
below gets a paragraph of its own starting "BREAKING:" that says what
changes and what to do about it. The release workflow copies the entry
into the GitHub release notes (packaging/release_notes.py, which refuses a
major bump without that paragraph), and the updater always asks before
installing such a release, even when updates install automatically
(updater.plan_update()). Raising project.PROJECT_FORMAT is always breaking.
Since v5.29.0 such a release also registers the change in slidemage/compat.py
(CHANGES: id, version, severity, how to fix, optionally a detector and a
migration); a test fails a BREAKING: paragraph without an entry. See the
README, "Project compatibility".

Estimated at v2.9.0 on 2026-07-28 from this app's commit history (`git log
--oneline -- slidemanager/`): v1.x covered the original compile/archive
tool through its Stop-compilation button; v2.0 began with the deck
slide-list editor, slide-source editor, and render-to-PDF, followed by
syntax highlighting, dark mode, several rounds of layout/UX fixes, the
deck-editor Undo button, a slide-edit render overhaul, the deck-source
"Source" button, return-to-originating-tab, and horizontal auto-scroll --
roughly nine minor-feature rounds into the v2 line by the time of this
estimate. This own version-display feature, plus this same round's
PDF-relocation copy-instead-of-move fix, round it up to v2.9.0. Continue
incrementing from here; this estimate does not need to be re-derived.

The nine entries below (v2.10.0 through v2.33.0) were backfilled on
2026-08-26 -- direct instruction, after it was pointed out that a real
v2.34.0 had existed for several days before the multi-language work's own
v3.0.0 correction (see that entry below), which this docstring's own
history skipped straight past. VERSION_NUMBER itself was kept current the
whole time (every commit in this range does carry its own real bump --
confirmed directly via `git show <commit>:slidemanager/version.py` at
each one, not assumed), but no dated paragraph was ever written for any
of them; the per-bump prose-history habit these entries model only began
with v3.0.0. Reconstructed the same way the v2.9.0 estimate above was --
from `git log`/`git show` against the real commits, not from memory.

v2.10.0 (2026-07-28 to 2026-08-11, reconstructed 2026-08-26): A slide search box, a formatting toolbar, and the full Tkinter to PySide6 migration, followed by a long run of Qt-specific polish. A top-right
slide search box; a second toolbar row for text-formatting/insertion
shortcuts; and the full PySide6 migration -- ten phases (environment
scaffold, QSS theme builder, main window shell, deck table + compile
threading, deck slide-list editor, slide editor, add-slide dialog, a
polish pass, and the actual cutover from Tkinter) -- followed immediately
by a long run of Qt-specific fixes and polish: tab elision, richer syntax
highlighting, header-comment fold, title-bar version display, a distinct
format toolbar, an extended insert-command menu, visible checkboxes,
itemize-wrap indentation, red Close buttons, a checkbox tick mark,
colored Text-color dropdown items, selected-tab text clipping,
active/inactive tab background colors, compile status dots kept next to
their own checkbox, hidden (not just disabled) checkboxes for unsupported
deck versions, an Underline formatting button, the app icon (rebuilt
several times from updated source art), and "Close and save" greyed out
until a slide actually has unsaved changes. Also: "Stop compilation" made
to actually interrupt a stuck PDF move, and the PyInstaller build
infrastructure (fixing the machine-local venv path on a machine whose
system Python is the Microsoft Store package).

v2.19.0 (2026-08-14, reconstructed 2026-08-26): Image descriptions and accessible transcripts shipped in four phases: decorative-image marking, a review tab, Ollama batch drafting, and transcript generation. Image descriptions and
accessible transcripts, in four phases (see ALT_TEXT_NOTES.md) --
decorative-image marking (a LuaTeX \\includegraphics wrapper tags them
/Artifact so screen readers skip them, verified with pikepdf across every
awkward call site); a review tab backed by per-slide %%ALT comment blocks
with a three-state staleness model (hashing comment-stripped slide source
plus every referenced image's own bytes, so a version-note edit doesn't
cry wolf but a re-cropped chart does); local-Ollama batch drafting,
resumable across sessions, that never overwrites a reviewed description
and detects the classic "faint scanned chart -> fabricated evenly-spaced
values" failure mode; and Markdown/HTML transcript generation that
resolves deck versions exactly as the PDF compile does. This one commit
jumps nine minor versions from v2.10.0 -- almost certainly several
same-session internal bumps that were never individually committed, the
same pattern this project's own later sessions repeat.

v2.20.0 (2026-08-14, reconstructed 2026-08-26): The invisible alt-text PDF layer: an informative image's short alt is typeset invisibly on the page for screen-reader text extraction. The invisible alt-text
PDF layer (phase 5) -- an informative image's short alt is typeset beside
it in PDF text rendering mode 3 (invisible on the page, returned by text
extraction), verified via pdftotext/PyMuPDF and a pixel-identical render
with and without it; plus citation rendering gained volume/issue/page
numbers.

v2.20.6 (2026-08-14, reconstructed 2026-08-26): A checkpoint before retiring the %%ALT block format: a drafting truncation fix, dark-mode contrast, a non-previewable-image button, and two transcript Markdown leaks fixed. A checkpoint before
retiring the %%ALT block format -- a drafting truncation fix (retry at a
larger token budget on dense charts), dark-mode scrollbar handle
contrast, an open-externally button for non-previewable images, per-image
role/status layout for multi-image slides, a collapsible alt-text comment
block in the source editor, and two systemic LaTeX-to-Markdown leaks
fixed in transcript.py.

v2.23.0 (2026-08-15, reconstructed 2026-08-26): Alt-text centralized into a single media/alt-text.json, compile-time PNG previews, per-slide transcript summaries, and a backgrounded fix for a PDF-move hang. Alt-text centralized into
a single media/alt-text.json (role/short/long/takeaway-default shared
once per image instead of split across a CSV and a per-slide comment
block, migrated with no real conflicts to resolve), compile-time PNG
previews refreshed by any compile that already happens, free-text
per-slide transcript summaries, and a real hang fixed -- a stuck PDF move
(cloud sync holding a lock) could freeze the whole compile queue; it now
runs on its own detached, safely-retrying background thread instead.

v2.24.0 (2026-08-15, reconstructed 2026-08-26): Template- and resolution-aware slide previews, a thumbnail-grid view, bulk preview regeneration, and automatic per-image source footnotes. Slide previews made
template- and resolution-aware (so two institutions' decks stop sharing,
and corrupting, one cache), each rendered directly from the compiled PDF
page instead of downsampled; a thumbnail-grid view for the deck editor;
and a bulk "Update previews" regenerate. The same version number also
covers 2026-08-20's automatic "Image source(s):" footnote (every image's
citation stored once and rendered automatically at compile time instead
of a hand-authored \\source{} per slide -- 167 of 281 images given a real
source, 152 slides' now-redundant \\source{} calls removed) -- committed
five days later with no version bump of its own.

v2.31.0 (2026-08-20, reconstructed 2026-08-26): Slidemaster.bib now auto-sorts on every Edit .bib tab open and close. Slidemaster.bib
auto-sorted on every "Edit .bib" tab open/close. Jumps seven minor
versions from v2.24.0, the same same-session-internal-bumps pattern as
v2.19.0 above.

v2.32.0 (2026-08-20, reconstructed 2026-08-26): A deck editor List/Thumbnail/Grid view toggle, deck-driven Update Previews, Edit/Duplicate deck-row buttons, and a source-editor Find bar. The deck editor's
List/Thumbnail/Grid view toggle; "Update previews" made deck-driven
(scans every deck for which template/slide combinations are actually in
use, rather than asking which single institution to compile everything
under); "Quick compile" replaced by separate Edit/Duplicate deck-row
buttons; and a Find bar in the slide-source editor (also covering
Slidemaster.bib and deck .tex files, which open through the same editor).

v2.33.0 (2026-08-21, reconstructed 2026-08-26): The whole per-slide version-tracking system -- \\setSlideVersion{}, the footer's version display, and the freeze-then-bump Save dialog -- migrated onto all 650 slides at once. The whole per-slide
version-tracking system this project still uses today --
\\setSlideVersion{}, the footer's "v1.2.0" display, and SlideManager's own
freeze-then-bump Save dialog (slide_versioning.py), migrated onto all 650
existing slide files at once; "Include footer timestamp" defaulted off;
and a compiled PDF's byte size is now verified before declaring a
relocation successful, instead of trusting "no exception raised" (a
cloud-sync-interrupted copy could previously produce a silently-accepted
0-byte PDF).

v3.0.0 (2026-08-24, direct instruction): Multi-language (EN/DE) support: slide-language filenames, deck-level \\decklanguage, rename/cross-reference tooling, and alt-text translation. Multi-language (EN/DE) support
-- new slide-language filename convention, deck-level \\decklanguage,
the slide-rename/cross-reference tooling, alt-text translation, language-
aware transcripts/preview cache (see LANGUAGE_NOTES.md) -- was first
landed as a minor bump (v2.34.0), then corrected to major on direct
instruction: a project-wide new capability like this warrants major even
though it's additive/non-breaking, not just "new feature or UI change."

v3.1.0 (2026-08-25, direct instruction): The app's first menu bar (Settings), plus per-(model, source language, target language) translation prompt configuration. A Settings menu (this app's
first menu bar) -- dark mode moved there from its own toolbar checkbox,
plus per-(model, source language, target language) translation prompt
configuration (translation_prompts.py, qt_settings_dialog.py), used by
alt_draft.OllamaTranslationBackend instead of the built-in default
whenever a matching entry exists. Also switched that backend from one
combined structured-JSON call per image to three separate plain "translate
this text" calls (short/long/takeaway) after direct testing showed the
combined approach unreliable on a dedicated MT model (sun_leaf/HY-MT).

v3.2.0 (2026-08-25, direct instruction): A user-editable default translation prompt, and one real bug caught in the same round: a storage-format change had silently dropped two already-saved per-model prompts. A user-editable *default*
translation prompt (translation_prompts.get_effective_prompt(),
Settings dialog's own "Default prompt" group), used for any model/pair
with no specific override -- get_prompt() alone is no longer the whole
story. Seeded with the translategemma:27b prompt. Also widened the
Settings dialog's From/To language combos, which an editable QComboBox
had sized down to a near-invisible sliver around their own 2-character
text. Caught and fixed one real bug in the same round: the storage
format change needed for the default prompt (a bare {model: ...} dict
becoming {"default": ..., "models": {...}}) silently dropped the two
already-saved per-model prompts the first time it ran, since the old
loader read the old flat file shape as empty -- caught by re-verifying
get_effective_prompt()'s exact-match resolution afterward, not assumed
correct, and fully recoverable since both prompts' exact wording was
still known. No real translation work was affected -- the corruption
happened after all 91 images from this same session were already done.

v3.2.1 (2026-08-25, direct instruction): Moved translation_prompts.json and dark mode's own storage into slidemanager/ itself, off the Windows registry, so both travel with the synced project folder. "everything pertaining to
SlideManager" belongs inside slidemanager/ itself and must keep working
purely from that folder being synced (this project's whole tree already
lives in a synced location) -- moved `translation_prompts.json` from the
project root into slidemanager/ (STORE_PATH now resolved from
`__file__`, not PROJECT_ROOT), and replaced dark mode's one-day-old
QSettings/registry storage with a plain gitignored `slidemanager/
app_settings.json` file (new module, app_settings.py) -- a registry key
is tied to one PC and would never have traveled with the folder to
another machine the way a file inside it does.

v3.3.0 (2026-08-25, direct instruction): Eight UI/workflow requests in one round, including a transcript-preview button, a Tabs menu, a Housekeeping menu, and a Duplicate-slide dialog with optional auto-translate. Eight UI/workflow requests in one
round -- a "Render transcript" button on the slide-source editor (one-slide
transcript preview in its own tab, transcript.py's generate_single_slide(),
qt_transcript_preview_tab.py); a "Tabs" menu (Archived decks/Images/Edit
.bib, none open by default any more, all closable -- previously two of
those three were permanent tabs and the third was a toolbar button); a
"Housekeeping" menu replacing the five maintenance buttons that used to
fill the bottom toolbar row, which is now gone entirely; unused_content.py
now strips LaTeX comments before matching, so a commented-out reference no
longer masks an otherwise genuinely unused file; "Quick navigation:" label
added before the deck editor's chapter combo; the slide-source editor's
toolbar split into two rows (Save/Revert/Find/Duplicate/Language above,
every render-related control -- Preview/Render version/Render language
(now hidden unless the slide's own text actually uses
\\multilingualtext{}{})/Render to PDF/Render transcript -- below); the find
bar repositioned to sit below the formatting toolbar rather than below the
folded header-comment block; and a "Duplicate slide" button
(qt_duplicate_slide_dialog.py) offering a plain same-language copy or a
cross-referenced translation into another language, the latter with an
optional (EN->DE only) machine-translation pass over the raw slide body
via alt_draft.OllamaTranslationBackend's new translate_text() method.

v3.3.1 (2026-08-25, direct instruction): The Images tab's Draft all… button now visually doubles as a red Stop button for as long as a batch is running. The Images tab's "Draft all…"
button now reuses the Close buttons' own red-outline/red-fill-on-hover
style (qt_theme.py's CLOSE_BUTTON) for as long as it doubles as "Stop" --
a drafting run in progress used to be signalled by text alone ("Stop"),
easy to miss in a long log-scrolling session; same
setObjectName()-then-unpolish()/polish() fix qt_slide_preview_popup.py's
own status_label already used to pick up a QSS rule change on an
already-styled widget.

v3.3.2 (2026-08-25, direct instruction): Three live-use fixes: the Render-language row's visibility now recomputes live, open deck editors refresh after a rename, and Stop is now rescindable. Three small fixes reported while
using the app live. The render bar's "Render language:" row previously
computed its own visibility once, from the file as opened -- renaming a
slide EN -> mult (or typing in a fresh \\multilingualtext{}{} call) left
it hidden until a close/reopen; new _update_render_language_visibility()
recomputes it from live state (current tag + current buffer) after both a
rename and a save, and now also shows as soon as a slide is tagged "mult"
at all, not only once the body already uses the macro. Renaming a slide's
language also left any already-open deck-editor tab showing it under its
old id-slug (that reference no longer resolving to a file on disk) --
new SlideManagerWindow.refresh_open_deck_editors() reloads the Active/
Archived tables and every open deck-editor tab from disk, called right
after a successful rename. And the Images tab's "Stop" button (mid-
drafting-batch) is now rescindable: clicking it again while it reads
"Stopping…" flips the stop flag back off instead of being a one-way
commitment.

v3.3.3 (2026-08-25, direct instruction): The Insert command… combo gained \\multilingualtext{EN}{DE}, seeding a selection into the first braces. "Insert command..." combo (the
slide-source editor's own formatting toolbar) gained
\\multilingualtext{EN}{DE} -- a selection goes into the *first* braces
(assumed English, matching that macro's own argument order) and the
cursor lands in the empty second braces ready for the translation; with
no selection, both pairs are empty and the cursor lands in the first one.
New _insert_multilingual(), a two-argument sibling of _wrap_or_insert's
existing single-argument \\macro{...} wrapping.

v3.3.4 (2026-08-25, direct report against a real "mult" slide, g6q):
Fixed a "mult" slide's transcript showing both languages concatenated together, from a title-stripping regex that collapsed both braces into one. Transcript.render_slide() never resolved \\multilingualtext{EN}{DE} calls
before extracting the title/body, so a "mult" slide's transcript showed
*both* languages concatenated together -- alt_blocks._slide_title()'s own
macro-name-stripping regex only removes the bare "\\multilingualtext"
token, then strips every remaining brace indiscriminately, collapsing
"{EN}{DE}" into "ENDE" rather than picking one. New
_resolve_multilingual_text() (brace-matched, so a nested \\textbf{...}
inside either argument survives) runs on the raw source text first, before
anything else derives from it. Verified directly against g6q's own file,
read-only: EN and DE renders each now show only their own language's
title.

v3.3.5 (2026-08-25, direct report -- running image drafting and
translation at the same time crashed): A single app-wide Ollama mutex now serializes every drafting/translation call, after running two at once crashed the local Ollama server. SlideManagerWindow gained a single
app-wide Ollama mutex (try_start_ollama_task()/end_ollama_task()) that
every Ollama-calling entry point now goes through -- single and batch
drafting, single and batch translation, the "Tune prompt…" dialog, and
qt_duplicate_slide_dialog.py's auto-translate option. A second attempt
while one is already running is refused with a message naming what's
currently running, rather than being allowed to fire a second concurrent
Ollama request; the crash is presumed to come from two different models
being loaded into VRAM at once, a limit of the local Ollama server itself,
not something this app can negotiate around, so a hard "one at a time" is
the reliable answer rather than trying to detect which combinations are
actually safe.

v3.3.6 (2026-08-25, direct instruction): "Mark reviewed" renamed "Save and mark reviewed", and a plain "Save draft" now correctly un-reviews just that slide's own use of the image. Images tab's "Mark reviewed"
button renamed "Save and mark reviewed" (it always saved too; the old
name undersold that). More substantively, "Save draft" now explicitly
un-reviews this slide's own use of the image it saves (use.reviewed = "")
instead of leaving review status untouched -- previously, hand-editing a
reviewed description via "Save draft" left it showing as "Reviewed"
against text nobody had actually re-checked; only entry.status (shared
across every slide using the image) is left alone, so another slide that
already reviewed the same image is unaffected.

v3.3.7 (2026-08-25, direct instruction): The drafting/translation model pickers now remember your last choice, and the menu bar gained System/Info entries including this version-history window. The Images tab's drafting-model
and translation-model pickers, plus the "Duplicate slide" dialog's own
auto-translate model choice, now remember the last one picked
(app_settings.json's "drafting_model"/"translation_model" keys),
preselected again on next launch if still installed --
DEFAULT_TRANSLATION_MODEL stays as the fresh-install/not-installed-anymore
fallback underneath that. Menu bar rearranged: "Settings" renamed
"System" with "Exit SlideManager" added below Preferences; a new
top-level "Info" action opens a version-history window that reads this
module's own docstring directly via the new parse_history() (no separate
changelog to maintain); Housekeeping's five actions now sit under two
labelled QMenu sections, "Cleanup" and "Updating".

v3.3.8 (2026-08-25, direct instruction/report): Three fixes to the per-image German translation workflow: a live staleness label, a backgrounded "Translate now", and an unsaved-edits prompt. Three fixes to the Images
tab's per-image German translation workflow. The "translation matches
current English text" label only ever reflected translated_from_hash as
of when the editor was built -- editing the English short/long text, even
saving it via "Save draft", never updated it until the whole editor was
rebuilt from a fresh disk read; it now flips to the stale message the
instant either field is edited and deliberately stays that way for the
rest of the session (no live re-check against the original wording).
"Translate now" blocked the whole app for the duration of three sequential
Ollama calls -- backgrounded via a new per-_ImageEditor translation_done
Signal, with a try/except around the cross-thread emit so a translation
that outlives its own editor (the user navigated to a different slide
while it was running) can't raise into the background thread instead of
being silently discarded; the Ollama mutex is released from the
background thread itself, not the GUI-thread signal handler, so it's
never left held just because the editor is gone by the time the request
finishes. And clicking "Translate now" with unsaved English edits now
asks whether to translate the current draft or the version on disk,
rather than silently always preferring the in-form draft.

v3.3.9 (2026-08-25, direct instruction): Switching slides while a translation is in flight now asks first, instead of silently discarding the result. Switching to a different slide
in the Images tab while one of the current slide's images has a
translation in flight now asks first ("Switch anyway?") instead of
silently discarding the result when it lands on a since-destroyed editor
-- QListWidget.currentRowChanged is the one funnel this goes through, so
a declined switch means reverting the list's own already-moved selection,
not preventing it (confirmed directly: the selection has already changed
by the time the signal fires). Deliberately does not fire during
_populate_list()'s own systemic clear()+reselect after a save (a
_suppress_switch_warning flag covers that whole call) -- confirmed
directly that QListWidget.clear() itself fires currentRowChanged(-1) as a
side effect, which would otherwise trip this check on a list that's
mid-rebuild for reasons that have nothing to do with the user choosing to
navigate away.

v3.3.10 (2026-08-25, direct instruction): The Settings dialog gained an Ollama models tab that lists and can delete installed models. Settings dialog gained an
"Ollama models" tab -- lists every installed model with its on-disk size
(alt_draft.list_installed_models_detailed()) and can delete one via
Ollama's own DELETE /api/delete (alt_draft.delete_model()), which removes
its actual files from the local model store, not just something this app
was tracking. Routed through the same app-wide Ollama mutex every
drafting/translation call already uses, so a model can't be deleted out
from under a batch that's actively using it.

v3.3.11 (2026-08-26, direct instruction): Every closable tab now always shows its close ×, instead of only revealing it on hover. Every closable tab (deck/slide
editors, Archived decks, Images, a transcript preview) now reserves extra
width and always draws its close "x", instead of only revealing it -- into
existing padding, no extra width reserved -- on hover. qt_closable_tab_bar.py's
own hover-tracking machinery (mouseMoveEvent/leaveEvent/_hovered_index) is
gone with it, since revealing the glyph on demand was its only reason to
exist; hit-testing now just checks whichever tab a click actually landed
on.

v3.3.12 (2026-08-26, direct instruction): Backfilled the nine missing v2.10.0-v2.33.0 history entries this docstring had skipped straight over. Backfilled the nine missing
v2.10.0-v2.33.0 history entries this file's own docstring had skipped
straight over (see that block's own explanatory note, right after the
v2.9.0 estimate above) -- a real documentation gap, not lost history: the
version *number* was current the whole time, just never accompanied by a
dated paragraph until v3.0.0. No functional change; parse_history()
picks these up exactly like any other entry, so the Info window's
version-history window now actually starts where the app's real history
does.

v3.3.13 (2026-08-26, direct report): Fixed settings/prompts silently resetting on every exe launch (a frozen-build temp-path bug), plus two smaller Images-tab and menu polish fixes. Fixed app_settings.py and
translation_prompts.py both silently resetting on every launch of the
compiled exe -- hand-edited translation prompts and the last-picked
drafting/translation models never survived a restart. Root cause: both
resolved their on-disk STORE_PATH from Path(__file__).resolve().parent,
which inside a frozen PyInstaller one-file build points into a fresh temp
extraction directory that's deleted on exit, not the real, persistent
slidemanager/ folder next to the actual .exe -- every save "worked" (no
error) but landed somewhere gone by the next launch. Never showed up in
this session's headless tests since none of those ran from the actual
compiled exe. Fixed both to resolve STORE_PATH from deck_scan.PROJECT_ROOT
instead, reusing the frozen-vs-dev resolution deck_scan.py already had to
solve the same problem for. Also: the Images tab was stretching far wider
than its own content needed and its label wasn't left-aligned -- Qt's
default QTabBar expanding=True was filling leftover bar width regardless
of tabSizeHint()'s own close-glyph allowance from v3.3.11; fixed via
setExpanding(False) plus an explicit text-align: left on QTabBar::tab. And
the System menu's dropdown had almost no right-hand padding around its
text -- this app's own blanket QWidget {...} QSS rule was already forcing
Qt to render menus through QSS instead of native Windows chrome, whose
default item padding is tighter, especially on the right; fixed with
explicit QMenu/QMenu::item/QMenu::separator rules.

v3.3.14 (2026-08-26, direct report): The Images tab now resets its own scroll position on every slide switch, and two stale doc references were fixed. The Images tab's form now resets its
scroll position to the top on every slide switch -- previously the
QScrollArea kept whatever position the just-destroyed previous slide's
form had been scrolled to, so e.g. clicking "Save and mark reviewed" and
landing on the next slide could show it scrolled partway down instead of
from the top. Also, readme.md's "Translating image descriptions/
citations" section still pointed at Settings -> Preferences... for
per-model translation prompts -- stale since v3.3.x's menu rename to
System; fixed, and added a line documenting the Ollama model-deletion tab
from v3.3.10, which had no documentation anywhere.

v3.3.15 (2026-08-26, direct report): Fixed the Images tab's still-centered label by hand-painting closable tabs instead of relying on Qt's own centered default. The Images tab's label still wasn't
left-aligned after v3.3.14's `text-align: left` QSS attempt -- confirmed
directly that Qt's built-in tab styles hardcode centered label painting
and simply ignore that property, unlike most other QSS-styled controls.
qt_closable_tab_bar.py's paintEvent() now draws each tab's shape via the
style (still fully QSS-themed) but paints the label itself -- left-
aligned, elided, underlined when selected, colored per its
setTabTextColor() role -- instead of letting Qt's own always-centered
label painting run at all. Also: the Settings dialog's Ollama models list
is now multi-selectable (ctrl/shift-click), and "Delete selected..."
deletes every selected model in one confirmation, reporting which ones
(if any) failed rather than stopping at the first.

v3.3.16 (2026-08-26, direct instruction/report): "Save draft" no longer jumps the Images tab back to the top, and "Translate now" gained a "Save, then translate" option. "Save draft" on the
Images tab no longer jumps the form back to the top -- v3.3.14's scroll
reset now only fires on an actual switch to a *different* slide (compared
by path), not on the same-slide reload every save triggers. Fixing this
surfaced a real pre-existing bug in _populate_list(): its own "re-show
explicitly" fallback after setCurrentRow() could run unconditionally even
when the currentRowChanged signal had already fired and handled the same
row, silently double-building that slide's editors on every reload --
harmless before (the second build just replaced the first with an
identical one), but very much not once an editor's own in-flight work
could get thrown away by it. Now only runs when _current_row_index shows
the signal genuinely didn't fire. Also: an image's "Translate now" dialog,
when the English draft has unsaved changes, now offers a third option
alongside "Unsaved draft"/"Version on disk" -- "Save, then translate"
-- which runs the same whole-slide Save draft the tab's own button does,
then automatically starts translating this image's just-saved text on
the freshly rebuilt editor, no second prompt needed.

v3.3.17 (2026-08-26, direct report): Retuned the closable-tab close-× gap, and fixed "Save draft" still jumping to the top plus "Render to PDF" ignoring the footer-timestamp checkbox. The gap between a closable tab's
label and its close "x" (e.g. the Images tab) was still visibly wide
after v3.3.15's left-alignment fix -- confirmed directly (measuring the
actual painted label/box positions) that the reserved width and the
resulting visual gap don't move 1:1, since the tab's natural width
already carries some built-in right-side slack before the close box's
own allowance is added; retuned so the gap is genuinely half what it was
(16px -> 8px), not just the reserved width. Also: "Save draft" on the
Images tab was *still* jumping to the top of the form despite v3.3.16 --
that fix compared the new slide against self._current, but
_populate_list()'s own slide_list.clear() fires a transient
_show_slide(None) as a side effect partway through every reload
(confirmed directly), which was zeroing self._current, then the
scrollbar itself, before the real same-slide reshow that followed it ever
got a chance to matter. Now tracked via a dedicated
self._last_shown_path that transient None call never touches, and the
scrollbar is left alone entirely while view is None (nothing is visibly
scrolled during that heartbeat anyway). And: the slide-source editor's
own "Render to PDF" always showed the footer timestamp regardless of the
main toolbar's "Include footer timestamp" checkbox -- that render path
never read it at all. render_slide_text_to_pdf() gained a
footer_timestamp parameter, mirroring compiler.py's own
\\gothamFooterTimestampOverride hook for a full deck compile.

v3.3.18 (2026-08-26, direct instruction): The Settings dialog now warns before closing with unsaved translation-prompt edits. The Settings dialog now warns
before closing if either translation-prompt form (the shared default, or
the per-model/per-language override currently shown) has unsaved edits --
neither field saves on its own, only its own dedicated Save button does,
so text sitting there when the dialog closed used to just vanish
silently. Save/Discard/Cancel, routed through a reject() override (the
one point the window's X button, Escape, and the Close button all already
funnel through) so all three close paths are covered by a single check.
Choosing Save re-runs each dirty form's own existing Save handler and
only actually closes if that succeeds (an empty prompt, say, stays open
with its own validation error already shown, same as clicking Save
directly always did).

v3.3.19 (2026-08-26, direct report): Another attempt at the persistent scroll-jump bug, this time by explicitly restoring the scroll position after Qt's own layout pass finishes. "Save, then translate" was still
jumping to the top of the Images tab form, even with v3.3.17's fix
(comparing the same-slide check against a dedicated
self._last_shown_path rather than self._current). Root cause this time:
that fix only ever left the scrollbar's *existing* value alone rather
than actively restoring it -- and every editor on the slide is destroyed
and rebuilt in between (setParent(None) on each, then new ones added),
which can itself shrink this scroll area's content down to nothing for a
moment. A real running Qt event loop can process that intermediate
resize and clamp the scrollbar's value right then, before the new editors
are even added back -- invisible to a synchronous headless test, since
nothing yields to the event loop for that intermediate layout pass to
actually run mid-test. _show_slide() now explicitly captures the
scrollbar's value before tearing anything down and restores it via
QTimer.singleShot(0, ...) afterward -- deferred one real event-loop tick,
so it runs *after* Qt has already sized the scroll area for the new
editors instead of racing that resize.

v3.3.20 (2026-08-26, direct instruction): A project-wide full-text slide search, plus on-demand PNG rendering of .pdf media for the Images tab preview and Ollama drafting. Two new features. First, a
project-wide full-text slide search (slide_search.py) -- unlike the
toolbar's existing "Find slide:" box, which only autocompletes on a
slide's own id/slug, this searches every slide's raw .tex body text
(case-insensitive substring, re-scanned fresh each search rather than a
maintained index, since ~665 small files scan in well under a second once
the OS has them in its own file cache). A new "Search text..." button
next to "Find slide:" (also Ctrl+Shift+F) opens a results dialog
(qt_slide_search_dialog.py) showing each match's slide id/title and a
snippet of context; double-clicking one opens it in the slide editor.
Second, .pdf media (media_render.py, PyMuPDF-backed, mirroring
slide_snapshot.py's own mtime-based cache-freshness check) is now
rendered to a cached PNG on demand for both the Images tab's own preview
(previously just "not previewable here" for every .pdf) and Ollama
drafting (previously silently skipped as undraftable, same as .eps still
is) -- the slide's own \\includegraphics{...pdf} is untouched either way,
only this SlideManager-side pipeline ever reads the rendered PNG. Minor
bump, matching this session's own precedent for a new capability sized
like this one (e.g. v3.3.9's switch-away warning, v3.3.10's Ollama model
deletion).

v3.3.21 (2026-08-26, direct instruction): Renamed the slide-search button and lengthened its result snippets. The slide-search button reads
"Search all slide texts..." (was "Search text..."), and its results'
context snippets are longer (150 characters of context on each side of a
match, up from 60 -- long enough to actually place a match in context).

v3.3.22 (2026-08-27, direct report): Two more attempts at the persistent scroll-jump bug, plus a try/except around the auto-translate call so a failure there stops being silent. "Save, then translate" was *still*
jumping to the top, even with v3.3.19's fix (a headless test of the exact
same mechanism had passed) -- and separately reported not visibly
starting the translation at all. Two changes, since the offscreen/headless
environment this project's own tests run in can't fully confirm either
theory (no real window, so no real native resize/paint round-trips to
race, and stderr from an uncaught exception is invisible in the compiled
app's windowed build regardless): the scroll-position restore now keeps
re-applying its target value in response to the scroll area's own
rangeChanged signal for 300ms, rather than trusting a single deferred
QTimer.singleShot(0, ...) call to land after Qt has *fully* finished
resizing for the rebuilt editors (a real onscreen window, with several
stacked editor panels each carrying their own nested layout, may need
more than one event-loop tick to settle that -- unconfirmable headlessly
either way). And the "Save, then translate" auto-triggered
_on_translate() call is now wrapped in its own try/except that logs
whatever it raises -- a direct Python call this deep inside a synchronous
save/reload/rebuild chain would otherwise abort silently partway through
_show_slide() on any exception, translation and the scroll-restore call
after it alike, with nothing visible pointing at why.

v3.3.23 (2026-08-27, direct instruction): Reordered the Images tab's fields so source comes after takeaway instead of before. Reordered each image editor's
fields on the Images tab so source/source_de come *after* takeaway/
takeaway_de instead of before -- short, long, takeaway, source (English),
then short_de, long_de, takeaway_de, source_de (German). Field order
only; nothing about how any of them are read, saved, or translated
changed.

v3.3.24 (2026-08-27, direct report): Added logging at every step of the translate pipeline, since "Save, then translate" was still silently not translating with no clue why. "Save, then translate" still not
visibly translating, with the log pane showing only "Saved draft for
..." and nothing past it -- reproduced the exact real slide/image
end-to-end (mocking only the Ollama HTTP call and the disk-touching
sync/update_store calls a test can't safely run for real) and it worked,
so the remaining, most likely explanation is one of several points in
this pipeline that failed *silently*, logging nothing at all either way:
whether the rebuilt editor's own auto-translate pickup ever found a
matching image, whether the background translation thread actually got
started, whether its result made it back to a still-live editor, and
whether it succeeded or failed once it did. Every one of those now logs
something to the log pane -- "Translating <image> into German
(<model>)...", "Translated <image> into German." / "*** Translation of
<image> failed: ... ***", "*** ... could not find <image> among this
slide's own images after saving ***", and "*** ... its editor panel was
already gone -- discarded ***" -- so whichever of these turns out to be
what's actually happening becomes visible instead of indistinguishable
from every other silent failure.

v3.3.25 (2026-08-27, direct report): Found the real root cause of the translate bug (a QListWidget signal firing mid-rebuild), plus a related bug where a plain save could land on the wrong slide. Found and fixed the actual root
cause behind "Save, then translate" not starting a translation, plus
three more Images tab fixes. The real bug (reproduced end-to-end against
the exact real slide/image from the report): QListWidget.addItem()
fires currentRowChanged repeatedly *while* refilling a previously-cleared
list, not just once via clear()'s own -1 (already relied on elsewhere in
this file) -- invisible with only a handful of rows, but a real, hundred-
row filtered list reliably landed a real, premature _show_slide() call on
some unrelated mid-rebuild row, silently consuming "Save, then
translate"'s one-shot state before the real final selection ever ran.
_populate_list() now blocks slide_list's signals for the whole clear()+
rebuild, so only the one, deliberate final selection can ever trigger a
rebuild. Separately, but discovered chasing the same report: a plain,
non-review save always clears *this slide's own* "reviewed" flag, which
can flip its state to something the *currently active filter* excludes
(e.g. viewing an already-reviewed image under a "Reviewed" filter) --
dropping it out of the filtered list the instant it's saved, so
reload()'s preserve-by-path matching can no longer find it and lands on
an unrelated slide instead. This explains "Save draft" jumping to the
top too (a real different-slide landing, not a scroll bug) and would have
broken the translate pickup even without the addItem() bug above. Fixed
with a one-shot _pin_visible_path that keeps the slide being saved
visible through its own reload regardless of the active filter (not for
"Save and mark reviewed" -- moving to a slide that still needs attention
stays the wanted behavior there).

Also: the "translation matches current English text" label used to
appear the moment an English edit was *saved*, before any real
translation ran -- root cause, the save's own mutate() re-stamped
translated_from_hash to the new English text whenever short_de/long_de
merely had *some* (possibly old, untouched) content, not only when the
German text itself had actually just changed to match; now compared
against the editor's own on-disk snapshot to tell "German changed this
save" from "German just happens to already exist." And every image in
the Images tab's own preview now has a thin gray border, so its edges
are visible even against the panel's own white background.

v3.3.26 (2026-08-27, direct report): Fixed the Images tab's image-preview border framing empty space around the image instead of the image itself. V3.3.25's image-preview border
framed the wrong box -- it was on the preview QLabel itself, which a
QVBoxLayout stretches to the panel's full width regardless of the
image's own, often-narrower, aspect-ratio-preserved size, so it outlined
empty space around the image rather than the image itself (visible
directly in a screenshot: a square logo, a wide gray-bordered rectangle
around it). The label is now sized exactly to its own scaled pixmap and
centered in a thin wrapper, so the border traces the image's actual
edges/dimensions instead.

v3.3.27 (2026-08-27, direct report): Fixed a stray dark-mode-colored gap left visible around a narrower-than-panel image preview. V3.3.26's fix (sizing the image
preview's label to its own scaled pixmap, rather than letting a
QVBoxLayout stretch it to the panel's width) left the space its own
centering wrapper opens up on either side of a narrower-than-panel image
rendering as this app's normal dark-mode widget background instead of
white -- previously invisible since the label's own white background,
before being fixed-size, covered that whole area regardless. The wrapper
now has the same explicit white background the label already did.

v3.3.28 (2026-08-27, direct instruction): Changed the Images tab's image-preview border from gray to magenta so it stands out against light images. The Images tab's image-preview
border is magenta (#ff00ff) now, not gray -- gray didn't stand out enough
against the many images with light/white backgrounds it exists to mark
the edges of.

v3.4.0 (2026-08-27, direct instruction): A new Export PPTX button compiles a deck and exports it as a real .pptx, one image per PDF page, for PowerPoint's own recording tools. A new "Export PPTX" button on
each active deck row -- compiles the deck (instructor version) and
exports the result as a real .pptx, one full-page image per PDF page
(pptx_export.py), so PowerPoint's own recording/presenter tools can be
used with a SlideMaster deck, which PowerPoint can't open directly. Every
PDF page becomes its own slide, including every beamer overlay/reveal
step -- what you actually want for a recording, not one slide per
\\slide{} call collapsing all its reveals into one. Uses the python-pptx
package (a new dependency, weighed directly against hand-building the
OOXML package by hand: this project has otherwise stayed deliberately
stdlib-first, PyMuPDF the one prior exception, but real stakes here --
an actual recording -- favored the well-tested standard way over a
hand-rolled package only as correct as this project's own understanding
of OOXML). Minor version bump, not patch: a genuinely new capability, not
a fix to an existing one (matches how multi-language support warranted a
major bump and this session's smaller feature/fix work has otherwise
stayed at patch level).

v3.5.0 (2026-08-28, direct instruction): Redesigned Export PPTX's reveal-step handling to stack one slide's steps with click-triggered fade animations, so ink annotations survive across reveals. Redesigned Export PPTX's own
reveal-step handling -- every PDF page belonging to one beamer \\slide{}
call (its own overlay/reveal sequence) is now stacked full-page onto a
*single* PowerPoint slide instead of getting one slide per page, first
reveal step on top, with a click-triggered "Fade" ("Verblassen") exit
animation on every image but the bottommost to peel each one away in
order. Motivation: PowerPoint's own ink annotations paint in a layer
above everything on a slide, so an annotation drawn during a live
recording now stays visible across that slide's own later reveal steps
instead of vanishing the moment the deck moves to the next PDF-page
slide, which is what v3.4.0's one-page-per-slide version did.
python-pptx has no animation API at all, so the click-triggered timing is
hand-assembled OOXML (pptx_export.py) -- verified directly against a real
PowerPoint installation via computer-use: built the real "Verblassen"
effect (and, before this feature settled on Fade, "Verschwinden") by hand
in PowerPoint's own UI, saved, and read its own generated XML back as
ground truth, then confirmed the generator's own output against it the
same way (Animation Pane populated correctly, a live slideshow run
clicking through an actual multi-reveal-step slide from a real compiled
deck). That verification pass caught two real bugs this session: a
missing nesting level in the click-effect XML (found via the ground-truth
diff) and, more subtly, a namespace URI typo in the generator's own `_P_NS`
constant ("openxml.org" instead of "openxmlformats.org") that made
PowerPoint silently discard every generated animation with no error and
no repair prompt -- caught only because a *multi*-effect export (unlike
the single-effect XML validated by hand-patching a real PowerPoint file,
which inherits its namespace from that file and so never exercises this
constant) showed an empty Animation Pane despite structurally correct-
looking XML. Patch-level in spirit (redesigning a feature from the same
session that was never actually shipped in a built .exe), but the visible
behavior change is substantial enough to warrant its own minor bump
rather than folding into v3.4.0's own entry after the fact.

v3.5.1 (2026-08-28, direct instruction): Fixed the slide-source editor's Tab key rendering far wider than intended. The slide-source editor's Tab
key rendered about 6 characters wide -- Qt's own QPlainTextEdit default
tab stop distance (80px) has nothing to do with SOURCE_FONT's own
character width, it just happened to work out that wide with Consolas
10pt. Now explicitly set to 2 characters, computed from SOURCE_FONT's own
QFontMetricsF rather than a hardcoded pixel count so it stays exactly 2
characters if that font ever changes (qt_slide_source_tab.py).

v3.6.0 (2026-08-29, direct instruction): Tab width is now a user-configurable, live-applied spinbox in Settings. The slide-source editor's Tab
width (v3.5.1, just above) is now user-settable -- a spinbox on the
Settings dialog's own General tab, right below the dark-mode checkbox,
persisted the same way (app_settings.py, key "tab_width_chars",
DEFAULT_TAB_WIDTH_CHARS=2 as the fallback when nothing's saved yet) and
applied live, the same live-refresh pattern set_dark_mode() already uses
for every open editor's highlighter: qt_gui.py's new
set_tab_width_chars() persists the choice, then calls a new
refresh_tab_width() on every tab in self._slide_source_tabs so an editor
already open when the setting changes picks it up immediately, not just
the next one opened. Minor bump: a genuinely new (if small) piece of user
-facing configuration, not a fix to existing behavior.

v3.6.1 (2026-08-29, direct instruction): Fixed the editor buffer not updating after a version-bump save, and the Language combo silently going unapplied if you saved without clicking Set. Two slide-source editor bugs.
(1) Saving a slide while bumping its version wrote the new
\\setSlideVersion{} line to disk correctly, but never updated the live
editor buffer (self.widget) to match -- the just-saved slide immediately
looked out of date in its own edit tab, still showing the pre-bump
version. Fixed with a new _apply_minimal_text_replace() (_on_save(),
qt_slide_source_tab.py): patches only the differing region between the
buffer text and what was actually saved, via a common-prefix/common-
suffix diff and a targeted QTextCursor edit, rather than a wholesale
setPlainText() that would have fixed the text but reset the cursor to the
top, discarded undo history, and jumped the scroll position on every
single save. (2) The "Language:" combo next to a slide's own Save button
is a genuinely separate action from Save (its own "Set" button, its own
confirmation dialog, since it renames the file and rewrites every deck
reference) -- but changing the combo and then saving without clicking
"Set" silently left the combo showing a value that no longer matched
reality, with nothing pending actually applied. New
_maybe_apply_pending_language_change(), called at the end of _on_save():
if the combo is left on a different, valid language than the slide is
actually tagged with, offers to apply it right there via the same
_on_set_language() the button itself calls (same confirmation dialog,
same rename machinery) -- but only then, since calling it unconditionally
would otherwise pop its own "can't be set back to untagged" error on
every single save of every still-untagged slide (the vast majority of
this project's 665 slides), where the combo correctly shows "(untagged)"
and nothing is actually pending.

v3.6.2 (2026-08-30, direct instruction): The Duplicate-slide dialog now hides irrelevant controls by mode, and "Preview"'s "Render now" finally respects the footer-timestamp checkbox. Two more small fixes. (1) The
"Duplicate slide" dialog's "New slide's language:" dropdown, auto-
translate checkbox, and model picker now hide entirely (not just gray
out) whenever "Just a duplicate (same language)" is selected -- none of
them mean anything in that mode, so leaving them visible-but-disabled was
just clutter (qt_duplicate_slide_dialog.py's _on_mode_change()/
_sync_translate_state()). The model row specifically stays hidden until a
translation will actually happen (checkbox checked AND the direction is
supported), not just whenever "another language" is picked. (2) The
"Include footer timestamp" toolbar checkbox was ignored by the "Preview"
button's own "Render now" (slide_preview.render_slide_to_pdf(), used by
both qt_slide_source_tab.py's _on_preview() and qt_deck_editor_tab.py's
_render_to_pdf()) -- a sibling bug to the one already fixed 2026-08-26 in
render_slide_text_to_pdf() (the separate "Render to PDF" button), which
this function was missed by at the time. Same fix: a new
footer_timestamp parameter, read live from the checkbox at both call
sites and threaded through the same _footer_timestamp_line() hook the
other render path already uses.

v3.7.0 (2026-08-31, direct instruction): The Add-slide dialog gained a "Duplicate existing slide" mode, the editor gained a smart Enter key, and "Refresh decks" now shows a wait cursor. Three editor/deck-table
improvements. (1) The
deck editor's "+ before"/"+ after" Add-slide dialog gains a third mode,
"Duplicate existing slide", alongside "Use existing slide"/"Create new
slide" -- picks a source slide, then launches the existing
DuplicateSlideDialog (qt_duplicate_slide_dialog.py, previously only
reachable from a slide's own source-editor tab) as a nested modal to do
the actual duplication (same language, or another language with an
optional auto-translate pass), and inserts the result into the deck at
the requested position once that dialog completes -- a one-step
duplicate-and-insert instead of duplicate-from-the-source-tab-then-
separately-add-it. Reuses that dialog rather than reimplementing
duplication, so the two entry points can never drift apart on what
"duplicate" means. (2) The slide-source editor's QPlainTextEdit
(qt_slide_source_tab.py) gains a smart Enter key (a new LatexPlainTextEdit
subclass): a new line always continues its predecessor's own leading
(tab) indentation, and pressing Enter right at the end of a
`\\begin{ENV}` line additionally opens the matching `\\end{ENV}` one line
below at the same indentation, cursor left in between at one extra tab of
indentation -- pre-seeded with `\\item ` when ENV is
`itemize`/`enumerate`. Detects the env name via the bare `\\begin{ENV}`
token rather than trying to regex-match the rest of the line, so it
still fires correctly when `\\begin{}` is followed by its own further
arguments on the same line (`\\begin{standardframe}{Title}`, a title
itself containing nested braces, etc.) -- confirmed directly against
that exact real-world case (kcc-Reasons-Repurchases's own title). (3)
The Active/Archived decks tables' own "Refresh decks" button now shows a
wait cursor (QApplication.setOverrideCursor) for the duration of the
rescan -- every deck file re-read and re-parsed, both tables' full row
widget trees rebuilt -- so a scan slow enough to notice has some visible
sign it's working. A thin qt_gui.py wrapper
(_on_refresh_decks_clicked()) around reload_decks() itself, not a change
to reload_decks() directly, since that function's many other callers
(after_deck_edit() and friends) are already fast/frequent enough that a
cursor flash on each one would just be noise.

v3.8.0 (2026-08-31, direct instruction): The Slidemaster.bib editor gained an A-Z jump bar to navigate its alphabetically sorted citations. The Slidemaster.bib editor tab
gains an A-Z "Jump to:" bar -- one button per letter, clicking one moves
the cursor (and scrolls, centered) to the first entry whose citation key
starts with that letter. Meaningful navigation specifically because the
file is already kept alphabetically sorted by key (bibliography.py's own
sort_entries(), run on open/close of this tab). Only appears for
Slidemaster.bib itself (a new self._is_bib flag, path ==
bibliography.DEFAULT_BIB) -- this same SlideSourceTab class also opens a
deck's raw .tex source, where a citation-key jump bar would be
meaningless. A letter with no matching entry logs a message instead of
silently doing nothing.

v3.9.0 (2026-08-31, direct instruction): A Reindent button recomputes a slide's own indentation from its \\begin{}/\\end{} nesting, and smart Enter now also continues \\item lines. Two more editor improvements.
(1) A "Reindent" button (slide files only, i.e. self._is_slide) recomputes
every line's own leading whitespace from its \\begin{}/\\end{} nesting
depth (one tab per level) -- reindent_latex(), a pure module-level
function so it's independently testable, with qt_slide_source_tab.py's
own _on_reindent() just the Qt-buffer/undo-step wrapper (the whole
document replaced as one edit block, so a single Ctrl+Z undoes the
entire pass). Deliberately scoped to \\begin{}/\\end{} line-start tokens
only, the same scope the smart-Enter feature below already commits
to -- not a full brace-nesting indenter, which would also have to reason
about braces inside math/macro arguments this project's slides use
constantly (\\textcolor{}{}, nested \\footnote{\\fullcite{}}, tikz node
options, ...). Confirmed directly against real content: a full scan of
every slide file found 230 of 651 with genuine drifted indentation (e.g.
22s-EN-More-Exotic-Bonds's own \\begin{minipage} body left at the same
depth as \\begin{minipage} itself rather than one tab in), all fixed
correctly; the other 421 are already-correct and reindent to a byte-for-
byte no-op. One known, accepted side effect: hand-added *extra*
indentation used to visually align a wrapped multi-line command argument
(e.g. a \\node[...] at (...) whose own {content} sits on the next line,
indented an extra level purely for readability, not environment nesting)
gets flattened back to the enclosing environment's own depth, since this
function has no concept of "argument continuation," only \\begin{}/
\\end{} depth. (2) LatexPlainTextEdit's smart Enter (see v3.7.0 above)
now also continues a `\\item` line: pressing Enter at the end of a line
starting with `\\item` inserts a new `\\item ` at the *same* indentation
(sibling items in one list, not nested content) -- checked only after
the existing \\begin{ENV} trigger finds nothing, so a line like
`\\item \\begin{itemize}` (an item that itself opens a nested list)
still gets that more specific begin/end handling instead.

v3.10.0 (2026-08-31, direct instruction): A Check syntax button asks a local Ollama model to flag likely LaTeX problems, offering a fix only when its claimed original text still matches exactly. A "Check syntax" button in the
slide and deck edit tabs (self._is_slide or a deck's own raw .tex source
-- excluded only for the Slidemaster.bib editor). Sends the editor's
current buffer to a local Ollama model (syntax_check.py, new module,
same call/parse shape as alt_draft.py's own OllamaBackend/
OllamaTranslationBackend, kept as a self-contained second copy rather
than importing that file's private helpers) asking it to find likely
LaTeX syntax problems -- unbalanced braces, mismatched \\begin{}/\\end{}
pairs, unescaped special characters -- and, only when confident, a
corrected replacement line. Explicitly framed everywhere in the UI as a
heuristic check via a language model, never a real LaTeX compile: it can
miss real problems and flag things that are fine, and the system prompt
tells it not to flag this project's own many custom macros just for
being unfamiliar.

The "offer to fix" half (direct instruction: implement it unless too
complex -- it wasn't) is safe specifically because every reported issue
carries the model's own claimed *original* text for the line it is
pointing at, alongside its suggested fix: SyntaxIssue.fix_is_safe()
only allows "Apply fix" when that original text matches the *live*
buffer's own line content exactly, so a hallucinated line number or
misremembered content just makes the fix unavailable rather than ever
overwriting the wrong line. Applying one edits the source tab's own
QPlainTextEdit as a single Undo step. New non-modal results dialog
(qt_syntax_check_dialog.py) -- deliberately not exec()'d, so the editor
underneath stays clickable while reviewing findings against it; clicking
an issue's own line number jumps/centers the editor there. Verified with
a mocked Ollama response, not just read over: a real slide's buffer, one
genuine matching issue (fix applied and confirmed undoable in one step)
and one deliberately mismatched "original" (confirmed its own Apply
button stays disabled).

v3.11.0 (2026-08-31, direct instruction): An AI draft button proposes an open-ended slide rewrite from a local Ollama model, shown as a diff, with the file's own header/version/overlay blocks mechanically protected from it. An "AI draft" button, slide
files only (self._is_slide -- unlike Check Syntax above, not offered for
a deck's own raw .tex source). An open, free-text prompt describing a
wanted change is sent, with the slide's current buffer, to a local
Ollama model (ai_draft.py, new module), which proposes a full revision;
shown as a line-level diff (difflib.ndiff, a small QSyntaxHighlighter
coloring +/- lines) in a new non-modal dialog (qt_ai_draft_dialog.py) --
nothing touches the editor until "Accept", which replaces the whole
buffer as one Undo step, same mechanism Reindent/Check-syntax-fixes
already use.

Asked first whether this was worth building at all, given an open
rewrite has no ground truth to verify a proposal against the way Check
Syntax's per-line fixes do (direct instruction: "tell me first how
feasible this is and what could go wrong" before implementing). Answer
implemented, not just discussed: mask_protected_regions()/unmask()
mechanically hide this slide's own leading header-comment block, its
\\setSlideVersion{} line, and every \\vbox to 0pt{...} block (this
project's own absolute-overlay idiom, README.md's "Available layouts"
section) behind opaque %%%PROTECTED_N%%% tokens *before* the model ever
sees the slide -- not a prompt-only request not to touch them. A
proposal that comes back missing, duplicating, or inventing one of
these tokens is refused outright (DraftProposal.error, never reaches the
dialog) rather than silently applied with a corrupted footer or an
altered version marker. This does not make the *rest* of a proposal
trustworthy (still an open rewrite from a local model -- the dialog's
own disclaimer says so plainly, and Accept is never automatic), only
removes one specific, mechanically-preventable failure mode.

Deliberately *not* protecting tikz/overlay content in general -- an
ordinary chart or diagram built with tikz is exactly the kind of thing a
rewrite prompt might legitimately need to touch; only the specific
\\vbox to 0pt{...} absolute-positioning wrapper is off-limits, since
that is calibrated pixel-level math with no meaning for a language
model to reason about.

Verified against every one of this project's own 651 real slide files
(not just synthetic examples): mask then unmask with no tampering
reproduces each file's exact original bytes, zero regressions. Also
verified with a mocked Ollama response end-to-end through the real Qt
dialog: prompt refused before any network call when empty; a legitimate
proposal shown correctly in the diff with protected content restored;
Accept applied and confirmed undoable in one step; a proposal that drops
a placeholder token refused rather than applied; the app-wide Ollama
mutex (try_start_ollama_task/end_ollama_task, shared with drafting/
translation/Check-syntax) correctly blocks a second concurrent request
and is released after the call whether it succeeded or not.

The displayed string also appends the commit date *and time* (not just
the date, per explicit request) of HEAD -- still git-derived, since
unlike VERSION_NUMBER itself it can't be hand-maintained without
drifting from reality (a launched GUI process never re-reads its own
source files, so this is still the only reliable way to tell which
commit a *running* instance actually started from). An earlier version
also appended a "+uncommitted" flag whenever the working tree had
uncommitted changes -- removed (2026-09-16, direct instruction): this
project is worked on directly in place, not from a clean checkout per
release, so that flag was true almost every time the app was actually
launched during active development, making it noise rather than signal.

v3.12.0 (2026-09-07, direct instruction): The alt-text workflow now covers hand-drawn tikz illustrations via \\tikzillustration{ID}, describable and role-markable the same way a real image is. The Images tab's alt-text
workflow now covers hand-drawn tikz illustrations, not just
\\includegraphics-ed files -- see ALT_TEXT_NOTES.md's "Phase 9" for the
full design. `\\tikzillustration{ID}` (Slidemaster_preamble_base.tex) wraps
an ordinary in-flow tikzpicture with a permanent, SlideManager-assigned
ID; it shows up in this tab's per-slide list as a synthetic "tikz:ID"
reference, with the same role radios and description fields a real image
already has -- nothing about the editor panel itself needed to change,
since it was already built generically from (reference, ImageEntry).
Marking one decorative wraps it in the same /Artifact type
sideimageframe's own filler image already uses, looked up through the
same media/alt-text.csv gothamalt.mark() already reads, keyed "tikz:ID"
instead of a real path -- no second place to author role, and no changes
needed to the Lua side at all. New tikz_render.py compiles an
illustration's current tikz body to a small standalone PDF (reusing
slide_preview.py's own wrapper-compile machinery), rasterizes it, and
auto-crops it to its own drawing, cached by a hash of the tikz source
itself -- what the vision-model drafting pipeline (Draft.../Tune
prompt...) and this tab's own preview panel both now feed on for a tikz
reference, through one new _resolve_for_drafting() dispatch point in
alt_draft.py. Verified directly: a throwaway slide with one informative
and one decorative tikzillustration compiled cleanly, and pikepdf
confirmed the decorative one's content sat inside a balanced
/Type /Background span while the informative one stayed unmarked;
tikz_render.ensure_rendered() was run end-to-end against a real slide file
(rendered, cached, cache-hit under 0.1s on a second call, and a
not-found id raised the expected error); sync_store() was confirmed to
discover a new tikz illustration the same add-only way it discovers a new
image; and one real end-to-end draft ran a rendered illustration through
qwen3-vl:32b.

v3.12.1 (2026-09-09, direct instruction): The version-history window's own entries now collapse to a one-line summary by default, with a show more/show less toggle. The Info menu's version-history
window now collapses each entry to a one-line summary by default (its own
first sentence, falling back to a plain word-boundary truncation for the
common case where that first sentence alone still runs long), with a
"[show more]"/"[show less]" link that expands or re-collapses just that
one entry in place (qt_version_history_dialog.py). Some of these
descriptions run to a dozen sentences; a window full of them at full
length meant scrolling past nine paragraphs to find the one entry actually
wanted. Implemented via a custom "toggle:N" link scheme intercepted
through QTextBrowser's anchorClicked() signal -- setOpenLinks(False) is
what actually stops the browser trying to navigate to it as a real
document (and blanking itself), a distinct property from
setOpenExternalLinks(False), which only ever governed http(s) links and
was already set. The scrollbar position is preserved across a toggle
(setHtml() resets it to the top on its own), so expanding one entry
doesn't jump the whole window back to the newest one.

v3.13.0 (2026-09-14, direct instruction/report): Wrapped 15 real tikz diagrams project-wide, fixed three real illustration-rendering bugs found doing it, and relabeled the review button with a matching re-check migration. The tikz-illustration
alt-text workflow (v3.12.0) went from built to actually used, and three
real bugs surfaced doing that. A structural (nesting/overlay/vbox-aware,
not a blind regex) migration wrapped the 15 tikz diagrams across this
project's own slides that turned out to be genuine standalone content --
excluding 163 absolute-position overlays, 43 nested inside another
tikzpicture's own node content, and (found by checking for actual drawing
primitives, not just structure) 16 that were only ever a bordered single
real image, which would have just duplicated that image's own already-
tracked description. Rendering all 15 (not just compiling them embedded
in their real slide) surfaced tikz_render.py silently dropping the
illustration's own tikz `[options]` (degraded silently for a *built-in*
style hook, hard-failed with "unknown key" for a *custom* one the options
themselves defined), a `\\newcommand`/`\\definecolor` declared above the
slide's own frame going undefined in a standalone recompile even though a
real deck compile already sees it, and one slide's own external
`\\resizebox{}{}{...}` wrapper (never part of the extracted illustration
body) leaving it clipped by a real slide's small canvas at native size --
all three fixed (`alt_blocks.py`, `tikz_render.py`; full story in
ALT_TEXT_NOTES.md's "Phase 9 follow-up"), all 15 re-verified after each.

Separately, direct report: a slide with more than one image is easy to
under-review, since "Save and mark reviewed" marks every image on the
slide reviewed in one click even if only one was actually looked at
closely. Relabeled "Save and mark <u>all images</u> reviewed" (a
combining low-line under each character of "all images", not HTML --
QPushButton does not parse rich text at all, confirmed directly), and
every slide that already showed fully "Reviewed" with more than one image
(9 slides, 20 image-uses) had its own per-slide review stamps reset to
"Needs re-check" as a one-off data migration alongside the rename, so the
new label reaches existing content, not just new reviews going forward.

v3.13.1 (2026-09-15, direct instruction): The review button's "all images" emphasis now only appears on a slide that actually has more than one image. The review button's own label
from v3.13.0 above now only says "Save and mark <u>all images</u>
reviewed" on a slide that actually *has* more than one -- plain "Save and
mark reviewed" otherwise, set fresh by _show_slide() on every slide
switch (_review_button_label(), qt_transcript_tab.py). The unconditional
wording was a permanent reminder that would have stopped standing out the
moment every slide's button said the same thing; this way the button
itself is the multi-image signal, present only when it means something.

v3.13.2 (2026-09-15, direct instruction): Every one of the 57 history
entries above now leads with a genuine, hand-written one-line summary,
and a real text-corruption bug from writing them was found and fixed.
Each entry's own collapsed view -- the version-history window's default
display since v3.12.1 -- is a real summary now, not a mechanical
first-sentence/character-count truncation that often landed mid-thought
or on an unhelpfully terse opening ("Two more editor improvements.").
Writing 57 summaries by hand surfaced a real, silent text-corruption bug
in the process: a LaTeX command reference inserted into this (non-raw)
docstring with only a single backslash isn't just a style inconsistency --
Python's own string parser reads `\\t`/`\\b`/`\\n` as their real escape
meaning (a tab, a
backspace, a newline) and quietly swallows the rest, which is exactly
what had already happened to `\\begin{}` in v3.9.0's own entry (a literal
backspace character sitting where the text should read "\\begin{}") and to
`\\newcommand` in v3.13.0's (silently split by a real newline, invisible
until this file's own runtime value -- not just its source text -- was
checked directly). Fixed globally across the whole docstring, all 57
entries verified to import with zero SyntaxWarnings and re-checked for
every affected command name still being intact in the actual parsed text,
not just judged by eye against the source.

v3.14.0 (2026-09-16, direct instruction): a new "Presenter" checkbox
(qt_deck_table.py) compiles a separate `<deck>-instructor-presenter.pdf`
using beamer's own built-in dual-screen mechanism (\\setbeameroption{show
notes on second screen=right}, gated behind a new \\ifdefined
\\gothamPresenterModeOverride hook in Slidemaster_preamble_base.tex,
compiler.py's own wrapper file \\def's it exactly like
\\deckversionoverride already is) -- every real slide becomes one wide
page, the plain slide on the left and a panel with that slide's own
\\note{} text on the right, for presenter software (pympress recommended;
see README.md's new "Presenting live" section) to split across the
projector and the presenter's own screen. Independent of every other
checkbox in the row, always instructor-version content regardless of
what else is ticked in the same batch (CompileJob.presenter, a new field
alongside version/chapter, not a value of version itself), with its own
status dot and its own jobname suffix. compiler.py's own compile-time
slide-preview-snapshot refresh is explicitly skipped for a presenter job
-- its doubled, side-by-side page layout has nothing in common with a
normal one-page-per-slide compile, so reading it the usual way would
misread pages and corrupt the real preview cache with it. Verified
directly, not just from beamer's own documentation: a real presenter
compile produces the expected wide combined pages, and \\note{} text
placed on a real test slide is confirmed present (both by direct text
extraction and visually) in the correct panel.

v3.14.1 (2026-09-10, direct report/instruction): a real \\note{} bug found
compiling a full presenter deck for the first time, plus a note-page
layout redesign. Compiling t-Uni-IA2-2026w's own presenter PDF end-to-end
(the first real multi-hundred-slide deck run through v3.14.0's own new
feature, not just the single-slide test it was verified against) failed
outright: slides/m47-EN-Portfolio-Risk-Variance-current.tex's own
\\note{...} call had two consecutive \\\\ line breaks with nothing but
whitespace between them ("Develop first, show after!\\\\\\\\ Cov
signifies..."), a genuine "There's no line here to end" LaTeX error --
invisible until now since beamer silently discards \\note{} content
whenever nothing actually renders it, which was every compile before
presenter mode existed. Fixed by replacing the doubled \\\\\\\\ with
\\par (valid in any context \\note{} can appear in, same visual
paragraph break intended); grepped every other slide's own \\note{} call
for the same doubled-\\\\ pattern and found none.

Also (direct instruction, same session): beamer's own default "note
page" template (beamerouterthemedefault.sty's
\\defbeamertemplate*{note page}{default}) reserves its top quarter for a
thumbnail of the current slide (\\insertslideintonotes) plus a rotated
compile-date beside it, then gives the title band (short title plus a
section/subsection/frametitle breadcrumb) that same 0.25\\paperheight,
leaving only the bottom 0.75 for \\insertnote -- redundant here, since
pympress (this project's own recommended presenter software) already
shows the current and next slide on its own screen, and \\title{} is
never called anywhere in this project (confirmed by grep), so the short-
title line was always blank. Two real problems found getting a
replacement working, neither caught until compiled against a real slide:
first, \\defbeamertemplate*{note page}{default}{...} here errors ("Command
\\beamer@@tmpop@note page@default already defined") -- both the starred
and unstarred \\defbeamertemplate forms register a variant name via a
plain \\newcommand internally, which always errors on a name beamer's own
outer theme already registered; fixed by registering a new named variant
("gothampresenter") instead and selecting it via \\setbeamertemplate{note
page}[gothampresenter], the same define-then-select pattern this file's
own footnote template already used. Second, a first attempt shrinking the
title band to a fixed 0.08\\paperheight overlapped real note text on a
real slide the moment its own section/subsection/frametitle breadcrumb
needed more than one line (this project's own decks do call \\section{})
-- fixed by dropping the fixed height/\\vfil entirely in favor of a
natural-height \\vbox (exactly as tall as whichever breadcrumb lines are
actually non-empty for that slide, never more), which structurally
can't overlap \\insertnote below it regardless of how many lines a given
slide's own breadcrumb needs. No color-theme "note title"/"note page"
background is set anywhere in this project, confirmed by grep, so
beamer's own \\ifbeamercolorempty guards around both of those bands --
already pure no-ops here -- were dropped too rather than carried over
unused.

v3.14.2 (2026-09-11, direct report): a second real tikz_render.py bug
found the same way v3.14.1's \\note{} bug was -- reported directly
against a real illustration, not caught by the single-slide test
v3.9.0-era tikz-illustration work was originally verified against.
previews/tikz_illustration_previews/ukm-tikz-*.png (the "Age of universe" label on
slides/ukm-EN-Tail-Risk-18-Sigma-current.tex's own tikz illustration) was
cut off on its own left edge: that label's `\\node[overlay, anchor=north,
align=center] at (\\linexcm,-1.3) {Age of universe};` sits centered within
a hair's width of x=0 (\\linexcm evaluates to ~0.004cm), so roughly half
its own text width bleeds into negative-x -- deliberately excluded from
the tikzpicture's own bounding box by `overlay`, the same mechanism
already known from ys3's own \\resizebox overflow (see v3.14.0's tikz-
illustration entry). Landed fine on a real slide, where that bleed lands
inside the frame's own ordinary left margin, but got clipped hard here
even after that same \\pagewidth=60cm/\\pageheight=60cm fix: enlarging the
*page* only adds room to the *right*/*bottom* of the frame's own small
(~128mm x 72mm) content block, which \\shipout still plants flush at the
page's true top-left corner regardless of how big \\pagewidth/\\pageheight
are -- zero margin on the *left*/*top* either way. Fixed generally, not
by special-casing this one diagram, with two new plain-TeX primitives
(\\hoffset=20cm, \\voffset=20cm, tikz_render.py's own _wrapper_text())
shifting the whole shipped page's content well clear of every edge, not
just the two \\pagewidth/\\pageheight already covered. Verified directly:
deleted the stale cached PNG (bytes now provably wrong, but the content-
hash cache key was unchanged since nothing about ukm-tikz's own tikz
source had changed, so it would otherwise have kept serving that same
clipped render forever) and re-rendered from the fixed wrapper, confirmed
both previously-cut-off lines now render in full. Also scanned every one
of this project's other 14 cached tikz-illustration previews for the same
edge-touching symptom (a cheap pixel check, not a full re-render of each)
-- one more flagged (ys3-tikz, content touching its own crop's top row)
but inspected directly and judged a false positive: a background color
panel's own legitimate top edge, not clipped text, and that illustration
was already directly re-verified complete end-to-end when v3.14.0's own
\\pagewidth/\\pageheight fix first landed.

v3.15.0 (2026-09-16, direct instruction): non-linear navigation
infrastructure plus a new "Generate appendix TOC" checkbox. Every real
slide now carries a permanent \\hypertarget{<bare id>}{} (Slidemaster_
preamble_base.tex's \\setSlideID@aux, the single choke point every
\\slide{}-family macro already passes through regardless of frame type),
giving any slide a free jump target for \\hyperlink{}/\\beamergotobutton{}/
\\beamerreturnbutton{} without colliding with this project's own documented
\\label{}/\\foreach collision. The new checkbox (qt_gui.py, between
"Include footer timestamp" and "Auto-open generated PDFs") adds, on an
Instructor/version-less or Presenter compile only, a generated appendix: an
agenda slide (one entry per chapter plus a leading "Front matter" entry)
followed by a 4x5 thumbnail grid per chapter (slidemanager/appendix_toc.py,
new module), each thumbnail using the existing slide_snapshot.THUMB_SIZE
cache and linking straight to its real slide; clicking a chapter on the
agenda jumps to that chapter's own grid, and the institute logo on every
slide of an appendix-enabled compile becomes an invisible link back to the
agenda (\\gothamInstituteLogoGraphic). Grid geometry (left-aligned to the
text margin, scaled up until either the row height or the logo's own right
edge binds -- direct instruction, from real rendered candidates) is
computed in LaTeX from this project's own per-institution length registers,
not a hardcoded cm value, so it adapts automatically across Graz/Innsbruck/
MCI. compiler.py's wrapper gains \\gothamAppendixTocOverride and, for an
appendix-generating job, inlines the deck's full body (the same "copy
preamble, splice body" trick already used for a per-chapter compile) so the
generated appendix can land before the deck's own \\end{document} -- a
plain \\input{deck.tex} would hit that \\end{document} first. Fixed along
the way: the appendix's own generated frames were leaving \\slideID at its
last real value, which would have corrupted slide_snapshot.capture_deck()'s
cache refresh (it keys purely off footer "slide id:" text) -- reset to a
literal "appendix" (never a real 3-character id) right after \\appendix;
and a \\dimexpr geometry calculation that multiplied by 304 before dividing
by 171 briefly exceeded TeX's ~16384pt dimension ceiling even though the
final result was a few centimeters -- reordered to divide first. Verified
via a real end-to-end compile (an in-memory scratch deck built from real
chapters/slides, run through the actual CompileJob/run_job pipeline): every
hypertarget lands on the right page, every agenda/grid/logo link resolves
correctly, and a combined Presenter+appendix compile produces the expected
notes-panel layout with no new errors.

v3.16.0 (2026-09-16, direct instruction): the Active/Archived decks
tables' long compile-options explainer (Instructor/During-course/After-
course, "After-course, per chapter", Presenter) was a permanently-visible
wrapped QLabel between the deck grid and the button row -- real vertical
space spent on every visit, read once and rarely again. Moved behind a
small "?" button next to Stop compilation (qt_deck_table.py): the same
text now shows on hover (tooltip) or on click (QMessageBox), out of the
way otherwise. No behavior change, no new dependency -- QMessageBox is
already part of PySide6.QtWidgets.

v3.16.1 (2026-09-16, direct instruction): the generated appendix's agenda
slide (appendix_toc.py) is now two columns (README.md's own "Available
layouts" pattern -- beamer's `columns` nested *inside* standardframe),
split roughly in half with any odd entry going to the left column --
needed for a deck with a full chapter list: IA2's own 13 entries (front
matter + 12 real chapters) ran off the bottom of a single-column agenda.
Verified against that real 13-entry list (a standalone test frame built
from the deck's own real chapter titles, dummy hypertargets, agenda
layout only): fits on one page with real headroom to spare, zero Overfull
warnings.

v3.16.2 (2026-09-16, direct instruction): the "Generate appendix TOC"
checkbox (qt_gui.py) is now persisted across launches via app_settings.py
-- the same local per-machine JSON store dark mode/tab-width/model-picker
settings already use -- instead of always resetting to unchecked like
footer_timestamp/auto_open still do. Read back with
`app_settings.get("appendix_toc", False)` at toolbar build time, written
on every toggle.

v3.17.0 (2026-09-16, direct instruction): a new "Open output folder"
checkbox (qt_gui.py), stacked directly below "Auto-open generated PDFs"
in its own vertical group rather than another flat entry in the
horizontal toolbar row -- opens pdf/ in File Explorer once a compile
batch finishes, if at least one job passed. Deliberately hooked into the
same PASS_LOG_RE match _open_pdf() already waits for, not run_jobs()'s
own return: a job "passing" run_jobs() only means the LaTeX compile
itself succeeded, while compiler.py's own _relocate_pdf_and_finish moves
the PDF into pdf/ on a separate, sometimes-still-in-flight background
thread -- opening the folder any earlier could show it before the file
was actually there. Opens at most once per batch (a new
_folder_opened_this_batch flag, reset in _start_jobs()) even when several
jobs pass, and is explicitly excluded from an Update-previews run (its
throwaway megadeck is never written to pdf/ at all) via the same
is_preview_all check auto-open already uses.

v3.17.1 (2026-09-16, direct instruction): top-aligned the compile-options
toolbar row (qt_gui.py) -- QHBoxLayout vertically centers each item
within the row's own height by default, and once the auto_open_checkbox/
open_output_folder_checkbox pair (v3.17.0) made that row two checkboxes
tall, every single-row checkbox beside it visibly drifted down instead of
lining up with the top one; fixed via per-item `Qt.AlignmentFlag.AlignTop`
on each addWidget()/setAlignment() on the nested auto_open_group layout
(QBoxLayout.addLayout() has no alignment parameter of its own). Also
added a PyInstaller splash screen (SlideManager.spec's new `Splash(...)`,
slidemanager/assets/splash.png generated from this project's own icon.ico
and palette.py's dark-mode colors) covering the one-file build's several-
second self-extraction delay -- qt_gui.py's main() closes it
(`pyi_splash.close()`, guarded for the unfrozen `python -m slidemanager`
case where that module doesn't exist) right after the real window is
constructed and shown. The one-file build itself stays as-is: already a
deliberate, documented trade-off (SlideManager.spec's own header comment)
against the several-hundred-loose-file churn a one-dir build would cause
in this project's synced folder.

v3.17.2 (2026-09-16, direct instruction): "Open output folder" (v3.17.0)
is now persisted across launches too, same app_settings.py pattern as
appendix_toc_checkbox -- read back with
`app_settings.get("open_output_folder", False)` at toolbar build time,
written on every toggle.

v3.17.3 (2026-09-16, direct instruction): reverted "Open output folder"
(v3.17.0/v3.17.2) entirely -- the checkbox itself, its app_settings.py
persistence, the _open_output_folder()/_folder_opened_this_batch
machinery, and the auto_open_group vertical grouping it needed (back to
a single flat toolbar.addWidget(self.auto_open_checkbox), same as before
v3.17.0 -- the per-item AlignTop tweaks from v3.17.1 came out with it
too, since a flat single-row toolbar never needed them). The splash
screen from v3.17.1 is unrelated and stays. Also: VERSION no longer
appends a "+uncommitted" flag when the working tree has uncommitted
changes -- this project is worked on directly in place rather than from
a clean per-release checkout, so that flag was true on nearly every
launch during active development and was noise, not signal.

v3.18.0 (2026-09-16, direct instruction): a deck can now redirect its own
compiled PDF to a custom folder -- see README.md's new "Custom output
folder" section for the full directive syntax. `\deckoutputfolder
[version]{path}` (a new, real but inert macro, `Slidemaster_preamble_
base.tex` -- matching this project's own convention that every deck-
authored, Python-parsed directive is a real command name, never a "%"
magic comment: confirmed no such convention exists anywhere in this
codebase before designing this one) is read directly out of a deck's own
source text by a new `deck_scan.py` regex (`OUTPUT_FOLDER_RE`), keyed per
version with a bare (no `[version]`) fallback line covering any version
without a more specific declaration; `Deck` gains an `output_folders`
field carrying that map. `compiler.py`'s new `resolve_output_dir(job)`
looks it up (normalizing a version-less job's `None` to `"instructor"`
so a bare `\deckoutputfolder[instructor]{...}` line works on any deck
regardless of whether it formally supports the version system) and
resolves a relative path against `PROJECT_ROOT`, falling back to the
existing `PDF_DIR` when a deck declares nothing. `run_job()` now calls
this instead of hardcoding `PDF_DIR` -- needing no change at all to
`_relocate_pdf`/`_relocate_pdf_and_finish`'s own copy2-based relocation
and retry/stall-avoidance logic (both already operate purely on whatever
`dest_pdf` Path they're handed, regardless of which folder it's in, which
is exactly why reusing that already-hardened code path here carries no
new move/stall risk). Per direct instruction: a custom-folder deck's PDF
goes there *only*, never also into `pdf/` -- `qt_gui.py`'s auto-open
follows the real destination too (a new `_job_output_dirs` map, resolved
once per job in `_compile_rows()` the same way `run_job()` does, so
`_open_pdf()` doesn't re-derive a `PDF_DIR`-only path). The compile log's
`MOVING`/`PASS` lines now show the real destination instead of a
hardcoded `"pdf/{jobname}.pdf"` string (confirmed `qt_gui.py`'s own
`MOVING_LOG_RE`/`PASS_LOG_RE` only anchor on the jobname right after
`"==== MOVING: "`/`"==== PASS: "`, never on what follows, so this is
safe). "Empty pdf/ folder" housekeeping and PPTX export's own output
folder are deliberately untouched -- out of scope for this request.
Verified via a real end-to-end compile (an in-memory `Deck` built from
real preamble text, `\deckoutputfolder` pointed at a scratch folder
outside the project, run through the actual `CompileJob`/`run_job()`
pipeline): the PDF landed only in the custom folder, `pdf/` got no copy,
the slide-preview snapshot cache still refreshed correctly against the
redirected PDF, and the log's own MOVING/PASS lines showed the real path
-- plus a separate regression check that a deck with no
`\deckoutputfolder` at all still resolves to `PDF_DIR` exactly as before.

v3.19.0 (2026-09-16, direct instruction): the Images tab gained a "Sort:"
dropdown (`qt_transcript_tab.py`, next to the existing "Show:" filter,
same `QLabel`+`QComboBox` toolbar idiom) listing every active deck --
picking one reorders whatever slides the current filter shows by that
deck's own `\slide{}`-family call order, with any slide not in that deck
kept at the end in whatever relative order it already had. Reuses
`deck_editor.parse_slide_calls(deck)` (already the project's own source
of a deck's real slide order, e.g. `appendix_toc.py`'s chapter grids) to
build a `{bare id: position}` map, cached in `self._sort_order` and
recomputed only when the dropdown's own selection changes (not on every
`_visible_rows()` call, which also runs on every single list click) --
`_visible_rows()` itself just does one stable `sorted(rows, key=...)`
over its already-filtered list, with a slide missing from the map falling
back to one-past-the-last-real-position so it always lands after every
slide the deck actually contains, and Python's sort stability keeps
missing slides in their prior relative order without a second tiebreaker.
Verified directly against this project's own largest deck (375 real
`\slide{}`-family calls, one repeated id confirmed via a real recap
slide): a scrambled id list sorted correctly into that deck's own order,
with ids never in the deck landing at the end in their original relative
order.

v3.19.1 (2026-09-16, direct report): the Images tab's "Also used on: ..."
note (an image editor panel's own warning that this description is
shared across multiple slides, editing it here changes it everywhere)
was plain `MUTED_LABEL` gray italics -- easy to miss, and it matters more
than an ordinary muted hint since it changes what a save actually
affects. Switched to `WARNING_LABEL` (the same theme-aware red/orange
`qt_theme.py` already defines and several other tabs already use for an
attention-worthy label -- `qt_deck_editor_tab.py`, `qt_gui.py`,
`qt_slide_preview_popup.py`, `qt_slide_source_tab.py`,
`qt_syntax_check_dialog.py`), not a one-off hardcoded color.

v3.19.2 (2026-09-16, direct instruction): a new "Save, then translate"
button sits next to "Translate now" (an image editor panel's own German
section header, below the English fields). Calls the exact same
TranscriptTab-owned callback (`self._on_save_and_translate`, ->
`_request_save_and_translate()` -> a whole-slide Save draft, then an
auto-translate pickup once the reload rebuilds this editor fresh --
unchanged, already existed) that `_on_translate()`'s own unsaved-changes
dialog's "Save, then translate" option already called -- this is a
direct one-click shortcut to that exact path, not a new one, for the
common case of "I just edited the English text and want both steps done
without an extra dialog in between."

v3.20.0 (2026-09-17, direct instruction): renamed the app from
"SlideManager" to "SlideMage" -- the exe/spec/batch/build-script names,
the `slidemanager/` package directory itself (now `slidemage/`, a pure
`git mv` since its own modules only ever used relative imports), every
window/menu/dialog string, the splash image's wordmark (regenerated), the
two desktop `.lnk` shortcuts (recreated rather than just renamed, since a
shortcut's target path is baked in as binary data), and the internal
temp/wrapper-file naming this app's own compiler/preview code uses
(`_slidemanager_*.tex` -> `_slidemage_*.tex`, kept in lockstep with
`qt_gui.py`'s own matching "Remove temp files" glob so it doesn't stop
finding its own temp files). Old Tkinter `gui.py` deliberately left alone
(frozen fallback, untouched since the PySide6 migration itself -- see
PYSIDE6_MIGRATION.md). Also dropped the "(git unavailable)" suffix
`_compute_version_string()` used to append when `git` isn't resolvable --
it now just falls back to bare VERSION_NUMBER with no parenthetical at all.

v3.20.1 (2026-09-17, direct instruction): renamed the Active decks
table's own "Edit" button (`qt_deck_table.py`) to "Source" -- it always
opened the deck's raw .tex source directly (`_on_edit_deck` ->
`open_deck_source_editor`), the same `SlideSourceTab` the deck slide-list
editor's own "Source" button already opens, so "Edit" was a second,
inconsistent name for the exact same destination.

v3.21.0 (2026-09-17, direct instruction): relocated whole-deck transcript
generation out of the Images tab -- a new "Transcript" button on the
deck-editor tab (next to "Source") and a new "Create Transcript" button
on the main deck table (next to "Stop compilation", which also asks
which deck) both prompt for version and call the same
`generate_deck_transcript()`. The Images tab's own deck/version picker is
gone; its "Generate transcript" now previews just the currently-selected
slide instead (`transcript.generate_single_slide()`, already used by the
slide-source editor's own "Render transcript" button -- nothing is ever
written to disk, it opens in a preview tab, same as that existing
button). Also: `\deckoutputfolder` no longer honors a commented-out
declaration (`OUTPUT_FOLDER_RE.finditer()` had no notion of "%" at all --
direct report), gained a `[transcript]` scope (independent of the PDF-output
scopes) for the transcript writer's own output location, and -- for both
PDF and transcript output -- a declared path that names a full file
rather than a folder now uses that exact filename instead of the usual
`<deck>-<version>` naming. Also fixed a real, separate bug found while
diagnosing a "367 of 375 slides" report (the gap itself was correct,
ordinary `\conditionalslide` exclusion): `\titleframe`/`\fullbleedframe`
are commands, not environments, so `alt_blocks.py`'s frame-detection
regexes never matched them -- their transcript entries were dumping raw,
unstripped macro-argument text (a bare version number, a raw image path)
as the transcript body, and a fullbleedframe slide's image had zero
description entry at all since `referenced_images()` never saw its path
either. Affected 26 files project-wide.

v3.21.1 (2026-09-17, direct question): `\deckoutputfolder[presenter]{...}`
now actually works -- found immediately after v3.21.0 shipped, when a real
deck used it and nothing distinguished its output from `[instructor]`'s.
A presenter job's own `.version` is already "instructor"
(`qt_deck_table.py`'s `DeckRow.build_jobs()` -- presenter mode always
wants full, unrestricted content), so `compiler.resolve_output_location()`
never had a way to look up a `[presenter]`-scoped folder distinctly; it
now checks that key first for a presenter job, falling back to
`[instructor]` then the bare form exactly as before if not declared.
Without this, two decks pointing `[instructor]`/`[presenter]` at
different full filenames (as v3.21.0's own new full-filename feature
invites) would have silently collided on the instructor PDF's own name.

v3.22.0 (2026-09-18, direct instruction): a "Clear selection" button sits
to the left of "Refresh decks" in both the Active and Archived decks
tables (`qt_deck_table.py`'s shared `DeckTableWidget`) -- unchecks every
version/"After-course, per chapter"/Presenter checkbox across every row
in that table in one click. `DeckRow` gains a small `clear_selection()`
method (iterating `self.vars.values()` plus `chapter_var`/
`presenter_var`, the same checkboxes `selected_versions()`/
`build_jobs()` already read) that the table-level button just calls once
per row.

v3.22.1 (2026-09-18, direct instruction): renamed the package directory
from `slidemage/` to `SlideMage/`, matching the app's own display-name
casing (the app itself, the exe, and the wordmark were already
"SlideMage" since v3.20.0 -- only the on-disk folder still lagged). Pure
`git mv` (two-step, since it's a case-only rename on a case-insensitive
filesystem), same as v3.20.0's own package-directory rename -- its
modules only ever used relative imports, so no self-import broke. Every
place that names the package explicitly was updated in lockstep to avoid
the exact failure a same-day first attempt at this hit: Python's
`FileFinder` matches an import name case-sensitively against its cached
directory listing even on a case-insensitive filesystem, so a stray
lowercase `slidemage` reference (an import, or a `-m slidemage` on the
command line) would silently fail to find the now-uppercase folder.
Updated: `slidemage_entry.py`'s `from slidemage.qt_gui import main`,
`SlideMage.bat`'s `-m slidemage` launch line, `SlideMage.spec`'s
`datas`/`splash`/`icon` paths, `.scripts/add_deck_headers.py`'s import,
and this package's own `app_settings.py`/`translation_prompts.py`
`STORE_PATH` constants (both point at a JSON file living inside the
package folder itself, not the Windows registry -- see those modules'
own docstrings). The internal `_slidemage_*.tex` wrapper-file prefix
(`compiler.py`, `slide_preview.py`, `update_all_previews.py`,
`qt_gui.py`'s own matching cleanup glob) is a separate, self-contained
naming convention, not a Python identifier -- deliberately left alone.

v3.23.0 (2026-09-18, direct instruction): `\\fullbleedframe{}` accepts a
comma-separated list of images (layered on top of each other, one revealed
per overlay step -- see its preamble comment), used to merge the
Fink/Palan/Theissen excursus's build-step screenshots into one slide each.
`alt_blocks.referenced_images()`/`replace_image_reference()` split that
list, so every layer still gets its own alt-text/`used_on` entry and the
Images tab's "Replace image..." still finds each one.

v3.24.0 (2026-09-18, direct instruction): Images tab toolbars regrouped.
Top row: translation (model, "Translate all..."), then drafting (model,
Draft descriptions/all, Tune prompt, Clear draft), then the transcript
preview (version, Generate transcript) -- all three fit on one row at
1920 wide (~1100px of 1920). Second row: Show/Sort/Rescan as one block,
then Find slide and Open slide source, with the slide-count summary at
its right end. "Save draft"/"Save and mark reviewed" moved from a row
below the images to the right of the slide title above them, freeing that
height for the image/description area.

v3.24.1 (2026-09-18, direct instruction): Images tab top row order changed
to drafting, translation, transcript (drafting and translation swapped),
and the images area's bottom edge now lines up with the slide list's (the
right-hand pane no longer has a bottom margin).

v3.25.0 (2026-09-20, direct instruction): support for the new deck macro
\slidestep{id-slug}[versions]{steps} (a \conditionalslide that also restricts
the typeset reveal steps; see README.md, "\slidestep"). Deck editor, "Included
in decks" headers, transcripts, appendix TOC (one thumbnail per slide id) and
slide rename all recognise it; a call that is omitted for a deck version does
not advance the frame counter, unlike \conditionalslide. Previews of a
\slidestep call show it for every deck version, with its steps.

v3.26.0 (2026-09-21, direct instruction): the Active decks table has a new
per-row "Open pdf" button that opens the deck's most recently created PDF
(`compiler.latest_pdf_for_deck()`: newest by modification time among every
version/presenter/appendix/per-chapter output, at both its
\deckoutputfolder destination and the default pdf/ folder; a message says so
if none exists yet). The row buttons are now ordered Open pdf, Source,
Duplicate, Tags, Export PPTX, Archive.

v3.27.0 (2026-09-21, direct instruction): slide ids may no longer look like numbers (all digits, "8e6", "inf"/"nan")
or Windows device names -- slide_ids.illegal_id_reason(), used by mint_slide_id() and mirrored in the R minting
script; new slide_rename.rename_slide_id(old, new) renames a slide id everywhere (files, deck references including
#workdeck.tex, \hyperlink targets, alt-text manifest, id registry). No GUI button yet.

v3.28.0 (2026-09-21, direct instruction): SlideMage now opens wide enough for the whole main screen: the window width is
set on first show to what the widest deck-table row (all its buttons and checkboxes) and the footer row need, limited
to the screen; before, the Active decks table sat behind a horizontal scroll bar at the default 1008px.

v3.28.1 (2026-09-22, direct report): the deck-editor tab's own Preview
popup no longer also opens the compiled PDF in an external viewer after
"Render now" -- the popup's own image already refreshes from the fresh
snapshot that compile leaves behind, so the external open was a redundant
second auto-open. qt_slide_source_tab.py's own separate "Preview" button
is untouched -- a different render_fn, not shared with the deck-editor
tab's.

v3.28.2 (2026-09-22, direct instruction): "Create new slide" (the deck
tab's own "+before"/"+after" -> Add slide dialog) now opens the new
slide's own source editor immediately after adding it, so there is
something to start typing into right away. "Use existing slide" and
"Duplicate existing slide" are unaffected -- both reference/copy content
that already has an author behind it. AddSlideDialog gained a return_to
param (passed through from the deck-editor tab that opened it), same
convention open_slide_editor() already uses everywhere else.

v3.28.3 (2026-09-22, direct instruction): the slide-source editor's
"Insert command" -> itemize/enumerate wrap (LatexPlainTextEdit's own
_LIST_ENVIRONMENTS) no longer leaves an empty body. With nothing
selected, it now pre-seeds "\item ", cursor right after it -- same as
the smart-Enter completion right after a freshly-typed \begin{itemize}
already does -- instead of a blank line with nothing to type into. With
one or more lines selected, each non-blank line becomes its own
"\item <text>" line inside the new block instead of the selection's raw
text landing verbatim between \begin/\end. Any other \begin/\end
environment this dropdown might ever wrap is unaffected.

v3.29.0 (2026-09-22, direct instruction): the project gained a CC BY-SA
4.0 LICENSE file (project root), and the Info window (previously just
the version-history browser) is now a two-tab QTabWidget -- "Version
history" (unchanged) and a new "License" tab, a read-only view of that
LICENSE file read fresh from disk on every open rather than a copy
embedded in this app. Prompted by preparing a trimmed copy of this
project to share with a colleague. qt_version_history_dialog.py's
LICENSE_PATH resolves via deck_scan.PROJECT_ROOT, the same frozen-vs-dev
-safe resolution app_settings.py/translation_prompts.py already use (see
v3.3.13 above for why a plain __file__-relative path breaks inside the
compiled .exe).

v3.29.1 (2026-09-23, direct instruction): the deck-editor tab's dropdowns
(the toolbar's "Quick navigation" chapter combo, and each row's own
variant combo, e.g. slide/slidestep/conditionalslide) no longer react to
the mouse wheel -- "I want the scroll wheel to only scroll through the
deck, everything else is error prone." A new NoScrollComboBox(QComboBox)
subclass ignores wheelEvent unconditionally, so the event propagates to
the deck's own QScrollArea instead of silently changing whichever combo
the cursor happened to be over mid-scroll. Verified with a real
headless-Qt QWheelEvent dispatched via QApplication.sendEvent: the new
combo's currentIndex is untouched and the event is left unaccepted
(confirmed to propagate); a plain QComboBox given the identical event
does change, confirming the test itself is real.

v3.29.2 (2026-09-23, direct instruction): a "Rename slide" button, right
next to "Duplicate slide" on the slide-source editor's own toolbar,
changes a slide's descriptive slug (the human-readable part of its
filename/id) while keeping its 3-character id and language segment
fixed -- opens a dialog pre-filled with the current slug, confirms with
a live count of deck references about to be rewritten (same UX pattern
as the existing "Set language" control), then does the actual rename.
New slide_rename.rename_slide_slug() (+ parse_id_slug()/
compute_new_slug() helpers) is the third id-slug renamer alongside
rename_slide_id() (bare id) and set_slide_language() (language segment)
-- the move+reference-rewrite+header-regen machinery the latter two
always shared is now factored into one _apply_id_slug_rename() all three
build on. First real use: hnr-EN-Deception-in-Experimental-Economics ->
hnr-EN-Deception-in-Experimental-Economics-Stage1 (the user's own "nhr"
was a transposed-letter typo for "hnr", resolved by content search --
only one slide in the whole project matches the topic, with an existing
"-Stage2" sibling the "-Stage1" name is clearly meant to parallel).

v3.29.3 (2026-09-23, direct instruction): an "Add citation" button, on
the slide-source editor's own formatting toolbar (the row right above
the text area, next to "Insert command"), opens a form for adding a new
entry to Slidemaster.bib without hand-writing BibTeX. Pick a type
(article/book/online source/report), fill in its fields -- every one
carries a tooltip and a placeholder example -- and a suggested citation
key appears live from the author/title/year (this file's own "surname +
year" convention), lettered (smith2024, smith2024a, ...) on a collision;
editing the key by hand opts out of further auto-suggestion. Checked
against every existing key before it can be added, so a duplicate ID is
never created; the file is re-sorted afterward, so it stays exactly as
alphabetical as the header comment promises. New bibliography.py
machinery backing it (TYPE_FIELDS, suggest_key(), format_entry(),
add_entry()) is usable standalone of the dialog too. Verified with real
headless-Qt tests (type switching, live key suggestion + its
collision-lettering, manual-edit opt-out, duplicate-key and
missing-required-field submits both correctly rejected, a real
successful add) against a throwaway copy of the .bib file -- the actual
project Slidemaster.bib was confirmed untouched by any of the testing.

v3.29.4 (2026-09-23, direct instruction, added mid-batch): a "Delete
slide" button, right after "Rename slide", permanently removes a
slide's current.tex (and any frozen versions) from disk. Checks whether
any deck still references it first and names them (not just a count) in
the confirmation dialog -- "check whether the slide is used in any decks
and ask whether the user really wants to delete" -- defaulting to No
since this can't be undone from within the app. On confirmation, every
whole \slide-family call line referencing it is also removed from every
deck (including #workdeck.tex), so nothing is left compiling against a
file that no longer exists; its image-manifest used_on/notes entries are
dropped, and deck-inclusion headers + translation cross-references are
regenerated. The bare id itself stays registered in slide_ids.csv (never
reissued), same reasoning rename_slide_id() already documents. New
slide_rename.deck_names_referencing()/delete_slide_id(). Verified
end-to-end (file + frozen-sibling removal, the deck's own reference line
cleanly gone with the rest of the file untouched, a repeat delete
correctly raising) and via a headless-Qt smoke test of the button/dialog
wiring itself, both against throwaway slide/deck files only.

v3.29.5 (2026-09-22, direct instruction): README.md's stale "Tkinter GUI" opening line fixed, and a cross-link to the new public github.com/stpalan/slidemaster repo added. Fixed this file's own opening
line, which still called this app "A Tkinter GUI" -- stale since the
PySide6 migration (v2.10.0). Also added a short pointer to
github.com/stpalan/slidemaster, the companion repo this one now gets
published alongside via git subtree, so a reader landing here from that
repo's own README knows where the other half lives.

v3.30.0 (Jürgen Fleiß's fork, 2026-09-25, direct instruction): a slide's number in the deck
editor's List/Thumbnail view is now an editable field. Typing another
number and pressing Enter moves the slide to that position -- typing 2
into slide 6 makes it the new slide 2 and shifts the old 2-5 down by one;
moving down works the same way in reverse. The moved slide joins the
section of the slide whose number it takes, and only its own line moves
in the deck's .tex (new deck_editor.move_slide_to()). Undoable like the
arrow buttons.

v3.31.0 (Jürgen Fleiß's fork, 2026-09-25, direct instruction): the Info menu is now a
dropdown with "Version history…" and a new "Check for updates…", which
compares VERSION_NUMBER with the latest GitHub release of
stpalan/slidemaster. When a newer release exists, a packaged build
offers to download that platform's release zip, unpacks it over the
running binary (moved aside as "<name>.old", removed on the next start)
and restarts; a source checkout is pointed at git pull instead. A
private repo needs SLIDEMAGE_GITHUB_TOKEN set. New updater.py; release.yml
now refuses a tag that doesn't match VERSION_NUMBER, so the check can
trust the tag.

v3.32.0 (Jürgen Fleiß's fork, 2026-09-25, direct instruction): the GitHub token for "Check
for updates…" can now be entered in Preferences -> General -> Updates
instead of only via SLIDEMAGE_GITHUB_TOKEN (which still takes
precedence). Saved in the per-user config folder (project.config_dir(),
file readable only by the user) rather than app_settings.json, which
lives in the project's synced .slidemage/ folder -- a token shouldn't
travel with a shared project.

v3.32.1 (Jürgen Fleiß's fork, 2026-09-25, direct instruction): "Check for updates…" now reads
releases from JuergenFleiss/slidemage, where they are actually published
-- stpalan/slidemaster has none, so the check could never find one.
From this version on, release tags equal VERSION_NUMBER (release.yml
enforces it); the earlier v0.0.x tags predate that.

v3.32.2 (Jürgen Fleiß's fork, 2026-09-26, bug report: "github responded 403 forbidden"): a
token GitHub refuses (expired, or a fine-grained one without Contents:
Read-only -- it then sees the repo but not its releases) now gets a
message naming that permission instead of a bare "403 Forbidden". The
docs recommend such a fine-grained, read-only token now that releases
live in the user's own repository.

v3.33.0 (Jürgen Fleiß's fork, 2026-09-26, bug report and direct instruction): importing an
.odp deck brings its tables in as editable gothamtables, instead of
LibreOffice's TablePreview .svm picture, which was saved as a ".png"
nobody could read and broke the PDF build ("libpng error: Not a PNG
file"). Other StarView Metafile pictures are skipped for the same reason.
Slide-number/footer/date placeholders and speaker-notes frames are no
longer imported as bullets, and a bullet starting with "<" or "[" is no
longer eaten as a beamer overlay spec. The log gets a "Clear log" button
beside "Copy log", and the deck editor a tri-state "Select all"
checkbox that selects every slide or none, replacing the "Clear
selection" button that only showed up with two or more slides ticked.

v3.33.1 (Jürgen Fleiß's fork, 2026-09-26, bug report: "slidemage does not restart after
update"): restarting the one-file build -- after an update, or when
opening another project -- now sets PYINSTALLER_RESET_ENVIRONMENT, so
the new process no longer reuses this one's _MEI temp folder, which is
deleted when it exits and made the new process die at startup. The
restart runs the old version's code, so the update *to* this version
still needs one manual start.

v3.33.2 (Jürgen Fleiß's fork, 2026-09-26, bug report: "preferences window is extremely
wide"): the long explanations on the Translation prompts, AI prompts and
Ollama models tabs now wrap, so Preferences opens about 680px wide
instead of about 2200px. In the deck editor's List and Thumbnail views,
spare width now goes to the slide-id column instead of opening a wide
gap between each row's checkbox and its editable slide number.

v3.30.0 (2026-09-23, direct instruction): a "Find slide in deck" search box in the deck editor toolbar, left of the Close button. Jumps to a
slide already loaded in the currently open deck -- scoped to that
deck's own slides via a live-updated QCompleter, unlike the main
window's project-wide "Find slide:" box, which opens a fresh editor
tab in a different slide instead of jumping within the current one.
Scrolls the matched row/card to the middle of whichever view (List/
Thumbnail and Grid both, so switching view afterward is already lined
up) rather than flush to the top the way the existing chapter quick-
nav jump does, since a single row's own neighbours are useful context
a chapter heading doesn't need. Same-day follow-up (direct instruction,
reported the scroll alone was hard to spot in a long deck, especially
near the very start/end where there's no surrounding "middle of the
visible rows" cue): the matched widget itself now flashes a yellow
highlight for a couple seconds after the jump. This bump should have
landed in the same commit as each of those two changes per this file's
own standing instruction above -- missed both times, caught only when
asked directly; backfilled here as one entry since neither commit was
released/seen as its own version in between.

v3.31.0 (2026-09-24, direct instruction): the slide-source editor's insert-command dropdown's itemize entry renamed from the literal
"\begin{itemize}...\end{itemize}" to "Bulleted list", and a new
"Bulleted list (ellipses)" entry added right after it -- same
wrap_env mechanic, but each item gets \item[\gothamBulletEllipsis] as
its label instead of a bare \item, preceded by a "%Use \ldots for
in-text ellipses" reminder comment (the hand-written pattern already
used on several slides, e.g. iqe/quy/emv). _wrap_environment() gained
optional item_prefix/leading_comment arguments to share the mechanic
rather than duplicating it.

v3.32.0 (2026-09-24, direct instruction): the two list-flavor entries just added to "Insert command..." in v3.31.0 (Bulleted list/Bulleted
list (ellipses)) moved out into their own dedicated "Insert list..."
combo, left of "Insert command...", alongside a new third option,
"Numbered" (plain \begin{enumerate}, same wrap_env mechanic as
"Regular bullet" -- enumerate needs no special item_prefix/leading_
comment, unlike the ellipsis flavor, since this theme already aligns
plain enumerate numerals correctly on its own). Both combo handlers
now share one _apply_insert_action(label, commands) dispatch method
instead of _on_command_selected duplicating the kind/payload branching
a second time for the new combo.

v3.32.1 (2026-09-24, direct instruction): the smart-Enter \item-continuation in the slide/deck source editor now repeats the current
line's own bracketed label (e.g. "\item[\gothamBulletEllipsis]"),
instead of always falling back to a bare "\item" -- LatexPlainTextEdit
._ITEM_LINE_RE gained an optional `(\[[^\]]*\])?` capture group (kept
the existing `\b` right after "item" so "\itemsep{...}" etc. still
correctly don't match), and _smart_return reuses that captured label
verbatim when inserting the next line. Patch bump: an editor-behavior
fix, not a new UI element.

v3.33.0 (2026-09-25, direct instruction): "Presenter" added as a choice in the slide-source editor's own "Render version" combo, alongside
Instructor/During-course/After-course. Not a fourth deck_version value
-- content-wise a presenter render is always instructor (matches how
SlideMage/compiler.py's own real-deck "Presenter" job already builds
one), so the combo's handlers translate "Presenter" to deck_version=
"instructor" plus a new `presenter` flag threaded through to
slide_preview.render_slide_text_to_pdf(), which emits
\def\gothamPresenterModeOverride{1} (same hook compiler.py's own
wrapper defines) to turn on beamer's dual-screen presenter mechanism.
Excluded from the compile-time PNG snapshot cache, same reasoning as
the existing during-course/after-course exclusion (a presenter PDF's
page count/layout is nothing like a normal compile's). "Render
transcript" treats "Presenter" as plain instructor too -- the flag has
no bearing on a text-only transcript. Verified end-to-end by calling
render_slide_text_to_pdf(presenter=True) directly against a real
slide: a 2x-wide 2-page PDF came back with the slide on the left half
of each page and the presenter-notes panel on the right, as expected.

v3.34.0 (2026-09-25, direct instruction): two Images-tab/slide-editor changes. (1) The Images tab's own "Find slide:" search box didn't
actually clear itself after jumping to a slide via a completer
suggestion -- root cause: QLineEdit.setCompleter() wires its own
internal "fill the line edit with the picked completion" slot to the
completer's `activated` signal, and since that wiring happens *after*
this tab's own connect() call, Qt ran it *after* this handler on every
emission, silently overwriting the `.clear()` that already ran.
Deferred the clear to the next event-loop iteration
(QTimer.singleShot(0, ...)) so it runs strictly after that internal
slot has already fired. (2) The slide-source editor's "Add citation"
button renamed to "Add reference" (it only ever creates a *new*
Slidemaster.bib entry), and a new "Insert citation" button added next
to it (qt_insert_citation_dialog.py) -- search the whole bib live by
author/title/year/key, pick an entry, then pick one of three citation-
style buttons (\fullcite/\textcite/\parencite -- the only three this
project's slides actually use, 285/40/6 uses respectively, zero bare
\cite) to insert that call at the cursor. Verified with a headless
(QT_QPA_PLATFORM=offscreen) smoke test: filtering, selection-enables-
buttons, style-button insertion, double-click-inserts-\fullcite-and-
closes, and both the empty-query (shows everything) and no-match
(buttons stay disabled) edge cases.

v3.34.1 (2026-09-25, direct instruction): "Add reference" button (and its dialog's own window title/submit button) renamed to "Add reference to .bib", to say where the reference goes.

v3.35.0 (2026-09-26, direct instruction): a batch of editor and settings changes. (1) Duplicate-slide dialog: Enter now creates the slide (Create is the dialog's default button, Cancel no longer auto-default). (2) Adding a *duplicate* of an existing slide from a deck tab's "+ before"/"+ after" dialog now opens the new slide in its source editor, exactly like "Create new slide" already did. (3) Slide editor keyboard shortcuts, scoped to the tab like Ctrl+F: Ctrl+I/B/U = the I/B/U toolbar buttons, Ctrl+S = Save, Ctrl+R = Render to PDF (slides only). (4) New "Insert block..." dropdown next to "Insert list..." with the project's beamer blocks (block, example, alert, reference, definition, info, plus the three floating variants); a selection becomes the block body and the cursor lands in the title's braces. (5) Tabs menu: "Edit test-slides.tex" opens decks/test-slides.tex in source mode. (6) "Check syntax" can be aborted with Escape (dialog or editor focused): the Ollama request now runs on a worker thread instead of blocking the GUI thread, and abort() closes the socket so Ollama stops generating -- on Windows only Winsock's closesocket() on the detach()ed handle wakes a blocked recv(); socket.shutdown()/close() do not (measured). (7) Settings gets an "AI models" tab with one default model each for Syntax check, AI drafting, Image descriptions and Translation; every model picker now preselects that default, and picking another one there applies to that dialog/tab only (the old remember-the-last-pick behaviour is gone; the setting keys are unchanged, so existing values carry over). (8) "Add reference to .bib": for a working paper/report the institution is optional and a DOI field was added. Verified with a headless (QT_QPA_PLATFORM=offscreen) smoke test: the four shortcuts, both block-insertion paths, the new Settings tab, and Escape aborting a check against a deliberately slow fake Ollama server (0.05 s from key press to released Ollama slot, from the dialog and from the editor).

v3.36.0 (2026-09-26, direct instruction): (1) Pre-render syntax check (latex_lint.py, qt_render_check.py): every PDF render -- the slide editor's Render to PDF (the buffer), both Preview popups' Render now (the saved slide), Create PDF for any decks/versions/chapters/presenter and Export PPTX (the deck file plus exactly the slide files that job includes in that version, per-chapter jobs only their chapter, plus \input-ed fragments like test-slides.tex) and Update slide previews (every slide any deck uses) -- first runs a static, lexical check and only interrupts on an error (dialog: Cancel [default] / Show in editor / Render anyway); warnings go to the log. 14 checks, listed in README.md ("Pre-render syntax check"): encoding, braces, environments, math-dollar, math-delims, ampersand, hash, citation (key not in Slidemaster.bib), image (file missing), slide-file (deck call to a missing slide file) as errors, and underscore, percent, overlay, optional-arg as warnings. Tuned over all 930 slide/deck files until quiet on everything that compiles (its one finding is a real leaked group: an unclosed `{` on line 39 of slides/zgz-EN-EBIT-Definition-current.tex); cost measured at about 0.1 ms per slide file -- a 395-slide deck ~300 ms cold, ~65 ms warm. (2) \slidestep in the variant dropdown of deck-editor rows and the Add slide dialog, with a "steps" field (validated: numbers, commas, ranges such as 2- or 1-2,4); switching a plain \slide to \slidestep/\conditionalslide now starts with all three versions ticked. Verified headlessly: 28 synthetic good/bad snippets for the lint checks, the row/dialog behaviour, and slide->slidestep edits on a temp deck.

v3.36.1 (2026-09-26, direct question): the pre-render check gained a 15th check, "caret" (warning): a ^ in running text outside math ("10^6" typed without $...$ gives "Missing $ inserted"). Quiet on all 930 slide/deck files.

v3.37.0 (2026-09-27, direct instruction): "Insert citation" dialog gets a fourth button, "bib id", that inserts only the bare citation key (no \fullcite{}/\textcite{}/\parencite{} around it).

v3.38.0 (2026-09-27, direct instruction): compile progress bar (compile_progress.py) -- a 3 px line in the "Create PDF" blue (#0066cc) right at the top edge of the log window, for Create PDF (queues of decks/versions/chapters/presenter), Export PPTX, Update previews and single-slide renders. Pass K comes from latexmk's "Run number K of rule 'lualatex'", the position inside a pass from the "(.../slides/<id>-" lines LaTeX prints when it starts a slide file: fraction = ((pass-1) + slides_seen/slides_total)/passes, 4 passes for a deck that uses biblatex, 3 without (single renders 3; Update previews' megadeck 4), held at 99% until the job really finishes, so an extra pass never overshoots. Slide totals reuse the syntax check's scoping (version/chapter filters, \input fragments); a queue is weighted by passes x slides; unknown-size jobs show the busy animation; Stop clears it. The status label now reads "pass 2/4, slide 137/395". Verified by replaying a real latexmk run (4 passes: 12.5% steps per slide, 99% at the last slide, 100% on MOVING), the two IA2 job specs (396/389 slides, 4 passes), single/second/unknown-size renders and Stop in a headless window; the slide-open pattern checked against a real IA2 TeX log (no wrapped paths).

v3.38.1 (2026-09-27, direct instruction): the deck editor's toolbar gets an "Add slide" button, shown only while the deck has no \\slide{}-family calls of its own (e.g. #workdeck-mini right after being cleared out) -- an empty deck has no row to hang a "+ before"/"+ after" button off of, so there was previously no way to add its first slide from this tab. Same dialog/flow as those two buttons; deck_editor.empty_deck_insert_point() finds the insert point (right before \\end{document}, one tab of indent) in place of a real call's own line_start/line_end/indent. Verified headlessly: the button's visibility toggles correctly for an empty vs. a real deck, a click hands the dialog the right insert point, and a malformed deck (no \\end{document}) shows an error dialog instead of crashing.

v3.39.0 (2026-09-27, direct instructions): (1) Settings -> AI models gets a "Translation prompts…" button next to the Translation model row, opening the per-(model, source, target) prompt editor (qt_translation_prompts_dialog.py, split out of qt_settings_dialog.py) in its own dialog; the "Translation prompts" tab is gone. (2) The slide editor's Enter-completion no longer auto-inserts \end{standardframe} right after a line reading \begin{standardframe}{...} (any title) -- standardframe's own body is a whole slide's worth of content, not a short list, so the auto-close just got in the way; Enter there now falls through to a plain newline at the same indent, same as any other non-completing line. Every other \begin{ENV} (itemize, figureframe, ...) still auto-closes as before. (3) Fixed two real bugs in "Housekeeping -> Archive unused slides and media files" found from a direct report (a batch run archived 8gc/ZZH/egk -- all three real, in-use slides -- plus media/alt-text.json/.csv, the accessibility image-description store): unused_content.py's slide-usage scan never recognized \slidestep{} (added to the project 2026-09-20 but never added to that scan's own macro list), so a slide referenced only via \slidestep looked completely unreferenced; and alt-text.json/.csv are read directly by Slidemaster_alt.lua, never \includegraphics{}-ed, so the media scan always treated them as unused -- both are now excluded/recognized explicitly (MEDIA_NEVER_UNUSED, \slidestep{} added to SLIDE_CURRENT_RE). All 103 files that batch run archived were restored by hand (git status confirmed clean; the false positives were exactly 8gc/ZZH/egk plus alt-text.json/.csv, everything else in that batch was genuinely unused). (4) "Archive unused slides and media files" now scans first and shows every file it would move in a new confirmation dialog (ArchiveUnusedDialog) -- Cancel (the default) or "Archive N file(s)" -- instead of moving on a bare Yes/No, so a result like the one above can be caught before anything moves. Verified headlessly: standardframe/itemize/figureframe Enter behavior, the Settings dialog's tab list and button wiring (with TranslationPromptsDialog itself built standalone), the archive dialog's row count and default button, the real repo re-scanned clean (8gc/ZZH/egk now correctly seen as used, alt-text.json/.csv excluded), and the Cancel/Accept paths of the new confirmation flow.

v3.40.0 (2026-09-27, direct instructions): (1) Settings -> AI models and the former separate "Ollama models" tab are now one tab, the Ollama section underneath a QFrame horizontal rule + "Ollama models" heading -- same content and behavior as before, just no longer a second tab (_build_ollama_models_tab -> _build_ollama_models_section(layout), sharing the AI models page's own QVBoxLayout). (2) slide_ids.BANNED_WORDS (mirrored in .scripts/R_Slidemaster/R/slide.new.id.R's own denylist) rejects real English words that read badly as a slide id -- seeded with "pee" after it turned up as a real slide's id; the existing slide was renamed (pee-EN-Where-to-Aim -> x6t-EN-Where-to-Aim via slide_rename.rename_slide_id(), which updates every deck reference, slide_ids.csv, and the image manifest). (3) Merged Jürgen Fleiß's "delete slide" fix from the public SlideMage repo (commit e879c13, 2026-09-23) into slide_rename.py's own _line_removal_pattern(): the previous pattern assumed every macro's own argument list ends at \{id_slug\}, true for \slide/\slidefinal/\omitslide/\conditionalslide[versions]{id_slug} but not for \slideversion{}/\omitslideversion{}'s own trailing {version} or \slidestep{id_slug}[versions]{steps}'s own [versions]{steps} tail -- so "Delete slide" on a slide referenced only that way silently left the dangling reference (and, for \slideversion{}, the frozen version file) behind with no error; separately, the previous pattern's bare \n (vs \r?\n) left a stray \r on every CRLF deck file regardless of macro. Verified with 9 cases covering all seven macros plus CRLF-cleanliness and a same-line no-false-match check.

v3.41.0 (2026-09-28, direct instructions): (1) "Create PDF" and "Export PPTX" now refuse a job that would typeset zero slides instead of running a real latexmk compile for a PDF with nothing on it -- compile_progress.count_job_slides() (built for the progress bar's own sizing) decides this, so \\conditionalslide/\\slidestep version filtering and \\input{}-ed fragments like test-slides.tex are already accounted for; an all-empty batch is refused outright, a mixed batch compiles the rest and lists what got skipped. (2) Merged all ten of Jürgen Fleiß's "Fix ten review findings" from the public SlideMage repo (commit 34cdbd7, 2026-09-28) after independently verifying each against this codebase: (a) compiler.py's wrapper-file write now opens with newline="" -- writing an already-CRLF deck's preamble/chapter text (the per-chapter and appendix branches splice it in raw) through write_text()'s universal-newlines default doubled every \\r\\n it contained into \\r\\r\\n; (b) run_job()/_relocate_pdf_and_finish() gained an on_relocated(success, dest_pdf) callback, fired once the PDF's backgrounded move into place has truly finished (or given up) -- _export_pptx_bg now waits on it and reads the pptx source from its real final destination instead of racing that move's own .build/ aux-file cleanup, which used to delete the file _export_pptx_bg was about to read; (c) run_jobs() gained _disambiguated_destinations(), which renames a same-batch collision (two+ jobs whose own \\deckoutputfolder resolves to the exact same file -- concretely reachable for a deck that names an exact file and is then compiled as several per-chapter jobs, e.g. IA2) so they no longer silently overwrite one another; (d) reload_decks() now calls the new _remap_job_status_rows(), re-pointing self._job_status_map at the freshly rebuilt DeckRow widgets by deck name -- without it, "Refresh decks" mid-compile kept updating discarded row widgets, so that job's own running/moving/pass/fail badge silently stopped appearing on screen; (e) deck_scan.py gained is_commented(text, pos) (an unescaped "%" anywhere on the position's own line before it, not just at the line's very start) and now uses it to exclude a commented-out \\section{} from a deck's chapter list; (f) deck_editor.is_commented_out(deck_text, call) applies the same check to a \\slide{}-family call, and appendix_toc.py's _sections() now skips a commented-out call rather than still listing it in the generated appendix; (g)-(h) slide_source.py gained StaleFileError and an expected_text parameter on save_slide_source() (same stale-check-then-write shape as deck_editor.py's own _apply()), and qt_slide_source_tab.py's _on_save() now passes its own previous_text and shows an error dialog on a mismatch, instead of silently overwriting a slide file someone else changed on disk since it was loaded; (i) alt_draft.TranslationResult gained source_hash, captured by OllamaTranslationBackend.translate() from the exact entry snapshot it translated; apply_one_translation() now refuses to apply a result whose source_hash no longer matches the store's current English-text hash (the EN text moved on while the translation was in flight) instead of always overwriting; (j) qt_transcript_tab.py's three background-thread self.app.log() calls (a translation's "editor panel was already gone" message, and the draft-all/translate-all batch progress callbacks) now go through self.app.signals.log.emit() instead, since self.app.log() is main-thread-only and these all run on a worker thread. Verified headlessly: the empty-deck guard (all-empty batch refused, mixed batch compiles the rest, Export PPTX refused) and, for the ten findings, comment-aware chapter/slide-call parsing (including an escaped "\\%" correctly NOT counting as a comment) with appendix filtering, the translation staleness guard against a real (temp) store, StaleFileError on a genuinely stale save and not on a fresh one, the CRLF wrapper fix at both the string and on-disk-bytes level, _disambiguated_destinations on a real collision and a solo job's untouched path, on_relocated firing exactly once on both the success and the cancelled-mid-relocation paths, and _remap_job_status_rows repointing a live compile's status updates at the post-refresh row (and dropping one whose deck vanished).

v3.41.1 (2026-09-28, direct instructions): slide_ids.BANNED_WORDS grows from just "pee" to 16 entries -- sex, wtf, ass, cum, tit, fag, cnt, kkk, fap, ffs, poo, hos, gun, gay, rip added, none colliding with any existing slide id so no rename was needed. Mirrored in .scripts/R_Slidemaster/R/slide.new.id.R's own denylist.

v4.0.0 (2026-09-28, direct instructions): SlideMage becomes a stand-alone, installable app in its own repository, stpalan/SlideMage, the authoritative one -- no longer a folder inside the SlideMaster project. The repository takes over the structure of Jürgen Fleiß's fork (JuergenFleiss/slidemage), merged with that fork's full history: the app as a Python package in src/slidemage (pyproject.toml; pip install -e . gives a slidemage command), the LaTeX framework in latex/ (Gotham theme, Slidemaster_preamble_base.tex, Slidemaster_alt.lua), a self-contained demo project in example/ (also the template for a new project), docs/, tests/, and GitHub Actions that build the Windows and Linux executables for every version tag (release.yml; the tag must equal VERSION_NUMBER). A project is any folder with a slide_ids.csv, chosen by --project, $SLIDEMASTER_PROJECT, an upward search, or the last project opened; per-project settings live in <project>/.slidemage/. From the fork: Open/create project, ODP/PPTX import, course schedule and course links, section editing and slide moving in the deck editor, editable slide numbers, Info -> Check for updates (now reading stpalan/SlideMage's releases; the GitHub token goes in Settings -> General -> Updates), editable AI prompts (Settings -> AI prompts), the Ollama host setting, Copy/Clear log. Kept from this line where both changed the same thing: the per-task default AI models (the fork's single 'Other AI tasks' default is dropped; its live refresh of open model pickers is kept and now follows the per-task defaults), the Settings dialog layout with translation prompts in their own dialog, the deck editor's Find-slide box and Add-slide button (the fork's inline 'Add first slide' button is dropped as a duplicate). Also: the splash screen is back for the Windows executable (the fork had dropped it); the version string's commit time now comes from the app's own checkout rather than the project's; the Settings and Translation prompts dialogs no longer open extra wide; the demo project's .latexmkrc files now work under MiKTeX with Git for Windows' Perl (it reports itself as 'cygwin' with /d/... paths, which left TEXINPUTS unusable); latex/ and example/ carry SlideMaster's framework and demo changes up to 2026-09-28. Version numbers v3.30.0 to v3.33.2 exist twice -- this repository's and the fork's (labelled "Jürgen Fleiß's fork" above) are different changes; both lines are merged here.

v4.1.0 (2026-09-28, direct instructions): (1) Settings -> AI prompts has three pages, Image descriptions, Slide rewrite and Translation; the translation prompts (default prompt and per-model overrides) moved there from the dialog behind the AI models tab's "Translation prompts…" button, which is gone (qt_translation_prompts_panel.py replaces qt_translation_prompts_dialog.py; unsaved text on the Translation page is asked about when Settings closes, like the other prompts). (2) Update behaviour: Settings -> General -> Updates chooses "Don't check for updates", "Check for updates and ask before installing" (default) or "Check for updates and install them automatically", stored per user and machine next to the GitHub token (updater.get_update_mode()). The packaged app checks three seconds after it starts, on a background thread; a failed check or an up-to-date copy only goes to the log. In "ask" mode a newer release offers Install now / Not now / Always install automatically / Stop checking for updates; "auto" installs and still asks before restarting. (3) Breaking releases: a release whose notes have a paragraph starting "BREAKING:" (or a "## Breaking changes" section), or whose major number is higher, is always asked about, even in automatic mode -- the dialog shows those paragraphs and offers Install anyway / Stay on vN.x (the newest release before the first breaking one) / Not now; every release between the running one and the newest counts (updater.plan_update(), using the release list instead of only the latest release). Convention, documented at the top of this docstring and in the README: a breaking release raises the major number and its history entry here gets a BREAKING: paragraph; the release workflow publishes the entry as the release notes (packaging/release_notes.py) and fails a major bump without that paragraph. (4) Project format guard: opening a project writes .slidemage/project.json ({"format": 1, "last_app_version": ...}, meant to be committed); a project whose format is newer than the app's gets a warning before it opens (Open anyway / Quit) and its file is left alone. (5) Import sessions follows the deck's \\decklanguage: an English deck gets "Course sessions" with Date/Time/Location/Session, its German group names, session types and (fully known) remarks translated from a fixed word list (course_schedule.translate_schedule()), and the slide is named <id>-EN-Course-Sessions. (6) Transcripts omit colour: \\textcolor, \\color, \\colorbox, \\fcolorbox, \\cellcolor, \\rowcolor and \\columncolor keep only their text -- before, the colour name was glued to it ("c_primary_highlightdata dredging"). Checked on all 14 SlideMaster decks: 427 colour specs removed, no other change. Not a breaking release: settings, prompts, projects and decks all keep working as before.

v5.0.0 (2026-09-30, direct instructions): systematic replacements for per-slide layout fixes, plus Jürgen Fleiß's Admin slides. (1) Admin slides (Jürgen Fleiß): the deck editor's "Import sessions…" is now "Admin slides…" -- a course-sessions table and/or a title slide (course title, chosen lecturers, semester) from the deck's linked Uni Graz course, read from UGO's public REST/JSON endpoints instead of the old HTML page (docs/UGO_api.md); follows \\decklanguage. The generated sessions table is now a gothamtable (the project's table style) with the same column geometry. (2) LaTeX framework (latex/): automatic Top Margin -- every top-aligned standardframe measures where its first content landed (at shipout, new latex/Slidemaster_layout.lua) and moves its body onto the Top Margin line on the next compile via <jobname>.top (latexmk reruns); never pushes a full slide into its footnotes/footer; exceptions [c] frames, sectionframe, \\progressstrip, \\gothamManualTopMargin, \\gothamAutoTopMarginfalse. New: \\cornerfigure, besidefigure, \\fitfigure, \\gothamContentBottomAlign (Bottom Margin), \\gothamFloatingInfoblockTopAlign, gothamtable[gap=...] (flush edges; a real separator after p/m/b columns; dark rules inside blocks automatically), [top=, bottom=] padding for the gothamfloating*block environments, \\deckitem<spec>, \\deckreveal*/\\deckrevealfinal* (space-preserving), TikZ visible on=<spec>, \\shrinklists, \\EUR, \\gothamTikzmark, TikZ styles gotham highlight/gotham dotted highlight/gotham arrow. The columns-first and columns[T] corrections (2026-09-21, Jürgen Fleiß 2026-09-30) now only act in frames the automatic Top Margin doesn't manage. (3) Pre-render check: new warnings table-edges (a gothamtable whose rules run past its text) and heading-text (a frame opening with a bold line above its list). (4) Transcripts: \\ifgothamInstructorVersion/...DuringCourse.../...AfterCourse... resolve per version (a slide that wrote an item once per branch used to list it twice); \\deckitem, \\deckreveal[*]/\\deckrevealfinal[*] no longer leave "[2]"/"<2->" behind; gothamtable's [gap=...] and the floating blocks' options and width argument are skipped (a floating block's title was its width before); "\\ " is a space. (5) ODP/PPTX import writes gothamtable[gap=12pt].

BREAKING: the automatic Top Margin changes where the first content of existing slides lands -- a slide whose first line was not on the Top Margin line moves onto it (e.g. slides starting with a plain paragraph move down ~3pt, a table's top rule down to the margin). Decks that must keep their old positions add \\gothamAutoTopMarginfalse to their preamble (or \\gothamManualTopMargin before a single frame). The first compile of a deck needs the usual latexmk rerun to apply it.

v5.1.0 (2026-10-01, direct instructions): (1) LaTeX framework: list item gaps now shrink with the font. A level-1 itemize/enumerate set at \\small or \\footnotesize used to pick up LaTeX's size-specific \\parsep (3pt plus 2pt, copied into \\parskip), so its items sat ~3pt further apart than at normal size and \\shrinklists{1} often gained nothing; the new \\gothamNoListParsep removes that extra space in every list. (2) Slide editor: a "Previous versions..." dropdown in the toolbar of a current slide lists its frozen versions (newest first) and opens the chosen one in its own tab; a frozen version opens read-only (Preview and Render to PDF show that version) until "Unlock editing" is clicked. (3) Insert command offers \\shrinklists{1} (change the 1 to 2 for the stronger step).

BREAKING: every slide with a level-1 list at \\small/\\footnotesize (a manual size switch, \\shrinklists, or a smaller block font) now has tighter item gaps than before -- typically ~3pt less per item. Slides tuned by hand around the old gaps (\\vspace, \\itemsep, a smaller font chosen only to make room) may now have unused space at the bottom and can be simplified; no slide gets taller.

v5.2.0 (2026-10-01, direct instructions): LaTeX framework. (1) \\gothamTikzword{name}{text}: a word as a named TikZ node, so an overlay arrow can point at the word and follows it when the layout moves (3ac's arrow at measured page coordinates had drifted off its words). (2) \\sectionfigure[keys]{image} for sectionframe: the image fills the gap from the title bar to the footer, flush with the right edge, and the frame's footnotes -- the image source included -- go into the rotated strip beside it (bij's image overlapped the title bar and covered its own source line; neb, u97, tyn and vtm did the same by hand with per-title measurements). The bar's bottom edge is computed from the title's depth (89.44bp minus it, at most 85.04bp, measured). (3) Footnotes inside a minipage or column now join the frame's other footnotes at the bottom (beamer's [frame] footnotes are the default; mje, zv4). (4) Transcripts: \\gothamTikzmark{name} no longer leaves its name behind as a word, \\gothamTikzword keeps its text.

BREAKING: a \\footnote{} or \\source{} inside a minipage/column used to be set right below that minipage with its own marker sequence; it now sits with the frame's other footnotes at the bottom and continues their markers (in this project: mje, zv4).

v5.3.0 (2026-10-01, direct instructions): (1) Every \\gotham... name this project created is now \\SM... (\\SMContentTopAlign, \\ifSMInstructorVersion, \\SMBulletEllipsis, the TikZ style SMImageBorder, ...): framework, institution preambles, Lua, SlideMage's own code, the demo project and every slide including frozen versions. The vendored Gotham theme keeps its names (\\gothamset, \\gothamFrametitleLeftpading, ...), and so do the environments (gothamtable, gothamfloatinginfoblock, ...). New module slidemage.sm_rename does the rename; `python -m slidemage.sm_rename <project folder>` applies it to another project. (2) \\cornerfigure[height=5cm, border]{media/x.png}: with width= or height= the argument is an image file, the other size follows from its aspect ratio; `border` adds the yellow image border; corner=e|w puts it on the Right/Left Margin, centred between Top and Bottom Margin. besidefigure takes the same keys and measures the figure itself (no width argument). (3) A bordered node (SMImageBorder) has its anchors on the border's outer edge, so the border -- not the stroke's centre line -- lands on a margin; \\cornerfigure's node has no inner/outer sep, so an unbordered image's own edge does. (4) Transcripts: \\setbeamertemplate/\\setbeamerfont/\\setbeamercolor no longer leave their names behind, \\item[label] keeps its label, \\ldots is an ellipsis.

BREAKING: (a) the \\gotham... -> \\SM... rename: a project or deck that uses this framework's own commands under their old names stops compiling -- run `python -m slidemage.sm_rename <project folder>` once (it rewrites slides, decks, preambles and .slidemage settings; the Gotham theme's own names are left alone). Old .top/.ovl files in a build folder are still read without errors. (b) \\cornerfigure content without a border sits 0.2pt closer to its corner (its node has no outer sep any more); a bordered node keeps TikZ's outer sep of half its line width even where \\cornerfigure sets outer sep=0pt, so its border's outer edge is on the margin. A slide that writes outer sep=0pt after SMImageBorder still opts out (needed where the node's corners are a coordinate frame for highlights). (c) besidefigure's arguments changed from {width}{figure} to [keys]{image file or content}.

v5.4.0 (2026-10-01, direct instruction): \\SMLineTop -- a zero-width strut as tall as a text line's line box (0.935em, the box the Top Margin is measured on). At the start of the first line of a text column beside a figure in top-aligned minipages ([t] plus \\vspace{0pt}) it makes the text and the figure start on the same line, so the automatic Top Margin puts both on it (m2k: its minipages were vertically centred, LaTeX's default, and the text started 12pt below the Top Margin).

v5.4.1 (2026-10-03, direct instruction): a compile run with several jobs now goes version by version, then deck by deck (compiler.order_jobs()): Presenter, Instructor, During-course, After-course, After-course per chapter; within each version the deck table's groups in order -- work decks, course decks, research presentations, test decks -- and decks of one group in table order. Selecting During-course and Presenter for #workdeck and IA2 compiles #workdeck Presenter, IA2 Presenter, #workdeck During-course, IA2 During-course. Before, it went deck by deck (all of one deck's versions, then the next deck).

v5.4.2 (2026-10-03, direct instruction): main window stays left-aligned. In a window wider than the deck table needs, the extra width goes to the right: the version checkboxes (Instructor ... Presenter) keep their place instead of being spread over the window, the Create PDF / Stop / Create Transcript / ? / Clear selection / Refresh decks buttons sit next to each other on the left, and so do the three checkboxes under the tabs (footer timestamp, appendix TOC, auto-open) -- less mouse travel.

v5.4.3 (2026-10-03, direct instruction): "Clear selection" on the main screen also clears the pass/fail marks of earlier compiles (✓, ✗, →) next to the checkboxes, in every row of that table. A job that is still running keeps its animated dots until it ends.

v5.5.0 (2026-10-03, direct instruction): "Generate appendix TOC" now also works for the student versions: every whole-deck compile -- Presenter, Instructor, During-course and After-course -- gets the generated appendix (agenda plus thumbnail grids) and the `-appendix` file-name suffix; each lists the slides its own version shows (\\conditionalslide/\\slidestep conditions), and the logo on every slide links to its agenda. Per-chapter compiles stay without one. The appendix is appended after the deck's last slide, so it already follows a deck's own appendix slides (a \\section{Appendix}) -- verified on #workdeck, where the deck's appendix slide comes first and the generated agenda and grids after it. Before, During-course/After-course compiles ignored the checkbox.

v5.5.1 (2026-10-03, direct instruction): the "-appendix" ending of PDF names is gone: a compile with "Generate appendix TOC" ticked writes the same file as one without (<deck>-instructor.pdf, <deck>-during-course.pdf, ... and -presenter), replacing it. PDFs named *-appendix.pdf left in pdf/ by earlier versions are no longer touched or offered by "Open pdf"; delete them by hand.

v5.5.2 (2026-10-03, direct instruction): "Clear selection" while a compile is running clears only the checkboxes -- the animated dots and the pass/fail marks of the run stay. A click after the run has finished clears the marks too (v5.4.3 cleared them at once, running jobs excepted).

v5.5.3 (2026-10-03, direct instruction): the status line by "Log:" counts compiles, not decks: ten deck versions of four decks read "Deck 1/10" ... "Deck 10/10" (each version is a compile of its own), not "Deck 2/4".

v5.6.0 (2026-10-03, direct instruction): \\SMCashCycleBars and \\SMCircularFlowDiagram are no longer part of the framework. They draw two specific finance-course diagrams (an operating/cash conversion cycle bar chart, a cash -> raw materials -> finished goods -> receivables circle), which is course content, not a framework feature; they now live in the content project that uses them (SlideMaster_SP's Slidemaster_project_macros.tex, loaded by its institution preambles). Its five slides render pixel-identically.

BREAKING: a project whose slides use \\SMCashCycleBars or \\SMCircularFlowDiagram stops compiling ("Undefined control sequence") until it defines them itself -- copy both \\newcommand blocks from SlideMage v5.5.3's latex/Slidemaster_preamble_base.tex into a file of the project and \\input it from each institution preamble after \\input{Slidemaster_preamble_base}.

v5.7.0 (2026-10-03, direct instruction): a generic SlideMage template, example/Slidemaster_preamble_slidemage.tex, for decks that don't belong to an institution -- the SlideMage logo (the app icon as a vector PDF, example/schemes/scheme_slidemage/), title and footer boxes in the splash screen's dark gray #1e1e1e with white text, the app's button blue #0066cc as highlight colour instead of Uni Graz yellow, and the app's other colours as the c_* palette (block titles, info blocks, link underlines, ...; every colour pair the framework combines checked against WCAG 2.1). It ships with the app as part of the example project new projects are created from; a deck selects it with \\input{Slidemaster_preamble_slidemage}. SlideMage recognises it like the institution templates: previews are stored under the template name "SlideMage", and Update previews builds them with this template.

v5.8.0 (2026-10-03, direct instruction): a default template for slides rendered outside a deck -- Settings -> General -> Slide rendering -> "Default template", listing the templates whose Slidemaster_preamble_<name>.tex the project has, saved immediately in .slidemage/app_settings.json ("default_template"). The slide editor's "Render to PDF" and "Preview" (including its cached preview image), and tikz illustration renders use it; before, they always used the Uni Graz template. Out of the box it is the SlideMage template; a project that doesn't have the chosen template falls back to SlideMage, then Graz, then whichever template it has (so SlideMaster_SP, which has no SlideMage template, keeps rendering in Graz). Renders from a deck editor row keep using that deck's own template. (slide_snapshot.render_template(), slide_preview.default_preamble()/template_preamble().)

v5.9.0 (2026-10-03, direct instruction): the SlideMage template is part of the framework now, not of the example project: latex/Slidemaster_preamble_slidemage.tex with its logo latex/slidemage-logo.pdf (+ .svg source), found on the same TeX search path as Slidemaster_preamble_base.tex. Every project next to the framework can use it without a copy of its own -- e.g. SlideMaster_SP, which has only institution layers, can now select it in a deck (\\input{Slidemaster_preamble_slidemage}) and in Settings -> General -> Slide rendering, which lists the project's own templates plus the framework's (slide_snapshot.framework_dirs(): $SLIDEMASTER_LATEX, ../latex, ../SlideMage/latex). A project's own Slidemaster_preamble_slidemage.tex would still win. Since the SlideMage template is now available everywhere, single-slide renders use it out of the box in every project, unless another default template is chosen there.

v5.10.0 (2026-10-04, direct instruction): regular slide ids start with a letter. Every newly minted id (Add slide, Duplicate slide, Admin slides, PPTX/ODP import) now has a letter first (slide_ids.ID_FIRST_ALPHABET); ids starting with a digit are reserved for the SlideMage manual (1 + letter + one more character) and the demo slides (2 + letter + one more character), minted with slide_ids.mint_slide_id(reserved="1"/"2") and checked by slide_ids.reserved_id_reason(); slide_ids.regular_id_reason() is illegal_id_reason() plus the letter-first rule. Minting and slide_rename.rename_slide_id() now compare ids without regard to case (Windows can't tell "zzh-..." from "ZZH-..." apart). rename_slide_id() refuses a digit-first new id unless reserved=True, and also renames the slide's cached previews (.previews/slide_previews/<old>-*.png), so they need no re-render. Existing digit-first ids keep working everywhere; they are just no longer handed out (SlideMaster_SP's 217 were renamed with rename_slide_id()).

v5.11.0 (2026-10-04, SlideMage manual, build step 1): \\SMCodeFile[listings keys]{path} shows LaTeX source on a slide, read from a small file at the project root (snippets/<slide id>-<n>.tex), so the slide needs no [fragile] frame. Framework (Slidemaster_preamble_base.tex): listings loaded; style SMCode -- Fira Mono Regular (\\SMCodeFont; the theme's \\ttfamily is Fira Mono Bold) at \\SMCodeSize (6.6/8.2pt), every control sequence backslash included in c_primary_highlight (backslash as letter + keyword prefix), comments c_primary_gray, c_tertiary_gray panel; \\% and \\\\ mapped so neither starts a comment nor colours the next word; umlauts, dashes, middle dot, ellipsis and arrow mapped. Keys go to \\lstinputlisting (firstline/lastline/basicstyle...). Transcript: the file becomes a fenced ```latex block (firstline/lastline honoured, tabs as two spaces), and the HTML transcript renders fenced blocks as <pre><code>. Pre-render check: new error "code-file" for a missing file; \\SMCodeFile's path is a non-typeset argument for the underscore check. Reserved ids (manual/demo) never have "e" in second place.

v5.12.0 (2026-10-04, SlideMage manual, build step 1b): visible navigation for readers, opt-in per deck. Framework: \\SMNavigationBar[deck,chapter,previews] (deck preamble) extends the footer's left text to "\\FooterText | Navigation: <three links>" -- the \\SMDeckAgenda contents slide, the current chapter's \\SMChapterAgenda (fallback: the contents slide), and the generated appendix agenda (only when the compile has it) -- white/footer-coloured text with the blue \\href underline (\\SMLinkUnderline); a link without a target in this PDF is left out. \\SMChapterAgenda[width] lists the slides of the current \\section in two columns as links, from what the previous pass recorded in the .aux: \\setSlideID writes \\SMAgendaSlide{section}{id}{slug label}, the frametitle hook writes the frame title (\\SMAgendaEntryTitle), \\SMAgendaTitle{text} names a title-less slide; \\small, \\footnotesize when it does not fit \\SMChapterAgendaMaxHeight; a \\slidestep slide once, the agenda's own slide not at all. \\deckappendixtoc is inert for LaTeX. Every deck now writes those agenda lines to its .aux (no visible change; demo decks pixel-compared against v5.10.0: identical apart from sub-0.01pt bullet rounding on one slide that already came with v5.11.0). App: deck_scan reads \\deckappendixtoc (Deck.appendix_toc) and the compile batch generates the appendix for such a deck whatever the toolbar checkbox says. Transcript: DeckSlide.chapter (number of \\section{}s before it); \\SMChapterAgenda becomes "This chapter's slides:" with each slide's title and number (German strings for German decks), \\SMDeckAgenda disappears, \\SMAgendaTitle names a title-less slide. alt_blocks._slide_title()'s filename fallback drops the language segment ("Quote Demo", not "EN Quote Demo").

v5.13.0 (2026-10-04, SlideMage manual, found while building it): \\SMCode{text} and \\SMCmd{name} set code in running text in Fira Mono Regular at 90% (\\texttt is the theme's Fira Mono Bold, which reads heavy and wide next to the Fira Sans Light body text and made the manual's slides overflow); \\SMCmd{slide} prints \\slide. Transcript: both become `code`, and a literal backslash survives -- \\textbackslash and \\SMCmd's backslash are parked while the inline conversion strips macro names and put back afterwards (before, \\texttt{\\textbackslash pause} came out as `pause`). \\SMChapterAgenda now tries \\normalsize first, then \\small, then \\footnotesize (it left the dividers mostly empty at \\small).

v5.13.1 (2026-10-04, found in the SlideMage manual's transcript): a \\\\ line break in running text becomes a space -- the macro strip used to take "\\SlideMage" out of "...\\\\SlideMage" and leave a stray backslash ("demonstration\\ 5.12" on a title slide); \\textperiodcentered becomes a middle dot instead of disappearing.

v5.13.2 (2026-10-04, found in the SlideMage manual): the generated appendix's footer no longer shows the last real slide's version and language next to "appendix" (appendix_toc resets \\ifSMSlideVersionSet/\\ifSMSlideLanguageSet with the slide id); a thumbnail cell without a cached preview labels the slide by its slug without the language segment.

v5.13.3 (2026-10-04, found in the SlideMage manual): images placed with the v5.x figure helpers -- \\cornerfigure[width/height]{file}, besidefigure, \\fitfigure, \\sectionfigure -- are now seen by the image scan (alt_blocks.referenced_images(): the Images tab's slide list, `used_on`, takeaways, transcripts) and by the pre-render check's "image" rule. Before, an image placed only that way had no slide in its `used_on`. An argument containing a backslash is content (a block, an \\includegraphics), not a file.

v5.14.0 (2026-10-04, found in the SlideMage manual's transcript): transcripts read the constructs a v5 slide uses. Inline code (\\SMCode, \\SMCmd, \\texttt) is verbatim -- escaped braces, \\textbackslash, "--" and "gap=12pt" survive, and adjacent spans join (`\\input{...}`). Maths: arrows, Greek letters and common symbols become characters, \\frac{a}{b} becomes a/b, \\SMUnderbrace{x}{label} becomes "x [label]". A \\tableofcontents lists the deck's chapters with their first slide numbers. A slide's own \\providecommand/\\newcommand macros are expanded. tikzillustration bodies are left to their description; figure-helper paths, \\shrinklists, \\fontsize, \\setcounter, \\ifnum...\\fi, overlay specifications and \\hyperlink targets no longer leak as text; \\progressstrip, \\SMWarningSign, \\quotesource, referenceblock, sideimageframe and \\begin{frame}[standout] are rendered; a table inside a table cell and "\\\\[1pt]" row ends no longer break a table. Framework: \\SMCode/\\SMCmd's font no longer applies TeX ligatures, so "--project" prints as typed.

v5.14.1 (2026-10-04, found by the layout check on the SlideMage manual): two framework layout fixes, and the layout check moves here. \\SMCodeFile's panel is a \\colorbox around the listing instead of listings' own frame, which was drawn 4-8pt above the box it occupied, so a code panel stuck out over the Top Margin. In columns[T] a list at the top of a column now starts on the column's top, like one at the top of a minipage: a smaller list (\\shrinklists, \\small) used to keep \\@listi's 4pt \\topsep and start below a figure beside it -- Slidemaster slides with such a list at the top of a [T] column move up by that much, onto the Top Margin. tools/check_layout.py (from the Slidemaster project's .scripts/) works on any project (--project, or the folder with slide_ids.csv above the PDF); frames around code panels and pictures are no longer reported as table rules, and a slide with a \\progressstrip is not held to the Top Margin.

v5.14.2 (2026-10-04, direct report): "Archive unused content" finds everything in one run. Images were judged against every slide file, including the slides archived in the same run, so an image only such a slide used survived until the next click (screenshot-jcr-science-journal-profile-2023.png, used only by the archived uwj). Now only slides that stay in use keep their images -- this includes frozen versions no deck pins, which are archived anyway.

v5.15.0 (2026-10-04, direct instruction): the compile progress label counts the passes a deck really needs. Every compile counts its LaTeX passes and remembers them per deck and job kind (instructor, during-course, after-course, presenter, per-chapter) in the project's .slidemage/compile_passes.json; the next compile of that deck shows "pass 3/6" instead of the fixed guess of 4 (3 without a bibliography), which stays for a deck compiled for the first time. Every SlideMage compile starts in a fresh build folder, so a deck's count only changes with its content. Not stored in the deck file: a compile writing into the deck would make an open deck editor refuse its next edit as "changed on disk".

v5.15.1 (2026-10-04, direct instruction: "the visible edge counts"): tools/check_layout.py measures the Right Margin as the logo's visible right edge on the rendered page. It used the PDF's drawing list, which skipped a white shape with a dark outline (the SlideMage logo's front card) and a small text mark (MCI's "®"), and so put the margin 2.4pt (SlideMage) to 12.7pt (MCI) too far left. Measured right, every template's logo ends on the framework's own Right Margin, so nothing changes in the framework.

v5.16.0 (2026-10-04, SlideMage manual plan, step 7): the SlideMage manual (decks/slidemage-manual.tex) is example/'s demo deck. The demo decks test.tex, test-student.tex, test-slides.tex and test-slidemage.tex and the sixteen ZZ* demo slides the manual replaces (ZZL included: a two-level subset of ZZO) are retired from example/ (their ids stay registered); the reference sheets in the manual's appendix and the empty slide get reserved demo ids: ZZU -> 2rg (footnote symbols), ZZO -> 2v9 (itemize spacing), ZZI -> 2p8 (empty slide). "Open Project..." on an empty folder therefore seeds a new project with the manual. CI compiles the manual (instructor and during-course; a clean build needs 6 passes, so latexmk runs with $max_repeat=10). README and docs point at the manual's slides. The Slidemaster project's own test decks and ZZ* copies are untouched.

v5.16.1 (2026-10-05, direct instruction): the compile progress label says "(estimated)" after the pass count while it is a guess -- a deck never compiled before (4 passes, 3 without a bibliography), a single-slide render, Update previews -- e.g. "pass 2/4 (estimated), slide 12/40"; once a deck has been compiled, its remembered count shows without it.

v5.17.0 (2026-10-05, direct instruction): readable code panels. \\SMCodeFile's three colours are named colours a template can set before \\input{Slidemaster_preamble_base}: SMCodeKeywordColor (control sequences), SMCodeCommentColor (% comments), SMCodeBackgroundColor (the panel). Without them a template keeps the old look -- highlight colour, c_primary_gray, c_tertiary_gray -- which with a yellow or orange highlight colour was about 1.1-1.3:1 contrast. The SlideMage template now sets #0066cc / #5f5f5f on #f0f0f0 (4.9:1 and 5.6:1; was 4.4:1 and 4.0:1), example's Uni Graz template a darkened Graz blue #1f5c99 and #5f5f5f on its tertiary gray (5.4:1, 5.0:1). Only pages with a code panel change. Projects with their own templates set the three colours there (SlideMaster_SP: Graz, MCI, Innsbruck done).

v5.18.0 (2026-10-05, direct instruction): the SlideMage manual has a deck group of its own. Tag `manual` (decks/slidemage-manual.tex now carries \\decktags{manual}, was test): a "SlideMage manual" section at the bottom of the deck table; it wins over any other group tag; it is never offered in the Tags or Duplicate dialogs (a copy of the manual starts out as a course deck), and the manual's Tags button is disabled, so it always stays in its section. Unlike a test deck, its name is a link to the deck editor again. Compile runs take it after the test decks.

v5.19.0 (2026-10-05, direct instruction): a project's copies of the framework and of the SlideMage manual follow app updates. A new project records a hash of every file it got from SlideMage (.slidemage/bundled_copies.json -- commit it). On start, when this SlideMage carries newer versions, an info dialog offers the update (Update / Not now / Don't ask again for this version); it then replaces the files changed only upstream, adds new ones, removes the ones no longer shipped, backing up everything it replaces or removes in .slidemage/backups/<time>/ first. Files changed in the project are kept and listed; files deleted there stay deleted; the manual's new slide ids go into slide_ids.csv, its image descriptions into media/alt-text.json (unreviewed descriptions of replaced images are refreshed). Older projects: a sibling latex/ that isn't part of a git checkout is adopted (every file that differs from this version is replaced, after the backup); a git checkout is never touched. A project without the manual is offered to add it -- only missing files are added. (bundled_copies.py; project.init_project() writes the baseline.)

v5.19.1 (2026-10-05, direct instruction): the "Test decks" section sorts below the "SlideMage manual" section in the deck table (work, course, research, manual, test), and compile runs follow the same order.

v5.20.0 (2026-10-05, direct instructions): compile pass counts. (1) A compile that needs more passes than expected raises the count in the progress label -- "pass 5/5" -- instead of "pass 4/4 (extra pass 5)"; the bar never moves backwards. (2) A deck's presenter and instructor compiles share their remembered count (they need the same passes: same content, the presenter layout only adds the notes panel -- measured equal on every SlideMaster deck), so a presenter compile shows the right count after an instructor compile and vice versa, without "(estimated)". A student version without a count of its own borrows the nearest one -- the other student version, else instructor/presenter -- and a per-chapter compile its version's whole-deck count, both still marked "(estimated)" (a student version can need a pass more or less: fewer slides, "final state only" slides). (compile_passes.predict().)

v5.20.1 (2026-10-05, found when the user's update dialog listed them): the manual's copy carried a developer's slides/.backups (the slide editor's undo history) into users' projects. The exe now bundles the example project file by file without slides/.backups, build output (.build, .previews, pdf, compiled decks) and machine-local settings (.slidemage/app_settings.json, project.json, compile_passes.json, bundled_copies.json); the copy and the update check skip every hidden folder; a new project never gets .backups. A project that already received them gets them removed by the next manual update (backed up first, as always).
v5.21.0 (2026-10-05, direct instructions): (1) A duplicated deck starts with the remembered compile pass counts of its original (compile_passes.copy_counts), so its first compile already shows "pass 3/5"; an original never compiled passes nothing on. (2) Manual: the installation slides are back in chapter 2 (the divider, 1f8, lists them; Appendix A and its divider are gone, the reference appendix is just "Appendix: Reference"). (3) Manual: the footer labels on slide 1nt ("Inside a slide file, and its footer") follow the footer when the compile timestamp is off -- the arrows move with the id block, the "compiled" arrow is dropped, the labels end at their arrows --; the "navigation links" arrow is gone from that slide (any deck can have them: \SMNavigationBar in its preamble, not a manual-only feature).
v5.22.0 (2026-10-05, direct instruction): a frozen version opened from "Previous versions" has a button "Make this the current version" (slide_versioning.restore_version): the slide's current content is archived first as a frozen version of its own (under its own tracked version, as a Save would), the frozen content becomes current with a new version number -- the highest known one with the minor number bumped, never reused -- and the current header ("Included in decks") is kept. Refused if the slide already has that content, or if the archive name is taken by different content, or if the current slide's tab has unsaved changes. Manual slide 1nt points at the navigation links again (any deck can have them).
v5.23.0 (2026-10-05, direct instruction): saving a new version of a slide that is used in more than one deck, is pinned in a deck, or has a translation first shows "Where this slide is used" (slide_usage.py, qt_slide_usage_dialog.py). Per deck: "Move to current" (the default; a pinned \slideversion / \omitslideversion becomes \slide / \omitslide, a call that follows -current already moves on) or "Keep vX.Y.Z" (the call is pinned to the version just frozen; a deck pinned already can "Stay on" its version). \slidefinal, \conditionalslide and \slidestep have no pinned form and always follow -current. The slide's translation partners (from its "Translation of" / "<LANG> translation" header comment) are named with their decks, with a tick box to open the translation after the save. Cancel cancels the save. The deck edits run after the slide is written, through the deck editor's own stale-checked rewrite, and open deck editors refresh. Not shown for "Overwrite" (no new version).
v5.24.0 (2026-10-05, direct instruction): \multilingualtext has a keyed form for any number of languages: \multilingualtext*{EN={Hello}, DE={Hallo}, FR={Bonjour}} typesets the pair whose key is the deck's \decklanguage code (upper or lower case); a deck in a language the list lacks gets the EN text, else the first. The two-argument form \multilingualtext{EN}{DE} is unchanged (and no longer a plain \newcommand but an expl3 NewDocumentCommand with the same behavior). \decklanguage[fr] (any code) now also sets the PDF /Lang to that code instead of en-US. Not yet language-aware beyond en/de: \ifSMGerman and the "Image source(s)" label.

v5.25.0 (2026-10-05, direct instruction): the project SlideMage opens by itself is now also remembered beside the exe (file "last_project" in the exe's folder, written whenever a project is opened). The pointer in %APPDATA% belongs to one computer, so a second PC running the same cloud-synced exe asked for the project again; it now finds it from the copy beside the exe. When the remembered project no longer exists the folder picker starts in its nearest existing parent folder instead of the program folder.

v5.26.0 (2026-10-05, direct instruction): the "Course link..." button of the deck table is now "Settings" (on every deck row, also for work, research and test decks; disabled for the SlideMage manual) and opens a dialog with the deck-wide settings that live in the deck file: template, language, footer text, course link (with Open), where the PDFs go (all outputs, each version, presenter, transcript, with Browse) and the always-add-appendix flag. All changes are written in one stale-checked write; only what was changed is touched, comments and line endings stay. New modules deck_settings.py (text in, text out) and qt_deck_settings_dialog.py replace qt_course_link_dialog.py; deck_editor.course_url_text() is the text part of set_course_url().

v5.27.0 (2026-10-05, direct instructions): (1) New \\SMLink{target}{text}: a link in running text, underlined like an \\href (a bare \\hyperlink has no underline); the manual's text links use it. (2) besidefigure lowers its figure by \\SMBesideFigureTopGap (0.2em) so its top edge meets the top of the first line's letters instead of the line box; this moves every besidefigure figure down by about 2 pt (yshift=0pt restores the old position). (3) Fix: the manual and framework update (bundled_copies.py) no longer treats SlideMage's own '%% Included in decks:' line as a user edit -- 38 of 56 manual slides of a real project were 'kept' only because of it and could never be updated; an update keeps the project's own line. (4) tools/manual/adopt_user_edits.py brings edits made in a project's copy of the manual back into example/. (5) The manual: slides 1b6, 1kg, 1ih rewritten and split (new 1b2, 1vd, 1be), the user's edits of the project copy adopted.

v5.27.1 (2026-10-06, direct instruction): every slide of the SlideMage manual carries \\setSlideVersion{1-0-0}, so its footer shows a version (51 slides had none: they were written as files and never saved through the slide editor's version dialog). The project's copy was stamped the same way and its update baseline moved with it, so nothing becomes a user change.

v5.28.0 (2026-10-06, direct instruction): \\sectionframe: every title bar is now the same height. Before, the bar depended on the title: one without descenders ("Slides", "Decks and deck versions") was 4.15 pt taller than one with them, and the height of the tallest letter shifted it further (the manual's dividers measured 85.04, 85.66, 86.92 and 89.19 bp). The title measurement gets a \\strut, the toppading formula a fixed reference depth (\\SMSectionframeRefDepth), \\SMSectionframeHeightCorrection is recalibrated, and \\sectionfigure starts 0.1 bp under the bar. VISIBLE CHANGE in course decks: section slides with a title without descenders (e.g. neb, u97, dvh) get a 4 pt shorter bar, and the body text of every section slide starts 1.5 pt lower than the new bar edge (it used to sit 7.4 pt under it). Manual: dividers 1y9 and 1f8 fixed (1y9 had an empty line above its text, 1f8 listed the agenda before its intro), all intros top-aligned.

v5.28.1 (2026-10-06, direct instruction): the ticked rows of a deck tab stay ticked when the tab is rebuilt -- saving a slide's source, any deck edit, a refresh, a trip through the Grid view. The selection is remembered by what each call is (command, slide, version, conditions, steps and which occurrence of it), not by its position in the file, so it also follows slides that move; rows whose slide was removed drop out.

v5.29.0 (2026-10-06, direct instruction): project compatibility. compat.py keeps a registry of the changes that are not backwards compatible (nothing registered yet: from now on a BREAKING: release must add its entry). When a project is opened with a newer SlideMage that has such changes the project does not have yet, a dialog offers Update project (automatic fixes, every changed file backed up first, #workdeck included), Show report, Not now (the dialog returns on the next open) and Don't ask again (per change). Appearance-only changes stay quiet: Info -> Project compatibility lists them. A project last used by a newer SlideMage gets a notice. The report (.slidemage/compat-report.md/.json) has file and line for every finding and a prompt for an AI tool; slidemage --check-project [--fix] [--json] does the same without a window. project.json keeps its other keys, highest_app_version never goes down.

v5.29.1 (2026-10-06, direct instruction): the manual carries the user's evening edits of 1an, 1bb, 1hi, 1pf, 1r2, 1v5, 1vn and 1ym (adopted from the project copy; their earlier versions are frozen next to them). Content only.

v5.29.2 (2026-10-06, direct instruction): the main window's search row says what it does: "Find slide:" is now "Slide name search:" (an ID/name lookup) and the button "Search all slide texts..." is now "Project-wide full-text search..." (and no longer loses the hook of the j: its descender was clipped by the 20 px the tab bar corner leaves it). The manual's slide 1ub names both (callouts 8 and 9), 1b6, 1cx and 1r8 use the new names, and the user's further evening edits of 1d8, 1kp, 1ti, 1ub, 1vn and 1y5 are adopted.

v5.29.3 (2026-10-06, direct instruction): manual content: slide 1ti has numbered callouts (1-10) on a cropped deck-editor screenshot with a matching numbered list, slide 1b2's screenshot strip now includes the versions list and the language controls, the user's edits of 1gu, 1kg and 1vd are adopted. Screenshots regenerated (tools/manual/make_screenshots.py prints the 1ti callout anchors).

v5.29.4 (2026-10-06, direct instruction): manual slide 1ih shows a taller Images tab screenshot (the window for that shot is 1080 px high, so the short and long description fields are visible) in a wider picture column; the user's edit of 1ih is adopted.

v5.29.5 (2026-10-06, direct instruction): manual slides 1ti, 1b2 and 1ih were checked in the context of the Slidemaster project, where the new screenshots were missing (the slide texts had been changed there but the pictures only in the bundle): now both match and nothing overflows. Slide 1ih has the Images tab as a 2828 x 2468 px picture (window 1500 px high) next to the text, running from the title bar to the footer, so the description, takeaway and source fields are readable. The user's edit of 1be is adopted.

v5.30.0 (2026-10-06, direct instruction): new \shrinklists{3}: all list levels at \scriptsize, one step below \shrinklists{2} (which gives \footnotesize/\scriptsize/\scriptsize). Until now every value of 2 or more meant 2, so a slide that wrote \shrinklists{3} silently got the same size as {2}; it now gets the smaller one.

v5.30.1 (2026-10-06, direct instruction): manual slide 1ih has the Images-tab screenshot on the right, the text on the left (as on the other picture slides). The user's edits of 1b2, 1b6, 1rv, 1ti and 1ub (and the frozen versions of those slides) are adopted, so the bundled manual and the Slidemaster copy are identical again.

v5.30.2 (2026-10-06, direct instruction): manual slide 1pn keeps "(slide ID 1ym)" together on one line.
"""
from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

VERSION_NUMBER = "v5.30.2"

# Matches every "vX.Y.Z (...): description..." paragraph in this module's
# own docstring above -- anchored to a line start so it skips the
# free-form "Estimated at v2.9.0 on ..." paragraph (doesn't start a line
# with "v2.9.0 (") and the trailing "The displayed string also appends
# ..." paragraph about VERSION itself, neither of which is a per-bump
# history entry.
_HISTORY_ENTRY_RE = re.compile(
    r"^(v\d+\.\d+\.\d+) \(([^)]*)\):\s*(.*?)"
    r"(?=\n\nv\d+\.\d+\.\d+ \(|\n\nThe displayed string|\Z)",
    re.MULTILINE | re.DOTALL,
)


@dataclass
class HistoryEntry:
    version: str
    meta: str          # whatever's in parens -- usually a date + reason
    description: str
    # The same text split at blank lines, each paragraph's own line wraps
    # joined -- keeps a "BREAKING:" paragraph recognizable
    # (packaging/release_notes.py, updater.breaking_notes()).
    paragraphs: list[str] = field(default_factory=list)


def parse_history() -> list[HistoryEntry]:
    """Every per-bump history entry in this module's own docstring above,
    oldest first. The Info menu's version-history dialog
    (qt_version_history_dialog.py) reads this directly rather than
    maintaining a separate changelog -- a new history paragraph appended
    here (the project's own standing per-bump convention, see
    VERSION_NUMBER's comment) is automatically visible in the GUI with
    nothing else to keep in sync."""
    text = __doc__ or ""
    entries = []
    for match in _HISTORY_ENTRY_RE.finditer(text):
        version, meta, body = match.group(1), match.group(2), match.group(3)
        meta = re.sub(r"\s+", " ", meta).strip()
        description = re.sub(r"\s+", " ", body).strip()
        paragraphs = [
            re.sub(r"\s+", " ", paragraph).strip()
            for paragraph in re.split(r"\n\s*\n", body) if paragraph.strip()
        ]
        entries.append(HistoryEntry(
            version=version, meta=meta, description=description, paragraphs=paragraphs))
    return entries


def _run_git(*args: str) -> str | None:
    popen_kwargs: dict = {}
    if os.name == "nt":
        popen_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    try:
        result = subprocess.run(
            # The app's own checkout, not the project: since v4.0.0 the two
            # are separate repositories, and the version string is about
            # the app. (A frozen build has no checkout -> plain number.)
            ["git", *args], cwd=Path(__file__).resolve().parent, capture_output=True, text=True,
            timeout=5, **popen_kwargs,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def _compute_version_string() -> str:
    commit_dt = _run_git(
        "show", "-s", "--format=%cd", "--date=format:%Y-%m-%d %H:%M", "HEAD"
    )
    if commit_dt is None:
        return VERSION_NUMBER
    return f"{VERSION_NUMBER} ({commit_dt})"


VERSION = _compute_version_string()
