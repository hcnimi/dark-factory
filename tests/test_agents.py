"""Tests for dark_factory.agents: SDK call wrappers."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from dark_factory.agents import (
    MAX_TURNS_FIX,
    MAX_TURNS_IMPLEMENT,
    MAX_TURNS_PR_BODY,
    MAX_TURNS_REVIEW,
    MODEL_OPUS,
    MODEL_SONNET,
    TIMEOUT_FIX,
    TIMEOUT_IMPLEMENT,
    TIMEOUT_PR_BODY,
    TIMEOUT_QUALITY_GATE,
    TIMEOUT_REVIEW,
    TIMEOUT_TEST_GEN,
    TOOLS_IMPLEMENT,
    TOOLS_NONE,
    TOOLS_REVIEW,
    _build_permission_callback,
    _sdk_query,
    call_fix,
    call_implement,
    call_pr_body,
    call_review,
)
from dark_factory.security import SecurityPolicy, default_policy, enforce_security


class TestConstants:
    """Verify model/turn/tool constants match spec requirements."""

    def test_implementation_uses_opus(self):
        assert MODEL_OPUS == "opus"

    def test_review_uses_sonnet(self):
        assert MODEL_SONNET == "sonnet"

    def test_implement_max_turns(self):
        assert MAX_TURNS_IMPLEMENT == 30

    def test_fix_max_turns(self):
        assert MAX_TURNS_FIX == 15

    def test_review_max_turns(self):
        assert MAX_TURNS_REVIEW == 10

    def test_pr_body_max_turns(self):
        assert MAX_TURNS_PR_BODY == 3

    def test_implement_tools_include_edit(self):
        assert "Edit" in TOOLS_IMPLEMENT
        assert "Write" in TOOLS_IMPLEMENT
        assert "Bash" in TOOLS_IMPLEMENT

    def test_review_tools_are_read_only(self):
        assert "Read" in TOOLS_REVIEW
        assert "Glob" in TOOLS_REVIEW
        assert "Grep" in TOOLS_REVIEW
        assert "Edit" not in TOOLS_REVIEW
        assert "Write" not in TOOLS_REVIEW
        assert "Bash" not in TOOLS_REVIEW

    def test_no_tools_is_empty(self):
        assert TOOLS_NONE == []

    def test_timeout_implement(self):
        assert TIMEOUT_IMPLEMENT == 600

    def test_timeout_fix(self):
        assert TIMEOUT_FIX == 600

    def test_timeout_review(self):
        assert TIMEOUT_REVIEW == 300

    def test_timeout_test_gen(self):
        assert TIMEOUT_TEST_GEN == 600

    def test_timeout_pr_body(self):
        assert TIMEOUT_PR_BODY == 120

    def test_timeout_quality_gate(self):
        assert TIMEOUT_QUALITY_GATE == 120


class TestSdkQueryTimeout:
    """Verify that _sdk_query respects timeout parameter."""

    def test_timeout_raises_on_slow_query(self):
        """A query that exceeds timeout should raise TimeoutError."""

        async def _slow_query(**kwargs):
            await asyncio.sleep(10)
            yield  # never reached

        with patch("claude_code_sdk.query", _slow_query):
            with pytest.raises(TimeoutError):
                asyncio.run(
                    _sdk_query(
                        "test",
                        model="sonnet",
                        max_turns=3,
                        allowed_tools=[],
                        timeout=0.1,
                    )
                )

    def test_no_timeout_completes_normally(self):
        """When timeout=None, a fast query completes without error."""
        from claude_code_sdk import ResultMessage

        async def _fast_query(**kwargs):
            msg = MagicMock(spec=ResultMessage)
            msg.total_cost_usd = 0.01
            msg.num_turns = 1
            yield msg

        with patch("claude_code_sdk.query", _fast_query):
            msgs, cost, turns = asyncio.run(
                _sdk_query(
                    "test",
                    model="sonnet",
                    max_turns=3,
                    allowed_tools=[],
                    timeout=None,
                )
            )
            assert cost == 0.01
            assert turns == 1


class TestBuildPermissionCallback:
    """Verify the can_use_tool callback respects SecurityPolicy."""

    def test_allows_safe_bash(self):
        policy = default_policy()
        callback = _build_permission_callback(policy)
        result = asyncio.run(callback("Bash", {"command": "git status"}, None))
        assert result.behavior == "allow"

    def test_blocks_dangerous_bash(self):
        policy = default_policy()
        callback = _build_permission_callback(policy)
        result = asyncio.run(callback("Bash", {"command": "rm -rf /"}, None))
        assert result.behavior == "deny"

    def test_blocks_write_outside_boundary(self, tmp_path):
        policy = SecurityPolicy(write_boundary=tmp_path)
        callback = _build_permission_callback(policy)
        result = asyncio.run(
            callback("Edit", {"file_path": "/etc/passwd"}, None)
        )
        assert result.behavior == "deny"

    def test_allows_write_inside_boundary(self, tmp_path):
        policy = SecurityPolicy(write_boundary=tmp_path)
        callback = _build_permission_callback(policy)
        target = str(tmp_path / "src" / "main.py")
        result = asyncio.run(callback("Edit", {"file_path": target}, None))
        assert result.behavior == "allow"

    def test_blocks_excalidraw(self):
        policy = default_policy()
        callback = _build_permission_callback(policy)
        result = asyncio.run(
            callback("mcp__excalidraw__create_element", {}, None)
        )
        assert result.behavior == "deny"


class TestCallImplementDryRun:
    def test_dry_run_returns_placeholder(self):
        output, cost, num_turns = asyncio.run(
            call_implement("test", worktree_path="/tmp", dry_run=True)
        )
        assert "dry-run" in output
        assert cost == 0.0
        assert num_turns == 0


class TestCallFixDryRun:
    def test_dry_run_returns_placeholder(self):
        output, cost, num_turns = asyncio.run(
            call_fix("test", worktree_path="/tmp", dry_run=True)
        )
        assert "dry-run" in output
        assert cost == 0.0
        assert num_turns == 0


class TestCallReviewDryRun:
    def test_dry_run_returns_pass(self):
        output, cost, num_turns = asyncio.run(
            call_review("test", worktree_path="/tmp", dry_run=True)
        )
        assert "PASS" in output
        assert cost == 0.0
        assert num_turns == 0


class TestCallPrBodyDryRun:
    def test_dry_run_returns_placeholder(self):
        output, cost, num_turns = asyncio.run(
            call_pr_body("test", dry_run=True)
        )
        assert "dry-run" in output
        assert cost == 0.0
        assert num_turns == 0
