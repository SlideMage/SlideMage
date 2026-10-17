"""What the assistant keeps of each route's conversation while another route is on (workspace v6 handoff,
section 2, "Commit"): the composer's draft, the attached files, the history the agent continues from, the
messages as they were shown and the model picked for that chat. Keyed by route (`ai_profile.LOCAL`, `CLAUDE_CODE`, `API`); nothing is copied or sent
from one route to another, and switching back finds everything as it was left. In memory only, for the session.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from PySide6.QtWidgets import QWidget

from ....ai.agent_types import AgentMessage


@dataclass
class RouteChat:
    draft: str = ""
    attached: list[str] = field(default_factory=list)          # project-relative paths of the next request
    history: list[AgentMessage] = field(default_factory=list)
    messages: list[QWidget] = field(default_factory=list)      # the conversation as shown, oldest first
    started: bool = False                                      # the first screen (the suggestions) is gone
    model: str = ""                                            # picked in the chat's model menu, for this chat only


def route_chats() -> defaultdict[str, RouteChat]:
    """A RouteChat per route key, made when first asked for."""
    return defaultdict(RouteChat)
