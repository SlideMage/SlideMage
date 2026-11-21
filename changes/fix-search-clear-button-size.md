kind: fixed
reason: direct request: make the "x" that deletes the search term a bit bigger

kit/widgets.enable_clear_button(edit) turns on the clear button of a QLineEdit and gives the box a small QProxyStyle (_LargeClearIcon, owned by the box) that answers PM_LineEditIconSize with CLEAR_ICON_PX (22 px instead of 16). Qt sizes, places and paints the "x" from that metric, so the button grows and stays at the right end; setting the button's own size instead left it hanging over the edge. The two search boxes that used setClearButtonEnabled(True), the slide list's "Find slide by id or title" and the library's "Find by title, ID or text", call it. Checked on the Windows platform against a plain box. Test: test_clear_button_gui.py.

NEW: The "x" in the slide search boxes that empties them is bigger and easier to hit.
- The slide list's find box and the library's search box both have it.
