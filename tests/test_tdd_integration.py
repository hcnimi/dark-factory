"""Integration tests: TDD pipeline flow (Phase 6.5 -> 7 -> 8) and state serialization with float phases.

Task 6.4: End-to-end dry_run flow verifying Phase 6.5, Phase 7 (with/without
visible tests), and Phase 8 verify_tests all work together.

Task 6.5: PipelineState round-trip with float phase numbers (6.5) and new
test path fields (visible_test_paths, holdout_test_paths).
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from dark_factory.pipeline import (
    Phase6_5Result,
    Phase7Result,
    run_phase,
    run_phase_6_5,
    run_phase_7,
)
from dark_factory.state import PipelineState, SourceInfo
from dark_factory.verify import VerificationResult, verify_tests


# ---------------------------------------------------------------------------
# Task 6.4: Integration — Phase 6.5 → Phase 7 → Phase 8 dry-run flow
# ---------------------------------------------------------------------------

class TestTDDPipelineFlowDryRun:
    """End-to-end dry-run: Phase 6.5 test gen, Phase 7 implementation,
    Phase 8 verification, exercising the visible + hold-out test wiring."""

    @pytest.fixture
    def state(self, tmp_path):
        source = SourceInfo(kind="jira", raw="SDLC-123", id="sdlc-123")
        return PipelineState(
            source=source,
            repo_root=str(tmp_path),
            branch="dark-factory/sdlc-123",
            dry_run=True,
        )

    def test_phase_6_5_dry_run_returns_empty_result(self, state, tmp_path):
        """Phase 6.5 with dry_run=True returns empty Phase6_5Result."""
        result = asyncio.run(
            run_phase_6_5(
                state,
                worktree_path=str(tmp_path),
                spec_texts=["Given a user, When they log in, Then they see dashboard"],
                dry_run=True,
            )
        )
        assert isinstance(result, Phase6_5Result)
        assert result.visible_test_paths == []
        assert result.holdout_test_paths == []
        assert result.cost_usd == 0.0

    def test_phase_6_5_no_specs_returns_empty_result(self, state, tmp_path):
        """Phase 6.5 with empty spec_texts returns empty result even without dry_run."""
        result = asyncio.run(
            run_phase_6_5(
                state,
                worktree_path=str(tmp_path),
                spec_texts=[],
                dry_run=False,
            )
        )
        assert isinstance(result, Phase6_5Result)
        assert result.visible_test_paths == []
        assert result.holdout_test_paths == []

    def test_phase_7_dry_run_no_visible_tests(self, state, tmp_path):
        """Phase 7 dry_run with empty visible_test_paths — no TDD section injected."""
        assert state.visible_test_paths == []

        issues = [{"id": "T-1", "title": "Add login", "type": "task"}]
        result = asyncio.run(
            run_phase_7(state, issues, str(tmp_path), dry_run=True)
        )
        assert isinstance(result, Phase7Result)
        assert len(result.results) == 1
        assert result.results[0].issue_id == "T-1"
        assert result.results[0].success is True
        assert result.total_cost_usd == 0.0

    def test_phase_7_dry_run_with_visible_tests(self, state, tmp_path):
        """Phase 7 dry_run with populated visible_test_paths — TDD section
        would be injected (but dry_run skips the SDK call)."""
        # Create actual test files on disk so the TDD path-reading logic can work
        test_dir = tmp_path / "tests"
        test_dir.mkdir()
        visible_test = test_dir / "visible_tests_sdlc-123.py"
        visible_test.write_text(
            "def test_login_happy_path():\n"
            "    assert True\n"
        )

        state.visible_test_paths = [str(visible_test)]

        issues = [{"id": "T-1", "title": "Add login", "type": "task"}]
        result = asyncio.run(
            run_phase_7(state, issues, str(tmp_path), dry_run=True)
        )
        assert isinstance(result, Phase7Result)
        assert len(result.results) == 1
        assert result.results[0].success is True
        assert result.total_cost_usd == 0.0

    def test_verify_tests_dry_run_returns_tuple(self, tmp_path):
        """verify_tests with dry_run=True returns (VerificationResult, None)."""
        # Need a detectable test command so we reach the dry_run branch
        (tmp_path / "conftest.py").write_text("")

        vr, holdout = asyncio.run(
            verify_tests(str(tmp_path), dry_run=True)
        )
        assert isinstance(vr, VerificationResult)
        assert vr.passed is True
        assert "dry-run" in vr.final_output
        assert holdout is None

    def test_verify_tests_dry_run_with_holdout_paths(self, tmp_path):
        """verify_tests dry_run ignores holdout_test_paths (returns None for holdout)."""
        (tmp_path / "conftest.py").write_text("")

        vr, holdout = asyncio.run(
            verify_tests(
                str(tmp_path),
                dry_run=True,
                holdout_test_paths=["tests/holdout_tests_sdlc-123.py"],
            )
        )
        assert vr.passed is True
        assert holdout is None

    def test_full_flow_6_5_to_7_to_8(self, state, tmp_path):
        """End-to-end: Phase 6.5 -> Phase 7 -> Phase 8 in dry_run mode."""
        # Phase 6.5: test generation (dry_run returns empty)
        phase_6_5_result = asyncio.run(
            run_phase_6_5(
                state,
                worktree_path=str(tmp_path),
                spec_texts=["Feature: login"],
                dry_run=True,
            )
        )
        assert phase_6_5_result.visible_test_paths == []
        assert phase_6_5_result.holdout_test_paths == []

        # State reflects no test paths from dry_run
        assert state.visible_test_paths == []
        assert state.holdout_test_paths == []

        # Phase 7: implementation (dry_run)
        issues = [{"id": "T-1", "title": "Implement login", "type": "task"}]
        phase_7_result = asyncio.run(
            run_phase_7(state, issues, str(tmp_path), dry_run=True)
        )
        assert len(phase_7_result.results) == 1
        assert phase_7_result.results[0].success is True

        # Phase 8: verification (dry_run)
        (tmp_path / "conftest.py").write_text("")
        vr, holdout = asyncio.run(
            verify_tests(str(tmp_path), dry_run=True)
        )
        assert vr.passed is True
        assert holdout is None


# ---------------------------------------------------------------------------
# Task 6.5: PipelineState serialization with float phases and test paths
# ---------------------------------------------------------------------------

class TestStateSerializationFloatPhases:
    """Round-trip serialization with current_phase=6.5, float completed_phases,
    and visible/holdout test path fields."""

    def test_float_phase_round_trip(self, tmp_path):
        """current_phase=6.5 and 6.5 in completed_phases survive save/load."""
        source = SourceInfo(kind="jira", raw="SDLC-123", id="sdlc-123")
        state = PipelineState(
            source=source,
            repo_root=str(tmp_path),
            current_phase=6.5,
            completed_phases=[0, 1, 2, 3, 4, 5, 6, 6.5],
            visible_test_paths=["tests/visible_tests_sdlc-123.py"],
            holdout_test_paths=["tests/holdout_tests_sdlc-123.py"],
        )

        path = state.save()
        loaded = PipelineState.load(path)

        assert loaded.current_phase == 6.5
        assert 6.5 in loaded.completed_phases
        assert loaded.completed_phases == [0, 1, 2, 3, 4, 5, 6, 6.5]
        assert loaded.visible_test_paths == ["tests/visible_tests_sdlc-123.py"]
        assert loaded.holdout_test_paths == ["tests/holdout_tests_sdlc-123.py"]

    def test_float_phase_in_json(self, tmp_path):
        """Verify the JSON file stores 6.5 as a float, not a string."""
        source = SourceInfo(kind="jira", raw="T-1", id="t-1")
        state = PipelineState(
            source=source,
            repo_root=str(tmp_path),
            current_phase=6.5,
            completed_phases=[0, 1, 2, 3, 4, 5, 6, 6.5],
        )

        path = state.save()
        data = json.loads(path.read_text())

        assert data["current_phase"] == 6.5
        assert isinstance(data["current_phase"], float)
        assert 6.5 in data["completed_phases"]

    def test_test_paths_in_json(self, tmp_path):
        """visible_test_paths and holdout_test_paths appear in JSON."""
        source = SourceInfo(kind="jira", raw="T-1", id="t-1")
        state = PipelineState(
            source=source,
            repo_root=str(tmp_path),
            visible_test_paths=["tests/visible_a.py", "tests/visible_b.py"],
            holdout_test_paths=["tests/holdout_a.py"],
        )

        path = state.save()
        data = json.loads(path.read_text())

        assert data["visible_test_paths"] == ["tests/visible_a.py", "tests/visible_b.py"]
        assert data["holdout_test_paths"] == ["tests/holdout_a.py"]

    def test_is_phase_completed_with_float(self, tmp_path):
        """is_phase_completed(6.5) returns True when 6.5 is in completed_phases."""
        source = SourceInfo(kind="jira", raw="T-1", id="t-1")
        state = PipelineState(
            source=source,
            repo_root=str(tmp_path),
            completed_phases=[0, 1, 2, 3, 4, 5, 6, 6.5],
        )

        assert state.is_phase_completed(6.5) is True
        assert state.is_phase_completed(6) is True
        assert state.is_phase_completed(7) is False

    def test_is_phase_completed_float_survives_round_trip(self, tmp_path):
        """is_phase_completed(6.5) still works after save/load."""
        source = SourceInfo(kind="jira", raw="T-1", id="t-1")
        state = PipelineState(
            source=source,
            repo_root=str(tmp_path),
            completed_phases=[0, 1, 2, 3, 4, 5, 6, 6.5],
        )

        path = state.save()
        loaded = PipelineState.load(path)

        assert loaded.is_phase_completed(6.5) is True
        assert loaded.is_phase_completed(6) is True
        assert loaded.is_phase_completed(7) is False

    def test_phase_advancement_6_to_6_5(self, tmp_path):
        """After phase 6, run_phase advances current_phase to 6.5."""
        source = SourceInfo(kind="jira", raw="T-1", id="t-1")
        state = PipelineState(
            source=source,
            repo_root=str(tmp_path),
            current_phase=6,
            completed_phases=[0, 1, 2, 3, 4, 5],
        )

        async def noop():
            return None

        asyncio.run(run_phase(state, 6, noop))

        assert state.current_phase == 6.5
        assert 6 in state.completed_phases

    def test_phase_advancement_6_5_to_7(self, tmp_path):
        """After phase 6.5, run_phase advances current_phase to 7."""
        source = SourceInfo(kind="jira", raw="T-1", id="t-1")
        state = PipelineState(
            source=source,
            repo_root=str(tmp_path),
            current_phase=6.5,
            completed_phases=[0, 1, 2, 3, 4, 5, 6],
        )

        async def noop():
            return None

        asyncio.run(run_phase(state, 6.5, noop))

        assert state.current_phase == 7
        assert 6.5 in state.completed_phases

    def test_phase_advancement_full_sequence(self, tmp_path):
        """Phase 5 -> 6 -> 6.5 -> 7 -> 8 advancement chain."""
        source = SourceInfo(kind="jira", raw="T-1", id="t-1")
        state = PipelineState(
            source=source,
            repo_root=str(tmp_path),
            current_phase=5,
            completed_phases=[0, 1, 2, 3, 4],
        )

        async def noop():
            return None

        asyncio.run(run_phase(state, 5, noop))
        assert state.current_phase == 6

        asyncio.run(run_phase(state, 6, noop))
        assert state.current_phase == 6.5

        asyncio.run(run_phase(state, 6.5, noop))
        assert state.current_phase == 7

        asyncio.run(run_phase(state, 7, noop))
        assert state.current_phase == 8

        assert state.completed_phases == [0, 1, 2, 3, 4, 5, 6, 6.5, 7]

    def test_float_phase_timing_key(self, tmp_path):
        """Phase timing for 6.5 is stored with string key '6.5'."""
        source = SourceInfo(kind="jira", raw="T-1", id="t-1")
        state = PipelineState(
            source=source,
            repo_root=str(tmp_path),
            current_phase=6.5,
            completed_phases=[0, 1, 2, 3, 4, 5, 6],
        )

        async def noop():
            return None

        asyncio.run(run_phase(state, 6.5, noop))

        assert "6.5" in state.phase_timings
        assert state.phase_timings["6.5"] >= 0

    def test_empty_test_paths_round_trip(self, tmp_path):
        """Empty visible/holdout paths survive round-trip as empty lists."""
        source = SourceInfo(kind="jira", raw="T-1", id="t-1")
        state = PipelineState(
            source=source,
            repo_root=str(tmp_path),
            visible_test_paths=[],
            holdout_test_paths=[],
        )

        path = state.save()
        loaded = PipelineState.load(path)

        assert loaded.visible_test_paths == []
        assert loaded.holdout_test_paths == []

    def test_multiple_test_paths_round_trip(self, tmp_path):
        """Multiple entries in test path lists survive round-trip."""
        source = SourceInfo(kind="jira", raw="T-1", id="t-1")
        state = PipelineState(
            source=source,
            repo_root=str(tmp_path),
            visible_test_paths=[
                "tests/visible_tests_t-1.py",
                "tests/visible_tests_t-1_extra.py",
            ],
            holdout_test_paths=[
                "tests/holdout_tests_t-1.py",
                "tests/holdout_tests_t-1_edge.py",
            ],
        )

        path = state.save()
        loaded = PipelineState.load(path)

        assert loaded.visible_test_paths == [
            "tests/visible_tests_t-1.py",
            "tests/visible_tests_t-1_extra.py",
        ]
        assert loaded.holdout_test_paths == [
            "tests/holdout_tests_t-1.py",
            "tests/holdout_tests_t-1_edge.py",
        ]
