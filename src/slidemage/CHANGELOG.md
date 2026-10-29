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
- Saving as you type, the "+" on the version line and Update Version are described in the manual.

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

v8.23.0 (2026-10-18, direct instruction: "Modify the dropdowns in this menu so they show the full AI model names at least when opened" and "Is the "Update Version" button always active? Shouldn't it be disabled when no edits have happened? Also, rename it to "Update version""): AI setup (the ▾ of the AI switch): ai_setup.fit_list_to_items() makes the open list of each model picker as wide as its longest entry (the closed boxes stay a fixed share of the 480 px popover), and the closed box's tooltip is the full name. Source view: the Update version button is enabled only when there is something to make a version of (SourcePane._changes_since_version: edits waiting for their autosave, a "+", or content that differs from the frozen version, as slide_versioning.plan_update() decides); otherwise it is off and its tooltip says why ("No changes since v1.1.0."). A slide that was never frozen but has not changed counts as unchanged: its first edit freezes it by itself. The button is checked again after every write (SourcePane.written). The label "Update Version" is "Update version" everywhere in the app (the button, the Versions panel's "Update version to vX.Y.Z", the dialogs, ⋮ → This deck → "Update version of all changed slides…", the Settings checkbox), in README.md, docs/SlideMage.md and the manual's slides 1an and 1b6. Tests in tests/test_ai_switch_gui.py, tests/test_source_view_gui.py, tests/test_side_panels_gui.py.

NEW: Full model names in AI setup, and "Update version" only when there is something to update.
- The model pickers of AI setup (the ▾ next to the AI switch) show the full model names when opened, and as a tooltip when closed.
- The Source view's "Update version" button (renamed from "Update Version") is greyed out while the slide has no changes since its last version.

v8.23.1 (2026-10-18, direct instruction: "I want the app to work on 1920x1080, can you fix the 15 known Windows layout failures with that in mind?"): the top bar's deck switcher may be wider where there is room: DECK_MAX_WIDTHS full 280 / narrow 220 / tight 200 / tiny 170 px (was 170 everywhere), so names like "t-Uni-Masterdeck-Publishing" show in full on 1920 x 1080 (full bar) and "slidemage-manual" down to the tight bar; at 125 % scaling (1536 px) the bar is the narrow one. The chat's message box (chat/view.py Composer) is as tall as its text up to six lines when there is room, and in a short assistant panel the layout may take it down to two lines (it scrolls) instead of a fixed height covering the pickers and the send button (the window 640 px high). Tests: the test application is styled as ui/app.main() styles it (conftest.qapp: the bundled fonts and the kit's light stylesheet; a test that switches the theme is reset after it) -- unstyled, Windows' own style gave every text button a minimum width of about 80 px the app never shows, which made 7 of the 15 Windows failures; the click-outside test of AI setup clicks through the window as a mouse does; the ⋮ menu may be a few px wider than 520 where its longest entry needs it (533 on Windows); the top bar's density tests measure the widths they need instead of assuming macOS' fonts.

NEW: The top bar shows longer deck names, and the chat box fits low windows.
- On a 1920 × 1080 screen the deck switcher shows names like "t-Uni-Masterdeck-Publishing" in full.
- In a low window the chat's message box shrinks and scrolls instead of covering the buttons below it.

v8.24.0 (2026-10-18, direct instructions: a PowerPoint-like presentation mode for the Presenter PDF; "a slider that lets the user slide through the reveal steps", with one timeline per deck version whose ticks change the reveal logic; single-slide renders of contents slides "put into a minimal deck that contains sections"): three features, planned in docs/plans/presentation-mode.md, docs/plans/reveal-step-slider.md and docs/plans/deck-context-preview.md (each with its implementation notes). Presentation mode (src/slidemage/presentation/, src/slidemage/ui/presentation/): the `present` command (F5, Ctrl+K, ⋮ → This deck, the Compile caret menu) opens the deck's Presenter PDF; each page is slide (left half) plus note page (right half), rendered with PyMuPDF; an audience window full-screen on the second screen and a presenter window built from a layout profile (built-ins "Current large" and "Next large", P switches; optional clock and timer: end time of day or duration, flashing red when reached); one screen or mirrored screens give the slide alone. Keys: wheel, arrows, PageUp/PageDown, Space, Enter step through the pages; digits + Enter jump to the slide with that number (frame -> pages from the Presenter compile's .nav, presentation/frames.py; without a fitting .nav the number is a page); B or . blacks out the projector, F freezes it (navigation moves only the presenter; badge and coloured frame in the presenter's current-slide view); Esc ends. Ctrl + left button is a laser pointer, D pen, E eraser, Delete / Clear clears the page's drawings (kept per page for the show, mirrored to the projector, stored as fractions of the slide); link clicks jump, Alt+Left returns, external links ask first. Keep-awake while presenting (Windows SetThreadExecutionState and the screensaver off for the session, macOS caffeinate, Linux D-Bus inhibit). Missing or stale Presenter PDF: compile first, present anyway, or present the normal PDF without notes. Settings -> Presentation, stored per user in layout.json (key presentation). No code from pympress or pdfpc (GPL). Reveal-step bar (ui/workspace/reveal_slider.py and preview_view.py): under the Preview, a slider over all overlay pages of the slide from an unrestricted render, ticks filled where the selected deck call includes the step, "Deck steps only", dashed ticks for editor-buffer renders, opens on the last step, hidden for one-page slides and in the transcript and presenter views; expands into one timeline per deck version (own numbering per version, a warning where version-dependent macros change the count); a click on a tick rewrites the deck's \slidestep calls for that version (split, merge, convert, back to the plain macro when every step of every version is on; one Undo step); \SMFinalStateForStudents is removed silently once no deck needs it (no new version, no "+", Undo restores it; a flag-only difference no longer counts as a change). Step counts are rendered in the background for the selected slide and 4 neighbours, one process, never while a render of the user's own runs. Deck-context previews (deck_context.py): slides whose own text needs the deck (contents, agendas, current section, cross-references) are typeset in the deck's last whole compile of that version (the page-compile machinery of partial_compile) or, without one, in a skeleton with all the deck's sections and the other slides' agenda titles; a chip says which and can compile the deck; only a render in the deck refreshes the cached snapshot; PreviewTarget gains deck_hash for these slides. Tests in tests/test_presentation_*.py, tests/test_reveal_*.py, tests/test_step_renders.py, tests/test_steps_edit.py and the deck-context tests; menu tests updated for the new entry.

NEW: Present from SlideMage, step through reveal steps, and contents slides that look as in the deck.
- F5 (or ⋮ → Present deck) presents the deck from its Presenter PDF: the projector shows the slide, your screen the current and next slide, the notes and optionally a clock or timer, in a layout you can switch with P.
- Wheel, arrows and clicker keys step through the reveals; a number + Enter jumps to that slide; B blacks out and F freezes the projector; Ctrl + click is a laser pointer, D draws, Delete clears; Esc ends.
- Under the Preview, a reveal-step slider shows every step of the slide and which ones the current deck includes; expanded, it shows one timeline per deck version, and clicking a tick adds or removes that step in that version.
- Contents, agenda and section slides are previewed as they look in the full deck.

v8.25.0 (2026-10-18, owner decision, docs/plans/idle-background-rendering.md): the footer timestamp is removed entirely. The footer keeps the slide id, version and language and the deck version, and loses the compile date and time, so wrappers no longer change between compiles (latexmk no-rewrite) and PDFs are reproducible. Removed: the template's SMFooterTimestampOverride, the .timestamp build file and its writing/reading (Slidemaster_preamble_base.tex), the Build options checkbox 'Include footer timestamp' with the workspace state and signal behind it, the footer_timestamp argument of CompileJob, SnapshotOptions, the preview renderers, the render service, the workspace tools and the readability check, the timestamp lines of the slide preview wrappers, the timestamp fields of compile records and snapshot manifests, and the Preview's 'Timestamp setting changed' state. \SMShowCompileTimestampfalse/true and \SMCompileTimestamp stay as harmless no-ops, so decks that still call them compile unchanged (nothing to migrate); old compile records and snapshots stay readable. The manual slides drop the timestamp option and the footer-arrow slide measures the old footer width. Tests updated.

NEW: The footer no longer shows the compile date and time.
- The Build options checkbox 'Include footer timestamp' is gone; the footer shows the slide id, version and language and the deck version only.
- Decks that still use \SMShowCompileTimestampfalse compile as before.

v8.26.0 (2026-10-18, idle-time background rendering, docs/plans/idle-background-rendering.md): SlideMage renders the slides of all decks in the background while it is idle, with every reveal step, so they are ready when a deck is opened. render_key.py is the content-addressed key: a unit (one deck slide call in a view and language, unrestricted: no `steps`) has a fast key (SHA-256 of the slide file's bytes, call, view, language, the deck's preamble, template, TeX engine line and OS, the latexmk rc files) and a manifest of every project or framework file the render read (from the render's recorded inputs, preview_build.recorded_inputs), each with its SHA-256; TeX's own files are covered by the engine line and, for a render made on this computer, a stat stamp. A render is current only if the key and every manifest file still match; one that differs only in the footer page number is "fresh, numbering differs" and is refreshed last. dep_hash.py hashes files with a (size, mtime) shortcut, never trusting or keeping the hash of a file modified within 3 s and giving none to a file that changes while read, with an audit that re-reads a sample. render_store.py keeps the renders on this computer, never in the project (a synced project must not carry gigabytes): write-once folders in the user's cache folder (project.cache_dir()/render-store/<hash of the project folder>/objects/<key>[.bg]/: slide.pdf, one 1280 px PNG per page, meta.json written last) with a SQLite index beside them, rebuilt from the meta.json files; an earlier `.previews/render-store/` in a project is deleted when the store opens. A render of the sweep (`.bg`) replaces the provisional one of the reveal slider with the same key; eviction removes superseded, old, orphaned and least recently used renders against a user-set disk limit (Settings, default 2 GB), protecting the recently used decks; failures are remembered by key and input state (deterministic ones never retried automatically, transient ones with 5 min / 30 min / 3 h backoff, three times at most). render_scheduler.py is the one queue (foreground, reveal slider neighbours, idle): a better class cancels a running worse job at once (even for the same key) and requeues it, user input cancels an idle job only after 20 s of running, one process by default (two in the Fast profile), a rest of 25 % of each idle job's duration (Normal), and idle jobs run with below-normal process priority (compiler.CancelToken.low_priority). idle_gate.py decides when idle jobs may start: 30 s without input, 20 s after start, nothing busy (busy.py registry, a compile, an AI task, the Preview, a modal dialog), not on battery (power_status.py: GetSystemPowerStatus / pmset / sysfs), CPU below 70 %, 5 GB free disk. background_renders.py lists what is outstanding in the owner's order (the open deck, decks whose course meets within 7 days from the cached schedule that course_schedule.fetch_schedule keeps in the cache folder, decks opened on this computer by recency, the rest by file date; per deck instructor, During course, After course; per version from the slide last looked at, wrapping; decks switched off or archived left out) and renders each unit through slide_preview.render_slide_to_pdf (no snapshot, all reveal steps: all_steps) with its wrapper, build caches and precompiled format in the store's work/ folder outside the project (preview_build.compile_cached(workspace=): latexmk runs in the project's decks/ folder with `-cd-` on the wrapper's absolute path), so a background render creates no file in the project; slides that need their deck (contents, agendas: deck_context) are left to the Preview with a second raster child (preview_raster_client.RasterClient, new; the module functions use a shared instance as before). The Preview shows a current stored render at once instead of an older snapshot (preview_view._stored_pixmap; not for a \slidestep call with steps, one reveal step or a part of the slide). UI: ui/workspace/background_previews.py (application-wide input watcher, deck usage, a dial at the bottom left of the centre column with the share of up-to-date renders of all prepared decks and a tooltip that explains it, which opens a status window with every deck's renders per version and its state, in the order they are worked through, with Pause, Render now and the failed slides; a chip beside it while there is work or something failed, with a menu: decks in priority order, stored size, Pause, Render now, leave the open deck out, failed slides; Progress/DeckProgress count renders per deck and version), Settings → General → Background previews, archiving a deck removes its renders (deck_actions.do_archive_deck). Tests: tests/test_render_key.py, test_render_scheduler.py, test_idle_gate.py, test_background_renders.py, test_background_previews_gui.py; tests set SLIDEMAGE_NO_BACKGROUND_PREVIEWS so a window under test renders nothing by itself. Not built: batching several slides per LaTeX run, and reusing one render for equivalent views (deferred until preview_equivalence.py of the ui-redesign branch is merged).

NEW: SlideMage prepares your slides in the background whenever you have not touched it for 30 seconds, so decks open with their previews already rendered.
- All reveal steps of every slide are rendered, most recently used decks first and the instructor version first; a deck whose files did not change is never rendered again.
- A small dial shows how much of all your decks' previews is up to date (hover for details); click it for a window with every deck and version. A chip beside it shows what is left, and can pause, render now or leave the open deck out. Nothing runs on battery, during a compile or while an AI task works.
- Settings → General → Background previews: switch it off, plug-in only, speed, disk limit (2 GB by default). The renders are kept on this computer, not in your synced project.

v8.27.0 (2026-10-18, Jürgen Fleiß's ui-redesign branch, PR #4, merged after v8.26.0 by the owner's instruction "reconcile Jürgen's proposed changes and fix the conflicts"; the footer compile timestamp his branch still carried is left out, as v8.25.0 removed it; his footer switches \SMFooterHide{id,deck} stay): integrates develop's render cleanup settings, Windows fixes, version reminders, full model names and responsive layout with the branch's preview rendering work and Claude chat defaults, selected-slide version updates and localized image descriptions. Keeps the shared batch version update flow and develop's sentence-case labels. AI setup tooltips retain both full model names and the restart guidance for Claude Code chat. The narrowest top bar uses slightly tighter spacing so its controls fit at 1024 px with the bundled Linux fonts. Branch-only preview entries formerly numbered v8.21.0-v8.21.2 are consolidated here to avoid colliding with develop's release numbers.

Preview requests capture source and per-view deck targets, and share a persistent dependency-validated completed cache. Sequential all-view batches retain partial successes; full-page reveal sequence signatures permit image deduplication without sharing PDFs. Preview actions and Claude Code/chat tools support explicit/all views, forced rerendering, per-view outcomes and guarded publication to the pane. The real LuaLaTeX acceptance probe records cold/warm/restart and dependency invalidation metrics.

Left-panel thumbnails prefer the same verified final slide image as the main Preview, including the selected course view, language, deck footer, occurrence, pinned version and editor revision. Shared Instructor snapshots are labelled as reference images. Hidden slides have no thumbnail in that view, and editor changes update thumbnail freshness without rebuilding the tree.

Preview dependencies now track the precompiled preamble's source inputs rather than its generated format file. When dependency validation expires a saved preview, each course view can still display its own integrity-checked previous render with an explicit older-preview notice, including after restarting the app. Historical images never count as fresh cache hits or skip rendering.

refresh_preview now defaults to all three course views instead of Instructor only; an explicit view still limits the refresh. Claude Code guidance uses view=all for general preview inspection and identifies the deck-wide refresh as a legacy Instructor snapshot operation.

NEW: Faster, consistent course previews, saved Claude chat defaults and version updates for selected slides.
- Render one or all course views, reuse unchanged previews, and keep earlier images visible while previews refresh.
- Slide thumbnails match the selected view and language; hidden slides have no thumbnail in that view.
- Choose a default Claude Code chat model and effort in AI setup; Restart applies the change to an open terminal.
- Right-click multiple selected slides and choose Update versions… to use one shared Patch, Minor or Major choice.
- German slides and decks receive German short and long image descriptions in media/alt-text.json.
- Keep develop's render cleanup settings, optional version reminders and Windows layout fixes.

v8.27.1 (2026-10-18, owner reports: "The previews indicator overlaps the slide id on my screen" and "this slide definitely has reveal steps, yet where is the slider?"): the background renders' dial and status chip are laid out in a row of their own under the centre column's views (CentreColumn.status_row; background_previews places them there and shows the row only while the dial is shown) instead of floating over the bottom-left corner of the views, where they covered the Preview's slide id and the Source view's last lines. The reveal-step bar appears at once for a slide whose text has an overlay command or spec (reveal_steps.SlideScan.may_reveal: \pause, \only, \uncover, \onslide, \visible, \alt, \conditionalpause, \deck..., <...> specs, visible on=) and says "Counting reveal steps…" until the all-steps render (some seconds) has counted them (RevealBar.show_counting); before, it stayed hidden until then. Slides without such commands show no bar while they are counted. Tests in tests/test_background_previews_gui.py, tests/test_reveal_bar_gui.py and tests/test_reveal_steps.py.

NEW: The background-render status no longer covers the slide id, and the reveal-step bar shows up at once.
- The background-render dial and its status sit in their own row under the slide, so they never cover the slide id or the editor.
- For a slide with reveal steps the step bar appears straight away and says "Counting reveal steps…" until the steps are known.

v8.27.2 (2026-10-18, owner decision: move the preview cache of the ui-redesign work out of the synced project folder): the completed-render cache (preview_cache.PreviewCache: rendered PDFs, their images and records) and the page-image cache (preview_pages) live in this computer's cache folder, project.preview_cache_dir(root) = project.cache_dir()/preview-cache/<project id>/render-results and /page-images, not in the project's .previews/ (which a synced project folder such as a cloud drive carried along). An earlier copy in .previews/render-results is deleted when the cache opens; it is only a cache. project.project_id(root) is shared with the background renders' store (render_store.project_id). The slide snapshots in .previews/slide_previews stay where they are. Tests in tests/test_preview_requests.py and tests/test_preview_pages.py.

NEW: Preview caches stay on your computer.
- Rendered previews are cached in SlideMage's own folder on this computer, so a project in a cloud folder no longer syncs them.

v8.27.3 (2026-10-18, owner reports on v8.27.2: a dark gap in the middle of the "w" of a title, the ochre "Checking current source" bar flashing every few seconds, the background-previews popup closing by itself, and a blurry preview): Fonts: weight 600 (the Preview title, assistant and task titles, the focused slide in the list, ...) had no bundled file, and Windows fattened Roboto Medium for it, which left dark gaps where the strokes of w and W overlap; every Roboto and Roboto Mono file is bundled now (Roboto 3 v3.016 from googlefonts/roboto-3-classic: all static weights with their italics, Roboto Condensed and the variable Roboto[ital,wdth,wght].ttf; Roboto Mono v3.001 from googlefonts/RobotoMono: all static weights with their italics and both variable files; OFL), so every weight from 100 to 900, upright and italic, has a real face and Qt never thickens or slants one itself (bold Roboto Mono, for one, was synthesized far too wide); ui/kit/fonts.py loads every .ttf in assets/fonts, the static files first. Roboto 400/500/700 upright render as before. Preview: a periodic recheck of an unchanged slide keeps the verified image current while it runs (PreviewPane._select_in_background), instead of marking it "Checking current source and settings…" every five seconds; a check that finds it stale still replaces it. Kit: Chip parents its icon and label when it makes them, since setVisible(True) on a parentless icon showed it as a window of its own for a moment, which closed any open menu or popup on Windows (the Preview rebuilds its chips on every refresh); the same order fix in the add-slide dialog, the image-replace dialog and the AI-fix card. Reveal steps: step pages are rasterised 1920 px wide (reveal_steps.PAGE_WIDTH, was 130 dpi: 820 px), as are background renders (background_renders.STORE_WIDTH, was 1280; render_key.RENDER_SCHEMA 3 renders them again). Tests in tests/test_ui_kit_gui.py and tests/test_preview_queue.py.

NEW: Sharper step previews, a calm status line and clean bold titles.
- Reveal steps and background renders are shown at full resolution, as sharp as the normal preview.
- The ochre "Checking current source…" note no longer flashes every few seconds, and the background-previews menu and window stay open.
- Every weight and italic of the interface fonts is built in: semi-bold titles no longer show dark gaps in letters such as w, and bold or italic code text looks right.

v8.28.0 (2026-10-19, preview steps, presenter pen, PDF without a project): Preview: the slide on show is counted at once (a foreground step render that stops a neighbour's background count, StepRenderQueue.submit) instead of waiting for the idle probe and for the neighbours ahead of it; while counting, only the track says "Counting steps…" (the label below it stays empty). The mouse wheel over the page goes through the deck as a presentation does: reveal step by reveal step, then slide by slide (PageView.wheeled, PreviewPane._on_wheel, CentreColumn._go_adjacent; forward opens the next slide at its first step, back the previous one at its last). The Render split button's menu is no longer replaced while it is open (PreviewPane._rebuild_menu waits for it to close), which closed it at every refresh. Presentation: the Pen button of the presenter window opens the pen's colour and width for this presentation only (the saved ones are untouched, also when the layout is switched); the Settings sheet gets a laser pointer size (PresentationSettings.laser_size); Pen, Eraser, Black and Freeze are lit while active. Start screen without a project: "Present a PDF…" presents a presenter PDF or any plain PDF (ui/presentation/launch.present_pdf_file) and returns to the start screen afterwards. Not run in this checkout (no Qt/pytest environment); tests/test_reveal_bar_gui.py adjusted for the empty label.

NEW: Faster step counting, wheel navigation, a pen you can set while presenting, and presenting a PDF without a project.
- The reveal steps of the slide you are looking at are counted straight away, and only one "Counting steps…" is shown.
- Scroll the mouse wheel over the preview to go through the deck like a presentation: step by step, then slide by slide.
- The Render menu stays open instead of closing every few seconds.
- Click Pen in the presenter view to set its colour and width for the current presentation; the laser pointer size is a setting; active tools are highlighted.
- On the start screen, "Present a PDF…" shows a presenter PDF or a plain PDF without opening a project.

v8.29.0 (2026-10-19, details view lists related files): Details view: a panel "Other languages and earlier versions" lists the slide's translation partner (with a "may be out of date" chip, slide_language.translation_link) and its frozen versions, newest first, each with an Open button that opens the file in the Source view (DetailsPane.open_requested -> CentreColumn.open_file). Not run in this checkout (no Qt/pytest environment).

NEW: The slide Details page lists the slide's other-language version and its earlier versions.
- Each entry has an Open button.

v8.29.1 (2026-10-19, idle rendering is never interrupted by the user): Background rendering: CPU load, battery-independent idle time and input now only decide whether a job may START (IdleGate: below CPU_LIMIT and SWEEP_SECONDS-long continuation once a job has started, so the sweep's own load does not stop it); mouse movement, keys, wheel and viewing slides never stop a running job (RenderScheduler.user_active no longer cancels). Only a job of a better class (the Preview's own render, the reveal-step renders) interrupts it, as before. The application-wide input watcher ignores mouse moves that Qt generates itself (not spontaneous, or the cursor did not move), which reset the 30 s idle timer every time the Preview refreshed. Tests in tests/test_idle_gate.py and tests/test_render_scheduler.py.

NEW: Background previews are no longer interrupted by mouse movement or by CPU load once they have started.
- They start only when you have been idle and the CPU is below 70%, and then keep going.
- A render you ask for yourself still takes priority.

v8.30.0 (2026-10-19, reveal steps from the render store): The reveal bar takes the step pages of a saved slide from a current render in the render store (the background sweep's, or the bar's own earlier one) instead of rendering them: PreviewPane._adopt_stored_steps, BackgroundPreviews.stored_pages. When the bar does render a slide itself, the PDF and its pages are kept in the store as a provisional object (StepRenderQueue on_pages -> BackgroundPreviews.store_steps -> BackgroundRenderer.store_reveal), so the count is instant the next time, also after a restart. Not for a slide that needs its deck's context, a \slidestep with steps, or the unsaved buffer. The application-wide input watcher test now covers spontaneous mouse moves only. Wording: the course-system code, the Admin slides tab, the deck settings placeholder and comments/docstrings no longer name the university (identifiers and file names that belong to a project's template are unchanged).

NEW: The reveal steps of a slide that was rendered before appear at once.
- Steps are read from the stored preview render, and kept for next time when they had to be counted.

v8.31.0 (2026-10-19, licence change and templates from the project): The licences change; nothing changes for users. The app is now GPL-3.0-or-later, the Slidemaster LaTeX framework LPPL 1.3c or later, the Gotham theme stays LPPL 1.3c (unchanged from its release v1.2.5.a; one stray comment in beamerouterthemegotham.sty was removed to match it), documentation and the example project stay CC BY-SA 4.0. Releases up to v8.30.0 remain available under CC BY-SA 4.0. New: LICENSE (overview), LICENSES/ (the full texts), latex/LICENSE, REUSE.toml, SPDX headers in every Python, Lua and Slidemaster LaTeX file, THIRD_PARTY_NOTICES.md (tools/third_party_notices.py), the licences in the About sheet's License tab and bundled in the executable (packaging/slidemage.spec), a source archive attached to each release (.github/workflows/release.yml), pyproject license metadata. The copyright line no longer names an institution. Templates: the app knows no institution by name. A template is any Slidemaster_preamble_<key>.tex of the project or the framework (slide_snapshot.available_templates), found by the \input in a deck's preamble (detect_template); the default for a deck without one and for slides rendered alone is the generic "slidemage" template, not "uni-graz"; its name in dialogs is the `% SlideMage template name: ...` line of its file, else its key read as words (slide_snapshot.template_label); its name in cached preview file names is its key in capitals (UniGraz stays UniGraz). Image folders of the template schemes are every schemes/<name>/ folder (alt_images.scheme_dirs). Courses: the course URL decides host and instance (course_schedule._course_parts), so any CAMPUSonline course page works. preview_equivalence keeps the digests of audited project templates without naming them, and its digests of the framework files changed with the new headers (comments only) and the generic preamble's template line. A deck without any template \input is now typeset with the generic template when previewed alone. Tests adjusted in tests/test_templates.py and tests/test_update_all_previews.py.

NEW: SlideMage is now free software under the GPL, and it no longer has any institution built in.
- Licences: the app is GPL-3.0-or-later, the LaTeX framework LPPL, the documentation CC BY-SA; see LICENSE and the About sheet.
- Your institution's templates are found in your project; the course schedule works with any CAMPUSonline course page.

v8.31.1 (2026-10-19, progress card names the running job): The progress card of a multi-job run (all views of a deck) named the first job that was running or being moved, so for the 30 s and more a finished version's PDF takes to be moved into place it said "Compiling <that version>" and "moving the PDF into place" while the next version was compiling and the bar moved (JobPanel.refresh now prefers the running job). New: status_trace.StatusTrace, wired into the compile slot, writes every change of what the card shows, with the time and the causing log line, to status-progression.log in SlideMage's config folder (the newest run; SLIDEMAGE_STATUS_LOG names another file). A replay of a real compile of three versions of a 397-slide deck found nothing else wrong: each version's "starting" lasts 1 to 4 s, the percentage never moves back, it reaches 100% at the last PDF. Tests in tests/test_job_panel_gui.py and tests/test_status_trace.py.

NEW: The progress card shows the version that is being compiled, and a log of the progress is kept.
- While a finished version's PDF is moved into place, the card now names the version that is compiling.
- A log of what the progress card showed, and when, is written for each run.

v8.32.0 (2026-10-19, deck compiles feed the Preview): After every successful whole-deck compile that is recorded (compile_records.py), the render store keeps the last page of each slide the PDF shows, for the compiled view and language (compiler.COMPILE_LISTENERS -> BackgroundPreviews._on_compiled -> BackgroundRenderer.ingest_compile; origin "compile", no slide PDF, marked partial). The Preview takes it through the same lookup as a background render (BackgroundPreviews.stored_page), so the slide shows as a current render without the "Shared Instructor reference; not verified..." note. It stays current while the slide's own file and everything else the compile read are unchanged, with the compile record's hashes as the manifest: other slides do not count, and a picture or snippet counts only when the slide mentions it by file name (BackgroundRenderer._compile_manifest). A slide that changed, or a changed preamble, template, framework, deck file or bibliography, makes it stale at once. Not stored for a \slidestep call, a slide that needs its deck's context, chapter and page compiles and the presenter PDF. A partial record is never used as the list of reveal steps (stored_pages) and gives way to the reveal bar's own full render (store_reveal); the idle sweep still renders the slide in full (a compile record is not "final"). RenderStore.put takes no PDF for it. Checked on the real IA2 compile: 374, 371 and 378 slides stored for the three versions in 45 to 118 s, k4p current in all three. Tests in tests/test_background_renders.py.

NEW: A compiled deck now fills the slide previews at once.
- After you compile a deck's versions, its slides show their compiled page as a current preview, without the "not verified" note, until the slide or what it depends on changes.

v8.33.0 (2026-10-19, folder build, one-click slides, steady chip): Releases: every release publishes two builds per platform, the single file (SlideMage-windows.zip, SlideMage-linux.zip) and the folder (SlideMage-windows-folder.zip, SlideMage-linux-folder.zip: SlideMage[.exe] and _internal/), which starts in about a quarter of the time because it does not unpack itself at every start (9 s against 2.5 s on the test machine). packaging/slidemage.spec builds both, .github/workflows/release.yml attaches both. Updating: an installation updates itself with the build it is (updater.install_flavour, asset_names). A single file is replaced as before. A folder cannot be replaced while it runs, so the update is unpacked next to it as "<folder>.update" (stage_folder_update), and a detached helper script (swap_script, spawn_folder_swap) waits until SlideMage has ended, swaps the two folders (the old one stays as "<folder>.old" until the next start removes it) and starts the new version with the same project when the user chose "Restart now"; otherwise the swap happens when SlideMage is closed. The Windows helper is tested for real in tests/test_updater_folder.py. Slide list: a click on a slide opens it (a click with Ctrl or Shift only selects; section markers keep their double click). Background previews: the status chip and dial stay blue ("Preparing previews") for the whole sweep instead of flipping to the grey "Previews" in the gaps between two jobs (BackgroundRenderer.sweeping, IdleGate.sweeping); they turn grey when something holds the sweep back or it is paused.

NEW: A faster-starting folder version, one-click slide opening, and a steady preview status.
- Each release now comes as a single file and as a folder (faster to start); the automatic update installs the same kind you have.
- Click a slide to open it.
- The preview status stays blue while previews are being prepared.

v8.34.0 (2026-10-19, direct instruction: "can the preview updating be parallelized? These are many small, independent tasks" and "Go with the fast option as a default, but implement a rule to start new threads only when the CPU use is below 70%"; then "When the user clicks the preview update status, can the popup window list the individual threads?"): Preview renders run several at once. On Windows they never did: every compile holds the project's preview maintenance lock "shared", and filelock.build_lock took it with msvcrt.locking, which has only exclusive locks, so all preview compiles of a project (foreground, reveal steps, background) ran one after another; it now takes Windows locks with LockFileEx, which has shared ones (measured on 24 cores, eight slides of the example manual from scratch: 96 s one at a time, 17 s eight at once). Background renders: the profiles scale with the machine (background_renders.PROFILES: gentle 1, normal a quarter of the cores, fast half of them, at most 16) and "fast" is the default; the scheduler runs at most `workers` jobs at once and starts one beside running ones only while the processor is below idle_gate.CPU_LIMIT (70%; RenderScheduler `may_add`), except the user's own render; one CpuMeter (power_status.shared_cpu_meter, measured at most once a second) answers every such question; progress.working follows every running job. Batches: preview_batch.render_batch renders its requests through parallel_runs.run_all (up to half the cores, the same CPU rule); views that make the same image stay one unit, in order, so the first renders and the others find it; results keep their order, and progress events carry `done` (how many finished), which the compile panel and the Preview's "Render all views" status show. "Rerender all previews for this deck" and "Render all views" use it. Images: the module-level raster functions use a pool of up to four raster children (preview_raster_client.RasterPool), so parallel renders do not queue for one. Status window (a click on the dial): a "Running now" list with one row per render (deck, slide, version, language, background or reveal steps, how long), and how many may run at once with the processor's load. Settings → General names the number each profile allows. Tests in tests/test_parallel_runs.py, tests/test_render_scheduler.py, tests/test_background_previews_gui.py, tests/test_update_all_previews.py and tests/test_preview_queue.py.

NEW: Previews render several at once.
- On Windows, previews were rendered strictly one after another; now several run in parallel (up to half your processor cores), which makes rendering a whole deck many times faster.
- Background previews use the "Fast" setting by default; another render only starts while the processor is less than 70% busy, so your computer stays responsive.
- Click the background-previews dial to see every render running right now.

v8.35.0 (2026-10-19, direct instruction: "Do option 1" -- more renders at once, one shared limit): A preview render mostly waits (process starts, file access, latexmk's bookkeeping) and computes only in short bursts, so half the cores left the processor mostly idle. parallel_runs.default_workers() and the "fast" profile now allow one render per logical core, at most parallel_runs.CEILING = 32 (about 300 MB each); "normal" stays a quarter, "gentle" one. One budget for the whole process (parallel_runs.RenderBudget, parallel_runs.BUDGET): the background renders, the reveal-step renders (both through RenderScheduler, new `budget` argument) and the user's batches (parallel_runs.run_all, new `budget` argument) draw on it, so together they never run more than the limit and the 70% rule looks at the total. The first render in the process always starts; the user's own render (P_FOREGROUND) and a batch's first take a place without waiting; idle background renders stand back while a batch wants places (RenderBudget.want). Measured on 24 cores, 17 slides of the example manual from scratch: 226 s one at a time, 48 s with v8.34.0, 30 s now. Settings' tooltip explains the shared limit. Tests in tests/test_parallel_runs.py and tests/test_render_scheduler.py.

NEW: Even more previews at once.
- Previews now render up to one per processor core (before: half), and background previews, reveal steps and "Rerender all" share that limit. A whole deck renders about a third faster again.

v8.36.0 (2026-10-19, direct instruction: "check 2a through c, finally do option 3" -- what one preview render costs, and the render that took 96 s): Three fixes in the preview build. The precompiled preamble (preview_format) never worked on Windows: the format build gave TeX the source as a Windows path, whose backslashes TeX reads as commands, so every format was marked bad (all five of a real project's, and every background one); MiKTeX also ignores TEXFORMATS, so -fmt now names the format file there (preview_format.fmt_option), and fontspec's Lua module, which a format cannot keep, is loaded again at each job start (PRELUDE_TAIL; without it a slide's font commands failed). The check that a format is current (about a quarter second) runs under a shared lock now, so renders that start together no longer queue for it one by one. And luaotfload, LuaTeX's font loader, tests its cache folder by creating and deleting a file of one fixed name, so LuaLaTeX runs that start at the same moment can make each other fail that test; luaotfload then quits, every font is missing, MiKTeX spends about a second per font trying to make one, and the run fails (the 96 s render: this, in several passes, then the retry without the format, which then also switched the format off). preview_build.run_preview recognises it (font_cache_race), runs latexmk again with all passes after a short pause, up to three times, and neither the render nor the format build marks the format bad for it (FontCacheBusy). With the format, a slide that cites nothing can finish without biber; latexmk then records the deck's bibliography as a missing source under the bare name the .bcf gives, and recorded_inputs took that for a project file that does not exist, so the background store called such a render unstable forever; sources latexmk recorded as missing (size -1) are no longer inputs. Measured on 24 cores, one slide from scratch: 12.5 s before, 7.5 s now; every pass with the format about 1.6 s instead of 2.9 s, with identical pixels; 17 slides of the example manual: 29 s with v8.35.0, 20 to 24 s now. Checked and left as they are: skipping biber when a slide cites nothing would save 1.4 s, but whether it cites is only known after the first pass (image sources from alt-text.json cite through Lua), so citing slides would get slower; latexmk's third pass changes no pixels but comes from its own caution about newly read helper files, and calling LuaLaTeX directly instead of latexmk would replace the dependency records the reusable preview builds rely on (a change to plan with the build code's author). Tests in tests/test_preview_build.py, one of them with the real engine when LuaLaTeX is installed.

NEW: Previews render much faster on Windows.
- The precompiled deck preamble now works on Windows, which makes each preview render about 40% faster.
- An occasional preview that took a minute or more, when many renders started at once, now simply runs again.

v8.37.0 (2026-10-20, direct instruction: "look into the third latexmk pass" and "implement the third-pass fix", section 1.2 of docs/plans/preview-passes-and-direct-lualatex.md): A slide's first preview render ran LuaLaTeX three times (lualatex, biber, lualatex, lualatex) although the third run changed nothing, not one pixel; latexmk ran it for three reasons, each enough on its own. biblatex writes the checksum of the .bbl it read into the .aux ("nohash" in the first run) and flips its request flags in .run.xml once biber ran, so latexmk saw both change in the second run; latexmk tracks the .bbl itself, and preview builds now pass it an rc file of SlideMage's own (preview_build.PREVIEW_LATEXMKRC, with -r, previews only) whose $hash_calc_ignore_pattern leaves those lines out of its checksums. latexmk normalised the build folder into Git-for-Windows Perl's spelling (/c/..., /tmp/... for the temp folder) while LuaLaTeX's recorder file names it C:/..., so it held every helper file twice and the second name looked newly read; the same rc file turns that normalisation off ($normalize_names = 0; previews give -outdir and -auxdir themselves). And latexmk treats a file that a run reads for the first time and then rewrites as one that did not exist before, which always asks for one more run: .aux and .nav escape that because LaTeX prints "No file X.nav." when they are missing, so latexmk knows them from the first run, but the framework read .ovl (\SMFinalStateForStudents) and .top (Top Margin) with \InputIfFileExists, which prints nothing, and biblatex reads .run.xml silently. Slidemaster_preamble_base.tex now prints the same "No file" line for a missing .ovl and .top (this helps whole-deck compiles too), and the preview wrapper does so for .run.xml after \begin{document} (preview_build.RUN_XML_NOTE; before it is the precompiled format). Both are part of the preview configuration key (schema 3), so every preview build starts fresh once; preview_equivalence's pin of the framework file is updated (only the log line changed, no view rule). Checked on every example slide in the Instructor view and every fourth in both student views, 137 forced renders before and after: all 131 that render are pixel-identical (the other six fail both ways, the two LaTeX installation slides), LuaLaTeX runs 332 -> 254, summed render time -19%; renders that still take three or more runs need them (a TikZ remember-picture mark that moves in the second run, the Top Margin correction that oscillates up to latexmk's limit, a switch of view in a build folder the views share). An edit render was already one run and an unchanged slide none. Tests in tests/test_preview_build.py, one with the real latexmk, LuaLaTeX and biber.

NEW: A slide's first preview renders faster.
- Previews no longer run LaTeX a third time when two runs have settled the slide; a deck's previews build about a fifth faster.

v8.38.0 (2026-10-20, direct instruction: "Whenever I click a new slide, a kind of minimized slidemage window pops up in the middle of the screen" and "make the slide preview a bit bigger in split mode ... reduce the right-hand bar's minimum width ... reduce the margin to the left and right of the preview"): Two widgets flashed up as small windows of their own on every click on a slide. A widget without a parent that is shown, even for one event, is a top-level window. The Source view's status line called setVisible(True) before it was in its layout (source_file._build_status_line; now it is only ever hidden there, for the bibliography). And one click refreshes the side panel twice (the new focus, then the opened file), so the second refresh removed the "Used in decks" box the first had just built; clear_layout detached it with setParent(None), and a widget that was never shown nor hidden is then shown as a window until deleteLater runs; clear_layout now hides each widget first. Found by logging every top-level Show event while the real window clicked through slides (none now in Preview, Split and Source); tests/test_stray_windows_gui.py does the same. Split view: the right-hand column can be dragged to 312 px instead of 360 (side_panels.MIN_WIDTH; 360 stays the default and what a double-click on the handle gives back); 312 px is what its widest content needs, the Visibility panel's card and the assistant's controls, once the assistant's model chip shortens a long model name with "…" (Chip(elide=True); the full name is in its tooltip) instead of widening the column (a local Ollama model's name had made it 280 px). The Preview's side margin is 12 px instead of 24, and the page keeps 8 px instead of 24 at its sides, room for its shadow. In a 1600 px window with both columns at their least, the page in the Split view grows from 320 x 180 to 424 x 238 px.

NEW: No more flicker when you click a slide, and a bigger preview in Split view.
- Clicking a slide no longer flashes a small window in the middle of the screen.
- The right-hand column can be made narrower, and the preview uses more of its width, so the slide in Split view is about a third larger.

v8.39.0 (2026-10-20, Jürgen Fleiß's PRs #5 and #7, released with v8.34.0 to v8.38.0 at the direct instruction "make this final version a release"): Two changes by Jürgen Fleiß. On his branch, which started from v8.33.0 before v8.34.0 to v8.38.0 existed, they were v8.33.1 and v8.33.2; they are one release here. Slide clicks keep the current view: a plain click on a slide opens its source with keep_mode=True, preserving the centre column's current mode; Enter and a double click still open the Source view; tests cover the click and Enter paths. Linux startup crash: the app could show its window and then crash with SIGSEGV while Qt WebEngine initialised focus, in Shiboken's QObject-wrapper conversion called from the application-wide event filter of the background-preview input watcher. On Linux the watcher now uses per-widget event filters, discovers new widgets every 250 ms and polls cursor movement while the app is active, avoiding wrapper conversion for Qt WebEngine's private focus objects; other platforms keep the application-wide filter without polling. Stopping the watcher removes the filters for the selected mode. GUI tests cover both modes, input from new controls and cleanup. Also (direct instruction, a traceback from the downloaded v8.33.0: "FileNotFoundError: ... pymupdf\layout/resources/onnx/layout_rf2.4.1+imf1.yaml"): the published v8.33.0 Windows build stopped at startup. pyproject.toml asked for any PyMuPDF, so the release workflow installed PyMuPDF 2.0, which loads a layout-analysis model when it is imported, and PyInstaller did not bundle the model's files; local builds still had 1.28. PyMuPDF is now kept below 2.0 (pyproject.toml, uv.lock), and the release workflow starts every build once with the new --self-test flag (cli.SELF_TEST_FLAG: imports every module the window needs, exits 0, or 1 without the message box a windowed build would open) before anything is uploaded.

NEW: Clicking a slide keeps the Preview, a Linux startup crash is fixed, and the Windows download starts again.
- A plain click on a slide opens it without leaving the Preview; press Enter or double-click to open its Source view.
- SlideMage no longer crashes during startup on Linux.
- The downloaded Windows version of v8.33.0 stopped at startup; this release starts, and every release is now started once before it is published.

v8.39.1 (2026-10-20, direct report "it was at 2%, then 0% again" and "the count just reset to 0 again"): Background previews rendered the same slides over and over without keeping them, so the dial rose and fell back to 0 % at every replan. v8.37.0 changed Slidemaster_preamble_base.tex, which every render's manifest names but the render key leaves out, so every render made before it became stale while keeping its key. The new render of an unchanged slide had that key, and RenderStore.put returned the stored object of the same name without writing the new one; the sweep counted the slide as done, and the next scan found the stale render again. put now keeps a stored object only when it was rendered from the same inputs (RenderStore._same_render: manifest, TeX files, page number, stability) and otherwise replaces it; a reveal render likewise gives way only to a current background render of its key. Tests in test_render_key.py; checked against a copy of the affected store, where the same four slides went from stale after every render to fresh.

NEW: Background previews keep what they render again.
- After v8.37.0 the background previews rendered the same slides again and again and the dial kept falling back to 0 %; they now keep each render and the dial climbs.

v8.39.2 (2026-10-20, direct report: "I said to update immediately. The app closed, a command window flashed open for a fraction of a second, but disappeared again immediately. Now nothing seems to happen."): The folder build's updater never put an update in place on Windows. It unpacked the release next to the installation and started a helper script to swap the folders once the app had ended; the helper was started detached, without a console and without input or output handles (the windowed app has none), and cmd ended at once with exit code 1, before it waited or moved anything, while the first console program it ran opened a window of its own (the flash). updater.start_helper now starts it with a console that is never shown and NUL as its input and output; the helper's retry count was in a ( ) block, where cmd expands %tries% only once, so a folder that stayed locked would have been retried forever; the loop is now plain lines. The Windows tests start the helper as the app does (it failed both before) and check that the retry limit ends the script. v8.33.0 to v8.39.1 have the broken helper, so a folder installation of those versions has to be replaced by hand once.

NEW: Updating the downloaded Windows folder version works.
- Installing an update closed SlideMage and then did nothing; it now puts the new version in place and starts it again.
- If you have v8.39.1 or older, replace the SlideMage folder with the downloaded one once; later updates install by themselves.

v8.39.3 (2026-10-20, direct instruction "fix the failing create_slide test here"): test_create_slide_shows_its_returned_preview_in_the_real_window failed in about one run in four, a different case each time: after create_slide the Preview showed "No preview for the ... view yet". create_slide adds the new slide to the deck, and the deck edit starts the header sync (window._regenerate_headers_bg) on a thread of its own; it wrote the new file's "Included in decks" header while the slide's preview rendered, and the Preview drops a render whose file changed meanwhile (PreviewPane._accepts), so the image the tool rendered was never shown. create_slide now writes that header itself before it renders (deck_headers.regenerate_header, one slide; regenerate_headers shares its parts), and the sync then finds nothing to change in the file. New test in test_create_slide.py; the GUI test passed in 40 runs of 40 afterwards. Also (direct report, tth: "Why does this notice not go away after rendering?"): a slide that needs its deck (sections, agendas) is typeset in the deck's last compile (deck_context.render_in_deck), which wrote no .inputs.json beside its PDF; the preview cache keeps no verified render without one, so the Preview went on saying "Previous render for instructor, EN; render to verify current source and settings." after every render of such a slide. render_in_deck now records what the page compile read, with the deck compile's own files (its .aux and the rest it restores) and without the deleted page build folder and wrapper (left out by name: latexmk's database spells the folder as Git's Perl does, /d/...). On the reported slide the Preview's check went from previous to verified after one render; test_deck_context.py checks the record.

NEW: Previews show up when they are rendered.
- After the assistant created a slide, the Preview sometimes said there was no preview yet; it now shows the slide the assistant rendered.
- Rendering a slide that needs its deck (a section overview, an agenda) now clears the "Previous render ... render to verify" notice.

v8.39.4 (2026-10-20, direct instruction "start fixing", docs/SLIDE_SELECTION_RESPONSIVENESS_PLAN.md step 2): Clicking the second occurrence of a slide that the deck calls twice ended with the Preview of the first one, and every focus listener ran twice. The press focuses the row with its occurrence key (SlideList._on_current_changed); the release opens the file, and CentreColumn.open_file then called set_focused_slide(bare_id) without the key, which cleared WorkspaceState.focused_occurrence, emitted focused_slide_changed a second time and made _focused_row resolve the first occurrence. open_file now focuses the slide only when its file belongs to another slide than the focused one, so opening the focused slide keeps the occurrence and emits nothing. Opening another slide, a frozen version of a different slide or a translation partner focuses as before. Test in test_centre_gui.py (second occurrence: key, frame number of the Preview target and exactly one focus signal for press and release; Enter keeps the occurrence).

NEW: Clicking the second use of a slide shows that use in the Preview.
- A slide that appears twice in a deck now previews the one you clicked, not always the first.

v8.39.5 (2026-10-20, direct instruction "start step 3", docs/SLIDE_SELECTION_RESPONSIVENESS_PLAN.md step 3): A click on a slide in the Preview built the slide's source editor (a SourceFile with its find bar, Ask-AI panel and a lint run) although only the Preview is on show, and refreshed the centre column twice, once for the press and once for the release. CentreColumn.open_file now builds the editor only when it is needed: the Source or Split view is on show (or is switched to), or the caller passes on_saved or line, which live on the SourceFile (a click, the language chip and the Versions panel pass neither). With the Preview alone on show the file just becomes the centre's path, as keyboard navigation already did, and refresh() builds the editor when Source or Split is shown. open_file also refreshes only when something changed: another path than the one the press set (an explicit file such as the deck source, Slidemaster.bib or a frozen version was open), a slide focused by the call itself, or a mode switch; the release of a click that changed nothing no longer repeats the press's refresh. WorkspaceWindow.open_slide_editor refreshes the centre itself when it comes back from the Images page, as open_file's unconditional refresh did there. Pending edits stay in their own SourceFile (autosave, conflict bar and the Update Version offer in _set_path are untouched), and the Source view is not asked to show a new file in Preview, so nothing is discarded or written to the new target. Tests in test_centre_gui.py (no SourceFile for a Preview click and one show_slide, the editor built on switching to Source, Split and Source clicks, on_saved and line in Preview, pending edits written to their own slide by a Preview click with the Update Version offer still asked) and test_workspace_window.py (a click coming back from the Images page, a click on the selected row after an explicit file).

NEW: Clicking through slides in the Preview is quicker.
- The source editor of a slide is only prepared when you open the Source view, not on every click in the Preview.
- A click no longer redraws the preview a second time.

v8.39.6 (2026-10-20, direct instruction "go", docs/SLIDE_SELECTION_RESPONSIVENESS_PLAN.md step 4): Every selection resolved the open deck again many times on the GUI thread, each time with a new slide_language.TranslationLinks (a glob of slides/*-current.tex and the header reads) and a pass over every slot: CentreColumn._focused_row (deck_outline.slide_row), preview_target.for_call (a second pass for the Instructor frame number, a third scan for resolve_call), the neighbour and next-slide lookups (deck_outline.build_outline), the side panels (deck_calls, _focused_row, id_slug and slide_path, each a resolution, and all of them for the first occurrence) and PreviewPane._refresh (a TranslationLinks for the chips, also on the 5 s validation poll); preview_requests.cache_identity also looked the PyMuPDF package up on every call. The slide list now publishes what it resolved anyway: deck_outline.resolve_outline builds an Outline (project, deck path and text, view, language, the sections the list shows, the TranslationLinks used and the Instructor frame number of every occurrence key, resolved once), SlideList.rebuild stores it on WorkspaceState.outline and _set_outline keeps its sections in step with the rows the list patches (thumbnails, stale previews). WorkspaceState.current_outline() returns it only while it matches the deck, view and language on show; deck_outline.slide_row and outline_rows and preview_target.for_call take an `outline` and use it when Outline.matches (same project, deck path and text, language and, for rows, view), else resolve as before, so the test deck, standalone files, translation partners outside the list (preview_target.resolve_views) and any other deck, view or language keep the old resolver. The centre, the neighbour targets, the side panels and PreviewPane._refresh (translation_link(links=outline.links)) read it. A rescan of the open deck with other text, a view or a language change simply no longer match. What a row says about its files (title, translation partner) is as old as the list's last rebuild, which is what the list shows; because the centre used to read the files at each refresh, WorkspaceState.drop_outline() runs on every write of the Source view, in CentreColumn._on_saved (Ctrl+S, a reload from disk) and when a version is restored, so those readers resolve afresh until the list's own rebuild after the write; _set_outline never brings a dropped outline back. Selection and the thumbnail patches are not invalidation events. SidePanel.refresh resolves the focused row once for the whole build and uses state.focused_occurrence (it used the first call), SidePanel.deck_calls reads the outline's rows; UsedInDecks keeps its own scan of all decks (find_usage, plan step 5). preview_requests._raster_version caches the PyMuPDF version for the process (tests/conftest.py clears it for each test; the test that patches preview_requests.version clears it itself); the identity value is unchanged. Tests in test_deck_outline.py (the outline holds build_outline's sections and the Instructor numbering for repeated, hidden and translated calls, lookups by key and by id, what it matches, slide_row and outline_rows with and without it, the reused row equals the resolved one), test_preview_target.py (for_call with and without the outline for every row of such a deck, same targets, no resolution), test_centre_gui.py (selection reuses the outline, another view or language or an edited deck resolves afresh, a saved title or translation header is seen at once, the preview refresh scans no links), test_slide_list_gui.py (the list publishes and patches the outline, drops it with the deck), test_side_panels_gui.py (the panel shows the focused occurrence and resolves once per refresh, Used in decks still opens its deck), test_workspace_window.py (in the real window, selecting among rows of an unchanged outline, duplicates included, resolves no slot and scans no slides folder; the preview refresh scans none; the outline follows view and language and a Source write drops it) and test_preview_requests.py (the identity follows a patched version, the version is read once).

NEW: Moving through the slides of a deck is quicker.
- The deck's slides are no longer analysed again with every click, only when the deck changes.
- The side panels now show the slide use you clicked when a deck calls a slide twice.

v8.39.7 (2026-10-20, direct instruction "complete all other steps", docs/SLIDE_SELECTION_RESPONSIVENESS_PLAN.md step 5, first half): Going back to a slide showed "No preview for the ... view yet" until the background validation of its image finished, because PreviewPane._invalidate cleared the selection on every target change and PreviewPane._pixmaps (up to 12 full-size 1920 x 1080 pixmaps, about 100 MB) was written by each render but never read; every refresh also decoded the PNG again, and PageView.paintEvent scaled the full-size pixmap on every paint. _pixmaps is now a DisplayCache, the read side of the display: key (target.key, view, language), entries record the saved file's mtime, the hash of the text that was rendered and the hash of the PNG the pixels came from (the same image is never decoded twice: PreviewPane._decoded). Only saved whole-slide renders go in (_on_finished without a note, publish_refresh, and a verified selection of the saved text); a buffer render, a draft and a render of part of the slide never do. Pages are kept at most at a render's full width (1920 px; a wider image is scaled down) and the cache is bounded by entries (12) and by bytes (64 MiB, width x height x 4 per entry), least recently used first, and is cleared with the pane. _invalidate still bumps the generation and the selection ticket and drops the pending validation, so stale completions are discarded as before; it only no longer matters for the pixels. In PreviewPane._image, while the validation of the slide is still to come and nothing is retained for it, a held page whose recorded mtime and text hash match the saved file and the editor buffer is shown at once as "Checking current source and settings…" (the existing previous state: not current, no PDF, no displayed spec); the verified path takes over when validation confirms, and the existing missing and previous states apply when it does not. A page whose file or text changed, or of another view or language, is not shown; the hidden-slide rule and the reveal-step pages still come first. The dependency validation is unchanged: nothing is current on the strength of the file's mtime. PageView keeps the pixmap scaled to the page rectangle (in device pixels) until the size or the pixmap changes, so a paint no longer rescales it. Tests in test_preview_queue.py (a return visit paints the held page while the validator is blocked, then goes current or, if the validation finds it stale, takes the existing states; a stale completion for slide A never replaces slide B; a changed file or text, another view or language shows no held page; draft and buffer renders are never whole-slide entries; a return visit decodes nothing again; the cache holds display-size pages within its byte budget and is cleared with the pane; PageView reuses its scaled copy between paints).

NEW: Going back to a slide you looked at shows its preview at once.
- The preview appears immediately while SlideMage checks that it is still up to date, and says so until the check is done.
- Previews use less memory, and the page is no longer rescaled on every redraw.

v8.39.8 (2026-10-20, direct instruction "complete all other steps", docs/SLIDE_SELECTION_RESPONSIVENESS_PLAN.md step 5, second half): A selection still ran the render store's work on the GUI thread: PreviewPane._image -> _stored_pixmap -> BackgroundPreviews.stored_page (render_key.unit_for, resolver.lookup with its dependency hashing, the page read from disk, the PNG decode), and _update_reveal -> _adopt_stored_steps -> stored_pages (the same lookup and every step PNG) plus the decode of the chosen step page; _update_reveal also queued the all-steps render (FOREGROUND) straight from the selection, and the 5 s _validation_poll rebuilt the chips and the menu on every tick. Now stored_page and stored_pages run on the pane's own single-worker executor (_display_executor, not the selection executor: a lookup must not wait behind a long validation), and decode to QImage there; both take the open deck's name as an argument (deck_name), read by the pane on the GUI thread, so the worker touches no GUI state. PreviewPane._look_up submits the work for a slot ('page' for the whole-slide page, ('steps', key) for a step list) with an identity (the generation, the target key, view, language and the file's mtime at submit time); a newer lookup for a slot cancels or replaces the older one, _invalidate drops them all, and the answer (signal _looked_up) is used on the GUI thread only if the slot still holds that identity and the generation, target, view, language and mtime still match - otherwise it is discarded, so an answer for slide A never shows on slide B. While the lookup is out the pane shows what it showed when the store had nothing (the held "Checking current source and settings…" page of the display cache, else the existing "No preview ... yet" message), never the previous slide; the page that arrives is shown as the synchronous result was (current, no PDF, no displayed spec), is put into the display cache with the revision captured at submit, and replaces a held page; the poll asks again (an unchanged page refreshes nothing). The stored page now comes before the held page in _image, since the store has verified it. Freshness is unchanged: the resolver decides, only where it runs differs; the stored page of the previous selection is dropped by _invalidate and never counts as current for the next. Reveal steps: _adopt_stored_steps asks the worker for the step pages and the chosen step's decoded image (taken instead of PNG decoding on the GUI thread when the step is shown); if the store has none, the render that the request wanted is queued then (_queue_steps). The foreground count that a selection started is deferred: a single-shot timer (SETTLE_MS, 150 ms) restarts with every new slide, and only when it fires (_settled) and the slide still has no counted steps does _update_reveal start the count; meanwhile the bar says "Counting..." and the slide image is not held back. The idle prefetch (PROBE_MS) is unchanged. _refresh rebuilds the chips only when what they are made from changed (text, tone, icon, tooltip, translation partner, deck-context view), and _rebuild_menu only when the menu's inputs changed (target, hidden, batch, busy, scope, reveal step, the render-all and open-PDF availability), so the poll leaves both alone. The dispose of the pane shuts the display worker down with the selection executor. Tests in test_preview_queue.py (the store is called off the GUI thread and the page is shown on arrival, current and without a PDF; the deck name is handed over; the stored page is held for a return visit and a blocked lookup shows the held page as being checked; a page for A that arrives after the selection moved to B is discarded; with the store blocked a new slide shows its message, never the previous slide; a changed file discards the page looked up for the old one; no pixmap is decoded from a stored page on the GUI thread; the poll asks again and only a changed page refreshes; a refresh that changes nothing rebuilds neither the chips nor the menu, a real change does) and test_reveal_bar_gui.py (selecting a slide starts no count until the selection rests; A, B, C in a row count only C, with "Counting..." meanwhile; the image shows before the count; the stored steps are read and decoded off the GUI thread; the stored steps are found without counting) and test_background_previews_gui.py (the stored page is found through the Preview after a background render, not after the slide changed).

NEW: Moving through the slides of a deck is quicker still.
- A slide's saved preview and its reveal steps are now loaded in the background, so clicking through slides no longer pauses while they are read.
- The step bar waits until you stop on a slide before it counts the steps, and the preview no longer redraws its labels and menu when nothing has changed.

v8.39.9 (2026-10-20, direct instruction "complete all other steps", docs/SLIDE_SELECTION_RESPONSIVENESS_PLAN.md step 6): The right column still did its own work on every focus change, and one of its paths moved the Source view. SidePanels.refresh flushed the panels and rebuilt the shown one for every focus, view and language signal; the default Used in decks panel ran slide_usage.find_usage, which scanned every deck file of the project (scan_decks) and resolved each deck with its own TranslationLinks (a glob of the slides folder), on the GUI thread, per signal. AssistantHeader.schedule recomputed the task offers (a lint of the slide, of every slide for the deck scope) on a zero-delay timer, which can still run before the next paint. The Speaker notes panel's flush wrote a pending edit through CentreColumn.edit_slide_text, which called SourceView.show_path(old slide): in Preview this built an editor for the slide being left, made it the Source view's current file and dropped the new slide's editor. Now SourcePane.edit_off_stage(path, change) applies the change to the buffer of `path` as one undo step without making it the file shown: it takes the open SourceFile (synced when it is not the current one) or builds one, refuses a read-only buffer (a frozen version), writes the file at once under the usual autosave, conflict and AI-fix rules (write_now), and drops the file again unless it is dirty or has a fix running (keep_open), so a buffer that could not be written stays open for the existing conflict notice and the dirty state. CentreColumn.edit_slide_text uses it unless `show` is given or the Source view shows the file already (then it is as before: show_path, the change in the buffer, left to the autosave); "Save notes" passes show=True, as its Ctrl+S-style save acts on the Source view's file. show_path's file construction moved to SourcePane._add_file for both. SidePanels now saves pending edits against the old target at once on a focus, view or language change (the old target is the one the panel was built for), lays a transparent shield over the shown panel (SidePanels._shield) so a quick click cannot change the slide that was left, without greying the panel out on every click, and rebuilds it once the changes have stopped: a single-shot timer (state.SETTLE_MS, 150 ms) restarted by each change; a deck change and choosing another panel stay immediate (single deliberate steps, and the new deck or panel has nothing to show until they rebuild); refresh() stops the timer, and does nothing while the panels' card is hidden (Focus assistant), bringing the panel up to date when the card comes back; panels that are not shown were never refreshed. find_usage takes the window's known decks (UsedInDecks passes WorkspaceWindow.decks, kept current by reload_decks) instead of scanning the folder, and, given a language, shares one TranslationLinks between all decks of the call (deck_language.slots and deck_slots take links=). On the example project (two decks, about 170 slide calls) the query took 19.7 ms per focus change before (scan and one TranslationLinks per deck) and 14.7 ms after, now once after the selection rests, so it stays synchronous inside the debounced rebuild; it grows with the number of slide calls in all decks (about 7 ms per 85 calls), which a worker or a per-deck cache could remove if a large project needs it. UsedInDecks._open focused the slide without its occurrence, so the second use of a slide in another deck opened the first; it now resolves the slot at the clicked place of the deck (deck_outline.resolve_slots) and focuses its key. AssistantHeader measured, on a focus change in the example deck, at about 7 ms for the slide scope (median; a lint of the slide) and 56 ms (max 116 ms) for the deck scope (a lint of every slide), so a change of slide, view or language no longer schedules the zero-delay refresh: it clears the offers, makes the task buttons do nothing (AssistantHeader._choose; they carry the offer of the slide that was left, and are not greyed out) and restarts a SETTLE_MS timer, after which the offers and the target are worked out for the state of then; deck, mode, dirty, lint and route changes, and a task starting or ending (the pill), stay immediate, and the 0.4 s poll leaves a pending settle alone. Tests in test_centre_gui.py (a panel edit of the slide left is written and the Source view stays on the new slide, without an editor of the old one; it does not replace the editor of the slide the Source view shows; a buffer in conflict stays open, with its edit, and is reported as unsaved; a frozen version is refused and leaves nothing open; the slide the Source view shows keeps the autosave route; show=True makes the file the Source view's own), test_side_panels_gui.py (three quick focus changes rebuild the shown panel once for the last slide; the old contents stop answering at once, a click on a row of the old slide opens no deck; a pending edit is saved against the old slide at once; a panel that is not shown and a hidden card rebuild nothing, and the card is up to date when it returns; a deck change rebuilds at once; a focus change scans no decks and one translation scan serves the query; archived decks are listed from the window's decks; the second use of a slide in another deck is focused by occurrence; in a real window a pending note is written to its slide in Preview and the Source view shows the new slide, and a note on a file in conflict is not lost), test_slide_usage.py (given decks are not scanned again and one translation scan serves all of them, archived decks included) and test_assistant_gui.py (a change of slide works the offers out once, after it has rested, with the task buttons doing nothing meanwhile).

Review fix before the merge: WorkspaceState.set_deck emits deck_changed (an immediate rebuild of the side panel) and then the focus, view and language it reset; each of those raised SidePanels._shield again and restarted the SETTLE_MS rebuild over content that was already current, so for 150 ms after a deck switch a click on the panel did nothing. SidePanels now remembers the state the shown panel was built for (_built_for: deck, focused slide and occurrence, view, language); a change that lands on it, after a deck switch or when the user comes back to the shown slide before the pause, leaves the panel answering and rebuilds nothing. Tests in test_side_panels_gui.py.

NEW: Moving through the slides no longer stalls on the side panels, and speaker notes you typed stay with their own slide.
- The panels on the right and the assistant's suggestions update a moment after you stop on a slide, not for every slide you pass.
- A speaker note you have typed is saved to its own slide when you move on, without switching the source editor back to that slide; clicking the second use of a slide in the "Used in decks" panel now opens that use.

v8.40.0 (2026-10-20, Jürgen Fleiß's PRs #6 and #10, direct instruction "Delete it and do the merges"): Two changes by Jürgen Fleiß. Dark slides per deck: Deck settings → General → Dark slides writes \newcommand{\SMDarkMode}{} into the deck before its template input (deck_settings.set_dark_mode, DeckSettings.dark_mode) and refreshes the Preview after saving; light stays the default. A template offers it with "% SlideMage dark mode: true" in its first 30 lines (deck_settings.template_supports_dark_mode), so copied or renamed templates work without institution names in the app; the checkbox is off for a template without it. The example Uni Graz template has a dark design (a #2B2B2B canvas, #3A3A3A cards, white body text, yellow inline code, black-on-grey code panels); Slidemaster_preamble_base.tex takes the slide canvas from SMCanvasColor (white unless a template sets it), also for the title-bar patches around the logo, and defines shared card and process styles (SMCard, SMProcess) whose colors a template sets once. As the framework file changed, every stored preview is rendered again once; preview_equivalence's pins of Slidemaster_preamble_base.tex and of the Uni Graz template are updated after an audit (\SMDarkMode is per deck, no rule depends on the version), so the versions of a slide still share one render where they did. New logo: three layered slides (yellow, grey, a dark front card with a yellow dot and two bars) in icon.svg, icon.ico (a simpler mark at 32 px and below) and splash.png; assets/logo/ holds the full set (mark, horizontal and stacked wordmark, for light and dark backgrounds). Review fixes before the merge: the top bar shows the dark-background variant of the mark in the dark theme (TopBar.set_dark, from WorkspaceWindow at start and on each Dark mode toggle), where the dark front card had all but vanished on the dark bar; and deck_settings._remove, which clearing an output folder or the appendix table of contents uses, took a whole line out when only whitespace stood before the setting, so another command after it on the same line went too; it now keeps the line unless only a comment follows, and set_dark_mode uses it instead of its own copy. Tests in test_deck_settings.py, test_deck_settings_gui.py and test_workspace_window.py.

NEW: Dark slides for a deck, and a new SlideMage logo.
- Deck settings → General → Dark slides gives a deck dark slides, when its template supports them; the Uni Graz template does.
- SlideMage has a new logo, also in the dark theme's top bar.
- Clearing an output folder or the appendix table of contents in Deck settings no longer deletes another command on the same line of the deck file.

v8.40.1 (2026-10-20, direct report "I just observed my SlideMage instance go from 1051 items remaining back to 1081 items remaining for background rendering. How is this possible?", then "Fix the store-full churn bug too."): The background sweep went round in circles once the render store reached its disk limit (Settings → Background previews → Disk limit, 2 GB by default). Each replan counts every unit without a current render as left, and then deletes the least recently used renders of the decks that are not protected (the open deck and the five opened most recently) until the store fits; those were left again at the next count. In a project that needs more than the limit (about 5,000 renders of about 0.5 MB against 2 GB) the count rose and fell for ever and the processor never rested. With the store at its limit (BackgroundRenderer._store_full: one more render of the average size would not fit), the planner now hands the scheduler only units of the protected decks (_top_up; _protected_decks also counts the open deck, which eviction now protects as well); they may still push out other decks' renders, which are then left but not rendered again. When only such units remain, the progress says why (STORE_FULL, "disk limit reached") and the sweep rests; a higher limit lets it go on. Test in test_background_renders.py.

NEW: Background previews stop at the disk limit instead of rendering the same slides over and over.
- When the stored previews reach the disk limit, SlideMage keeps rendering the decks you use and shows "disk limit reached" for the rest; raise the limit in Settings → Background previews to let it finish.

v8.41.0 (2026-10-20, docs/MENU_UPDATE_PLAN.md step M1): The three deck maintenance commands and the project and program rows get a home in the sheets, before the ⋮ menu drops them (M2). Deck settings → General ends with a Maintenance group (ui/dialogs/deck_settings.py): rows Deck snapshot, Previews and Slide versions, each a name, a one-line caption and a compact button for the commands create_snapshot, rerender_deck_previews and update_deck_versions. The sheet is modal, so a button asks about unsaved changes (Discard or Cancel), closes the sheet with action "command:<id>" and deck_actions.on_deck_settings runs the command through the command registry (window.commands.run); the button is disabled when the command is not enabled for the window, so enabled state stays in actions.py. Settings gets two tabs: Project (rows Bibliography file and Test slides with Edit buttons for the commands edit_bib and edit_test_slides, "not found" and a disabled Edit for a missing file, and Project compatibility → project_compat) and About (the version number, Version history → version_history, Check for updates → check_updates); these buttons also run their command through the registry after the sheet has closed. SettingsSheet.close_then(action) closes through done(), which still asks about unsaved prompt text, and the window runs sheet.after once the sheet is gone. ProjectContext gets test_slides_path next to bibliography_path (the window's Edit test-slides.tex used to build it itself); the label, caption and button row is the kit's action_row. Tests in test_deck_settings_maintenance_gui.py and test_settings_gui.py.

NEW: Deck settings and Settings have the maintenance buttons that were in the ⋮ menu.
- Deck settings → General: a Maintenance group with Create snapshot…, Rerender all and Update changed…, each with a line saying what it does.
- Settings has a Project tab (edit the .bib file and test-slides.tex, check project compatibility) and an About tab (version, version history, check for updates).

v8.42.0 (2026-10-20, docs/MENU_UPDATE_PLAN.md step M2): The ⋮ menu (menus.py, MORE_COLUMNS) has two short columns: This deck (Present, Deck settings…, Export PPTX…, Duplicate deck…, then Archive deck… after a separator) and Project (Image descriptions, Open project…, New deck…, then Housekeeping… and Archive unused… after a separator), with Settings… and the ⌘K note in the footer; the Info column and the Housekeeping header are gone. Admin slides, Tags, Edit deck source, the snapshot, previews and slide-version commands, Edit .bib, Edit test-slides.tex, Find anything, Version history, Check for updates and Project compatibility stay registered and are ⌘K commands (the sheets of v8.41.0 run several of them through the registry). The deck_settings command gets the shortcut Ctrl+, (⌘, on macOS; no other command or QKeySequence binding used it), which the menu shows in place of a hint. The wizard_preview command ("Preview wizard magic") is deleted together with what only it used in wizard_portal.py: the demo parameter of WizardPortal and play_wizard, the sample slide it drew (_slide) and the __main__ preview; the AI-edit animation, review_snapshot and note_review_updates stay. Tests in test_more_menu_gui.py (new layout, keyboard, Ctrl+,), test_commands.py, test_wizard_portal.py, test_rerender_deck_gui.py, test_manual_group.py and test_workspace_window.py follow the shorter menu; README.md and docs/SlideMage.md name the new places.

NEW: The ⋮ menu is shorter and Deck settings opens with Ctrl+, (⌘, on a Mac).
- The menu now has just This deck (Present, Deck settings, Export PPTX, Duplicate, Archive) and Project (Image descriptions, Open project, New deck, Housekeeping, Archive unused), plus Settings.
- Everything that left the menu is still in Ctrl+K / ⌘K, and the snapshot, previews, slide versions, .bib, project compatibility, version history and update check are also in the Deck settings and Settings sheets.
- "Preview wizard magic" is gone.

v8.43.0 (2026-10-20, docs/MENU_UPDATE_PLAN.md step M3): PopoverMenu (ui/kit/widgets.py) gets add_submenu(key, text, build): a row with a trailing ▸ whose activation (click, Enter) opens the flyout that build(menu) returns, a second non-inline PopoverMenu (a Qt popup child of the first, min_width 280, a title row with the row's text), left of the menu with its top at the row, right of it when the screen has no room on the left, placed by Popover._show_at. One flyout at a time; the same row again closes it (a press on the row already closed the popup, so the key of a flyout closed with the mouse button down is kept until the release); an item of the flyout is triggered on the parent menu and closes both; Qt's popup stack closes the flyout on a click outside it and on Esc, and the parent closes it when it hides. Keyboard entry into a flyout is not supported yet. The ⋮ menu's MORE_COLUMNS take a Submenu(title, ids) among the command ids, drawn by add_commands (left out when no command is visible, disabled when none is available, keyed submenu:<title>): Export ▸ (Export PPTX…) and Housekeeping ▸ (Housekeeping…, Archive unused…). Tests in test_ui_kit_gui.py (submenu rows, position, one at a time, dismissal) and test_more_menu_gui.py.

NEW: Export and Housekeeping in the ⋮ menu open a small side menu.
- Export ▸ (Export PPTX…) and Housekeeping ▸ (Housekeeping…, Archive unused…) open to the left of the menu; click the row again or press Esc to close it.

v8.44.0 (2026-10-21, docs/MENU_UPDATE_PLAN.md step M4): Export LaTeX…: new Qt-free module latex_export.py, export_deck(ctx, deck, dest_dir, log) -> ExportResult(folder, files, missing). It writes <dest>/<deck name>-latex/ into a scratch folder next to it and renames it into place (an existing folder is removed only then; an exception leaves the old folder and no scratch). The files come from following the sources rather than from a compile: from the deck, with the search path of the project's .latexmkrc (decks/, project root, the framework folders of slide_snapshot.framework_dirs), through \input/\include/\usepackage/\usetheme-family names, \includegraphics and \SMCodeFile arguments and any name with a file suffix in a text, recursively through .tex/.sty/.cls/.lua files; a file shown as code (\SMCodeFile, \lstinputlisting) is copied but not read. The deck's slide calls (and translation partners) are read by the new unused_content.slide_filenames_in(), which find_used_slide_filenames now uses per deck text, and the media/ references by the new unused_content.media_references() (bare stems, same-stem siblings, comments stripped; also returns the references that match no file), which find_used_media_filenames now uses: Housekeeping's archive scan and the export share them. The deck and any decks/ fragment it \inputs go to the folder root with their \def\input@path and \graphicspath lines changed from {../} to {./}; media/alt-text.json and .csv, the .bib (a bare \SMUseBibliography) and a generated .latexmkrc (lualatex) are added. Slides, media or files the sources name that the project lacks are returned in ExportResult.missing and logged, not fatal. The export_latex command (actions.py, meta "self-contained · with media folder") asks for a folder (QFileDialog.getExistingDirectory), asks before replacing an existing <deck>-latex folder, flushes the Source view, exports and shows a window toast with an "Open folder" action (compile_actions.export_latex, on_toast_action; the action key carries the path); it is in the ⋮ menu's Export ▸ flyout and in ⌘K. The manual deck exports to 162 files and compiles to the same 97 pages as in the project. Tests in test_latex_export.py (contents, only the used media, path lines, missing files, replace, no half folder, a real latexmk build of the folder away from the project), test_latex_export_gui.py, test_more_menu_gui.py and test_commands.py; README.md and docs/SlideMage.md name the command.

NEW: Export LaTeX… in the ⋮ menu (Export) saves a deck as a folder you can compile anywhere.
- Pick a folder; SlideMage creates "<deck>-latex" in it with the deck, the slides and images it uses, the template and the bibliography, ready for latexmk. It asks before replacing an earlier export.
- Files the deck mentions but the project does not have are listed in the Log; the rest is exported.

v8.45.0 (2026-10-21, docs/findings.md plan 1): preview_build._compile_reserved passes latexmk -g (go mode) for a forced build only when the slide's wrapper text is unchanged (the existing wrapper-rewrite check now also decides that: `changed`). Every RenderService miss passes force_build=True; until now that made latexmk rerun every rule, so each edit render also ran biber (reason go_mode) for a slide with no citations. A changed wrapper reruns LuaLaTeX anyway and that pass reads every input again, so -g only matters when the text is the same and an input was edited with its time and size restored (the theme case in test_preview_requests.py, which renders as before). Accepted edge case, in the compile_cached docstring: a .bib edited with its time restored in the same render as a slide text change is not seen by biber (latexmk's own behaviour). The font-cache-race retry in run_preview still adds its own -g. Callers keep force_build=True. Linux, example/ slide 1an, medians of 3: edit 2.41 -> 1.91 s (latexmk rules biber 0.52 + lualatex 1.41 -> lualatex 1.38), view switch 3.85 -> 3.35 s and 3.90 -> 3.46 s; cold and unchanged are unchanged (6.18 s, 0.07 s). Equivalence: 10 slides of slidemage-manual-copy in all three views, edited with an appended comment: the 30 display images are pixel- and byte-identical to the previous behaviour (-g forced). Tests in test_preview_build.py (an edit after a cached build runs lualatex alone; the same text with force runs lualatex and biber).

NEW: Previews of an edited slide appear faster.
- Typing in a slide and previewing again takes about half a second less, because the bibliography is no longer processed again when nothing in it changed.
- Nothing about how the preview looks has changed.

v8.46.0 (2026-10-21, docs/findings.md plan 2): PreviewCache.prune() no longer reads every manifest when nothing is deleted, and RenderService.work() calls the new PreviewCache.maybe_prune() instead of prune(). prune(): the stat pass uses os.scandir (_generations: generation size = sum of its files, images folder size, as before); the manifests are read for blob references only if a generation was deleted in this call (nothing deleted -> no blob lost a reference); a corrupt manifest still returns without deleting blobs. maybe_prune(): prunes the first time in a process, then at most every PRUNE_INTERVAL (10 minutes) per cache root, earlier only if an in-memory size estimate exceeds MAX_BYTES (prune() records the total it computed, store() adds the PDF, new blobs and manifest it wrote; module-level _PRUNED under a lock, no file on disk). Callers: only work() was per render; the other prune() callers are tests. _prune_transients (remember_transient) measured at 5.5 ms for the full 256 records, bounded, left as is. Linux, tools/preview_bench.py fill-cache (400 generations, manifests 40.6 MB), prune() median of 3: 116 -> 11 ms; edit render: no prune() call after the first of the process. Tests in tests/test_preview_cache.py: no manifest read when nothing is deleted, survivors' blobs kept after a deletion, maybe_prune interval and size estimate.

NEW: Previews of a slide appear a little sooner, most noticeably after a long time of use.
- Cleaning up old preview files no longer runs after every preview; it runs at most every ten minutes, or sooner if the cache grows past its limit.
- Nothing about how the preview looks has changed.

v8.47.0 (2026-10-21, docs/findings.md plan 3): Files outside the project and framework folders (the TeX distribution, the tool binaries latexmk, lualatex, pdflatex, xelatex, biber, bibtex, and the cache's own PDFs and images) are no longer read and SHA-256-hashed again for every cache check. preview_cache.FileStates(roots) returns the same [resolved path, sha256] as file_state(), but for a file not inside one of the roots (search_roots(): project, framework, TEXINPUTS/BIBINPUTS/BSTINPUTS/LUAINPUTS entries; also when reached through a link) it keeps the state in a process-wide, thread-safe, 20 000-entry LRU memo while (size, mtime_ns, inode, ctime_ns) is unchanged. Files inside the roots are always read, so an edit with a restored mtime is still caught (the theme tests are unchanged); a file changed within the last 3 s and a missing file are not remembered; the stored manifests and format.json keep their format, so existing caches stay valid. Used by input_state/dependency_state (lookup, store, stability check), ValidationPass (inputs, stable), configuration_state (tool binaries; the rc files are tiny and always read) and preview_format (_stamp for _fresh and _build). store() no longer computes _evidence() a second time: it derives it from the begin() it just compared with `before` (the stability fields dropped); the final begin()/input_state re-check after the build is unchanged. RenderService.work() shares one ValidationPass between group_lookup and lookup, so their evidence and input reads happen once. shutil.which is looked up at most every 30 s per (tool, PATH) by preview_cache.find_tool (configuration_key, configuration_state, preview_format). Linux, tools/preview_bench.py, example/ slide 1an, medians of 3: content read edit 143 -> 2.0 MB, unchanged 44 -> 1.1 MB, cold 143 -> 45 MB (the first render of a process still reads the distribution once); times: edit 1.90 -> 1.93 s (LuaLaTeX itself), unchanged 0.07 s, preview_format._fresh 35 ms. Tests in tests/test_preview_cache.py: a file outside the roots is read once while its stat is unchanged, read again after a size, mtime or restored-mtime change, never remembered when just written or missing, files inside the roots (and links into them) always read, the memo is bounded, the state has the stored shape, configuration_state reads the binaries once, a dependency outside the roots hits until it changes, find_tool.

NEW: Previews use much less disk and processor time.
- While the Preview pane is open, the check that the shown preview is still current no longer re-reads tens of megabytes of LaTeX installation files every few seconds.
- Editing a slide and previewing again reads about 2 MB instead of 143 MB, which helps most on Windows, where reading many files is slow.

v8.48.0 (2026-10-21, docs/findings.md plan 4): The Preview pane shows a freshly rendered slide as soon as its pictures exist; the cache record (reveal-sequence raster, store, group publication, prune, temp-folder cleanup) follows on the same worker. RenderRequest gains an event `delivered` (the pixels exist) next to `done` (delivered and recorded) and `wait(cancel, timeout, *, pixels_only=False)`: a plain wait() returns when the request is done, exactly as before (the cache PDF, the final preview_result and _cache_entry, so compare_rendered, preview_batch, the AI tools and the reveal-step render are unchanged), wait(pixels_only=True) returns at the delivery with the render's temp PDF (cache hits and finished requests return the final result). RenderService.request.work() is split: it builds and calls slide_snapshot.prepare_preview_images, delivers (RenderRequest._deliver sets a provisional preview_result and metrics), then record() runs the reveal sequence, PreviewCache.store, pin (cache lease), publish_group, drop_temp and maybe_prune. A cancel after the delivery does not stop the record, and the last waiter leaving a delivered request no longer cancels it; a failure in record() is logged and the delivered render stays the result, never a render failure. A request that arrives while the record runs still finds the registered request and shares it. The temp render folder is removed by the record, except when a pixels_only waiter was handed its PDF (RenderRequest.lent): then it is removed when the request object is released (weakref.finalize, also at exit), and the pane keeps its last request (`_last_request`) as long as it keeps `_last_pdf`; the pane counts a lent request as cached for remember_transient, and the display history is written after the record. _ImageConsumer.wait accepts pixels_only but still waits for the record (its view's display history needs the cache entry). The cache thumbnail now comes from the raster child: prepare_preview_images asks for one more size, (320, 180, "fit") (preview_cache.THUMBNAIL_MAX, aspect kept inside the box) and returns that PNG after the display PNGs; store(thumbnail=...) keeps it and falls back to thumbnail_png() (PIL) without it. The pixels differ slightly from PIL's LANCZOS, which does not matter for a list thumbnail. store() no longer reads an existing content-addressed blob back to compare it: the blob counts as the same image when its FileStates state (memoised outside the roots) hashes to its name; a damaged blob is rewritten. tools/preview_bench.py reports `pixels s` (the pane's wait(pixels_only=True) returns) next to `total s` (record done). Linux, tools/preview_bench.py, example/ slide 1an, medians of 3: time to pixels edit 1.91 -> 1.78 s (the record, 0.12 s: store 97 ms, reveal sequence 22 ms, now follows; total 1.90 s), cold 6.43 -> 6.23 s, unchanged 0.06 s (a cache hit, no change). Tests: tests/test_preview_requests.py (wait(pixels_only=True) returns while store() is blocked, a duplicate request during the record shares the build, the entry and a later cache hit after the record, the temp folder is kept for the lent PDF and removed on release, removed at once for a plain wait, a record failure keeps the delivered render and the next request renders again), tests/test_preview_cache.py (supplied thumbnail kept, blobs deduplicated without being read back, a damaged blob rewritten), tests/test_preview_raster.py (fit size), tests/test_preview_bench.py (pixels column). Review fix to v8.47.0's FileStates: it resolved every path and compared Paths per search root on each call (22 000 lstat calls in two renders, ~120 ms per store()); it now compares normcased string prefixes and calls realpath only when the memo misses: store() 97 -> 34 ms, a cache hit 0.07 -> 0.03 s, an edit render 1.84 s.

NEW: A rendered slide appears in the Preview a little sooner.
- After a change, the preview picture is shown as soon as it is drawn; saving it to the preview memory now happens right afterwards instead of before.
- Small list pictures of slides are made together with the preview, so less work remains afterwards.

v8.49.0 (2026-10-21, docs/findings.md plan 6): Every view and language of a slide has a build folder of its own. The reusable latexmk folder was keyed by preamble and slide only, so the views shared one: Instructor writes no .ovl, the student views do, and the flipped helper files made latexmk run LuaLaTeX twice after every view switch. preview_build.view_variant(wrapper_text) reads the `\deckversion[...]` and `\decklanguage[...]` lines the wrapper sets after \begin{document}, ahead of its \setSlideID (slide_preview._deck_version_line/_deck_language_line write them), and _compile_cached passes `slide|variant` to configuration_key for the per-slide key; a wrapper without such lines keeps its old key. The precompiled format key (compile_cached) is unchanged, so the format stays one per preamble, shared by all views. The presenter mode is a line before the preamble and was already in the key. Background renders keep their own workspace, and prune_unused needs no change: a wrapper `_slidemage_preview-<key>.tex` and its cache folder `<key>` are still paired by the key, so each view's folder is removed after 14 unused days. A view's first render in its new folder is cold once (LuaLaTeX twice, biber when the slide cites). Linux, tools/preview_bench.py view-switch, example/ slide 1an, medians of 3 (each render with a fresh edit): Instructor 1.86 s, During course 3.39 -> 1.85 s, back to Instructor 3.35 -> 1.83 s (LuaLaTeX once instead of twice); an ordinary edit render is 1.87 s. Tests: tests/test_preview_build.py (views and languages get different cache folders, the same view the same one regardless of slide text; with the real TeX tools, Instructor -> During course -> Instructor with a helper file that differs per view runs one LuaLaTeX for each return, which ran two before).

NEW: Switching between Instructor and the student views in the Preview is faster.
- After you switch the view and change the slide, the new preview takes about 1.8 seconds instead of about 3.4 seconds, as it does when you stay in one view.
- Each view of a slide keeps its own working files, so the first preview in a view you have not used yet takes a little longer, once.

v8.50.0 (2026-10-21, docs/findings.md plan 5): Background previews of one deck, view and language are rendered up to 16 slides at a time in ONE LuaLaTeX document instead of one document per slide, and split into the same store records. Two LuaLaTeX passes and one biber run serve the whole batch, which cost 2.7 s fixed plus about 0.35 s per slide in the feasibility study, against about 4 s for each slide alone. Setting `bg_previews_batch_size` (background_renders.BATCH_SIZE_KEY, default 16, 1 = one document per slide, no UI). The planner (`_top_up`/`_take_batch`) takes the next outstanding units of the plan with the same deck, view, language and preamble text, at most one per bare slide id (the pages of a repeated id could not be told apart; the second waits for a later batch), none that failed before (they run alone), and submits one scheduler job per batch (payload `(units, origin)` for every job now; the scheduler gains `jobs(priority)` so units already queued or running are not batched again after a replan; the queue-ahead of a batch job is `workers + 2` jobs). The reveal slider's jobs and foreground priorities are unchanged and single. `slide_preview.render_slides_to_pdf` builds the batch wrapper with the same pieces as `render_slide_to_pdf` (`_wrapper_text`, `_slide_call`: preamble, `\deckversion`, `\decklanguage`, the all-steps overlay line once, then `\setcounter{framenumber}` and the call of each slide; one `\end{document}`; a short job name `batch-<digest>`); the single wrapper now writes the overlay line before the page-number line (the same TeX, so every foreground build folder reruns once). `BackgroundRenderer.render_batch` computes each unit's fast key and lookup first (a unit that is current is left out and counted, a lone remaining unit is queued singly), renders the document, and splits it with the slide id on every page (`slide_snapshot.slide_id_in` on the texts the raster child reads, `slide_runs`): the run ids must equal the planned bare ids in the planned order and the pages must add up, else nothing is stored. Each unit's pages go to a PDF of its own (new raster child op `extract_pages`: MuPDF stays out of the app threads), are rasterised like a single render's (`_rasterise`) and stored by `_store_render`, which `render_unit` uses too, so the record (key, `.bg` object, origin background, pages, meta) has the shape a single render makes. Evidence per unit: the files the batch read, filtered by `_unit_inputs` (not the other slides; of media and snippets only those the slide's text or a snippet it uses names, with or without the extension) and hashed by `build_manifest`; TeX distribution files of the other slides only go to `tex_files`. `media/alt-text.csv` and `.json`, which every render reads, are kept now (`_compile_manifest` dropped them because no slide names them; deck-compile records are fixed too). A unit whose fast key changed while the batch ran is not stored. If the batch does not compile or cannot be split, nothing is stored, no failure is recorded and the units are queued as single jobs, so a broken slide is found and remembered by its own render; a cancelled batch is requeued as a whole. Progress counts units (each stored unit raises `fresh`); the status window shows a batch as one row, "N slides". Linux, tools/preview_bench.py background-batch, slidemage-manual-copy, Instructor EN, 64 units, serial, fresh store and warm format: one document each 248.6 s wall / 239.8 s child CPU, batches of 16 48.2 s / 41.0 s (5.2x and 5.8x less). Tests: tests/test_background_renders.py (planner groups by deck, view, language, size and bare id, keeps order, lone failed units; queued units are not batched twice; a batch stores the single render's record shape with the unit's own PDF and evidence; current units left out; an edited unit not stored; split and compile failure queue singles without failure records; cancel; one running row; alt texts kept; with the real TeX tools a batch of three slides gives the PNG pages and the manifests of their single renders), tests/test_preview_raster.py (`extract_pages`).

NEW: The background previews of a deck are ready several times sooner.
- The slides of a deck are prepared in groups, so a whole deck is ready in about a fifth of the time and the computer is much less busy on the way.
- Nothing looks different: the pictures are the same as before.

v8.51.0 (2026-10-21, docs/findings.md plan 5): "Rerender all previews for this deck" renders the slides it finds no verified preview of up to 16 at a time in ONE LuaLaTeX document, like the background previews (v8.50.0), and records each slide as a render of its own. `update_all_previews.rerender_deck` passes the background setting (`background_renders.batch_size(ctx)`, `bg_previews_batch_size`, default 16, 1 = one document per slide) to `deck_preview_refresh.run` and `preview_batch.render_batch(batch_size=)`. The new `batch_render` module groups the requests that are to be rendered (`groups`): plain, visible slides of a deck (no hidden slide, no `needs_context`, no presenter, overlay, region, element or all-steps request, no `\SMDeckAgenda`-like deck-context text, no capture error) with no verified preview (`RenderService.is_cached`, which looks up the request's own entry and its image group's; forced requests always count), in plan order, of one view, language and preamble text, at most `batch_size` per document and one per bare slide id (a repeated id waits for the next document); a request that would be alone renders singly. `batch_render.build` takes the cache's guard (`cache.begin`) before the compile, compiles the document with `slide_preview.render_slide_texts_to_pdf` (the editor-style wrapper of every slide, `_text_wrapper` and `_text_slide`, the pieces `render_slide_text_to_pdf` uses too: preamble, overlay line once, `\deckversion`, `\decklanguage`, then per slide `\setcounter{framenumber}`, `\setSlideID`, `\setSlideLanguageFromSlug`, the slide's version, steps, omitted and final state and its text; a short job name `batch-<digest>`), splits the pages by the slide id on each page (`slide_snapshot.batch_runs`: the ids must be the planned bare ids in the planned order and the pages must add up, else nothing is used), extracts each slide's pages into a PDF of its own (raster op `extract_pages`, now with an `out` argument in `preview_raster_client.read_document`) and gives the dependencies of each slide (`render_key.unit_inputs`: the code `BackgroundRenderer._unit_inputs` had, now shared; not the other slides, of the media and snippets only those the slide's text or preamble or a snippet it uses names, and the alt texts every render reads). `RenderService.request(prebuilt=PrebuiltRender)` then records that PDF through the path of a single render (`prepare_preview_images`, `preview_sequence`, `cache.store` with the guard taken before the document, `publish_group`, the display history, the publish callback), so the entry has the identity, the images and the evidence of a render of its own and a later single request is a cache hit; a request that another request already runs does not use it and its PDF is removed. `render_batch` announces each request once ('rendering') and reports one final event per request as before; a document that does not compile or cannot be split, or a cancelled refresh, leaves its requests to their single renders. The single editor-style wrapper now writes the page number right before `\setSlideID` (after the overlay, version and language lines): the same TeX behaviour, so each foreground build folder reruns once. `RENDER_SCHEMA` and the background keys and records are unchanged. Linux, 16 CPUs, `tools/preview_bench.py --scenarios deck-refresh --batch-size N`, slidemage-manual-copy (79 slides, 3 views, forced, fresh cache): one document each 219.7 s wall / 2258 s child CPU, batches of 16 79.5 s / 647 s (2.8x and 3.5x less; the machine was also busy with other work, the single-document numbers of the earlier plans were 168.9 s / 1071 s). Tests: tests/test_batch_render.py (grouping by view, language, preamble, size, bare id and cached entries, forced requests, requests that are not plain slides; the split, its failures and the dependencies of each slide; the wrapper of each slide is the text of a single render; progress events, singles after a failed document, image-group followers, cancel; the service records a made PDF and a later request finds it, a stale guard stores nothing; with the real TeX tools three slides, one with `\slidestep`, give the display pictures, page images and evidence of their single renders), tests/test_update_all_previews.py (the setting reaches the refresh).

NEW: "Rerender all previews for this deck" is several times faster.
- The slides are prepared in groups of up to 16, so a whole deck is done in about a third of the time and the computer is much less busy on the way.
- Nothing looks different: the pictures are the same as before.

v8.51.1 (2026-10-21, direct report: "it offered to update, downloaded, closed, but reopened again with the old version"): The folder build's update still did not install on Windows when SlideMage had been started from Explorer. Explorer starts it with the installation as its working folder; the swap helper inherited that folder, and Windows does not move a folder that a running process works in, so all 20 tries failed and the helper started the old version again (the update stayed unpacked as "<folder>.update"). `updater.start_helper` now starts the helper in its own temp folder, and the helper changes to the installation before it starts the new version, so that version works there as after a start from Explorer. Preview: since v8.48.0 the pane shows a render's pixels before its cache record is written and took such a render as cached (`RenderRequest.lent`), so it did not keep the pixels as a transient image. When the record then was not written (a render without recorded inputs, as in v8.39.3), the page showed "No preview" right after a render that had worked. `PreviewPane` counts a render as cached only once its record is there (tests/test_centre_gui.py failed about one run in six). While that record is written (about a second), the page of the render just made of this very text shows as current (`_render_being_recorded`) instead of "Previous render ... render to verify", and it is checked again as soon as the record is there (`_check_when_recorded`), not at the next 5 s recheck (tests/test_centre_gui.py). Export LaTeX: replacing an earlier export deleted the old folder before the new one was renamed into its place, so a rename that Windows denied (a virus scanner or the indexer holding the just-written files) lost the old export and showed "Couldn't export". `latex_export.export_deck` now moves the old folder aside, renames the new one in, tries a denied rename again for up to 5 s (`_rename`), puts the old folder back when the new one cannot go in and deletes it only afterwards. Tests: tests/test_latex_export.py (a rename denied twice succeeds, one always denied keeps the old folder), tests/test_updater_folder.py starts the helper from a process that works in the installation folder, as the app does (it failed before the fix); test_preview_cache.py skips its link test where Windows allows no symbolic links and names the fake latexmk latexmk.exe on Windows; test_background_previews_gui.py keeps its progress while the planning thread runs.

NEW: Updates of the Windows folder version install again.
- After an update SlideMage reopened with the old version; it now starts the new one.
- A slide you render always shows its picture; it sometimes stayed at "No preview".
- Right after a render the Preview no longer calls the new picture a previous one for a second.
- Export LaTeX keeps the earlier export when it cannot replace it, and no longer fails now and then on Windows.
- If you have v8.51.0 or older, replace the SlideMage folder with the downloaded one once (it is next to it as SlideMage.update); later updates install by themselves.

v8.52.0 (2026-10-21, direct request: "render only when the SlideMage window is not focused, so that the response time when the user is looking at it, scrolling, etc., is not diminished"; then "in front, start after 60 s without input, stop on any input, never during a presentation"): Background previews give way to the user. idle_gate.IdleGate knows whether the window is in front (`note_focus`, from QApplication.applicationStateChanged in ui/workspace/background_previews.py; coming to the front counts as input) and whether a presentation runs (`presenting`, the workspace window's `presentation`). A background render may start once the window has been out of focus for LEAVE_GRACE (3 s), or in front without input for IN_FRONT_IDLE (60 s), instead of after 30 s without input; without a window reporting its focus the 30 s rule holds as before. The in-front rule applies during a sweep too and is the first reason given (`IN_USE`, "you are using SlideMage"); "Render now" overrides it. During a presentation nothing starts, not even after "Render now" (`PRESENTING`). Running background renders stop and go back in the queue (never a failure; `RenderScheduler.interrupt(P_IDLE)`) when the window comes to the front (`BackgroundRenderer.window_focus`), on any input while it is in front (`user_active`) and when a presentation starts (`presentation_started`, from ui/presentation/launch.py). The reveal slider's renders of the selected slide are not affected. Status texts: the chip says "Previews wait while you use SlideMage · N left", the dial's tooltip and the status window explain why and when they render (`IN_USE_EXPLAINED`, `background_previews.waiting_text`); the Settings caption and README.md describe the new rule. Tests: tests/test_idle_gate.py, test_render_scheduler.py, test_background_previews_gui.py.

NEW: SlideMage stays quick while you use it.
- Background previews render when you switch to another window, or after a minute without using SlideMage.
- Coming back, scrolling or typing stops them at once; they never run during a presentation.
- The previews chip says why they are waiting.

v8.52.1 (2026-10-21, direct request: "make the updater treat a release without this platform's file as no update yet"): GitHub lists a release as the latest as soon as its first file is attached, and the platforms' builds finish minutes apart (v8.52.0: the Linux folder after 2.5 min, the Windows folder after 5 min). A copy that checked in between was offered the release and the download failed with "Release ... has no download for this platform". `updater.plan_update(need_asset=True)` (the start-up check, and "Check for updates" in a copy that installs updates itself) leaves out the newest releases that do not have this installation's file yet; an older newer one is offered meanwhile, and the next check finds the new one. A release in between without the file (one built before that kind of file existed) still counts as passed over, so its breaking-change note is not lost. A copy run from source still hears of every release. Tests: tests/test_updater.py.

NEW: The updater offers a new version once its download is ready.
- Right after a release it no longer offers a version whose file for your computer is still being built.

v8.52.2 (2026-10-21, direct report: "SlideMage appears very delayed, not reacting to restoring the window from being minimized, not pausing rendering when the mouse is moving. When minimized ... there seems to be no progress"): Two loads, found by profiling the running app (py-spy), kept the window waiting and the background renders from getting anywhere. (1) The Preview counts the reveal steps of the neighbouring slides when it is idle, and asks after every refresh (`_probe_steps`, PROBE_MS). `CentreColumn._neighbour_targets` built each neighbour with `for_call` without a language, which uses the state's outline only when that is English; in German each of the six neighbours resolved every slot of the deck again, reading every slide's language header, on the GUI thread. The English Instructor frame numbers are now resolved once per deck text and shared (`_english_frames`), and the neighbour targets are kept while the slide, view, language and outline stay. (2) Every render ran `preview_build.prune_unused` before its compile: a pass over every wrapper of its folder, each under the process-wide build lock and a file lock. The background workspace held 671 wrappers (three per slide since v8.49.0), so the ten background workers queued behind one another there, could not stop when told to, and took the time the window needed. `maybe_prune_unused` runs the pass at most once every 10 minutes per folder (PRUNE_EVERY); a wrapper becomes old only after 14 days. A render told to stop while it waited now stops before its compile. Tests: tests/test_centre_gui.py (a German slide's neighbours resolve the deck once), tests/test_preview_build.py (the pass runs at most once in ten minutes per folder).

NEW: SlideMage reacts at once again while previews are prepared.
- With German selected, clicking around no longer makes the window lag.
- Background previews make progress again and stop promptly when you come back.

v8.52.3 (2026-10-21, direct report: "SlideMage does not stop background rendering when I move the mouse over the active window, or even when I select different slides"): The renders did stop (checked on Windows with real input events through the app's input watcher, BackgroundRenderer.user_active and the scheduler), but the chip and the dial went on saying "Preparing previews". They took the reason for waiting from the planner (`progress.paused_because`), which is a planner step old, and coming back to the window asked the planner for a rescan of every deck first, which took long in a large project; meanwhile `sweeping()` held for 60 s after the last start. `BackgroundRenderer.waiting_because()` now asks the gate directly whether the user is at the window or presenting (else the planner's reason); `sweeping()`, the chip, the dial's tooltip and the status window use it. A change of window focus and the start of a presentation no longer ask for a rescan (what is outstanding did not change); they refresh the display at once. Tests: tests/test_background_previews_gui.py (the chip says the renders wait as soon as the user is back; the earlier tests run as without a window that reports its focus).

NEW: The previews chip shows at once that rendering stopped.
- When you come back to SlideMage or use it, the chip says the previews wait, instead of "Preparing previews".
- Switching windows no longer makes SlideMage look through all decks again.

v8.52.4 (2026-10-21, direct report: "Even selecting a slide did not cause the rendering to stop, at least according to the display. However, when I clicked the progress number, it showed 0 processes running", and "the progress should only count down when a slide is really done"): Two errors in what background rendering showed. (1) The planner rebuilt the progress with the running render copied from the old one (`progress.working`); a render that ended during that scan stayed "working" in the copy until the next one started, and in front of the window none starts, so the chip said "Preparing previews" with nothing running. What runs is now read from the workers' own list under their lock, both when the planner rebuilds the progress and in `sweeping()`. (2) A slide whose stored render is right apart from its page number counts as fresh in the plan and is refreshed last; when that refresh was done it was counted again (`_count_fresh`), so the number left ran ahead by a batch and the next plan put it back up (582 -> 598). The plan now remembers those slides (`_counted`) and their refresh is not counted twice. New: background-trace.log in the cache folder (Windows: %LOCALAPPDATA%\SlideMage), a small file of what background rendering decided and when (focus in/out, input that stopped renders, starts and ends, the planner's reason, what the chip says), each with what the gate knew then; kept below 512 KB (the older part in background-trace.log.1). Tests: tests/test_background_renders.py (what runs comes from the workers; the trace lines; a refreshed page number is not counted twice), tests/test_background_previews_gui.py (a running render is the workers').

NEW: The previews count and chip are right.
- The chip no longer says "Preparing previews" when nothing renders.
- The number left only goes down when a slide is done, and no longer jumps back up.

v8.52.5 (2026-10-21, direct report with a screenshot: "When I click into the window, background rendering stops, but the status bar does not reflect that"; the status window said "Running now: 0" while its first lines said "Rendering now"): From the trace (background-trace.log) of the user's machine. Coming back stopped ten renders, but each stop waited for taskkill on its process tree (a few tenths of a second), one after the other, on the GUI thread and under the scheduler's lock: the window froze for about 2.6 s and the workers could not finish meanwhile. `CancelToken.request_stop(wait=False)` sets the stop at once and kills on a thread of its own; `RenderScheduler.interrupt` uses it. The chip, the dial and the status window's first lines counted a render as running until its worker had ended, which took up to 20 s for one in the middle of rasterising; they now count, as the status window's list does, only renders that have not been told to stop (`sweeping()` asks `scheduler.running_jobs()`). The trace logged "start" every time the scheduler asked whether a job may start (dozens a second while it waited for a place); it now logs when a render really starts. Tests: tests/test_render_scheduler.py (a stop does not wait for the kill), tests/test_background_renders.py (a render told to stop is no longer "Preparing"), tests/test_background_previews_gui.py.

NEW: Coming back to SlideMage is instant again.
- The window no longer freezes for a few seconds while background renders stop.
- The chip shows at once that previews wait, even while a stopped render is still ending.

v8.53.0 (2026-10-21, direct request: "when I scroll through the slide previews, updating lags noticeably, with the screen claiming that there is no preview yet popping up briefly quite often"; then "prefetch the neighbours' stored pictures, keep the last picture with Loading... while a check is out, and drop superseded checks while scrolling"): Scrolling through slides in the Preview. (1) Read ahead: once the selection rests, the stored pages (background renders) of the NEIGHBOURS slides next to the one on show are read and decoded on a worker of their own (`PreviewPane._prefetch_neighbours`, preview-prefetch), held by slide, view, language and file date (PREFETCHED, 16) and so kept across a change of slide; the slide scrolled to shows its page at once (`_stored_pixmap` takes it, the 5 s poll asks the store again later). Only stored pages: nothing is compiled. Reads of slides no longer next to the one on show are dropped while still queued. (2) "Loading...": while a check of the slide on show is out (its validation, its store lookup, or the rest after scrolling), the page that was on show stays, faint (`PageView.keep_dimmed`), and the status says "Loading..."; with nothing on show the page says so. "No preview for the ... view yet" comes only when the checks have answered and found nothing. The page of another slide is never shown as current: it is faint and authorizes no PDF. (3) Scrolling: a change of slide within SCROLLING_MS (300 ms) of the last starts no check (no validation, no store lookup of the page or of its reveal steps): the slide shows what is held or read ahead, and is checked when the selection has rested (SETTLE_MS, 150 ms, `_settled`). A single click still checks at once. Tests: tests/test_preview_queue.py (scrolling holds the checks back until the selection rests; the neighbours' pages are read ahead and the next slide shows at once; a blocked store keeps the previous page faint and loading; the earlier tests of "never the previous slide" now check that it is never shown as current), tests/conftest.py (tests change slides faster than anyone scrolls: SCROLLING_MS is 0 unless a test sets it).

NEW: Scrolling through slides is smooth.
- The slides next to the one you look at are prepared ahead, so the next one appears at once.
- While a slide loads, the previous one stays, faint, with "Loading..." instead of a flash of "No preview".
- Scrolling quickly no longer makes SlideMage check every slide it passes.

v8.54.0 (2026-10-21, direct instruction: "let's implement your earlier plan, keeping the compressed slides of the current view - language, deck version - in memory, plus the nearest 20 decoded"): The Preview reads ahead the stored pages of the whole open deck in the view and language on show, not only its four neighbours. Once the selection rests (`_settled`), `PreviewPane._prefetch_neighbours` orders every slide the view typesets (CentreColumn._deck_targets, built once per deck text, view, language and outline: about 50 ms for 400 slides) outward from the slide on show (one after, one before, two after, ...; `_preload_order`) and reads them on the read-ahead worker: the nearest PREFETCHED (20, about 8 MB each decoded) are held decoded, the others as their PNG (`_compressed`, at most PRELOAD_BYTES, 512 MB; at the limit the pages farthest from the slide on show give way, `_keep_compressed`). A slide that is held only as PNG is decoded when it is shown (a few milliseconds, `_preloaded`), without asking the store. Measured on a 762-slide deck: a stored page is 126 KB (median; up to 2.3 MB with large images) and decodes in 7 ms (23 ms at most). The worker rests PRELOAD_PAUSE (10 ms) before each store lookup so the GUI thread gets its turn; a slide whose store has no page yet is asked again after PRELOAD_RETRY (120 s), not at every rest; reads still queued are dropped and queued again in the new order at each rest. Another deck, view or language drops what was read ahead (`_drop_preloaded`, also when the pane closes); scrolling without a rest keeps at most PREFETCHED decoded pages. Only what the background renders stored is read: nothing is compiled. Tests in tests/test_preview_queue.py (the order through the whole deck, a page held as PNG is shown at once, a slide without a page is not asked again at every rest, another view drops them, the farthest give way at the limit).

NEW: The whole deck is prepared for scrolling.
- SlideMage keeps the stored previews of every slide of the open deck ready, so jumping to any slide shows it at once, not only the next one.

v8.54.1 (2026-10-21, direct report: "when I duplicated a deck - p-Doctoral-School-2026-11-16 -, I needed to restart the app for it to show up in the deck list. I also believe it did not get the workdeck tag even though I chose it"): Duplicate deck… stopped right after copying the file whenever the copy was to get another group than the original's: it read the copy for the tag write with deck_editor.read, which v8.3.7 (shared file I/O) had renamed to fileio.read_text_exact without updating this caller. The AttributeError was not among the errors the action catches, so the group was never written and the decks were not scanned again: the copy came up only after a restart, without the group chosen. deck_actions.on_duplicate_deck now reads it with read_text_exact. Test in tests/test_duplicate_deck_gui.py (the copy is in the deck switcher at once, with the group chosen).

NEW: Duplicating a deck works again.
- A duplicated deck shows up in the deck switcher at once, with the group you chose (for example Workdeck).

v8.55.0 (2026-10-21, direct requests: "When I right-click a section and select Remove section, I want to be asked whether I just want to remove this section, this section and all of its slides - remove from the deck, not delete the slides, obviously -, or remove all sections from the deck" and, on where the deck source is, "deck source needs to be wired in somewhere"): The slide list's Remove section… asks now (dialogs/remove_section.RemoveSectionSheet): only the section, its slides staying in the deck (as before, and the choice it starts on); the section and its slides (deck_editor.remove_section_and_calls: the marker and every slide call of the section, folded calls included, in one stale-checked write; other lines of the section, comments for instance, stay; the slide files stay in the project); or every section of the deck, all slides staying (deck_editor.remove_all_sections, offered when the deck has more than one; refused as a whole when one marker shares its line with other text). Each is one deck edit, which Undo takes back. Edit deck source is in the ⋮ menu under This deck, not only in Ctrl+K. Tests in test_section_editor.py, test_slide_list_gui.py and test_more_menu_gui.py.

NEW: Removing a section asks what to remove, and the deck source is in the ⋮ menu.
- Remove section asks whether to remove only the section, the section with its slides (they leave the deck, their files stay), or all sections of the deck.
- Edit deck source is now in the ⋮ menu under This deck.

v8.56.0 (2026-10-22, direct requests: "When editing the .bib file, SlideMage offers the formatting toolbar. This makes no sense in this text-only file. The same is true when editing a deck source", "Give it an x to close it and return to the previous view ... When the user switches to the preview instead of clicking the x, also close the deck source, asking for whether to save in case changes were made", and "Can we generally make the autosave functionality optional? Turn it on by default, but I personally do not like it, so I would like to turn it off in the settings or using a similar switch near the menu or title bar as is available in Office"): AutoSave can be switched off: the top bar's AutoSave switch, shown in the full bar, Settings -> General -> Saving, and Ctrl+K "Turn AutoSave off/on" (command autosave; WorkspaceWindow.set_autosave) set one choice of this user and machine, layout_settings "autosave", on unless switched off (source_file.autosave_on). Off, the Source view writes a file only on Ctrl+S: no autosave timer, and neither leaving a file nor a flush before a run writes it (SourceFile.write_now writes only when explicit or forced); a file with unsaved edits stays open and counts as unsaved (SourceFile.unsaved, SourcePane.blocked_files: the top bar's "Unsaved changes", "1 more not saved", the question on closing the window), and its toolbar says "Not saved - Ctrl+S". Actions that change a file themselves still write its edits first (write_now force: deck edits, slide rename and move, Add slide copies, image replacement, restoring a version, Add reference). Switched on again, the edits that wait are saved shortly (SourcePane.autosave_changed). A deck's own source and Slidemaster.bib are plain text: the Source view shows no formatting row for them, Ctrl+B, Ctrl+I and Ctrl+U do nothing there, and an "x" closes them and goes back to the focused slide in the mode it was in before the file was opened (CentreColumn.close_explicit_file). A switch to Preview or Details closes them too; edits that would be lost, with AutoSave off or a save that could not be made, are asked about, Save, Discard or Cancel, and Cancel keeps the file open in the Source view. Tests in test_source_view_gui.py, test_centre_gui.py, test_settings_gui.py and test_topbar_tab_order_gui.py.

NEW: AutoSave can be switched off, and a deck's source and the .bib close with an x.
- AutoSave, on by default, can be switched off in the top bar or in Settings; then Ctrl+S saves, and unsaved files are pointed out before they are left or the window closes.
- A deck's source and Slidemaster.bib show no formatting buttons; their x, or a switch to Preview, goes back to the slide you were on, asking about unsaved changes.

v8.57.0 (2026-10-22, direct request: "Build the updated menu on a separate branch so I can see it in the app", after the menu bar plan agreed the same day): The window has a menu bar again, in place of the top bar's ⋮ button: File, Edit, Deck, Slide, View, Build, AI, Housekeeping and Help (menus.py MENU_BAR, build_menu_bar, fill_menu), with every command of the registry; Deck → Switch deck is a submenu of the decks grouped as in the deck switcher. Each menu fills itself from the registry when it opens: labels, enabled states, radio items for View as, language, centre mode and the AI route, section titles as kitMenuHeader labels, submenus for Rewrite selection as, Export, Visibility, Section and Side panel. An item shows its key after a tab but binds none, so the window's shortcuts stay the only bindings. New commands: compile:current, Compile PDF of the view shown, Ctrl+Shift+B, since Ctrl+B is bold in the Source view; save, find, replace and render_buffer, which show the keys the window and the Source view bind themselves through the new Command.hint, also shown by key_text; switch_deck; open_manual, F1, switches to the manual deck; shortcuts, Keyboard shortcuts…, a sheet built from the registry plus the Source view's and slide list's own keys, dialogs/shortcuts.py. View as gets Ctrl+1, Ctrl+2 and Ctrl+3; Exit shows Alt+F4 and binds nothing. build_registry takes mac, default sys.platform == "darwin", and applies MAC_KEYS there: Settings ⌘, and Deck settings ⌥⌘, , Present ⌥⌘P, no F1, Quit from QuitRole; Settings, Exit and Version history get the macOS menu roles, and the Source view's replace key is ⌥⌘F on a Mac, source_file.REPLACE_KEY, as ⌘H hides the app there. The ⋮ button, MORE_COLUMNS, MORE_FOOTER, MORE_NOTE and build_more_menu are gone; kit_qss styles QMenuBar from the tokens. The Settings and Deck settings rows, the Compile menu and the ⌘K palette stay. Tests: test_menu_bar_gui.py replaces test_more_menu_gui.py; conftest gets menu_bar_ids, filled_menu and menu_actions; test_commands.py, test_workspace_window.py, test_manual_group.py, test_rerender_deck_gui.py, test_latex_export_gui.py, test_ai_switch_gui.py, test_accessibility_gui.py and test_topbar_tab_order_gui.py follow. Merged into develop after v8.56.0, AutoSave: File → Turn AutoSave on/off joins Save in the File menu, so every command stays in the menu bar; the hints in Settings → Updates, the update notice and a test deck's empty centre point to Help → Check for updates… and Deck → Edit deck source instead of the ⋮ menu. Manual updated through v8.57.0 (the last full pass was v8.19.1; every NEW: section since then checked, direct instruction: the manual is brought up to date before every release, and each update is noted here): slides 1ub, 1ti, 1b6, 1an, 1b2, 1gu, 1kg, 1vd, 1d8, 1kp, 1nu, 1hi, 1r8, 1nk and its German qft, 1jv, 1v5, 1wk, 1az and 1d7 name the menu bar instead of the ⋮ menu and cover AutoSave, Remove section…, Update versions… for several slides, the Details view's translation and earlier versions, background previews, the reveal-step bar and the mouse wheel, Ctrl+Shift+B, Export LaTeX…, Dark slides, Settings → Ollama and AI setup, the Windows and Linux downloads as one file or a folder, and the Not reviewed filter (v8.3.11, never in the manual); the new slide 1je, Presenting, covers F5, the presenter keys, Settings → Presentation and Present a PDF… The Working in SlideMage divider sets SMChapterAgendaMaxHeight for its intro line. New screenshots; tools/manual/make_screenshots.py works again: it shows the cached preview through PreviewPane._image (the DisplayCache of v8.54.0 took item assignment away), keeps the window off screen with the native platform on Windows (offscreen drew labels in the icon font since the fonts of v8.27.3), tolerates a lock left in its throwaway copy, and crops for the menu bar. README and docs/SlideMage.md: AutoSave can be off; the menu bar is v8.57.

NEW: A menu bar replaces the ⋮ menu.
- Nine menus (File, Edit, Deck, Slide, View, Build, AI, Housekeeping and Help) list every command, with its keyboard shortcut.
- New shortcuts: Ctrl+1, Ctrl+2 and Ctrl+3 switch the view, Ctrl+Shift+B compiles the PDF of the view shown, F1 opens the SlideMage manual.
- Help → Keyboard shortcuts lists every key.
- AutoSave can also be switched on and off in the File menu.
- The SlideMage manual (F1) is up to date: the menu bar, AutoSave, removing sections, background previews, and a new slide on presenting.

v8.58.0 (2026-10-22, direct requests: "What are all the decks/_slidemage_preview-...tex files? Can they be removed? If they still serve a purpose, can such files in the future be put in the .build folder? Also, when I duplicate a deck, open the new deck", "Make shift-tab decrease indentation in a source edit tab", "Move the Autosave toggle to the right of Help in the menu bar, and make it more clearly a toggle by restyling it like the View as setting, with on and off options" and "save all AI model-related settings in the SlideMage folder structure, not the project folder structure"): A preview's wrapper, the small deck latexmk compiles for one slide, is written to .build/preview-wrappers/ (preview_build.wrapper_dir, also for slide_preview._compile_fresh) instead of decks/, where a cached render kept one per slide, view and preamble for up to UNUSED_DAYS. latexmk still runs in decks/ with -cd-, as for a background workspace's wrapper, so the ../ of the deck preambles and the bibliography resolve as before; -cd- now comes after the -r of a project rc file, which may set $do_cd and had made latexmk change into the wrapper's folder. active_build takes the project root for its maintenance lock instead of the folder above the wrapper. prune_unused also looks in the new folder; remove_legacy_wrappers deletes the old wrappers in decks/ once per project and session, their caches kept: none is read any more. Duplicate deck… opens the copy, as New deck… does. In the Source view Shift+Tab takes one indentation level off the cursor's line or every selected line, a tab or up to a tab's width of spaces (latex_edit.outdent_width), and Tab on a selection of several lines indents them, one undo step each; the editor handles both in event(), which saw Shift+Tab as a focus move; Keyboard shortcuts lists them. AutoSave is an On | Off segmented control right after the menu bar's Help (autosave_switch.AutoSaveSwitch, a child of the QMenuBar placed after its last menu on every layout, hidden while that menu is in the overflow; slimmer segments keep the bar's height and the window's 640 px minimum); with a native menu bar, macOS, it sits in the top bar before Saved. The top bar's AutoSave chip is gone. The AI settings of this computer -- the models per route and task, what Cloud means, the Ollama server, the API key's file fallback and the per-task model keys of before v8.0 -- are kept in SlideMage's own folder, config_dir()/ai_settings.json (app_settings.MACHINE_KEYS, MACHINE_STORE_PATH), for every project on it; load() and save() split and merge them, and the first load of a project moves any it still holds out of it, a value already on this computer winning. The project keeps its Local/Cloud policy, the Cloud first-use flag, the German form of address and the prompts. Settings → Cloud says where a saved key now is. tools/manual/make_screenshots.py uses throwaway layout and AI settings files, so the shots no longer depend on this computer's. docs/plans/editable-deck-tags.md plans user-editable deck groups: kept with the project, built-in groups removable, a deck in several groups (direct decisions the same day). The Windows build carries pywinpty's OpenConsole.exe and winpty-agent.exe (packaging/slidemage.spec, WINPTY_HELPERS; the release workflow checks the folder build for them): conpty.dll starts a program through them, and without them the Claude Code terminal's claude got a console closed at once and ended before printing anything, exit code -1073741510 (0xC000013A), in every Windows release with the terminal (direct report: "When I switch to Claude Code, I get" that). Update version offers New slide… besides Major, Minor and Patch (direct request: "offer the option to save this version as a new slide"): the changes since the slide's version become a slide of their own with a fresh id and history (slide_branch.save_as_new_slide, slide_add.create_copy), the slide goes back to that version without using up a number (slide_versioning.revert_to_version), and the decks ticked in NewSlideVersionSheet, the edited one ticked to begin with, load the new slide instead (deck_editor.retarget_slide_calls: every call that follows the current content, keeping its kind, conditions and steps; calls pinned to a version stay). The new slide opens. Manual updated through v8.58.0: 1an has New slide… and the new dialog, 1ub shows and numbers AutoSave after Help, 1kp says Duplicate deck… opens the copy, 1hi that model choices are kept on this computer; new screenshots. Tests in test_preview_build.py, test_slide_preview_cleanup.py, test_duplicate_deck_gui.py, test_latex_edit.py, test_source_indent_gui.py, test_menu_bar_gui.py, test_topbar_tab_order_gui.py, test_app_settings.py, test_packaging.py, test_slide_branch.py and test_slide_versions_gui.py.

NEW: Claude Code works in the Windows download, changes can become a new slide, duplicated decks open, AutoSave is an On | Off switch, and AI settings stay on your computer.
- The _slidemage_preview files no longer appear in your decks folder; the ones there are removed.
- Duplicate deck… opens the copy.
- In the Source view, Shift+Tab unindents the line or the selected lines; Tab indents several selected lines.
- AutoSave On | Off sits right after Help in the menu bar.
- Your AI model choices, the Ollama address and a saved API key are kept on this computer, for all your projects, not in the project folder.
- The Claude Code terminal works in the Windows download: it ended at once with exit code -1073741510.
- Update version can save your changes as a new slide instead, used in this deck (and others you tick), while the slide itself stays as it was.
- The SlideMage manual (F1) is up to date.

v8.59.0 (2026-10-23, direct requests: "When I hover over a slide title in the split view's source window, show the full title in the hover text" and "When clicking Update slide, also offer an overwrite option"): The Source view's file name, the slide's id and title, is cut with an ellipsis where the pane is narrow, the Split view, and shown whole in its tooltip (an ElidedLabel that takes the header's free width; it was a plain label that the layout clipped). Update version offers Overwrite vX.Y.Z beside Major, Minor, Patch and New slide: the changes go into the version they were made to, which keeps its number, and the slide is written without its "+" (slide_versioning.overwrite_version, CentreColumn.overwrite_version); decks pinned to that version get the change too, as the question says. Nothing changed since that version: refused, as before. Tests in test_slide_versions_gui.py and test_source_view_gui.py.

NEW: Update version can overwrite the version, and long slide names show whole on hover.
- Update version offers Overwrite: the changes go into the current version number instead of a new one.
- Hovering over the slide name at the top of the Source view shows the whole name when it is cut off, e.g. in Split view.

v8.59.1 (2026-10-23, Jürgen's PR 16 merged: the Linux launcher icon follows the system theme): The Linux app icon (assets/icon.svg, shipped in SlideMage-linux.zip for the desktop entry) carries both palettes of the logo mark and picks one with prefers-color-scheme: the black front slide on a light system, the off-white one on a dark system. Renderers that ignore the media query show the light palette, as before; Qt's renderer is one of them, so the logo in the top bar is drawn exactly as before. The Windows icon.ico is unchanged.

NEW: The Linux launcher icon now matches a dark system theme too.
- On a dark desktop the front slide of the logo is light instead of black.
- Whether the launcher switches by itself depends on your desktop; if not, it shows the same icon as before.

v8.60.0 (2026-10-23, docs/plans/editable-deck-tags.md with the direct decisions "the groups belong to the project, built-in groups can be removed, and a deck can be in several groups" and "There is no need to distinguish between a deck's main and other groups, it is just listed twice"): Deck groups are data of the project instead of fixed tags. deck_groups.py holds the ordered list of DeckGroup(tag, label, heading, roles, fallback), stored in full under "deck_groups" in .slidemage/project.json once edited; without an entry, or with one that does not validate, the defaults apply, which reproduce the groups of before: work pinned, course the fallback, research, test with the test role. The roles carry the behaviour: pinned decks come first without a heading, test decks have no slide list and no background previews; each role and the fallback sit on at most one group, and removing the group removes the behaviour. manual stays reserved and outside the list. scan_decks gives every Deck its groups, in switcher order, and the union of their roles; Deck.group is the first of them, which the compile order still uses, so a deck is compiled once. menus.deck_sections lists a deck under each of its groups, the same way under each, for the deck switcher, Deck → Switch deck and Several decks…, whose checkboxes of one deck are linked; decks naming no group go to the fallback group, else to an "Other decks" section shown only when needed. The Tags…, Duplicate deck… and New deck… sheets have one checkbox per group, none allowed, and say where an unchecked deck goes; tags_with_groups sets exactly the chosen group tags and keeps every other tag. The course URL and the palette's deck entries look at all of a deck's groups. Settings → Project → Deck groups, settings_deck_groups.py: add a group with its tag proposed from the label, edit heading, label, roles and fallback with a question before a role moves, move up and down, remove any group, offering for decks that carry its tag to move them to another group, take the tag off or leave it, one undo step per rewritten deck, restore the default groups keeping the user's own, and Found in decks with Add as group for tags no group knows; every change is saved at once and the decks are rescanned. Deck → Tags… has Edit groups…, which opens that section, window.open_deck_groups, and then asks again. Note: a deck tagged both course and test is now a test deck; before, the first known tag decided. Manual updated through v8.60.0: 1d8 explains groups of the project's own, several groups per deck and Edit groups…, with a new screenshot of the Tags sheet; 1r8 lists the deck groups under Settings; README's deck tags section describes the editable list. Tests in test_deck_groups.py, test_deck_in_several_groups.py, test_settings_deck_groups_gui.py, test_manual_group.py, test_duplicate_deck_gui.py, test_menu_bar_gui.py and test_settings_gui.py.

NEW: Deck groups are yours to edit, and a deck can be in several groups.
- Settings → Project → Deck groups adds your own groups, renames them, changes their order in the deck switcher and removes any group, the built-in ones too.
- The groups belong to the project, so everyone working on it sees the same ones.
- Deck → Tags… has a checkbox per group; a deck in two groups is listed under both.
- Tags… has an Edit groups… button that takes you straight to the list.
- Decks without a group are listed under Other decks if no group is marked to take them.
- The SlideMage manual (F1) is up to date.

v8.61.0 (2026-10-23, direct requests: "When all previews are rendered, add a green All previews are up to date. status text", "Move the Local/cloud selection from the top of the SlideMage window to the top of the Cloud element on the bottom right of the screen" and "When the user switches the Claude Code model in the local/cloud selection dropdown and a Claude Code session is running in SlideMage, offer to restart the cloud session to implement the switch. Alternatively, SlideMage could simply send a /model change to the active Claude Code"): The background previews' chip stays once everything is rendered and says "All previews are up to date." in green (BackgroundPreviews.summary, tone ok); before, it disappeared. The Local | Cloud AI switch (ai_switch.AiSwitch) is the first row of the assistant card instead of the top bar (assistant_header.AssistantHeader.ai_switch, window.ai_switch), so every AI control is in one place: one row with Focus and New conversation, in place of the route's icon, name and what the conversation runs on, which is now the second line of the switch's tooltip (AiSwitch.set_note); the model also shows under the message box. The card keeps its height, so a 640 px window still fits the conversation. The switch drops the connection's name below a header 360 px wide, as in the default column, and its labels below 280 px. The top bar, without it, needs less room: full below 1400 px instead of 1500, narrow below 1100 instead of 1320. The texts that pointed to the switch in the top bar (Settings, the route badge of the AI dialogs) say where it is now. Changing the default Claude Code chat model or effort in AI setup while Claude Code runs in the terminal asks what to do (ai_setup.ask_session_model): Switch now restarts it on the new default in the same conversation, New conversation restarts it afresh, Later leaves it; nothing is asked when it runs on the new default already (ClaudeCodeSession.model, effort). Every Claude Code SlideMage starts gets its own --session-id; Switch now (ClaudeCodeView.switch_session) sends Esc Esc, which puts text not yet sent into Claude Code's input history, where Up finds it again, and stops a reply being written, and then starts it with --resume and the new --model and --effort, which apply to that session only. A session without a saved transcript, where nothing was sent yet, starts afresh (claude_launch.has_transcript). Typing /model instead would also have made the model Claude Code's own default for every session; checked with Claude Code 2.1.309. The top bar imports Qt's SVG module, without which QIcon drew its logo empty in a run from source. Manual updated through v8.61.0: 1ub numbers the switch in the assistant and its callouts follow the shorter top bar, 1gu mentions the green chip; all screenshots made again. README: the switch's place, the question about a running Claude Code, the green chip. Tests in test_background_previews_gui.py, test_ai_switch_gui.py, test_accessibility_gui.py, test_assistant_gui.py, test_chat_gui.py, test_claude_launch.py, test_claude_scope.py, test_settings_gui.py, test_topbar_tab_order_gui.py and test_workspace_window.py.

NEW: The Local | Cloud switch moved into the AI assistant, and a finished background render says so.
- Local | Cloud now sits at the top of the AI assistant on the right, with the rest of the AI controls; the top bar has more room.
- When all previews are rendered, a green "All previews are up to date." appears next to the progress dial.
- Changing the Claude Code model in AI setup while Claude Code is running asks whether to switch the running session now, keeping the conversation and anything you had typed but not sent (press Up), or start a new conversation.
- The SlideMage manual (F1) is up to date.

v8.61.1 (2026-10-27, pre-publication clean-up: the wizard sprite sheet was a 2.4 MB PNG, most of the weight of the shipped assets): The AI-edit animation's sprite sheet (assets/wizard-poses.png, used by wizard_portal.WizardPortal) is now assets/wizard-poses.webp, a lossy WebP at quality 90 with the same 1536x1024 size and alpha channel: 403 KB instead of 2.4 MB, and no visible difference on the workspace's background (mean colour error under 3 of 255). A lossless PNG could not get below 1.8 MB because the sprites are painted, not flat colour, and a 256-colour PNG showed dithering noise in the beards. Qt loads it through the qwebp image-format plugin, which PySide6 ships and the PyInstaller build already collects (it is in the installed build's PySide6/plugins/imageformats). The SlideMage manual needs no change, nothing the user sees is different.

NEW: The AI-edit wizard animation's image is much smaller (2.4 MB to 0.4 MB), so SlideMage's download is smaller.
- No visible change; the wizard looks the same.

v8.62.0 (2026-10-25, direct requests: "a QR-code generator that takes a URL as an argument and returns a QR code in vector format that we can save in the project or also in a location of the user's choosing and put somewhere on a slide", with URL as the default and email, contact, calendar entry and map location as options, the caption as an option or a user-defined text such as "QR 1", PNG output too, an info text listing the recommended sizes for seminar room and lecture hall, the AI tool in the first version and an "Insert QR" button in the slide edit tab): New qr_code.py makes QR codes with segno, a new dependency: pure Python, BSD-3-Clause. A code holds a link, normalized to https:// when it has no scheme; a mailto: link with subject and body; a vCard 3.0 contact, "Family, Given" or "Given Family"; an iCalendar VEVENT whose times are converted from local time to UTC, all-day events as dates with the exclusive end day, text escaped as RFC 5545 asks; or a map location from an address, coordinates or a pasted Google Maps, OpenStreetMap or Apple Maps link, as a Google Maps link by default, a geo: URI or an OpenStreetMap link, with no geocoding service. Files are PDF, the project's default, or PNG of at least 1000 px in media/, and a copy anywhere as PDF, PNG, SVG or EPS; black on white with a quiet zone of 4 modules; PDF, SVG and EPS are drawn by qr_code.py itself as one filled rectangle per run of dark modules, since segno's own vector output strokes each row without setting a line width and, placed on a slide, took the slide's thin lines, which left every row a hairline; an existing file is never overwritten, names follow the caption or the content, so a "QR 1" caption gives qr-1.pdf. The recommended height is the code's share of the text height at which the farthest viewer can still scan it: a module reads from about 500 times its size away and the farthest seat is about 4 screen heights away in a seminar room, 8 in a lecture hall, so a 29-module link needs 0.30 and 0.59; error correction is M for links and L for contacts and events, where coarser dots matter more than recovery from damage. media/qr-codes.json keeps what each code was made from; its alt text goes into media/alt-text.json as reviewed. New \SMQRCode[height]{image}{caption} in Slidemaster_preamble_base.tex: the code at a default 0.6\textheight with the caption centred under it, as wide as the code, in \SMQRCodeCaptionStyle; an inline box, so codes go side by side or into \cornerfigure. A link caption is \url, which breaks at slashes. The image scan for alt texts, the pre-render check for missing images and the transcript know \SMQRCode; the transcript keeps the caption. The Source view has a QR button after Cite, with the tooltip "Insert a QR code for ..."; its short label keeps the format row, which sets the pane's smallest width, 40 px shorter than "Insert QR" would. Its sheet, ui/dialogs/qr_code.py, has fields per kind, with date and time pickers and All day for events, a live preview, the grid size and the recommended heights for both rooms, a warning below the seminar room's, height, caption None, Its text or Custom, file name and format, Also save a copy… and Advanced with error correction and quiet zone. Opened with the cursor on an \SMQRCode call it made, it opens filled in as Update and writes the same file again. Date and time fields have the look of the other fields in the kit style sheet. The assistant's new make_qr_code tool, also offered to Claude Code, makes the file and returns the call with the recommended heights; the images guide mentions it. README: \SMQRCode under Layout helpers. preview_equivalence.py: the base preamble's audited hash follows, as \SMQRCode has no view-dependent rule, and \SMQRCode is a safe slide command. Tests in test_qr_code.py, test_qr_dialog_gui.py, test_agent_tools.py, test_mcp_server.py and test_source_view_gui.py, whose long file name is longer now that the row is wider.

NEW: QR codes for slides.
- The QR button in the Source view, next to Insert and Cite, makes a QR code for a link, an email, a contact, a calendar event or a map location and puts it on the slide.
- A live preview shows the code and the height it needs on the slide for a seminar room and for a lecture hall.
- Under the code goes the link, a text of your own such as "QR 1" for the slide's text to refer to, or nothing.
- The code is a PDF or PNG in media/; you can also save a copy anywhere as PDF, PNG, SVG or EPS.
- Put the cursor on a code's line and click QR to change it.
- The AI assistant can make QR codes too.

v8.62.1 (2026-10-26, direct request: "when I tried to close SlideMage, it told me bb6 still had unsaved changes. I clicked save, but it didn't ask me which version to save under", answered with: only with the setting): Closing SlideMage, opening another project and restarting for an update count as leaving every slide edited since it was last left, the one on show included: with Settings → General → "Ask about Update version when leaving a changed slide" on, each such slide whose current file has its "+" gets that question after the unsaved edits are saved, as a switch to another slide would (CentreColumn.offer_versions_on_close, called at the end of the window's _resolve_dirty_edits). Before, only a switch asked, so the slide still on show at the end was never asked about. Edits discarded on closing are not asked about. Tests in test_centre_gui.py.

NEW: Closing SlideMage asks about Update version too.
- With "Ask about Update version when leaving a changed slide" on in Settings → General, closing SlideMage asks it for each slide you changed, including the one still open.

v8.63.0 (2026-10-26, direct requests: "the settings window gets cut off. It should get a scrollbar and be less tall so it fits the screen", "Give me the option to insert a \cornerfigure[corner=se]{} command in the Insert menu", "Make the QR default to no caption below the code", "In the QR insert dialog, offer an option of inserting the QR with a cornerfigure" and "Remove the Source button from the toolbar of slide edit tabs"): A sheet tab added with ModalSheet.add_tab(..., scroll=True) scrolls, and the sheet opens as tall as its tallest such tab needs, at most 85 % of the screen, centred on it (fit_to_screen); every Settings tab does, so its bottom and Close are reachable on any screen. The Source view's Insert menu has \cornerfigure[corner=se]{...}, which wraps the selection or leaves the cursor in its braces. A new QR code has no caption unless one is chosen; the make_qr_code tool takes caption "auto" for the link or the other content. The QR sheet's new "On the slide" puts the call where the cursor is or in a corner, top or bottom, right or left, inside \cornerfigure[corner=...] (qr_code.place, CORNERS); the tool takes corner too. Update keeps a code where it is. The Source view's format row no longer has Source, the \source button; Footnote stays. Tests in test_settings_gui.py, test_insert_popovers_gui.py, test_qr_dialog_gui.py and test_agent_tools.py.

NEW: Settings fits your screen, QR codes can go in a corner, and the Insert menu has \cornerfigure.
- Settings is never taller than the screen; each tab scrolls when it does not fit.
- The QR button's sheet has "On the slide": where the cursor is, or a corner of the slide.
- New QR codes have no caption unless you choose one.
- Insert has \cornerfigure[corner=se]{...} for an image or other content in the bottom-right corner.
- The format row of the Source view no longer has the Source button.

v8.63.1 (2026-10-26, direct request: "When I search for a slide using the Find anything option and I edit its source and click to render the preview, I jump back to the slide I was on before searching", fixed as proposed): A slide focused that the open deck does not show, opened from Find anything, keeps the focus. The slide list had no row for it and left its highlight on the slide shown before, and its rebuild after a save or a render made that row the focused slide again. Now the list clears its highlight and selection when the focus goes to a slide it does not show (SlideList._on_state_focus), and a rebuild makes a row the focused slide only when the focused slide was or is one of the deck's, so a removed slide still hands the focus to the one that took its place. Tests in test_palette_gui.py.

NEW: A slide opened from Find anything stays on show when you save or render it.
- Before, if the slide was not in the open deck, saving or rendering it jumped back to the slide you were on before searching.

v8.64.0 (2026-10-26, direct requests: "Switching the Claude model does not retain typed prompt text that has not been sent", "Move the scrollbar in the settings a bit to the right, so there is a little margin between text and scrollbar" and "The Find anything displays only a subset of the results it finds - how can I see the others?"): Switch now keeps the prompt typed in Claude Code but not sent. Esc Esc alone did not keep it: the text is now read off the terminal's screen before the restart, the input box being the last prompt line under a rule, its text what is not dim, which leaves out Claude Code's grey placeholder (terminal/draft.py; terminal.js's screenLines, TerminalWidget.read_screen, as JSON since a nested array did not come through). Once the restarted session's input box is on the screen, empty, the prompt is typed into it again, not sent: as keystrokes, or as a bracketed paste when it has line ends. It is looked for every 300 ms for 20 s; Esc Esc still stops a running reply and puts the prompt into Claude Code's input history too. Checked against the real terminal widget with a box drawn as Claude Code draws it, not with Claude Code itself. A scrolling sheet tab, every Settings tab, keeps 14 px between its content and the scroll bar (SCROLL_GAP). Find anything lists 8 slides and 10 text matches, as before, and now ends a longer group with Show all N, which lists every one, up to 200, and keeps the palette open on the row after it; the heading says how many there are, slides included now. A new search lists 10 again. Tests in test_terminal_draft.py, test_ai_switch_gui.py, test_settings_gui.py and test_palette_gui.py.

NEW: Switch now keeps your unsent prompt, and Find anything can show all results.
- Switching the Claude Code model with Switch now puts the prompt you had typed but not sent back into the input box.
- In Find anything, a list of slides or text matches that is cut short ends with Show all, which lists every one of them.
- The scroll bar in Settings no longer touches the text next to it.

v8.64.1 (2026-10-27, AI tools review, docs/AI_TOOLS_FIX_PLAN.md step 1): The "This slide" scope is enforced by the agent tools themselves, not only by the Claude Code hook. Over MCP, modify_slide, create_slide and add_slide could change any slide or deck while the scope was Slide; the built-in chat had the scope as context text only. ToolContext now carries the scope and the focused slide (None: unrestricted, as for the headless tasks); edit_file, write_file and modify_slide (on the file actually written, after the EN/DE partner) refuse a slide or deck other than the focused slide, and add_slide and create_slide refuse in Slide scope since they change the deck, all pointing to switch_to_deck_mode. One rule for hook and tools (claude_scope.scope_problem, deck_problem). Agent.run sets the scope per request; the Claude Code session reads it with the focus on the GUI thread per MCP call. Tests in test_agent_tools.py, test_agent.py, test_mcp_server.py and test_claude_code_gui.py.

NEW: In "This slide" mode, the assistant can no longer change other slides or the deck.
- Before, the built-in chat and the tools Claude Code uses through SlideMage could still reach other slides; now they ask to switch to Deck mode first.

v8.64.2 (2026-10-27, AI tools review, docs/AI_TOOLS_FIX_PLAN.md step 3): One source of tool guidance. The chat's system prompt (agent_context.SYSTEM_PROMPT) and Claude Code's ORIENTATION re-described the tools' arguments, defaults and results and had drifted from the tool descriptions: both called refresh_deck_previews "legacy Instructor snapshots (only)" while it refreshes all course views by default. The prompts now keep the workflow (read before changing, which tool for which job, what is slow, readability fixes, protected parts, answer style) and leave what a tool does to its description (SYSTEM_PROMPT 5.4k to 4.4k characters, ORIENTATION 3.3k to 2.5k). read_file, check_readability and write_file descriptions are more precise. test_tool_guidance.py fails when a prompt names a tool its assistant does not have.

NEW: The assistant gets shorter, consistent instructions about SlideMage's tools.
- The assistant's instructions about SlideMage's tools are shorter and no longer contradict the tool descriptions.

v8.64.3 (2026-10-27, AI tools review, docs/AI_TOOLS_FIX_PLAN.md step 2): modify_slide edits the file it was given. It followed the EN/DE switch to the linked translation partner even for an explicit path, so an edit aimed at a DE slide while editing in EN landed on the EN slide, and a given expected text was compared with the partner's and failed as "changed since you read it". Now only a bare slide id ("1y8") follows the switch, and the result says so ("1y8 in DE is its partner xyz-DE-Hallo"); a path is used as given. The scope check stays on the file actually written. Tests in test_modify_slide.py and test_agent_tools.py.

NEW: The assistant's slide edits land on the slide it named.
- Before, an edit of a German slide while editing in English could change the English version instead.

v8.64.4 (2026-10-27, AI tools review, docs/AI_TOOLS_FIX_PLAN.md step 4): The agent tools' arguments are checked one level deeper. check_arguments looked at top-level types and enums only, so each tool checked nested input by hand or not at all. It now follows the schema down: types including number (not a boolean), enum, minLength, minItems, array items and nested objects' properties, required and additionalProperties, and its errors name the path the model passed ("Argument 'edits[2].old' must be of type string."). modify_slide's own check of its edits and make_qr_code's of the height type are gone; a QR code's fields must be text (a phone number sent as a number would lose its leading zero), a bibliography entry's may still be numbers (a year). Tests in test_agent_tools.py.

NEW: The assistant gets clearer messages when it calls a tool with wrong arguments.
- When the assistant passes a tool wrong arguments, the message now says which one is wrong, also inside nested input.

v8.65.0 (2026-10-27, AI tools review, docs/AI_TOOLS_FIX_PLAN.md steps 5-7): One preview path, insert_slide, and cleanups of the agent tools.

After the assistant writes a slide, its preview now comes from the same batch path as render_preview (preview_batch_output gets an explicit language and a show flag; _render_preview is gone), so the image after modify_slide or create_slide and the one render_preview gives for that slide agree. The target is resolved before the slide is shown, a hidden slide is not shown, and showing the slide in focus keeps its occurrence in the deck (GuiWorkspace.show_slide), so the pane accepts the image of a slide the deck calls twice.

Inserting an existing slide into the deck is its own tool, insert_slide (slide, after); add_slide only creates (a skeleton or a translation copy) and no longer takes existing. A translation is placed after its source, read from the editor's buffer. create_slide's deck is optional: the open deck by default, still refused when another is named.

CLAUDE_CODE_READ_ONLY is CLAUDE_CODE_PRE_APPROVED (refresh_preview writes the preview cache); a failed tool call logs tool_end with error; each call gets its own copy of the tool context; edits.not_frozen is public. test_chat_gui's closed-file edit runs in the scope Deck, as v8.64.1 requires. Tests in test_modify_slide.py, test_chat_gui.py, test_agent_tools.py, test_create_slide.py, test_translation_placement.py and test_mcp_server.py.

NEW: After the assistant edits a slide, the preview shows it in the slide's own language and position.
- Before, the preview after an edit and a preview the assistant asked for could show different languages, or the wrong copy of a slide used twice in a deck.

v8.66.0 (2026-10-27, direct requests: "Check how it is possible that SlideMage reports 268/252 Instructor slides rendered for the t-Uni-FM2-2027s deck", "Yes, fix the double counting", "Could we show the same window in both cases, removing the information that is shown when I click the status text" , "put a large version of the percentage-with-progress-circle that is shown in the SlideMage main window on the top right of the background previews window" and "The status message \"Previews paused\" is unintuitive, change it to \"Preview rendering paused\"", "Retry failed slides at least once after all other slides have been rendered" and "Add an app-wide setting that lets the user choose whether edited but unsaved slides [the ones whose version ends on \"+\"] should be rendered when rendering a deck, or whether the last saved version should be rendered instead [default]" and "Prevent such insertions of ending groups when each opening already has an ending"): A slide counts as up to date once per plan. The background renderer counted a slide each time a job found it current, so a view could show more renders than it has (268 / 252) and the number left ran behind. The background-trace.log showed how: a batch the plan still held was handed out again the moment the same batch, on its way already, had finished, and its 16 slides were counted a second time; a batch stopped part-way (SlideMage coming to the front) and run again, and a reveal render of a current slide, did the same. The plan now keeps every label it counts (`_counted`, which held only the slides right apart from their page number) and `_count_fresh` counts a label at most once, under the workers' lock. The status chip opens the status window, as the dial does, instead of its own menu, which said less: the window now also says the disk space the stored previews take, and a tick per deck says whether it is prepared in the background (the menu could do that for the open deck only; the tick follows the setting at once, not the next plan). A large dial, with a % sign, stands top right in the window; "Click for the decks." is left to the dial's tooltip. The chip says "Preview rendering paused (reason)" instead of "Previews paused (reason)". A failed slide that is not tried again by itself (a TeX error; a passing error after its last automatic try) is tried once more, on its own, when the plan has nothing else left: it counts as outstanding again, not failed, until that try ends. The try is noted in the store before it runs (a new table, last_tries, which older versions leave alone), so it is made once per failure; changing what the slide reads, or "Try failed slides again", gives it a new one. A render that succeeds now forgets the slide's failure, which stayed among "N slides cannot be rendered" before. A deck compile (PDF, snapshot, PowerPoint export) now typesets a slide whose version line carries a "+" from its last version's frozen file, not from its current file: the compile wrapper starts with a \declare@file@substitution line per such slide (LaTeX's file substitution, LaTeX 2020-10), which every \input{slides/<id>-current.tex} of \slide{} and the other calls follows, so neither the framework nor the decks change (slide_versioning.saved_version_lines, compiler.wrapper_text). A slide whose frozen file is missing keeps its current file. Settings → General, "Compile decks with the changes not yet made a version" (off by default, RENDER_CHANGES_SETTING_KEY), compiles them as they are now, as before; only then do a snapshot and an export still warn about slides changed since their last version. A slide's own Preview and the background previews always show the slide as it is now. Checked with lualatex that the substitution loads the frozen file. Enter at the end of a \begin{ENV} line in the Source view no longer adds an \end{ENV} when the file has one for every \begin{ENV} already (outside comments): it only opens the indented line inside (on "\item " in a list). Before, Enter after \begin{sectionframe}{...} with its \end{sectionframe} on the next line put a second one under it (latex_edit.smart_return, which now gets the whole text). Tests in test_background_renders.py, test_background_previews_gui.py, test_deck_versions.py and test_latex_edit.py.

NEW: The status text opens the Background previews window, which shows a large progress dial.
- Clicking the status text next to the progress dial now opens the same Background previews window as the dial.
- The window shows the disk space your stored previews take, and a tick per deck turns its background previews on or off.
- A deck's counts no longer show more rendered slides than it has.
- "Previews paused" now reads "Preview rendering paused".
- Slides that could not be rendered are tried once more after all other slides are done.
- A deck's PDF now shows the last version of a slide marked "+", not its unversioned changes. A new switch in Settings → General includes the changes instead.
- Pressing Enter after a \begin{...} line no longer adds a second \end{...} when the environment is already closed.

v8.67.0 (2026-10-27, direct requests: "How is it possible that SlideMage says all previews are rendered, yet that there is no preview for the selected slide", "Do 3 and 2" and "remove the green background from the status line - use only green font. The background signifies for me that there is something to do"): Slides that need their deck are rendered too, and "All previews are up to date." is green text without a background. A contents, agenda or section divider slide was left out of the background previews and of their counts, and the Preview did not render it when it was selected, so the slide showed "No preview" and a button under a status that said everything was up to date. Two changes: first, the Preview now renders such a slide by itself when it is shown and has no picture, once per file revision, view and language, as Render now does, except when its source has lint errors or an earlier render of it failed; second, once a whole-deck compile of the deck and view is on record and the deck file has not changed since, the background sweep counts these slides and typesets each one on its own in that compile, with deck_context.render_in_deck, all steps, never in a batch. render_key.Unit has a new context field, the deck's name, which is part of the store key only when it is set, so these renders never share a key with a slide rendered alone. BackgroundPreviews.stored_page now serves them, the Preview marks such a picture "In the deck's context", and a finished deck compile asks the sweep to plan again. Without a usable compile they are not counted, as before, and the Preview's own render on selection, with the skeleton and its warning chip, covers them. A picture follows the compile's auxiliary files, so a changed title in another slide shows in a contents slide after the next whole-deck compile, as with a render from the Preview. The status chip tone ok_text, green text on no background, replaces the green chip for "All previews are up to date.", because a background says there is something to do. Tests in test_background_renders.py, test_deck_context_gui.py and test_background_previews_gui.py.

NEW: Contents and section slides get a preview by themselves, and the status line is green text only.
- Selecting a contents, agenda or section slide now renders its preview at once instead of waiting for Render now.
- After a deck has been compiled, these slides are also rendered in the background and counted, so "All previews are up to date." includes them.
- "All previews are up to date." is now plain green text without a green background.

v8.67.1 (2026-10-28, direct requests: "Let's set up an organization. Would we then move the SlideMage repo there, was well as the as-yet-to-be-developed theme and plugin repos?" and "I have created the organization SlideMage and am logged in in chrome. Can you do the rest?"): The repository moved from stpalan/SlideMage to the SlideMage organization, SlideMage/SlideMage, together with slidemage-website, slidemage-plugin-template and slidemage-plugin-hello, and it is public now. updater.REPO names the new place, so the update check and the release notes' changelog link go there directly; GitHub forwards the old name, so copies before this one still find their updates. README, REUSE.toml, docs/PROJECT_OVERVIEW.md and docs/SlideMage.md (the token for the update check now has the organization as its resource owner, needed only while a repository is private) say the same. Tests in test_release_notes.py.

NEW: SlideMage now lives in the SlideMage organization on GitHub.
- Updates come from github.com/SlideMage/SlideMage; older copies are forwarded there automatically.

v8.68.0 (2026-10-28, direct request: "I want a \"Save\" button when I edit a deck's source."): The Source view's toolbar has a Save button for a deck's source and the other files that are no slide (Slidemaster.bib, test-slides.tex) while AutoSave is off, beside the "x". It does what Ctrl+S does (SourcePane.save: the file is written, a deck's source goes through after_deck_edit as before) and is enabled while the file has edits not written yet. With AutoSave on these files are saved as you type, and a slide keeps its own toolbar with "Not saved · Ctrl+S", so the button is not shown there. Tests in test_centre_gui.py.

NEW: A Save button for a deck's source.
- When AutoSave is off, editing a deck's source (or Slidemaster.bib) shows a Save button next to the "x"; it does the same as Ctrl+S.

v8.69.0 (2026-10-28, direct request: "Yes, fix it", the proposal: each preview depends only on the alt-text entries of its own slide's images, so a new alt text no longer invalidates every preview): A stored preview depends only on the alt texts of the pictures its render read. Every render reads media/alt-text.csv (Slidemaster_alt.lua) and records media/alt-text.json with it, and a render's manifest held each file's whole hash, so one new alt text, here a QR code's at 13:29, put every preview out of date: the background previews went from 215 left to 4040. The manifest now holds, for each of the two files, a KIND_ALT_TEXT entry: the hash of its rows for the files the render read, matched as Slidemaster_alt.lua matches a picture (the lower-case file name, or the name without its extension). render_key.Resolver.narrow_alt_text makes these entries for a render and for a deck compile's page (an alt-text file changed since the compile keeps its whole-file entry); manifest_current checks them; each file is parsed once per content (_alt_rows). Previews stored before this keep their whole-file entries until they are rendered again. Tests in test_render_key.py.

NEW: A new alt text no longer makes every preview out of date.
- Adding or editing the alt text of one picture now only re-renders the previews of the slides that show it.

v8.69.1 (2026-10-28, plugins plan, phase 4): The Anthropic API is reached without the anthropic SDK. AnthropicProvider moved to ai/anthropic_provider.py and talks to /v1/messages and /v1/models with http.client and server-sent events, as the Ollama provider already did with its own plumbing. It keeps what the SDK gave: streaming for chat() too, so that Stop always has a connection to end; two retries with backoff (or the server's retry-after) on 408/409/429/5xx and dropped connections, only before any answer has arrived, and a Stop that also ends the wait; the same error messages; unknown events and deltas ignored. The assistant's turn is kept as plain JSON blocks (thinking blocks with their signatures included) and replayed unchanged. Tests in test_agent_claude.py and test_ai_providers.py.

NEW: Nothing changes for you; the Claude API route works as before.
- The anthropic package is no longer used (its removal from the build is a separate step).

v8.70.0 (2026-10-28, plugins plan, phase 4): The anthropic package and what came only with it (pydantic, pydantic_core, httpx2, httpcore2, anyio, jiter and others) leave pyproject.toml, the build spec and THIRD_PARTY_NOTICES.md; tools/third_party_notices.py no longer lists it. The download gets smaller and the first request to the API no longer waits for the SDK to load.

AI HTTPS requests now follow system and environment proxy settings and bypass rules, using CONNECT through HTTP proxies with credentials sent only to the proxy; local Ollama stays direct. The shared transport makes TCP connection, proxy tunnelling and TLS handshake abortable by publishing the active socket during setup, with nonblocking TCP polling and synchronized socket ownership. Tests in test_ai_providers.py and test_agent_claude.py.

NEW: A smaller download and more reliable AI connections.
- SlideMage is a little smaller to download.
- AI requests can use the proxy settings often needed on university and company networks.
- Stop can end an AI connection stuck while connecting.

v8.71.0 (2026-10-28, plugins plan, phases 0 and 1; docs/PLUGIN_HOST_PLAN.md): The plugin host. A plugin is a Python package with a plugin.toml, installed unpacked in config_dir()/plugins/<id>/ (or a checkout named by SLIDEMAGE_PLUGIN_PATH), imported under its own name and activated with slidemage.plugin_api (API 1): commands and Deck menu entries, Deck settings tabs with a footer action, Settings tabs, compact side-panel boxes, a render priority, and host services for deck edits, slide insertion, cache folders, settings and background work. A plugin that fails to load is shown with its error and never stops the start. plugins/installer.py checks the SHA-256, refuses unsafe or compiled archive members and swaps the folder atomically; plugins/catalogue.py reads https://slidemage.org/plugins/index.json (never GitHub's latest release). New Settings tab Plugins and Help → Plugins…; a first-start sheet when the list has something to offer; plugin updates follow the app's update mode. Updates and removals are staged until startup, and host storage names are reserved. Plugin deck edits refresh the window and create an undo step; they are refused while the deck settings sheet has unsaved core changes, and slide insertion rolls back on failure. Core deck writes use atomic replacement with a stale-text check. Plugins can refresh their sidebar boxes, which are also rebuilt at midnight. Feature-to-plugin migrations can be announced once per feature (none are configured in this release). The README and manual document plugins. The frozen build bundles the standard library and PySide6's widget modules for plugins, checked by --self-test --plugins, including a plugin widget. Nothing that is built in moves out yet. Tests in tests/test_plugin_*.py; test_plugin_campusonline_e2e.py runs the real CampusOnline plugin when SLIDEMAGE_E2E_CAMPUSONLINE names its checkout.

NEW: SlideMage can install plugins.
- Settings → Plugins (also Help → Plugins…) lists installed plugins and the ones on the SlideMage website, and installs, updates, disables or removes them; a plugin file can be installed by hand too.
- Each plugin says what it needs and what it contacts on the network before you install it.
- Plugin updates and removals take effect on restart, keeping the running plugin's files available until then.
- Plugin edits refresh the deck and can be undone. Save or discard changes on the other Deck settings tabs before a plugin edits that deck.
- Slide insertion by a plugin is all-or-nothing, and deck writes are protected against interrupted writes.
- Plugin side-panel boxes can refresh when their data changes and at the start of a new day.
- The README and manual explain how to install, use, write and test plugins.

v8.71.1 (2026-10-28, merging the plugins PRs: the plugin self-test failed on Windows): The plugin self-test and the build's list of standard-library hidden imports leave out curses, pty and tty on Windows (plugins/selftest.py POSIX_ONLY): find_spec finds them there, but they import _curses or termios, which Windows lacks, so `slidemage --self-test --plugins` failed in every Windows build. Two tests check what only POSIX can show: a file's mode bits, and a backslash in a zip member's name, which Windows' zipfile turns into "/" when it writes and reads it.

NEW: The plugin self-test passes on Windows.
- Windows builds no longer fail their plugin self-test.

v8.72.0 (2026-10-28, plugins plan, phases 3 and 6 - core part; docs/PLUGINS_REMAINING_PLAN.md): The AI becomes routes in a registry, and the plugin host gets what AI plugins need. Ollama, Claude Code and the Anthropic API are AiRoute modules (ai/routes.py, ai/ollama_route.py, ai/claude_code_route.py, ai/anthropic_api_route.py), registered from core at start; ai_profile and resolver work over the route ids ollama, claude_code and anthropic_api, and a stored local or api is read as the new id and rewritten on the next change. There is still no silent fallback between routes. The switch, AI setup, header, pickers, task cards and bubbles are built from the routes; the assistant takes its surfaces from chat_surface; one empty side shows "Install a plugin…", and with no route at all the assistant, the AI menu and the AI commands hide. ai/claude_tasks.py is renamed ai/tasks.py, ui/workspace/terminal/tasks.py ui/workspace/task_bubbles.py. Settings' AI, Cloud, Ollama and Prompts tabs become one AI tab with a section per service: built-ins via settings_section, plugins via Host.add_settings_section; the old tab constants open the tab scrolled to their section. The host adds add_ai_route, where a duplicate id fails the plugin, add_entry_point with `--plugin <id>:<name>` while `--claude-hook` is unchanged, terminal as a service split from the Claude Code session, watch_external_edits, credentials, which finds the old Anthropic key, ai_tools, focus, and lazy re-exports of the neutral AI types; API_VERSION stays 1. Only the first local route is used for now, and the switch asks before leaving any chat surface. The modules plugin_api loads by name are hidden imports in the spec and are imported by `--self-test --plugins`; without them the frozen app's Claude Code hook failed with ModuleNotFoundError. Tab in AI setup now reaches the cloud connection before the project setting and the link, and the Settings project setting has an accessible name. The AI tab's scroll to a section no longer raises when the sheet closed before its deferred scroll ran.

NEW: One AI tab in Settings.
- Settings' AI, Cloud, Ollama and Prompts tabs are now one AI tab, with a section for each service.
- Plugins can add AI services of their own.

v9.0.0 (2026-10-28, plugins plan, phase 2; docs/PLUGINS_REMAINING_PLAN.md, 2a): CampusOnline is a plugin. Removed from core: course_schedule.py, admin_slides.py and ui/dialogs/admin_slides.py; the course-link parser of deck_scan (COURSE_URL_RE, parse_course_url, Deck.course_url), of deck_settings (DeckSettings.course_url) and of deck_editor (normalize_course_url, course_url_text, set_course_url); the "Course link" field, its Open button and the Admin slides tab (with its Insert footer) of the Deck settings sheet; the admin_slides command with its Deck menu entry and enabled rule; the core "course session soon" rule of the background renderer (BackgroundRenderer keeps plugin_soon, and loses its soon argument); docs/UGO_api.md, which lives with the plugin. A deck's "%% SlideMage course URL: ..." comment is never touched by the code that is left: Deck settings, Save writes only the settings it has, so the comment stays (tested), and the deck compiles the same. plugins/upgrade.py recognises the comment with a regex of its own (the host recognising a plugin's data), so used_features still finds CampusOnline projects. MIGRATIONS records CampusOnline for v9.0.0; the onboarding or migration sheet offers it once with its reason even if onboarding was dismissed, while Claude and Ollama stay off. Opening a project whose decks have a course link while the campusonline plugin is not loaded shows a toast with "Open Plugins" and "Don't show again" (the second stored per project, key campusonline_hint_dismissed). compat.py registers the change as "campusonline-plugin" (appearance, with a detector for decks with a course link, no migration, because the comment stays). Tests changed: test_course_schedule*, test_admin_slides* and test_course_url* are deleted; the course and admin cases left the shared test files; new tests in test_deck_settings.py, test_plugin_upgrade.py, test_plugin_offer.py and test_compat.py.

BREAKING: CampusOnline course links, admin slides and session-aware rendering are now the CampusOnline plugin. Decks keep their course link; install the plugin from Settings → Plugins or the first-start sheet to use them again.

NEW: CampusOnline features are now a plugin.
- The course link of a deck, the admin slides and rendering ahead of a course session moved into the CampusOnline plugin; install it from Settings → Plugins or the first-start sheet.
- Your decks keep their course link, and the first-start sheet ticks the plugin for you when your project uses it.
- A project with course links now tells you once, with a button to the plugin list, when the plugin is missing.

v9.1.0 (2026-10-29, AI-free core): AI routes are supplied by plugins through the public route, terminal, credentials, task and image APIs. Legacy settings are read without migration by plugin compatibility readers.

BREAKING: AI is now two plugins, Claude and Ollama; SlideMage offers them at the next start to everyone who used them; your keys, models and settings carry over

NEW: SlideMage works as a complete editor without an AI plugin.
- Manual image descriptions and translation remain available.
- Plugins provide AI routes and retain existing settings.


v9.1.1 (2026-10-29, the taskbar showed the simplified mark): icon.ico carries the full SlideMage mark (three layered slides, the yellow dot and the two text bars) at every size, 16 to 256 px, rendered from the mark per size. The 16 to 32 px sizes held the simplified small mark (a large yellow dot, no bars), which Windows shows in the taskbar, the title bar and Explorer.

NEW: The app icon is the full SlideMage logo at every size.
- The taskbar and the title bar show the same icon as the desktop shortcut.

v9.1.2 (2026-10-29, direct request: "Update the manual then."): The SlideMage manual and its documentation are brought up to date with every user-visible change from v8.62.0 to v9.1.1. New manual slide 1a4 QR codes, in the chapter Content and layout after 1c9, with its own code in media/qr-slidemage-org.pdf (qr-codes.json, alt-text.json and alt-text.csv, snippets/1a4-1.tex, slide_ids.csv and decks/slidemage-manual.tex list it). Plugins: 1vx says Claude, Ollama and CampusOnline are plugins, 1iz describes the first-start sheet (recommended Claude and Ollama, a plugin ticked for a feature used before, Install selected, See all plugins, Restart now) and Settings tabs and AI sections that plugins add. AI as plugins: 1wk, 1hi, 1v5, 1bb with its German bhx, 1f8 with its German tks, 1ub, 1b6, 1fg, 1ih, 1be and 1vn say where the assistant, Ollama and Claude Code come from and use the one AI tab of Settings; 1wk adds that This slide asks before touching other slides. CampusOnline as a plugin: 1kp, 1d7, 1y5 and 1vn. Background previews window, status text and dial: 1gu. Save button, QR button and corner figures in the Insert menu: 1b6. Find anything Show all: 1fg and 1r8. A deck PDF shows the last version of a slide marked +: 1an. 1r8 lists Plugins and the AI tab. 1nk with its German qft says the repository is public and offers plugins at the first start. README: the AI plugins in the introduction, the quick start, the workspace and Settings, the public repository and the update token, the Plugins section (the three plugins, the first-start sheet), the QR paragraph (On the slide, corner, no default caption, change a code), the Deck settings section (course link and Admin slides from the CampusOnline plugin), Save, Update version on closing and the + rule of deck PDFs, background previews, drafts and Prompts. docs/SlideMage.md: the intro, the Source view (QR, Save), Show all, Background previews, Plugins, the AI tab and its sections, the update token and the ai package note. Manual updated through v9.1.1: 1a4 is new, 1vx, 1iz, 1wk, 1hi, 1v5, 1bb, 1f8, 1nk, 1ub, 1b6, 1fg, 1ih, 1be, 1vn, 1kp, 1d7, 1y5, 1gu, 1an and 1r8 are changed, and so are the German bhx, tks and qft. The screenshots are not made again, because tools/manual/make_screenshots.py needs the AI routes, which are plugins now; the ones of the main window, the Source view, the chat, the palette and the preview show the state before v8.62.0.

NEW: The SlideMage manual (F1) is up to date.
- A new slide explains QR codes: the QR button, what a code can hold, the sizes for a seminar room and a lecture hall, captions and corners.
- The plugins chapter describes the first-start sheet, Install from file and slidemage.org/plugins.
- The manual says that the AI assistant, Ollama and Claude Code come from the Claude and Ollama plugins and that the course link and admin slides come from the CampusOnline plugin.
- The background previews window, the Save button for a deck source and Show all in Find anything are explained.
- Settings has one AI tab with a section per service, and updates come from the public repository on GitHub.

v9.1.3 (2026-10-29, direct request: "Fix screenshots first"): tools/manual/make_screenshots.py works with the AI in plugins. It loads the Claude and Ollama plugins as dev plugins from checkouts named by --plugins, SLIDEMAGE_PLUGIN_PATH or the folders next to the repository, with the plugins directory pointed at the throwaway folder so the computer's installed plugins stay out, and stubs the model lists in the plugins' own providers (ollama.provider.OllamaProvider, claude.api.provider.AnthropicProvider); without a plugin the chat shot is left out. The Settings shots follow the sheet's tabs as they are (General, AI, Presentation, Project, About, Plugins) instead of the old General, Models, Cloud, Ollama and Prompts. The focused slide is rendered for real when no stored preview of it exists, since a stored page is now looked up off the GUI thread and a throwaway copy has none: the copy keeps every PDF except the compiled decks (decks/pdf/), as the framework's slidemage-logo.pdf and the slides' PDF media are needed for a render, SLIDEMASTER_LATEX names the copy's framework, and example/.build/preview-cache comes along when it exists. The manual's 14 screenshots are made again with both plugins: the main window, slide editor, details, preview, list, side panel, deck switcher, Tags sheet, Images page and toolbar, save dialog, transcript, chat and palette show today's UI (the QR button, no Source button in the format row, the background previews status, the AI assistant from the plugin). The callouts of 1ub and 1ti still sit on their elements. Manual updated through v9.1.2: new screenshots. tools/manual/README.md describes --plugins and the render.

NEW: The manual's screenshots show SlideMage as it is now.
- The pictures of the workspace, the slide editor, the AI assistant and the Images page show the current version, with the AI from the Claude and Ollama plugins.
