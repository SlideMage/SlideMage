kind: new
reason: direct request: an alt-text archive that keeps the descriptions of deleted and archived slides and images, phase 2 of docs/plans/alt-text-archive.md

alt_archive.unused_descriptions() lists the entries no slide in slides/ references (UnusedDescription: the image, whether its file is gone, whether it has text; suggested when the file is gone, since a description whose file exists may belong to a new image not yet placed on a slide). The archive page of the Housekeeping sheet lists them after the unused slides and media files, the suggested ones ticked and the others not; the worker that archives the ticked files then calls alt_archive.archive_images() for the ticked descriptions (reason "unused description"). The page's intro, the button ("Archive 3 items" when descriptions are listed, "files" otherwise), the row on the list page and the line after the move count them. The entries the archiving in hand orphans still move on their own (phase 1). Tests: test_housekeeping_descriptions_gui.py, test_alt_archive.py.

NEW: The Housekeeping review of unused content now also lists image descriptions no slide uses and can move them to the alt-text archive.
- Descriptions whose image file is gone are ticked; those whose file still exists are not, as the image may be new.
- What you archive stays retrievable in media/archive/alt-text-archive.json.
