"""Tests for dark_factory.pipeline: run_phase() wrapper."""

from __future__ import annotations

import asyncio

import pytest

from dark_factory.pipeline import run_phase
from dark_factory.state import PipelineError, PipelineState, SourceInfo


@pytest.fixture
def state(tmp_path):
    return PipelineState(
        source=SourceInfo(kind="jira", raw="TEST-1", id="test-1"),
        repo_root=str(tmp_path),
    )


class TestRunPhase:
    def test_success_records_timing(self, state):
        async def phase_fn():
            return "done"

        result = asyncio.run(run_phase(state, 0, phase_fn))
        assert result == "done"
        assert "0" in state.phase_timings
        assert state.phase_timings["0"] >= 0

    def test_success_appends_completed(self, state):
        async def phase_fn():
            return None

        asyncio.run(run_phase(state, 0, phase_fn))
        assert 0 in state.completed_phases

    def test_success_advances_current_phase(self, state):
        async def phase_fn():
            return None

        asyncio.run(run_phase(state, 0, phase_fn))
        assert state.current_phase == 1

    def test_success_saves_state(self, state, tmp_path):
        async def phase_fn():
            return None

        asyncio.run(run_phase(state, 0, phase_fn))
        path = tmp_path / ".dark-factory" / "test-1.json"
        assert path.exists()

    def test_failure_raises_pipeline_error(self, state):
        async def bad_phase():
            raise ValueError("something broke")

        with pytest.raises(PipelineError) as exc_info:
            asyncio.run(run_phase(state, 2, bad_phase))
        assert exc_info.value.phase == 2
        assert "something broke" in str(exc_info.value)

    def test_failure_saves_state(self, state, tmp_path):
        async def bad_phase():
            raise RuntimeError("crash")

        with pytest.raises(PipelineError):
            asyncio.run(run_phase(state, 3, bad_phase))

        path = tmp_path / ".dark-factory" / "test-1.json"
        assert path.exists()
        loaded = PipelineState.load(path)
        assert loaded.error == "crash"

    def test_failure_records_timing(self, state):
        async def bad_phase():
            raise RuntimeError("fail")

        with pytest.raises(PipelineError):
            asyncio.run(run_phase(state, 1, bad_phase))
        assert "1" in state.phase_timings

    def test_failure_does_not_add_to_completed(self, state):
        async def bad_phase():
            raise RuntimeError("fail")

        with pytest.raises(PipelineError):
            asyncio.run(run_phase(state, 4, bad_phase))
        assert 4 not in state.completed_phases

    def test_passes_args_to_phase_fn(self, state):
        results = []

        async def phase_fn(a, b, key=None):
            results.append((a, b, key))

        asyncio.run(run_phase(state, 0, phase_fn, "x", "y", key="z"))
        assert results == [("x", "y", "z")]

    def test_sequential_phases(self, state):
        async def noop():
            return None

        asyncio.run(run_phase(state, 0, noop))
        asyncio.run(run_phase(state, 1, noop))
        asyncio.run(run_phase(state, 2, noop))

        assert state.completed_phases == [0, 1, 2]
        assert state.current_phase == 3
        assert len(state.phase_timings) == 3
