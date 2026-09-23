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
    datas=[(str(ASSETS), "slidemage/assets")],
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="SlideMage",
    console=False,
    icon=icon,
)
