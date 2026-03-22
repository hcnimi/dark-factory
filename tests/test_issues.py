"""Tests for dark_factory.issues: Phase 6 beads issue creation."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from dark_factory.issues import (
    CreatedIssue,
    CyclicDependencyError,
    InvalidDependencyError,
    ParsedTask,
    PhaseResult,
    TaskDAG,
    create_issues,
    parse_tasks_md,
    parse_tasks_md_with_deps,
)


class TestParseTasksMd:
    def test_numbered_list(self):
        text = "1. Add Redis client\n2. Add middleware\n3. Write tests\n"
        assert parse_tasks_md(text) == [
            "Add Redis client",
            "Add middleware",
            "Write tests",
        ]

    def test_bullet_list(self):
        text = "- Add client\n- Add middleware\n"
        assert parse_tasks_md(text) == ["Add client", "Add middleware"]

    def test_checkbox_list(self):
        text = "- [ ] Pending\n- [x] Done\n"
        assert parse_tasks_md(text) == ["Pending", "Done"]

    def test_empty(self):
        assert parse_tasks_md("") == []

    def test_mixed_content(self):
        text = "# Tasks\n\nOverview text\n\n1. First task\n2. Second task\n"
        assert parse_tasks_md(text) == ["First task", "Second task"]


class TestCreateIssuesDryRun:
    """Dry-run mode must not invoke subprocess."""

    def test_single_task_dry_run(self):
        result = create_issues(
            source_id="SDLC-123",
            summary="Add caching",
            external_ref="jira:SDLC-123",
            tasks=["Implement cache"],
            dry_run=True,
        )
        assert result.epic_id is None
        assert len(result.issues) == 1
        assert result.issues[0].issue_type == "task"

    def test_multi_task_creates_epic(self):
        result = create_issues(
            source_id="SDLC-123",
            summary="Add caching",
            external_ref="jira:SDLC-123",
            tasks=["Task A", "Task B", "Task C"],
            dry_run=True,
        )
        assert result.epic_id is not None
        # 1 epic + 3 tasks
        assert len(result.issues) == 4
        assert result.issues[0].issue_type == "epic"
        for issue in result.issues[1:]:
            assert issue.issue_type == "task"
            assert issue.parent_id == result.epic_id

    def test_two_tasks_no_epic(self):
        result = create_issues(
            source_id="TEST-1",
            summary="Small change",
            external_ref="jira:TEST-1",
            tasks=["Task A", "Task B"],
            dry_run=True,
        )
        assert result.epic_id is None
        assert len(result.issues) == 2

    def test_empty_tasks(self):
        result = create_issues(
            source_id="TEST-1",
            summary="Nothing",
            external_ref="jira:TEST-1",
            tasks=[],
            dry_run=True,
        )
        assert result.epic_id is None
        assert result.issues == []

    def test_dry_run_ids_are_deterministic(self):
        """Same title should produce the same dry-run ID."""
        r1 = create_issues("X-1", "S", "x:1", ["Do thing"], dry_run=True)
        r2 = create_issues("X-1", "S", "x:1", ["Do thing"], dry_run=True)
        assert r1.issues[0].id == r2.issues[0].id


class TestCreateIssuesLive:
    """Live mode invokes subprocess — mock it."""

    @patch("dark_factory.issues.subprocess.run")
    def test_single_task_calls_bd(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps({"id": "BD-42", "title": "Implement cache"}),
        )

        result = create_issues(
            source_id="SDLC-1",
            summary="Cache",
            external_ref="jira:SDLC-1",
            tasks=["Implement cache"],
        )

        assert mock_run.called
        assert result.issues[0].id == "BD-42"

    @patch("dark_factory.issues.subprocess.run")
    def test_bd_failure_raises(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=1,
            stderr="not found",
        )

        with pytest.raises(RuntimeError, match="bd command failed"):
            create_issues("X-1", "S", "x:1", ["task"])

    @patch("dark_factory.issues.subprocess.run")
    def test_bd_non_json_raises(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="not json at all",
        )

        with pytest.raises(RuntimeError, match="non-JSON"):
            create_issues("X-1", "S", "x:1", ["task"])

    @patch("dark_factory.issues.subprocess.run")
    def test_multi_task_creates_epic_then_children(self, mock_run):
        call_count = 0

        def fake_run(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return MagicMock(
                returncode=0,
                stdout=json.dumps({"id": f"BD-{call_count}", "title": "t"}),
            )

        mock_run.side_effect = fake_run

        result = create_issues(
            source_id="S-1",
            summary="Big feature",
            external_ref="jira:S-1",
            tasks=["A", "B", "C"],
        )

        # 1 epic create + 3 task creates = 4 calls
        assert mock_run.call_count == 4
        assert result.epic_id == "BD-1"
        assert len(result.issues) == 4


class TestParseTasksMdWithDeps:
    """Tests for the dependency-aware task parser."""

    def test_parallel_marker(self):
        text = "1. [P] Add endpoint\n"
        result = parse_tasks_md_with_deps(text)
        assert len(result) == 1
        assert result[0] == ParsedTask(index=1, title="Add endpoint", dependencies=[])

    def test_depends_single(self):
        text = "1. [P] Setup\n2. [depends: 1] Wire up\n"
        result = parse_tasks_md_with_deps(text)
        assert result[1] == ParsedTask(index=2, title="Wire up", dependencies=[1])

    def test_depends_multiple(self):
        text = "1. [P] A\n2. [P] B\n3. [depends: 1, 2] Combine\n"
        result = parse_tasks_md_with_deps(text)
        assert result[2] == ParsedTask(index=3, title="Combine", dependencies=[1, 2])

    def test_no_marker_first_task(self):
        """First task with no marker is independent."""
        text = "1. Setup database\n"
        result = parse_tasks_md_with_deps(text)
        assert result[0] == ParsedTask(index=1, title="Setup database", dependencies=[])

    def test_no_marker_subsequent(self):
        """Task 2 with no marker defaults to depending on task 1."""
        text = "1. First step\n2. Second step\n"
        result = parse_tasks_md_with_deps(text)
        assert result[0].dependencies == []
        assert result[1].dependencies == [1]

    def test_mixed_formats(self):
        """Mix of [P], [depends:], and unmarked tasks."""
        text = (
            "1. [P] Independent A\n"
            "2. [P] Independent B\n"
            "3. [depends: 1, 2] Merge step\n"
            "4. Sequential after merge\n"
        )
        result = parse_tasks_md_with_deps(text)
        assert result[0] == ParsedTask(1, "Independent A", [])
        assert result[1] == ParsedTask(2, "Independent B", [])
        assert result[2] == ParsedTask(3, "Merge step", [1, 2])
        # No marker on task 4 → depends on task 3
        assert result[3] == ParsedTask(4, "Sequential after merge", [3])

    def test_checkbox_with_markers(self):
        text = "- [ ] [P] Setup infra\n- [ ] [depends: 1] Deploy app\n"
        result = parse_tasks_md_with_deps(text)
        assert result[0] == ParsedTask(1, "Setup infra", [])
        assert result[1] == ParsedTask(2, "Deploy app", [1])

    def test_numbered_with_markers(self):
        text = "1. [P] Create schema\n2. [depends: 1] Run migration\n"
        result = parse_tasks_md_with_deps(text)
        assert result[0] == ParsedTask(1, "Create schema", [])
        assert result[1] == ParsedTask(2, "Run migration", [1])


class TestTaskDAG:
    """Tests for dependency graph resolution."""

    def test_all_parallel_single_wave(self):
        dag = TaskDAG()
        for i in range(1, 4):
            dag.add_task(ParsedTask(index=i, title=f"Task {i}", dependencies=[]))
        waves = dag.resolve_waves()
        assert waves == [[1, 2, 3]]

    def test_linear_chain(self):
        """1→2→3→4 produces 4 waves of 1 task each."""
        dag = TaskDAG()
        dag.add_task(ParsedTask(1, "A", []))
        dag.add_task(ParsedTask(2, "B", [1]))
        dag.add_task(ParsedTask(3, "C", [2]))
        dag.add_task(ParsedTask(4, "D", [3]))
        waves = dag.resolve_waves()
        assert waves == [[1], [2], [3], [4]]

    def test_diamond_dependency(self):
        """Diamond: 1→(2,3)→4 produces 3 waves."""
        dag = TaskDAG()
        dag.add_task(ParsedTask(1, "Root", []))
        dag.add_task(ParsedTask(2, "Left", [1]))
        dag.add_task(ParsedTask(3, "Right", [1]))
        dag.add_task(ParsedTask(4, "Join", [2, 3]))
        waves = dag.resolve_waves()
        assert waves == [[1], [2, 3], [4]]

    def test_cycle_detection(self):
        dag = TaskDAG()
        dag.add_task(ParsedTask(1, "A", [2]))
        dag.add_task(ParsedTask(2, "B", [1]))
        with pytest.raises(CyclicDependencyError):
            dag.resolve_waves()

    def test_invalid_reference(self):
        dag = TaskDAG()
        dag.add_task(ParsedTask(1, "A", [99]))
        with pytest.raises(InvalidDependencyError):
            dag.resolve_waves()

    def test_self_reference(self):
        dag = TaskDAG()
        dag.add_task(ParsedTask(1, "A", [1]))
        with pytest.raises(CyclicDependencyError):
            dag.resolve_waves()

    def test_map_to_issues(self):
        dag = TaskDAG()
        dag.add_task(ParsedTask(1, "A", []))
        dag.add_task(ParsedTask(2, "B", [1]))
        dag.add_task(ParsedTask(3, "C", [1]))

        task_to_issue = {1: "BD-10", 2: "BD-20", 3: "BD-30"}
        result = dag.map_to_issues(task_to_issue)
        assert result == [["BD-10"], ["BD-20", "BD-30"]]

    def test_mixed_waves(self):
        """[1:P, 2:P, 3:depends 1,2, 4:P, 5:depends 3] → [[1,2,4],[3],[5]]"""
        dag = TaskDAG()
        dag.add_task(ParsedTask(1, "A", []))
        dag.add_task(ParsedTask(2, "B", []))
        dag.add_task(ParsedTask(3, "C", [1, 2]))
        dag.add_task(ParsedTask(4, "D", []))
        dag.add_task(ParsedTask(5, "E", [3]))
        waves = dag.resolve_waves()
        assert waves == [[1, 2, 4], [3], [5]]
