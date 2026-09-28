# Build a one-file SlideMage executable, for whichever OS this actually
# runs on -- PyInstaller never cross-compiles. From the repo root, with
# pyinstaller installed (pip install pyinstaller):
#     pyinstaller packaging/slidemage.spec
# Output lands in dist/SlideMage(.exe). The exe finds its project via
# --project, $SLIDEMASTER_PROJECT, an upward search from the cwd, the
# last project opened, or a folder picker.
import sys
from pathlib import Path

ROOT = Path(SPECPATH).parent
ASSETS = ROOT / "src" / "slidemage" / "assets"

# Bundled so a project created via "Open Project..."'s "not a project
# yet -- create one?" offer (project.py's init_project()) can be seeded
# with real, working demo content even when SlideMage was only ever
# downloaded as this one exe, never cloned from the repo. Whole
# directories, .build/.previews/pdf build output included -- simpler
# than pre-filtering here, and project.py's own copytree(ignore=...)
# already strips that output back out at the point a new project is
# actually created from it, so nothing that matters ships in a new
# project either way; this only costs a few extra MB in the exe itself.
TEMPLATE_DATAS = [
    (str(ROOT / "example"), "slidemage_template/example"),
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
    datas=[(str(ASSETS), "slidemage/assets"), *TEMPLATE_DATAS],
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
