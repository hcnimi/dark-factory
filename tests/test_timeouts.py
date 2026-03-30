"""Tests for per-task timeout and dynamic Phase 7 timeout."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from dark_factory.agents import (
    COST_CEILING_DEFAULT,
    TIMEOUT_IMPLEMENT,
    TIMEOUT_IMPLEMENT_BASE,
    TIMEOUT_IMPLEMENT_PER_TASK,
)
from dark_factory.pipeline import _implement_single_task, ImplementationResult
from dark_factory.state import PipelineState, SourceInfo


class TestTimeoutConstants:
    """Verify timeout constants are sensible."""

    def test_base_timeout(self):
        assert TIMEOUT_IMPLEMENT_BASE == 120

    def test_per_task_timeout(self):
        assert TIMEOUT_IMPLEMENT_PER_TASK == 300

    def test_cost_ceiling(self):
        assert COST_CEILING_DEFAULT == 20.0


class TestPerTaskTimeout:
    """Verify individual task timeout handling."""

    def test_timed_out_task_returns_failed(self, tmp_path):
        state = PipelineState(
            source=SourceInfo(kind="inline", raw="test", id="test-timeout"),
            repo_root=str(tmp_path),
        )
        issue = {"id": "T-1", "title": "Test task", "type": "task"}

        # Simulate a timeout by making wait_for raise TimeoutError
        original_wait_for = asyncio.wait_for

        async def _mock_wait_for(coro, *, timeout=None):
            # Cancel the coroutine to avoid warnings, then raise
            coro.close()
            raise asyncio.TimeoutError()

        with patch("dark_factory.agents.call_implement", AsyncMock(return_value=("done", 0.5, 5))):
            with patch("dark_factory.pipeline.asyncio.wait_for", _mock_wait_for):
                result = asyncio.run(
                    _implement_single_task(
                        state, issue, str(tmp_path), None,
                        dry_run=False, task_timeout=0.1,
                    )
                )

        assert isinstance(result, ImplementationResult)
        assert result.success is False
        assert "timed out" in result.output.lower()

    def test_fast_task_succeeds(self, tmp_path):
        state = PipelineState(
            source=SourceInfo(kind="inline", raw="test", id="test-fast"),
            repo_root=str(tmp_path),
        )
        issue = {"id": "T-2", "title": "Fast task", "type": "task"}

        async def _fast_implement(*args, **kwargs):
            return "implemented the feature successfully", 0.5, 5

        with patch("dark_factory.agents.call_implement", _fast_implement):
            with patch("dark_factory.pipeline.subprocess.run") as mock_run:
                mock_run.return_value = type("R", (), {"stdout": "1 file changed", "returncode": 0})()
                with patch("dark_factory.pipeline.detect_test_command", return_value=None):
                    result = asyncio.run(
                        _implement_single_task(
                            state, issue, str(tmp_path), None,
                            dry_run=False, task_timeout=600,
                        )
                    )

        assert result.success is True


class TestCliTaskTimeout:
    """Verify --task-timeout CLI parsing."""

    def test_task_timeout_flag(self):
        from dark_factory.cli import parse_args
        args = parse_args(["TEST-1", "--task-timeout", "120"])
        assert args.task_timeout == 120.0

    def test_task_timeout_equals_syntax(self):
        from dark_factory.cli import parse_args
        args = parse_args(["TEST-1", "--task-timeout=300"])
        assert args.task_timeout == 300.0

    def test_default_task_timeout_is_none(self):
        from dark_factory.cli import parse_args
        args = parse_args(["TEST-1"])
        assert args.task_timeout is None
