"""Tests for Phase 7 feedback loop improvements.

Covers: lint-in-loop prompt, self-review checklist prompt, and
_run_targeted_tests helper.
"""

from __future__ import annotations

from unittest.mock import patch

import subprocess

import pytest

from dark_factory.pipeline import _build_phase7_prompt, _run_targeted_tests


class TestRunTargetedTests:
    """Tests for _run_targeted_tests helper."""

    def test_dry_run_returns_empty(self):
        result = _run_targeted_tests("/tmp/wt", "pytest", dry_run=True)
        assert result == ""

    def test_no_test_command_returns_empty(self):
        result = _run_targeted_tests("/tmp/wt", None)
        assert result == ""

    def test_no_test_command_default_returns_empty(self):
        result = _run_targeted_tests("/tmp/wt")
        assert result == ""

    def test_timeout_returns_empty(self):
        with patch("dark_factory.pipeline.subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired(cmd="pytest", timeout=120)
            result = _run_targeted_tests("/tmp/wt", "pytest")
        assert result == ""

    def test_file_not_found_returns_empty(self):
        with patch("dark_factory.pipeline.subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError("pytest not found")
            result = _run_targeted_tests("/tmp/wt", "pytest")
        assert result == ""

    def test_successful_run_returns_output(self):
        with patch("dark_factory.pipeline.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args="pytest",
                returncode=0,
                stdout="3 passed",
                stderr="",
            )
            result = _run_targeted_tests("/tmp/wt", "pytest")
        assert "3 passed" in result

    def test_calls_subprocess_with_correct_args(self):
        with patch("dark_factory.pipeline.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args="pytest", returncode=0, stdout="", stderr="",
            )
            _run_targeted_tests("/my/worktree", "npm test")

        mock_run.assert_called_once_with(
            "npm test",
            shell=True,
            cwd="/my/worktree",
            capture_output=True,
            text=True,
            timeout=120,
        )


class TestPhase7PromptLintInstruction:
    """4a: Verify the Phase 7 prompt includes lint-in-loop instruction."""

    def test_prompt_contains_lint_instruction(self):
        prompt = _build_phase7_prompt(
            worktree_path="/tmp/wt",
            issue_id="T-1",
            issue_title="Add feature",
        )
        assert "run the project's lint command if available" in prompt

    def test_prompt_contains_fix_lint_errors(self):
        prompt = _build_phase7_prompt(
            worktree_path="/tmp/wt",
            issue_id="T-1",
            issue_title="Add feature",
        )
        assert "Fix any lint errors before moving to the next file" in prompt

    def test_lint_step_is_numbered_8(self):
        prompt = _build_phase7_prompt(
            worktree_path="/tmp/wt",
            issue_id="T-1",
            issue_title="Add feature",
        )
        assert "8. After completing each file change, run the project's lint command" in prompt


class TestPhase7PromptSelfReviewChecklist:
    """4b: Verify the Phase 7 prompt includes expanded self-review checklist."""

    def test_prompt_contains_self_review_checklist_heading(self):
        prompt = _build_phase7_prompt(
            worktree_path="/tmp/wt",
            issue_id="T-1",
            issue_title="Add feature",
        )
        assert "Self-review checklist before committing" in prompt

    def test_prompt_contains_git_diff_stat(self):
        prompt = _build_phase7_prompt(
            worktree_path="/tmp/wt",
            issue_id="T-1",
            issue_title="Fix bug",
        )
        assert "git diff --stat" in prompt

    def test_prompt_contains_debug_artifacts_check(self):
        prompt = _build_phase7_prompt(
            worktree_path="/tmp/wt",
            issue_id="T-1",
            issue_title="Fix bug",
        )
        assert "debug artifacts" in prompt
        assert "console.log" in prompt
        assert "FIXME" in prompt

    def test_prompt_contains_test_files_check(self):
        prompt = _build_phase7_prompt(
            worktree_path="/tmp/wt",
            issue_id="T-1",
            issue_title="Fix bug",
        )
        assert "Confirm test files exist for new/modified source files" in prompt

    def test_prompt_contains_commented_out_code_check(self):
        prompt = _build_phase7_prompt(
            worktree_path="/tmp/wt",
            issue_id="T-1",
            issue_title="Fix bug",
        )
        assert "Remove any commented-out code you added" in prompt

    def test_prompt_includes_issue_details(self):
        prompt = _build_phase7_prompt(
            worktree_path="/my/path",
            issue_id="PROJ-42",
            issue_title="Refactor widgets",
        )
        assert "PROJ-42" in prompt
        assert "Refactor widgets" in prompt
        assert "/my/path" in prompt
