"""Tests for dark_factory.state: PipelineState serialization round-trip."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dark_factory.state import PipelineError, PipelineState, SourceInfo


@pytest.fixture
def source():
    return SourceInfo(kind="jira", raw="SDLC-123", id="sdlc-123")


@pytest.fixture
def state(source, tmp_path):
    return PipelineState(source=source, repo_root=str(tmp_path))


class TestSourceInfo:
    def test_fields(self):
        s = SourceInfo(kind="file", raw="specs/feature.md", id="feature")
        assert s.kind == "file"
        assert s.raw == "specs/feature.md"
        assert s.id == "feature"


class TestPipelineStateSerialization:
    def test_save_creates_file(self, state, tmp_path):
        path = state.save()
        assert path.exists()
        assert path == tmp_path / ".dark-factory" / "sdlc-123.json"

    def test_save_creates_directory(self, state, tmp_path):
        state.save()
        assert (tmp_path / ".dark-factory").is_dir()

    def test_round_trip(self, state, tmp_path):
        state.current_phase = 3
        state.completed_phases = [0, 1, 2]
        state.phase_timings = {"0": 0.5, "1": 1.2, "2": 0.8}
        state.total_cost_usd = 0.42
        state.branch = "feat/sdlc-123"
        state.worktree_path = "/tmp/wt"
        state.epic_id = "EPIC-1"
        state.issues = [{"id": "SDLC-124", "title": "subtask"}]

        path = state.save()
        loaded = PipelineState.load(path)

        assert loaded.source.kind == "jira"
        assert loaded.source.id == "sdlc-123"
        assert loaded.current_phase == 3
        assert loaded.completed_phases == [0, 1, 2]
        assert loaded.phase_timings == {"0": 0.5, "1": 1.2, "2": 0.8}
        assert loaded.total_cost_usd == 0.42
        assert loaded.branch == "feat/sdlc-123"
        assert loaded.worktree_path == "/tmp/wt"
        assert loaded.epic_id == "EPIC-1"
        assert loaded.issues == [{"id": "SDLC-124", "title": "subtask"}]

    def test_save_is_valid_json(self, state, tmp_path):
        state.save()
        path = tmp_path / ".dark-factory" / "sdlc-123.json"
        data = json.loads(path.read_text())
        assert data["source"]["kind"] == "jira"

    def test_overwrite_on_second_save(self, state, tmp_path):
        state.save()
        state.current_phase = 5
        state.save()
        loaded = PipelineState.load(state._state_path())
        assert loaded.current_phase == 5

    def test_dry_run_preserved(self, source, tmp_path):
        state = PipelineState(source=source, repo_root=str(tmp_path), dry_run=True)
        path = state.save()
        loaded = PipelineState.load(path)
        assert loaded.dry_run is True

    def test_error_preserved(self, state, tmp_path):
        state.error = "Phase 2 failed: timeout"
        path = state.save()
        loaded = PipelineState.load(path)
        assert loaded.error == "Phase 2 failed: timeout"


class TestPipelineStateHelpers:
    def test_is_phase_completed(self, state):
        state.completed_phases = [0, 1, 2]
        assert state.is_phase_completed(1) is True
        assert state.is_phase_completed(5) is False

    def test_next_phase(self, state):
        state.current_phase = 3
        assert state.next_phase() == 3


class TestPipelineError:
    def test_message_includes_phase(self):
        err = PipelineError(phase=7, message="implementation failed")
        assert "Phase 7" in str(err)
        assert "implementation failed" in str(err)
        assert err.phase == 7
