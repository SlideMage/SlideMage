# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""packaging/tex-requirements.toml and the installers made from it (packaging/tex_requirements.py)."""
import importlib.util
import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PACKAGING = REPO / "packaging"


def _generator():
    spec = importlib.util.spec_from_file_location("tex_requirements", PACKAGING / "tex_requirements.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_installers_carry_the_current_lists_and_keys():
    generator = _generator()
    for path, text in generator.generated().items():
        assert path.read_text(encoding="utf-8") == text, f"run python packaging/tex_requirements.py ({path.name})"


def test_every_requirement_names_its_packages():
    data = _generator().load()
    for entry in data["tex"]:
        assert re.fullmatch(r"[A-Za-z0-9-]+\.(sty|cls|lua|otf|tex|tfm)", entry["file"]), entry
        assert entry.get("fedora"), entry
        assert entry.get("debian") or entry.get("optional"), entry
        for key in ("ctan", "debian", "fedora", "miktex"):
            assert re.fullmatch(r"[a-z0-9][a-z0-9.+-]*", entry.get(key, "x")), entry   # safe as shell words
    assert {p["name"] for p in data["programs"]} == {"lualatex", "latexmk", "biber", "kpsewhich"}


def test_the_framework_packages_are_all_required():
    """Each package the framework loads itself is in the list (or part of every LaTeX installation)."""
    in_every_latex = {"calc", "ifluatex", "ifxetex", "iftex", "pgfpages", "graphicx", "keyval", "amsmath", "amssymb",
                      "fontawesome5", "xparse", "tikz"}
    files = {e["file"].rsplit(".", 1)[0] for e in _generator().load()["tex"]}
    used = set()
    for path in (REPO / "latex").glob("*.*"):
        if path.suffix in (".tex", ".sty"):
            text = path.read_text(encoding="utf-8")
            for match in re.finditer(r"\\(?:usepackage|RequirePackage)\s*(?:\[[^\]]*\])?\s*\{([^}]*)\}", text):
                used.update(name.strip() for name in match.group(1).split(","))
    # tikz is required through its file tikz.sty; pgfplots, xcolor, ... by their own names.
    assert used - in_every_latex - files == set()


def test_the_shell_installer_is_executable_in_git():
    mode = subprocess.run(["git", "ls-files", "-s", "packaging/install-slidemage.sh"], cwd=REPO,
                          capture_output=True, text=True).stdout.split(" ")[0]
    assert mode in ("100755", ""), "git update-index --chmod=+x packaging/install-slidemage.sh"
