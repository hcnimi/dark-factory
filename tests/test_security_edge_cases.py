"""Edge-case tests for dark_factory.security: blocked patterns, boundaries, tools.

Covers pattern boundary conditions, path traversal, symlink-like paths,
multiple blocked tool prefixes, and case sensitivity.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dark_factory.security import (
    DEFAULT_BLOCKED_PATTERNS,
    DEFAULT_BLOCKED_TOOLS,
    SecurityPolicy,
    default_policy,
    enforce_security,
)


# ---------------------------------------------------------------------------
# Blocked Bash patterns: boundary cases
# ---------------------------------------------------------------------------

class TestBlockedPatternBoundaries:
    """Verify blocked patterns match correctly at boundaries."""

    def test_rm_rf_root_blocked(self):
        policy = default_policy()
        assert enforce_security(policy, "Bash", {"command": "rm -rf /"}) is False

    def test_rm_rf_home_blocked(self):
        policy = default_policy()
        assert enforce_security(policy, "Bash", {"command": "rm -rf /home/user"}) is False

    def test_rm_single_file_allowed(self):
        policy = default_policy()
        assert enforce_security(policy, "Bash", {"command": "rm temp.txt"}) is True

    def test_rm_rf_relative_allowed(self):
        # "rm -rf build/" actually IS allowed: the pattern r"rm\s+-rf\s+/" requires
        # a / immediately after the whitespace following -rf. "rm -rf build/" has
        # "build/" not matching \s+/ directly.
        policy = default_policy()
        assert enforce_security(policy, "Bash", {"command": "rm -rf build/"}) is True

    def test_rm_rf_dot_allowed(self):
        # "rm -rf ." doesn't have /
        policy = default_policy()
        assert enforce_security(policy, "Bash", {"command": "rm -rf ."}) is True

    def test_git_force_push_with_flag_position(self):
        policy = default_policy()
        # --force before branch
        assert enforce_security(
            policy, "Bash", {"command": "git push --force origin feat/x"}
        ) is False
        # --force after remote/branch
        assert enforce_security(
            policy, "Bash", {"command": "git push origin feat --force"}
        ) is False

    def test_git_force_push_shorthand_not_blocked(self):
        # -f is not in the default pattern (only --force)
        policy = default_policy()
        result = enforce_security(
            policy, "Bash", {"command": "git push -f origin feat"}
        )
        # Default patterns use --force, so -f is allowed (gap by design)
        assert result is True

    def test_drop_table_case_insensitive(self):
        policy = default_policy()
        assert enforce_security(
            policy, "Bash", {"command": "drop table users"}
        ) is False
        assert enforce_security(
            policy, "Bash", {"command": "DROP TABLE users"}
        ) is False

    def test_drop_table_in_longer_command(self):
        policy = default_policy()
        assert enforce_security(
            policy, "Bash", {"command": "psql -c 'DROP TABLE users CASCADE'"}
        ) is False

    def test_git_checkout_main_blocked(self):
        policy = default_policy()
        assert enforce_security(
            policy, "Bash", {"command": "git checkout main"}
        ) is False

    def test_git_checkout_main_with_extra_args_blocked(self):
        # git\s+checkout\s+main\b should block "git checkout main" but the \b
        # allows "git checkout main --" to still match
        policy = default_policy()
        assert enforce_security(
            policy, "Bash", {"command": "git checkout main --"}
        ) is False

    def test_git_checkout_feature_branch_allowed(self):
        policy = default_policy()
        assert enforce_security(
            policy, "Bash", {"command": "git checkout feat/main-page"}
        ) is True

    def test_git_checkout_main_substring_blocked(self):
        # \b matches between "main" and "-" since "-" is non-word char,
        # so "git checkout main-feature" IS blocked by the pattern
        policy = default_policy()
        assert enforce_security(
            policy, "Bash", {"command": "git checkout main-feature"}
        ) is False

    def test_git_reset_hard_blocked(self):
        policy = default_policy()
        assert enforce_security(
            policy, "Bash", {"command": "git reset --hard HEAD~1"}
        ) is False
        assert enforce_security(
            policy, "Bash", {"command": "git reset --hard"}
        ) is False

    def test_git_reset_soft_allowed(self):
        policy = default_policy()
        assert enforce_security(
            policy, "Bash", {"command": "git reset --soft HEAD~1"}
        ) is True

    def test_empty_command(self):
        policy = default_policy()
        assert enforce_security(policy, "Bash", {"command": ""}) is True

    def test_missing_command_key(self):
        policy = default_policy()
        assert enforce_security(policy, "Bash", {}) is True


# ---------------------------------------------------------------------------
# Write boundary enforcement
# ---------------------------------------------------------------------------

class TestWriteBoundaryEdgeCases:
    def test_exact_boundary_path_allowed(self, tmp_path):
        """Writing to the boundary root itself should be allowed."""
        policy = SecurityPolicy(write_boundary=tmp_path)
        target = str(tmp_path / "file.py")
        assert enforce_security(policy, "Write", {"file_path": target}) is True

    def test_parent_directory_blocked(self, tmp_path):
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        policy = SecurityPolicy(write_boundary=worktree)
        target = str(tmp_path / "outside.py")
        assert enforce_security(policy, "Edit", {"file_path": target}) is False

    def test_sibling_directory_blocked(self, tmp_path):
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        other = tmp_path / "other-repo"
        other.mkdir()
        policy = SecurityPolicy(write_boundary=worktree)
        target = str(other / "file.py")
        assert enforce_security(policy, "Write", {"file_path": target}) is False

    def test_deeply_nested_inside_allowed(self, tmp_path):
        policy = SecurityPolicy(write_boundary=tmp_path)
        target = str(tmp_path / "a" / "b" / "c" / "d" / "file.py")
        assert enforce_security(policy, "Edit", {"file_path": target}) is True

    def test_path_traversal_blocked(self, tmp_path):
        """Path with .. that escapes boundary should be blocked."""
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        policy = SecurityPolicy(write_boundary=worktree)
        # ../other-repo resolves outside the boundary
        target = str(worktree / ".." / "other-repo" / "file.py")
        assert enforce_security(policy, "Write", {"file_path": target}) is False

    def test_empty_file_path(self, tmp_path):
        policy = SecurityPolicy(write_boundary=tmp_path)
        # Empty path doesn't trigger the block (early return on empty)
        assert enforce_security(policy, "Write", {"file_path": ""}) is True

    def test_no_file_path_key(self, tmp_path):
        policy = SecurityPolicy(write_boundary=tmp_path)
        assert enforce_security(policy, "Write", {}) is True

    def test_read_not_affected_by_boundary(self, tmp_path):
        """Read tool should NOT be blocked by write boundary."""
        policy = SecurityPolicy(write_boundary=tmp_path)
        assert enforce_security(
            policy, "Read", {"file_path": "/etc/passwd"}
        ) is True

    def test_glob_not_affected_by_boundary(self, tmp_path):
        """Glob tool should NOT be blocked by write boundary."""
        policy = SecurityPolicy(write_boundary=tmp_path)
        assert enforce_security(
            policy, "Glob", {"pattern": "**/*.py", "path": "/outside"}
        ) is True

    def test_grep_not_affected_by_boundary(self, tmp_path):
        policy = SecurityPolicy(write_boundary=tmp_path)
        assert enforce_security(
            policy, "Grep", {"pattern": "TODO", "path": "/outside"}
        ) is True


# ---------------------------------------------------------------------------
# Blocked tools: pattern matching
# ---------------------------------------------------------------------------

class TestBlockedToolsEdgeCases:
    def test_excalidraw_all_variants_blocked(self):
        policy = default_policy()
        tools = [
            "mcp__excalidraw__create_element",
            "mcp__excalidraw__delete_element",
            "mcp__excalidraw__update_element",
            "mcp__excalidraw__export_scene",
            "mcp__excalidraw__batch_create_elements",
            "mcp__excalidraw__get_canvas_screenshot",
        ]
        for tool in tools:
            assert enforce_security(policy, tool, {}) is False, f"{tool} should be blocked"

    def test_non_excalidraw_mcp_allowed(self):
        policy = default_policy()
        assert enforce_security(policy, "mcp__github__create_pr", {}) is True

    def test_multiple_blocked_tool_prefixes(self):
        policy = SecurityPolicy(blocked_tools=["mcp__slack__", "mcp__excalidraw__"])
        assert enforce_security(policy, "mcp__slack__send", {}) is False
        assert enforce_security(policy, "mcp__excalidraw__create_element", {}) is False
        assert enforce_security(policy, "mcp__github__create_pr", {}) is True

    def test_empty_blocked_tools(self):
        policy = SecurityPolicy(blocked_tools=[])
        assert enforce_security(policy, "mcp__excalidraw__create_element", {}) is True

    def test_blocked_tool_exact_match(self):
        """Substring match: 'Read' as a blocked tool blocks anything containing 'Read'."""
        policy = SecurityPolicy(blocked_tools=["Read"])
        assert enforce_security(policy, "Read", {}) is False
        # Also blocks ReadFile etc since it's substring
        assert enforce_security(policy, "ReadFile", {}) is False

    def test_core_tools_allowed_by_default(self):
        policy = default_policy()
        for tool in ["Read", "Edit", "Write", "Bash", "Glob", "Grep"]:
            assert enforce_security(policy, tool, {}) is True, f"{tool} should be allowed"


# ---------------------------------------------------------------------------
# Combined policies
# ---------------------------------------------------------------------------

class TestCombinedPolicies:
    def test_bash_blocked_plus_boundary(self, tmp_path):
        """Both bash blocking and write boundary should work together."""
        policy = SecurityPolicy(
            blocked_patterns=[r"rm\s+-rf"],
            write_boundary=tmp_path,
        )
        # Bash blocked
        assert enforce_security(
            policy, "Bash", {"command": "rm -rf /tmp"}
        ) is False
        # Write outside boundary blocked
        assert enforce_security(
            policy, "Write", {"file_path": "/etc/file"}
        ) is False
        # Normal bash allowed
        assert enforce_security(
            policy, "Bash", {"command": "ls -la"}
        ) is True
        # Write inside boundary allowed
        assert enforce_security(
            policy, "Write", {"file_path": str(tmp_path / "ok.py")}
        ) is True

    def test_all_three_checks_in_one_policy(self, tmp_path):
        policy = SecurityPolicy(
            blocked_patterns=[r"rm\s+-rf"],
            write_boundary=tmp_path,
            blocked_tools=["mcp__slack__"],
        )
        # Tool blocked
        assert enforce_security(policy, "mcp__slack__send", {}) is False
        # Bash blocked
        assert enforce_security(
            policy, "Bash", {"command": "rm -rf /x"}
        ) is False
        # Boundary blocked
        assert enforce_security(
            policy, "Edit", {"file_path": "/outside/file.py"}
        ) is False
        # All checks pass
        assert enforce_security(
            policy, "Bash", {"command": "echo hello"}
        ) is True


# ---------------------------------------------------------------------------
# Default policy structure
# ---------------------------------------------------------------------------

class TestDefaultPolicyStructure:
    def test_blocked_patterns_count(self):
        policy = default_policy()
        # Should have at least the 6 patterns defined in DEFAULT_BLOCKED_PATTERNS
        assert len(policy.blocked_patterns) >= 6

    def test_blocked_tools_includes_excalidraw(self):
        policy = default_policy()
        assert any("excalidraw" in t for t in policy.blocked_tools)

    def test_default_patterns_are_valid_regex(self):
        """All default patterns must compile without error."""
        import re
        for pattern in DEFAULT_BLOCKED_PATTERNS:
            re.compile(pattern)  # Raises re.error if invalid

    def test_worktree_sets_boundary(self, tmp_path):
        policy = default_policy(worktree=tmp_path)
        assert policy.write_boundary == tmp_path

    def test_no_worktree_no_boundary(self):
        policy = default_policy()
        assert policy.write_boundary is None
