"""Tests for dark_factory.lock: session locking."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from dark_factory.lock import SessionLock, acquire_lock, release_lock, _is_pid_alive
from dark_factory.state import PipelineError


class TestIsPidAlive:
    """Verify PID liveness detection."""

    def test_current_process_is_alive(self):
        assert _is_pid_alive(os.getpid()) is True

    def test_nonexistent_pid_is_dead(self):
        # PID 99999999 almost certainly doesn't exist
        assert _is_pid_alive(99999999) is False


class TestAcquireLock:
    """Verify lock acquisition behavior."""

    def test_acquires_lock_creates_file(self, tmp_path):
        lock = acquire_lock(tmp_path, "test-session", "run-123")
        assert lock.lock_path.exists()
        content = json.loads(lock.lock_path.read_text())
        assert content["pid"] == os.getpid()
        assert content["run_id"] == "run-123"

    def test_acquires_lock_returns_session_lock(self, tmp_path):
        lock = acquire_lock(tmp_path, "test-session", "run-123")
        assert isinstance(lock, SessionLock)
        assert lock.pid == os.getpid()
        assert lock.run_id == "run-123"

    def test_rejects_active_lock(self, tmp_path):
        # First lock with current PID (definitely alive)
        lock_path = tmp_path / "test-session.lock"
        lock_path.write_text(json.dumps({
            "pid": os.getpid(),
            "run_id": "existing-run",
        }))

        with pytest.raises(PipelineError, match="already running"):
            acquire_lock(tmp_path, "test-session", "new-run")

    def test_removes_stale_lock(self, tmp_path):
        # Lock with definitely-dead PID
        lock_path = tmp_path / "test-session.lock"
        lock_path.write_text(json.dumps({
            "pid": 99999999,
            "run_id": "dead-run",
        }))

        lock = acquire_lock(tmp_path, "test-session", "new-run")
        assert lock.run_id == "new-run"
        content = json.loads(lock.lock_path.read_text())
        assert content["pid"] == os.getpid()

    def test_removes_corrupted_lock(self, tmp_path):
        lock_path = tmp_path / "test-session.lock"
        lock_path.write_text("not valid json")

        lock = acquire_lock(tmp_path, "test-session", "new-run")
        assert lock.run_id == "new-run"

    def test_creates_state_dir_if_missing(self, tmp_path):
        state_dir = tmp_path / "subdir" / ".dark-factory"
        lock = acquire_lock(state_dir, "test-session", "run-123")
        assert state_dir.exists()
        assert lock.lock_path.exists()


class TestReleaseLock:
    """Verify lock release behavior."""

    def test_release_removes_file(self, tmp_path):
        lock = acquire_lock(tmp_path, "test-session", "run-123")
        assert lock.lock_path.exists()
        release_lock(lock)
        assert not lock.lock_path.exists()

    def test_release_idempotent(self, tmp_path):
        lock = acquire_lock(tmp_path, "test-session", "run-123")
        release_lock(lock)
        release_lock(lock)  # Should not raise
        assert not lock.lock_path.exists()


class TestRunIdInEvents:
    """Verify run_id is included in event logging."""

    def test_phase_event_includes_run_id(self, tmp_path):
        from dark_factory.pipeline import _log_phase_event
        from dark_factory.state import PipelineState, SourceInfo

        state = PipelineState(
            source=SourceInfo(kind="inline", raw="test", id="test-run-id"),
            repo_root=str(tmp_path),
            run_id="abc-123",
        )
        _log_phase_event(state, 7, "started")

        events_path = tmp_path / ".dark-factory" / "test-run-id.events.jsonl"
        assert events_path.exists()
        event = json.loads(events_path.read_text().strip())
        assert event["run_id"] == "abc-123"

    def test_task_event_includes_run_id(self, tmp_path):
        from dark_factory.pipeline import _log_task_event
        from dark_factory.state import PipelineState, SourceInfo

        state = PipelineState(
            source=SourceInfo(kind="inline", raw="test", id="test-run-id"),
            repo_root=str(tmp_path),
            run_id="abc-123",
        )
        _log_task_event(state, "task_start", task_id="T-1")

        events_path = tmp_path / ".dark-factory" / "test-run-id.events.jsonl"
        assert events_path.exists()
        event = json.loads(events_path.read_text().strip())
        assert event["run_id"] == "abc-123"

    def test_event_omits_run_id_when_empty(self, tmp_path):
        from dark_factory.pipeline import _log_phase_event
        from dark_factory.state import PipelineState, SourceInfo

        state = PipelineState(
            source=SourceInfo(kind="inline", raw="test", id="test-no-run"),
            repo_root=str(tmp_path),
        )
        _log_phase_event(state, 7, "started")

        events_path = tmp_path / ".dark-factory" / "test-no-run.events.jsonl"
        event = json.loads(events_path.read_text().strip())
        assert "run_id" not in event
