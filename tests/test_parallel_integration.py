"""Integration tests for parallel task execution in Phase 7.

Tests the full pipeline path from run_phase_7() with dependency markers,
verifying wave resolution, execution ordering, and backward compatibility.
"""

from __future__ import annotations

import asyncio

import pytest

from dark_factory.pipeline import (
    ImplementationResult,
    MergeConflict,
    Phase7Result,
    run_phase_7,
)
from dark_factory.state import PipelineState, SourceInfo


@pytest.fixture
def state(tmp_path):
    return PipelineState(
        source=SourceInfo(kind="inline", raw="test", id="test-parallel"),
        repo_root=str(tmp_path),
        branch="dark-factory/test-parallel",
        max_parallel=3,
    )


class TestParallelMarkerIntegration:
    """8.1: Full pipeline with parallel markers produces correct wave execution order."""

    def test_all_parallel_tasks_complete(self, state):
        """All [P] tasks should execute (single wave in parallel path)."""
        issues = [
            {"id": "T-1", "title": "[P] Add validation endpoint", "type": "task"},
            {"id": "T-2", "title": "[P] Add email service", "type": "task"},
            {"id": "T-3", "title": "[P] Update docs", "type": "task"},
        ]
        result = asyncio.run(
            run_phase_7(state, issues, "/tmp/wt", dry_run=True)
        )
        assert len(result.results) == 3
        assert all(r.success for r in result.results)
        ids = {r.issue_id for r in result.results}
        assert ids == {"T-1", "T-2", "T-3"}

    def test_dependent_task_runs_after_dependencies(self, state):
        """Task with [depends: 1, 2] should appear after tasks 1 and 2 in results."""
        issues = [
            {"id": "T-1", "title": "[P] Add validation endpoint", "type": "task"},
            {"id": "T-2", "title": "[P] Add email service", "type": "task"},
            {"id": "T-3", "title": "[depends: 1, 2] Wire validation into email", "type": "task"},
        ]
        result = asyncio.run(
            run_phase_7(state, issues, "/tmp/wt", dry_run=True)
        )
        assert len(result.results) == 3
        result_ids = [r.issue_id for r in result.results]
        t3_idx = result_ids.index("T-3")
        t1_idx = result_ids.index("T-1")
        t2_idx = result_ids.index("T-2")
        assert t3_idx > t1_idx
        assert t3_idx > t2_idx

    def test_diamond_dependency_ordering(self, state):
        """Diamond: 1 -> (2, 3) -> 4. Task 4 must be last."""
        issues = [
            {"id": "T-1", "title": "[P] Base module", "type": "task"},
            {"id": "T-2", "title": "[depends: 1] Feature A", "type": "task"},
            {"id": "T-3", "title": "[depends: 1] Feature B", "type": "task"},
            {"id": "T-4", "title": "[depends: 2, 3] Integration", "type": "task"},
        ]
        result = asyncio.run(
            run_phase_7(state, issues, "/tmp/wt", dry_run=True)
        )
        assert len(result.results) == 4
        result_ids = [r.issue_id for r in result.results]
        assert result_ids[-1] == "T-4"
        assert result_ids[0] == "T-1"

    def test_mixed_parallel_and_dependent(self, state):
        """Mix of [P] and [depends:] with an independent task in a later wave."""
        issues = [
            {"id": "T-1", "title": "[P] Independent A", "type": "task"},
            {"id": "T-2", "title": "[P] Independent B", "type": "task"},
            {"id": "T-3", "title": "[depends: 1, 2] Depends on A and B", "type": "task"},
            {"id": "T-4", "title": "[P] Independent C", "type": "task"},
            {"id": "T-5", "title": "[depends: 3] Depends on C-combo", "type": "task"},
        ]
        result = asyncio.run(
            run_phase_7(state, issues, "/tmp/wt", dry_run=True)
        )
        assert len(result.results) == 5
        result_ids = [r.issue_id for r in result.results]
        assert result_ids.index("T-5") > result_ids.index("T-3")
        assert result_ids.index("T-3") > result_ids.index("T-1")
        assert result_ids.index("T-3") > result_ids.index("T-2")

    def test_epics_filtered_from_parallel_execution(self, state):
        """Epics should be skipped even in parallel mode."""
        issues = [
            {"id": "E-1", "title": "Epic", "type": "epic"},
            {"id": "T-1", "title": "[P] Task A", "type": "task"},
            {"id": "T-2", "title": "[P] Task B", "type": "task"},
        ]
        result = asyncio.run(
            run_phase_7(state, issues, "/tmp/wt", dry_run=True)
        )
        assert len(result.results) == 2
        ids = {r.issue_id for r in result.results}
        assert "E-1" not in ids

    def test_merge_conflicts_empty_in_dry_run(self, state):
        """Dry-run should not produce merge conflicts."""
        issues = [
            {"id": "T-1", "title": "[P] Task A", "type": "task"},
            {"id": "T-2", "title": "[P] Task B", "type": "task"},
        ]
        result = asyncio.run(
            run_phase_7(state, issues, "/tmp/wt", dry_run=True)
        )
        assert result.merge_conflicts == []

    def test_zero_cost_in_dry_run(self, state):
        """Dry-run should have zero cost."""
        issues = [
            {"id": "T-1", "title": "[P] Task A", "type": "task"},
            {"id": "T-2", "title": "[depends: 1] Task B", "type": "task"},
        ]
        result = asyncio.run(
            run_phase_7(state, issues, "/tmp/wt", dry_run=True)
        )
        assert result.total_cost_usd == 0.0


class TestSequentialFallbackIntegration:
    """8.2: Pipeline without markers preserves sequential behavior."""

    def test_no_markers_sequential_order(self, state):
        """Tasks without markers should execute in listed order."""
        issues = [
            {"id": "T-1", "title": "Add endpoint", "type": "task"},
            {"id": "T-2", "title": "Add tests", "type": "task"},
            {"id": "T-3", "title": "Update docs", "type": "task"},
        ]
        result = asyncio.run(
            run_phase_7(state, issues, "/tmp/wt", dry_run=True)
        )
        assert len(result.results) == 3
        ids = [r.issue_id for r in result.results]
        assert ids == ["T-1", "T-2", "T-3"]

    def test_no_markers_all_succeed(self, state):
        """Sequential tasks should all succeed in dry-run."""
        issues = [
            {"id": "T-1", "title": "Task A", "type": "task"},
            {"id": "T-2", "title": "Task B", "type": "task"},
        ]
        result = asyncio.run(
            run_phase_7(state, issues, "/tmp/wt", dry_run=True)
        )
        assert all(r.success for r in result.results)

    def test_no_markers_empty_merge_conflicts(self, state):
        """Sequential mode should never produce merge conflicts."""
        issues = [
            {"id": "T-1", "title": "Task A", "type": "task"},
        ]
        result = asyncio.run(
            run_phase_7(state, issues, "/tmp/wt", dry_run=True)
        )
        assert result.merge_conflicts == []

    def test_empty_issues_returns_empty_result(self, state):
        """No issues should return an empty result."""
        result = asyncio.run(
            run_phase_7(state, [], "/tmp/wt", dry_run=True)
        )
        assert result.results == []
        assert result.total_cost_usd == 0.0

    def test_only_epics_returns_empty_result(self, state):
        """Only epics (no tasks) should return an empty result."""
        issues = [
            {"id": "E-1", "title": "Epic 1", "type": "epic"},
        ]
        result = asyncio.run(
            run_phase_7(state, issues, "/tmp/wt", dry_run=True)
        )
        assert result.results == []
