"""Tests for dark_factory.pipeline: Phases 7 and 9."""

from __future__ import annotations

import asyncio
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from dark_factory.pipeline import (
    ImplementationResult,
    MergeConflict,
    Phase7Result,
    ReviewResult,
    _has_dependency_markers,
    _is_off_rails,
    merge_parallel_branch,
    run_phase_7,
    run_phase_9,
)
from dark_factory.state import PipelineState, SourceInfo


@pytest.fixture
def state(tmp_path):
    return PipelineState(
        source=SourceInfo(kind="jira", raw="TEST-1", id="test-1"),
        repo_root=str(tmp_path),
        branch="dark-factory/test-1",
    )


class TestIsOffRails:
    """Heuristic guard for implementation agent."""

    def test_short_messages_not_off_rails(self):
        assert _is_off_rails(["msg1", "msg2", "msg3"]) is False

    def test_few_messages_not_off_rails(self):
        assert _is_off_rails([f"msg{i}" for i in range(9)]) is False

    def test_repeated_messages_is_off_rails(self):
        msgs = [f"msg{i}" for i in range(8)] + ["stuck"] * 5
        assert _is_off_rails(msgs) is True

    def test_excessive_messages_is_off_rails(self):
        msgs = [f"msg{i}" for i in range(101)]
        assert _is_off_rails(msgs) is True

    def test_varied_messages_not_off_rails(self):
        msgs = [f"msg{i}" for i in range(50)]
        assert _is_off_rails(msgs) is False


class TestPhase7DryRun:
    def test_skips_epics(self, state):
        issues = [
            {"id": "E-1", "title": "Epic", "type": "epic"},
            {"id": "T-1", "title": "Task 1", "type": "task"},
        ]
        result = asyncio.run(
            run_phase_7(state, issues, "/tmp/wt", dry_run=True)
        )
        assert isinstance(result, Phase7Result)
        # Only the task should be processed, not the epic
        assert len(result.results) == 1
        assert result.results[0].issue_id == "T-1"

    def test_processes_all_tasks(self, state):
        issues = [
            {"id": "T-1", "title": "Task 1", "type": "task"},
            {"id": "T-2", "title": "Task 2", "type": "task"},
            {"id": "T-3", "title": "Task 3", "type": "task"},
        ]
        result = asyncio.run(
            run_phase_7(state, issues, "/tmp/wt", dry_run=True)
        )
        assert len(result.results) == 3

    def test_dry_run_zero_cost(self, state):
        issues = [{"id": "T-1", "title": "Task 1", "type": "task"}]
        result = asyncio.run(
            run_phase_7(state, issues, "/tmp/wt", dry_run=True)
        )
        assert result.total_cost_usd == 0.0

    def test_empty_issues(self, state):
        result = asyncio.run(
            run_phase_7(state, [], "/tmp/wt", dry_run=True)
        )
        assert result.results == []

    def test_result_contains_issue_ids(self, state):
        issues = [
            {"id": "T-1", "title": "Task 1", "type": "task"},
            {"id": "T-2", "title": "Task 2", "type": "task"},
        ]
        result = asyncio.run(
            run_phase_7(state, issues, "/tmp/wt", dry_run=True)
        )
        ids = [r.issue_id for r in result.results]
        assert ids == ["T-1", "T-2"]


class TestPhase9DryRun:
    def test_dry_run_returns_pass(self):
        result = asyncio.run(
            run_phase_9("/tmp/wt", spec_text="test spec", dry_run=True)
        )
        assert isinstance(result, ReviewResult)
        assert result.verdict == "PASS"

    def test_dry_run_zero_cost(self):
        result = asyncio.run(
            run_phase_9("/tmp/wt", dry_run=True)
        )
        assert result.total_cost_usd == 0.0


class TestImplementationResult:
    def test_fields(self):
        r = ImplementationResult(
            issue_id="T-1",
            success=True,
            output="done",
            cost_usd=0.5,
        )
        assert r.issue_id == "T-1"
        assert r.success is True
        assert r.cost_usd == 0.5


class TestReviewResult:
    def test_total_cost(self):
        r = ReviewResult(
            review_cost_usd=1.0,
            fix_cost_usd=0.5,
        )
        assert r.total_cost_usd == 1.5

    def test_default_verdict_is_pass(self):
        r = ReviewResult()
        assert r.verdict == "PASS"


class TestHasDependencyMarkers:
    def test_no_markers(self):
        issues = [{"title": "Add endpoint", "type": "task"}]
        assert _has_dependency_markers(issues) is False

    def test_parallel_marker(self):
        issues = [{"title": "[P] Add endpoint", "type": "task"}]
        assert _has_dependency_markers(issues) is True

    def test_depends_marker(self):
        issues = [{"title": "[depends: 1] Wire up", "type": "task"}]
        assert _has_dependency_markers(issues) is True


class TestMergeParallelBranch:
    @patch("dark_factory.pipeline.subprocess.run")
    def test_clean_merge(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        assert merge_parallel_branch("/wt", "parallel/t-1") is True

    @patch("dark_factory.pipeline.subprocess.run")
    def test_conflict_returns_false(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1)
        assert merge_parallel_branch("/wt", "parallel/t-1") is False

    @patch("dark_factory.pipeline.subprocess.run")
    def test_timeout_returns_false(self, mock_run):
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="git", timeout=60)
        assert merge_parallel_branch("/wt", "parallel/t-1") is False


class TestPhase7WithMarkersDryRun:
    def test_parallel_markers_dry_run(self, state):
        """Tasks with [P] markers should still complete in dry-run."""
        issues = [
            {"id": "T-1", "title": "[P] Add endpoint", "type": "task"},
            {"id": "T-2", "title": "[P] Add tests", "type": "task"},
            {"id": "T-3", "title": "[depends: 1, 2] Wire up", "type": "task"},
        ]
        result = asyncio.run(
            run_phase_7(state, issues, "/tmp/wt", dry_run=True)
        )
        assert len(result.results) == 3
        ids = [r.issue_id for r in result.results]
        assert "T-1" in ids
        assert "T-2" in ids
        assert "T-3" in ids

    def test_sequential_fallback_no_markers(self, state):
        """Tasks without markers should use sequential execution."""
        issues = [
            {"id": "T-1", "title": "Add endpoint", "type": "task"},
            {"id": "T-2", "title": "Add tests", "type": "task"},
        ]
        result = asyncio.run(
            run_phase_7(state, issues, "/tmp/wt", dry_run=True)
        )
        assert len(result.results) == 2
        # Sequential: T-1 before T-2
        assert result.results[0].issue_id == "T-1"
        assert result.results[1].issue_id == "T-2"


class TestMergeConflict:
    def test_merge_conflict_fields(self):
        mc = MergeConflict(issue_id="T-1", branch_name="parallel/T-1")
        assert mc.issue_id == "T-1"
        assert mc.branch_name == "parallel/T-1"

    def test_merge_conflict_default_status(self):
        mc = MergeConflict(issue_id="T-1", branch_name="parallel/T-1")
        assert mc.status == "needs-manual-merge"

    def test_phase7_result_has_merge_conflicts(self):
        result = Phase7Result()
        assert result.merge_conflicts == []


class TestPhase7ErrorIsolation:
    def test_skipped_dependency_failed_dry_run(self, state):
        """If task 1 fails (simulated), task 3 depending on 1 should be skipped."""
        # In dry-run mode tasks don't actually fail, so this mainly tests
        # that the wave execution path handles the markers correctly
        issues = [
            {"id": "T-1", "title": "[P] Task A", "type": "task"},
            {"id": "T-2", "title": "[P] Task B", "type": "task"},
            {"id": "T-3", "title": "[depends: 1] Task C", "type": "task"},
        ]
        result = asyncio.run(
            run_phase_7(state, issues, "/tmp/wt", dry_run=True)
        )
        # All should complete in dry-run (no actual failures)
        assert len(result.results) == 3


class TestSubWaveBatching:
    """WARNING 1: When a wave has more tasks than max_parallel, sub-batching kicks in."""

    def test_five_parallel_tasks_with_max_parallel_2(self, state):
        """5 [P] tasks with max_parallel=2 should sub-batch into 3 batches (2+2+1)."""
        state.max_parallel = 2
        issues = [
            {"id": "T-1", "title": "[P] Task A", "type": "task"},
            {"id": "T-2", "title": "[P] Task B", "type": "task"},
            {"id": "T-3", "title": "[P] Task C", "type": "task"},
            {"id": "T-4", "title": "[P] Task D", "type": "task"},
            {"id": "T-5", "title": "[P] Task E", "type": "task"},
        ]
        result = asyncio.run(
            run_phase_7(state, issues, "/tmp/wt", dry_run=True)
        )
        assert len(result.results) == 5
        assert all(r.success for r in result.results)
        ids = {r.issue_id for r in result.results}
        assert ids == {"T-1", "T-2", "T-3", "T-4", "T-5"}

    def test_six_parallel_with_dependent_and_max_parallel_2(self, state):
        """6 [P] tasks + 1 dependent, max_parallel=2. All complete in correct order."""
        state.max_parallel = 2
        issues = [
            {"id": "T-1", "title": "[P] Task A", "type": "task"},
            {"id": "T-2", "title": "[P] Task B", "type": "task"},
            {"id": "T-3", "title": "[P] Task C", "type": "task"},
            {"id": "T-4", "title": "[P] Task D", "type": "task"},
            {"id": "T-5", "title": "[P] Task E", "type": "task"},
            {"id": "T-6", "title": "[P] Task F", "type": "task"},
            {"id": "T-7", "title": "[depends: 1, 2, 3, 4, 5, 6] Final", "type": "task"},
        ]
        result = asyncio.run(
            run_phase_7(state, issues, "/tmp/wt", dry_run=True)
        )
        assert len(result.results) == 7
        result_ids = [r.issue_id for r in result.results]
        # Dependent task must be last
        assert result_ids[-1] == "T-7"


class TestMaxParallelOne:
    """WARNING 2: max_parallel=1 should force sequential execution through the parallel path."""

    def test_max_parallel_1_all_parallel_tasks(self, state):
        """With max_parallel=1, [P] tasks execute one at a time."""
        state.max_parallel = 1
        issues = [
            {"id": "T-1", "title": "[P] Task A", "type": "task"},
            {"id": "T-2", "title": "[P] Task B", "type": "task"},
            {"id": "T-3", "title": "[P] Task C", "type": "task"},
        ]
        result = asyncio.run(
            run_phase_7(state, issues, "/tmp/wt", dry_run=True)
        )
        assert len(result.results) == 3
        assert all(r.success for r in result.results)
        ids = {r.issue_id for r in result.results}
        assert ids == {"T-1", "T-2", "T-3"}

    def test_max_parallel_1_with_dependencies(self, state):
        """max_parallel=1 with [depends:] still respects wave ordering."""
        state.max_parallel = 1
        issues = [
            {"id": "T-1", "title": "[P] Task A", "type": "task"},
            {"id": "T-2", "title": "[P] Task B", "type": "task"},
            {"id": "T-3", "title": "[depends: 1, 2] Task C", "type": "task"},
        ]
        result = asyncio.run(
            run_phase_7(state, issues, "/tmp/wt", dry_run=True)
        )
        assert len(result.results) == 3
        result_ids = [r.issue_id for r in result.results]
        assert result_ids.index("T-3") > result_ids.index("T-1")
        assert result_ids.index("T-3") > result_ids.index("T-2")


class TestMultipleMergeConflicts:
    """WARNING 3: Multiple merge conflicts in a single wave."""

    @patch("dark_factory.pipeline._abort_merge")
    @patch("dark_factory.pipeline.merge_parallel_branch")
    @patch("dark_factory.worktree.remove_parallel_worktree")
    @patch("dark_factory.worktree.create_parallel_worktree")
    @patch("dark_factory.pipeline._implement_single_task")
    def test_two_of_three_branches_conflict(
        self,
        mock_impl,
        mock_create_wt,
        mock_remove_wt,
        mock_merge,
        mock_abort,
        state,
    ):
        """When 2 of 3 branches conflict, both get MergeConflict entries."""
        from dark_factory.worktree import ParallelWorktree

        # Worktree creation returns stubs
        mock_create_wt.side_effect = [
            ParallelWorktree(f"/wt-{i}", f"parallel/T-{i}", state.repo_root)
            for i in range(1, 4)
        ]

        # All 3 implementations succeed
        async def _success_impl(st, issue, wt, sysprompt, *, dry_run=False):
            return ImplementationResult(
                issue_id=issue["id"], success=True, output="ok", cost_usd=0.0,
            )
        mock_impl.side_effect = _success_impl

        # T-1 merges clean, T-2 and T-3 conflict
        mock_merge.side_effect = [True, False, False]

        issues = [
            {"id": "T-1", "title": "[P] Task A", "type": "task"},
            {"id": "T-2", "title": "[P] Task B", "type": "task"},
            {"id": "T-3", "title": "[P] Task C", "type": "task"},
        ]
        result = asyncio.run(
            run_phase_7(state, issues, "/tmp/wt")
        )
        assert len(result.merge_conflicts) == 2
        conflict_ids = {mc.issue_id for mc in result.merge_conflicts}
        assert conflict_ids == {"T-2", "T-3"}
        # All conflicts should have needs-manual-merge status
        assert all(mc.status == "needs-manual-merge" for mc in result.merge_conflicts)
        # Abort should be called for each failed merge
        assert mock_abort.call_count == 2

    @patch("dark_factory.pipeline._abort_merge")
    @patch("dark_factory.pipeline.merge_parallel_branch")
    @patch("dark_factory.worktree.remove_parallel_worktree")
    @patch("dark_factory.worktree.create_parallel_worktree")
    @patch("dark_factory.pipeline._implement_single_task")
    def test_clean_branch_still_merged(
        self,
        mock_impl,
        mock_create_wt,
        mock_remove_wt,
        mock_merge,
        mock_abort,
        state,
    ):
        """The clean branch should still be merged even when others conflict."""
        from dark_factory.worktree import ParallelWorktree

        mock_create_wt.side_effect = [
            ParallelWorktree(f"/wt-{i}", f"parallel/T-{i}", state.repo_root)
            for i in range(1, 4)
        ]

        async def _success_impl(st, issue, wt, sysprompt, *, dry_run=False):
            return ImplementationResult(
                issue_id=issue["id"], success=True, output="ok", cost_usd=0.0,
            )
        mock_impl.side_effect = _success_impl

        # T-1 clean, T-2 conflict, T-3 clean
        mock_merge.side_effect = [True, False, True]

        issues = [
            {"id": "T-1", "title": "[P] Task A", "type": "task"},
            {"id": "T-2", "title": "[P] Task B", "type": "task"},
            {"id": "T-3", "title": "[P] Task C", "type": "task"},
        ]
        result = asyncio.run(
            run_phase_7(state, issues, "/tmp/wt")
        )
        assert len(result.merge_conflicts) == 1
        assert result.merge_conflicts[0].issue_id == "T-2"
        # merge_parallel_branch called 3 times (all succeeded so all attempted)
        assert mock_merge.call_count == 3


class TestErrorIsolationMocked:
    """WARNING 4: Mock-based error isolation -- actual failures, not dry-run."""

    @patch("dark_factory.pipeline._implement_single_task")
    def test_one_failure_others_complete(self, mock_impl, state):
        """One task raising an exception should not prevent others from completing."""
        call_count = 0

        async def _impl_side_effect(st, issue, wt, sysprompt, *, dry_run=False):
            nonlocal call_count
            call_count += 1
            if issue["id"] == "T-1":
                raise RuntimeError("Agent crashed")
            return ImplementationResult(
                issue_id=issue["id"], success=True, output="ok", cost_usd=0.1,
            )

        mock_impl.side_effect = _impl_side_effect

        # Sequential path (no markers) -- each task calls _implement_single_task
        # But sequential path doesn't catch exceptions per-task, so use parallel path
        issues = [
            {"id": "T-1", "title": "[P] Task A (will fail)", "type": "task"},
            {"id": "T-2", "title": "[P] Task B", "type": "task"},
            {"id": "T-3", "title": "[P] Task C", "type": "task"},
        ]

        with patch("dark_factory.worktree.create_parallel_worktree") as mock_cwt, \
             patch("dark_factory.worktree.remove_parallel_worktree"):
            from dark_factory.worktree import ParallelWorktree
            mock_cwt.side_effect = [
                ParallelWorktree(f"/wt-{i}", f"parallel/T-{i}", state.repo_root)
                for i in range(1, 4)
            ]

            result = asyncio.run(
                run_phase_7(state, issues, "/tmp/wt")
            )

        assert len(result.results) == 3
        # T-1 failed
        t1 = next(r for r in result.results if r.issue_id == "T-1")
        assert t1.success is False
        assert "Agent crashed" in t1.output
        # T-2 and T-3 succeeded
        t2 = next(r for r in result.results if r.issue_id == "T-2")
        t3 = next(r for r in result.results if r.issue_id == "T-3")
        assert t2.success is True
        assert t3.success is True

    @patch("dark_factory.pipeline._implement_single_task")
    def test_dependent_task_skipped_when_dependency_fails(self, mock_impl, state):
        """Task depending on a failed task should be skipped."""
        async def _impl_side_effect(st, issue, wt, sysprompt, *, dry_run=False):
            if issue["id"] == "T-1":
                raise RuntimeError("Task 1 failed")
            return ImplementationResult(
                issue_id=issue["id"], success=True, output="ok", cost_usd=0.1,
            )

        mock_impl.side_effect = _impl_side_effect

        issues = [
            {"id": "T-1", "title": "[P] Task A (will fail)", "type": "task"},
            {"id": "T-2", "title": "[P] Task B (independent)", "type": "task"},
            {"id": "T-3", "title": "[depends: 1] Task C (depends on A)", "type": "task"},
        ]

        with patch("dark_factory.worktree.create_parallel_worktree") as mock_cwt, \
             patch("dark_factory.worktree.remove_parallel_worktree"):
            from dark_factory.worktree import ParallelWorktree
            mock_cwt.side_effect = [
                ParallelWorktree(f"/wt-{i}", f"parallel/T-{i}", state.repo_root)
                for i in range(1, 3)  # Only 2 worktrees needed (T-1, T-2 in wave 1)
            ]

            result = asyncio.run(
                run_phase_7(state, issues, "/tmp/wt")
            )

        assert len(result.results) == 3
        # T-1 failed
        t1 = next(r for r in result.results if r.issue_id == "T-1")
        assert t1.success is False
        # T-2 independent -- should succeed
        t2 = next(r for r in result.results if r.issue_id == "T-2")
        assert t2.success is True
        # T-3 depends on T-1 -- should be skipped
        t3 = next(r for r in result.results if r.issue_id == "T-3")
        assert t3.success is False
        assert "skipped_dependency_failed" in t3.output

    @patch("dark_factory.pipeline._implement_single_task")
    def test_independent_task_unaffected_by_failure_in_same_wave(self, mock_impl, state):
        """An independent task in the same wave as a failing task should still succeed."""
        async def _impl_side_effect(st, issue, wt, sysprompt, *, dry_run=False):
            if issue["id"] == "T-2":
                raise RuntimeError("T-2 exploded")
            return ImplementationResult(
                issue_id=issue["id"], success=True, output="ok", cost_usd=0.1,
            )

        mock_impl.side_effect = _impl_side_effect

        issues = [
            {"id": "T-1", "title": "[P] Task A", "type": "task"},
            {"id": "T-2", "title": "[P] Task B (will fail)", "type": "task"},
            {"id": "T-3", "title": "[P] Task C", "type": "task"},
        ]

        with patch("dark_factory.worktree.create_parallel_worktree") as mock_cwt, \
             patch("dark_factory.worktree.remove_parallel_worktree"):
            from dark_factory.worktree import ParallelWorktree
            mock_cwt.side_effect = [
                ParallelWorktree(f"/wt-{i}", f"parallel/T-{i}", state.repo_root)
                for i in range(1, 4)
            ]

            result = asyncio.run(
                run_phase_7(state, issues, "/tmp/wt")
            )

        # T-1 and T-3 should succeed despite T-2 failing
        t1 = next(r for r in result.results if r.issue_id == "T-1")
        t3 = next(r for r in result.results if r.issue_id == "T-3")
        assert t1.success is True
        assert t3.success is True
        # T-2 failed
        t2 = next(r for r in result.results if r.issue_id == "T-2")
        assert t2.success is False


class TestPhase7TDDSectionInjection:
    """Verify Phase 7 injects TDD section into prompt when visible tests exist."""

    @patch("dark_factory.agents.call_implement")
    def test_tdd_section_in_prompt_when_visible_tests_populated(
        self, mock_call_implement, state, tmp_path
    ):
        """When state.visible_test_paths has entries, the implementation prompt
        includes the TDD section with test file content."""
        test_dir = tmp_path / "tests"
        test_dir.mkdir()
        visible_test = test_dir / "visible_tests_test-1.py"
        visible_test.write_text(
            "def test_login_happy_path():\n"
            "    assert True\n"
        )
        state.visible_test_paths = [str(visible_test)]

        captured_prompt = None

        async def _capture_prompt(
            prompt, *, worktree_path, system_prompt, is_off_rails, dry_run=False
        ):
            nonlocal captured_prompt
            captured_prompt = prompt
            return "[mock] implementation done", 0.0, 0

        mock_call_implement.side_effect = _capture_prompt

        issues = [{"id": "T-1", "title": "Add login", "type": "task"}]
        asyncio.run(
            run_phase_7(state, issues, str(tmp_path))
        )

        assert captured_prompt is not None
        assert "## TDD Tests (make these pass)" in captured_prompt
        assert "Do NOT modify these test files" in captured_prompt
        assert "def test_login_happy_path():" in captured_prompt

    @patch("dark_factory.agents.call_implement")
    def test_no_tdd_section_when_visible_tests_empty(
        self, mock_call_implement, state, tmp_path
    ):
        """When state.visible_test_paths is empty, no TDD section in prompt."""
        assert state.visible_test_paths == []

        captured_prompt = None

        async def _capture_prompt(
            prompt, *, worktree_path, system_prompt, is_off_rails, dry_run=False
        ):
            nonlocal captured_prompt
            captured_prompt = prompt
            return "[mock] implementation done", 0.0, 0

        mock_call_implement.side_effect = _capture_prompt

        issues = [{"id": "T-1", "title": "Add login", "type": "task"}]
        asyncio.run(
            run_phase_7(state, issues, str(tmp_path))
        )

        assert captured_prompt is not None
        assert "## TDD Tests" not in captured_prompt
