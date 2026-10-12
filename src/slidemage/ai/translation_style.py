"""The project's rules for translations by Claude Code (Claude Code tasks plan, step 2): how German addresses the
audience, `de_address` ("Sie" or "du") in .slidemage/project.json, and the optional .slidemage/glossary.md
("EN = DE" lines) that goes into every translation request as it is. No Qt."""
from __future__ import annotations

from .. import project
from ..deck_scan import PROJECT_ROOT

ADDRESSES = ("Sie", "du")
GLOSSARY_PATH = ".slidemage/glossary.md"
_KEY = "de_address"


def de_address() -> str:
    """The project's German form of address; "Sie" unless it says "du"."""
    value = project.read_project_json(PROJECT_ROOT).get(_KEY)
    return value if value in ADDRESSES else ADDRESSES[0]


def set_de_address(value: str) -> None:
    data = project.read_project_json(PROJECT_ROOT)
    data[_KEY] = value
    project.write_project_json(PROJECT_ROOT, data)


def glossary() -> str:
    """The text of the project's glossary file, "" without one."""
    try:
        return (PROJECT_ROOT / GLOSSARY_PATH).read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return ""
