"""SDK call wrappers for LLM agent invocations.

Each wrapper configures model, max_turns, allowed_tools, and can_use_tool
appropriate to the task type.  Returns (messages, cost_usd) tuple.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .security import SecurityPolicy, default_policy, enforce_security

# ---------------------------------------------------------------------------
# Model / turn constants — single source of truth for the whole pipeline
# ---------------------------------------------------------------------------

MODEL_OPUS = "opus"
MODEL_SONNET = "sonnet"

MAX_TURNS_IMPLEMENT = 30
MAX_TURNS_FIX = 15
MAX_TURNS_REVIEW = 10
MAX_TURNS_PR_BODY = 3
MAX_TURNS_QUALITY_GATE = 3
MAX_TURNS_TEST_GEN = 10

# Tool sets by agent role
TOOLS_IMPLEMENT = ["Read", "Edit", "Write", "Bash", "Glob", "Grep"]
TOOLS_REVIEW = ["Read", "Glob", "Grep"]
TOOLS_NONE: list[str] = []


# ---------------------------------------------------------------------------
# can_use_tool callback factory
# ---------------------------------------------------------------------------

def _build_permission_callback(policy: SecurityPolicy):
    """Synchronously build the async callback (no await needed)."""
    try:
        from claude_code_sdk import PermissionResultAllow, PermissionResultDeny
    except ImportError:
        # SDK not available — return a simple allow/deny dict-based callback
        # that still enforces the policy (used in test environments)
        async def fallback_callback(
            tool_name: str,
            tool_input: dict[str, Any],
            context: Any,
        ):
            from dataclasses import dataclass

            @dataclass
            class _Allow:
                behavior: str = "allow"

            @dataclass
            class _Deny:
                behavior: str = "deny"
                message: str = ""

            if enforce_security(policy, tool_name, tool_input):
                return _Allow()
            return _Deny(message=f"Blocked by security policy: {tool_name}")

        return fallback_callback

    async def callback(
        tool_name: str,
        tool_input: dict[str, Any],
        context: Any,
    ) -> PermissionResultAllow | PermissionResultDeny:
        if enforce_security(policy, tool_name, tool_input):
            return PermissionResultAllow()
        return PermissionResultDeny(
            message=f"Blocked by security policy: {tool_name}"
        )

    return callback


# ---------------------------------------------------------------------------
# SDK query() wrapper — used for bounded tasks (review, PR body)
# ---------------------------------------------------------------------------

async def _sdk_query(
    prompt: str,
    *,
    model: str,
    max_turns: int,
    allowed_tools: list[str],
    cwd: str | None = None,
    system_prompt: str | None = None,
    policy: SecurityPolicy | None = None,
) -> tuple[list[str], float, int]:
    """Run a bounded SDK query() call and return (messages, cost_usd, num_turns)."""
    try:
        from claude_code_sdk import ClaudeCodeOptions, ResultMessage, query
    except ImportError:
        return [f"[sdk-unavailable] prompt: {prompt[:200]}"], 0.0, 0

    options = ClaudeCodeOptions(
        model=model,
        max_turns=max_turns,
        allowed_tools=allowed_tools,
        permission_mode="bypassPermissions",
    )
    if cwd:
        options.cwd = cwd
    if system_prompt:
        options.system_prompt = system_prompt
    if policy:
        options.can_use_tool = _build_permission_callback(policy)

    messages: list[str] = []
    cost = 0.0
    num_turns = 0

    async for msg in query(prompt=prompt, options=options):
        if isinstance(msg, ResultMessage):
            cost = msg.total_cost_usd or 0.0
            num_turns = getattr(msg, "num_turns", 0) or 0
        elif hasattr(msg, "content"):
            content = msg.content if isinstance(msg.content, str) else str(msg.content)
            messages.append(content)

    return messages, cost, num_turns


# ---------------------------------------------------------------------------
# SDK ClaudeSDKClient wrapper — used for implementation (supports interrupt)
# ---------------------------------------------------------------------------

async def _sdk_client_query(
    prompt: str,
    *,
    model: str,
    max_turns: int,
    allowed_tools: list[str],
    cwd: str | None = None,
    system_prompt: str | None = None,
    policy: SecurityPolicy | None = None,
    is_off_rails: Any | None = None,
) -> tuple[list[str], float, int]:
    """Run an SDK ClaudeSDKClient session with interrupt() guard.

    If is_off_rails(messages) returns True during streaming, the client
    calls interrupt() to abort the runaway agent.
    """
    try:
        from claude_code_sdk import (
            ClaudeCodeOptions,
            ClaudeSDKClient,
            ResultMessage,
        )
    except ImportError:
        return [f"[sdk-unavailable] prompt: {prompt[:200]}"], 0.0, 0

    options = ClaudeCodeOptions(
        model=model,
        max_turns=max_turns,
        allowed_tools=allowed_tools,
        permission_mode="bypassPermissions",
    )
    if cwd:
        options.cwd = cwd
    if system_prompt:
        options.system_prompt = system_prompt
    if policy:
        options.can_use_tool = _build_permission_callback(policy)

    client = ClaudeSDKClient(options)
    messages: list[str] = []
    cost = 0.0
    num_turns = 0

    try:
        await client.connect(prompt=prompt)
        async for msg in client.receive_response():
            if isinstance(msg, ResultMessage):
                cost = msg.total_cost_usd or 0.0
                num_turns = getattr(msg, "num_turns", 0) or 0
            elif hasattr(msg, "content"):
                content = (
                    msg.content if isinstance(msg.content, str) else str(msg.content)
                )
                messages.append(content)

                # Guard: interrupt if the agent goes off-rails
                if is_off_rails and is_off_rails(messages):
                    client.interrupt()
                    break
    finally:
        await client.disconnect()

    return messages, cost, num_turns


# ---------------------------------------------------------------------------
# Public wrappers — one per agent role
# ---------------------------------------------------------------------------

async def call_implement(
    prompt: str,
    *,
    worktree_path: str,
    system_prompt: str | None = None,
    is_off_rails: Any | None = None,
    dry_run: bool = False,
) -> tuple[str, float, int]:
    """Phase 7 implementation agent: opus, max_turns=30, edit tools, security.

    Uses ClaudeSDKClient for interrupt() support.
    Returns (combined_output, cost_usd, num_turns).
    """
    if dry_run:
        return "[dry-run] implementation skipped", 0.0, 0

    policy = default_policy(worktree=Path(worktree_path))
    messages, cost, num_turns = await _sdk_client_query(
        prompt,
        model=MODEL_OPUS,
        max_turns=MAX_TURNS_IMPLEMENT,
        allowed_tools=TOOLS_IMPLEMENT,
        cwd=worktree_path,
        system_prompt=system_prompt,
        policy=policy,
        is_off_rails=is_off_rails,
    )
    return "\n".join(messages), cost, num_turns


async def call_fix(
    prompt: str,
    *,
    worktree_path: str,
    system_prompt: str | None = None,
    dry_run: bool = False,
) -> tuple[str, float, int]:
    """Phase 8 test-fix agent: opus, max_turns=15, edit tools, security.

    Returns (combined_output, cost_usd, num_turns).
    """
    if dry_run:
        return "[dry-run] fix skipped", 0.0, 0

    policy = default_policy(worktree=Path(worktree_path))
    messages, cost, num_turns = await _sdk_query(
        prompt,
        model=MODEL_OPUS,
        max_turns=MAX_TURNS_FIX,
        allowed_tools=TOOLS_IMPLEMENT,
        cwd=worktree_path,
        system_prompt=system_prompt,
        policy=policy,
    )
    return "\n".join(messages), cost, num_turns


async def call_review(
    prompt: str,
    *,
    worktree_path: str,
    system_prompt: str | None = None,
    dry_run: bool = False,
) -> tuple[str, float, int]:
    """Phase 9 review agent: sonnet, max_turns=10, read-only tools.

    Review agents cannot Edit or Write files.
    Returns (combined_output, cost_usd, num_turns).
    """
    if dry_run:
        return "[dry-run] review skipped\nPASS", 0.0, 0

    # Review agents get no security policy since they have no write tools
    messages, cost, num_turns = await _sdk_query(
        prompt,
        model=MODEL_SONNET,
        max_turns=MAX_TURNS_REVIEW,
        allowed_tools=TOOLS_REVIEW,
        cwd=worktree_path,
        system_prompt=system_prompt,
    )
    return "\n".join(messages), cost, num_turns


async def call_pr_body(
    prompt: str,
    *,
    dry_run: bool = False,
) -> tuple[str, float, int]:
    """Phase 11 PR body agent: sonnet, max_turns=3, no tools.

    Returns (pr_body_text, cost_usd, num_turns).
    """
    if dry_run:
        return "[dry-run] PR body generation skipped", 0.0, 0

    messages, cost, num_turns = await _sdk_query(
        prompt,
        model=MODEL_SONNET,
        max_turns=MAX_TURNS_PR_BODY,
        allowed_tools=TOOLS_NONE,
    )
    return "\n".join(messages), cost, num_turns


async def call_quality_gate(
    prompt: str,
    *,
    dry_run: bool = False,
) -> tuple[str, float, int]:
    """Phase 1.5 quality gate agent: sonnet, max_turns=3, no tools."""
    if dry_run:
        return "[dry-run] quality gate skipped", 0.0, 0

    messages, cost, num_turns = await _sdk_query(
        prompt,
        model=MODEL_SONNET,
        max_turns=MAX_TURNS_QUALITY_GATE,
        allowed_tools=TOOLS_NONE,
    )
    return "\n".join(messages), cost, num_turns


async def call_test_gen(
    prompt: str,
    *,
    worktree_path: str,
    dry_run: bool = False,
) -> tuple[str, float, int]:
    """Phase 6.5 test generation agent: sonnet, max_turns=10, read-only tools.

    Reads specs and generates visible + hold-out test code.
    Returns (combined_output, cost_usd, num_turns).
    """
    if dry_run:
        return "[dry-run] test generation skipped", 0.0, 0

    messages, cost, num_turns = await _sdk_query(
        prompt,
        model=MODEL_SONNET,
        max_turns=MAX_TURNS_TEST_GEN,
        allowed_tools=TOOLS_REVIEW,
        cwd=worktree_path,
    )
    return "\n".join(messages), cost, num_turns
