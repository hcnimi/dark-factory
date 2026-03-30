"""Tests for resume artifact validation."""

from __future__ import annotations

import pytest

from dark_factory.state import PipelineState, SourceInfo


def _make_state(tmp_path, **overrides):
    """Create a PipelineState with sensible defaults."""
    defaults = dict(
        source=SourceInfo(kind="inline", raw="test", id="test-resume"),
        repo_root=str(tmp_path),
    )
    defaults.update(overrides)
    return PipelineState(**defaults)


class TestValidatePhaseArtifacts:
    """Verify artifact validation per phase."""

    def test_phase_6_5_valid_with_test_paths(self, tmp_path):
        from dark_factory.__main__ import _validate_phase_artifacts
        state = _make_state(tmp_path,
            visible_test_paths=["/tmp/tests/visible.py"],
            phase_timings={"6.5": 5.0},
        )
        assert _validate_phase_artifacts(state, 6.5) is True

    def test_phase_6_5_invalid_without_test_paths(self, tmp_path):
        from dark_factory.__main__ import _validate_phase_artifacts
        state = _make_state(tmp_path, phase_timings={"6.5": 5.0})
        assert _validate_phase_artifacts(state, 6.5) is False

    def test_phase_6_75_valid_with_contracts(self, tmp_path):
        from dark_factory.__main__ import _validate_phase_artifacts
        state = _make_state(tmp_path,
            sprint_contracts=[{"task_id": "T-1"}],
            phase_timings={"6.75": 3.0},
        )
        assert _validate_phase_artifacts(state, 6.75) is True

    def test_phase_6_75_invalid_without_contracts(self, tmp_path):
        from dark_factory.__main__ import _validate_phase_artifacts
        state = _make_state(tmp_path, phase_timings={"6.75": 3.0})
        assert _validate_phase_artifacts(state, 6.75) is False

    def test_phase_7_valid_with_completed_tasks(self, tmp_path):
        from dark_factory.__main__ import _validate_phase_artifacts
        state = _make_state(tmp_path,
            phase7_completed_tasks=["T-1", "T-2"],
            phase_timings={"7": 120.0},
        )
        assert _validate_phase_artifacts(state, 7) is True

    def test_phase_7_invalid_without_completed_tasks(self, tmp_path):
        from dark_factory.__main__ import _validate_phase_artifacts
        state = _make_state(tmp_path, phase_timings={"7": 120.0})
        assert _validate_phase_artifacts(state, 7) is False

    def test_ghost_completion_detected_by_timing(self, tmp_path):
        from dark_factory.__main__ import _validate_phase_artifacts
        state = _make_state(tmp_path,
            visible_test_paths=["/tmp/test.py"],
            phase_timings={"6.5": 0.001},  # 1ms = ghost
        )
        assert _validate_phase_artifacts(state, 6.5) is False

    def test_phase_8_valid_with_timing(self, tmp_path):
        from dark_factory.__main__ import _validate_phase_artifacts
        state = _make_state(tmp_path, phase_timings={"8": 30.0})
        assert _validate_phase_artifacts(state, 8) is True

    def test_phase_8_ghost_by_timing(self, tmp_path):
        from dark_factory.__main__ import _validate_phase_artifacts
        state = _make_state(tmp_path, phase_timings={"8": 0.01})
        assert _validate_phase_artifacts(state, 8) is False

    def test_other_phases_always_valid(self, tmp_path):
        from dark_factory.__main__ import _validate_phase_artifacts
        state = _make_state(tmp_path)
        assert _validate_phase_artifacts(state, 1) is True
        assert _validate_phase_artifacts(state, 2) is True
        assert _validate_phase_artifacts(state, 11) is True


class TestShouldRunPhase:
    """Verify _should_run_phase detects ghost completions."""

    def test_uncompleted_phase_should_run(self, tmp_path):
        from dark_factory.__main__ import _should_run_phase
        state = _make_state(tmp_path)
        assert _should_run_phase(state, 7) is True

    def test_completed_phase_with_artifacts_should_not_run(self, tmp_path):
        from dark_factory.__main__ import _should_run_phase
        state = _make_state(tmp_path,
            completed_phases=[7],
            phase7_completed_tasks=["T-1"],
            phase_timings={"7": 120.0},
        )
        assert _should_run_phase(state, 7) is False

    def test_ghost_completion_should_rerun(self, tmp_path):
        from dark_factory.__main__ import _should_run_phase
        state = _make_state(tmp_path,
            completed_phases=[6.5],
            phase_timings={"6.5": 0.003},  # ghost
        )
        assert _should_run_phase(state, 6.5) is True
        # Phase should be removed from completed_phases
        assert 6.5 not in state.completed_phases

    def test_completed_phase_without_artifacts_should_rerun(self, tmp_path):
        from dark_factory.__main__ import _should_run_phase
        state = _make_state(tmp_path,
            completed_phases=[6.75],
            phase_timings={"6.75": 5.0},
            # no sprint_contracts
        )
        assert _should_run_phase(state, 6.75) is True
        assert 6.75 not in state.completed_phases
