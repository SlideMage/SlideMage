# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Screenshots of SlideMage's workspace window, made offscreen from the real widgets.

    python tools/manual/make_screenshots.py OUT_DIR [--plugins DIR ...] [--only NAME ...] [--scale N] [--list]

Writes OUT_DIR/screenshot-slidemage-<name>.png for the main views: the workspace in Preview, Source,
Split and Details, each side panel, the chat, the command palette, the deck and compile menus, the
compile job card, the Images page, the slide list with a selection, and the Settings, Deck settings,
Add slide, Tags, transcript preview and About sheets. Nothing is written into the repository: the run
works on a throwaway copy of `example/` (with the sibling `latex/` framework), in the light theme (--dark: the dark one),
with a fixed Ollama model list and no network.

The AI comes from plugins (v9.1.0): --plugins names checkouts of slidemage-plugin-claude and
slidemage-plugin-ollama (default: SLIDEMAGE_PLUGIN_PATH, else the sibling folders of this repository), loaded
as dev plugins; the plugins installed on this computer are not. Without them the shots show SlideMage with no
AI, and the chat shot is left out.

The manual's own images (MANUAL_IMAGES: crops of these shots, reduced to 256 colours) are written to
OUT_DIR/manual/ under the names the manual's slides use; copy them into example/media/.

Windows keep their logical size (WINDOW) but are rendered at --scale times the pixels (a device pixel
ratio of 2: crisp text instead of a stretched picture). Modal sheets are never exec()'d (that would
block forever offscreen): they are shown, grabbed and closed. Menus are painted onto the window
shot below the button they hang on.
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PREFIX = "screenshot-slidemage-"
MANUAL = "slidemage-manual"   # the deck every shot is taken in
WINDOW = (1700, 950)
SLIDE_LIST_WIDTH = 340   # wider than the default column: the bulk bar's "3 slides selected" and its button fit
# Slides of the example project the shots are taken on: a plain frame, one that cites, one with
# a picture (a chart that does not change with the UI), the slide whose transcript is shown.
SLIDE = "1y8"
CITING_SLIDE = "1nz"
PICTURE_SLIDE = "1rb"
TRANSCRIPT_FILE = "1ub-EN-Main-Window-current.tex"
# Placeholder decks, one per deck group, so the deck menu shows the grouping.
PLACEHOLDER_DECKS = {"#workdeck": "work", "course-example-2027s": "course", "talk-example-seminar": "research"}


# The manual's images (example/media/screenshot-slidemage-<name>.png): name -> (shot, crop). The crop
# is (left, top, right, bottom) as fractions of the shot, None for all of it.
MANUAL_IMAGES = {
    "main-window": ("workspace-preview", None),
    "slide-list": ("slide-list", (0.004, 0.163, 0.209, 1.0)),
    "slide-editor": ("workspace-source", None),
    "slide-details": ("workspace-details", (0.19, 0.14, 0.765, 0.535)),
    "slide-preview": ("workspace-preview", (0.176, 0.113, 0.778, 0.99)),
    "side-panel": ("panel-visibility", (0.785, 0.125, 0.9925, 0.25)),
    "deck-switcher": ("menu-deck", (0.0, 0.033, 0.245, 0.303)),
    "tags-dialog": ("deck-group", None),
    "images-page": ("images-page", None),
    "images-toolbar": ("images-page", (0.0, 0.745, 0.2, 0.985)),
    "save-dialog": ("save-prompt", None),
    "transcript": ("transcript", None),
    "chat": ("chat", (0.782, 0.462, 0.995, 0.99)),
    "palette": ("palette-search", (0.3175, 0.1145, 0.6825, 0.608)),
}


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("out_dir", type=Path, nargs="?", help="folder the PNG files go to (created)")
    parser.add_argument("--only", nargs="+", metavar="NAME", help="make only these shots (see --list)")
    parser.add_argument("--scale", type=int, default=2, help="device pixel ratio of the shots (default 2)")
    parser.add_argument("--dark", action="store_true", help="the dark theme instead of the light one")
    parser.add_argument("--list", action="store_true", help="print the names of the shots and exit")
    parser.add_argument("--plugins", nargs="+", type=Path, metavar="DIR",
                        help="plugin checkouts to load (default: SLIDEMAGE_PLUGIN_PATH, else ../slidemage-plugin-claude "
                             "and ../slidemage-plugin-ollama)")
    return parser.parse_args(argv)


def plugin_folders(args: argparse.Namespace) -> list[Path]:
    """The plugin checkouts the run loads: --plugins, else SLIDEMAGE_PLUGIN_PATH, else the sibling checkouts."""
    if args.plugins:
        return args.plugins
    if os.environ.get("SLIDEMAGE_PLUGIN_PATH"):
        return [Path(p) for p in os.environ["SLIDEMAGE_PLUGIN_PATH"].split(os.pathsep) if p]
    return [p for p in (REPO.parent / f"slidemage-plugin-{name}" for name in ("claude", "ollama")) if p.is_dir()]


def prepare_project(parent: Path) -> Path:
    """A copy of example/ and latex/ under `parent` with fresh settings and the placeholder decks."""
    # The compiled decks (decks/pdf/) stay behind, not every PDF: the framework's logo and the slides' PDF media
    # are needed for a render.
    ignore = shutil.ignore_patterns(".build", "pdf", "__pycache__", ".backups", "app_settings.json", "project.json")
    project = parent / "example"
    shutil.copytree(REPO / "example", project, ignore=ignore)
    shutil.copytree(REPO / "latex", parent / "latex", ignore=ignore)
    cache = REPO / "example" / ".build" / "preview-cache"
    if cache.is_dir():      # the stored previews, for the slide list's thumbnails (older ones say "preview old")
        shutil.copytree(cache, project / ".build" / "preview-cache", ignore=shutil.ignore_patterns("build.lock"))
    (project / "decks" / "slidemage-manual-copy.tex").unlink(missing_ok=True)   # the project's copy: not part of the picture
    manual = (project / "decks" / "slidemage-manual.tex").read_text(encoding="utf-8")
    preamble = manual.split("\\begin{document}")[0]
    for name, tag in PLACEHOLDER_DECKS.items():
        text = preamble.replace("\\decktags{manual}", f"\\decktags{{{tag}}}")
        (project / "decks" / f"{name}.tex").write_text(text + "\\begin{document}\n\\end{document}\n", encoding="utf-8")
    return project


# -- the grabbing helpers (Qt is imported in run(), after the environment is set) --------------------

class Shooter:
    def __init__(self, app, window, out_dir: Path) -> None:
        self.app, self.window, self.out_dir = app, window, out_dir

    def settle(self, rounds: int = 6, ms: int = 50) -> None:
        from PySide6.QtTest import QTest
        for _ in range(rounds):
            self.app.processEvents()
            QTest.qWait(ms)

    def save(self, image, name: str) -> None:
        path = self.out_dir / f"{PREFIX}{name}.png"
        image.save(str(path))
        print(f"{path.name}  {image.width()} x {image.height()}")

    def show_cached_preview(self) -> None:
        """Show the focused slide's cached snapshot as a finished render, without the "Cached preview" note
        (a real render needs a full LaTeX build, which a throwaway copy has not got). The Preview's own lookup
        answers with that page as current for this slide (since v8.54.0 a held page is checked first)."""
        preview = self.window.centre.preview
        target = preview._target
        found = preview._image(target)
        for _ in range(40):            # a stored page is looked up off the GUI thread: wait for it to arrive
            if found is not None:
                break
            self.settle(2, 50)
            found = preview._image(target)
        if found is None:              # the throwaway copy has no stored previews: render the slide once
            preview.render_now()
            for _ in range(1800):      # a cold LaTeX run takes up to a few minutes
                self.settle(1, 100)
                found = preview._image(target)
                if found is not None:
                    break
        if found is None:
            raise SystemExit(f"no preview of {target.key}: the render did not finish")
        pixmap = found[0]
        lookup = preview._image
        preview._image = lambda shown, **kw: (pixmap, True, '') if shown.key == target.key else lookup(shown, **kw)
        preview._refresh()
        self.settle(10)

    def window_shot(self, name: str) -> None:
        self.settle()
        self.save(self.window.grab(), name)

    def popup_shot(self, name: str, popup, anchor, *, align_right: bool = False) -> None:
        """The window with `popup` (a menu) painted below `anchor`. The offscreen screen is small and
        clamps real popups to it, so the place is worked out here instead of read from the popup."""
        from PySide6.QtCore import QPoint
        from PySide6.QtGui import QPainter
        self.settle()
        image = self.window.grab()
        picture = popup.grab()
        left = anchor.mapTo(self.window, QPoint(0, anchor.height() + 4))
        if align_right:
            left.setX(anchor.mapTo(self.window, QPoint(anchor.width(), 0)).x() - picture.width() // picture.devicePixelRatio())
        painter = QPainter(image)
        painter.drawPixmap(left, picture)
        painter.end()
        self.save(image, name)

    def sheet_shot(self, name: str, sheet, tab: int | None = None) -> None:
        if tab is not None:
            sheet.set_current_tab(tab)
        sheet.show()
        self.settle(10)
        self.save(sheet.grab(), name)

    def focus(self, slide_id: str, mode: str = "preview") -> None:
        self.window.stack.setCurrentWidget(self.window.centre)
        self.window.state.set_mode(mode)
        self.window.state.set_focused_slide(slide_id)
        self.settle(10)


# -- the shots --------------------------------------------------------------------------------------

def shot_workspace(shooter: Shooter) -> None:
    shooter.focus(SLIDE)
    shooter.show_cached_preview()
    for mode in ("preview", "source", "split", "details"):
        shooter.focus(SLIDE, mode)
        shooter.window_shot(f"workspace-{mode}")
    shooter.focus(SLIDE, "preview")


def shot_panels(shooter: Shooter) -> None:
    panels = shooter.window.side_panels
    on_slide = {"citations": CITING_SLIDE, "images": PICTURE_SLIDE, "transcript": PICTURE_SLIDE}
    for key in panels.panels:
        shooter.focus(on_slide.get(key, SLIDE))
        panels.set_panel(key)
        shooter.window_shot(f"panel-{key}")
    panels.set_panel("used")


def shot_chat(shooter: Shooter) -> None:
    """A conversation made of events, as the agent would report them (no model is asked)."""
    from slidemage.ai.agent_types import Done, TextDelta, ToolCall, ToolFinished, ToolResult, ToolStarted
    from slidemage.ui.workspace.chat.cards import UserBubble

    shooter.focus(SLIDE)
    chat = shooter.window.assistant.chat
    shooter.window_shot("chat-empty")
    chat.new_chat()
    chat._begin_conversation()
    chat._add(UserBubble("Make the second bullet shorter and say what the frame is for."))
    chat._start_turn("Claude Sonnet 5.5")
    call = ToolCall("t1", "read_file", {"path": "slides/1y8-EN-Standardframe-current.tex"})
    chat._on_event(TextDelta("I'll read the slide first."))
    chat._on_event(ToolStarted(call))
    chat._on_event(ToolFinished(call, ToolResult("t1", "\\begin{standardframe}{Standardframe} ... \\end{standardframe}")))
    chat._on_event(TextDelta("The second bullet runs over two lines. Shorter: **\"Text, lists and pictures\"**; "
                             "and a lead-in sentence says what the frame is for."))
    chat._on_event(Done("end_turn", turns=2))
    shooter.window_shot("chat")


def shot_slide_list(shooter: Shooter) -> None:
    """The slide list in a short window, with three slides selected (the bulk bar shows)."""
    from PySide6.QtWidgets import QAbstractItemView

    from slidemage.ui.workspace import slide_list

    window = shooter.window
    shooter.focus("1gu")
    window.resize(WINDOW[0], 530)
    window.set_column_widths(left=SLIDE_LIST_WIDTH)
    shooter.settle(10)
    tree = window.slide_list.tree
    wanted = [item for item in tree.slide_items() if tree.data_of(item).call.id in ("1gu", "1kg", "1tb")]
    for item in wanted:
        item.setSelected(True)
    tree.scrollToItem(wanted[0], QAbstractItemView.ScrollHint.PositionAtTop)
    shooter.window_shot("slide-list")
    tree.clearSelection()
    window.resize(*WINDOW)
    window.set_column_widths(left=slide_list.WIDTH)
    shooter.settle(10)


def shot_palette(shooter: Shooter) -> None:
    shooter.focus(SLIDE)
    palette = shooter.window.palette
    palette.open()
    shooter.window_shot("palette")
    palette.input.setText("source")
    shooter.window_shot("palette-search")
    palette.hide()


def shot_save_prompt(shooter: Shooter) -> None:
    """The Update Version prompt of a slide's source: a modal message box, grabbed by a timer while it is open."""
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    from slidemage.ui.workspace.source_file import prompt_version_level

    def grab() -> None:
        box = QApplication.activeModalWidget()
        box.setFixedWidth(700)            # offscreen the box is sized for the text, and clips its buttons
        shooter.settle()
        shooter.save(box.grab(), "save-prompt")
        box.reject()

    QTimer.singleShot(500, grab)
    prompt_version_level(shooter.window, (1, 2, 0))


def shot_menus(shooter: Shooter) -> None:
    from slidemage.ui.workspace.menus import build_deck_menu, build_compile_menu

    shooter.focus(SLIDE)
    window, topbar = shooter.window, shooter.window.topbar
    menu = build_deck_menu(topbar, window.decks, window.state.deck)
    menu.popup_below(topbar._deck_button)
    shooter.popup_shot("menu-deck", menu, topbar._deck_button)
    menu.hide()
    menu.deleteLater()
    menu = build_compile_menu(topbar, window)
    menu.popup_below(topbar._compile, align_right=True)
    shooter.popup_shot("menu-compile", menu, topbar._compile, align_right=True)
    menu.hide()
    menu.deleteLater()


def shot_compile_job(shooter: Shooter) -> None:
    """The job card in the middle of a run of three jobs, and at the end of it with one failure."""
    from slidemage.compile_status import RunStatus

    window = shooter.window
    shooter.focus(SLIDE)
    root = Path(os.environ["SLIDEMAGE_PROJECT"])
    names = {"manual-instructor": "manual · Instructor", "manual-during-course": "manual · During course",
             "manual-after-course": "manual · After course"}
    run = RunStatus(names, root=root, verb="Compiling", pdfs={n: root / "decks" / "pdf" / f"{n}.pdf" for n in names})
    panel = window.compile_display.panel
    panel.start(run, per_job_stop=True, can_retry=True)
    for line in ("==== Compiling manual -> manual-instructor ====", "==== PASS: manual-instructor -> x ====",
                 "==== Compiling manual -> manual-during-course ===="):
        run.feed(line)
    panel.refresh(0.46, "pass 2/3, slide 31/75", over=False)
    shooter.window_shot("compile-job")
    run.feed("slides/1y8-EN-Standardframe-current.tex:7: Undefined control sequence.")
    run.feed("*** FAIL: manual-during-course -- exit 12 ***")
    run.feed("==== Compiling manual -> manual-after-course ====")
    run.feed("==== PASS: manual-after-course -> x ====")
    run.finish(stopped=False)
    panel.refresh(1.0, "", over=True)
    shooter.window_shot("compile-job-done")
    panel.hide()


def shot_images_page(shooter: Shooter) -> None:
    window = shooter.window
    window.stack.setCurrentWidget(window.images_page)
    shooter.settle(20, 100)
    window.images_page.show_slide(PICTURE_SLIDE)
    shooter.window_shot("images-page")
    window.stack.setCurrentWidget(window.centre)


def shot_sheets(shooter: Shooter) -> None:
    from slidemage import transcript
    from slidemage.ui.dialogs.about import AboutSheet
    from slidemage.ui.dialogs.add_slide import AddSlideSheet
    from slidemage.ui.dialogs.deck_group import DeckGroupSheet
    from slidemage.ui.dialogs.deck_settings import DeckSettingsSheet
    from slidemage.ui.dialogs.settings import SettingsSheet
    from slidemage.ui.dialogs.transcript_preview import TranscriptPreviewSheet

    window = shooter.window
    shooter.focus(SLIDE)
    deck = window.state.deck
    sheet = SettingsSheet(window)
    for index in range(sheet._tabs.count()):      # General, AI (with an AI plugin), ..., Plugins, plugins' own tabs
        shooter.sheet_shot(f"settings-{sheet._tabs.tabText(index).lower()}", sheet, index)
    sheet.close()
    sheet = AddSlideSheet(window, deck, 0, "\t", where="after 1y8", is_dirty=window.centre.is_dirty)
    shooter.sheet_shot("add-slide", sheet)
    sheet.close()
    sheet = AddSlideSheet(window, deck, 0, "\t", where="after 1y8", source="existing",
                         is_dirty=window.centre.is_dirty)
    shooter.sheet_shot("add-slide-existing", sheet)
    sheet.close()
    templates = [(key, key) for key in ("slidemage", "uni-graz")]
    sheet = DeckSettingsSheet(window, deck, templates)
    for index, name in enumerate(("general", "output")):
        shooter.sheet_shot(f"deck-settings-{name}", sheet, index)
    sheet.close()
    sheet = AboutSheet(window)
    shooter.sheet_shot("about", sheet)
    sheet.close()
    sheet = DeckGroupSheet(window, "Tags", ("course",), groups=window.deck_groups, edit_groups=True)
    shooter.sheet_shot("deck-group", sheet)
    sheet.close()
    path = Path(os.environ["SLIDEMAGE_PROJECT"]) / "slides" / TRANSCRIPT_FILE
    entry = transcript.generate_single_slide(window.project, path.read_text(encoding="utf-8"), TRANSCRIPT_FILE[:3], "during-course", "en")
    sheet = TranscriptPreviewSheet(window, f"Transcript: {TRANSCRIPT_FILE[:3]}", transcript.to_html(entry, "Transcript preview"))
    shooter.sheet_shot("transcript", sheet)
    sheet.close()


SHOTS = {
    "workspace": shot_workspace,       # workspace-preview / -source / -split / -details
    "panels": shot_panels,             # panel-<key> for each of the 8 side panels
    "chat": shot_chat,                 # chat-empty, chat
    "slide-list": shot_slide_list,     # slide-list
    "palette": shot_palette,           # palette, palette-search
    "save-prompt": shot_save_prompt,   # save-prompt
    "menus": shot_menus,               # menu-deck, menu-compile
    "compile-job": shot_compile_job,   # compile-job, compile-job-done
    "images-page": shot_images_page,   # images-page
    "sheets": shot_sheets,             # settings-*, add-slide, deck-settings-*, about, deck-group, transcript
}


def make_manual_images(out_dir: Path) -> None:
    """The manual's images, cut from the shots that exist in `out_dir`, into out_dir/manual/."""
    from PIL import Image

    target = out_dir / "manual"
    target.mkdir(exist_ok=True)
    for name, (shot, crop) in MANUAL_IMAGES.items():
        source = out_dir / f"{PREFIX}{shot}.png"
        if not source.exists():
            continue
        image = Image.open(source).convert("RGB")
        if crop:
            width, height = image.size
            image = image.crop((round(crop[0] * width), round(crop[1] * height),
                                round(crop[2] * width), round(crop[3] * height)))
        path = target / f"{PREFIX}{name}.png"
        image.quantize(256, method=Image.Quantize.FASTOCTREE, dither=Image.Dither.NONE).save(path, optimize=True)
        print(f"manual/{path.name}  {image.width} x {image.height}")


# -- the run ------------------------------------------------------------------------------------

def run(args: argparse.Namespace, work: Path) -> None:
    project = prepare_project(work)
    os.environ["SLIDEMAGE_PROJECT"] = str(project)
    os.environ["SLIDEMAGE_LATEX"] = str(work / "latex")     # the copy's framework, also when the repo is on another drive
    os.environ["QT_SCALE_FACTOR"] = str(args.scale)
    # On Windows the offscreen platform no longer matches the bundled Roboto weights (v8.27.3: every weight is its own
    # file), and labels fall back to the icon font; the native platform draws them, the window is never on screen.
    os.environ.setdefault("QT_QPA_PLATFORM", "windows" if sys.platform == "win32" else "offscreen")
    sys.path.insert(0, str(REPO / "src"))

    from PySide6.QtCore import QCoreApplication, Qt
    from PySide6.QtWidgets import QApplication

    QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    app = QApplication([sys.argv[0]])

    from slidemage import app_settings
    from slidemage.project import ProjectContext
    from slidemage.ui import layout_settings

    # This computer's own settings and plugins are neither read nor written: the shots look the same on every machine.
    layout_settings.STORE_PATH = work / "layout.json"
    app_settings.MACHINE_STORE_PATH = work / "ai_settings.json"
    from slidemage.plugins import credentials, loader
    from slidemage.ui.app import load_plugins
    from slidemage.ui.kit.fonts import load_fonts
    from slidemage.ui.kit.theme import ThemeManager
    from slidemage.ui.workspace.window import WorkspaceWindow

    loader.plugins_dir = lambda: work / "plugins"
    os.environ[loader.PATH_ENV] = os.pathsep.join(str(p) for p in plugin_folders(args))
    credentials._keyring = lambda: None
    os.environ.pop("ANTHROPIC_API_KEY", None)
    load_plugins(ProjectContext.at(project))

    # No network and no keys, so the same model lists come out on every machine.
    if "ollama" in sys.modules:
        from ollama.provider import InstalledModel, OllamaProvider
        models = [InstalledModel("qwen3:8b", 5_200_000_000, "2026-09-30T10:00:00Z", ("completion", "tools")),
                  InstalledModel("llama3.2-vision:11b", 7_900_000_000, "2026-09-12T10:00:00Z", ("completion", "vision")),
                  InstalledModel("gemma3:12b", 8_100_000_000, "2026-08-21T10:00:00Z", ("completion", "vision"))]
        OllamaProvider.installed = lambda self, detailed=False: models if detailed else [m.name for m in models]
        OllamaProvider.list_models = lambda self, vision_only=False: [m.name for m in models]
        app_settings.set(ProjectContext.at(project), "chat_model", "ollama:qwen3:8b")
    if "claude" in sys.modules:
        from claude.api.provider import AnthropicProvider
        AnthropicProvider.list_models = lambda self: []

    load_fonts()
    theme = ThemeManager(dark=args.dark)
    theme.apply()
    window = WorkspaceWindow(theme, ProjectContext.at(project))
    window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)     # not on screen, so not cut to the screen's size
    window.resize(*WINDOW)
    window.show()
    window.state.set_deck(next(deck for deck in window.decks if deck.name == MANUAL))
    shooter = Shooter(app, window, args.out_dir)
    shooter.settle(20, 50)
    try:
        for name, shot in SHOTS.items():
            if name == "chat" and not window.assistant.available:
                print("chat: left out, no AI plugin loaded (see --plugins)")
                continue
            if args.only is None or name in args.only:
                shot(shooter)
    finally:
        window.hide()
        window.deleteLater()
        app.processEvents()


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    if args.list:
        print("\n".join(f"{name}: {shot.__doc__ or SHOTS[name].__name__}".split("\n")[0] for name, shot in SHOTS.items()))
        return 0
    if args.out_dir is None:
        raise SystemExit("give the folder for the PNG files")
    unknown = set(args.only or ()) - set(SHOTS)
    if unknown:
        raise SystemExit(f"unknown shot(s): {', '.join(sorted(unknown))}; --list names them")
    args.out_dir.mkdir(parents=True, exist_ok=True)
    # A background render may still hold a lock in the throwaway copy when it is removed; that is no failure.
    with tempfile.TemporaryDirectory(prefix="slidemage-shots-", ignore_cleanup_errors=True) as work:
        run(args, Path(work))
    make_manual_images(args.out_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
