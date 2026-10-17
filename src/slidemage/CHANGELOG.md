# SlideMage release history

For each app-code change, bump `VERSION_NUMBER` in `src/slidemage/version.py`
and append its entry here in the same commit. Keep entries oldest first, in
the format `vX.Y.Z (date, reason): description`, with any further paragraphs
separated by blank lines. Use plain backslashes for LaTeX commands; this is
text, not a Python string. The About sheet and `packaging/release_notes.py`
read this file through `version.parse_history()`.

SlideMage's own version string, shown in the main window's title bar and
the Info menu's version-history dialog (formerly gui.py's own toolbar,
back when that was the only display for it). Renamed from "SlideManager"
to "SlideMage" in v3.20.0 (see that entry below) -- older history entries
below intentionally still say "SlideManager"/"slidemanager", since they're
a dated record of what was true at each past release, not living
documentation.

`VERSION_NUMBER` in `version.py` is hand-maintained, not derived -- a
semantic-looking "v2.9.0" says a lot more at a glance than a bare git hash ever did, but
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

Release notes (v5.35.4, direct instruction: GitHub users should see "in few
sentences or bullet points what is new since the previous release"): every
history entry after v5.35.3 has a paragraph of its own starting "NEW:" --
on the NEW: line an optional one-sentence summary, then one "- " bullet per
change users notice, in plain words (what they can do now, what was fixed;
no module names). The GitHub release lists the NEW: bullets of every
version since the previous release, the tagged version's summary on top
(so when a release bundles several versions, that summary describes them
all), then the BREAKING: paragraphs; the technical text of an entry stays
here. packaging/release_notes.py refuses a release with an entry lacking
NEW:. (Exception, v8.3.0: entries up to and including v8.2.1 are exempt;
only a version after v8.2.1 must have the paragraph.)

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
v3.0.0 correction (see that entry below), which this file's own
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
decorative-image marking (a LuaTeX \includegraphics wrapper tags them
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
of a hand-authored \source{} per slide -- 167 of 281 images given a real
source, 152 slides' now-redundant \source{} calls removed) -- committed
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

v2.33.0 (2026-08-21, reconstructed 2026-08-26): The whole per-slide version-tracking system -- \setSlideVersion{}, the footer's version display, and the freeze-then-bump Save dialog -- migrated onto all 650 slides at once. The whole per-slide
version-tracking system this project still uses today --
\setSlideVersion{}, the footer's "v1.2.0" display, and SlideManager's own
freeze-then-bump Save dialog (slide_versioning.py), migrated onto all 650
existing slide files at once; "Include footer timestamp" defaulted off;
and a compiled PDF's byte size is now verified before declaring a
relocation successful, instead of trusting "no exception raised" (a
cloud-sync-interrupted copy could previously produce a silently-accepted
0-byte PDF).

v3.0.0 (2026-08-24, direct instruction): Multi-language (EN/DE) support: slide-language filenames, deck-level \decklanguage, rename/cross-reference tooling, and alt-text translation. Multi-language (EN/DE) support
-- new slide-language filename convention, deck-level \decklanguage,
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
\multilingualtext{}{})/Render to PDF/Render transcript -- below); the find
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
slide EN -> mult (or typing in a fresh \multilingualtext{}{} call) left
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

v3.3.3 (2026-08-25, direct instruction): The Insert command… combo gained \multilingualtext{EN}{DE}, seeding a selection into the first braces. "Insert command..." combo (the
slide-source editor's own formatting toolbar) gained
\multilingualtext{EN}{DE} -- a selection goes into the *first* braces
(assumed English, matching that macro's own argument order) and the
cursor lands in the empty second braces ready for the translation; with
no selection, both pairs are empty and the cursor lands in the first one.
New _insert_multilingual(), a two-argument sibling of _wrap_or_insert's
existing single-argument \macro{...} wrapping.

v3.3.4 (2026-08-25, direct report against a real "mult" slide, g6q):
Fixed a "mult" slide's transcript showing both languages concatenated together, from a title-stripping regex that collapsed both braces into one. Transcript.render_slide() never resolved \multilingualtext{EN}{DE} calls
before extracting the title/body, so a "mult" slide's transcript showed
*both* languages concatenated together -- alt_blocks._slide_title()'s own
macro-name-stripping regex only removes the bare "\multilingualtext"
token, then strips every remaining brace indiscriminately, collapsing
"{EN}{DE}" into "ENDE" rather than picking one. New
_resolve_multilingual_text() (brace-matched, so a nested \textbf{...}
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
\gothamFooterTimestampOverride hook for a full deck compile.

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
is) -- the slide's own \includegraphics{...pdf} is untouched either way,
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
\slide{} call collapsing all its reveals into one. Uses the python-pptx
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
reveal-step handling -- every PDF page belonging to one beamer \slide{}
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
\setSlideVersion{} line to disk correctly, but never updated the live
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
`\begin{ENV}` line additionally opens the matching `\end{ENV}` one line
below at the same indentation, cursor left in between at one extra tab of
indentation -- pre-seeded with `\item ` when ENV is
`itemize`/`enumerate`. Detects the env name via the bare `\begin{ENV}`
token rather than trying to regex-match the rest of the line, so it
still fires correctly when `\begin{}` is followed by its own further
arguments on the same line (`\begin{standardframe}{Title}`, a title
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

v3.9.0 (2026-08-31, direct instruction): A Reindent button recomputes a slide's own indentation from its \begin{}/\end{} nesting, and smart Enter now also continues \item lines. Two more editor improvements.
(1) A "Reindent" button (slide files only, i.e. self._is_slide) recomputes
every line's own leading whitespace from its \begin{}/\end{} nesting
depth (one tab per level) -- reindent_latex(), a pure module-level
function so it's independently testable, with qt_slide_source_tab.py's
own _on_reindent() just the Qt-buffer/undo-step wrapper (the whole
document replaced as one edit block, so a single Ctrl+Z undoes the
entire pass). Deliberately scoped to \begin{}/\end{} line-start tokens
only, the same scope the smart-Enter feature below already commits
to -- not a full brace-nesting indenter, which would also have to reason
about braces inside math/macro arguments this project's slides use
constantly (\textcolor{}{}, nested \footnote{\fullcite{}}, tikz node
options, ...). Confirmed directly against real content: a full scan of
every slide file found 230 of 651 with genuine drifted indentation (e.g.
22s-EN-More-Exotic-Bonds's own \begin{minipage} body left at the same
depth as \begin{minipage} itself rather than one tab in), all fixed
correctly; the other 421 are already-correct and reindent to a byte-for-
byte no-op. One known, accepted side effect: hand-added *extra*
indentation used to visually align a wrapped multi-line command argument
(e.g. a \node[...] at (...) whose own {content} sits on the next line,
indented an extra level purely for readability, not environment nesting)
gets flattened back to the enclosing environment's own depth, since this
function has no concept of "argument continuation," only \begin{}/
\end{} depth. (2) LatexPlainTextEdit's smart Enter (see v3.7.0 above)
now also continues a `\item` line: pressing Enter at the end of a line
starting with `\item` inserts a new `\item ` at the *same* indentation
(sibling items in one list, not nested content) -- checked only after
the existing \begin{ENV} trigger finds nothing, so a line like
`\item \begin{itemize}` (an item that itself opens a nested list)
still gets that more specific begin/end handling instead.

v3.10.0 (2026-08-31, direct instruction): A Check syntax button asks a local Ollama model to flag likely LaTeX problems, offering a fix only when its claimed original text still matches exactly. A "Check syntax" button in the
slide and deck edit tabs (self._is_slide or a deck's own raw .tex source
-- excluded only for the Slidemaster.bib editor). Sends the editor's
current buffer to a local Ollama model (syntax_check.py, new module,
same call/parse shape as alt_draft.py's own OllamaBackend/
OllamaTranslationBackend, kept as a self-contained second copy rather
than importing that file's private helpers) asking it to find likely
LaTeX syntax problems -- unbalanced braces, mismatched \begin{}/\end{}
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
\setSlideVersion{} line, and every \vbox to 0pt{...} block (this
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
\vbox to 0pt{...} absolute-positioning wrapper is off-limits, since
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

v3.12.0 (2026-09-07, direct instruction): The alt-text workflow now covers hand-drawn tikz illustrations via \tikzillustration{ID}, describable and role-markable the same way a real image is. The Images tab's alt-text
workflow now covers hand-drawn tikz illustrations, not just
\includegraphics-ed files -- see ALT_TEXT_NOTES.md's "Phase 9" for the
full design. `\tikzillustration{ID}` (Slidemaster_preamble_base.tex) wraps
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
themselves defined), a `\newcommand`/`\definecolor` declared above the
slide's own frame going undefined in a standalone recompile even though a
real deck compile already sees it, and one slide's own external
`\resizebox{}{}{...}` wrapper (never part of the extracted illustration
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
Python's own string parser reads `\t`/`\b`/`\n` as their real escape
meaning (a tab, a
backspace, a newline) and quietly swallows the rest, which is exactly
what had already happened to `\begin{}` in v3.9.0's own entry (a literal
backspace character sitting where the text should read "\begin{}") and to
`\newcommand` in v3.13.0's (silently split by a real newline, invisible
until this file's own runtime value -- not just its source text -- was
checked directly). Fixed globally across the whole docstring, all 57
entries verified to import with zero SyntaxWarnings and re-checked for
every affected command name still being intact in the actual parsed text,
not just judged by eye against the source.

v3.14.0 (2026-09-16, direct instruction): a new "Presenter" checkbox
(qt_deck_table.py) compiles a separate `<deck>-instructor-presenter.pdf`
using beamer's own built-in dual-screen mechanism (\setbeameroption{show
notes on second screen=right}, gated behind a new \ifdefined
\gothamPresenterModeOverride hook in Slidemaster_preamble_base.tex,
compiler.py's own wrapper file \def's it exactly like
\deckversionoverride already is) -- every real slide becomes one wide
page, the plain slide on the left and a panel with that slide's own
\note{} text on the right, for presenter software (pympress recommended;
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
compile produces the expected wide combined pages, and \note{} text
placed on a real test slide is confirmed present (both by direct text
extraction and visually) in the correct panel.

v3.14.1 (2026-09-10, direct report/instruction): a real \note{} bug found
compiling a full presenter deck for the first time, plus a note-page
layout redesign. Compiling t-Uni-IA2-2026w's own presenter PDF end-to-end
(the first real multi-hundred-slide deck run through v3.14.0's own new
feature, not just the single-slide test it was verified against) failed
outright: slides/m47-EN-Portfolio-Risk-Variance-current.tex's own
\note{...} call had two consecutive \\ line breaks with nothing but
whitespace between them ("Develop first, show after!\\\\ Cov
signifies..."), a genuine "There's no line here to end" LaTeX error --
invisible until now since beamer silently discards \note{} content
whenever nothing actually renders it, which was every compile before
presenter mode existed. Fixed by replacing the doubled \\\\ with
\par (valid in any context \note{} can appear in, same visual
paragraph break intended); grepped every other slide's own \note{} call
for the same doubled-\\ pattern and found none.

Also (direct instruction, same session): beamer's own default "note
page" template (beamerouterthemedefault.sty's
\defbeamertemplate*{note page}{default}) reserves its top quarter for a
thumbnail of the current slide (\insertslideintonotes) plus a rotated
compile-date beside it, then gives the title band (short title plus a
section/subsection/frametitle breadcrumb) that same 0.25\paperheight,
leaving only the bottom 0.75 for \insertnote -- redundant here, since
pympress (this project's own recommended presenter software) already
shows the current and next slide on its own screen, and \title{} is
never called anywhere in this project (confirmed by grep), so the short-
title line was always blank. Two real problems found getting a
replacement working, neither caught until compiled against a real slide:
first, \defbeamertemplate*{note page}{default}{...} here errors ("Command
\beamer@@tmpop@note page@default already defined") -- both the starred
and unstarred \defbeamertemplate forms register a variant name via a
plain \newcommand internally, which always errors on a name beamer's own
outer theme already registered; fixed by registering a new named variant
("gothampresenter") instead and selecting it via \setbeamertemplate{note
page}[gothampresenter], the same define-then-select pattern this file's
own footnote template already used. Second, a first attempt shrinking the
title band to a fixed 0.08\paperheight overlapped real note text on a
real slide the moment its own section/subsection/frametitle breadcrumb
needed more than one line (this project's own decks do call \section{})
-- fixed by dropping the fixed height/\vfil entirely in favor of a
natural-height \vbox (exactly as tall as whichever breadcrumb lines are
actually non-empty for that slide, never more), which structurally
can't overlap \insertnote below it regardless of how many lines a given
slide's own breadcrumb needs. No color-theme "note title"/"note page"
background is set anywhere in this project, confirmed by grep, so
beamer's own \ifbeamercolorempty guards around both of those bands --
already pure no-ops here -- were dropped too rather than carried over
unused.

v3.14.2 (2026-09-11, direct report): a second real tikz_render.py bug
found the same way v3.14.1's \note{} bug was -- reported directly
against a real illustration, not caught by the single-slide test
v3.9.0-era tikz-illustration work was originally verified against.
previews/tikz_illustration_previews/ukm-tikz-*.png (the "Age of universe" label on
slides/ukm-EN-Tail-Risk-18-Sigma-current.tex's own tikz illustration) was
cut off on its own left edge: that label's `\node[overlay, anchor=north,
align=center] at (\linexcm,-1.3) {Age of universe};` sits centered within
a hair's width of x=0 (\linexcm evaluates to ~0.004cm), so roughly half
its own text width bleeds into negative-x -- deliberately excluded from
the tikzpicture's own bounding box by `overlay`, the same mechanism
already known from ys3's own \resizebox overflow (see v3.14.0's tikz-
illustration entry). Landed fine on a real slide, where that bleed lands
inside the frame's own ordinary left margin, but got clipped hard here
even after that same \pagewidth=60cm/\pageheight=60cm fix: enlarging the
*page* only adds room to the *right*/*bottom* of the frame's own small
(~128mm x 72mm) content block, which \shipout still plants flush at the
page's true top-left corner regardless of how big \pagewidth/\pageheight
are -- zero margin on the *left*/*top* either way. Fixed generally, not
by special-casing this one diagram, with two new plain-TeX primitives
(\hoffset=20cm, \voffset=20cm, tikz_render.py's own _wrapper_text())
shifting the whole shipped page's content well clear of every edge, not
just the two \pagewidth/\pageheight already covered. Verified directly:
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
\pagewidth/\pageheight fix first landed.

v3.15.0 (2026-09-16, direct instruction): non-linear navigation
infrastructure plus a new "Generate appendix TOC" checkbox. Every real
slide now carries a permanent \hypertarget{<bare id>}{} (Slidemaster_
preamble_base.tex's \setSlideID@aux, the single choke point every
\slide{}-family macro already passes through regardless of frame type),
giving any slide a free jump target for \hyperlink{}/\beamergotobutton{}/
\beamerreturnbutton{} without colliding with this project's own documented
\label{}/\foreach collision. The new checkbox (qt_gui.py, between
"Include footer timestamp" and "Auto-open generated PDFs") adds, on an
Instructor/version-less or Presenter compile only, a generated appendix: an
agenda slide (one entry per chapter plus a leading "Front matter" entry)
followed by a 4x5 thumbnail grid per chapter (slidemanager/appendix_toc.py,
new module), each thumbnail using the existing slide_snapshot.THUMB_SIZE
cache and linking straight to its real slide; clicking a chapter on the
agenda jumps to that chapter's own grid, and the institute logo on every
slide of an appendix-enabled compile becomes an invisible link back to the
agenda (\gothamInstituteLogoGraphic). Grid geometry (left-aligned to the
text margin, scaled up until either the row height or the logo's own right
edge binds -- direct instruction, from real rendered candidates) is
computed in LaTeX from this project's own per-institution length registers,
not a hardcoded cm value, so it adapts automatically across Graz/Innsbruck/
MCI. compiler.py's wrapper gains \gothamAppendixTocOverride and, for an
appendix-generating job, inlines the deck's full body (the same "copy
preamble, splice body" trick already used for a per-chapter compile) so the
generated appendix can land before the deck's own \end{document} -- a
plain \input{deck.tex} would hit that \end{document} first. Fixed along
the way: the appendix's own generated frames were leaving \slideID at its
last real value, which would have corrupted slide_snapshot.capture_deck()'s
cache refresh (it keys purely off footer "slide id:" text) -- reset to a
literal "appendix" (never a real 3-character id) right after \appendix;
and a \dimexpr geometry calculation that multiplied by 304 before dividing
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
ordinary `\conditionalslide` exclusion): `      itleframe`/`ullbleedframe`
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

v3.23.0 (2026-09-18, direct instruction): `\fullbleedframe{}` accepts a
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
the smart-Enter completion right after a freshly-typed egin{itemize}
already does -- instead of a blank line with nothing to type into. With
one or more lines selected, each non-blank line becomes its own
"\item <text>" line inside the new block instead of the selection's raw
text landing verbatim between egin/\end. Any other egin/\end
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
"egin{itemize}...\end{itemize}" to "Bulleted list", and a new
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
"Numbered" (plain egin{enumerate}, same wrap_env mechanic as
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
the existing `` right after "item" so "\itemsep{...}" etc. still
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
style buttons (ullcite/        extcite/\parencite -- the only three this
project's slides actually use, 285/40/6 uses respectively, zero bare
\cite) to insert that call at the cursor. Verified with a headless
(QT_QPA_PLATFORM=offscreen) smoke test: filtering, selection-enables-
buttons, style-button insertion, double-click-inserts-ullcite-and-
closes, and both the empty-query (shows everything) and no-match
(buttons stay disabled) edge cases.

v3.34.1 (2026-09-25, direct instruction): "Add reference" button (and its dialog's own window title/submit button) renamed to "Add reference to .bib", to say where the reference goes.

v3.35.0 (2026-09-26, direct instruction): a batch of editor and settings changes. (1) Duplicate-slide dialog: Enter now creates the slide (Create is the dialog's default button, Cancel no longer auto-default). (2) Adding a *duplicate* of an existing slide from a deck tab's "+ before"/"+ after" dialog now opens the new slide in its source editor, exactly like "Create new slide" already did. (3) Slide editor keyboard shortcuts, scoped to the tab like Ctrl+F: Ctrl+I/B/U = the I/B/U toolbar buttons, Ctrl+S = Save, Ctrl+R = Render to PDF (slides only). (4) New "Insert block..." dropdown next to "Insert list..." with the project's beamer blocks (block, example, alert, reference, definition, info, plus the three floating variants); a selection becomes the block body and the cursor lands in the title's braces. (5) Tabs menu: "Edit test-slides.tex" opens decks/test-slides.tex in source mode. (6) "Check syntax" can be aborted with Escape (dialog or editor focused): the Ollama request now runs on a worker thread instead of blocking the GUI thread, and abort() closes the socket so Ollama stops generating -- on Windows only Winsock's closesocket() on the detach()ed handle wakes a blocked recv(); socket.shutdown()/close() do not (measured). (7) Settings gets an "AI models" tab with one default model each for Syntax check, AI drafting, Image descriptions and Translation; every model picker now preselects that default, and picking another one there applies to that dialog/tab only (the old remember-the-last-pick behaviour is gone; the setting keys are unchanged, so existing values carry over). (8) "Add reference to .bib": for a working paper/report the institution is optional and a DOI field was added. Verified with a headless (QT_QPA_PLATFORM=offscreen) smoke test: the four shortcuts, both block-insertion paths, the new Settings tab, and Escape aborting a check against a deliberately slow fake Ollama server (0.05 s from key press to released Ollama slot, from the dialog and from the editor).

v3.36.0 (2026-09-26, direct instruction): (1) Pre-render syntax check (latex_lint.py, qt_render_check.py): every PDF render -- the slide editor's Render to PDF (the buffer), both Preview popups' Render now (the saved slide), Create PDF for any decks/versions/chapters/presenter and Export PPTX (the deck file plus exactly the slide files that job includes in that version, per-chapter jobs only their chapter, plus \input-ed fragments like test-slides.tex) and Update slide previews (every slide any deck uses) -- first runs a static, lexical check and only interrupts on an error (dialog: Cancel [default] / Show in editor / Render anyway); warnings go to the log. 14 checks, listed in README.md ("Pre-render syntax check"): encoding, braces, environments, math-dollar, math-delims, ampersand, hash, citation (key not in Slidemaster.bib), image (file missing), slide-file (deck call to a missing slide file) as errors, and underscore, percent, overlay, optional-arg as warnings. Tuned over all 930 slide/deck files until quiet on everything that compiles (its one finding is a real leaked group: an unclosed `{` on line 39 of slides/zgz-EN-EBIT-Definition-current.tex); cost measured at about 0.1 ms per slide file -- a 395-slide deck ~300 ms cold, ~65 ms warm. (2) \slidestep in the variant dropdown of deck-editor rows and the Add slide dialog, with a "steps" field (validated: numbers, commas, ranges such as 2- or 1-2,4); switching a plain \slide to \slidestep/\conditionalslide now starts with all three versions ticked. Verified headlessly: 28 synthetic good/bad snippets for the lint checks, the row/dialog behaviour, and slide->slidestep edits on a temp deck.

v3.36.1 (2026-09-26, direct question): the pre-render check gained a 15th check, "caret" (warning): a ^ in running text outside math ("10^6" typed without $...$ gives "Missing $ inserted"). Quiet on all 930 slide/deck files.

v3.37.0 (2026-09-27, direct instruction): "Insert citation" dialog gets a fourth button, "bib id", that inserts only the bare citation key (no ullcite{}/      extcite{}/\parencite{} around it).

v3.38.0 (2026-09-27, direct instruction): compile progress bar (compile_progress.py) -- a 3 px line in the "Create PDF" blue (#0066cc) right at the top edge of the log window, for Create PDF (queues of decks/versions/chapters/presenter), Export PPTX, Update previews and single-slide renders. Pass K comes from latexmk's "Run number K of rule 'lualatex'", the position inside a pass from the "(.../slides/<id>-" lines LaTeX prints when it starts a slide file: fraction = ((pass-1) + slides_seen/slides_total)/passes, 4 passes for a deck that uses biblatex, 3 without (single renders 3; Update previews' megadeck 4), held at 99% until the job really finishes, so an extra pass never overshoots. Slide totals reuse the syntax check's scoping (version/chapter filters, \input fragments); a queue is weighted by passes x slides; unknown-size jobs show the busy animation; Stop clears it. The status label now reads "pass 2/4, slide 137/395". Verified by replaying a real latexmk run (4 passes: 12.5% steps per slide, 99% at the last slide, 100% on MOVING), the two IA2 job specs (396/389 slides, 4 passes), single/second/unknown-size renders and Stop in a headless window; the slide-open pattern checked against a real IA2 TeX log (no wrapped paths).

v3.38.1 (2026-09-27, direct instruction): the deck editor's toolbar gets an "Add slide" button, shown only while the deck has no \slide{}-family calls of its own (e.g. #workdeck-mini right after being cleared out) -- an empty deck has no row to hang a "+ before"/"+ after" button off of, so there was previously no way to add its first slide from this tab. Same dialog/flow as those two buttons; deck_editor.empty_deck_insert_point() finds the insert point (right before \end{document}, one tab of indent) in place of a real call's own line_start/line_end/indent. Verified headlessly: the button's visibility toggles correctly for an empty vs. a real deck, a click hands the dialog the right insert point, and a malformed deck (no \end{document}) shows an error dialog instead of crashing.

v3.39.0 (2026-09-27, direct instructions): (1) Settings -> AI models gets a "Translation prompts…" button next to the Translation model row, opening the per-(model, source, target) prompt editor (qt_translation_prompts_dialog.py, split out of qt_settings_dialog.py) in its own dialog; the "Translation prompts" tab is gone. (2) The slide editor's Enter-completion no longer auto-inserts \end{standardframe} right after a line reading egin{standardframe}{...} (any title) -- standardframe's own body is a whole slide's worth of content, not a short list, so the auto-close just got in the way; Enter there now falls through to a plain newline at the same indent, same as any other non-completing line. Every other egin{ENV} (itemize, figureframe, ...) still auto-closes as before. (3) Fixed two real bugs in "Housekeeping -> Archive unused slides and media files" found from a direct report (a batch run archived 8gc/ZZH/egk -- all three real, in-use slides -- plus media/alt-text.json/.csv, the accessibility image-description store): unused_content.py's slide-usage scan never recognized \slidestep{} (added to the project 2026-09-20 but never added to that scan's own macro list), so a slide referenced only via \slidestep looked completely unreferenced; and alt-text.json/.csv are read directly by Slidemaster_alt.lua, never \includegraphics{}-ed, so the media scan always treated them as unused -- both are now excluded/recognized explicitly (MEDIA_NEVER_UNUSED, \slidestep{} added to SLIDE_CURRENT_RE). All 103 files that batch run archived were restored by hand (git status confirmed clean; the false positives were exactly 8gc/ZZH/egk plus alt-text.json/.csv, everything else in that batch was genuinely unused). (4) "Archive unused slides and media files" now scans first and shows every file it would move in a new confirmation dialog (ArchiveUnusedDialog) -- Cancel (the default) or "Archive N file(s)" -- instead of moving on a bare Yes/No, so a result like the one above can be caught before anything moves. Verified headlessly: standardframe/itemize/figureframe Enter behavior, the Settings dialog's tab list and button wiring (with TranslationPromptsDialog itself built standalone), the archive dialog's row count and default button, the real repo re-scanned clean (8gc/ZZH/egk now correctly seen as used, alt-text.json/.csv excluded), and the Cancel/Accept paths of the new confirmation flow.

v3.40.0 (2026-09-27, direct instructions): (1) Settings -> AI models and the former separate "Ollama models" tab are now one tab, the Ollama section underneath a QFrame horizontal rule + "Ollama models" heading -- same content and behavior as before, just no longer a second tab (_build_ollama_models_tab -> _build_ollama_models_section(layout), sharing the AI models page's own QVBoxLayout). (2) slide_ids.BANNED_WORDS (mirrored in .scripts/R_Slidemaster/R/slide.new.id.R's own denylist) rejects real English words that read badly as a slide id -- seeded with "pee" after it turned up as a real slide's id; the existing slide was renamed (pee-EN-Where-to-Aim -> x6t-EN-Where-to-Aim via slide_rename.rename_slide_id(), which updates every deck reference, slide_ids.csv, and the image manifest). (3) Merged Jürgen Fleiß's "delete slide" fix from the public SlideMage repo (commit e879c13, 2026-09-23) into slide_rename.py's own _line_removal_pattern(): the previous pattern assumed every macro's own argument list ends at \{id_slug\}, true for \slide/\slidefinal/\omitslide/\conditionalslide[versions]{id_slug} but not for \slideversion{}/\omitslideversion{}'s own trailing {version} or \slidestep{id_slug}[versions]{steps}'s own [versions]{steps} tail -- so "Delete slide" on a slide referenced only that way silently left the dangling reference (and, for \slideversion{}, the frozen version file) behind with no error; separately, the previous pattern's bare 
 (vs 
?
) left a stray 
 on every CRLF deck file regardless of macro. Verified with 9 cases covering all seven macros plus CRLF-cleanliness and a same-line no-false-match check.

v3.41.0 (2026-09-28, direct instructions): (1) "Create PDF" and "Export PPTX" now refuse a job that would typeset zero slides instead of running a real latexmk compile for a PDF with nothing on it -- compile_progress.count_job_slides() (built for the progress bar's own sizing) decides this, so \conditionalslide/\slidestep version filtering and \input{}-ed fragments like test-slides.tex are already accounted for; an all-empty batch is refused outright, a mixed batch compiles the rest and lists what got skipped. (2) Merged all ten of Jürgen Fleiß's "Fix ten review findings" from the public SlideMage repo (commit 34cdbd7, 2026-09-28) after independently verifying each against this codebase: (a) compiler.py's wrapper-file write now opens with newline="" -- writing an already-CRLF deck's preamble/chapter text (the per-chapter and appendix branches splice it in raw) through write_text()'s universal-newlines default doubled every \r\n it contained into \r\r\n; (b) run_job()/_relocate_pdf_and_finish() gained an on_relocated(success, dest_pdf) callback, fired once the PDF's backgrounded move into place has truly finished (or given up) -- _export_pptx_bg now waits on it and reads the pptx source from its real final destination instead of racing that move's own .build/ aux-file cleanup, which used to delete the file _export_pptx_bg was about to read; (c) run_jobs() gained _disambiguated_destinations(), which renames a same-batch collision (two+ jobs whose own \deckoutputfolder resolves to the exact same file -- concretely reachable for a deck that names an exact file and is then compiled as several per-chapter jobs, e.g. IA2) so they no longer silently overwrite one another; (d) reload_decks() now calls the new _remap_job_status_rows(), re-pointing self._job_status_map at the freshly rebuilt DeckRow widgets by deck name -- without it, "Refresh decks" mid-compile kept updating discarded row widgets, so that job's own running/moving/pass/fail badge silently stopped appearing on screen; (e) deck_scan.py gained is_commented(text, pos) (an unescaped "%" anywhere on the position's own line before it, not just at the line's very start) and now uses it to exclude a commented-out \section{} from a deck's chapter list; (f) deck_editor.is_commented_out(deck_text, call) applies the same check to a \slide{}-family call, and appendix_toc.py's _sections() now skips a commented-out call rather than still listing it in the generated appendix; (g)-(h) slide_source.py gained StaleFileError and an expected_text parameter on save_slide_source() (same stale-check-then-write shape as deck_editor.py's own _apply()), and qt_slide_source_tab.py's _on_save() now passes its own previous_text and shows an error dialog on a mismatch, instead of silently overwriting a slide file someone else changed on disk since it was loaded; (i) alt_draft.TranslationResult gained source_hash, captured by OllamaTranslationBackend.translate() from the exact entry snapshot it translated; apply_one_translation() now refuses to apply a result whose source_hash no longer matches the store's current English-text hash (the EN text moved on while the translation was in flight) instead of always overwriting; (j) qt_transcript_tab.py's three background-thread self.app.log() calls (a translation's "editor panel was already gone" message, and the draft-all/translate-all batch progress callbacks) now go through self.app.signals.log.emit() instead, since self.app.log() is main-thread-only and these all run on a worker thread. Verified headlessly: the empty-deck guard (all-empty batch refused, mixed batch compiles the rest, Export PPTX refused) and, for the ten findings, comment-aware chapter/slide-call parsing (including an escaped "\%" correctly NOT counting as a comment) with appendix filtering, the translation staleness guard against a real (temp) store, StaleFileError on a genuinely stale save and not on a fresh one, the CRLF wrapper fix at both the string and on-disk-bytes level, _disambiguated_destinations on a real collision and a solo job's untouched path, on_relocated firing exactly once on both the success and the cancelled-mid-relocation paths, and _remap_job_status_rows repointing a live compile's status updates at the post-refresh row (and dropping one whose deck vanished).

v3.41.1 (2026-09-28, direct instructions): slide_ids.BANNED_WORDS grows from just "pee" to 16 entries -- sex, wtf, ass, cum, tit, fag, cnt, kkk, fap, ffs, poo, hos, gun, gay, rip added, none colliding with any existing slide id so no rename was needed. Mirrored in .scripts/R_Slidemaster/R/slide.new.id.R's own denylist.

v4.0.0 (2026-09-28, direct instructions): SlideMage becomes a stand-alone, installable app in its own repository, stpalan/SlideMage, the authoritative one -- no longer a folder inside the SlideMaster project. The repository takes over the structure of Jürgen Fleiß's fork (JuergenFleiss/slidemage), merged with that fork's full history: the app as a Python package in src/slidemage (pyproject.toml; pip install -e . gives a slidemage command), the LaTeX framework in latex/ (Gotham theme, Slidemaster_preamble_base.tex, Slidemaster_alt.lua), a self-contained demo project in example/ (also the template for a new project), docs/, tests/, and GitHub Actions that build the Windows and Linux executables for every version tag (release.yml; the tag must equal VERSION_NUMBER). A project is any folder with a slide_ids.csv, chosen by --project, $SLIDEMASTER_PROJECT, an upward search, or the last project opened; per-project settings live in <project>/.slidemage/. From the fork: Open/create project, ODP/PPTX import, course schedule and course links, section editing and slide moving in the deck editor, editable slide numbers, Info -> Check for updates (now reading stpalan/SlideMage's releases; the GitHub token goes in Settings -> General -> Updates), editable AI prompts (Settings -> AI prompts), the Ollama host setting, Copy/Clear log. Kept from this line where both changed the same thing: the per-task default AI models (the fork's single 'Other AI tasks' default is dropped; its live refresh of open model pickers is kept and now follows the per-task defaults), the Settings dialog layout with translation prompts in their own dialog, the deck editor's Find-slide box and Add-slide button (the fork's inline 'Add first slide' button is dropped as a duplicate). Also: the splash screen is back for the Windows executable (the fork had dropped it); the version string's commit time now comes from the app's own checkout rather than the project's; the Settings and Translation prompts dialogs no longer open extra wide; the demo project's .latexmkrc files now work under MiKTeX with Git for Windows' Perl (it reports itself as 'cygwin' with /d/... paths, which left TEXINPUTS unusable); latex/ and example/ carry SlideMaster's framework and demo changes up to 2026-09-28. Version numbers v3.30.0 to v3.33.2 exist twice -- this repository's and the fork's (labelled "Jürgen Fleiß's fork" above) are different changes; both lines are merged here.

v4.1.0 (2026-09-28, direct instructions): (1) Settings -> AI prompts has three pages, Image descriptions, Slide rewrite and Translation; the translation prompts (default prompt and per-model overrides) moved there from the dialog behind the AI models tab's "Translation prompts…" button, which is gone (qt_translation_prompts_panel.py replaces qt_translation_prompts_dialog.py; unsaved text on the Translation page is asked about when Settings closes, like the other prompts). (2) Update behaviour: Settings -> General -> Updates chooses "Don't check for updates", "Check for updates and ask before installing" (default) or "Check for updates and install them automatically", stored per user and machine next to the GitHub token (updater.get_update_mode()). The packaged app checks three seconds after it starts, on a background thread; a failed check or an up-to-date copy only goes to the log. In "ask" mode a newer release offers Install now / Not now / Always install automatically / Stop checking for updates; "auto" installs and still asks before restarting. (3) Breaking releases: a release whose notes have a paragraph starting "BREAKING:" (or a "## Breaking changes" section), or whose major number is higher, is always asked about, even in automatic mode -- the dialog shows those paragraphs and offers Install anyway / Stay on vN.x (the newest release before the first breaking one) / Not now; every release between the running one and the newest counts (updater.plan_update(), using the release list instead of only the latest release). Convention, documented at the top of this docstring and in the README: a breaking release raises the major number and its history entry here gets a BREAKING: paragraph; the release workflow publishes the entry as the release notes (packaging/release_notes.py) and fails a major bump without that paragraph. (4) Project format guard: opening a project writes .slidemage/project.json ({"format": 1, "last_app_version": ...}, meant to be committed); a project whose format is newer than the app's gets a warning before it opens (Open anyway / Quit) and its file is left alone. (5) Import sessions follows the deck's \decklanguage: an English deck gets "Course sessions" with Date/Time/Location/Session, its German group names, session types and (fully known) remarks translated from a fixed word list (course_schedule.translate_schedule()), and the slide is named <id>-EN-Course-Sessions. (6) Transcripts omit colour: \textcolor, \color, \colorbox, \fcolorbox, \cellcolor, \rowcolor and \columncolor keep only their text -- before, the colour name was glued to it ("c_primary_highlightdata dredging"). Checked on all 14 SlideMaster decks: 427 colour specs removed, no other change. Not a breaking release: settings, prompts, projects and decks all keep working as before.

v5.0.0 (2026-09-30, direct instructions): systematic replacements for per-slide layout fixes, plus Jürgen Fleiß's Admin slides. (1) Admin slides (Jürgen Fleiß): the deck editor's "Import sessions…" is now "Admin slides…" -- a course-sessions table and/or a title slide (course title, chosen lecturers, semester) from the deck's linked Uni Graz course, read from UGO's public REST/JSON endpoints instead of the old HTML page (docs/UGO_api.md); follows \decklanguage. The generated sessions table is now a gothamtable (the project's table style) with the same column geometry. (2) LaTeX framework (latex/): automatic Top Margin -- every top-aligned standardframe measures where its first content landed (at shipout, new latex/Slidemaster_layout.lua) and moves its body onto the Top Margin line on the next compile via <jobname>.top (latexmk reruns); never pushes a full slide into its footnotes/footer; exceptions [c] frames, sectionframe, \progressstrip, \gothamManualTopMargin, \gothamAutoTopMarginfalse. New: \cornerfigure, besidefigure, \fitfigure, \gothamContentBottomAlign (Bottom Margin), \gothamFloatingInfoblockTopAlign, gothamtable[gap=...] (flush edges; a real separator after p/m/b columns; dark rules inside blocks automatically), [top=, bottom=] padding for the gothamfloating*block environments, \deckitem<spec>, \deckreveal*/\deckrevealfinal* (space-preserving), TikZ visible on=<spec>, \shrinklists, \EUR, \gothamTikzmark, TikZ styles gotham highlight/gotham dotted highlight/gotham arrow. The columns-first and columns[T] corrections (2026-09-21, Jürgen Fleiß 2026-09-30) now only act in frames the automatic Top Margin doesn't manage. (3) Pre-render check: new warnings table-edges (a gothamtable whose rules run past its text) and heading-text (a frame opening with a bold line above its list). (4) Transcripts: \ifgothamInstructorVersion/...DuringCourse.../...AfterCourse... resolve per version (a slide that wrote an item once per branch used to list it twice); \deckitem, \deckreveal[*]/\deckrevealfinal[*] no longer leave "[2]"/"<2->" behind; gothamtable's [gap=...] and the floating blocks' options and width argument are skipped (a floating block's title was its width before); "\ " is a space. (5) ODP/PPTX import writes gothamtable[gap=12pt].

BREAKING: the automatic Top Margin changes where the first content of existing slides lands -- a slide whose first line was not on the Top Margin line moves onto it (e.g. slides starting with a plain paragraph move down ~3pt, a table's top rule down to the margin). Decks that must keep their old positions add \gothamAutoTopMarginfalse to their preamble (or \gothamManualTopMargin before a single frame). The first compile of a deck needs the usual latexmk rerun to apply it.

v5.1.0 (2026-10-01, direct instructions): (1) LaTeX framework: list item gaps now shrink with the font. A level-1 itemize/enumerate set at \small or \footnotesize used to pick up LaTeX's size-specific \parsep (3pt plus 2pt, copied into \parskip), so its items sat ~3pt further apart than at normal size and \shrinklists{1} often gained nothing; the new \gothamNoListParsep removes that extra space in every list. (2) Slide editor: a "Previous versions..." dropdown in the toolbar of a current slide lists its frozen versions (newest first) and opens the chosen one in its own tab; a frozen version opens read-only (Preview and Render to PDF show that version) until "Unlock editing" is clicked. (3) Insert command offers \shrinklists{1} (change the 1 to 2 for the stronger step).

BREAKING: every slide with a level-1 list at \small/\footnotesize (a manual size switch, \shrinklists, or a smaller block font) now has tighter item gaps than before -- typically ~3pt less per item. Slides tuned by hand around the old gaps (\vspace, \itemsep, a smaller font chosen only to make room) may now have unused space at the bottom and can be simplified; no slide gets taller.

v5.2.0 (2026-10-01, direct instructions): LaTeX framework. (1) \gothamTikzword{name}{text}: a word as a named TikZ node, so an overlay arrow can point at the word and follows it when the layout moves (3ac's arrow at measured page coordinates had drifted off its words). (2) \sectionfigure[keys]{image} for sectionframe: the image fills the gap from the title bar to the footer, flush with the right edge, and the frame's footnotes -- the image source included -- go into the rotated strip beside it (bij's image overlapped the title bar and covered its own source line; neb, u97, tyn and vtm did the same by hand with per-title measurements). The bar's bottom edge is computed from the title's depth (89.44bp minus it, at most 85.04bp, measured). (3) Footnotes inside a minipage or column now join the frame's other footnotes at the bottom (beamer's [frame] footnotes are the default; mje, zv4). (4) Transcripts: \gothamTikzmark{name} no longer leaves its name behind as a word, \gothamTikzword keeps its text.

BREAKING: a \footnote{} or \source{} inside a minipage/column used to be set right below that minipage with its own marker sequence; it now sits with the frame's other footnotes at the bottom and continues their markers (in this project: mje, zv4).

v5.3.0 (2026-10-01, direct instructions): (1) Every \gotham... name this project created is now \SM... (\SMContentTopAlign, \ifSMInstructorVersion, \SMBulletEllipsis, the TikZ style SMImageBorder, ...): framework, institution preambles, Lua, SlideMage's own code, the demo project and every slide including frozen versions. The vendored Gotham theme keeps its names (\gothamset, \gothamFrametitleLeftpading, ...), and so do the environments (gothamtable, gothamfloatinginfoblock, ...). New module slidemage.sm_rename does the rename; `python -m slidemage.sm_rename <project folder>` applies it to another project. (2) \cornerfigure[height=5cm, border]{media/x.png}: with width= or height= the argument is an image file, the other size follows from its aspect ratio; `border` adds the yellow image border; corner=e|w puts it on the Right/Left Margin, centred between Top and Bottom Margin. besidefigure takes the same keys and measures the figure itself (no width argument). (3) A bordered node (SMImageBorder) has its anchors on the border's outer edge, so the border -- not the stroke's centre line -- lands on a margin; \cornerfigure's node has no inner/outer sep, so an unbordered image's own edge does. (4) Transcripts: \setbeamertemplate/\setbeamerfont/\setbeamercolor no longer leave their names behind, \item[label] keeps its label, \ldots is an ellipsis.

BREAKING: (a) the \gotham... -> \SM... rename: a project or deck that uses this framework's own commands under their old names stops compiling -- run `python -m slidemage.sm_rename <project folder>` once (it rewrites slides, decks, preambles and .slidemage settings; the Gotham theme's own names are left alone). Old .top/.ovl files in a build folder are still read without errors. (b) \cornerfigure content without a border sits 0.2pt closer to its corner (its node has no outer sep any more); a bordered node keeps TikZ's outer sep of half its line width even where \cornerfigure sets outer sep=0pt, so its border's outer edge is on the margin. A slide that writes outer sep=0pt after SMImageBorder still opts out (needed where the node's corners are a coordinate frame for highlights). (c) besidefigure's arguments changed from {width}{figure} to [keys]{image file or content}.

v5.4.0 (2026-10-01, direct instruction): \SMLineTop -- a zero-width strut as tall as a text line's line box (0.935em, the box the Top Margin is measured on). At the start of the first line of a text column beside a figure in top-aligned minipages ([t] plus \vspace{0pt}) it makes the text and the figure start on the same line, so the automatic Top Margin puts both on it (m2k: its minipages were vertically centred, LaTeX's default, and the text started 12pt below the Top Margin).

v5.4.1 (2026-10-03, direct instruction): a compile run with several jobs now goes version by version, then deck by deck (compiler.order_jobs()): Presenter, Instructor, During-course, After-course, After-course per chapter; within each version the deck table's groups in order -- work decks, course decks, research presentations, test decks -- and decks of one group in table order. Selecting During-course and Presenter for #workdeck and IA2 compiles #workdeck Presenter, IA2 Presenter, #workdeck During-course, IA2 During-course. Before, it went deck by deck (all of one deck's versions, then the next deck).

v5.4.2 (2026-10-03, direct instruction): main window stays left-aligned. In a window wider than the deck table needs, the extra width goes to the right: the version checkboxes (Instructor ... Presenter) keep their place instead of being spread over the window, the Create PDF / Stop / Create Transcript / ? / Clear selection / Refresh decks buttons sit next to each other on the left, and so do the three checkboxes under the tabs (footer timestamp, appendix TOC, auto-open) -- less mouse travel.

v5.4.3 (2026-10-03, direct instruction): "Clear selection" on the main screen also clears the pass/fail marks of earlier compiles (✓, ✗, →) next to the checkboxes, in every row of that table. A job that is still running keeps its animated dots until it ends.

v5.5.0 (2026-10-03, direct instruction): "Generate appendix TOC" now also works for the student versions: every whole-deck compile -- Presenter, Instructor, During-course and After-course -- gets the generated appendix (agenda plus thumbnail grids) and the `-appendix` file-name suffix; each lists the slides its own version shows (\conditionalslide/\slidestep conditions), and the logo on every slide links to its agenda. Per-chapter compiles stay without one. The appendix is appended after the deck's last slide, so it already follows a deck's own appendix slides (a \section{Appendix}) -- verified on #workdeck, where the deck's appendix slide comes first and the generated agenda and grids after it. Before, During-course/After-course compiles ignored the checkbox.

v5.5.1 (2026-10-03, direct instruction): the "-appendix" ending of PDF names is gone: a compile with "Generate appendix TOC" ticked writes the same file as one without (<deck>-instructor.pdf, <deck>-during-course.pdf, ... and -presenter), replacing it. PDFs named *-appendix.pdf left in pdf/ by earlier versions are no longer touched or offered by "Open pdf"; delete them by hand.

v5.5.2 (2026-10-03, direct instruction): "Clear selection" while a compile is running clears only the checkboxes -- the animated dots and the pass/fail marks of the run stay. A click after the run has finished clears the marks too (v5.4.3 cleared them at once, running jobs excepted).

v5.5.3 (2026-10-03, direct instruction): the status line by "Log:" counts compiles, not decks: ten deck versions of four decks read "Deck 1/10" ... "Deck 10/10" (each version is a compile of its own), not "Deck 2/4".

v5.6.0 (2026-10-03, direct instruction): \SMCashCycleBars and \SMCircularFlowDiagram are no longer part of the framework. They draw two specific finance-course diagrams (an operating/cash conversion cycle bar chart, a cash -> raw materials -> finished goods -> receivables circle), which is course content, not a framework feature; they now live in the content project that uses them (SlideMaster_SP's Slidemaster_project_macros.tex, loaded by its institution preambles). Its five slides render pixel-identically.

BREAKING: a project whose slides use \SMCashCycleBars or \SMCircularFlowDiagram stops compiling ("Undefined control sequence") until it defines them itself -- copy both \newcommand blocks from SlideMage v5.5.3's latex/Slidemaster_preamble_base.tex into a file of the project and \input it from each institution preamble after \input{Slidemaster_preamble_base}.

v5.7.0 (2026-10-03, direct instruction): a generic SlideMage template, example/Slidemaster_preamble_slidemage.tex, for decks that don't belong to an institution -- the SlideMage logo (the app icon as a vector PDF, example/schemes/scheme_slidemage/), title and footer boxes in the splash screen's dark gray #1e1e1e with white text, the app's button blue #0066cc as highlight colour instead of Uni Graz yellow, and the app's other colours as the c_* palette (block titles, info blocks, link underlines, ...; every colour pair the framework combines checked against WCAG 2.1). It ships with the app as part of the example project new projects are created from; a deck selects it with \input{Slidemaster_preamble_slidemage}. SlideMage recognises it like the institution templates: previews are stored under the template name "SlideMage", and Update previews builds them with this template.

v5.8.0 (2026-10-03, direct instruction): a default template for slides rendered outside a deck -- Settings -> General -> Slide rendering -> "Default template", listing the templates whose Slidemaster_preamble_<name>.tex the project has, saved immediately in .slidemage/app_settings.json ("default_template"). The slide editor's "Render to PDF" and "Preview" (including its cached preview image), and tikz illustration renders use it; before, they always used the Uni Graz template. Out of the box it is the SlideMage template; a project that doesn't have the chosen template falls back to SlideMage, then Graz, then whichever template it has (so SlideMaster_SP, which has no SlideMage template, keeps rendering in Graz). Renders from a deck editor row keep using that deck's own template. (slide_snapshot.render_template(), slide_preview.default_preamble()/template_preamble().)

v5.9.0 (2026-10-03, direct instruction): the SlideMage template is part of the framework now, not of the example project: latex/Slidemaster_preamble_slidemage.tex with its logo latex/slidemage-logo.pdf (+ .svg source), found on the same TeX search path as Slidemaster_preamble_base.tex. Every project next to the framework can use it without a copy of its own -- e.g. SlideMaster_SP, which has only institution layers, can now select it in a deck (\input{Slidemaster_preamble_slidemage}) and in Settings -> General -> Slide rendering, which lists the project's own templates plus the framework's (slide_snapshot.framework_dirs(): $SLIDEMASTER_LATEX, ../latex, ../SlideMage/latex). A project's own Slidemaster_preamble_slidemage.tex would still win. Since the SlideMage template is now available everywhere, single-slide renders use it out of the box in every project, unless another default template is chosen there.

v5.10.0 (2026-10-04, direct instruction): regular slide ids start with a letter. Every newly minted id (Add slide, Duplicate slide, Admin slides, PPTX/ODP import) now has a letter first (slide_ids.ID_FIRST_ALPHABET); ids starting with a digit are reserved for the SlideMage manual (1 + letter + one more character) and the demo slides (2 + letter + one more character), minted with slide_ids.mint_slide_id(reserved="1"/"2") and checked by slide_ids.reserved_id_reason(); slide_ids.regular_id_reason() is illegal_id_reason() plus the letter-first rule. Minting and slide_rename.rename_slide_id() now compare ids without regard to case (Windows can't tell "zzh-..." from "ZZH-..." apart). rename_slide_id() refuses a digit-first new id unless reserved=True, and also renames the slide's cached previews (.previews/slide_previews/<old>-*.png), so they need no re-render. Existing digit-first ids keep working everywhere; they are just no longer handed out (SlideMaster_SP's 217 were renamed with rename_slide_id()).

v5.11.0 (2026-10-04, SlideMage manual, build step 1): \SMCodeFile[listings keys]{path} shows LaTeX source on a slide, read from a small file at the project root (snippets/<slide id>-<n>.tex), so the slide needs no [fragile] frame. Framework (Slidemaster_preamble_base.tex): listings loaded; style SMCode -- Fira Mono Regular (\SMCodeFont; the theme's \ttfamily is Fira Mono Bold) at \SMCodeSize (6.6/8.2pt), every control sequence backslash included in c_primary_highlight (backslash as letter + keyword prefix), comments c_primary_gray, c_tertiary_gray panel; \% and \\ mapped so neither starts a comment nor colours the next word; umlauts, dashes, middle dot, ellipsis and arrow mapped. Keys go to \lstinputlisting (firstline/lastline/basicstyle...). Transcript: the file becomes a fenced ```latex block (firstline/lastline honoured, tabs as two spaces), and the HTML transcript renders fenced blocks as <pre><code>. Pre-render check: new error "code-file" for a missing file; \SMCodeFile's path is a non-typeset argument for the underscore check. Reserved ids (manual/demo) never have "e" in second place.

v5.12.0 (2026-10-04, SlideMage manual, build step 1b): visible navigation for readers, opt-in per deck. Framework: \SMNavigationBar[deck,chapter,previews] (deck preamble) extends the footer's left text to "\FooterText | Navigation: <three links>" -- the \SMDeckAgenda contents slide, the current chapter's \SMChapterAgenda (fallback: the contents slide), and the generated appendix agenda (only when the compile has it) -- white/footer-coloured text with the blue \href underline (\SMLinkUnderline); a link without a target in this PDF is left out. \SMChapterAgenda[width] lists the slides of the current \section in two columns as links, from what the previous pass recorded in the .aux: \setSlideID writes \SMAgendaSlide{section}{id}{slug label}, the frametitle hook writes the frame title (\SMAgendaEntryTitle), \SMAgendaTitle{text} names a title-less slide; \small, \footnotesize when it does not fit \SMChapterAgendaMaxHeight; a \slidestep slide once, the agenda's own slide not at all. \deckappendixtoc is inert for LaTeX. Every deck now writes those agenda lines to its .aux (no visible change; demo decks pixel-compared against v5.10.0: identical apart from sub-0.01pt bullet rounding on one slide that already came with v5.11.0). App: deck_scan reads \deckappendixtoc (Deck.appendix_toc) and the compile batch generates the appendix for such a deck whatever the toolbar checkbox says. Transcript: DeckSlide.chapter (number of \section{}s before it); \SMChapterAgenda becomes "This chapter's slides:" with each slide's title and number (German strings for German decks), \SMDeckAgenda disappears, \SMAgendaTitle names a title-less slide. alt_blocks._slide_title()'s filename fallback drops the language segment ("Quote Demo", not "EN Quote Demo").

v5.13.0 (2026-10-04, SlideMage manual, found while building it): \SMCode{text} and \SMCmd{name} set code in running text in Fira Mono Regular at 90% (\texttt is the theme's Fira Mono Bold, which reads heavy and wide next to the Fira Sans Light body text and made the manual's slides overflow); \SMCmd{slide} prints \slide. Transcript: both become `code`, and a literal backslash survives -- \textbackslash and \SMCmd's backslash are parked while the inline conversion strips macro names and put back afterwards (before, \texttt{\textbackslash pause} came out as `pause`). \SMChapterAgenda now tries \normalsize first, then \small, then \footnotesize (it left the dividers mostly empty at \small).

v5.13.1 (2026-10-04, found in the SlideMage manual's transcript): a \\ line break in running text becomes a space -- the macro strip used to take "\SlideMage" out of "...\\SlideMage" and leave a stray backslash ("demonstration\ 5.12" on a title slide); \textperiodcentered becomes a middle dot instead of disappearing.

v5.13.2 (2026-10-04, found in the SlideMage manual): the generated appendix's footer no longer shows the last real slide's version and language next to "appendix" (appendix_toc resets \ifSMSlideVersionSet/\ifSMSlideLanguageSet with the slide id); a thumbnail cell without a cached preview labels the slide by its slug without the language segment.

v5.13.3 (2026-10-04, found in the SlideMage manual): images placed with the v5.x figure helpers -- \cornerfigure[width/height]{file}, besidefigure, \fitfigure, \sectionfigure -- are now seen by the image scan (alt_blocks.referenced_images(): the Images tab's slide list, `used_on`, takeaways, transcripts) and by the pre-render check's "image" rule. Before, an image placed only that way had no slide in its `used_on`. An argument containing a backslash is content (a block, an \includegraphics), not a file.

v5.14.0 (2026-10-04, found in the SlideMage manual's transcript): transcripts read the constructs a v5 slide uses. Inline code (\SMCode, \SMCmd, \texttt) is verbatim -- escaped braces, \textbackslash, "--" and "gap=12pt" survive, and adjacent spans join (`\input{...}`). Maths: arrows, Greek letters and common symbols become characters, \frac{a}{b} becomes a/b, \SMUnderbrace{x}{label} becomes "x [label]". A \tableofcontents lists the deck's chapters with their first slide numbers. A slide's own \providecommand/\newcommand macros are expanded. tikzillustration bodies are left to their description; figure-helper paths, \shrinklists, \fontsize, \setcounter, \ifnum...\fi, overlay specifications and \hyperlink targets no longer leak as text; \progressstrip, \SMWarningSign, \quotesource, referenceblock, sideimageframe and \begin{frame}[standout] are rendered; a table inside a table cell and "\\[1pt]" row ends no longer break a table. Framework: \SMCode/\SMCmd's font no longer applies TeX ligatures, so "--project" prints as typed.

v5.14.1 (2026-10-04, found by the layout check on the SlideMage manual): two framework layout fixes, and the layout check moves here. \SMCodeFile's panel is a \colorbox around the listing instead of listings' own frame, which was drawn 4-8pt above the box it occupied, so a code panel stuck out over the Top Margin. In columns[T] a list at the top of a column now starts on the column's top, like one at the top of a minipage: a smaller list (\shrinklists, \small) used to keep \@listi's 4pt \topsep and start below a figure beside it -- Slidemaster slides with such a list at the top of a [T] column move up by that much, onto the Top Margin. tools/check_layout.py (from the Slidemaster project's .scripts/) works on any project (--project, or the folder with slide_ids.csv above the PDF); frames around code panels and pictures are no longer reported as table rules, and a slide with a \progressstrip is not held to the Top Margin.

v5.14.2 (2026-10-04, direct report): "Archive unused content" finds everything in one run. Images were judged against every slide file, including the slides archived in the same run, so an image only such a slide used survived until the next click (screenshot-jcr-science-journal-profile-2023.png, used only by the archived uwj). Now only slides that stay in use keep their images -- this includes frozen versions no deck pins, which are archived anyway.

v5.15.0 (2026-10-04, direct instruction): the compile progress label counts the passes a deck really needs. Every compile counts its LaTeX passes and remembers them per deck and job kind (instructor, during-course, after-course, presenter, per-chapter) in the project's .slidemage/compile_passes.json; the next compile of that deck shows "pass 3/6" instead of the fixed guess of 4 (3 without a bibliography), which stays for a deck compiled for the first time. Every SlideMage compile starts in a fresh build folder, so a deck's count only changes with its content. Not stored in the deck file: a compile writing into the deck would make an open deck editor refuse its next edit as "changed on disk".

v5.15.1 (2026-10-04, direct instruction: "the visible edge counts"): tools/check_layout.py measures the Right Margin as the logo's visible right edge on the rendered page. It used the PDF's drawing list, which skipped a white shape with a dark outline (the SlideMage logo's front card) and a small text mark (MCI's "®"), and so put the margin 2.4pt (SlideMage) to 12.7pt (MCI) too far left. Measured right, every template's logo ends on the framework's own Right Margin, so nothing changes in the framework.

v5.16.0 (2026-10-04, SlideMage manual plan, step 7): the SlideMage manual (decks/slidemage-manual.tex) is example/'s demo deck. The demo decks test.tex, test-student.tex, test-slides.tex and test-slidemage.tex and the sixteen ZZ* demo slides the manual replaces (ZZL included: a two-level subset of ZZO) are retired from example/ (their ids stay registered); the reference sheets in the manual's appendix and the empty slide get reserved demo ids: ZZU -> 2rg (footnote symbols), ZZO -> 2v9 (itemize spacing), ZZI -> 2p8 (empty slide). "Open Project..." on an empty folder therefore seeds a new project with the manual. CI compiles the manual (instructor and during-course; a clean build needs 6 passes, so latexmk runs with $max_repeat=10). README and docs point at the manual's slides. The Slidemaster project's own test decks and ZZ* copies are untouched.

v5.16.1 (2026-10-05, direct instruction): the compile progress label says "(estimated)" after the pass count while it is a guess -- a deck never compiled before (4 passes, 3 without a bibliography), a single-slide render, Update previews -- e.g. "pass 2/4 (estimated), slide 12/40"; once a deck has been compiled, its remembered count shows without it.

v5.17.0 (2026-10-05, direct instruction): readable code panels. \SMCodeFile's three colours are named colours a template can set before \input{Slidemaster_preamble_base}: SMCodeKeywordColor (control sequences), SMCodeCommentColor (% comments), SMCodeBackgroundColor (the panel). Without them a template keeps the old look -- highlight colour, c_primary_gray, c_tertiary_gray -- which with a yellow or orange highlight colour was about 1.1-1.3:1 contrast. The SlideMage template now sets #0066cc / #5f5f5f on #f0f0f0 (4.9:1 and 5.6:1; was 4.4:1 and 4.0:1), example's Uni Graz template a darkened Graz blue #1f5c99 and #5f5f5f on its tertiary gray (5.4:1, 5.0:1). Only pages with a code panel change. Projects with their own templates set the three colours there (SlideMaster_SP: Graz, MCI, Innsbruck done).

v5.18.0 (2026-10-05, direct instruction): the SlideMage manual has a deck group of its own. Tag `manual` (decks/slidemage-manual.tex now carries \decktags{manual}, was test): a "SlideMage manual" section at the bottom of the deck table; it wins over any other group tag; it is never offered in the Tags or Duplicate dialogs (a copy of the manual starts out as a course deck), and the manual's Tags button is disabled, so it always stays in its section. Unlike a test deck, its name is a link to the deck editor again. Compile runs take it after the test decks.

v5.19.0 (2026-10-05, direct instruction): a project's copies of the framework and of the SlideMage manual follow app updates. A new project records a hash of every file it got from SlideMage (.slidemage/bundled_copies.json -- commit it). On start, when this SlideMage carries newer versions, an info dialog offers the update (Update / Not now / Don't ask again for this version); it then replaces the files changed only upstream, adds new ones, removes the ones no longer shipped, backing up everything it replaces or removes in .slidemage/backups/<time>/ first. Files changed in the project are kept and listed; files deleted there stay deleted; the manual's new slide ids go into slide_ids.csv, its image descriptions into media/alt-text.json (unreviewed descriptions of replaced images are refreshed). Older projects: a sibling latex/ that isn't part of a git checkout is adopted (every file that differs from this version is replaced, after the backup); a git checkout is never touched. A project without the manual is offered to add it -- only missing files are added. (bundled_copies.py; project.init_project() writes the baseline.)

v5.19.1 (2026-10-05, direct instruction): the "Test decks" section sorts below the "SlideMage manual" section in the deck table (work, course, research, manual, test), and compile runs follow the same order.

v5.20.0 (2026-10-05, direct instructions): compile pass counts. (1) A compile that needs more passes than expected raises the count in the progress label -- "pass 5/5" -- instead of "pass 4/4 (extra pass 5)"; the bar never moves backwards. (2) A deck's presenter and instructor compiles share their remembered count (they need the same passes: same content, the presenter layout only adds the notes panel -- measured equal on every SlideMaster deck), so a presenter compile shows the right count after an instructor compile and vice versa, without "(estimated)". A student version without a count of its own borrows the nearest one -- the other student version, else instructor/presenter -- and a per-chapter compile its version's whole-deck count, both still marked "(estimated)" (a student version can need a pass more or less: fewer slides, "final state only" slides). (compile_passes.predict().)

v5.20.1 (2026-10-05, found when the user's update dialog listed them): the manual's copy carried a developer's slides/.backups (the slide editor's undo history) into users' projects. The exe now bundles the example project file by file without slides/.backups, build output (.build, .previews, pdf, compiled decks) and machine-local settings (.slidemage/app_settings.json, project.json, compile_passes.json, bundled_copies.json); the copy and the update check skip every hidden folder; a new project never gets .backups. A project that already received them gets them removed by the next manual update (backed up first, as always).

v5.21.0 (2026-10-05, direct instructions): (1) A duplicated deck starts with the remembered compile pass counts of its original (compile_passes.copy_counts), so its first compile already shows "pass 3/5"; an original never compiled passes nothing on. (2) Manual: the installation slides are back in chapter 2 (the divider, 1f8, lists them; Appendix A and its divider are gone, the reference appendix is just "Appendix: Reference"). (3) Manual: the footer labels on slide 1nt ("Inside a slide file, and its footer") follow the footer when the compile timestamp is off -- the arrows move with the id block, the "compiled" arrow is dropped, the labels end at their arrows --; the "navigation links" arrow is gone from that slide (any deck can have them: \SMNavigationBar in its preamble, not a manual-only feature).

v5.22.0 (2026-10-05, direct instruction): a frozen version opened from "Previous versions" has a button "Make this the current version" (slide_versioning.restore_version): the slide's current content is archived first as a frozen version of its own (under its own tracked version, as a Save would), the frozen content becomes current with a new version number -- the highest known one with the minor number bumped, never reused -- and the current header ("Included in decks") is kept. Refused if the slide already has that content, or if the archive name is taken by different content, or if the current slide's tab has unsaved changes. Manual slide 1nt points at the navigation links again (any deck can have them).

v5.23.0 (2026-10-05, direct instruction): saving a new version of a slide that is used in more than one deck, is pinned in a deck, or has a translation first shows "Where this slide is used" (slide_usage.py, qt_slide_usage_dialog.py). Per deck: "Move to current" (the default; a pinned \slideversion / \omitslideversion becomes \slide / \omitslide, a call that follows -current already moves on) or "Keep vX.Y.Z" (the call is pinned to the version just frozen; a deck pinned already can "Stay on" its version). \slidefinal, \conditionalslide and \slidestep have no pinned form and always follow -current. The slide's translation partners (from its "Translation of" / "<LANG> translation" header comment) are named with their decks, with a tick box to open the translation after the save. Cancel cancels the save. The deck edits run after the slide is written, through the deck editor's own stale-checked rewrite, and open deck editors refresh. Not shown for "Overwrite" (no new version).

v5.24.0 (2026-10-05, direct instruction): \multilingualtext has a keyed form for any number of languages: \multilingualtext*{EN={Hello}, DE={Hallo}, FR={Bonjour}} typesets the pair whose key is the deck's \decklanguage code (upper or lower case); a deck in a language the list lacks gets the EN text, else the first. The two-argument form \multilingualtext{EN}{DE} is unchanged (and no longer a plain 
ewcommand but an expl3 NewDocumentCommand with the same behavior). \decklanguage[fr] (any code) now also sets the PDF /Lang to that code instead of en-US. Not yet language-aware beyond en/de: \ifSMGerman and the "Image source(s)" label.

v5.25.0 (2026-10-05, direct instruction): the project SlideMage opens by itself is now also remembered beside the exe (file "last_project" in the exe's folder, written whenever a project is opened). The pointer in %APPDATA% belongs to one computer, so a second PC running the same cloud-synced exe asked for the project again; it now finds it from the copy beside the exe. When the remembered project no longer exists the folder picker starts in its nearest existing parent folder instead of the program folder.

v5.26.0 (2026-10-05, direct instruction): the "Course link..." button of the deck table is now "Settings" (on every deck row, also for work, research and test decks; disabled for the SlideMage manual) and opens a dialog with the deck-wide settings that live in the deck file: template, language, footer text, course link (with Open), where the PDFs go (all outputs, each version, presenter, transcript, with Browse) and the always-add-appendix flag. All changes are written in one stale-checked write; only what was changed is touched, comments and line endings stay. New modules deck_settings.py (text in, text out) and qt_deck_settings_dialog.py replace qt_course_link_dialog.py; deck_editor.course_url_text() is the text part of set_course_url().

v5.27.0 (2026-10-05, direct instructions): (1) New \SMLink{target}{text}: a link in running text, underlined like an \href (a bare \hyperlink has no underline); the manual's text links use it. (2) besidefigure lowers its figure by \SMBesideFigureTopGap (0.2em) so its top edge meets the top of the first line's letters instead of the line box; this moves every besidefigure figure down by about 2 pt (yshift=0pt restores the old position). (3) Fix: the manual and framework update (bundled_copies.py) no longer treats SlideMage's own '%% Included in decks:' line as a user edit -- 38 of 56 manual slides of a real project were 'kept' only because of it and could never be updated; an update keeps the project's own line. (4) tools/manual/adopt_user_edits.py brings edits made in a project's copy of the manual back into example/. (5) The manual: slides 1b6, 1kg, 1ih rewritten and split (new 1b2, 1vd, 1be), the user's edits of the project copy adopted.

v5.27.1 (2026-10-06, direct instruction): every slide of the SlideMage manual carries \setSlideVersion{1-0-0}, so its footer shows a version (51 slides had none: they were written as files and never saved through the slide editor's version dialog). The project's copy was stamped the same way and its update baseline moved with it, so nothing becomes a user change.

v5.28.0 (2026-10-06, direct instruction): \sectionframe: every title bar is now the same height. Before, the bar depended on the title: one without descenders ("Slides", "Decks and deck versions") was 4.15 pt taller than one with them, and the height of the tallest letter shifted it further (the manual's dividers measured 85.04, 85.66, 86.92 and 89.19 bp). The title measurement gets a \strut, the toppading formula a fixed reference depth (\SMSectionframeRefDepth), \SMSectionframeHeightCorrection is recalibrated, and \sectionfigure starts 0.1 bp under the bar. VISIBLE CHANGE in course decks: section slides with a title without descenders (e.g. neb, u97, dvh) get a 4 pt shorter bar, and the body text of every section slide starts 1.5 pt lower than the new bar edge (it used to sit 7.4 pt under it). Manual: dividers 1y9 and 1f8 fixed (1y9 had an empty line above its text, 1f8 listed the agenda before its intro), all intros top-aligned.

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

v5.30.3 (2026-10-06, direct instruction): the slide editor screenshot of manual slide 1b6 is taken in a narrower window (cut off just right of the "Close and save" button, so the buttons are larger on the slide) and a taller one (fills the picture column); tools/manual/make_screenshots.py has SLIDE_EDITOR_HEIGHT and SLIDE_EDITOR_RIGHT_MARGIN for it. 1b6 no longer overflows.

v5.30.4 (2026-10-06, direct instruction): manual slide 1td labels every frame in its full LaTeX form: \titleframe{...}, \quoteframe{...}, \fullbleedframe{...} (commands) and \begin{sectionframe}, \begin{standardframe}, ... \begin{frame}[standout] (environments), instead of a mix of backslash, bare name and brackets.

v5.31.0 (2026-10-06, direct instruction): (1) Rotated footnotes (\sidefootnotes, every sideimageframe) are set in the footnote colour: on the SlideMage template, where the footer text is white, they came out white on white and only the footnote mark showed. (2) The rotated footnote beside a sideimageframe picture sits 1pt closer (2.1pt instead of 3.1pt from the picture; the ink of the nearest line is now 2.9pt away, as the bottom footnotes are from the footer). (3) A frame with a \progressstrip is placed by the automatic Top Margin like any other, with the strip's height added: its first line now sits the usual 16pt below the strip, whatever the body starts with (a paragraph was 10pt below, a list 14pt). Slides with a strip move down 0-6pt; the new length \SMProgressStripHeight is the strip's height (Slidemaster_layout.lua: gotham_layout.top_extra). Manual: slide 1sv is split in two, the new slide 1w4 shows numbered and lettered lists; 1vh, 1j2 and 1b6 are adjusted; the user's edits of 1b6, 1gr, 1ih, 1j2, 1wa, 1x6 and 1y3 are adopted.

v5.31.1 (2026-10-07, direct instructions; manual content only): (1) Slide 1nz's reference (a footnote with fullcite) uses the house format of the author's university decks -- Markowitz, H., 1952. "Portfolio Selection", Journal of Finance 7(1), 77-91. -- the manual deck now carries the same biblatex set-up (authoryear with the book, article, online and report drivers). (2) Slide 1dk (Plain beamer reveals) is split in two: 1dk explains the four plain commands in full sentences, the new slide 1un (Other overlay commands, and two traps) covers uncover, visible, only, alt, onslide and the two traps; 1dk is version 1.1.0, 1.0.0 frozen. (3) Slide 1mu: the closing note stays to the right of the code snippet (a two-column layout), version 1.0.3. (4) The user's edit of slide 1u4 (1.1.0) adopted. The manual has 73 slides.

v5.32.0 (2026-10-07, direct instruction): the citation format is the template's job, not each deck's. New framework command SMUseBibliography[file.bib] (Slidemaster_preamble_base.tex): in a deck's preamble it loads biblatex with SMBiblatexOptions, registers Slidemaster.bib (or the given file; the biber-safe lookup that every deck used to copy) and applies SMBibliographyStyle. Defaults: biblatex's stock authoryear. The Uni Graz preamble and the SlideMage template (latex/Slidemaster_preamble_slidemage.tex, and the example project's Graz preamble) now define the house format -- Markowitz, H., 1952. "Portfolio Selection", Journal of Finance 7(1), 77-91., with the book, article, online and report drivers -- by redefining SMBiblatexOptions and SMBibliographyStyle; a deck wanting its own format redefines them before the call, or loads biblatex itself as before. The manual deck and every Uni Graz course deck of the SlideMaster project now consist of the one line SMUseBibliography instead of 90 copied lines (FM2's compiled text was checked identical, page by page). Not breaking: decks that load biblatex themselves keep working. The manual has no changed slides; 1nz shows the same reference.

v5.32.1 (2026-10-07, direct instruction; the first real migration of the compatibility check): the move of the citation format into the templates (v5.32.0) is registered in compat.py as the change "bibliography-in-template" (severity LAYOUT: it opens the dialog on start). Its detector finds the decks that carry an unmodified copy of the house format (code line for line, comments ignored); Update project replaces the copy in each such deck by SMUseBibliography and, for a template file of the project that does not define the format yet, inserts the block after its input of the base preamble (and the project macros). Decks with a variant of the format, and decks whose template defines another format, are left as they are; nothing is changed while the framework next to the project lacks SMUseBibliography. Implementation: compat_bibliography.py, the format as data in bibliography_house.py (the templates must carry exactly that block -- tested), compat_types.py (Change and Finding moved out of compat.py so that an entry module can import them without a cycle). Tried on a copy of SlideMaster's decks before the move: 8 decks and the Graz template migrated, identical to the hand conversion; the older #workdeck variant was left alone.

v5.32.2 (2026-10-07, direct question; manual content only): slide 1d7 (quick reference, deck commands) said the [v] argument takes the three deck versions everywhere. For deckoutputfolder it also takes presenter and transcript (the presenter PDF is the instructor version with notes, so slide conditions -- conditionalslide, slidestep -- need no extra value); the slide says so now. Version 1.0.1, 1.0.0 frozen.

v5.32.3 (2026-10-07, direct instruction; manual content only): the user's edit of slide 1x7 (Linking and navigating, version 1.1.1; the earlier 1.1.0 frozen) adopted into the bundled manual. The release collects everything since v5.4.0.

v5.33.0 (2026-10-07, direct instructions; design in docs/DECK_SNAPSHOT_PLAN.md): deck snapshots -- a self-contained copy of a deck that compiles exactly as the deck does today, whatever later changes in the project, the framework or SlideMage. New menu Decks, after System, with "Create deck snapshot..." and "Import PPTX/ODP..." (moved there from System). The dialog takes one or more decks (snapshotted one after the other on the compile slot; one failure doesn't stop the rest, Stop skips the remaining ones), folder or .zip, and whether the LaTeX package files and the SlideMage app go in; the settings are remembered. Snapshots go to <project>/snapshots/<deck>_<YYYY-MM-DD>_<HH-MM> (or .zip), any number per deck; when the selected decks already have snapshots, SlideMage asks once whether to delete them (to the Recycle Bin, each only after its deck's new snapshot was made and checked); snapshots/ is added to the project's .gitignore. Archiving a deck asks "Snapshot, then archive" / "Archive only" / Cancel -- the deck is archived once the snapshot is done, or after a second yes if it failed. How: every version of the deck and the presenter PDF are compiled with latexmk's -recorder (SOURCE_DATE_EPOCH fixed); everything they read is copied at the same relative paths (project files; the framework whole, at its position next to the project, so the project's own .latexmkrc finds it), the TeX distribution's files and the embedded fonts are recorded with version and hash (and copied into texmf/ when asked), the footer timestamps are kept, and wrappers plus render.bat/render.sh reproduce each version. Then the snapshot is rendered from its own folder: every file read must lie inside it (or the TeX distribution) and every page must equal the reference PDF, otherwise it is discarded with the reason in the log (a failed biber run fails the reference compile). A snapshot's project folder opened in SlideMage shows a banner, is never changed by the app itself (no compatibility migrations, no framework or manual updates, no project.json bookkeeping) and compiles with its own framework, dates and timestamps into its own pdf/. Command line: python -m slidemage.deck_snapshot create/verify/list. Manual: new slide 1nu (Deck snapshots); 1kp mentions the snapshot offered on archiving (1.2.0, 1.1.1 frozen); 1r8 names the Decks menu for the import (1.1.1, 1.1.0 frozen).

v5.34.0 (2026-10-08, direct instruction: avoid re-creating PDFs that are already current): a deck snapshot reuses a version's last PDF when nothing that compile read has changed. After every successful whole-deck compile SlideMage keeps a record in .build/compile-records/<jobname>.json (compile_records.py): the SHA-256 of every file the compile read (latexmk's -recorder list, now passed explicitly, plus the .bib files biber read), of the wrapper (version, presenter, footer timestamp and appendix settings), the TeX engine's version, the footer timestamp, the start time and the published PDF's path and hash. A snapshot checks each version against its record; when everything matches and the PDF is unchanged where it was published, that PDF becomes the snapshot's reference and the version isn't compiled again (the log says which versions were reused and why the others are compiled). The verification render from the snapshot itself still runs, so a fully current deck takes about half the time. Not recorded: a compile during which one of its files changed, and one whose bibliography wasn't built; luaotfload's font caches are left out of the hashes. Each version now carries its own SOURCE_DATE_EPOCH in snapshot.json and in render.bat/render.sh (a reused PDF's is its compile's start). Command line: --recompile compiles every version regardless. "Remove temp files" keeps the records (direct instruction: small, worth keeping). The same records stop needless compiles from the deck table (direct instruction): when a checked version hasn't changed since its last compile and that PDF is still where this compile would put it, SlideMage asks first -- Compile anyway / Skip unchanged (default) / Cancel. The slide previews a generated appendix shows are copied into the record as the compile read them and not compared (they are refreshed after every instructor compile, and a slide showing a time never renders the same twice); a snapshot that reuses a PDF takes those copies. Snapshots now also contain the previews a generated appendix shows (they were left out, and the appendix pointed at the project's own .previews by absolute path -- a snapshot of such a deck would have failed its check once previews existed); the wrapper stored in a snapshot uses project-relative paths, and each version gets its own copy of them (.previews/<jobname>/: a version compiled before an instructor compile refreshed them shows different thumbnails than one compiled after). Page compiles (direct instruction: "compile individual pages or page ranges ... retaining the page numbers the slides would have in the full deck ... Ideally ... replacing these slides in the full deck"): a deck row's new Pages field ("4, 5, 7-10, 15" -- the numbers in the slide footers) makes the checked versions and the presenter PDF compile only those slides (a slide always whole, with all its reveal steps), numbered as in the whole deck, on top of the version's last whole-deck compile (its PDF tells which slide each number is, its kept auxiliary files give contents, agendas, citations and links): the deck without the other slide calls, the frame and page counters set before each kept slide, two single passes with the full deck's auxiliary files restored in between (keeping the new layout corrections and tikz positions). With the new toolbar option "Pages replace theirs in the full PDF" (on, remembered) the new pages are drawn onto the old pages of that PDF -- the page objects stay, so bookmarks and links into them keep working; the new pages' links are re-targeted -- and the record moves to the patched PDF, so more page compiles can follow (a snapshot or the "nothing changed" check then sees the PDF as no longer matching a whole-deck compile). A slide whose number of pages changed can't be swapped in place: its pages go to "<pdf>-pages-<numbers>.pdf" and the log says to compile the whole deck. Refused (compile the whole deck): no whole-deck compile on record, the deck file changed since (slides added, moved or removed shift every number after them), the PDF changed. The log lists slides that changed since the whole-deck compile but weren't asked for. Not updated by a page compile: other pages showing something of the changed slides (a new title in the contents, an appendix thumbnail). Every PDF of one click on Create PDF carries the moment of that click in its PDF info dictionary (/SlideMageRun, a line of the compile wrapper -- left out of the compile record's wrapper hash); a page compile that swaps pages in stamps its own. "Open pdf" opens the deck's usual PDF -- the instructor version, or the one chosen in the deck's Settings ("Open pdf opens", a new deck setting stored as "%% SlideMage open PDF: <version>" in the preamble, a comment like the course link, so older frameworks still compile the deck) -- unless a newer PDF of the deck comes from a later click or has no stamp: then it asks which one, newest first (direct instructions). Manual: slide 1nu mentions the reuse (1.0.1, 1.0.0 frozen).

v5.35.0 (2026-10-08, direct instructions): page compiles accept a deck file that changed after the slides they compile ("If a deck only contains changes after the slide that is to be inserted, it could still compile and replace"): the compile record keeps a copy of the deck file as compiled, and a page compile is refused only when the deck changed in its preamble or before the end of the last slide it compiles (a slide added, moved or removed there shifts the numbers); a record from before this version has no copy, so there any change still counts. A page compile also reads the deck file afresh from disk instead of the deck table's possibly older copy. Confirmed with a real compile of the manual (question: "the instructor deck should receive slide 7 in the instructor version and the during-course deck ... in the during-course version"): footer number 65, the \slidestep demo, compiled for both versions in one run, put two pages (both reveal steps) into the instructor PDF and one page into the during-course PDF. Manual: new slide 1tb (Compiling single pages, after 1kg; also mentions the question before compiling an unchanged version); 1kg 1.2.0 (Open pdf follows the deck's setting and asks after a later run; 1.1.0 frozen); 1ub 1.3.0 (the deck table's Pages column, callouts moved; 1.2.0 frozen); all SlideMage screenshots retaken (tools/manual/make_screenshots.py). The manual has 75 slides.

v5.35.1 (2026-10-08, direct report: "After a single-slide compile has finished, the blue progress bar continues to move left to right in 'starting' mode"): the progress bar ends a job on its "MOVING" line, which a page compile never logs (it patches the PDF itself); a job's PASS line now ends it as well, so the bar fills and clears after a page compile like after any other.

v5.35.2 (2026-10-08, direct report: "On 1ub, the image source footnote is moved partially below the footer"): tools/check_layout.py now sees a footnote or image-source line that an overfull frame pushed into or under the footer box (it skipped every small line reaching into the footer, so it could not report it); such a line is told apart from the footer's own text by its size (3.19 pt; footer text is 3.99 pt and up in every template). Manual: 1ub 1.3.1 (item 4 names the deck buttons in two lines instead of three; 1.3.0 frozen) and 1rv 1.2.2 (smaller version crops; its source line was hidden under the footer since v5.30.1; 1.2.1 frozen).

v5.35.3 (2026-10-09, direct report: Update Ollama models failed for four models with "pull model manifest: file does not exist"): those were custom models (built with ollama create from a base model), which have no registry entry of their own. SlideMage knew custom models only from a hand-kept name table that listed some of them, partly under misspelt names; it now pulls every model first and, when the registry says the model does not exist, takes its base from what Ollama records (/api/show details.parent_model), updates that base and rebuilds the custom model on it -- or, if the custom model already uses the base's current weights, leaves it as it is ("already uses the current ..."). Not a custom-model fallback for other pull errors (e.g. Ollama not running). The update confirmation now explains the custom-model case in general instead of naming models from the table.

v5.35.4 (2026-10-09, direct instruction: "describe the releases in a more helpful manner, so GitHub users see in few sentences or bullet points what is new since the previous release"): every history entry from now on has a NEW: paragraph -- a one-sentence summary and "- " bullets for users -- and packaging/release_notes.py builds the GitHub release from those: the tagged version's summary, "This release covers ..." when it bundles several versions, every version's bullets, a "## Breaking changes" section from the BREAKING: paragraphs and a "## Full changelog" link under a heading of its own (release.yml no longer lets GitHub append its own changelog line, which would have landed inside the breaking-changes section the updater reads). A release fails when an entry after v5.35.3 has no NEW: paragraph; older entries keep printing their full text. version.parse_history() gives each entry its summary and bullets (HistoryEntry.summary, .news). The texts of all six releases so far (v4.0.0 to v5.35.3) were rewritten on GitHub the same way.

NEW: Clearer release notes.
- Release notes on GitHub now list in a few bullet points what is new since the previous release, followed by any breaking changes and a link to the full list of changes.

v5.35.5 (2026-10-09, direct report: "While translating an image description, I attempted to switch to another slide on the Images tab. I got the warning message and selected 'No' in response to 'Switch anyway'. However, SlideMage still made the switch"): reproduced with a real click on a row (tests/test_review_gui.py). The slide on show did stay, but the list highlighted the clicked row: the warning is raised from inside the list's mouse press, and Qt selects the clicked row after the handler has returned, undoing the revert (qt_transcript_tab._decline_switch()). The list is now put back once more after Qt has finished the click, for both warnings ("Unsaved image edits" and "Translation in progress"); the revert is skipped if the user has moved on since. A test covers both warnings.

NEW: Fixed: answering "No" to "Switch anyway?" on the Images tab.
- Declining the warning when you leave a slide with unsaved image edits or a translation still running keeps the list on the slide you are working on; the list used to highlight the slide you had clicked while the old slide stayed open.

v5.35.6 (2026-10-11, direct report: "When I select a different view in the Images tab in the 'Show:' dropdown, the selection jumps to a different slide even if a translation is under way. There should be a safety check as when manually switching away from one slide to another while a translation is ongoing"): the "Show:" combo was connected straight to _populate_list(), which took the combo's index for the slide to re-select, found nothing and landed on the first row -- a different slide than the one on show, with the warning suppressed (qt_transcript_tab._on_filter_changed()). Now the slide on show stays on show whenever the new view still lists it (re-selected by path, its editors and any translation in them untouched, no spurious "unsaved edits" question); when the new view would drop it, a translation in flight is confirmed first ("Translation in progress ... Switch anyway?") and "No" puts the dropdown back. The "Sort:" dropdown no longer jumps to the first row either. Tests in tests/test_review_gui.py.

NEW: Fixed: the "Show:" and "Sort:" dropdowns on the Images tab no longer jump to another slide.
- Choosing another view in "Show:" (or another deck in "Sort:") keeps you on the slide you are working on whenever that slide is still in the list, with its translation and unsaved edits intact.
- When the chosen view would no longer list your slide while a translation is running, you are asked "Switch anyway?" first, as when you click another slide; answering No puts the dropdown back.

v5.35.7 (2026-10-11, direct report: "When compiling individual slides multiple times, SlideMage often gets stuck", with a log that ends with latexmk's last line and no "==== PASS" line): the compile itself had finished (four passes, "All targets are up-to-date"); what failed was the cleanup after it. .build/ still held the files of those preview jobs (a .fls, .log, .nav ... each), i.e. deleting or moving a file there raised PermissionError (WinError 32 -- a freshly written file in the cloud-synced folder, still open in the sync client or lualatex), an OSError that the render thread (qt_slide_source_tab._render_bg(), which only caught RuntimeError) let kill it without a log line, so the status bar went on showing the render as running. slide_preview._compile_and_extract() now copies the finished PDF out (retrying while the file is locked), deletes the job's build files best-effort (retrying; a file that stays locked is reported and swept by a later render once it is an hour old) and never fails a finished render over them; _render_bg() ends every failure with a "*** FAIL: render of ... ***" line. Tests in tests/test_slide_preview_cleanup.py. Not changed: every render still leaves its PDF in its own folder under %TEMP%\slidemage_preview_*.

NEW: Fixed: single-slide renders no longer get stuck after the compile.
- A render whose build files are still locked for a moment (cloud sync, antivirus) now finishes normally instead of silently hanging in the status bar; leftovers in .build/ are cleaned up by a later render.
- Any other unexpected error during a render is shown as a failed render.

v5.35.8 (2026-10-11, direct instruction: "Let SlideMage automatically delete individual slide renders (typically triggered from the edit tab) sometime after at least 24 hours have passed"): the PDF of a single-slide render (the slide editor's "Render to PDF", a Preview popup's "Render now") sits in a folder of its own, %TEMP%\slidemage_preview_*, so the viewer can open it, and nothing ever deleted it (about 280 had piled up). slide_preview.sweep_old_renders() removes those folders once they -- and everything in them -- are at least 24 hours old; it runs on a background thread 8 seconds after the app starts and after every single-slide render. Only folders with that prefix that hold nothing but files are touched; a PDF a viewer still has open is kept and retried by the next sweep. Test in tests/test_slide_preview_cleanup.py.

NEW: Single-slide renders clean up after themselves.
- The PDF of a single-slide render (the temporary files "Render to PDF" and "Render now" open) is deleted automatically once it is more than 24 hours old, at the next start of SlideMage or the next render.

v5.36.0 (2026-10-12, direct instruction: "create or modify the frame type for the agenda slide to also allow using subsections instead of sections, so I can create an agenda slide that lists all the subsections in a chapter"): \SMSubsectionAgenda[width] next to \SMChapterAgenda. Framework: every slide's \setSlideID also records, once per \subsection, the id of the subsection's first slide and the subsection's title (\subsecname) in the .aux (\SMAgendaSubsection{section}{id}{title}); \SMSubsectionAgenda lists the titles of the current \section's subsections in the same two columns and \normalsize/\small/\footnotesize steps, each a link to that first slide, and sets the same chapter target as \SMChapterAgenda (the navigation bar's "Chapter contents"). The two commands share \SM@ag@main. Slides before a chapter's first \subsection are not listed; a subsection with no slide in the version is not either. Transcripts: DeckSlide.subsection, a "This chapter's sections:" / "Die Abschnitte dieses Kapitels:" list with the number of each subsection's first slide (transcript._subsection_titles()). Tests in tests/test_navigation.py. In the SlideMaster project, slide bij (the Masterdeck's "Trends in publishing" divider) uses it in place of its typed list of topics.

NEW: A chapter divider can list the chapter's subsections.
- **Subsection agenda.** \SMSubsectionAgenda in a chapter's divider (sectionframe) lists the chapter's \subsection titles in two columns, each a link to the subsection's first slide. \SMChapterAgenda still lists the chapter's slides.
- **In transcripts** the subsections appear as a list with the slide number each one starts at.

v5.36.1 (2026-10-13, direct report: "On mbz in the instructor version, on the second reveal steps, the footnote is printed three times"): in a presenter compile a slide with a \footnote{} or \source{} in its title and a \note{} carried that footnote three times on its last reveal step. The presenter note page's breadcrumb typesets the frame title twice (once to measure it, once to show it) and the footnote ran each time, adding two copies to the slide's own. The breadcrumb now typesets the title with \footnote and \footnotemark switched off, so the slide keeps its single footnote and the breadcrumb no longer shows the marker. Checked by rendering mbz and qfk as presenter compiles: one footnote on every step. Plain instructor, during-course and after-course compiles were never affected.

NEW: A footnote in a slide title is printed once in the presenter deck.
- On the last reveal step of a slide with a footnote in its title and a speaker note, the presenter deck no longer repeats the footnote.

v6.0.0 (2026-10-10, direct instruction: the redesign of the window): SlideMage's window is rebuilt as one workspace for the deck that is open, with an AI assistant. Nothing in a project changes: projects, decks, slides, snapshots and settings read as before, and a project opened with 6.0 gets no format change.

The workspace: a top bar (deck switcher with the decks by group and the archived ones at the foot, View as Instructor / During course / After course, EN / DE, Preview | Split | Source | Details, Compile PDF, Images, and a three-dot menu holding what the menu bar and the deck table's per-row buttons held); the slide list on the left (sections that fold and rename, thumbnails, notes for hidden / no translation / source error / preview old, drag and drop, multi-select with a bulk bar, undo, a right-click menu with Call as); in the middle the focused slide as Preview, as Source (LaTeX with a live check, Insert, Cite, Ask AI to fix), as Split, or as Details (rename, duplicate, delete); on the right a side panel for the slide (Used in decks, Slide versions with Freeze as vX.Y.Z, Visibility, Citations, Language, Image descriptions, Transcript entry, Speaker notes) above the assistant. Ctrl+K opens the command palette: every command, every slide, and full-text search over slides, deck files and the bibliography. Compile PDF makes the view chosen in the top bar; its arrow offers every version, chapters, the presenter PDF, the pages of the selected slides or by number, several decks, all decks except the archive, the transcripts, Stop and Build options. A run shows as a card (one line per job, progress, Stop, Retry failed, Open PDFs), the log is a drawer (Ctrl+L) that opens by itself on a failure. The Images page is a full-window page for describing, drafting, translating and reviewing image descriptions (filters, deck or file order, Tune prompt, Replace image, one job at a time with Stop). Dialogs are sheets in the new look (Add slide, Open project, Settings, Deck settings with Admin slides, Housekeeping, Snapshots, Tags, Import PPTX/ODP, About); Roboto, Roboto Mono and Material Icons ship with the app.

The AI assistant: Chat is an agent, not a suggestion box. It sees the focused slide (the buffer, with unsaved edits), works on this slide or the whole deck, and has tools to read, search and edit project files, lint, render a preview, add slides and bibliography entries and compile. In Ask before edits each change is shown as a diff to Apply or Reject; in Edit automatically it is applied at once with Undo. A slide's header comment, its setSlideVersion line, its vbox to 0pt blocks and frozen versions can never be edited. Every AI task (chat, image descriptions, translation, syntax fix) can use a local Ollama model (for the chat one that can call tools) or a Claude model through the Anthropic API (key from ANTHROPIC_API_KEY, the system keychain with the optional keyring package, or the settings file); Settings -> Cloud has Local AI only (for every project, overridable per project), and the first cloud request in a project says what will be sent. Claude Code is a second tab: a terminal running your own installed, logged-in claude command in the project folder, with the focused slide served over a local MCP server and a hook that blocks edits of protected parts; a file with unsaved edits that Claude Code changes on disk shows a conflict bar. The tab is offered only when claude is found.

Changed or removed (your habits may need a second look): there are no tabs, deck table, deck editor, menu bar or per-deck checkboxes; compile the other versions from the arrow of Compile PDF. A click selects a slide, a double click or Enter opens its source. The deck editor's Grid view and hover preview, the group folding of the deck table and its help are gone. A section's Add slide here adds at the end of the section (it used to add at the top). Duplicate and Translate put the copy into the open deck right after the original; a failed machine translation creates nothing. The language of a slide is set in the Language panel (no offer after a save), and the top bar's EN / DE only changes the preview. Cite inserts a full citation by default (textcite, parencite or the key on offer). Settings -> AI drafting (the "AI draft" dialog) and the "Slide rewrite" prompt are removed: ask the chat instead; the syntax check is now the status line of the Source view with Ask AI to fix. Saving image edits as a draft happens when you leave the slide; Preferences is Settings. Global full-text search is part of the palette.

The program: a one-file build is about 300 MB (it carries QtWebEngine for the terminal), checked on Linux; Windows and macOS builds are untested. New dependencies: anthropic, ptyprocess (pywinpty on Windows) and, optionally, keyring.

BREAKING: the program works differently from SlideMage 5.x in the ways listed above; nothing in a project needs migrating, so the compatibility check only lists this under Info -> Project compatibility. What you need to know: compile the other versions (After course, per chapter, Presenter, several decks, transcripts) from the arrow of Compile PDF instead of the deck row's checkboxes; AI drafting of a whole slide is gone in favour of the chat (a model that can call tools is needed for local use, and the model setting of AI drafting no longer exists); a Linux machine needs QtWebEngine's system libraries to start the app.

v6.1.0 (2026-10-11, direct instruction: BIG CHANGE 2, faster previews): Preview requests keep one running compile and the latest queued request, debounce automatic saves, bound session image retention and update the older-buffer notice after typing, and discard obsolete results after source, deck preamble, view, language or timestamp changes. A reusable image child process keeps MuPDF out of GUI/worker threads and restarts after an image-process failure. The display and canonical snapshots reuse prepared PNGs, cached by PDF content with bounded memory; only accepted renders publish snapshots. Cached scratch previews skip unusable SyncTeX output. Reusable builds also invalidate on toolchain, environment and latexmk configuration changes, preserve active files during housekeeping, and export recorded dependencies for the CLI watch mode. Optional preview profiling records build stages and latexmk rule durations. Generated preview/snapshot wrappers are excluded from slide deck-membership headers. Repeated manual benchmarks use visible title, body and graphic edits and retain the cold/warm/unchanged distinction.

v6.1.1 (2026-10-11, direct instruction: fix the independent preview review findings): Preview disposal now survives actual Qt destruction and removes queued or failed temporary results. Accepted image identity includes the timestamp setting; unverified disk snapshots remain visible with a request to render. Cleanup and build reservations share an atomic guard and a persistent cross-process maintenance lock. The image helper has a 15-second request deadline, validates its response and recovers after a stalled read or write. The short benchmark uses four fixed manual calls, immutable implementation/input/options identities, fresh interrupted attempts, adjacent before/after ordering and durable checksummed evidence.

v7.0.0 (2026-10-11, direct instruction: BIG CHANGE 1, the language switch follows translations): EN / DE resolves each deck slot to its linked partner in the chosen language across the slide list, Preview, Source, Details and side panels. DE edits and saved/buffer renders use the German file; unsaved buffers survive switching languages. A translation has an independent id and version history, so an English version pin stays in EN while DE uses the translation's current file. Missing partners fall back to the called slide with the existing no-version flag. The original call keeps placement, view conditions and reveal steps. Full, chapter, presenter and selected-page compiles of the open deck follow the selected language; alternate-language PDFs have their own names. Compile wrappers resolve local slide-list fragments and the generated appendix too, with original input files retained in compile records.

BREAKING: linked translations are one logical row and one typeset slot in SlideMage, even when older decks list both language calls. EN / DE now selects the file to edit as well as the render language. Existing deck and slide files need no migration. To typeset both linked files as separate bilingual slides, use independent, unlinked copies. An English pin does not pin the German translation; each slide has its own version history. Compiling raw deck source outside SlideMage retains its literal calls.

v7.0.1 (2026-10-11, direct instruction): The slide list's "no DE" and "no EN" indicators use the app's red warning colour in both themes, including the focused row. The rest of the row keeps its usual colours.

v7.0.2 (2026-10-11, code review fix A5): A slide's version is read from its first \setSlideVersion line that is not commented out; before, a commented-out marker (e.g. "% \setSlideVersion{9-9-9}") counted, so a save froze and bumped from the wrong version. A save also removes every \setSlideVersion line before writing the new one, so a slide can no longer end up with two different versions.

v8.0.0 (2026-10-11, code review fix A1a): \omitslide and \omitslideversion now include slides only in instructor decks; during-course and after-course compiles skip them while keeping subsequent frame numbers aligned. Decks without \deckversion and presenter compiles retain instructor content.

BREAKING: \omitslide and \omitslideversion no longer send tagged slides to during-course or after-course decks. Use \slide or \slideversion for slides students should receive; keep omission calls for instructor-only content. The existing \studentversion flag still skips these slides, including in instructor decks.

v8.0.1 (2026-10-11, code review fix A1b): One rule decides whether a slide call is typeset in a deck version (SlideCall.included_in), used by the slide list, the appendix agenda, the lint check, the compile progress count and page compiles; the appendix and lint kept their own rules, which still counted \omitslide slides in the student versions. An explicitly empty list, \conditionalslide[]{...} or \slidestep{...}[]{...}, now means no version everywhere, as in LaTeX; it meant every version in the slide list and the transcript.

v8.0.2 (2026-10-11, code review fix A3): Slide calls with spaces or a line break before an argument -- \slide {id}, \conditionalslide [instructor] {id} -- are legal TeX and are now recognised: the slide list shows them, "Archive unused content" no longer offers their files, and their slides get the deck in their "Included in decks" header. The two separate slide-call patterns of unused-content archiving and the deck headers are gone; both use the deck parser.

v8.0.3 (2026-10-11, code review fix A2a): Slides in a fragment pulled into a deck with \include (not only \input) are resolved to the selected language when compiling, counted in the progress bar and checked by the lint.

v8.0.4 (2026-10-11, code review fix A2b): Transcripts find a deck's slides as the compile does -- with the deck parser and the translation resolution -- instead of their own pattern. A German deck's transcript now describes the linked German slides the PDF shows, not the English originals; a translation partner the deck also calls explicitly is one entry (as in the PDF), not two; and slide calls inside \iffalse...\fi, verbatim or a \note are no longer counted. Fragments are looked up as TeX does: from the deck's folder first, then the project folder.

v8.0.5 (2026-10-11, code review fix A4): The Image descriptions side panel saves only the fields you changed, so a description a drafting or translation job wrote while the panel was open is no longer overwritten by the older text still shown there. A redraft that finishes after you moved to another slide showing the same image no longer fills that slide's form.

v8.0.6 (2026-10-11, code review fix A6): A new empty project can add a standard slide: without a slide template of its own, the bundled example project's template is used (before, adding the slide failed). Creating a project from the example no longer copies generated preview wrappers (decks/_*.tex).

v8.0.7 (2026-10-11, code review fix A7): A compile whose bibliography could not be built (biber failed, so citations show as their keys) still succeeds, but now writes a warning to the compile log.

v8.0.8 (2026-10-11, code review fix A8): Compiling only some pages works for slides that come from an \input or \include fragment of the deck; before, such pages were refused as "not from a slide of the deck's list".

v8.0.9 (2026-10-11, code review cleanup B1a): Internal: the TeX source-text helpers (comment pattern, comment and verbatim masking, the \input/\include pattern) live once in tex_source.py instead of four copies and private names other modules borrowed. No change in behaviour.

v8.0.10 (2026-10-11, code review cleanup B1b): Internal: every helper one module uses from another has a public name (22 renames, e.g. compiler.build_env, deck_scan.parse_chapters, alt_blocks.slide_title); no module reaches into another one's private names any more. No change in behaviour.

v8.0.11 (2026-10-11, code review cleanup B2): Internal: the compile status lines ("==== Compiling ...", "==== PASS: ...", "*** FAIL: ...") are written and recognised in one module, compile_log.py, instead of f-strings in five modules and two copies of the patterns in the progress bar and the job list. The log text is unchanged.

v8.0.12 (2026-10-11, code review cleanup B4): Internal: copy-pasted helpers merged -- the Windows no-console subprocess option (11 copies) and the git checks of archiving and renaming live in processes.py; the slide id helpers bare_id and slide_id_of exist once. No change in behaviour.

v8.0.13 (2026-10-11, code review cleanup B3): Internal: the five places that run latexmk (compile, page compile, slide preview, reusable preview build, deck snapshot) share one function for starting it, streaming its output to the log and letting Stop end it; each keeps its own command and checks. No change in behaviour.

v8.0.14 (2026-10-11, code review cleanup B5): Internal: removed 11 unused functions and what only they used (about 290 lines), among them the old image-description bake-off, a bulk language setter and an unused "other model" setting. No change in behaviour.

v8.0.15 (2026-10-11, code review cleanup C1): Internal: slide_language owns the slide file names -- current_name(), frozen_name() and one pattern for frozen versions (-vX-Y-Z.tex, three parts as the naming convention says) replace names assembled by hand in about 20 places and two patterns that disagreed. No change in behaviour for files SlideMage writes.

v8.0.16 (2026-10-11, code review cleanup C2): Internal: the three deck views are defined once in deck_editor (they lived in transcript.py, imported from there by the workspace, and were written out in four more modules); the translation languages EN/DE are one constant beside the slide languages. No change in behaviour.

v8.0.17 (2026-10-11, code review fix C3): The language badges ("EN + DE"), the Language panel and the preview's "translation outdated" notice find a slide's translation partner by the same rules as the slide list, preview and compile -- also when the link is recorded on only one of the two slides, and not at all when two translations claim the same original. Before, they read only the slide's own first header comment and could disagree.

v8.0.18 (2026-10-11, code review fix C4): A translation or duplicate of a slide starts its own version history like any new slide (no version until its first tracked save, counted from 1.0.0); before, it carried over the original's \setSlideVersion, e.g. a German translation of a slide at 1.1.0 started at 1.1.0.

v8.0.19 (2026-10-11, code review cleanup D3): The release history moved out of version.py (about 2,000 lines of docstring) into src/slidemage/CHANGELOG.md, which the About sheet and the release notes read; a new release adds its entry there. The version string with the commit time is worked out when first needed, not when the app starts. No change in what is shown.

v8.0.20 (2026-10-11, code review cleanup D4-D6): Internal: palette.py (the UI colours) moved into the UI kit; references to the notes files LANGUAGE_NOTES.md and ALT_TEXT_NOTES.md, which are not in the repository, were removed (one was in an error message); the lint check also catches unused imports, redefinitions and unused variables, and the existing ones were removed. No change in behaviour.

v8.0.21 (2026-10-12, responsive layout L1): The workspace columns no longer need about 1,560 px together: the centre column needed the Images page's width even while it showed a slide. The Images page itself is narrower too (its slide list is 340 px, and Save/Mark reviewed sit on their own row). The window's minimum width is still set by the top bar until the next change.

v8.0.22 (2026-10-12, responsive layout L2): The window can be made narrower than 1,568 px (now about 1,020): the top bar adapts to its width. With less room the "View as" label is hidden, "Saved" becomes a dot, the deck name is shortened and the Compile button just says "Compile"; with little room the view and mode switches show short labels (full names as tooltips) and Images moves into the ⋮ menu.

v8.0.23 (2026-10-12, responsive layout L3): The window opens where and as large as it was last closed (or maximised); the first time, or when that screen is gone, it fills about 90 % of the screen instead of a fixed 1280 x 860, so it never starts larger than the screen. It can be made as small as 1024 x 640. Window layout (size, position, the side panel's width) is kept per user and computer, in layout.json in the SlideMage settings folder, instead of in the project; the side panel's width is taken over from the project once.

v8.1.0 (2026-10-12, responsive layout L4): The slide list can be dragged wider or narrower (220 to 520 px) like the side panel, and its width is remembered. Double-clicking the divider next to the slide list or the side panel puts that column back to its standard width.

v8.2.0 (2026-10-12, responsive layout L5): The slide list and the side panel can be hidden and shown again: with the buttons at the left and right ends of the top bar, with Ctrl+Alt+[ and Ctrl+Alt+], from the command palette or ⋮ -> View, or by dragging a column's divider all the way to the edge. A shown column comes back at its last width, and the choice is remembered. The Images page still takes both columns' room while it is open, without changing that choice.

v8.2.1 (2026-10-12, responsive layout L6): The split between the side panel and the assistant is remembered, and in a short window the side panel gives way first, so the assistant's suggestions, input and Send stay usable down to the smallest window (640 px). If the suggestions still do not fit, a "Suggestions" menu offers them.

v8.3.0 (2026-10-12, direct instruction: merge develop v5.36.0): The develop line's releases v5.35.4 to v5.36.0 are merged into the redesigned UI (v8.2.1). (1) Release notes: packaging/release_notes.py builds the GitHub release notes from the NEW: paragraphs of CHANGELOG.md (through version.parse_history(), which now gives each entry its summary and bullets): the NEW: bullets of every version since the previous release, then the breaking changes, then a link to the full changelog; release.yml no longer lets GitHub append its own changelog line. Versions up to and including v8.2.1 are exempt from the NEW: requirement (their entries predate it); the release fails only if a version after v8.2.1 has no NEW: paragraph (tests/test_release_notes.py; the README's release steps say so). (2) Images page: two edge cases from develop's v5.35.5/v5.35.6 turned out to be real bugs here too. After declining "Translation in progress ... Switch anyway?" following a click on another slide, the list kept the clicked slide highlighted (the click selects its row after the handler returned); SlideNav.select() now puts the choice back once Qt has finished the click. A "Show" filter that no longer lists the slide on show while a translation is under way switched slides without asking; ImagesPage._on_view_changed() now asks first, and "No" restores the filter (SlideNav.restore_filter()). Tests in tests/test_images_page_gui.py. (3) Locked build files (v5.35.7): the fresh-render path of slide_preview.compile_and_extract() copies the PDF out of .build/ with retries instead of shutil.move, deletes its build files with retries, never fails a finished render because of cleanup (the log says how many files stayed behind), and sweeps stale preview-* leftovers; the Preview pane's render worker already ended every exception with a "*** Render failed" line, which is now also written when the result was superseded. tests/test_slide_preview_cleanup.py. (4) Old renders (v5.35.8): slide_preview.sweep_old_renders() deletes slidemage_preview_* folders under the temp directory that hold only files and are at least 24 hours old; the workspace runs it 8 seconds after start and the preview worker after every render, off the GUI thread. tests/conftest.py points the temp directory at a test folder. (5) \SMSubsectionAgenda (v5.36.0): the LaTeX side is taken as it is; transcript.resolve_deck() numbers subsections inside the deck_slots loop (the \subsection count since the chapter's \section, by the source position of each slide call). Not a breaking release.

NEW: Everything from the 5.x line up to 5.36 is in, and this release rounds up what changed since 5.x for people upgrading from there.
- **New window.** SlideMage is now one workspace for the open deck: a top bar, the slide list on the left, the slide as Preview, Source, Split or Details in the middle, and a side panel with the assistant. Projects, decks and settings read as before.
- **AI assistant.** The chat can read, search and edit your project files, lint, render a preview, add slides and compile; changes are shown as a diff to apply or reject, or applied at once with Undo.
- **Command palette.** Ctrl+K finds every command, every slide and any text in slides, deck files and the bibliography.
- **Faster preview.** Previews reuse the previous build, only the newest request is compiled, and results that are out of date are never shown.
- **English and German side by side.** Choose EN or DE and the slide list, preview, source and side panels all show the linked slide in that language; a translation has its own version history.
- **Compile menu.** Compile the view chosen in the top bar, every version, chapters, the presenter PDF, selected pages, several decks or the transcripts; runs show as cards with progress, Stop and Retry failed, and the log is a drawer (Ctrl+L).
- **Images page.** A full-window page to draft, translate and review image descriptions, with filters, deck or file order, and one job at a time.
- **Breaking in 8.0:** \omitslide and \omitslideversion no longer send slides to during-course or after-course decks. Use \slide or \slideversion for slides students should receive.
- **Fixes to slide handling.** Slide calls with spaces before an argument, slides in \include fragments and German decks' transcripts are now handled as the compile does.
- **Layout that fits.** The window opens as you left it and can be as small as 1024 x 640; the slide list and side panel can be resized and hidden, and their widths are remembered.

v8.3.1 (2026-10-12, streamlining step 1): UI duplication consolidated; behavior is unchanged. (1) widgets: clear_layout() (kit/widgets.py) is the one way to empty a layout; the Popover menu, the Toast, the command palette list, the chat's suggestion list, the diff card, the preview's chips and the side panels' rows no longer carry their own copies (panels/base.py's clear() moved there). The kit's caption() helper replaces eleven hand-written PANEL_CAPTION labels in dialogs and pages. (2) kit_qss: the 25 label rules that only set family, size, weight and color are written through one text() helper; boxes with the same fill and radius (cards, the grey boxes of the side panels, details, chat tools and job lists) and the two bordered bars share a rule; the view tuple comes from tokens.VIEWS. The generated stylesheet has the same rules in light and dark; screenshots of the four centre modes and the kit gallery are pixel-identical. (3) Images: review_refused() (pages/image_form.py) is the one "Nothing to review yet" warning of the Images page and the inspector's panel; the panel's message now lists the image in the page's wording. Test for the panel's refusal in tests/test_side_panels_gui.py.

NEW: No visible changes; internal clean-up.
- The warning when an image is marked reviewed without a long description now reads the same in the side panel as on the Images page.

v8.3.2 (2026-10-12, streamlining step 2): edit application consolidated; behavior is unchanged except one safeguard. claude_runner.apply_result, a wrapper that only turned write_text's ToolError into a string, is gone: the headless tasks (write, translation link) call ai.tools.edits.write_text, the one place that applies a slide edit outside the open editor (expected-text check, backup, undo record), directly. write_text now also refuses a frozen slide version itself, so every caller (agent tools, headless tasks, undo) gets the rule that only edit_file and write_file applied before.

NEW: No visible changes; internal clean-up.
- A background task can no longer write into a frozen version of a slide.

v8.3.3 (2026-10-12, direct report: the Claude Code tab's picker said Sonnet, the terminal ran Opus): the model and effort picker of the Claude Code tab now also sets the interactive terminal's model and effort (--model/--effort at each start), not only the suggestion tasks'. Changing it while Claude Code is running takes effect for tasks at once and for the terminal on Restart, which the status line says.

NEW: The Claude Code tab's model choice applies to the terminal too.
- The model and effort picked in the Claude Code tab now also start the terminal session; after changing them, Restart to switch the running session.

v8.3.4 (2026-10-12, streamlining step 3): the project is now chosen once, by the entry point, and handed on; behavior is unchanged. project.ProjectContext (a frozen dataclass: the project root and the places inside it) replaces deck_scan.PROJECT_ROOT and the ~45 path constants computed from it at import (SLIDES_DIR, DECKS_DIR, BUILD_DIR, STORE_PATH, ...), so importing a SlideMage module no longer selects a project. cli.py creates the context once and gives it to the window (WorkspaceWindow(theme, context)), which passes it on: app_settings, deck_scan.scan_decks, the housekeeping layer (housekeeping, unused_content, archive), the deck snapshot options and folders and the UI that reads settings take it as an argument. The modules not migrated yet (editing, compilation, previews, the AI stack) read project.transitional_context() when they run -- the context set by the entry point, else $SLIDEMASTER_PROJECT / the working directory / the last project, decided at the first call, never at import; their migration follows. deck_snapshot's and preview_cli's command lines choose their project the same way. The MaintenanceMixin and DeckActionsMixin of the window are plain functions now (maintenance.py, deck_actions.py) and the command registry (actions.py) lists them; the side panels get the edits they ask of the Source view and the slide list as a PanelActions value instead of reaching through the window to its siblings. slide_rename's five copies of the deck-file listing are one function. The tests run on two temporary projects without reloads (tests/test_project_context.py) and the path patching of ~200 test lines is one use_project() call.

NEW: No visible changes; internal clean-up.
- Settings, housekeeping and deck snapshots always work on the project the window was opened on.

v8.3.5 (2026-10-13, streamlining step 4): the compile slot is an object of its own and the compile layer takes the project explicitly; behavior is unchanged. ui/workspace/compile_controller.py (CompileController) owns a run: the cancel token, the worker thread (ui/background.py), the progress estimate, the job rows, the jobs behind them for retry, and reports through signals; compile_display.py shows it (job panel, Log drawer, toast), compile_actions.py holds the flows around it (Compile menu, pre-checks, snapshots, Export PPTX, Update previews) as plain functions, and CompileJobsMixin is gone from WorkspaceWindow. In the compile layer, compiler.latexmk_command() / run_latexmk() / Build / wrapper_file() are the one place latexmk is started, its output judged (PDF, TeX log, no fatal error) and a wrapper written and removed; compiler.run_job, partial_compile, deck_snapshot and both preview builds use them, and preview_build.run_preview() / publish_preview() execute a fresh and a cached preview build alike (the build folder is the difference). compiler, partial_compile, slide_preview, preview_build, slide_snapshot, tikz_render, media_render, update_all_previews, compile_passes, compile_progress and deck_snapshot take a ProjectContext instead of calling project.transitional_context().

NEW: No visible changes; internal clean-up.
- A fresh preview render now reads latexmk's output the way the cached one does.

v8.3.6 (2026-10-13, streamlining step 4b): every module works on the ProjectContext it is given, and project.transitional_context() and project.use() are gone: no module reads a "current project" any more, so two projects can be open in one process (tests/test_project_context.py runs the editing and AI layers on two at once). The editing layer (slide_ids, slide_rename, slide_source, slide_language, slide_versioning, slide_add, slide_import, slide_usage, admin_slides, deck_duplicate, deck_headers, deck_outline, deck_language, deck_editor, snippets, latex_lint, transcript, alt_blocks, alt_images, alt_draft, image_review, bundled_copies, compile_records) and the AI layer (ai/resolver, credentials, providers, ollama_admin, translation_style, claude_tasks, claude_runner, claude_images, claude_hook, agent, guides, ai/tools) take the context as their first argument; the prompt stores (translation_prompts, draft_prompts) too. Where only a path is needed the path is passed: bibliography.load/sort_entries/add_entry/entry_line take the .bib, search_project the project root, template_choices the root, and ollama_admin the Ollama host. Workspace and ToolContext carry their ProjectContext (ToolContext.project; .root is derived), OllamaProvider.for_project() / AnthropicProvider.for_project() read the host and key from a project, and the processes started on their own (claude_hook, the preview and deck_snapshot command lines, tools/) build their context at their entry point with project.from_environment(). Behavior is unchanged except the two caches that were global: latex_lint's citation-key cache is now kept per project file, and the transcript no longer keeps the parsed Slidemaster.bib for the whole session.

NEW: No visible changes; internal clean-up.
- A reference added to Slidemaster.bib shows in the next transcript without restarting SlideMage.

v8.3.7 (2026-10-13, streamlining step 5): one atomic writer, one place for the lexical TeX helpers, one process-launch helper, and the last window reach-through is gone. New fileio.py holds atomic_write (temporary file beside the target, fsync, os.replace retried on Windows locks; text or bytes), replace_with_retry (moved from deck_snapshot), read_json/write_json for the JSON stores, and read_text_exact/write_text_exact (moved from archive.py; text with its line endings untouched). They replace six hand-rolled temp-then-rename writers (alt_images, compat, compile_records, ai/claude_scope, partial_compile, draft_prompts) and the plain writes of app_settings, translation_prompts, ui/layout_settings, project.json, the recent-projects list and the bundled-copies manifest, so every store is now written complete or not at all. Storage scopes stay separate (project content, project preferences, machine layout, credentials) and alt_images keeps its lock and reviewed-image conflict checks. tex_source.py now owns braced_argument (moved from alt_blocks), comment_start and blanked_verbatim; latex_lint, deck_language, protected_regions, bibliography, latex_edit and slide_preview use them instead of their own scanners, the slide macros of slide_rename and latex_lint come from deck_editor.ALL_MACROS, and the \end{...frame} pattern is shared. processes.py gains command_output, move_file and delete_file (git mv / git rm for tracked files, plain move or unlink otherwise), used by archive, slide_rename, deck_snapshot, compile_records and version. The Images page, the Add slide sheet and the details pane no longer reach through the window into the Source view; the window offers relaunch_with_project() instead of its private method being called from maintenance. Behavior is unchanged except where the old variants differed: a Source-view brace highlight now treats "\\{" as a real brace; JSON stores and the project file are always written with plain "\n" line ends and atomically.

NEW: No visible changes; internal clean-up.
- Your settings, prompts and project files can no longer be left half-written by a crash or a full disk.

v8.3.8 (2026-10-13, streamlining step 6): integration check of the project-context migration. Every function that takes a ProjectContext or a project root is now annotated so a static type check catches a Path passed for a context (or the reverse), the one failure that would pass silently because Path('/x').root is '/'; a run of the whole test suite with a call-time check of every such parameter found no wrong call. The preview build (preview_build, preview_format) and the compile actions gained those annotations; a test covers atomic_write on a locked file (retried, then written; a permanent lock leaves the old text and no temporary file). Behavior is unchanged.

NEW: No visible changes; internal clean-up.
- Nothing for you to do; this release only double-checks the earlier clean-up.

v8.3.9 (2026-10-13, Claude Code speed plan C1): cheap correctness and instruction fixes for the embedded terminal. add_slide now returns an MCP error when deck insertion fails after creation, names the existing slide id and path, and gives an insertion-only retry via existing; an already-present live slide is a no-op. Deck editor dirtiness is checked again immediately before insertion, preserving edits made during confirmation or creation. The prompt orientation, scope context and get_focus description agree that focus is already supplied and needs refreshing only when missing or stale; independent reads are batched, and terminal tool descriptions/results no longer advertise chat-only file tools. Focus publishing records success only after writing the file, so a failed write is retried. Project watching shares deck_scan's generated-wrapper rule and ignores preview wrappers. Regression tests cover recoverable errors, repeated retries by id/path without new files or ids, dirty-deck races, terminal instructions, focus-write retries and wrapper changes.

NEW: Claude Code creates and inserts slides more reliably.
- If inserting a new slide fails, Claude can retry with the same slide instead of creating a duplicate; unsaved deck edits are protected.
- Claude uses the focus supplied with your prompt, batches independent reads and gets instructions for its available tools.
- Failed focus updates are retried, and temporary preview files no longer trigger project refreshes.


v8.3.10 (2026-10-13, Claude Code speed plan C2): fresh reads and protected background header updates. Tool reads synchronously reload a clean open buffer through the same GUI-thread path as DiskSync before reading it; dirty buffers keep priority. read_buffer, lint, render_preview and get_focus report whether they checked the file or unsaved editor text, captured with the text in one GUI snapshot. Included-in-decks header regeneration uses atomic_write with an exact expected-text check immediately before replacement, including each retry after a Windows file lock; a mismatch re-reads and regenerates, and three conflicts leave the newer slide untouched for a later pass. StaleFileError is shared through fileio and remains available from slide_source. Regression tests cover clean and dirty MCP checks before polling, concurrent header edits, bounded retries, LF/CRLF preservation, failed writes and changes while an atomic write or locked-file retry is pending.

NEW: Claude Code checks the latest slide text and background header updates protect your edits.
- A quick read, lint or preview after a terminal edit sees the new file immediately; unsaved editor edits take priority and are identified in the result.
- Updating deck-inclusion headers preserves newer slide content when another writer edits the slide at the same time.


v8.3.11 (2026-10-13, Claude Code speed plan CR): persistent review labels for Claude slide changes. A per-project JSON store records author, kind, source, ISO time, text hash and deck insertion provenance; read/modify/write uses the existing interprocess lock and fileio atomic replacement, shared directly by the app and the terminal PostToolUse hook. Chat edits (including unsaved buffers), slide drafts, translation partners and all headless text tasks mark live slides; frozen versions and image-description drafts are excluded. Renames carry marks and deletion/archiving drops them. The slide list and Details show Not reviewed, with a registry action for focused or selected slides, a review button and list filter. Manual edits keep the mark; terminal disk polling also watches the review store. Regression tests cover persistence, concurrent writers, hook events, write paths and review controls.

NEW: Claude's slide changes stay labelled until you review them.
- A Not reviewed label appears on slides Claude creates or changes, including translations and terminal edits.
- Use Mark reviewed after checking a slide, or select several slides to mark them together; the Not reviewed filter finds slides still waiting.
- Editing a slide yourself keeps its label until you explicitly mark it reviewed.


v8.3.12 (2026-10-13, Claude Code speed plan C3): composite create_slide for terminal MCP and chat. A complete drafted frame is checked for lint errors, single-frame structure and translation protection before any write. Existing slide_add creation and deck insertion are combined with rollback of the new file/id and translation backreference on insertion failure; a failed rollback uses C1's existing-slide insertion retry. The explicit deck identity is rechecked against the live GUI deck at commit. The apply_slide helper shares validation, checked write/creation, review marking, one cached render and show with C3b. Returned PNGs are handed to the preview pane with target/context/revision checks, including student views; showing a slide makes the preview visible. Orientation and the frames guide direct free-form drafting to create_slide, leaving add_slide for skeletons/translations in place. Fake workspace/renderer and socket-free MCP regressions cover creation, refusal without writes, rollback/retry, translation links and protection, compile errors and preview publication.

NEW: Claude can draft, insert and show a complete slide in one call.
- New drafts are checked before writing, inserted into the named open deck, marked Not reviewed and shown with their preview.
- Failed insertion rolls back the draft; if cleanup fails, Claude can insert the existing slide without creating a duplicate.
- A slide that fails to compile stays in place with its error and file path so Claude can fix it directly.


v8.3.13 (2026-10-13, Claude Code speed plan C3b): composite modify_slide for terminal MCP and chat. Existing slides accept ordered exact old/new replacements or full new text, with an optional expected-text guard and current-text excerpt on mismatch. The edited EN/DE language resolves linked partners; clean editor reads use C2 freshness and dirty buffers remain the reported base. Frozen versions are refused before proposal; apply_slide shares protected-region, lint and structure validation, checked writes, backup/undo, Not reviewed marking, one render and preview publication. Translation headers select translation provenance. Orientation and guides direct slide changes to the composite tool and other files to ordinary editing. Socket-free regressions cover edits, refusals without writes, buffer freshness, concurrent changes, translation resolution, review marks, undo and retained changes after render errors.

NEW: Claude can change, check and show an existing slide in one call.
- Slide changes use your current editor text and language, protect frozen versions and managed regions, and stay labelled Not reviewed.
- Stale text and ambiguous replacements are refused; compile failures keep the change and return the error so Claude can fix it.


v8.3.14 (2026-10-13, Claude Code speed plan C4): shared preview requests and cancellable builds. MCP render_preview and the create_slide/modify_slide tail request the pane's in-flight render service, keyed by source text/revision, target/deck/preamble, view, language and render options. Matching automatic, saved and buffer requests share one build and one raster subprocess; full-size pane images and the existing 1280-pixel MCP PNG are prepared together. The GUI publishes images and canonical snapshots through its generation, target, view, language, timestamp and source-revision checks before returning accepted tool results; another focused slide still leaves the tool's image available. The separate show_rendered path is removed. Tool waits time out; terminal stop/restart retains and cancels its session token, and cancellation reaches maintenance/build/format lock waits, preamble creation and cached/fresh latexmk runs. POSIX cancellable processes run in their own session so cancellation kills TeX children as well as latexmk. Build, format and raster caches and cross-process locks remain. Fake-builder, socket-free MCP, Qt-pane and subprocess regressions cover shared renders, stale publication, another focused slide, cancellation, timeout and released locks.

NEW: Claude and the preview pane share renders, and stopping Claude cancels pending previews.
- A matching preview builds once and appears in the pane only while its slide, settings and source are still current.
- Claude still receives its preview image if you switch to another slide while it renders.
- Stopping or restarting Claude ends waiting and running preview builds so later renders can proceed.

v8.3.15 (2026-10-13, Claude Code speed plan C5): light hooks and optional timing. The Claude Code hook process no longer imports the ai tools package, the compiler, PyMuPDF or Qt: the protection rules (slide_kind, protected_problem) moved to slide_protection.py, the cross-process build_lock to filelock.py (preview_build re-exports it) and call_for_slide_path to slide_language.py, so the review store (ai_review) needs neither slide_preview nor preview_build. Hook start-up per event fell from about 230 ms to about 55 ms (median of 10 subprocess runs); decisions, exit codes and review marks are unchanged. SLIDEMAGE_TIMING=1 in the environment appends JSON lines (prompt received by the hook, tool start/end, slide written, render done, pane published) to <project>/.slidemage/timing.jsonl; python tools/timing_summary.py <project> prints the latest request's timeline. Off by default and silent when off. Tests check that the hook modules import none of the heavy packages and that the events appear in order only when timing is on.

NEW: Claude Code's hooks start faster, and prompt-to-preview time can be measured.
- Each hook call before and after Claude's edits now takes roughly a quarter of the time.
- A debug switch (SLIDEMAGE_TIMING=1) logs when a request, its tool calls and its preview happen.

v8.3.16 (2026-10-13, chat attachments): the chat can read papers and figures. read_file now reads a PDF as text by page (start_page, max_pages; scanned pages are flagged), shows PDF pages as images with pages_as_images (4 pages per call at 110 dpi, for figures, formulas and tables) and shows PNG, JPEG, GIF, WebP, SVG and EPS files to the model (a model without vision gets the existing note instead). The composer has a paperclip button, accepts dropped files and pasted images; a file from outside the project is copied into the new sources/ folder (ProjectContext.sources_dir; -2, -3 ... on a name clash, nothing is overwritten), a file already in the project is referenced in place. Attachments show as removable chips above the box and the request lists them ("Attached: sources/paper.pdf"); the agent is told to read them with read_file and to use add_bib_entry for a paper. All MuPDF work runs in the existing preview raster child process (new document requests in its JSON protocol), never in the app process or its worker threads. Tests cover PDF paging, page images, image files, refusals, copying, chips, the request text, drop and paste.

NEW: Attach papers, figures and other files to the chat.
- Click the paperclip next to Send, drop files onto the message box, or paste an image into it.
- Files from outside the project are copied into the project's sources/ folder; the chat then reads PDFs (text and page images) and looks at images.
- Click a chip above the message box to remove an attachment before sending.

v8.3.17 (2026-10-13, attachments in Claude Code): the Claude Code tab has the paperclip too. Picking files, dropping them onto the terminal or pasting an image (clipboard with an image and no text) places each in the project like the chat does (outside files are copied into sources/, with -2, -3 ... on a clash and spaces in the copy's name written as '-'; inside files stay) and types its @path and a space at the prompt, without Enter (a path with spaces is quoted: @"a b.pdf"), then focuses the terminal. The button is off while Claude Code is not running. The placing code moved from the chat view to ui/workspace/attachments.py (unique_path, place_file, save_image), used by both tabs. Tests cover the helper, the typed @paths, a drop event and the disabled state.

NEW: Attach files in the Claude Code tab.
- Click the paperclip, drop files onto the terminal or paste an image: Claude Code gets the file's @path at the prompt and reads PDFs and images itself.
- Files from outside the project are copied into the project's sources/ folder.

v8.4.0 (2026-10-13, workspace v6 step 1, route audit): one resolver decides which route and model answers every AI request. New ai/ai_profile.py (pure): the session's mode (Local | Cloud, in memory, starting from the project's policy), the cloud connection (Claude Code | API, in the app settings), the project policy (project.json, ai.policy; a project without one is Local, an older ai.local_only true/false reads as local/cloud), the per-project first-use flag cloud_seen (replaces cloud_consent) and the models per route and task (app settings, ai_models: Local, Claude Code, API x chat, image descriptions, translation, fixes/notes/transcripts); the earlier per-task "ollama:..."/"anthropic:..." settings read as the Local and API models until the first write moves them (syntax_check_model becomes the fixes task). resolve(ctx, task) returns a frozen Route (route, model, effort, label such as "translategemma:12b · Ollama", "Claude Code · Haiku · effort medium", "claude-sonnet-5-5 · API"); a running request keeps its Route. ai/resolver.py turns a Route into a provider or backend (chat provider, image draft and translation backends, slide translator) or raises RouteUnavailable ("not available on Cloud · Claude Code ... nothing was sent and no other route or model is used"); the old Local-AI-only API (LocalOnlyError, global and project switches, cloud_models, provider_for(spec)) is gone. Rewired through it: the native chat and its model chip (Local and API; on Claude Code the chat is the terminal), the palette's chat entry, the Images page (draft, redraft, tune, translate; Claude Code runs its own backends and takes no Ollama slot), the Add slide translation (Claude Code runs the Translate task), Ask AI to fix (Local and API only), and the Claude Code tab's tasks: image tasks and slide translation also run on Local and API providers, every other task is refused there with "not available on <route>". The pickers list only the active route's models. Settings: AI models has a route selector and keeps each route's models; Cloud has "Cloud means" (Claude Code | Anthropic API) and "This project" (Local | Cloud, also moves the running session until the top-bar switch exists). The Claude Code tab's model/effort picker is removed (its tasks follow the route's models; the terminal uses Claude Code's own defaults). docs/AI_ROUTE_AUDIT.md lists every dispatch path, its backend per route and what is left for later steps. Tests cover the profile (defaults, migration, policy from project.json, every mode/connection/task), the resolver's refusals, and the rewired chat, pickers, Images page, Add slide, Ask AI to fix and Claude Code tasks.

NEW: AI requests follow one Local / Cloud setting; each route keeps its own models.
- A project starts on Local unless its setting (Settings -> Cloud, "This project") says Cloud; "Cloud means" chooses Claude Code or the Anthropic API.
- Settings -> AI models keeps separate models for Local, Claude Code and the API; every picker lists only the models of the route in use.
- A task that a route cannot do says so instead of using another route (for example, proofreading on Local).
- The model picker of the Claude Code tab is gone: Claude Code tasks use the models set in Settings, and the terminal uses Claude Code's own default.

v8.4.1 (2026-10-13, direct instruction): Claude Code tasks default to Haiku at medium effort (was Sonnet at medium); the user tested it as good enough. claude_runner.MODEL is "haiku"; a saved choice in Settings -> AI models still wins.

NEW: Claude Code tasks are faster by default.
- They use Haiku at medium effort unless another model is chosen in Settings -> AI models.

v8.5.0 (2026-10-13, direct instruction: workspace v6 handoff, step 2): the AI switch. The top bar has one Local | Cloud control for every AI task of the project (ui/workspace/ai_switch.py, after the deck switcher: Local with a computer icon, Cloud with a cloud icon in amber, the connection "Claude Code" or "API", "running" while AI work runs, "stopping…", a ▾ for AI setup, a roving tab stop with the arrow keys and Enter, and a polite accessibility announcement of each commit). A move goes through one request flow (ui/workspace/ai_route.py): running AI work shows the busy popover (listing each item with the Route it captured; "Stop and switch" cancels what can be cancelled, a file write that has started finishes, the switch reads "stopping…" and the request starts over when everything has ended; if the work ends by itself the popover says so), leaving Cloud · Claude Code with a live terminal asks about the session, going to Cloud while the project setting is Local warns every time, and going to Cloud for the first time in a project asks once (cloud_seen); only then the route is committed. The popovers are one component (ui/workspace/ai_popups.py): 360 px under the switch, secondary button first, Esc is the secondary button, a click outside does not dismiss them; kit.Popover gained an inline mode (a child of the window, so it works on Wayland and holds combo boxes) with outside-click and Esc handling. "Running AI work" is one query, WorkspaceWindow.running_ai_work(): every source builds RunningWork items (ui/workspace/ai_work.py) from its own state (Claude Code tasks and batches, a chat answer, an Images page run, Ask AI to fix, and the Ollama slot when none of them accounts for it; the Add slide and prompt-tuning sheets are modal, so the switch cannot be moved while they run). AI setup (ui/workspace/ai_setup.py, 480 px) has a grid of every task by Local and Cloud, each cell a dropdown saved as the default through ai_profile.set_model_choice with a toast (the installed Ollama models come from the cached, threaded ui/ai_models.LocalModelList, the Claude Code choices from claude_code_choices(), the API models from resolver.api_models), the Cloud connection (a change while on Cloud is a route change and asks like the switch), the project setting (it only sets where the switch starts) and a link to Settings → AI. WorkspaceState mirrors the route and emits ai_route_changed; on a commit every picker and model label is filled again (chat chip, Images page, Ask AI to fix, Source view) and the chat keeps a draft, the attached files and the conversation per route (ui/workspace/chat/route_chat.py, in memory). A toast says what changed; nothing is sent. The Settings AI models, Cloud means and This project controls are gone (Settings has an AI tab with the German address, and the API key on Cloud). Images left the top bar for ⋮ → Project and ⌘K, with a primary "Close images" button while the page is open; the deck switcher is 170 px at most; the top bar's densities are full, narrow (below 1500 px: short labels), tight (below 1320 px: the switch drops the connection name) and tiny (the switch is icons only), the switch the last to shrink. New commands: Use Local AI, Use Cloud AI, AI setup…. Tests: tests/test_ai_switch_gui.py (flow, popovers, Escape, Stop and switch, commit, per-route drafts, AI setup, keyboard, commands), plus the updated top bar, Settings and Images page tests.

NEW: One Local | Cloud switch in the top bar moves every AI task, with AI setup next to it.
- The switch asks before it stops running AI work, ends a live Claude Code terminal, or sends a Local project to the cloud; nothing is sent by switching.
- AI setup (the ▾) sets the default model of every task for Local and Cloud, what Cloud means (Claude Code or the Anthropic API) and where the switch starts when the project opens.
- Chat drafts and conversations are kept separately for Local, Claude Code and the API.
- Images is in ⋮ → Project and ⌘K; a Close images button shows while the page is open.
- Settings keeps the API key, Ollama and the prompts; the model and Cloud controls moved to AI setup.

v8.6.0 (2026-10-13, workspace v6 step 3, the unified assistant): the right column is two cards 12 px apart, the side panels (stretch 38, at least 128 px) and the assistant card (stretch 62, at least 380 px), so the panels give way first; the column is 360 px by default, and the draggable split between them and its setting are gone. The outer Chat | Claude Code tabs are replaced by one assistant card (ui/workspace/assistant.py) whose body follows the AI switch: the native chat on Local and Cloud · API, the real terminal on Cloud · Claude Code (started when first shown there, ended by the switch's session popup, started again when the route comes back). Its header (assistant_header.py) has four rows: the route (icon, name in amber on Cloud, "Chat with <model> · <host>", "Terminal · permissions are handled in Claude Code" or "Chat with <api model>"), Focus (open_in_full/close_fullscreen: hides the side panels, not remembered) and New conversation (clears the route on show only: the chat's, or a new Claude Code session); the scope (This slide | Whole deck, now shared by the chat, the terminal's session and the header, with its target "1y8 · Title", " · unsaved" or "deck · 80 slides"); at most two task buttons, picked from the terminal/tasks.py bubbles of the scope by the prototype's priority (translation, fix, shorten, proofread, title, notes, images, summary) among those TaskRunner.refusal lets the route run, then "All actions…" (opens Ctrl+K); and a pill with the running task and Open. The TaskRunner now belongs to the card, not to the terminal, so tasks run on every route (it has its own GuiWorkspace and finds `claude` when a Claude Code task starts; it refuses one when `claude` is missing); its status line, Stop and "Show result" moved to task_row.py. Every task is also a palette command (task:slide:<name>, task:deck:<name>, group AI), visible while it fits; a refused one shows its refusal as a toast and in the status line. The terminal lost its scope switch, bubble strip and More menu and gained a caption ("Permissions are handled in Claude Code. Conversation model: set in Claude Code. Task buttons: Haiku · effort medium (AI setup)"); when `claude` is not installed, or `claude auth status` (claude_launch.signed_in, run on a worker thread; unclear counts as signed in) says it is signed out, an amber card replaces it ("Claude Code is not signed in. Cloud stays selected. Nothing is sent and no other model is used until you sign in." with Sign in…, which starts the terminal where Claude Code asks for its login; or the install hint with Check again) and the task buttons wait. The chat lost its scope switch, New chat button and provider choice; its model chip lists the active route's models, the default marked "default" and the others "this chat only" (a pick lasts for that route's conversation and is forgotten by New conversation; the default is AI setup's). "Ask the chat" and the Source view's chat entry say that the conversation is the terminal when the route is Claude Code. The message list may shrink to 40 px so the controls always fit. kit: ElidedLabel, FlowLayout (task buttons wrap), amber card and header styles. Tests: tests/test_assistant_gui.py (body per route and its swap, header texts, New conversation per route, Focus, scope and target, the two buttons, route gating, All actions, palette commands, the pill, the not-signed-in and not-installed cards, the caption) and the updated column, chat, terminal and task tests.

NEW: One assistant card for every route, with the task buttons in its header.
- The card shows the chat on Local and Cloud · API and the Claude Code terminal on Cloud · Claude Code; its header names the route, the scope (this slide or the whole deck) and what it works on.
- The two most useful tasks for the slide (Translate, Fix LaTeX errors, Make more concise, ...) are buttons that only appear when the route can run them; All actions… opens Ctrl+K, where every task is listed.
- Focus assistant hides the side panels; New conversation clears the current route only.
- The chat's model menu lists the route's models and marks the default; a pick is for that chat only.
- If Claude Code is not installed or not signed in, an amber card says so and nothing is sent.

v8.7.0 (2026-10-13, workspace v6 step 4, the task card): a task on one slide (Translate, Update translation, Fix LaTeX errors, Proofread, Make more concise, Better title, Add speaker notes) is now a task card (ui/workspace/task_card_model.py, pure: TaskCard with kind, title, the captured target (slide id and title, the file it was started on), the captured Route, phase, t0, auto and undo flags, and the texts, steps and buttons of each phase; ui/workspace/task_card.py, the view) owned by the TaskRunner (terminal/tasks.py), which moves it through Generate, Review, Apply and Check preview and to Done, Conflict, Applied but preview failed, Stopped, Failed or Setup needed. The runner's apply is split in two: the answer is checked for freshness (the slide still has the text the task was started on; a translation still has no partner) and then, with the chat's "Ask before edits" (read through the `edit_auto` callable of AssistantArea from the chat session, which persists it as app_settings chat_edit_mode), stops in Review with the proposal as a DiffCard ("Nothing is written yet"), and Apply writes it; with "Edit automatically" it is written at once (Review shows "skipped · Edit automatically", Done is prefixed "Applied automatically (Edit automatically is on)."). Apply runs on the next event-loop turn so the card shows "Writing …. This step cannot be interrupted." (a card in Apply is AI work under way with nothing to stop: Stop and switch waits for it). The write is the same as before (a fix or update goes into the open buffer, Ctrl+Z undoes it, or onto a closed file with a backup; a translation creates the partner slide, links it, puts its call after the source's) and Undo (buffer undo or the backup, GuiWorkspace.undo_in_buffer) is offered only after those writes, not after a translation. A slide that changed while the task ran, or while the proposal waited, is the Conflict phase: the proposal is kept, nothing is written, Compare with current shows the proposal against the slide as it is now, Run again starts the same task on the same slide on the route that is active now, Dismiss closes it. After a write, Check preview renders the written slide in the current view and language through the preview's shared RenderService (a worker calls GuiWorkspace.render_preview, the call the chat's render tool uses, so the pane publishes the image if it shows that slide; the target comes from the new ai.tools.slidemage.slide_target); Done says "The preview is current."; a compile error is Applied, preview failed with the first error line ("Undefined control sequence on line 9"), "Nothing was rolled back" and Open source, View log, Close; Stop and switch cancels the render and Done says it was not rendered. A route that cannot run the task (resolver problem, the route has no implementation, no `claude`), a declined first-use confirmation, or a Claude Code that is not logged in (claude_runner.NOT_LOGGED_IN) is the Setup needed / Stopped phase on the card instead of a status line or toast ("Sign in…" is the Claude Code card's button, ClaudeCodeView.sign_in); nothing is sent and no other route or model is used. The card takes the assistant body's place (assistant.py, task_card.py) with "← Back to conversation"; while it generates, waits for review, applies or renders, Back leaves the header's row 4 pill ("Fix LaTeX errors · waiting for review") whose Open brings it back, a card that has ended is just closed; the target line adds "(still this slide, though you moved on)" when the Source view shows another slide. The Language panel's Translate (PanelActions.translate) and the palette's task commands open the same card for the slide translation; the Add slide sheet keeps its own translation. TaskRunner.busy and running_work report a card in Generate, Apply or Check preview, not one in Review (which holds the other tasks back: occupied). Batches, the image tasks and the summary keep the task row (task_row.py: status, Stop, Show result); the single-slide path of the old row (the conflict result) is gone. The terminal's translate_slide tool says that the task card shows the proposed slide. kit: task card styles, DiffCard.show_all. Tests: tests/test_task_card_gui.py (every phase with its text and buttons, the elapsed seconds, Stop, Reject, Edit automatically, Conflict with Compare and Run again, preview failed with Open source and View log, Setup needed with Sign in, Undo only after a write, Back to conversation and the pill, the target note, the Language panel's Translate, the busy query per phase, the model's pure helpers) and the updated task, assistant, side panel and review tests.

NEW: A task on one slide is a card that shows its steps and waits for you before it writes.
- Translate, Update translation, Fix LaTeX errors, Proofread, Make more concise, Better title and Add speaker notes open a task card in the assistant: Generate, Review, Apply, Check preview.
- With Ask before edits, the proposed change is shown as a diff and nothing is written until you press Apply; with Edit automatically it is written at once and the card says so.
- After a change the slide is rendered again; the card says whether the preview is current or failed, and offers Undo where the change can be taken back.
- If the slide changed while the task ran, the proposal is kept, not applied, and you can compare it with the slide or run the task again.
- A route that cannot run the task, or a Claude Code that is not signed in, shows a Setup needed card; nothing is sent.
- Back to conversation leaves a pill in the assistant header while the task is still going; the Language panel's Translate opens the same card.

v8.8.0 (2026-10-13, workspace v6 step 5, image batches on a route): the Images page and the assistant's image tasks show and keep the route. The buttons that send content say " · cloud" while the AI switch is on Cloud (ai_models.cloud_label, refreshed on ai_route_changed: Draft this slide, Draft all…, Translate all… and the forms' Translate and Save, then translate on the Images page; the Image descriptions panel's Redraft…; the Language panel's Translate to <LANG>; SidePanel.refresh_route updates an open panel without rebuilding it), and a note under each picker of the Images page names the route's model (Route.label of ai_profile.resolve with the picker's choice) and, on Cloud, "sends this image to the cloud" or "sends the description to the cloud". The question before Draft all… and Translate all… (ui/pages/image_results.py: question, confirm) reads "Draft 4 image descriptions in <project>?" and, under it, "<route label> · sends each image and its slide text to the cloud · 10–60 s per image." (Cloud) or "<model> · Ollama · expect this to take hours." (Local; a translation names no estimate on Local); Retry failed asks it again for the failed images on the route active now. A batch captures its route when it starts: Job.route is the picker's Route and the backend is built from it once (image_jobs.draft_job and translate_job replace draft_work and translate_work), so a switch of the route changes nothing about a run under way, and the job card reads "Image 2 of 4 · chart.png · <route label>". What became of each image is now data: alt_draft.run_batch and run_translation_batch (their callbacks are on_item_done(image, outcome)) settle every image as an ItemOutcome in the new batch_result.py (done, kept, failed with a reason, cancelled) in BatchSummary.outcomes and TranslationBatchSummary.outcomes, and a result that is not ok now counts as failed (it was counted as skipped); a request ended by the stop is cancelled, not failed. A person's work during the run is kept: apply_one_draft and apply_one_translation take the text the queue saw at its start as a baseline and write nothing over a different English (draft) or German (translation) text, so an edit saved meanwhile, as well as a review, is reported as kept; English typed into the open form while its image is drafted also counts as kept (it wins at the next save). When a run ends, is stopped, or is cancelled by "Stop and switch" (ImagesPage._abort_job shows the panel; the images not reached are cancelled), the results panel (image_results.BatchResultView, BatchResult in batch_result.py: "Image descriptions · done" or "· partly done", "Image translations · …", the route, the summary, a row per image with its icon and label, Retry failed (n) and Close) is shown under the job card of the Images page; Retry failed starts a new batch of only the failed images. The assistant's Describe images and Translate image descriptions tasks end in the same widget (TaskRunner.result, retry_failed and close_result; AssistantArea shows it in the body's place with Back to conversation, a new task clears it). The busy popover lists a batch as "Drafting image descriptions · 2 of 4 done · <route>" as before. Tests: tests/test_image_batches_gui.py (the pure result and question, the pipeline's outcomes and an edit during the run, the notes and suffixes per route and their refresh on a switch, the questions, the captured route and progress, the panel with Retry failed, the edited-in-the-form case, Stop and switch, the side panels, the assistant's tasks) and the updated task card test.

NEW: Image batches show the route they run on and end in a list of what became of each image.
- On Cloud, the buttons that send content say "· cloud", and the Images page names the model under each picker and what it sends.
- Draft all… and Translate all… ask first, naming the model, what is sent and how long one image takes.
- A batch keeps the route it started on when you move the AI switch; its progress line names the route.
- When a batch ends, is stopped or is cancelled by a switch, a list shows each image: drafted, kept because you edited it during the run, failed with the reason, or cancelled; descriptions you wrote or reviewed meanwhile are never overwritten.
- Retry failed runs only the failed images again, as a new batch on the route that is active now; the assistant's image tasks end in the same list.

v8.9.0 (2026-10-13, workspace v6 step 6, the two-column ⋮ menu): the long one-column ⋮ menu is one 520px popover in two columns and a footer. menus.py's MORE_SECTIONS became MORE_COLUMNS, the sections of each column as (header, command ids) where a section without a header is set off by a separator, plus MORE_FOOTER and the MORE_NOTE caption; build_more_menu builds it from the command registry as before (labels, shortcuts, tones and enabled rules from actions.py). The left column is This deck (Deck settings…, Admin slides…, Edit deck source, Tags…, Duplicate deck…, Export PPTX…, Create deck snapshot…, then Archive deck… in red after a separator); the right column is Project (Find anything… with Ctrl+K, Image descriptions, Edit .bib, Edit test-slides.tex, Open project…), Housekeeping (Housekeeping…, Archive unused slides and media files) and Info (Version history…, Check for updates…, Project compatibility…, kept as an extra section because they are hard to find otherwise); the footer has Settings… and the caption "Everything here is also in ⌘K / Ctrl+K". Only shortcuts show on the right of an item, not the commands' hint texts (add_commands(..., hints=False), Command.key_text()). The View column toggles, Import presentation, Refresh decks, Open latest PDF, Log, Empty pdf folder, Remove temp files, Update slide previews, Reestablish broken translation links and Exit SlideMage left the menu and are ⌘K commands only (the four housekeeping jobs are also in the Housekeeping… dialog). The layout is the kit's PopoverMenu: add_column() starts a column, add_footer() a footer row with add_note() at its right end, which switch it to the compact look (kit_qss: 12.5px items with a 10.5px mono shortcut, 13px/500 headers, a hairline between the columns and above the footer, 6px padding, the separator inset 6px with 5px above and below); a PopoverMenu(focus_first=True) opens on its first enabled item; ↑/↓ move within a column or the footer (wrapping), ←/→ switch between the columns and the footer at the same position, Enter activates, Esc and a click outside close (the popup's own behaviour). Tests: tests/test_more_menu_gui.py (the two columns' sections and items in order, the footer, the destructive item and its separator, 520px, each item running its command, the keyboard, Esc, the outside click, every left-out entry still in the palette) and the updated menu tests.

NEW: The ⋮ menu is a compact two-column menu instead of one long list.
- Left: This deck (Deck settings… to Create deck snapshot…, Archive deck… in red at the end). Right: Project (Find anything…, Image descriptions, Edit .bib, Edit test-slides.tex, Open project…), Housekeeping and Info (version history, updates, project compatibility).
- Settings… is at the bottom left; the caption at the bottom right says everything is also in Ctrl+K.
- The menu opens on its first item; the arrow keys move within a column and between the columns, Enter chooses and Esc closes.
- The view toggles, Import, Refresh decks, Open latest PDF, Log, Exit and the single housekeeping jobs moved to Ctrl+K only.

v8.10.0 (2026-10-13, workspace v6 step 7, the dialog badge, keyboard support and the live region): the last step of the workspace v6 handoff. The dialogs that run or configure AI show the route as a read-only pill under their title: kit.widgets.ModeBadge (an icon and "Local · Ollama", "Cloud · Claude Code" or "Cloud · Anthropic API", amber on Cloud with the cloud tokens, the tooltip "Change it with the switch in the top bar") placed by ModalSheet.add_under_title, and ai_models.RouteBadge / add_route_badge, which follows WorkspaceState.ai_route_changed; it is in the Settings sheet, the Deck settings sheet, the Add slide sheet (its translation) and the Images page's prompt-tuning sheet, none of which has a route picker of its own (a stand-in without a state, as in a test, gets no badge). One live-region helper, kit.widgets.announce(widget, text) (a polite QAccessibleAnnouncementEvent, nothing on a Qt before 6.8), replaces the switch's own code and is also used for the start of "stopping…", the state line of the task card (once per phase, not on every tick of the seconds), the end of an image batch (the results title and summary) and AI setup's "Default for …" confirmations. Keyboard fixes: a request from the switch with the keyboard used to hand the focus back to the switch at once, so the popup it had opened had none (the popup now takes it and the commit puts it back on the selected segment); the popups open on their secondary button (the safe one), keep a replaced list's focus on the same button, and their link ("Change the project setting…", "Settings → AI…") is a kit button in the Tab order; an inline kit.Popover keeps Tab and Shift+Tab inside and gives the focus back to where it was on Esc or a button (close_and_return; AI setup returns to the ▾); kit Button and IconButton also answer Enter (Qt does it only for a dialog's default button) and take the focus from the Tab key only; the focus ring is drawn for every kit button, icon button and segment (2px of the focus token, in kit_qss.py; it was only on a roving segment), the cloud connection, project setting and assistant scope controls are radio groups with one tab stop, the header's task buttons made after the window are put in the Tab order after the scope (setTabOrder), and the running pill's Open is a real button; the task card takes the focus on its first action when it opens, keeps it on the buttons of the next phase (a phase without buttons parks it on the steps toggle) and the assistant hands the focus back to the message box when a card or results panel that held it goes. Accessible names: an IconButton's tooltip is its accessible name, the segments, the route icons ("Local"/"Cloud"), the step icons ("done", "in progress", ...), the steps toggle (with "Expanded"/"Collapsed"), the scope and the pill's Open have names. Tests: tests/test_accessibility_gui.py (the badge in each dialog per route with tone, tooltip, refresh and no route picker; the switch's arrows, Space and Enter; the popups' initial focus, Tab order, Esc and focus return; AI setup's reading order, Tab trap and Esc to the ▾; the announce helper and its callers; names) and tests/test_accessibility_cards_gui.py (the header's Tab order, the task card's focus and announcements, the step icon words, the results panel's announcement and focus).

NEW: Dialogs that use AI show which route they run on, and the AI switch, its popups, AI setup and the assistant work with the keyboard and a screen reader.
- The Settings, Deck settings, Add slide and prompt-tuning dialogs show a small "Local · Ollama" or amber "Cloud · Claude Code" badge under their title; hover it for how to change it (the switch in the top bar).
- The switch's popups open on the safe button, Tab goes round inside them, Esc is the secondary button and the focus goes back where it was; AI setup does the same with its cells in reading order and Esc returns to the ▾.
- Buttons answer Enter as well as Space and show a blue focus ring when you reach them with the Tab key.
- A task card takes the focus on its first button and keeps it from phase to phase; the screen reader hears each phase, the end of an image batch, the switch's change and AI setup's confirmations.
- Icon-only buttons and the route and step icons have names a screen reader can read.

v8.10.1 (2026-10-14, bug fix): the preview never renders the Source view's buffer of another slide. In Preview mode the Source view keeps the slide it last showed, so the preview pane asked it for "the current buffer" and could render that other slide's unsaved text under the previewed slide. CentreColumn._preview_buffer now asks SourcePane.buffer(path) for the previewed slide's own file (PreviewPane.target_path), and gets nothing when that file is not open there. Test: test_the_preview_never_renders_the_buffer_of_another_slide.

NEW: The preview always shows the slide you are looking at.
- After switching slides in Preview mode, Render no longer shows the unsaved text of the slide you edited before.

v8.11.0 (2026-10-14, small UI todos step S1): rerender the previews of one deck, and agent tools to refresh previews. update_all_previews.py: needed_slides_by_template(ctx, deck=None) narrows the scan to one deck, run(..., deck=) shares the compile, progress and log code and prunes nothing (only a scan of every deck can tell which cached files are stale, so the project-wide run stays the one place that deletes and another deck's previews are never touched), and run() now waits for run_job()'s background PDF relocation (the on_relocated callback of each template's compile) so the snapshots are written when it returns. rerender_deck(ctx, deck, log, ...) is the one implementation: it runs that and returns a DeckResult (the deck's slides whose snapshot file was written during the run, those that were not, and the first TeX or log error). compile_actions.update_previews and the new rerender_deck_previews share _start_previews (labels, job names, progress specs, the compile slot with opens_pdfs=False) and _confirm_previews_lint; the deck flow asks once ("Rerender the cached previews of the N slide(s) of <deck>?") and start_deck_previews is the question-free start. New command rerender_deck_previews "Rerender all previews for this deck" (ui/workspace/actions.py, in the palette, enabled with a deck open) and an item of the ⋮ menu's This deck column after Create deck snapshot…. Agent tools in the new ai/tools/previews.py, registered for the chat and over MCP: refresh_preview (slide id or path, default the focused slide; renders the instructor view as the open deck calls it, or alone, through preview_target.render, i.e. the same locked, reusable preview build as the Preview pane, which writes the cached PNGs itself; the temporary PDF is deleted; a failure returns the first TeX error line; a frozen version or a non-slide is refused; it is allowed without asking in Claude Code) and refresh_deck_previews (deck name, default the open deck; Workspace.refresh_deck_previews: headless it calls rerender_deck, the window runs it on its compile slot like the menu action, without the questions, and the chat's Stop stops it; it blocks until done, within one hour, and reports the counts and the refreshed and failed slide ids; Claude Code asks first). Tests: tests/test_update_all_previews.py (the deck filter, no prune, the project-wide prune, failed slides, the first error), tests/test_rerender_deck_gui.py (the command, the menu item enabled and disabled, the action with the shared function and the current deck, the questions, busy), tests/test_chat_gui.py (the workspace's compile-slot run, busy, failure, Stop), tests/test_agent_tools.py (focused slide, explicit slide, instructor view, failures, deck default, lists, deadline) and the updated menu and MCP tool-list tests.

NEW: Rerender all previews for one deck, and the agent can refresh previews.
- ⋮ → This deck → Rerender all previews for this deck (also in ⌘K) rerenders the cached previews of every slide of the open deck, with the usual progress and Log, and leaves the other decks' previews alone.
- The assistant has two new tools, refresh_preview for one slide (the focused one by default) and refresh_deck_previews for a deck (the open one by default); they say which slides were refreshed and which failed.

v8.12.0 (2026-10-14, small UI todos step S2): the image source in the side panel, with its own review state. alt_images.py: ImageEntry.source_status ("reviewed" | "to_review", SOURCE_REVIEWED / SOURCE_TO_REVIEW, one state for source and source_de together) is written to media/alt-text.json only when it is to_review, so a store from before it loads every citation as reviewed and an image without a source has nothing to review (source_state() returns ""); the compile CSV keeps its columns. flag_source_change(entry, before) is the one rule (a source or source_de that differs from before is to review and its reviewed state is gone); set_source() applies it to an entry in memory, save_source() in the store, mark_source_reviewed() is the only way back, and flag_edited_sources(ctx, path, before) applies it to a store file written as a file. Every writer of a source goes through them: image_review.apply_form_edit (the Images page's form, which no longer sets the fields with setattr), the side panel (alt_images.save_source), the bundled-manual merge (a replaced entry with another credit), and the two writers that edit the file itself, the chat's edit_file / write_file (ai/tools/edits.py write_text on disk, and a new file) and the Claude Code hook (record_write snapshots and compares media/alt-text.json); the draft and translation pipeline never writes a source. alt_images._update_entry is the shared single-entry update of set_takeaway_default, save_source and mark_source_reviewed. UI: image_form.py factors the source field out (SOURCE_SPECS, labelled_edit()) and adds SourceStatus (a Chip "To review" warning / "Reviewed" ok and a "Mark reviewed" button, disabled while the field has an unsaved change); the Images page form has one under the English and one under the German field, the Image descriptions panel (panels/images.py) shows the field of the top bar's language with the same label and placeholder, saved with the description by changed-field baselines (a source the panel did not edit keeps what another writer stored) and confirmed at once by Mark reviewed. The Images page and the panel are never visible together, so WorkspaceWindow._on_page_changed saves the panel's pending edit when the page opens (ImagesPage.ensure_loaded now reads the store again once loaded, forms with edits keep them) and refreshes the panel when the page is left. image_review.FILTERS gains "Source to review"; the slide state, the summary and "Needs attention" stay about the description. Tests: tests/test_image_source.py (the store, the one rule, every writer, the filter), tests/test_image_source_gui.py (the page form, the sync with the panel through the window) and the panel tests in tests/test_side_panels_gui.py.

NEW: The Image descriptions side panel has the Reference / citation box, and a changed citation is marked To review.
- The panel shows the same Source (Quelle in DE) field as the Images page; both edit the same entry and show each other's saves.
- Any change to a citation, by you in either view or by the assistant or Claude Code editing the image store, sets it to To review; Mark reviewed confirms it, apart from the description's own review.
- The Images page can list the slides whose citation is still to review (filter Source to review).

v8.13.0 (2026-10-14, small UI todos step S3): Compare rendered, the side-by-side rendered before and after of an AI edit. ui/workspace/compare_rendered.py: CompareRendered is a non-modal QDialog (1200 x 720, so not squeezed into the 360 px assistant column; Esc, Close and the window's button end it) that typesets two texts of one slide for the same target, view, language and footer timestamp as the Check preview step (preview_view.render_context, now also used by TaskRunner._check_preview) and shows them as "Before" and "After" in equal PageView panes (preview_view's page widget, renamed from _Page). Both are requested as drafts (saved=False, render_text) from a RenderService of the dialog's own, so the compile slot, the build locks and the request sharing are the Preview pane's and nothing is written; each side has a QThread (background.start_detached) that waits for its request with the dialog's cancel event and reads the PDF's pages as PNGs in the raster child process (preview_raster_client.read_document, op pdf_images, 130 dpi, at most 60 pages). A side that fails shows "<Before|After> could not be rendered: <first error line>" (task_card_model.first_error) while the other is shown; a side still rendering shows a "Rendering…" chip (kit Chip.set_icon is new) and message. ‹ and › and the arrow keys (window shortcuts) move both sides to the same page, a side with fewer pages says "No page N" and "After has only M pages."; until the user moves, the page is the last one both sides have. "Text diff" swaps the pages for the chat's DiffCard of the same two texts (all rows). Closing sets the cancel event, closes the RenderService (its requests are cancelled) and disconnects the workers, which end at their next 50 ms check. Entry points: the task card has a "Compare rendered" action in Review, Conflict and Done (TaskCard.can_compare: a change to an existing slide; TaskRunner.compare_texts gives the card's before and after, in Conflict the slide as it is now against the proposal), the chat's DiffCard has a compare_clicked signal and button in every state, shown for an edit of an existing slide file only (not for a new file, a .bib or any other file; compare_rendered.can_compare is preview_target.for_path), and the command slide:compare "Compare rendered with last AI edit" (palette, the slide list's context menu) and a "Compare rendered" button in the Details view's "Not reviewed" row; both compare the text before the last AI edit with the slide's text now (compare_with_last_edit). The earlier text is new: ai_review.mark(before=) keeps the text an "edit" replaced, one file per slide in .slidemage/ai-before/ (ProjectContext.ai_before_dir; the last edit only, kept after Mark reviewed, moved by a rename, nothing kept when the text did not change), written by write_text (the chat's and the tasks' edits) and by the Claude Code hook's PostToolUse from the snapshot its PreToolUse already took (ai_review.last_before reads it). Tests: tests/test_compare_rendered_gui.py (drafts for the top bar's view and language, equal panes, page navigation with unequal counts and the keys, one failing side, text diff, closing cancels the pending renders, a slow side, non-slide files, both themes, the chat cards, the palette command, the Details button, the task card in Review, Done and Conflict) and tests/test_ai_review.py (the kept text of chat edits, the hook and renames).

NEW: Compare rendered shows the slide before and after an AI edit side by side.
- The task card (Review, Conflict and Done), the chat's edit cards and the Details view of a slide Claude Code changed have a Compare rendered button; Ctrl+K has "Compare rendered with last AI edit".
- Both versions are typeset in the view and language of the top bar, labelled Before and After, with ‹ › or the arrow keys to step through the reveal steps of both; a version that cannot be typeset says why while the other is still shown.
- Text diff shows the source diff of the same two texts; Esc closes the window and stops any rendering still under way. Nothing is written.
- SlideMage now keeps the text a slide had before the last AI edit (including Claude Code's in the terminal) in .slidemage/ai-before/.

v8.14.0 (2026-10-14, small UI todos step S4a): the readability check, a deterministic measure of whether an audience can read a slide or a deck. readability_pdf.py reads a rendered PDF in the raster child process (preview_raster.document op "layout", preview_raster_client.read_layout with its own 300 s timeout; the GUI process never opens the PDF): per page the visible text as lines (dominant size, colour, box; text-render-mode-3 text such as the slide-id stamp and the alt text of figures is dropped, text beyond the page is kept so that clipping can be seen), the placed raster images with their pixel size, the opaque fills in paint order and the vector figures (clusters of at least 12 paths away from page-wide bars). readability.py (no MuPDF, no Qt) classifies every line (the footer, found as a filled bar at the bottom or the last 5 % of the page, and the slide-id stamp are not content): figure text (centre inside an image or a vector figure), citation (starts like Source/Quelle/Image source/a footnote symbol of the template, or is small print, at most 0.75 times the body size, low on the slide or sideways, as the template sets \source in 3.2 pt), heading (the title bar in the top 15 %, larger text in the upper third), else body; the body size is the one most characters below the title bar use. Thresholds are one frozen dataclass, Thresholds/DEFAULTS, documented in the module docstring, all sizes in % of the slide height (the messages quote pt for a 7.5 in slide): body and heading >= 3.3 %, citation >= 2.2 %, text in figures >= 2.6 % (error below, warning within 5 % above), a heading smaller than the slide's body is a warning, the largest image under 25 % of the slide area (or under 35 % of its width unless it fills 75 % of the height) is a warning (images under 3 % and backgrounds over 80 % are not judged), contrast under WCAG 4.5:1 (3:1 for headings and text from 5 %; the background is the topmost opaque fill under the text, none when a picture is behind it), clipped text (off the page or into the footer) and overlapping lines from different lines are errors, more than 90 words or 14 lines of body text and baselines closer than 1.0 times the font size are warnings. Findings (Finding: slide, page, rule, class, severity, measured, threshold, unit, box as fractions of the page, excerpt or image file, count, suggestion, file) group into SlideReport and Report with summary, to_text(limit) for the agent and to_dict() as JSON for the Make readable step. The last page of each run of pages with one footer slide id is judged, as the slide snapshots take it (new slide_snapshot.slide_runs, which capture_deck now uses too), earlier pages only for clipped text. readability_check.py is the glue: check_slide renders a draft through a RenderService, check_deck reads the compiled PDF of the view and language only while compile_records.check_record(record, None) finds the PDF and every file the compile read unchanged (a new wrapper_text=None skips the wrapper and engine comparison), else StalePdf says why and nothing is compiled; findings get the slide's file and an image finding the file of the slide's \includegraphics with the same pixel size. UI: ui/workspace/readability_panel.py has ReadabilityPanel (summary line, findings grouped by slide with severity icon, class, measured value against the threshold, excerpt, suggestion, Show slide and a click on a finding focus the slide, Check again, Close; a stale deck offers Compile the deck first, which starts the normal compile and runs the check when it settles) and ReadabilityCheck (the worker thread, Check again, Back); the assistant shows it in the conversation's place (AssistantArea.readability_panel, check_readability(scope)), the header offers Check readability / Check deck readability when no AI task is on show (AssistantHeader.can_check), and the commands slide:readability and deck:readability are in Ctrl+K; it runs on every route. Agent tool check_readability (ai/tools/readability.py; slide or deck, default the focused slide; a stale deck PDF is reported, not compiled) in the chat and, read-only, over MCP for Claude Code. Tests: tests/test_readability.py (rules, classification, pages to slides, reports, the deck PDF's freshness, on synthetic MuPDF PDFs; one opt-in real beamer deck), tests/test_readability_gui.py, tests/test_readability_tool.py, and the updated header and MCP tool-list tests.

NEW: Check readability tells you whether the audience can read your slides.
- Ctrl+K → "Check readability of this slide" (a draft of the slide in view) or "of this deck" (its compiled PDF; if that is out of date it says why and offers to compile first) lists, per slide, text that is too small for a projected slide, images shown too small, low contrast, cut-off or overlapping text, too many words and cramped lines, each with the measured value, the limit and a suggestion; a click takes you to the slide. It uses no AI and works on every route.
- Sizes are judged against the slide height: body text should be at least 3.3 % (about 18 pt on a 7.5 in slide), sources and footnotes 2.2 %, text in figures 2.6 %; sources and footnotes are told apart from body text, and the footer is left out.
- The assistant has a new read-only tool, check_readability, for a slide or a deck.

v8.15.0 (2026-10-14, small UI todos step S4b): Make readable, the AI task that enlarges the text and images of one slide and lays it out again until the S4a findings are met. claude_tasks.READABLE: rules (enlarge with the template's size commands rather than \fontsize, wider \includegraphics, columns, spacing and itemize nesting, wording trimmed only where needed, protected parts and markup kept, the preamble untouched) and the answer {"body": the whole new source, "note": optional}: body, because a relayout is not expressible as unique before/after pieces, goes through the same claude_tasks.check as the other body tasks (protected parts, no new lint error); note is the model's remark (the slide cannot fit without losing content, and how to split it), carried by Outcome.note (claude_tasks.answer_note) to the card. claude_tasks.readable_request carries the slide, the floors in points of the slide's page (SlideReport.height_pt is new) and the findings the slide can fix (Report.to_dict(fixable_only=True)) with the thresholds in their units. Template-level findings: Finding.template_level and SlideReport.fixable; readability_check._mark_template_level marks the citation-class text-size findings of a slide whose source sets no font size command (the footnote and source font is the template's, the same on every slide), the panel says "set by the template" with a hint where to change it, to_text says so, and the request leaves them out. readability_check.KnownFindings (the window's readability_known) keeps the last report of each slide for exactly the text that was measured: every panel check and every Make readable measurement fills it, an edit forgets it, the header offers the "Make readable" bubble (terminal/tasks._text_offers) only for a slide with known errors and never runs a check to decide. Routes: READABLE is a FIXES task in KINDS, in PROVIDER_TASKS and CARD_TASKS; ai/provider_tasks.run_task is the generic JSON task on a Local or API provider (rules as system prompt, schema as schema=, reply parsed with parse_json_object, judged by claude_runner.judge, shared with run_task, one repair round, a reply cut off fails at once); claude_runner.run_task now uses judge; TaskRunner._text_task picks Claude Code, the translation path or the generic path, and no route stands in for another (AI_ROUTE_AUDIT.md path 9g). The card: the worker measures the proposed text as a draft (readability_check.check_slide, TaskRunner._measuring, Outcome.measured) before Review, which says "After the change: 0 errors, 1 warning (was 4 errors)" (task_card_model.Readable) or that the proposal does not compile; Apply and Check preview run as usual and Done reuses the numbers of the written text (the same text) with what is now readable and what is still below the floor, plus Run again, which sends the findings that remain; cut-off or overlapping text after the change ends the card in the new phase Overflow (Undo, Run again). Entry points: a "Make readable" button per slide with fixable findings in the readability panel (ReadabilityPanel.make_readable_clicked, AssistantArea.make_readable), the header bubble, and Ctrl+K "Make this slide readable" (slide:readable: runs the task when findings are known, else the check first). No new agent tool: the agent guide and the Claude Code orientation describe check_readability, modify_slide, check again. Tests: tests/test_make_readable_gui.py (the card flow with fake claude, a fake render and a fake measurement, the three routes, the routes that are not ready, the panel button, the header gating, the palette command), tests/test_provider_tasks.py, and additions to tests/test_claude_tasks.py and tests/test_readability.py (request, rules, answer check, template-level marking, known findings).

NEW: Make readable fixes the readability findings of a slide with the AI.
- After Check readability, a slide with errors has a Make readable button (in the findings, in the assistant header, and in Ctrl+K as "Make this slide readable"). The AI enlarges text and images and lays the slide out again so that it still fits on one page, trimming wording only where needed; it runs on Claude Code, Local and Cloud · API, whichever route you chose.
- Review shows the numbers before you decide ("After the change: 0 errors, 1 warning (was 4 errors)") next to the diff and Compare rendered; Done says what is readable now and what is still below the floor, and Run again continues with what remains. Text cut off or overlapping after the change counts as failed: Undo or Run again.
- If the slide cannot be made readable without losing content, the card says so and suggests how to split it.
- Findings that the template sets (for example the footnote and source font) are marked "set by the template" with a hint where to change them, and are left out of the request.

v8.15.1 (2026-10-14, bug fix): the keyboard order of the workspace top bar. The deck switcher (DropdownButton) was not a Tab stop, and the two parts of the Compile split button took neither Tab-only focus nor Enter and drew no focus ring. Now DropdownButton takes the focus from Tab only (a click does not draw the ring), opens on Enter, Space and Down, and shows the kit's 2px focus ring (a transparent border of the same width otherwise, taken out of its layout margins and counted in the elided width, so nothing moves); SplitButton's parts (_SplitPart) are Tab-only Enter-pressable buttons with the ring (kit_qss); SegmentedControl.buttons() and SplitButton.buttons() expose the stops. TopBar._set_tab_order chains every stop once with QWidget.setTabOrder in the visual order, ⇤ column toggle, deck switcher, the AI switch (its selected segment, then ▾), View as, EN|DE, Preview|Split|Source|Details, Compile and its ▾, Close images, ⋮, ⇥, so the chain goes on into the slide list, the centre and the side panels (the order the window adds them to its splitter); a hidden widget ("Close images") and an unselected roving segment are skipped by Qt, so the chain does not depend on the density. View as, EN|DE and the modes are now roving segmented controls like the AI switch: Qt let Tab land on the first segment of a button group, selected or not. PopoverMenu.current_key opens a menu on that item (the deck switcher's current deck). Tests: tests/test_topbar_tab_order_gui.py (Tab and Shift+Tab across the bar in the full, narrow and tiny densities and with Images open, the bar going on into the slide list and the centre before the side panels, the deck switcher as a stop opening on the current deck with Enter, Space and Down and Esc returning to it, Enter and Space on the stops, the ring drawn on every stop).

NEW: The top bar can be used from the keyboard in its visual order.
- Tab (Shift+Tab) walks the top bar from left to right, starting with the slide list toggle, then goes on into the slide list, the slide and the assistant.
- The deck switcher is now a Tab stop: Enter, Space or the down arrow opens it on the current deck, and Esc brings you back to it.
- View as, EN | DE and Preview | Split | Source | Details are each one Tab stop; the left and right arrows change the choice and Enter or Space activates it.
- Compile PDF and its arrow take Enter and show the focus ring like every other button.

v8.16.0 (2026-10-14, small translation fixes, UI_EXTENSIONS_AND_FIXES_PLAN section 2): where a new translation is called in the deck, and the language chip as a jump to the partner. Placement: slide_add.translation_call(deck, source) is the one rule, the first call of the source in the deck (a translation is called once: deck_language folds a separately listed partner into the original's slot and resolves it for every repeat of the source, so one call per repeat would only add folded duplicates), and translation_spec(call) the call itself as deck_language.resolve_call gives a partner (deck_language.PARTNER_MACROS, now shared: same macro, views and reveal steps, \slideversion and \omitslideversion become the plain call). add_slide and create_slide with translation_of and no after insert after that call (an explicit after still wins; the retry hint of a failed insertion names it); a source the deck does not call keeps the end of the deck. The task card's Translate, the deck batch and the MCP translate_slide already inserted after the source's first call but always as a plain \slide, and now use the same two functions; the Add slide sheet places the translation of another slide than the one it was opened for directly after that slide's call (its place line follows) and presets "Appears in" from the source call. Chip jump: the language chip of the Preview (chips_for) is built from the one translation-link reader (translation_link of the file shown, for a slide in the deck or alone) and, with a partner, is a pressable kit Chip (Tab stop from Tab only, Enter and Space, 2px transparent-until-focused ring, tooltip "Go to the German version" / "Go to the English original" also as accessible name) that emits PreviewPane.partner_requested; the centre opens the partner file without leaving the mode (open_file keep_mode), keeps the top bar's language, and shows it as the deck calls it in its own language (slide_target, typeset in that language through PreviewPane.language) so it looks as in DE mode; a partner file that is gone gives a toast. The pinned-version chip reads the version of the file shown. Tests: tests/test_translation_placement.py (add_slide and create_slide: right after the source, several calls, explicit after, source not in the deck, conditional, overlay, omit and pinned calls; the shared functions), tests/test_add_slide_gui.py and tests/test_claude_tasks_gui.py (the sheet and the task card), tests/test_centre_gui.py and tests/test_translation_chip_gui.py (EN to DE and back, keyboard, tooltip, no partner, outside the deck, missing file, in the whole window with the slide list).

NEW: A translation now sits right next to its original in the deck, and the language chip above the preview jumps between a slide and its translation.
- A new German (or English) translation of a slide, from the assistant's add slide or create slide, the task card's Translate, translating a whole deck or the Add slide sheet, is put directly after the original in the deck, with the same visibility and reveal steps.
- The EN + DE chip above the preview shows the German version of this slide ("Go to the German version"); on the German slide it goes back to the English original. The top bar's EN | DE switch is unchanged.
- The chip works with the keyboard (Tab, then Enter or Space).

v8.17.0 (2026-10-14, Claude Code reviews plan, step R1, first two actions): Rewrite selection and Proofread selection. Capture: selection.py (pure) holds the file, its whole text and the selected range as Python offsets; SourcePane.selection() reads it from the editor of the slide shown (new SourceEditor.selection_range(), UTF-16 positions converted) and refuses a blank selection, a frozen or read-only file, a hidden Source view and a selection that touches a protected region (new protected_regions.protected_spans, which mask_protected_regions now uses). Tasks: claude_tasks.REWRITE (answer {"text": ...}, the whitespace at the selection's ends kept; REWRITE_PRESETS Simplify and Shorten, Custom asks in an InstructionPopover) and PROOFREAD_SELECTION (answer {"edits": [...]}, each before once in the selection); the requests carry CONTEXT_CHARS of text on either side. check(), judge(), claude_runner.run_task and provider_tasks.run_task take an optional span: the answer applies to that range of the whole file, every character outside it stays, and the protected parts and lint errors are those of the file. TaskRunner: _capture_selection (the capture holds the whole file as `sent` and the span), both tasks are FIXES-kind card tasks on Claude Code, Local and the API, with the instruction kept on the card for Run again; Apply is the usual write_text into the buffer (editor undo, Conflict when the text changed). Entry points: context menu of the Source editor (PopoverMenu: edit commands, then Rewrite selection with its choices and Proofread selection), the header's buttons first in PRIORITY while a selection exists (the poll of the header includes it), palette commands selection:rewrite (Ctrl+Shift+R), selection:rewrite:<choice> and selection:proofread, enabled with a usable selection. The MCP tool read_selection (Workspace.selection, GuiWorkspace) returns path, range, text and context for the terminal. Tests: tests/test_selection.py (capture, requests, check on a range, the runners) and tests/test_selection_tasks_gui.py (capture in the Source view, header, palette, context menu, the card flow with Apply, Undo, Conflict and Custom, the three routes, routes not ready, read_selection).

NEW: Select text in a slide's Source view and have the AI rewrite or proofread just that text, reviewed before anything is changed.
- Right-click the selection, or use the assistant's buttons, Ctrl+Shift+R or the command palette: Rewrite selection (Simplify, Shorten or your own instruction) and Proofread selection.
- Only the selected text can change; the rest of the slide, its LaTeX commands, labels and protected parts stay as they are.
- Review shows the change in place, and Compare rendered shows it typeset; Apply puts it into the editor, so Ctrl+Z takes it back. If you edit the slide meanwhile, the proposal is kept but not applied.
- It works with Claude Code, Local and the Anthropic API; selections in frozen versions or touching the slide's protected parts are refused.

v8.18.0 (2026-10-14, small UI todos batch 2, step C1, docs/SMALL_UI_TODOS_PLAN.md): continuous saving and Update Version. Version line: \setSlideVersion{X-Y-Z+} means "changed since X.Y.Z" (footer "vX.Y.Z+"; the preamble prints the "+" as part of the third field); slide_versioning.parse_marker / version_text / without_plus / carry_plus. slide_versioning.save_slide() is the one in-app write of a slide's text (Source view autosave, chat edits through ai/tools/edits.write_text, task Apply, image repoint): stale check ignoring the "+", and for a slide's current file prepare_autosave(): when the line has no "+" and that version is not frozen yet (every slide saved before, restored ones, untracked ones as 1.0.0) the file on disk is frozen first, then written with the "+"; mark=False (undo, rollback) puts an earlier text back exactly. update_version() (Update Version, and the Versions panel's button, through CentreColumn.freeze_version) replaces freeze_current() and plan_save(): with "+", or content that differs from the frozen version (header and version line ignored, so an edit made by Claude Code in the terminal counts), the content is written without "+" as bump(version, level) and frozen as that; a version saved the old way and not frozen yet is frozen as it is; a frozen number is never reused; decks that keep the old content are pinned to the version moved on from. restore_version() archives a "+" slide as the next patch above every known version. SourceFile: AUTOSAVE_DELAY_MS (1.5 s) debounce, write_now() (also on switching files, before every compile / snapshot / preview run through compile_actions._busy, before freezing or restoring, on window close; Ctrl+S writes now and renders), paused while read-only, in conflict with a change on disk (the conflict bar, no message box) or during an AI fix; one backup per file per editing session (save_slide_source backup=False touches slides/.backups/<file>/.last-save so slide_source.last_saved still sees the save). Source view: the Save button is Update Version (a slide's current file only; asks major / minor / patch for the change since the last version), the chip says "Saving…" or "Not saved: changed on disk"; prompt_version_choice and the "Overwrite" choice are gone. GuiWorkspace.apply_to_buffer and the task runner's freshness check ignore the "+". Tests: tests/test_restore_version.py (marker, save_slide, update_version, restore of a "+" slide, last_saved), tests/test_source_view_gui.py (autosave, conflict, unlocked frozen file, Update Version button), tests/test_slide_versions_gui.py, tests/test_review_gui.py (closing saves without asking; edits that cannot be saved still ask), and the chat, task and agent-tool tests for the "+".

NEW: Slides are saved as you type, and "Update Version" makes a version when you decide.
- The Source view saves your edits a moment after you stop typing, and before you switch slides, compile or close the window. There is no unsaved state to lose.
- The "Save" button is now "Update Version": it keeps the slide as it is now as a numbered version (major, minor or patch), which decks can keep using.
- A slide changed since its last version shows a "+" after its version number, e.g. v1.2.0+, in the footer, the Details view and the Versions panel.
- If the file changes on disk while you have edits that are not saved yet (Claude Code in the terminal), saving pauses and the bar above the editor lets you choose.

v8.19.0 (2026-10-15, retire the unsaved state): With autosave there is nothing "unsaved" to ask about, so the checks that refused or asked now write first and only meet what could not be written (SourceFile.blocked: read-only buffer, conflict bar up, AI fix running). SourcePane.dirty_changed and WorkspaceState.dirty now mean exactly that, and SourcePane gains written and blocked_files(); the Revert button is gone (the Versions panel restores, the editor undoes). CentreColumn.unsaved(path) writes the file and answers whether edits remain (deck edits, Add slide copy, slide rename and move, image replacement, project update); is_dirty is for displays. The window refreshes the slide list and side panels once after a pause in writing, and at once on Ctrl+S or a file switch, not after every autosave. Tests: test_workspace_window.py, test_source_view_gui.py, test_centre_gui.py, test_compat_gui.py, test_image_review.py and the sheets that took the old wording.

NEW: Nothing is left "unsaved" while you type.
- The top bar says "Unsaved changes" only when edits really could not be saved, for example while a file is in conflict with a change on disk.
- The Revert button is gone: go back with Undo or restore a version in the Versions panel.
- Messages that asked you to "save first" now appear only when saving was not possible, and say why.

v8.19.1 (2026-10-15, docs for autosave): The manual describes saving as you type, the "+" on the version line and Update Version in README.md and docs/SlideMage.md (slide_versioning, SourceFile.write_now). The example manual's slides 1an (Slide versions), 1b6 (Slide editor) and 1wk (AI assistant) say Update Version instead of Save and Overwrite, and carry the "+" themselves; screenshot-slidemage-save-dialog.png is now the Update Version prompt, made by tools/manual/make_screenshots.py (shot_save_prompt, using prompt_version_level), with its alt text.

NEW: The manual and the example slides explain automatic saving and Update Version.

v8.20.0 (2026-10-15, follow-ups to continuous saving): slide_versioning.mark_external_edit(ctx, path) puts the "+" on a slide's current file that was changed outside the app (its content differs from its frozen version; SourceFile.disk_changed calls it before reloading a clean buffer, so Claude Code's edits in the terminal show the "+" like in-app ones); slide_versioning.changed_slides(ctx, deck, language) lists the slides a deck calls from their current file that carry a "+". Settings → General: "Render the Preview after each autosave" (app_settings key live_render_on_autosave, off by default; WorkspaceWindow._live_render renders the written slide through preview.render_after_save when the Preview or Split view shows it, its source has no errors and no compile runs). compile_actions._confirm_changed_slides warns before a snapshot and a PowerPoint export when a deck has "+" slides (Continue anyway / Cancel). New command update_deck_versions (⋮ → This deck → "Update Version of all changed slides…", ⌘K): CentreColumn.update_deck_versions asks major / minor / patch once and makes a version of every "+" slide of the open deck (decks are not rewritten; the slide's own Update Version still asks per deck). The assistant header says " · not saved" only for edits that could not be saved (CentreColumn.is_blocked), no longer flickering while typing. modify_slide's expected text ignores the "+". Tests: tests/test_deck_versions.py, test_workspace_window.py (live render), test_more_menu_gui.py, test_assistant_gui.py, and the chat and snapshot tests that now allow for the "+".

NEW: Follow-ups to saving as you type.
- Edits made by Claude Code in the terminal now get the "+" too.
- Settings → General can render the Preview after every autosave (off by default).
- Creating a snapshot or exporting to PowerPoint warns when slides have changes that are not a version yet.
- ⋮ → This deck → "Update Version of all changed slides…" makes a version of every changed slide of the deck in one go.

v8.21.0 (2026-10-18, direct instruction: "Make the 24-hour cleanup a settings option, allowing the user to set a cleanup timeframe, including a "Never" option"): the first release after merging ui-redesign (v8.20.0) into develop (v5.36.1), so it also carries v5.36.1's presenter-deck footnote fix. Settings -> General: "Delete single-slide renders" -- After 1 hour / 24 hours (default) / 3 days / 1 week / 30 days / Never (app_settings key render_cleanup_hours, in hours; 0 = Never; a value set by hand in app_settings.json is shown as "After N hours"). slide_preview.render_cleanup_hours(ctx) reads it (a missing, negative or unreadable value means 24 hours); slide_preview.sweep_renders(ctx) runs sweep_old_renders() with that age, or nothing for Never. Both sweeps use it: 8 seconds after the start (ui/workspace/maintenance.py) and after every render (PreviewPane's render worker). Tests in tests/test_slide_preview_cleanup.py, tests/test_settings_gui.py and tests/test_preview_queue.py.

NEW: You choose when single-slide renders are deleted.
- Settings → General → "Delete single-slide renders": after 1 hour, 24 hours (as before), 3 days, 1 week or 30 days, or Never.
- The presenter deck prints a footnote in a slide title once (from v5.36.1).

v8.21.1 (2026-10-18, direct instruction: fix the test failures on Windows): ai/claude_runner.run_json() no longer fails a Claude Code task whose answer has arrived because its empty working folder is still in use on Windows (a child of the process ends a moment after it; tempfile.TemporaryDirectory raised PermissionError): _remove_folder() retries for up to two seconds and then leaves the folder. The test suite runs on Windows: tests/fake_claude.py makes the fake `claude` a claude.exe there (pip's distlib launcher + the script as a zip), as Windows runs no shebang script; the "not executable" case of test_claude_discovery is skipped there (no executable bit); test_preview_build's fake `lualatex` is an existing file; tools/preview_benchmark/compare.py accepts a scratch project in the temp folder, not only under /tmp; the deck-settings tests' fake window has CentreColumn.unsaved (v8.19.0) instead of is_dirty. The layout tests that measure widths with the fonts of macOS still fail on Windows (15).

NEW: Claude Code tasks on Windows no longer fail after their answer arrived.
- A translation or other Claude Code task could end as failed on Windows although Claude had answered, when its temporary folder was still in use for a moment; that no longer happens.

v8.22.0 (2026-10-18, direct instruction: "I want a settings option that makes SlideMage ask, when switching away from a "+" slide, whether the version should be updated"): Settings -> General -> Versions: "Ask about Update Version when leaving a changed slide" (app_settings key slide_versioning.ASK_ON_LEAVE_SETTING_KEY, ask_update_version_on_leave; off by default). CentreColumn records the files the Source view wrote (SourcePane.written) and, whenever the file it shows changes (_set_path: another slide focused, another file opened, the language or the deck switched), checks the file it left once the switch is done (QTimer.singleShot(0), after the switch has written the pending edits): a slide's current file that was written on this visit and carries a "+" gets centre.ask_update_on_leave() -- "Update Version…" runs the slide's own Update Version (CentreColumn.update_version: the level, then what each deck does), "Not now" leaves the "+", "Don't ask again" turns the setting off. A slide only looked at, or edited and left once already, is not asked about; closing the window does not ask. Tests in tests/test_centre_gui.py and tests/test_settings_gui.py.

NEW: SlideMage can ask about Update Version when you leave a changed slide.
- Settings → General → Versions: "Ask about Update Version when leaving a changed slide" (off by default).
- When you switch away from a slide you edited and it shows a "+", SlideMage offers to make the changes a version now; "Not now" keeps the "+", and "Don't ask again" turns the question off.
