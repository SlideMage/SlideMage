# Build a one-file SlideMage executable. From the repo root, with the build
# extra installed (pip install -e ".[build]"):
#     pyinstaller packaging/slidemage.spec
# The exe finds its project via --project, $SLIDEMASTER_PROJECT, the folder
# it sits in (searched upward), the last project opened, or a folder picker.
import sys
from pathlib import Path

ROOT = Path(SPECPATH).parent
ASSETS = ROOT / "src" / "slidemage" / "assets"

a = Analysis(
    [str(ROOT / "packaging" / "launch_slidemage.py")],
    pathex=[str(ROOT / "src")],
    datas=[(str(ASSETS), "slidemage/assets")],
)
pyz = PYZ(a.pure)

# PyInstaller's splash screen needs Tcl/Tk at build time and is unsupported
# on macOS; it only matters for the Windows one-file build's unpack delay.
splash_parts = []
if sys.platform == "win32":
    splash = Splash(str(ASSETS / "splash.png"), binaries=a.binaries, datas=a.datas)
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
    icon=str(ASSETS / "icon.ico"),
)
