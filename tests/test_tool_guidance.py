# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Tool names in each prompt must be available to that assistant."""
import re

import pytest

from slidemage.ai.agent_context import SYSTEM_PROMPT
from slidemage.ai.claude_launch import ORIENTATION
from slidemage.ai.tools import CLAUDE_CODE_TOOLS, TOOLS


# Guide topic and alt-text fields, not tools.
NON_TOOLS = {"images_and_text", "short_de", "long_de", "takeaway_de"}
SNAKE_CASE = re.compile(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b")


@pytest.mark.parametrize("prompt, available", [(SYSTEM_PROMPT, TOOLS), (ORIENTATION, CLAUDE_CODE_TOOLS)])
def test_prompt_tool_names_are_available(prompt, available):
    all_names = {tool.spec.name for tool in TOOLS + CLAUDE_CODE_TOOLS}
    mentioned = set(SNAKE_CASE.findall(prompt)) | {name for name in all_names if re.search(rf"\b{re.escape(name)}\b", prompt)}
    assert mentioned - NON_TOOLS <= {tool.spec.name for tool in available}
