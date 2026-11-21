kind: fixed
reason: direct request: the archive review listed one image twice, and archiving unused content did nothing for files that archive/ already held

1. alt_archive.unused_descriptions(ctx, moving) leaves out the images in `moving`: the media files the review offers to archive, whose description goes into the alt-text archive with the file anyway (unused_content.archive_files archives the entries of the files it moves). The Housekeeping scan passes the unused media files as `moving`, and alt_archive.described_images() tells which of them have a description: their row reads "media  name  (its description goes along)" and has no second row. File and description are one item, ticked or unticked together. A description whose file is not offered for archiving keeps its own row, ticked only when the file is gone.

2. unused_content._archive_files used to skip a file whose name was in archive/ already, log "Skipped", and leave it in its folder, so the review listed the same files again and again and archiving them did nothing. archive_copy_state() now compares the two: an identical copy (COPY_SAME) is removed from the folder, an archived .tex text that differs only in the SM names and in comments (COPY_OLDER: after sm_rename.rename_identifiers(rename_text(archived)), the lines without their comments and without blank lines equal the file's; the archived copy loses only comments, such as the generated "Included in decks" line) is replaced by the file, and any other difference (COPY_DIFFERS) is never overwritten: the file stays where it is and the log says so. The Housekeeping review lists such a file unticked with the note "a different file of this name is in media/archive/ (or slides/archive/): it would stay".

3. The intro of the review said "102 items would be moved" while the button, counting the ticked ones, said "Archive 82 items". It now says how many are listed and how many are ticked ("102 items listed, 82 ticked. The ticked ones would be moved ...") and follows the ticking.

4. alt_archive.unused_descriptions() no longer lists an entry with nothing written whose file is on disk: the Images scan makes such an empty row for every image file it finds (the theme logos in schemes/ among them, which no slide ever shows), archiving it saves nothing and the next scan makes it again. An entry with text, or whose file is gone, is still offered.

Tests: test_archive_existing_copies.py, test_housekeeping_descriptions_gui.py, test_alt_archive.py.

NEW: Archiving unused content now also removes the files that archive/ already holds an identical copy of, instead of listing them again every time.
- An archived slide that differs from the current file only in SM names and comments is replaced by the current file; a file whose archived namesake differs otherwise is left where it is, unticked and marked in the list.
- In the Housekeeping review of unused content, an image file and its description are one item: the description moves with the file, or both stay.
- The review no longer lists the empty description rows the Images scan makes for image files, and its intro says how many items are listed and how many are ticked.
