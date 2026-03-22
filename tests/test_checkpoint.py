"""Tests for dark_factory.checkpoint: Phase 5 human checkpoint."""

from __future__ import annotations

import pytest

from dark_factory.checkpoint import (
    Decision,
    PlanSummary,
    parse_decision,
    parse_spec_requirements,
    parse_tasks,
    render_checkpoint,
)


@pytest.fixture
def plan():
    return PlanSummary(
        external_ref="jira:SDLC-123",
        summary="Add caching layer",
        branch="dark-factory/sdlc-123",
        worktree_path="/tmp/repo-df-sdlc-123",
        review_result="PASS",
        spec_overview="Adds Redis caching to the API layer.",
        requirements=["Cache GET responses", "Cache invalidation on PUT"],
        tasks=["Add Redis client wrapper", "Integrate cache middleware", "Add cache tests"],
    )


class TestRenderCheckpoint:
    def test_contains_source(self, plan):
        output = render_checkpoint(plan)
        assert "jira:SDLC-123" in output
        assert "Add caching layer" in output

    def test_contains_branch(self, plan):
        output = render_checkpoint(plan)
        assert "dark-factory/sdlc-123" in output

    def test_contains_requirements_count(self, plan):
        output = render_checkpoint(plan)
        assert "Requirements (2)" in output

    def test_contains_task_count(self, plan):
        output = render_checkpoint(plan)
        assert "Implementation Plan (3 tasks)" in output

    def test_contains_options(self, plan):
        output = render_checkpoint(plan)
        assert "(A) Approve" in output
        assert "(B) Adjust" in output
        assert "(C) Abort" in output

    def test_dry_run_shows_no_options(self, plan):
        output = render_checkpoint(plan, dry_run=True)
        assert "Dry run complete" in output
        assert "(A) Approve" not in output

    def test_contains_review_result(self, plan):
        output = render_checkpoint(plan)
        assert "PASS" in output

    def test_contains_spec_overview(self, plan):
        output = render_checkpoint(plan)
        assert "Redis caching" in output


class TestParseDecision:
    @pytest.mark.parametrize("input_val", ["A", "a", "approve", "Approve"])
    def test_approve(self, input_val):
        assert parse_decision(input_val) == Decision.APPROVE

    @pytest.mark.parametrize("input_val", ["B", "b", "adjust", "modify"])
    def test_modify(self, input_val):
        assert parse_decision(input_val) == Decision.MODIFY

    @pytest.mark.parametrize("input_val", ["C", "c", "abort"])
    def test_abort(self, input_val):
        assert parse_decision(input_val) == Decision.ABORT

    def test_whitespace_handled(self):
        assert parse_decision("  a  ") == Decision.APPROVE

    def test_invalid_raises(self):
        with pytest.raises(ValueError, match="Unrecognized"):
            parse_decision("maybe")


class TestParseSpecRequirements:
    def test_extracts_h3_headings(self):
        spec = "### Cache GET responses\nSome detail\n### Cache invalidation\n"
        result = parse_spec_requirements(spec)
        assert result == ["Cache GET responses", "Cache invalidation"]

    def test_skips_structural_h2(self):
        spec = "## Requirements\n### Actual requirement\n## Scenarios\n"
        result = parse_spec_requirements(spec)
        assert result == ["Actual requirement"]

    def test_includes_non_structural_h2(self):
        spec = "## User authentication\ndetails\n"
        result = parse_spec_requirements(spec)
        assert result == ["User authentication"]

    def test_empty_spec(self):
        assert parse_spec_requirements("") == []


class TestParseTasks:
    def test_numbered_list(self):
        text = "1. Add Redis client\n2. Add middleware\n3. Write tests\n"
        result = parse_tasks(text)
        assert result == ["Add Redis client", "Add middleware", "Write tests"]

    def test_bullet_list(self):
        text = "- Add client\n- Add middleware\n"
        result = parse_tasks(text)
        assert result == ["Add client", "Add middleware"]

    def test_checkbox_list(self):
        text = "- [ ] Pending task\n- [x] Done task\n"
        result = parse_tasks(text)
        assert result == ["Pending task", "Done task"]

    def test_with_parallel_markers(self):
        text = "1. [P] Task A\n2. [P] Task B\n3. Task C\n"
        result = parse_tasks(text)
        assert result == ["[P] Task A", "[P] Task B", "Task C"]

    def test_empty_text(self):
        assert parse_tasks("") == []

    def test_ignores_non_task_lines(self):
        text = "# Tasks\n\nSome description.\n\n1. Actual task\n"
        result = parse_tasks(text)
        assert result == ["Actual task"]
