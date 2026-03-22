"""Tests for dark_factory.__main__: phase dispatch and JSON output."""

from __future__ import annotations

import json
import subprocess
import sys

import pytest


def run_module(*args: str, stdin: str = "") -> tuple[int, dict | None, str]:
    """Run ``python3 -m dark_factory`` and return (returncode, parsed_stdout, stderr)."""
    result = subprocess.run(
        [sys.executable, "-m", "dark_factory", *args],
        capture_output=True,
        text=True,
        input=stdin,
        timeout=10,
    )
    stdout_data = None
    if result.stdout.strip():
        try:
            stdout_data = json.loads(result.stdout)
        except json.JSONDecodeError:
            pass
    return result.returncode, stdout_data, result.stderr


class TestPhase0Dispatch:
    def test_jira_key(self):
        rc, data, _ = run_module("0", "SDLC-123")
        assert rc == 0
        assert data["phase"] == 0
        assert data["status"] == "initialized"
        assert data["source"]["kind"] == "jira"
        assert data["source"]["id"] == "sdlc-123"

    def test_file_path(self):
        rc, data, _ = run_module("0", "specs/feature.md")
        assert rc == 0
        assert data["source"]["kind"] == "file"

    def test_inline(self):
        rc, data, _ = run_module("0", "add", "dark", "mode")
        assert rc == 0
        assert data["source"]["kind"] == "inline"

    def test_dry_run_flag(self):
        rc, data, _ = run_module("0", "SDLC-1", "--dry-run")
        assert rc == 0
        assert data["dry_run"] is True

    def test_resume_no_prior_state(self):
        rc, data, _ = run_module("0", "SDLC-999", "--resume")
        assert rc == 0
        # No prior state file, so status is "initialized", not "resumed"
        assert data["status"] == "initialized"


class TestPhase5Dispatch:
    def test_renders_checkpoint(self):
        plan = {
            "external_ref": "jira:TEST-1",
            "summary": "Test feature",
            "branch": "dark-factory/test-1",
            "worktree_path": "/tmp/wt",
            "review_result": "PASS",
            "spec_overview": "Testing.",
            "requirements": ["Req A", "Req B"],
            "tasks": ["Task 1", "Task 2"],
        }
        rc, data, _ = run_module("5", stdin=json.dumps(plan))
        assert rc == 0
        assert data["phase"] == 5
        assert data["status"] == "checkpoint"
        assert "jira:TEST-1" in data["prompt"]
        assert "(A) Approve" in data["prompt"]

    def test_dry_run_checkpoint(self):
        plan = {
            "external_ref": "jira:TEST-1",
            "summary": "Test",
            "branch": "b",
            "worktree_path": "/tmp",
            "dry_run": True,
            "requirements": [],
            "tasks": [],
        }
        rc, data, _ = run_module("5", stdin=json.dumps(plan))
        assert rc == 0
        assert data["dry_run"] is True
        assert "Dry run complete" in data["prompt"]


class TestPhase6Dispatch:
    def test_dry_run_creates_issues(self):
        task_data = {
            "source_id": "TEST-1",
            "summary": "Test",
            "external_ref": "jira:TEST-1",
            "tasks": ["Task A", "Task B", "Task C"],
            "dry_run": True,
        }
        rc, data, _ = run_module("6", stdin=json.dumps(task_data))
        assert rc == 0
        assert data["phase"] == 6
        assert data["epic_id"] is not None
        assert len(data["issues"]) == 4  # 1 epic + 3 tasks

    def test_parses_tasks_text(self):
        task_data = {
            "source_id": "TEST-2",
            "summary": "Small",
            "external_ref": "jira:TEST-2",
            "tasks_text": "1. First task\n2. Second task\n",
            "dry_run": True,
        }
        rc, data, _ = run_module("6", stdin=json.dumps(task_data))
        assert rc == 0
        assert len(data["issues"]) == 2  # 2 tasks, no epic


class TestPhase10Dispatch:
    def test_no_dev_server(self, tmp_path):
        config = {
            "worktree_path": str(tmp_path),
            "check_items": ["Check login"],
        }
        rc, data, _ = run_module("10", stdin=json.dumps(config))
        assert rc == 0
        assert data["phase"] == 10
        assert data["command"] is None
        assert "No dev server command detected" in data["checklist"]

    def test_with_claude_md(self, tmp_path):
        config = {
            "worktree_path": str(tmp_path),
            "claude_md_text": "Start with npm run dev at http://localhost:4200",
            "check_items": ["Check UI"],
        }
        rc, data, _ = run_module("10", stdin=json.dumps(config))
        assert rc == 0
        assert data["command"] == "npm run dev"
        assert data["url"] == "http://localhost:4200"


class TestErrorHandling:
    def test_no_args(self):
        rc, _, stderr = run_module()
        assert rc == 1
        assert "Usage" in stderr

    def test_unknown_phase(self):
        rc, _, stderr = run_module("99")
        assert rc == 1
        assert "Unknown phase" in stderr


class TestZeroLLMTokens:
    """Verify that deterministic phases produce pure JSON output
    with no LLM interaction indicators."""

    def test_phase_0_is_deterministic(self):
        rc, data, _ = run_module("0", "SDLC-1")
        assert rc == 0
        # Output is valid JSON — no free-form LLM text
        assert isinstance(data, dict)
        assert "phase" in data

    def test_phase_5_is_deterministic(self):
        plan = {
            "external_ref": "x:1",
            "summary": "s",
            "branch": "b",
            "worktree_path": "/tmp",
            "requirements": ["r"],
            "tasks": ["t"],
        }
        rc, data, _ = run_module("5", stdin=json.dumps(plan))
        assert rc == 0
        assert isinstance(data, dict)

    def test_phase_6_is_deterministic(self):
        task_data = {
            "source_id": "X-1",
            "summary": "s",
            "external_ref": "x:1",
            "tasks": ["t"],
            "dry_run": True,
        }
        rc, data, _ = run_module("6", stdin=json.dumps(task_data))
        assert rc == 0
        assert isinstance(data, dict)

    def test_phase_10_is_deterministic(self, tmp_path):
        config = {
            "worktree_path": str(tmp_path),
            "check_items": [],
        }
        rc, data, _ = run_module("10", stdin=json.dumps(config))
        assert rc == 0
        assert isinstance(data, dict)
