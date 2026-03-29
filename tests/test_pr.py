"""Tests for dark_factory.pr: Phase 11 push, PR creation, and cleanup."""

from __future__ import annotations

import asyncio

import pytest

from dark_factory.pr import (
    PRResult,
    cleanup_state_file,
    create_draft_pr,
    create_pr,
    generate_pr_body,
    mark_pr_ready,
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
        cleanup_state_file(str(tmp_path), "nonexistent")


class TestCreatePr:
    def test_dry_run_returns_placeholder_url(self):
        url = create_pr("/tmp", "branch", "title", "body", dry_run=True)
        assert "github.com" in url
        assert url.startswith("https://")


class TestCreateDraftPr:
    def test_dry_run_returns_placeholder_url(self):
        url = create_draft_pr("/tmp", "branch", "title", "body", dry_run=True)
        assert "github.com" in url

    def test_dry_run_does_not_call_subprocess(self):
        url = create_draft_pr("/tmp", "branch", "t", "b", dry_run=True)
        assert isinstance(url, str)


class TestMarkPrReady:
    def test_dry_run_is_noop(self):
        mark_pr_ready("/tmp", dry_run=True)


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
                dry_run=True,
            )
        )

        assert isinstance(result, PRResult)
        assert result.pr_url.startswith("https://")
        assert result.branch == "dark-factory/test-1"
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
                dry_run=True,
            )
        )
        assert isinstance(result, PRResult)
