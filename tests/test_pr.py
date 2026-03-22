"""Tests for dark_factory.pr: Phase 11 push, PR creation, and cleanup."""

from __future__ import annotations

import asyncio
import json

import pytest

from dark_factory.pr import (
    PRResult,
    cleanup_state_file,
    close_issues,
    create_pr,
    generate_pr_body,
    run_phase_11,
)


class TestCleanupStateFile:
    def test_removes_json_state(self, tmp_path):
        state_dir = tmp_path / ".dark-factory"
        state_dir.mkdir()
        state_file = state_dir / "test-1.json"
        state_file.write_text("{}")

        cleanup_state_file(str(tmp_path), "test-1")
        assert not state_file.exists()

    def test_removes_md_state(self, tmp_path):
        state_dir = tmp_path / ".dark-factory"
        state_dir.mkdir()
        md_file = state_dir / "test-1.md"
        md_file.write_text("# state")

        cleanup_state_file(str(tmp_path), "test-1")
        assert not md_file.exists()

    def test_removes_empty_dir(self, tmp_path):
        state_dir = tmp_path / ".dark-factory"
        state_dir.mkdir()
        state_file = state_dir / "test-1.json"
        state_file.write_text("{}")

        cleanup_state_file(str(tmp_path), "test-1")
        assert not state_dir.exists()

    def test_keeps_dir_with_other_files(self, tmp_path):
        state_dir = tmp_path / ".dark-factory"
        state_dir.mkdir()
        (state_dir / "test-1.json").write_text("{}")
        (state_dir / "other.json").write_text("{}")

        cleanup_state_file(str(tmp_path), "test-1")
        assert state_dir.exists()
        assert (state_dir / "other.json").exists()

    def test_no_state_file_is_safe(self, tmp_path):
        # Should not raise even if nothing exists
        cleanup_state_file(str(tmp_path), "nonexistent")


class TestCloseIssues:
    def test_dry_run_returns_all_ids(self):
        result = close_issues(["A-1", "A-2"], "done", dry_run=True)
        assert result == ["A-1", "A-2"]

    def test_empty_list(self):
        result = close_issues([], "done", dry_run=True)
        assert result == []


class TestCreatePr:
    def test_dry_run_returns_placeholder_url(self):
        url = create_pr("/tmp", "branch", "title", "body", dry_run=True)
        assert "github.com" in url
        assert url.startswith("https://")


class TestGeneratePrBody:
    def test_dry_run_includes_summary(self):
        body, cost = asyncio.run(
            generate_pr_body(
                "10 files changed",
                "TEST-1",
                "Test feature",
                "jira:TEST-1",
                "dark-factory-test-1",
                dry_run=True,
            )
        )
        assert "Test feature" in body
        assert cost == 0.0

    def test_dry_run_includes_external_ref(self):
        body, cost = asyncio.run(
            generate_pr_body(
                "", "X-1", "s", "jira:X-1", "dark-factory-x-1", dry_run=True
            )
        )
        assert "jira:X-1" in body


class TestRunPhase11:
    def test_dry_run_full_flow(self, tmp_path):
        # Create state file to verify cleanup
        state_dir = tmp_path / ".dark-factory"
        state_dir.mkdir()
        (state_dir / "test-1.json").write_text("{}")

        result = asyncio.run(
            run_phase_11(
                repo_root=str(tmp_path),
                worktree_path=str(tmp_path / "wt"),
                branch="dark-factory/test-1",
                source_id="test-1",
                summary="Test feature",
                external_ref="jira:TEST-1",
                issue_ids=["ISS-1", "ISS-2"],
                dry_run=True,
            )
        )

        assert isinstance(result, PRResult)
        assert result.pr_url.startswith("https://")
        assert result.branch == "dark-factory/test-1"
        assert result.closed_issues == ["ISS-1", "ISS-2"]
        # State file cleaned up
        assert not (state_dir / "test-1.json").exists()

    def test_dry_run_no_issues(self, tmp_path):
        result = asyncio.run(
            run_phase_11(
                repo_root=str(tmp_path),
                worktree_path=str(tmp_path / "wt"),
                branch="dark-factory/test-1",
                source_id="test-1",
                summary="Test",
                external_ref="jira:TEST-1",
                issue_ids=[],
                dry_run=True,
            )
        )
        assert result.closed_issues == []
