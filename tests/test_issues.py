"""Tests for dark_factory.issues: Phase 6 issue creation."""

from __future__ import annotations

import pytest

from dark_factory.issues import (
    CreatedIssue,
    CyclicDependencyError,
    InvalidDependencyError,
    ParsedTask,
    PhaseResult,
    TaskDAG,
    _reset_task_counter,
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

    def test_ignores_indented_sub_bullets(self):
        text = "- Task A\n  - Sub-bullet\n- Task B\n"
        assert parse_tasks_md(text) == ["Task A", "Task B"]

    def test_ignores_deeply_indented_sub_bullets(self):
        text = "- Task A\n    - Deep sub-bullet\n      - Even deeper\n- Task B\n"
        assert parse_tasks_md(text) == ["Task A", "Task B"]

    def test_checkbox_with_sub_bullets(self):
        text = "- [ ] Task A\n  - detail\n- [x] Task B\n"
        assert parse_tasks_md(text) == ["Task A", "Task B"]


class TestCreateIssues:
    """Internal ID generation — no subprocess."""

    def setup_method(self):
        _reset_task_counter()

    def test_single_task(self):
        result = create_issues(
            source_id="SDLC-123",
            summary="Add caching",
            external_ref="jira:SDLC-123",
            tasks=["Implement cache"],
        )
        assert result.epic_id is None
        assert len(result.issues) == 1
        assert result.issues[0].issue_type == "task"
        assert result.issues[0].id == "TASK-1"

    def test_multi_task_creates_epic(self):
        result = create_issues(
            source_id="SDLC-123",
            summary="Add caching",
            external_ref="jira:SDLC-123",
            tasks=["Task A", "Task B", "Task C"],
        )
        assert result.epic_id == "TASK-1"
        assert len(result.issues) == 4
        assert result.issues[0].issue_type == "epic"
        for i, issue in enumerate(result.issues[1:], start=2):
            assert issue.issue_type == "task"
            assert issue.parent_id == "TASK-1"
            assert issue.id == f"TASK-{i}"

    def test_two_tasks_no_epic(self):
        result = create_issues(
            source_id="TEST-1",
            summary="Small change",
            external_ref="jira:TEST-1",
            tasks=["Task A", "Task B"],
        )
        assert result.epic_id is None
        assert len(result.issues) == 2

    def test_empty_tasks(self):
        result = create_issues(
            source_id="TEST-1",
            summary="Nothing",
            external_ref="jira:TEST-1",
            tasks=[],
        )
        assert result.epic_id is None
        assert result.issues == []

    def test_ids_are_deterministic_after_reset(self):
        _reset_task_counter()
        r1 = create_issues("X-1", "S", "x:1", ["Do thing"])
        _reset_task_counter()
        r2 = create_issues("X-1", "S", "x:1", ["Do thing"])
        assert r1.issues[0].id == r2.issues[0].id

    def test_dry_run_same_behavior(self):
        """dry_run flag is kept for API compat but behavior is identical."""
        result = create_issues("X-1", "S", "x:1", ["task"], dry_run=True)
        assert result.issues[0].id == "TASK-1"

    def test_reset_counter(self):
        create_issues("X-1", "S", "x:1", ["task"])
        _reset_task_counter()
        result = create_issues("X-2", "S", "x:2", ["task"])
        assert result.issues[0].id == "TASK-1"


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

    def test_ignores_indented_sub_bullets(self):
        text = "- [P] Task A\n  - Sub-bullet\n- [depends: 1] Task B\n"
        result = parse_tasks_md_with_deps(text)
        assert len(result) == 2
        assert result[0] == ParsedTask(index=1, title="Task A", dependencies=[])
        assert result[1] == ParsedTask(index=2, title="Task B", dependencies=[1])

    def test_sub_bullets_dont_affect_task_indexing(self):
        text = "- [P] Task A\n  - Sub-bullet 1\n  - Sub-bullet 2\n- Task B\n"
        result = parse_tasks_md_with_deps(text)
        assert len(result) == 2
        assert result[1] == ParsedTask(index=2, title="Task B", dependencies=[1])


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
