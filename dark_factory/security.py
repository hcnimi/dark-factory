"""Security policy enforcement for dark-factory v2.

Provides a can_use_tool callback that the SDK agent uses to gate
every tool invocation against a SecurityPolicy.
"""

from __future__ import annotations

import re
from pathlib import Path

from .types import SecurityPolicy


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_BLOCKED_PATTERNS: list[str] = [
    r"rm\s+-rf\s+/",
    r"git\s+push\s+.*--force",
    r"git\s+push\s+.*-f\b",
    r"DROP\s+TABLE",
    r"git\s+checkout\s+main\b",
    r"git\s+checkout\s+master\b",
    r"git\s+reset\s+--hard",
    r"git\s+branch\s+-D\s+main\b",
    r"git\s+branch\s+-D\s+master\b",
]

DEFAULT_BLOCKED_TOOLS: list[str] = ["mcp__"]


def default_policy(write_boundary: Path | None = None) -> SecurityPolicy:
    """Return a SecurityPolicy with safe defaults."""
    return SecurityPolicy(
        blocked_patterns=list(DEFAULT_BLOCKED_PATTERNS),
        write_boundary=write_boundary,
        blocked_tools=list(DEFAULT_BLOCKED_TOOLS),
    )


# ---------------------------------------------------------------------------
# Core check
# ---------------------------------------------------------------------------

def check_security(
    policy: SecurityPolicy,
    tool_name: str,
    tool_input: dict,
) -> tuple[bool, str]:
    """Evaluate a single tool call against the security policy.

    Returns (allowed, reason).
    """
    # 1. Blocked tool name substrings
    for substr in policy.blocked_tools:
        if substr in tool_name:
            return False, f"Tool blocked: name contains '{substr}'"

    # 2. Bash command pattern matching
    if tool_name == "Bash":
        command = tool_input.get("command", "")
        for pattern in policy.blocked_patterns:
            if re.search(pattern, command, re.IGNORECASE):
                return False, f"Bash command blocked: matches '{pattern}'"

    # 3. Write boundary enforcement for file-writing tools
    if tool_name in ("Edit", "Write") and policy.write_boundary is not None:
        file_path = tool_input.get("file_path", "")
        if file_path:
            resolved = Path(file_path).resolve()
            boundary = policy.write_boundary.resolve()
            # Path.is_relative_to handles the containment check
            if not resolved.is_relative_to(boundary):
                return False, (
                    f"Write blocked: {resolved} is outside boundary {boundary}"
                )

    return True, ""


# ---------------------------------------------------------------------------
# SDK callback builder
# ---------------------------------------------------------------------------

def build_permission_callback(
    policy: SecurityPolicy,
):
    """Build an async callback matching the SDK's CanUseTool signature.

    CanUseTool = Callable[
        [str, dict[str, Any], ToolPermissionContext],
        Awaitable[PermissionResultAllow | PermissionResultDeny]
    ]
    """
    from claude_code_sdk.types import (
        PermissionResultAllow,
        PermissionResultDeny,
    )

    async def callback(tool_name: str, tool_input: dict, context) -> PermissionResultAllow | PermissionResultDeny:
        allowed, reason = check_security(policy, tool_name, tool_input)
        if allowed:
            return PermissionResultAllow()
        return PermissionResultDeny(message=reason)

    return callback
