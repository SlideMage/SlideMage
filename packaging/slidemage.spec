# Build SlideMage as a one-file executable and as a folder, for whichever OS this actually
# runs on -- PyInstaller never cross-compiles. From the repo root, with
# pyinstaller installed (pip install -e ".[build]"):
#     pyinstaller packaging/slidemage.spec
# Output lands in dist/SlideMage(.exe) and dist/SlideMage-folder/. The exe finds its project via
# --project, $SLIDEMASTER_PROJECT, an upward search from the cwd, the
# last project opened, or a folder picker.
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).parent
ASSETS = ROOT / "src" / "slidemage" / "assets"

# The whole assets/ folder is data: the fonts (assets/fonts), the Claude Code terminal's page and scripts
# (assets/terminal, loaded by QtWebEngine from a file), the frame thumbnails (assets/frames) and the icons.
# The release history is also data, stored beside version.py.
# Everything else the app needs is code: PyInstaller follows the imports. Not the Anthropic SDK, which
# loads its resource modules lazily, and not QtWebEngine's helper process and resources, which the PySide6
# hooks of PyInstaller add as soon as QtWebEngineWidgets is imported (ui/workspace/terminal/web.py).
# ptyprocess (pywinpty on Windows) is imported inside a function and found that way.
HIDDEN_IMPORTS = collect_submodules("anthropic")

# Bundled so a project created via "Open Project..."'s "not a project
# yet -- create one?" offer (project.py's init_project()) can be seeded
# with real, working demo content even when SlideMage was only ever
# downloaded as this one exe, never cloned from the repo. Also the source of
# the manual updates (bundled_copies.py).
#
# The example project is filtered file by file (v5.20.1): bundling the whole
# folder also shipped a developer's slides/.backups (the slide editor's undo
# history), their .slidemage/app_settings.json and compile output -- and the
# backups reached users' projects through the manual's copy.
_EXAMPLE_SKIP_DIRS = {".build", ".previews", ".backups", "pdf", "__pycache__"}
_EXAMPLE_SKIP_FILES = {
    ".slidemage/app_settings.json", ".slidemage/project.json",
    ".slidemage/compile_passes.json", ".slidemage/bundled_copies.json",
}


def _example_datas():
    example = ROOT / "example"
    datas = []
    for path in sorted(example.rglob("*")):
        rel = path.relative_to(example)
        if (not path.is_file() or _EXAMPLE_SKIP_DIRS.intersection(rel.parts)
                or rel.as_posix() in _EXAMPLE_SKIP_FILES
                or (rel.parts[0] == "decks" and path.name.endswith((".pdf", ".synctex.gz")))):
            continue
        datas.append((str(path), str(Path("slidemage_template/example") / rel.parent)))
    return datas


TEMPLATE_DATAS = [
    *_example_datas(),
    (str(ROOT / "latex"), "slidemage_template/latex"),
]

# PyInstaller only actually embeds this on Windows (.ico) and macOS
# (.icns) -- ignored on Linux, where a windowmanager/taskbar icon instead
# comes from a .desktop file's own Icon= line, conventionally an SVG/PNG,
# not the Windows .ico this project ships for that platform's build.
if sys.platform == "win32":
    icon = str(ASSETS / "icon.ico")
elif sys.platform == "darwin":
    icon = None  # no .icns shipped
else:
    icon = str(ASSETS / "icon.svg")

a = Analysis(
    [str(ROOT / "packaging" / "launch_slidemage.py")],
    pathex=[str(ROOT / "src")],
    datas=[
        (str(ASSETS), "slidemage/assets"),
        (str(ROOT / "src" / "slidemage" / "CHANGELOG.md"), "slidemage"),
        # The licences, for the About sheet (app_info.license_text) and for everyone who gets the executable.
        (str(ROOT / "LICENSE"), "slidemage/legal"),
        (str(ROOT / "THIRD_PARTY_NOTICES.md"), "slidemage/legal"),
        (str(ROOT / "LICENSES"), "slidemage/legal/LICENSES"),
        *TEMPLATE_DATAS,
    ],
    hiddenimports=HIDDEN_IMPORTS,
)
pyz = PYZ(a.pure)

# Windows only: a splash screen (splash.png) shown by the bootloader while
# the one-file build unpacks itself, several seconds before any Python code
# runs -- without it, double-clicking the exe looks like nothing happened.
# slidemage/splash.py closes it. Not on macOS (unsupported by PyInstaller)
# or Linux (would need Tk on the build runner; untested).
splash_parts = []
if sys.platform == "win32":
    splash = Splash(
        str(ASSETS / "splash.png"),
        binaries=a.binaries,
        datas=a.datas,
        text_pos=None,
        always_on_top=True,
    )
    splash_parts = [splash, splash.binaries]

exe = EXE(
    pyz,
    a.scripts,
    *splash_parts,
    a.binaries,
    a.datas,
    [],
    name="SlideMage",
    console=False,
    icon=icon,
)

# The same program as a folder (dist/SlideMage-folder/: SlideMage[.exe] and _internal/). It does not unpack itself
# at every start, so it starts in about a quarter of the time (v8.33.0); the release publishes both and an
# installation updates itself with the build it is (updater.install_flavour()).
folder_exe = EXE(
    pyz,
    a.scripts,
    *([splash] if splash_parts else []),
    [],
    exclude_binaries=True,
    name="SlideMage",
    console=False,
    icon=icon,
)
folder = COLLECT(
    folder_exe,
    a.binaries,
    a.datas,
    *([splash.binaries] if splash_parts else []),
    name="SlideMage-folder",
)
