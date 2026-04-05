"""Tests for dark_factory.security."""

import pytest
from pathlib import Path

from dark_factory.security import (
    check_security,
    default_policy,
    build_permission_callback,
    DEFAULT_BLOCKED_PATTERNS,
    DEFAULT_BLOCKED_TOOLS,
)
from dark_factory.types import SecurityPolicy


class TestCheckSecurity:
    @pytest.mark.parametrize("command", [
        "rm -rf /",
        "rm  -rf  /etc",
        "git push --force origin main",
        "git push origin main --force",
        "git push origin main -f",
        "git push -f origin feature",
        "git reset --hard",
        "git reset --hard HEAD~5",
        "DROP TABLE users",
        "drop table sessions",
        "git checkout main",
        "git checkout master",
        "git branch -D main",
        "git branch -D master",
    ])
    def test_blocks_dangerous_commands(self, command):
        policy = default_policy()
        allowed, reason = check_security(policy, "Bash", {"command": command})
        assert not allowed
        assert reason  # Has explanation

    @pytest.mark.parametrize("command", [
        "python3 -m pytest",
        "git status",
        "git commit -m 'fix'",
        "git push origin feature-branch",
        "npm test",
        "ls -la",
        "cat README.md",
    ])
    def test_allows_safe_commands(self, command):
        policy = default_policy()
        allowed, _ = check_security(policy, "Bash", {"command": command})
        assert allowed

    def test_blocks_mcp_tools(self):
        policy = default_policy()
        allowed, _ = check_security(policy, "mcp__slack__send", {})
        assert not allowed

    def test_allows_standard_tools(self):
        policy = default_policy()
        for tool in ("Read", "Edit", "Write", "Bash", "Glob", "Grep"):
            allowed, _ = check_security(policy, tool, {})
            assert allowed

    def test_write_boundary_blocks_outside(self, tmp_path):
        policy = SecurityPolicy(write_boundary=tmp_path / "worktree")
        (tmp_path / "worktree").mkdir()

        allowed, _ = check_security(policy, "Edit", {"file_path": "/etc/passwd"})
        assert not allowed

    def test_write_boundary_allows_inside(self, tmp_path):
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        policy = SecurityPolicy(write_boundary=worktree)

        allowed, _ = check_security(policy, "Edit", {"file_path": str(worktree / "src/main.py")})
        assert allowed

    def test_read_tools_not_blocked_by_boundary(self, tmp_path):
        policy = SecurityPolicy(write_boundary=tmp_path / "worktree")
        allowed, _ = check_security(policy, "Read", {"file_path": "/etc/hosts"})
        assert allowed


class TestDefaultPolicy:
    def test_has_blocked_patterns(self):
        policy = default_policy()
        assert len(policy.blocked_patterns) == len(DEFAULT_BLOCKED_PATTERNS)

    def test_accepts_write_boundary(self, tmp_path):
        policy = default_policy(write_boundary=tmp_path)
        assert policy.write_boundary == tmp_path


class TestPermissionCallback:
    @pytest.mark.asyncio
    async def test_callback_allows_safe(self):
        from claude_code_sdk.types import PermissionResultAllow
        policy = default_policy()
        cb = build_permission_callback(policy)
        # SDK callback takes 3 args: tool_name, tool_input, context
        result = await cb("Read", {"file_path": "/tmp/test"}, None)
        assert isinstance(result, PermissionResultAllow)

    @pytest.mark.asyncio
    async def test_callback_blocks_dangerous(self):
        from claude_code_sdk.types import PermissionResultDeny
        policy = default_policy()
        cb = build_permission_callback(policy)
        result = await cb("Bash", {"command": "rm -rf /"}, None)
        assert isinstance(result, PermissionResultDeny)
        assert result.message  # Has explanation
