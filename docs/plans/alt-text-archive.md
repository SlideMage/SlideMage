# Alt-text archive

Keep the live store (`media/alt-text.json`) lean while retaining every description of slides and images that are no
longer needed. Agreed with the user, 2026-11-21.

## Why

- Deleting a slide (`slide_rename.delete_slide_id`) dropped its takeaway overrides, reviewed stamps and summary and left
  its image entries behind.
- Archiving a slide (`unused_content.archive_files`) left the store untouched: the `used_on` keys went stale and sync
  only reported them. Archiving a media file left its entry (`SyncReport.missing`).
- The only removal was "Replace image" (`alt_images.delete_entry`): the text was gone for good.
- Redrafts overwrite in place; git history was the only record.

In Slidemaster on 2026-11-21: 63 of 504 entries had no live slide (12 with text, 1 reviewed), 43 had a missing file.

## Design

- File `media/archive/alt-text-archive.json`: out of every scan already, travels with the archived images, in git.
  Own format version 1; `alt-text.json` stays at version 3.
- Per key a list of snapshots, newest last. `images`: the whole entry (all languages, role, source, drafted_by, hint)
  and the slides it was used on. `slides`: what belongs to one slide alone (takeaway overrides, reviewed stamps and
  hashes per image, the summary), with the slide's name for a reader.
- A snapshot is added only if its content differs from the newest one (archive, restore, edit, archive again keeps
  both versions; repeating changes nothing).
- The archive is written before the store changes: an interruption leaves a duplicate, never a loss. A newer archive is
  never written. Nothing deletes a snapshot except `purge_*()`, called by a person.

## Rules for what moves

1. **A slide's own data** always moves when the slide is deleted or archived (no current file left; a frozen version of
   a live slide changes nothing).
2. **A whole image entry** moves with it only if the event orphaned it: every use of it was by the archived slides and
   no slide in `slides/` references it. An entry another slide still uses stays.
3. **Entries nobody uses that the event did not orphan** are never moved on their own: a new image not yet placed on a
   slide looks the same. Auto-archiving asks the user (phase 2): list with checkboxes, entries with a missing file
   ticked, the others not; what is not ticked is offered again next time.
4. An entry with no text goes without a snapshot.
5. Restoring never overwrites text that is there; the user chooses "keep current" or "take archived".
6. Purge is manual only; the archive only grows. Snapshot list, not latest only.

## Phases

1. **Done in the first PR:** `alt_archive.py` (archive, restore, purge, `unreferenced_entries`), hooks in
   `delete_slide_id`, `archive_files` (slides and media) and "Replace image", dialog wording, tests.
2. Housekeeping page "Archive unused descriptions" (rule 3, also the one-time cleanup of existing projects), and the
   question in the auto-archiving dialog.
3. `sync_store` reports `restorable` (a slide id or image path live again with an archived snapshot), the Images tab
   banner, a list with search by slide name and text, restore, copy onto another image, purge; the manual's Images
   slides.
