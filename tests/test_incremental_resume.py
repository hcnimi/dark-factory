"""Tests for Phase 7 incremental resume with git validation."""

from __future__ import annotations

import asyncio
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from dark_factory.pipeline import (
    ImplementationResult,
    _validate_task_completion,
    run_phase_7,
)
from dark_factory.state import PipelineState, SourceInfo


class TestValidateTaskCompletion:
    """Verify git checkpoint validation."""

    def test_returns_true_when_commit_found(self, tmp_path):
        with patch("dark_factory.pipeline.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="abc1234 checkpoint: Implements T-1\n")
            assert _validate_task_completion("T-1", str(tmp_path)) is True

    def test_returns_false_when_no_commit(self, tmp_path):
        with patch("dark_factory.pipeline.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="")
            assert _validate_task_completion("T-1", str(tmp_path)) is False

    def test_returns_false_on_timeout(self, tmp_path):
        with patch(
            "dark_factory.pipeline.subprocess.run",
            side_effect=subprocess.TimeoutExpired("git", 10),
        ):
            assert _validate_task_completion("T-1", str(tmp_path)) is False

    def test_returns_false_on_file_not_found(self, tmp_path):
        with patch(
            "dark_factory.pipeline.subprocess.run",
            side_effect=FileNotFoundError("git not found"),
        ):
            assert _validate_task_completion("T-1", str(tmp_path)) is False


class TestResumeSkipsValidCompletions:
    """Verify resume skips tasks with valid git commits."""

    def test_skips_task_with_git_commit(self, tmp_path):
        state = PipelineState(
            source=SourceInfo(kind="inline", raw="test", id="test-resume"),
            repo_root=str(tmp_path),
            phase7_completed_tasks=["T-1"],
        )
        issues = [
            {"id": "T-1", "title": "Already done", "type": "task"},
            {"id": "T-2", "title": "Not done", "type": "task"},
        ]

        with patch("dark_factory.pipeline._validate_task_completion", return_value=True):
            with patch("dark_factory.pipeline._implement_single_task") as mock_impl:
                mock_impl.return_value = ImplementationResult(
                    issue_id="T-2", success=True, output="done", cost_usd=0.5
                )
                result = asyncio.run(
                    run_phase_7(state, issues, str(tmp_path), dry_run=False)
                )

        # T-1 skipped, only T-2 implemented
        mock_impl.assert_called_once()
        call_issue = mock_impl.call_args[0][1]  # second positional arg is the issue
        assert call_issue["id"] == "T-2"


class TestResumeInvalidatesGhostCompletions:
    """Verify ghost completions (no git commit) are re-run."""

    def test_reruns_task_without_git_commit(self, tmp_path):
        state = PipelineState(
            source=SourceInfo(kind="inline", raw="test", id="test-ghost"),
            repo_root=str(tmp_path),
            phase7_completed_tasks=["T-1"],
        )
        issues = [
            {"id": "T-1", "title": "Ghost completion", "type": "task"},
        ]

        with patch("dark_factory.pipeline._validate_task_completion", return_value=False):
            with patch("dark_factory.pipeline._implement_single_task") as mock_impl:
                mock_impl.return_value = ImplementationResult(
                    issue_id="T-1", success=True, output="done", cost_usd=0.5
                )
                result = asyncio.run(
                    run_phase_7(state, issues, str(tmp_path), dry_run=False)
                )

        # T-1 should be re-implemented after ghost invalidation
        mock_impl.assert_called_once()
        call_issue = mock_impl.call_args[0][1]
        assert call_issue["id"] == "T-1"

    def test_dry_run_skips_validation(self, tmp_path):
        """In dry_run mode, validation is skipped — tasks are just skipped."""
        state = PipelineState(
            source=SourceInfo(kind="inline", raw="test", id="test-dry"),
            repo_root=str(tmp_path),
            phase7_completed_tasks=["T-1"],
        )
        issues = [
            {"id": "T-1", "title": "Already done", "type": "task"},
        ]

        with patch("dark_factory.pipeline._validate_task_completion") as mock_validate:
            with patch("dark_factory.pipeline._implement_single_task") as mock_impl:
                result = asyncio.run(
                    run_phase_7(state, issues, str(tmp_path), dry_run=True)
                )

        # Validation should not be called in dry_run
        mock_validate.assert_not_called()
        # Task should be skipped, not implemented
        mock_impl.assert_not_called()
