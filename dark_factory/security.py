"""Security policy enforcement for SDK agent tool calls.

Replaces prompt-based "do NOT" instructions with deterministic code-level
guards evaluated on every tool invocation via the can_use_tool callback.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class SecurityPolicy:
    """Defines what an agent is and isn't allowed to do."""

    blocked_patterns: list[str] = field(default_factory=list)
    """Regex patterns matched against Bash command strings."""

    write_boundary: Path | None = None
    """If set, file writes (Edit/Write) outside this directory are denied."""

    blocked_tools: list[str] = field(default_factory=list)
    """Tool name patterns to deny outright (matched as substrings)."""


# Sensible defaults -- agents should never do these regardless of context
DEFAULT_BLOCKED_PATTERNS: list[str] = [
    r"rm\s+-rf\s+/",
    r"git\s+push\s+.*--force",
    r"DROP\s+TABLE",
    r"git\s+checkout\s+main\b",
    r"git\s+checkout\s+master\b",
    r"git\s+reset\s+--hard",
]

DEFAULT_BLOCKED_TOOLS: list[str] = [
    "mcp__excalidraw__",
]


def default_policy(worktree: Path | None = None) -> SecurityPolicy:
    """Create a SecurityPolicy with sensible defaults."""
    return SecurityPolicy(
        blocked_patterns=list(DEFAULT_BLOCKED_PATTERNS),
        write_boundary=worktree,
        blocked_tools=list(DEFAULT_BLOCKED_TOOLS),
    )


def enforce_security(
    policy: SecurityPolicy,
    tool_name: str,
    tool_input: dict,
) -> bool:
    """Evaluate whether a tool invocation is allowed.

    Returns True if allowed, False if blocked.  Designed to be used as
    the can_use_tool callback in ClaudeCodeOptions.
    """
    # Check blocked tools (substring match)
    for pattern in policy.blocked_tools:
        if pattern in tool_name:
            return False

    # Check Bash commands against blocked patterns
    if tool_name == "Bash":
        command = tool_input.get("command", "")
        for pattern in policy.blocked_patterns:
            if re.search(pattern, command, re.IGNORECASE):
                return False

    # Check write boundary for file-modifying tools
    if policy.write_boundary and tool_name in ("Edit", "Write"):
        file_path = tool_input.get("file_path", "")
        if file_path:
            try:
                target = Path(file_path).resolve()
                boundary = policy.write_boundary.resolve()
                if not str(target).startswith(str(boundary)):
                    return False
            except (ValueError, OSError):
                return False

    return True
