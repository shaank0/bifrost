"""Classify an MCP tool by the action verb embedded in its name.

Role grants on the MCP gateway can serve whole categories ("read only")
instead of enumerating tools, and the rule keeps applying as vendors add
tools. Names are the ORIGINAL upstream names (``autotask_create_ticket``),
never the gateway-prefixed form.

Safety properties:

- Dangerous meta-tools (``raw_request`` etc.) are matched FIRST, so an escape
  hatch never classifies by its verb. They belong to no grantable category:
  only an explicit per-tool allow serves them (see ``access.is_tool_allowed``).
- Unknown verbs fall into ``modify`` — a new or unusual tool can never
  silently land in ``read``.
- Names are tokenized on camelCase/PascalCase boundaries as well as on
  ``-``/``_``, so a separator-free name (``ExecTool``) is matched exactly
  like ``exec_tool``.
"""

from __future__ import annotations

import re
from typing import Literal

ToolCategory = Literal["read", "create", "modify", "delete", "dangerous"]

GRANTABLE_CATEGORIES: tuple[ToolCategory, ...] = ("read", "create", "modify", "delete")

# Meta-tools that bypass verb semantics (raw API access, tool executors).
DANGEROUS_PATTERNS: tuple[str, ...] = (
    "raw_request",
    "execute_tool",
    "run_quickjob",
    "router",
    "graph-batch",
    "exec",
    "exec_tool",
    "graph_request",
    "raw",
)

# Every write verb maps to modify/create/delete — none may ever map to read.
# Listing write verbs explicitly makes a write verb that LEADS a name win over
# a read verb that appears later as a noun (update-sharepoint-list-item).
VERB_TO_CATEGORY: dict[str, ToolCategory] = {
    "get": "read",
    "list": "read",
    "search": "read",
    "test": "read",
    "create": "create",
    "delete": "delete",
    "archive": "delete",
    **{
        verb: "modify"
        for verb in (
            "update", "set", "unset", "send", "add", "remove", "move", "copy",
            "upload", "share", "forward", "reply", "clear", "merge", "unmerge",
            "format", "sort", "insert", "pin", "unpin", "accept", "decline",
            "tentatively", "cancel", "dismiss", "snooze", "reauthorize",
            "resolve", "convert", "rescan", "configure", "run", "unarchive",
        )
    },
}

_LOWER_UPPER = re.compile(r"([a-z0-9])([A-Z])")
_ACRONYM_WORD = re.compile(r"([A-Z]+)([A-Z][a-z])")
_SEPARATORS = re.compile(r"[-_]+")


def tokenize_tool_name(name: str) -> list[str]:
    """Split a tool name into lowercase tokens on ``-``/``_`` and case
    boundaries: ``ExecTool`` → ``[exec, tool]``, ``XMLParser`` → ``[xml, parser]``."""
    split = _ACRONYM_WORD.sub(r"\1_\2", _LOWER_UPPER.sub(r"\1_\2", name))
    return [token for token in _SEPARATORS.split(split.lower()) if token]


_DANGEROUS_TOKENS: tuple[tuple[str, ...], ...] = tuple(
    tuple(tokenize_tool_name(pattern)) for pattern in DANGEROUS_PATTERNS
)


def _contains_sequence(tokens: list[str], pattern: tuple[str, ...]) -> bool:
    width = len(pattern)
    return any(
        tuple(tokens[i : i + width]) == pattern for i in range(len(tokens) - width + 1)
    )


def classify_tool(name: str) -> ToolCategory:
    """Classify a tool name. Unknown verbs are ``modify``, never ``read``."""
    tokens = tokenize_tool_name(name)
    if any(_contains_sequence(tokens, pattern) for pattern in _DANGEROUS_TOKENS):
        return "dangerous"
    for token in tokens:
        category = VERB_TO_CATEGORY.get(token)
        if category is not None:
            return category
    return "modify"
