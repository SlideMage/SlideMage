# Build a one-file SlideMage executable. From the repo root, with the build
# extra installed (pip install pyinstaller):
#     pyinstaller packaging/slidemage.spec
# The exe finds its project via --project, $SLIDEMASTER_PROJECT, an upward
# search from the cwd, the last project opened, or a folder picker.
from pathlib import Path

ROOT = Path(SPECPATH).parent
ASSETS = ROOT / "src" / "slidemage" / "assets"

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
    icon=str(ASSETS / "icon.ico"),
)
