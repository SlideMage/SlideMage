"""The project's rules for translations by Claude Code (Claude Code tasks plan, step 2): how German addresses the
audience, `de_address` ("Sie" or "du") in .slidemage/project.json, and the optional .slidemage/glossary.md
("EN = DE" lines) that goes into every translation request as it is. No Qt."""
from __future__ import annotations

from .. import project
from ..project import ProjectContext

ADDRESSES = ("Sie", "du")
GLOSSARY_PATH = ".slidemage/glossary.md"
_KEY = "de_address"


def de_address(ctx: ProjectContext) -> str:
    """The project's German form of address; "Sie" unless it says "du"."""
    value = project.read_project_json(ctx.root).get(_KEY)
    return value if value in ADDRESSES else ADDRESSES[0]


def set_de_address(ctx: ProjectContext, value: str) -> None:
    data = project.read_project_json(ctx.root)
    data[_KEY] = value
    project.write_project_json(ctx.root, data)


def glossary(ctx: ProjectContext) -> str:
    """The text of the project's glossary file, "" without one."""
    try:
        return (ctx.root / GLOSSARY_PATH).read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return ""
