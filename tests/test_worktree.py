"""Tests for dark_factory.worktree: parallel worktree management."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

from dark_factory.worktree import (
    ParallelWorktree,
    _active_worktrees,
    create_parallel_worktree,
    remove_parallel_worktree,
)


class TestCreateParallelWorktree:
    def test_dry_run_returns_info_without_subprocess(self):
        result = create_parallel_worktree("/repo/root", "beads-042", dry_run=True)
        assert isinstance(result, ParallelWorktree)
        assert result.branch_name == "parallel/beads-042"
        assert "parallel-beads-042" in result.worktree_path
        assert result.repo_root == "/repo/root"

    def test_dry_run_does_not_call_git(self):
        with patch("dark_factory.worktree.subprocess.run") as mock_run:
            create_parallel_worktree("/repo/root", "beads-001", dry_run=True)
            mock_run.assert_not_called()

    @patch("dark_factory.worktree.subprocess.run")
    def test_creates_worktree_with_git(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        result = create_parallel_worktree("/repo/root", "beads-042")

        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        assert args[0:3] == ["git", "worktree", "add"]
        assert "-b" in args
        assert "parallel/beads-042" in args

    @patch("dark_factory.worktree.subprocess.run")
    def test_registers_for_cleanup(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        # Clear registry
        _active_worktrees.clear()

        result = create_parallel_worktree("/repo/root", "beads-099")
        assert len(_active_worktrees) == 1
        assert _active_worktrees[0] == (result.worktree_path, result.branch_name)

        # Cleanup
        _active_worktrees.clear()


class TestRemoveParallelWorktree:
    @patch("dark_factory.worktree.subprocess.run")
    def test_removes_worktree_and_branch(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        remove_parallel_worktree("/tmp/wt", "parallel/beads-001", "/repo/root")

        assert mock_run.call_count == 2
        # First call: worktree remove
        assert mock_run.call_args_list[0][0][0][:3] == ["git", "worktree", "remove"]
        # Second call: branch delete
        assert mock_run.call_args_list[1][0][0][:3] == ["git", "branch", "-D"]

    @patch("dark_factory.worktree.subprocess.run")
    def test_cleanup_on_worktree_remove_failure(self, mock_run):
        """Branch delete still runs even if worktree remove fails."""
        mock_run.side_effect = [
            subprocess.TimeoutExpired(cmd="git", timeout=30),
            MagicMock(returncode=0),
        ]
        # Should not raise
        remove_parallel_worktree("/tmp/wt", "parallel/beads-001", "/repo/root")
        # Branch delete was still attempted
        assert mock_run.call_count == 2

    @patch("dark_factory.worktree.subprocess.run")
    def test_removes_from_registry(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        _active_worktrees.clear()
        _active_worktrees.append(("/tmp/wt", "parallel/beads-001"))

        remove_parallel_worktree("/tmp/wt", "parallel/beads-001", "/repo/root")
        assert len(_active_worktrees) == 0

    @patch("dark_factory.worktree.subprocess.run")
    def test_safe_to_call_twice(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        _active_worktrees.clear()
        _active_worktrees.append(("/tmp/wt", "parallel/beads-001"))

        remove_parallel_worktree("/tmp/wt", "parallel/beads-001", "/repo/root")
        remove_parallel_worktree("/tmp/wt", "parallel/beads-001", "/repo/root")
        # No error on second call
